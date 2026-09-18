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


def _verdict(ok: Optional[bool], good: str, bad: str) -> str:
    """Gercek olcume dayali verdict uretir; ``None`` = olculmedi.

    Rapor hukuki bir beyandir. Olculmemis ya da basarisiz bir denetim icin
    "PASSED" basmak beyanin tamamini gecersiz kilar, o yuzden burada sabit
    kodlanmis bir sonuc yok.
    """
    if ok is None:
        return "<font color='#b45309'><b>NOT MEASURED</b></font>"
    color = "#059669" if ok else "#dc2626"
    return "<font color='%s'><b>%s</b></font>" % (color, good if ok else bad)


def _risk_verdict(level: Optional[str]) -> str:
    """Gizlilik denetcisinin kendi risk seviyesini verdict'e cevirir.

    Denetci taban cizgisini de hesaba katarak LOW/MEDIUM/HIGH/UNKNOWN
    uretir; bunu rapor icinde yeniden esik karsilastirmasiyla turetmek
    denetcinin kararini golgelerdi.
    """
    if not level or level == "UNKNOWN":
        return "<font color='#b45309'><b>NOT MEASURED</b></font>"
    colors_by_level = {"LOW": "#059669", "MEDIUM": "#b45309", "HIGH": "#dc2626"}
    return "<font color='%s'><b>%s RISK</b></font>" % (
        colors_by_level.get(level, "#b45309"), level)


def _metric_text(value: Optional[float], fmt: str = "%.3f") -> str:
    """Olculmemis metrik yerine sayi uydurmaz."""
    return "—" if value is None else fmt % value


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
        # "Certified" degil: bu belge bir beyandir, bir belgelendirme degil.
        self.drawString(54, 32, "100% Synthetic Data • Non-PII • EU AI Act Art. 50 Provenance Declaration")
        self.restoreState()


