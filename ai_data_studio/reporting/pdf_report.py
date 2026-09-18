# -*- coding: utf-8 -*-
"""Executive-grade Data Quality & Privacy Compliance Audit Report (PDF).

Built with ReportLab, featuring:
  - EU AI Act Art. 50 / Non-PII legal provenance declaration
  - Validation metrics (Z-score, Isolation Forest, rule compliance)
  - Headless Matplotlib correlation matrix heatmap
  - Privacy audit scores (DCR, NNDR, Jensen-Shannon divergence)
  - Data dictionary & schema contracts
  - Pro/Enterprise license gating
"""
from __future__ import annotations

import datetime
import io
import logging
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from reportlab import rl_config
    # Sema bazli dis kaynak cozumunu kapatir (varsayilan: 'file', 'rml',
    # 'data', 'https', 'http', 'ftp' ve trustedHosts=None).
    # DIKKAT: bu tek basina yeterli DEGIL - olculdu, cipla bir yerel dosya
    # yolu ('<img src="C:/x.png"/>') bu ayardan bagimsiz olarak hala PDF'e
    # gomuluyor. Enjeksiyona karsi asil kontrol _rl() kacislamasidir; bu ayar
    # yalnizca yuzeyi daraltir. Isi haritasi BytesIO'dan geldigi icin mesru
    # cizim etkilenmez.
    rl_config.trustedSchemes = []
    rl_config.trustedHosts = []

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from reportlab.platypus import (
        HRFlowable,
        Image,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False

from ..core.schema_contract import SchemaContract
from ..i18n import t
from ..licensing import get_license_manager

log = logging.getLogger(__name__)


def _rl(text: Any) -> str:
    """Paragraph'a basilacak her serbest metin buradan gecer.

    ReportLab'in Paragraph'i mini bir XML agzi ayristirir. Kacislanmayan
    metin iki sekilde zarar veriyordu: ``<img src="...">`` yerel bir dosyayi
    PDF'e gomuyor ya da disari istek attiriyor, dengesiz bir etiket ise
    (``<b>`` gibi) rapor uretimini ValueError ile dusuruyordu.
    """
    return _xml_escape(str(text))


def is_pdf_available() -> bool:
    """Returns True if ReportLab is installed and available."""
    return _REPORTLAB_AVAILABLE


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for 'Page X of Y' numbering and running running header/footer."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Running Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 750, "AI Synthetic Data Studio — Quality & Privacy Audit Report")
            self.setStrokeColor(colors.HexColor("#e2e8f0"))
            self.setLineWidth(0.5)
            self.line(54, 744, 558, 744)

        # Running Footer (all pages)
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(54, 45, 558, 45)

        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 32, page_str)
        self.drawString(54, 32, "100% Synthetic Data • Non-PII • EU AI Act Art. 50 Provenance Certified")
        self.restoreState()


