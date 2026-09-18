# -*- coding: utf-8 -*-
"""Enterprise PDF Report generation tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from ai_data_studio.core.schema_contract import ColumnSpec, SchemaContract
from ai_data_studio.licensing.manager import ProFeatureRequiredError
from ai_data_studio.reporting import generate_pdf_report, is_pdf_available


class TestPDFReportGeneration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.out_pdf = Path(self.temp_dir.name) / "audit_report.pdf"

        # Realistic synthetic dataset
        np.random.seed(42)
        n = 200
        income = np.random.normal(65000, 15000, n).clip(20000, 150000)
        credit = (300 + (income / 150000) * 500 + np.random.normal(0, 30, n)).clip(300, 850)
        self.df = pd.DataFrame({
            "customer_id": [f"CUST-{i:05d}" for i in range(n)],
            "annual_income": income,
            "credit_score": credit.astype(int),
            "account_balance": np.random.exponential(5000, n),
            "tier": np.random.choice(["bronze", "silver", "gold"], n),
            "is_default": np.random.choice([0, 1], n, p=[0.92, 0.08]),
        })

        self.schema = SchemaContract(
            domain="Financial Credit & Risk Scoring",
            row_count_target=n,
            columns=[
                ColumnSpec(name="customer_id", type="string"),
                ColumnSpec(name="annual_income", type="float", min=20000, max=150000, distribution="normal"),
                ColumnSpec(name="credit_score", type="int", min=300, max=850),
                ColumnSpec(name="account_balance", type="float", min=0, max=50000),
                ColumnSpec(name="tier", type="category", categories=["bronze", "silver", "gold"]),
                ColumnSpec(name="is_default", type="bool", target_ratio=0.08),
            ],
        )

        self.report = {
            "raw_rows": 210,
            "validation": {
                "rows_after_validation": 200,
                "zscore_removed": 6,
                "isolation_forest_removed": 4,
                "category_failures": 0,
                "rule_failures": 0,
            },
            "privacy": {
                "mean_dcr": 0.384,
                "nndr_ratio": 0.891,
                "jensen_shannon_mean": 0.038,
            },
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pdf_availability(self):
        """ReportLab must be installed and available."""
        self.assertTrue(is_pdf_available())

    def test_pro_gate_blocks_community_tier(self):
        """Generating PDF with enforce_pro=True without Pro license raises error."""
        with mock.patch("ai_data_studio.reporting.pdf_report.get_license_manager") as mock_get_mgr:
            mock_mgr = mock.MagicMock()
            mock_mgr.require_pro.side_effect = ProFeatureRequiredError("Audit PDF")
            mock_get_mgr.return_value = mock_mgr

            with self.assertRaises(ProFeatureRequiredError):
                generate_pdf_report(
                    self.df, self.schema, self.report, self.out_pdf,
                    domain="credit", enforce_pro=True
                )

    def test_pdf_generation_success(self):
        """Complete PDF report builds with headers, charts, and tables."""
        pdf_path = generate_pdf_report(
            self.df,
            self.schema,
            self.report,
            self.out_pdf,
            job_id=42,
            domain="Financial Credit & Risk Scoring",
            enforce_pro=False,
        )

        self.assertTrue(pdf_path.exists())
        self.assertGreater(pdf_path.stat().st_size, 5000)  # Contains real binary PDF content

        # Check standard PDF header
        with open(pdf_path, "rb") as f:
            header = f.read(5)
            self.assertEqual(header, b"%PDF-")

    def test_pdf_generation_with_active_pro_license(self):
        """When an active Pro license is installed, enforce_pro=True passes."""
        with mock.patch("ai_data_studio.reporting.pdf_report.get_license_manager") as mock_get_mgr:
            mock_mgr = mock.MagicMock()
            # require_pro does not raise
            mock_mgr.require_pro.return_value = None
            mock_get_mgr.return_value = mock_mgr

            pdf_path = generate_pdf_report(
                self.df,
                self.schema,
                self.report,
                self.out_pdf,
                job_id=101,
                domain="Banking",
                enforce_pro=True,
            )
            self.assertTrue(pdf_path.exists())
            self.assertGreater(pdf_path.stat().st_size, 5000)



class TestPDFParagraphInjection(unittest.TestCase):
    """Serbest metnin ReportLab isaretlemesi olarak yorumlanmadigini dogrular.

    ``domain`` LLM yanitindan veya paylasilan bir sema JSON'undan gelir ve
    dogrudan bir Paragraph'a basiliyordu. Kacislanmadan:
      * ``<img src="...">`` yerel bir dosyayi PDF'e gomuyordu,
      * dengesiz bir etiket rapor uretimini ValueError ile dusuruyordu.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.out_pdf = self.tmp / "report.pdf"

        self.secret = self.tmp / "secret.png"
        try:
            from PIL import Image as PILImage
            PILImage.new("RGB", (400, 400), (0, 255, 0)).save(self.secret)
            self.have_pillow = True
        except Exception:
            self.have_pillow = False

        # Tek sayisal kolon: korelasyon isi haritasi cizilmez
        # (_render_correlation_heatmap en az iki sayisal kolon ister), boylece
        # PDF'te gorulen her /XObject enjeksiyondan gelmis demektir.
        n = 30
        self.df = pd.DataFrame({
            "value_a": np.arange(n, dtype=float),
            "label": ["row-%d" % i for i in range(n)],
        })
        self.schema = SchemaContract(
            domain="placeholder",
            row_count_target=n,
            columns=[
                ColumnSpec(name="value_a", type="float"),
                ColumnSpec(name="label", type="string"),
            ],
        )
        self.report = {"raw_rows": n, "validation": {"rows_after_validation": n}}

    def tearDown(self):
        self.temp_dir.cleanup()

    def _build(self, domain: str) -> bytes:
        generate_pdf_report(
            dataframe=self.df, schema=self.schema, report=self.report,
            output_path=self.out_pdf, job_id=1, domain=domain,
            enforce_pro=False,
        )
        return self.out_pdf.read_bytes()

    def test_img_tag_in_domain_does_not_embed_local_file(self):
        """Gomulen gorsel PDF'e bir /XObject ekler; kacislanmis metin eklememeli."""
        if not self.have_pillow:
            self.skipTest("Pillow yok")
        baseline = self._build("Quarterly Sales")
        self.assertNotIn(b"/XObject", baseline)

        hostile = 'Sales <img src="%s" width="200" height="200"/>' % (
            str(self.secret).replace("\\", "/"))
        produced = self._build(hostile)
        self.assertNotIn(b"/XObject", produced)

    def test_unbalanced_markup_in_domain_does_not_crash(self):
        for hostile in ("Sales <b>Q4", "Sales </para><para>", "Sales <font color='red'>"):
            with self.subTest(domain=hostile):
                self.assertTrue(self._build(hostile).startswith(b"%PDF"))

    def test_bare_angle_brackets_and_ampersand_survive(self):
        self.assertTrue(self._build("revenue < 500 & profit > 0").startswith(b"%PDF"))

    def test_remote_url_in_domain_is_not_fetched(self):
        """Disari istek denemesi rapor uretimini dusurmemeli."""
        produced = self._build(
            'Sales <img src="http://attacker.invalid/beacon.png" width="9" height="9"/>')
        self.assertTrue(produced.startswith(b"%PDF"))
        self.assertNotIn(b"/XObject", produced)

if __name__ == "__main__":
    unittest.main()