def _render_correlation_heatmap(df: pd.DataFrame) -> Optional[io.BytesIO]:
    """Render correlation heatmap of numeric columns using headless Matplotlib.

    pyplot KULLANILMAZ. pyplot global bir figure yoneticisi (Gcf) tutar ve
    thread-safe degildir; bu fonksiyon hem PipelineWorker thread'inden
    (run_pipeline -> _write_outputs) hem de "Export PDF" dugmesiyle Tk ana
    thread'inden cagriliyor. plt.title/plt.tight_layout "gecerli figure"e
    etki ettigi icin iki kosu cakistiginda basliklar birbirine karisabilir.
    Figure/FigureCanvas nesneleri yereldir, o yuzden yaris kosulu olusmaz.

    Ayrica matplotlib.use("Agg") calisma aninda cagrilmaz: surecin backend'ini
    worker thread'den degistirmek GUI tarafini etkileyebiliyordu. Agg burada
    dogrudan FigureCanvasAgg ile secilir.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if len(numeric_cols) < 2:
        return None

    # Limit to top 10 numeric columns for readable report chart
    cols = numeric_cols[:10]
    corr = df[cols].corr().fillna(0.0).values

    fig = Figure(figsize=(6.5, 3.8), dpi=200)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
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

    ax.set_title("Correlation Matrix Heatmap", pad=20, fontsize=9,
                 fontweight="bold", color="#1e293b")
    fig.tight_layout()

    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", bbox_inches="tight")
    finally:
        # savefig patlarsa figure sizmasin: eski surumde plt.close(fig)
        # hata yolunda hic calismiyordu.
        fig.clf()
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

    # Serh banner'i da gizlilik denetiminin durumuna bakiyor, o yuzden
    # rapor alanlari story kurulmadan once cozulur.
    privacy_audit: Dict[str, Any] = report.get("privacy_audit") or {}

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
    # Arac neyi BILDIGINI beyan eder, hukuki sonuc cikarmaz. Onceki metin
    # "Cleared for cross-border transfer ... and regulatory testing" diyordu:
    # bu bir hukuki degerlendirmedir ve uretim araci bunu veremez. Gizlilik
    # ifadesi de kosulsuzdu; artik denetimin kosup kosmadigina bagli.
    audit_sentence = {
        "measured": "A privacy audit was run against reference data for this "
                    "dataset; its metrics are in section 4.",
        "no_reference": "A privacy audit was requested but no reference dataset "
                        "was available, so memorisation metrics could not be "
                        "computed.",
        "none": "No privacy audit was run for this dataset, so no memorisation "
                "or leakage measurement supports this declaration.",
    }[("measured" if privacy_audit.get("has_reference_data")
       else "no_reference" if privacy_audit else "none")]

    prov_text = (
        "<b>PROVENANCE DECLARATION (EU AI Act Art. 50)</b><br/>"
        "This dataset was generated locally from a schema contract using "
        "mathematical copula and parametric synthesis models. No source records "
        "were copied into the output. " + _rl(audit_sentence) + " "
        "Whether the dataset may be transferred, published or relied on for a "
        "given purpose is a determination for the data controller, not for this "
        "tool."
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

    # Pipeline raporunun GERCEK alanlari. Onceki surum report["validation"],
    # report["privacy"] ve report["raw_rows"] okuyordu; bu anahtarlarin ucu de
    # hicbir zaman uretilmiyordu, dolayisiyla her rapor sifirlar ve sabit
    # varsayilanlarla dolduruluyordu.
    stages: List[Dict[str, Any]] = list(report.get("stages") or [])
    rules_info: List[Dict[str, Any]] = list(report.get("business_rules") or [])
    corr_info: List[Dict[str, Any]] = list(report.get("correlations") or [])
    conformance: Dict[str, Any] = report.get("schema_conformance") or {}
    raw_rows = report.get("rows_in")
    cleaned_rows = report.get("rows_out", row_count)
    retention_pct = report.get("retention_pct")
    if retention_pct is None and raw_rows:
        retention_pct = cleaned_rows / raw_rows * 100.0

    rule_violations = sum(int(r.get("violations") or 0) for r in rules_info
                          if r.get("status") == "applied")
    corr_checked = [c for c in corr_info if c.get("pass") is not None]
    corr_failed = [c for c in corr_checked if not c.get("pass")]
    conformance_ok = (bool(conformance)
                      and not conformance.get("missing_columns")
                      and not conformance.get("extra_columns"))

    # Toplu kalite karari: olculmeyen hicbir seyi "gecti" saymaz.
    checks = [c for c in (
        (rule_violations == 0) if rules_info else None,
        (not corr_failed) if corr_checked else None,
        conformance_ok if conformance else None,
    ) if c is not None]
    quality_ok = all(checks) if checks else None

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
            Paragraph(_metric_text(retention_pct, "%.1f%%"), table_cell),
            Paragraph(f"{col_count}", table_cell),
            Paragraph(_verdict(quality_ok, "PASSED", "REVIEW REQUIRED"), table_cell),
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
    # Skorkart pipeline'in GERCEKTEN kostugu asamalardan kurulur. Sabit dort
    # satir yazmak, o asama hic kosmamis olsa bile "CLEANED/PASSED" beyan
    # ediyordu; asama adlari ayrica i18n'lidir, o yuzden ada gore eslesme yok.
    val_data = [
        [
            Paragraph("<b>Validation Stage</b>", table_header),
            Paragraph("<b>Rows In</b>", table_header),
            Paragraph("<b>Removed</b>", table_header),
            Paragraph("<b>Rows Out</b>", table_header),
        ]
    ]
    if stages:
        for st in stages:
            before = st.get("rows_before")
            after = st.get("rows_after")
            removed = int(st.get("removed") or 0)
            val_data.append([
                Paragraph(_rl(st.get("stage", "—")), table_cell),
                Paragraph(_metric_text(before, "%d"), table_cell),
                Paragraph(f"{removed:,}", table_cell),
                Paragraph(_metric_text(after, "%d"), table_cell),
            ])
    else:
        val_data.append([
            Paragraph(_verdict(None, "", ""), table_cell),
            Paragraph("—", table_cell),
            Paragraph("—", table_cell),
            Paragraph("—", table_cell),
        ])

    val_table = Table(val_data, colWidths=[220, 90, 90, 104])
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
    story.append(Spacer(1, 10))

    contract_data = [
        [
            Paragraph("<b>Contract Check</b>", table_header),
            Paragraph("<b>Observed</b>", table_header),
            Paragraph("<b>Status</b>", table_header),
        ],
        [
            Paragraph("Business rules & invariants", table_cell),
            Paragraph(f"{rule_violations:,} violations" if rules_info else "—", table_cell),
            Paragraph(_verdict((rule_violations == 0) if rules_info else None,
                               "PASSED", "FAILED"), table_cell),
        ],
        [
            Paragraph("Correlation targets", table_cell),
            Paragraph(f"{len(corr_checked) - len(corr_failed)}/{len(corr_checked)} met"
                      if corr_checked else "—", table_cell),
            Paragraph(_verdict((not corr_failed) if corr_checked else None,
                               "PASSED", "FAILED"), table_cell),
        ],
        [
            Paragraph("Schema conformance", table_cell),
            Paragraph(
                ("%d missing, %d extra" % (len(conformance.get("missing_columns") or []),
                                           len(conformance.get("extra_columns") or [])))
                if conformance else "—", table_cell),
            Paragraph(_verdict(conformance_ok if conformance else None,
                               "PASSED", "FAILED"), table_cell),
        ],
    ]
    contract_table = Table(contract_data, colWidths=[220, 160, 124])
    contract_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(contract_table)
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
    # UYDURMA VARSAYILAN YOK. Onceki surum report["privacy"] okuyordu - boyle
    # bir anahtar hic uretilmiyor - ve bulunamayinca 0.38 / 0.89 / 0.04
    # basiyordu. Yani her rapor, gizlilik denetimi hic kosmamis olsa bile
    # olculmus gibi gorunen uc sayi ve "Low Risk" beyani tasiyordu.
    dcr_info: Dict[str, Any] = privacy_audit.get("dcr") or {}
    nndr_info: Dict[str, Any] = privacy_audit.get("nndr") or {}
    dcr_score = dcr_info.get("mean_dcr")
    nndr_score = nndr_info.get("mean_nndr")
    js_div = privacy_audit.get("distribution_divergence")
    has_reference = bool(privacy_audit.get("has_reference_data"))

    story.append(Paragraph("4. Privacy Audit & Leakage Metrics", heading_style))
    if not privacy_audit:
        story.append(Paragraph(
            "<b>No privacy audit was performed for this run.</b> Distance to Closest "
            "Record, Nearest Neighbour Distance Ratio and distribution divergence "
            "require a reference dataset; run the pipeline with the privacy audit "
            "enabled to populate this section.",
            body_style))
        story.append(Spacer(1, 12))
    else:
        if not has_reference:
            story.append(Paragraph(
                "No reference dataset was supplied, so memorisation metrics could "
                "not be computed for this run.", body_style))
            story.append(Spacer(1, 4))
        priv_data = [
            [
                Paragraph("<b>Metric</b>", table_header),
                Paragraph("<b>Reference Threshold</b>", table_header),
                Paragraph("<b>Observed Value</b>", table_header),
                Paragraph("<b>Auditor Assessment</b>", table_header),
            ],
            [
                Paragraph("Distance to Closest Record (DCR)", table_cell),
                Paragraph("higher is safer (baseline-relative)", table_cell),
                Paragraph(_metric_text(dcr_score), table_cell),
                Paragraph(_risk_verdict(dcr_info.get("risk_level")), table_cell),
            ],
            [
                Paragraph("Nearest Neighbour Ratio (NNDR)", table_cell),
                Paragraph("higher is safer (baseline-relative)", table_cell),
                Paragraph(_metric_text(nndr_score), table_cell),
                Paragraph(_risk_verdict(nndr_info.get("memorization_risk")), table_cell),
            ],
            [
                Paragraph("Jensen-Shannon Divergence", table_cell),
                Paragraph("0 = identical, 1 = disjoint (not a privacy guarantee)", table_cell),
                Paragraph(_metric_text(js_div), table_cell),
                Paragraph("<font color='#475569'><b>INFORMATIONAL</b></font>"
                          if js_div is not None else _verdict(None, "", ""),
                          table_cell),
            ],
        ]
        priv_table = Table(priv_data, colWidths=[150, 160, 80, 114])
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