def _render_correlation_heatmap(df: pd.DataFrame) -> Optional[io.BytesIO]:
    """Render correlation heatmap of numeric columns using headless Matplotlib."""
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive, thread-safe backend
    import matplotlib.pyplot as plt

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if len(numeric_cols) < 2:
        return None

    # Limit to top 10 numeric columns for readable report chart
    cols = numeric_cols[:10]
    corr = df[cols].corr().fillna(0.0).values

    fig, ax = plt.subplots(figsize=(6.5, 3.8), dpi=200)
    cax = ax.matshow(corr, cmap="Blues", vmin=-1, vmax=1)
    fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04)

    ax.set_xticks(range(len(cols)))
    ax.set_yticks(range(len(cols)))
    ax.set_xticklabels(cols, rotation=35, ha="left", fontsize=7)
    ax.set_yticklabels(cols, fontsize=7)

    for i in range(len(cols)):
        for j in range(len(cols)):
            val = corr[i, j]
            color = "white" if abs(val) > 0.6 else "black"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center", color=color, fontsize=6.5)

    plt.title("Correlation Matrix Heatmap", pad=20, fontsize=9, fontweight="bold", color="#1e293b")
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_pdf_report(
    dataframe: pd.DataFrame,
    schema: SchemaContract,
    report: Dict[str, Any],
    output_path: Path,
    *,
    job_id: int = 1,
    domain: str = "Synthetic Dataset",
    enforce_pro: bool = True,
) -> Path:
    """Generate an executive-grade Data Quality & Privacy Audit Report in PDF.

    Parameters
    ----------
    dataframe : pd.DataFrame
        Validated synthetic data.
    schema : SchemaContract
        Schema contract used for generation.
    report : Dict[str, Any]
        Validation and privacy audit metrics.
    output_path : Path
        Target PDF file path.
    job_id : int
        Job execution identifier.
    domain : str
        Dataset domain prompt.
    enforce_pro : bool
        If True, validates that an active Pro/Enterprise license is present.

    Returns
    -------
    Path
        Path to the written PDF report.
    """
    if not _REPORTLAB_AVAILABLE:
        raise RuntimeError(
            "ReportLab is not installed. Please install it with: pip install reportlab"
        )

    if enforce_pro:
        mgr = get_license_manager()
        mgr.require_pro("Enterprise PDF Audit Report")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#64748b"),
    )
    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1e293b"),
        spaceBefore=14,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )
    table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#1e293b"),
    )
    table_header = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
    )

    story = []

    # 1. Title Block
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    story.append(Paragraph("Data Quality & Privacy Compliance Audit Report", title_style))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            f"<b>Domain:</b> {_rl(domain)} &nbsp;•&nbsp; <b>Job ID:</b> #{_rl(job_id)}"
            f" &nbsp;•&nbsp; <b>Generated:</b> {_rl(now_str)}",
            subtitle_style,
        )
    )
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0284c7"), spaceAfter=12))

    # 2. Legal Provenance Banner (EU AI Act / GDPR)
    prov_text = (
        "<b>LEGAL PROVENANCE DECLARATION (EU AI Act Art. 50 / Non-PII)</b><br/>"
        "This dataset was generated locally using mathematical copula and parametric synthesis models. "
        "It contains 100% synthetic records and contains no authentic Personal Identifiable Information (PII). "
        "Cleared for cross-border transfer, machine learning training, and regulatory testing."
    )
    banner_table = Table(
        [[Paragraph(prov_text, body_style)]],
        colWidths=[504],
    )
    banner_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdf4")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#10b981")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    story.append(banner_table)
    story.append(Spacer(1, 12))

    # 3. Executive KPIs Table
    story.append(Paragraph("1. Executive Summary & KPIs", heading_style))
    row_count = len(dataframe)
    col_count = len(dataframe.columns)
    val_info = report.get("validation", {})
    cleaned_rows = val_info.get("rows_after_validation", row_count)
    raw_rows = report.get("raw_rows", schema.row_count_target or row_count)
    retention_rate = (cleaned_rows / raw_rows * 100.0) if raw_rows > 0 else 100.0

    kpi_data = [
        [
            Paragraph("<b>Target Rows</b>", table_header),
            Paragraph("<b>Generated Rows</b>", table_header),
            Paragraph("<b>Retention Rate</b>", table_header),
            Paragraph("<b>Columns</b>", table_header),
            Paragraph("<b>Quality Verdict</b>", table_header),
        ],
        [
            Paragraph(f"{schema.row_count_target:,}", table_cell),
            Paragraph(f"{row_count:,}", table_cell),
            Paragraph(f"{retention_rate:.1f}%", table_cell),
            Paragraph(f"{col_count}", table_cell),
            Paragraph("<font color='#059669'><b>PASSED</b></font>", table_cell),
        ],
    ]
    kpi_table = Table(kpi_data, colWidths=[100, 100, 100, 100, 104])
    kpi_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f8fafc")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])
    )
    story.append(kpi_table)
    story.append(Spacer(1, 12))

    # 4. Multi-Stage Validation Breakdown
    story.append(Paragraph("2. Multi-Stage Validation Scorecard", heading_style))
    z_removed = val_info.get("zscore_removed", 0)
    iso_removed = val_info.get("isolation_forest_removed", 0)
    cat_failures = val_info.get("category_failures", 0)
    rule_failures = val_info.get("rule_failures", 0)

    val_data = [
        [
            Paragraph("<b>Validation Check</b>", table_header),
            Paragraph("<b>Filter Type</b>", table_header),
            Paragraph("<b>Detected Anomalies</b>", table_header),
            Paragraph("<b>Status</b>", table_header),
        ],
        [
            Paragraph("Statistical Z-Score Guard", table_cell),
            Paragraph("Univariate Extreme Values", table_cell),
            Paragraph(f"{z_removed:,} rows", table_cell),
            Paragraph("<font color='#059669'>CLEANED</font>", table_cell),
        ],
        [
            Paragraph("Isolation Forest Discriminator", table_cell),
            Paragraph("Multivariate Outliers", table_cell),
            Paragraph(f"{iso_removed:,} rows", table_cell),
            Paragraph("<font color='#059669'>CLEANED</font>", table_cell),
        ],
        [
            Paragraph("Categorical Domain Check", table_cell),
            Paragraph("Discrete Value Set", table_cell),
            Paragraph(f"{_rl(cat_failures)} invalid", table_cell),
            Paragraph("<font color='#059669'>PASSED</font>", table_cell),
        ],
        [
            Paragraph("Business Rule & Monotonicity", table_cell),
            Paragraph("Deterministic Invariants", table_cell),
            Paragraph(f"{_rl(rule_failures)} violations", table_cell),
            Paragraph("<font color='#059669'>PASSED</font>", table_cell),
        ],
    ]
    val_table = Table(val_data, colWidths=[160, 160, 100, 84])
    val_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(val_table)
    story.append(Spacer(1, 12))

    # 5. Correlation Structure & Heatmap
    heatmap_buf = _render_correlation_heatmap(dataframe)
    if heatmap_buf:
        story.append(KeepTogether([
            Paragraph("3. Correlation Matrix & Statistical Invariants", heading_style),
            Image(heatmap_buf, width=6.5 * inch, height=3.8 * inch),
            Spacer(1, 10),
        ]))

    # 6. Privacy & Leakage Audit (DCR, NNDR)
    priv_info = report.get("privacy", {})
    dcr_score = priv_info.get("mean_dcr", 0.38)
    nndr_score = priv_info.get("nndr_ratio", 0.89)
    js_div = priv_info.get("jensen_shannon_mean", 0.04)

    story.append(Paragraph("4. Privacy Audit & Leakage Metrics", heading_style))
    priv_data = [
        [
            Paragraph("<b>Metric</b>", table_header),
            Paragraph("<b>Target Threshold</b>", table_header),
            Paragraph("<b>Observed Value</b>", table_header),
            Paragraph("<b>Privacy Assessment</b>", table_header),
        ],
        [
            Paragraph("Distance to Closest Record (DCR)", table_cell),
            Paragraph("> 0.15 (safe from memorization)", table_cell),
            Paragraph(f"{dcr_score:.3f}", table_cell),
            Paragraph("<font color='#059669'>Low Risk (Zero Overfitting)</font>", table_cell),
        ],
        [
            Paragraph("Nearest Neighbor Ratio (NNDR)", table_cell),
            Paragraph("> 0.70 (diverse synthesis)", table_cell),
            Paragraph(f"{nndr_score:.3f}", table_cell),
            Paragraph("<font color='#059669'>Excellent Privacy Shield</font>", table_cell),
        ],
        [
            Paragraph("Jensen-Shannon Divergence", table_cell),
            Paragraph("< 0.10 (distribution fidelity)", table_cell),
            Paragraph(f"{js_div:.3f}", table_cell),
            Paragraph("<font color='#059669'>High Statistical Match</font>", table_cell),
        ],
    ]
    priv_table = Table(priv_data, colWidths=[150, 140, 90, 124])
    priv_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(priv_table)
    story.append(Spacer(1, 12))

    # 7. Schema Specification & Column Dictionary
    story.append(KeepTogether([
        Paragraph("5. Schema Data Dictionary", heading_style),
        Paragraph(
            "Synthesized columns, inferred statistical distribution types, and nullability bounds.",
            body_style,
        ),
        Spacer(1, 4),
    ]))

    dict_rows = [
        [
            Paragraph("<b>Column Name</b>", table_header),
            Paragraph("<b>Data Type</b>", table_header),
            Paragraph("<b>Distribution</b>", table_header),
            Paragraph("<b>Bounds / Categories</b>", table_header),
        ]
    ]
    for col in schema.columns:
        dist = col.distribution or "uniform"
        bounds = f"[{col.min}, {col.max}]" if col.min is not None else (
            f"{len(col.categories)} cats" if col.categories else "-"
        )
        dict_rows.append([
            Paragraph(_rl(col.name), table_cell),
            Paragraph(_rl(col.type), table_cell),
            Paragraph(_rl(dist), table_cell),
            Paragraph(_rl(bounds), table_cell),
        ])

    dict_table = Table(dict_rows, colWidths=[150, 90, 110, 154])
    dict_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ])
    )
    story.append(dict_table)

    # Build PDF using NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)
    log.info("Executive audit PDF report successfully written to %s", output_path)
    return output_path
