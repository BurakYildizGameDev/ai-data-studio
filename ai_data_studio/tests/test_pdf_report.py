# -*- coding: utf-8 -*-
"""Enterprise PDF Report generation tests."""
from __future__ import annotations

import re
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

        # Pipeline raporunun GERCEK sekli (orchestrator ciktisiyla birebir).
        # Eski fixture "validation" / "privacy" / "raw_rows" anahtarlarini
        # kullaniyordu; bu anahtarlar hicbir zaman uretilmiyordu, yani testler
        # yanlis bir sozlesmeyi dogruluyordu.
        self.report = {
            "rows_in": 210,
            "rows_out": 200,
            "retention_pct": 95.2,
            "removed_total": 10,
            "stages": [
                {"stage": "Duplicate removal", "rows_before": 210,
                 "rows_after": 210, "removed": 0, "removed_pct": 0.0},
                {"stage": "Schema bounds", "rows_before": 210,
                 "rows_after": 204, "removed": 6, "removed_pct": 2.86},
                {"stage": "Z-score outliers", "rows_before": 204,
                 "rows_after": 200, "removed": 4, "removed_pct": 1.96},
            ],
            "business_rules": [
                {"rule": "credit_score <= 850", "status": "applied",
                 "violations": 0, "violation_pct": 0.0},
            ],
            "correlations": [
                {"pair": ["annual_income", "credit_score"],
                 "expected_sign": "positive", "min_r": 0.3,
                 "method": "pearson", "actual_r": 0.71, "pass": True},
            ],
            "schema_conformance": {"missing_columns": [], "extra_columns": [],
                                   "column_order_matches": True},
            "privacy_audit": {
                "has_reference_data": True,
                "overall_privacy_status": "NO_ISSUES_FOUND",
                "distribution_divergence": 0.038,
                "dcr": {"mean_dcr": 0.384, "min_dcr": 0.11,
                        "risk_level": "LOW", "identical_matches": 0},
                "nndr": {"mean_nndr": 0.891, "median_nndr": 0.9,
                         "memorization_risk": "LOW", "low_ratio_count": 0},
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


class TestPDFReportTruthfulness(unittest.TestCase):
    """Rapor yalnizca OLCULEN seyleri beyan etmeli.

    Onceki surum report["validation"] / report["privacy"] / report["raw_rows"]
    okuyordu. Pipeline bu anahtarlarin hicbirini uretmez, dolayisiyla her
    rapor sifir sayimlar ve sabit 0.38 / 0.89 / 0.04 gizlilik degerleriyle
    doluyor, yaninda kosulsuz "PASSED" / "Low Risk" basiyordu.
    """

    def setUp(self):
        from reportlab import rl_config
        # Sikistirmasiz yaz: metin PDF'e duz "(...) Tj" olarak girer ve
        # disari bagimlilik olmadan okunabilir.
        self._old_compression = rl_config.pageCompression
        rl_config.pageCompression = 0

        self.temp_dir = tempfile.TemporaryDirectory()
        self.out_pdf = Path(self.temp_dir.name) / "r.pdf"
        n = 20
        self.df = pd.DataFrame({
            "value_a": np.arange(n, dtype=float),
            "label": ["row-%d" % i for i in range(n)],
        })
        self.schema = SchemaContract(
            domain="probe", row_count_target=n,
            columns=[ColumnSpec(name="value_a", type="float"),
                     ColumnSpec(name="label", type="string")],
        )

    def tearDown(self):
        from reportlab import rl_config
        rl_config.pageCompression = self._old_compression
        self.temp_dir.cleanup()

    def _text(self, report) -> str:
        generate_pdf_report(dataframe=self.df, schema=self.schema, report=report,
                            output_path=self.out_pdf, job_id=1, domain="probe",
                            enforce_pro=False)
        data = self.out_pdf.read_bytes().decode("latin-1")
        return " ".join(re.findall(r"\(([^)]*)\)", data))

    def test_missing_privacy_audit_invents_no_metrics(self):
        text = self._text({"rows_in": 20, "rows_out": 20})
        for fabricated in ("0.380", "0.890", "0.040",
                           "Zero Overfitting", "Excellent Privacy"):
            self.assertNotIn(fabricated, text)
        self.assertIn("No privacy audit", text)

    def test_failing_business_rules_are_not_reported_as_passed(self):
        text = self._text({
            "rows_in": 20, "rows_out": 20,
            "business_rules": [{"rule": "x <= y", "status": "applied",
                                "violations": 7, "violation_pct": 35.0}],
        })
        self.assertIn("7 violations", text)
        self.assertIn("FAILED", text)
        self.assertIn("REVIEW REQUIRED", text)

    def test_failing_correlation_is_not_reported_as_passed(self):
        text = self._text({
            "rows_in": 20, "rows_out": 20,
            "correlations": [{"pair": ["a", "b"], "expected_sign": "positive",
                              "min_r": 0.3, "actual_r": 0.01, "pass": False}],
        })
        self.assertIn("FAILED", text)

    def test_clean_run_is_reported_as_passed(self):
        text = self._text({
            "rows_in": 20, "rows_out": 20,
            "business_rules": [{"rule": "x <= y", "status": "applied",
                                "violations": 0, "violation_pct": 0.0}],
            "correlations": [{"pair": ["a", "b"], "expected_sign": "positive",
                              "min_r": 0.3, "actual_r": 0.8, "pass": True}],
            "schema_conformance": {"missing_columns": [], "extra_columns": []},
        })
        self.assertIn("PASSED", text)
        self.assertNotIn("REVIEW REQUIRED", text)

    def test_unmeasured_checks_say_not_measured(self):
        text = self._text({"rows_in": 20, "rows_out": 20})
        self.assertIn("NOT MEASURED", text)
        self.assertNotIn("REVIEW REQUIRED", text)

    def test_real_stage_names_reach_the_scorecard(self):
        text = self._text({
            "rows_in": 20, "rows_out": 18,
            "stages": [{"stage": "Schema bounds", "rows_before": 20,
                        "rows_after": 18, "removed": 2, "removed_pct": 10.0}],
        })
        self.assertIn("Schema bounds", text)
        self.assertIn("Rows In", text)

    def test_auditor_risk_level_drives_the_privacy_verdict(self):
        text = self._text({
            "rows_in": 20, "rows_out": 20,
            "privacy_audit": {
                "has_reference_data": True,
                "distribution_divergence": 0.4,
                "dcr": {"mean_dcr": 0.01, "risk_level": "HIGH"},
                "nndr": {"mean_nndr": 0.1, "memorization_risk": "HIGH"},
            },
        })
        self.assertIn("HIGH RISK", text)
        self.assertNotIn("LOW RISK", text)

    def test_banner_does_not_draw_a_legal_conclusion(self):
        """Arac neyi bildigini beyan eder; transfer izni verilip verilmeyecegini degil."""
        text = self._text({"rows_in": 20, "rows_out": 20})
        self.assertNotIn("Cleared for cross-border transfer", text)
        self.assertIn("determination for the data controller", text)

    def test_banner_states_when_no_privacy_audit_ran(self):
        text = self._text({"rows_in": 20, "rows_out": 20})
        self.assertIn("No privacy audit was run", text)

    def test_banner_states_when_an_audit_did_run(self):
        text = self._text({
            "rows_in": 20, "rows_out": 20,
            "privacy_audit": {"has_reference_data": True,
                              "dcr": {"mean_dcr": 0.4, "risk_level": "LOW"}},
        })
        self.assertIn("A privacy audit was run", text)
        self.assertNotIn("No privacy audit was run", text)

    def test_footer_does_not_claim_certification(self):
        text = self._text({"rows_in": 20, "rows_out": 20})
        self.assertNotIn("Provenance Certified", text)
        self.assertIn("Provenance Declaration", text)


class TestHeatmapRendering(unittest.TestCase):
    """Isi haritasinin pyplot global durumuna dokunmadigini dogrular.

    _render_correlation_heatmap hem PipelineWorker thread'inden hem de
    "Export PDF" dugmesiyle Tk ana thread'inden cagriliyor. pyplot'in figure
    yoneticisi (Gcf) thread-safe degil; plt.title/tight_layout "gecerli
    figure"e etki ettigi icin iki kosu cakisabiliyordu.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        n = 60
        self.df = pd.DataFrame({
            "a": np.random.random(n),
            "b": np.random.random(n),
            "c": np.random.random(n),
        })
        self.schema = SchemaContract(
            domain="probe", row_count_target=n,
            columns=[ColumnSpec(name=c, type="float") for c in ("a", "b", "c")])
        self.report = {"rows_in": n, "rows_out": n}

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_rendering_leaves_no_pyplot_figures(self):
        import matplotlib.pyplot as plt
        from ai_data_studio.reporting.pdf_report import _render_correlation_heatmap

        plt.close("all")
        before = len(plt.get_fignums())
        for _ in range(10):
            self.assertIsNotNone(_render_correlation_heatmap(self.df))
        self.assertEqual(len(plt.get_fignums()), before)

    def test_failed_savefig_does_not_leak_a_figure(self):
        import matplotlib.figure
        import matplotlib.pyplot as plt
        from ai_data_studio.reporting.pdf_report import _render_correlation_heatmap

        plt.close("all")
        before = len(plt.get_fignums())
        with mock.patch.object(matplotlib.figure.Figure, "savefig",
                               side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                _render_correlation_heatmap(self.df)
        self.assertEqual(len(plt.get_fignums()), before)

    def test_single_numeric_column_skips_the_heatmap(self):
        from ai_data_studio.reporting.pdf_report import _render_correlation_heatmap

        one = pd.DataFrame({"a": np.arange(10.0), "label": ["x"] * 10})
        self.assertIsNone(_render_correlation_heatmap(one))

    def test_concurrent_report_generation_succeeds(self):
        """Iki thread ayni anda rapor yazabilmeli."""
        import threading

        errors = []
        produced = []
        lock = threading.Lock()

        def worker(idx):
            try:
                out = self.tmp / ("concurrent_%d.pdf" % idx)
                generate_pdf_report(
                    dataframe=self.df, schema=self.schema, report=self.report,
                    output_path=out, job_id=idx, domain="job-%d" % idx,
                    enforce_pro=False)
                with lock:
                    produced.append(out.stat().st_size)
            except Exception as exc:
                with lock:
                    errors.append("%s: %s" % (type(exc).__name__, exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(produced), 6)
        self.assertTrue(all(size > 0 for size in produced))

if __name__ == "__main__":
    unittest.main()
