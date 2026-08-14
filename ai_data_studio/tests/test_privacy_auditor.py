"""Privacy & HIPAA Safe Harbor denetim modülü testleri."""
from __future__ import annotations

import unittest
import numpy as np
import pandas as pd

from ai_data_studio.core import validator
from ai_data_studio.core.schema_contract import SchemaContract
from ai_data_studio.core.privacy_auditor import (
    DCRResult,
    NNDRResult,
    HIPAAAuditResult,
    PrivacyAuditReport,
    PrivacyAuditor,
    shift_clinical_dates,
    cap_hipaa_age,
    audit_dataset_privacy,
)


class TestDCRAndNNDR(unittest.TestCase):
    """En Yakın Kayda Mesafe (DCR) ve En Yakın Komşu Mesafe Oranı (NNDR) testleri."""

    def setUp(self):
        self.rng = np.random.default_rng(42)
        n = 100
        self.ref_df = pd.DataFrame({
            "age": self.rng.integers(20, 70, n),
            "income": self.rng.normal(50000, 15000, n),
            "score": self.rng.uniform(0, 100, n),
        })

    def test_exact_memorization_detected(self):
        """Referans veriyle birebir örtüşen kopyalanmış sentetik veri ezberleme riski vermelidir."""
        # Sentetik veri referans verinin doğrudan kopyası olsun
        synth_df = self.ref_df.copy()

        auditor = PrivacyAuditor()
        dcr = auditor.compute_dcr(synth_df, self.ref_df)

        self.assertAlmostEqual(dcr.min_distance, 0.0, places=4)
        self.assertEqual(dcr.exact_matches_count, len(synth_df))
        self.assertTrue(dcr.memorization_risk)

    def test_safe_synthetic_data_no_memorization(self):
        """Ayrık sentetik veri güvenli DCR ve NNDR üretmelidir."""
        synth_df = pd.DataFrame({
            "age": self.rng.integers(20, 70, 80) + 0.5,
            "income": self.rng.normal(50000, 15000, 80) + 50.0,
            "score": self.rng.uniform(0, 100, 80) + 0.25,
        })

        auditor = PrivacyAuditor()
        dcr = auditor.compute_dcr(synth_df, self.ref_df)
        nndr = auditor.compute_nndr(synth_df, self.ref_df)

        self.assertGreater(dcr.min_distance, 0.0)
        self.assertEqual(dcr.exact_matches_count, 0)
        self.assertFalse(dcr.memorization_risk)

        self.assertGreater(nndr.mean_ratio, 0.0)
        self.assertLessEqual(nndr.mean_ratio, 1.0)
        self.assertFalse(nndr.overfitting_risk)

    def test_categorical_and_missing_values_handled(self):
        """Kategorik ve eksik değer içeren verilerde DCR güvenle hesaplanmalıdır."""
        ref = self.ref_df.copy()
        ref["city"] = ["Ankara" if i % 2 == 0 else "Istanbul" for i in range(len(ref))]
        ref.loc[0, "income"] = np.nan

        synth = ref.copy()
        auditor = PrivacyAuditor()
        dcr = auditor.compute_dcr(synth, ref)
        self.assertIsInstance(dcr, DCRResult)


class TestHIPAAIdentifierScanner(unittest.TestCase):
    """HIPAA Safe Harbor 18 Doğrudan Tanımlayıcı tarama testleri."""

    def test_scanner_flags_direct_identifiers(self):
        """Doğrudan kimlik belirten kolonlar (TCKN, hasta adı, mrn, eposta) yakalanmalıdır."""
        df = pd.DataFrame({
            "patient_name": ["Ahmet Yılmaz", "Ayşe Demir"],
            "tckn": ["12345678901", "98765432109"],
            "mrn": ["MRN-101", "MRN-102"],
            "email": ["ahmet@test.com", "ayse@test.com"],
            "blood_pressure": [120, 130],
        })

        auditor = PrivacyAuditor()
        audit = auditor.scan_hipaa_identifiers(df)

        self.assertFalse(audit.is_hipaa_safe)
        self.assertIn("patient_name", audit.flagged_columns)
        self.assertIn("tckn", audit.flagged_columns)
        self.assertIn("mrn", audit.flagged_columns)
        self.assertIn("email", audit.flagged_columns)
        self.assertNotIn("blood_pressure", audit.flagged_columns)

    def test_clean_clinical_dataset_passes(self):
        """Anonim klinik veri seti HIPAA Safe Harbor testinden başarıyla geçmelidir."""
        df = pd.DataFrame({
            "age": [45, 52, 63, 71],
            "systolic_bp": [120, 135, 140, 128],
            "hba1c": [5.6, 6.2, 7.1, 5.9],
            "treatment_group": ["A", "B", "A", "B"],
        })

        auditor = PrivacyAuditor()
        audit = auditor.scan_hipaa_identifiers(df)

        self.assertTrue(audit.is_hipaa_safe)
        self.assertEqual(len(audit.flagged_columns), 0)


class TestClinicalDateShifting(unittest.TestCase):
    """Klinik tarih öteleme (Date Shifting) testleri."""

    def setUp(self):
        self.df = pd.DataFrame({
            "patient_id": ["P1", "P1", "P2", "P2"],
            "admission_date": [
                "2023-01-10",
                "2023-03-15",
                "2023-05-01",
                "2023-06-20",
            ],
            "discharge_date": [
                "2023-01-15",
                "2023-03-22",
                "2023-05-10",
                "2023-06-25",
            ],
        })

    def test_date_shifting_preserves_intervals(self):
        """Öteleme sonrası hastanın iki tarihi arasındaki gün farkı (interval) birebir korunmalıdır."""
        # Orijinal farklar
        orig_adm = pd.to_datetime(self.df["admission_date"])
        orig_dis = pd.to_datetime(self.df["discharge_date"])
        orig_stay = (orig_dis - orig_adm).dt.days

        shifted = shift_clinical_dates(
            self.df,
            patient_id_col="patient_id",
            date_cols=["admission_date", "discharge_date"],
            min_shift_days=30,
            max_shift_days=365,
            seed=42,
        )

        shifted_adm = pd.to_datetime(shifted["admission_date"])
        shifted_dis = pd.to_datetime(shifted["discharge_date"])
        shifted_stay = (shifted_dis - shifted_adm).dt.days

        # Kalış süreleri tam olarak aynı kalmalıdır!
        pd.testing.assert_series_equal(orig_stay, shifted_stay)

        # Ancak tarihler orijinalinden farklı olmalıdır!
        self.assertFalse((orig_adm == shifted_adm).any())

    def test_deterministic_date_shifting(self):
        """Aynı rastgele seed ile yapılan öteleme birebir aynı sonucu vermelidir."""
        shift1 = shift_clinical_dates(
            self.df, date_columns=["admission_date"], patient_id_col="patient_id",
            min_shift_days=30, max_shift_days=365, seed=123
        )
        shift2 = shift_clinical_dates(
            self.df, date_columns=["admission_date"], patient_id_col="patient_id",
            min_shift_days=30, max_shift_days=365, seed=123
        )
        pd.testing.assert_frame_equal(shift1, shift2)


class TestHIPAAAgeCapping(unittest.TestCase):
    """HIPAA 45 CFR § 164.514(b) 89 yaş üstü kümeleme testleri."""

    def test_age_greater_than_89_capped(self):
        """89'dan büyük yaşlar HIPAA gereğince 90 olarak sınırlandırılmalıdır."""
        df = pd.DataFrame({
            "patient_id": [1, 2, 3, 4, 5],
            "age": [25, 88, 89, 90, 102],
        })

        capped = cap_hipaa_age(df, age_col="age", max_age=89, capped_val=90)

        expected = [25, 88, 89, 90, 90]
        self.assertEqual(capped["age"].tolist(), expected)


class TestPrivacyAuditorEndToEnd(unittest.TestCase):
    """Uçtan uca PrivacyAuditor ve Markdown raporlama testleri."""

    def test_full_privacy_audit_report(self):
        rng = np.random.default_rng(100)
        ref_df = pd.DataFrame({
            "age": rng.integers(20, 80, 50),
            "cholesterol": rng.normal(200, 30, 50),
        })
        synth_df = pd.DataFrame({
            "age": rng.integers(20, 80, 50),
            "cholesterol": rng.normal(200, 30, 50),
        })

        report = audit_dataset_privacy(synth_df, ref_df)
        self.assertIsInstance(report, PrivacyAuditReport)

        md = report.to_markdown()
        self.assertIn("HIPAA Safe Harbor", md)
        self.assertIn("DCR (Distance to Closest Record)", md)
        self.assertIn("NNDR", md)
        self.assertIn("Diferansiyel Gizlilik", md)

        summary = report.to_dict()
        self.assertIn("dcr", summary)
        self.assertIn("nndr", summary)
        self.assertIn("empirical_epsilon", summary)
        self.assertIn("hipaa", summary)


class TestValidatorIntegration(unittest.TestCase):
    """Validator üzerinden audit_privacy entegrasyon testi."""

    def test_validator_runs_privacy_audit(self):
        contract = SchemaContract.from_dict({
            "domain": "clinical_trial_test",
            "columns": [
                {"name": "age", "type": "int", "min": 18, "max": 100},
                {"name": "score", "type": "float", "min": 0.0, "max": 1.0},
            ]
        })
        rng = np.random.default_rng(42)
        ref_df = pd.DataFrame({
            "age": rng.integers(20, 70, 60),
            "score": rng.uniform(0.1, 0.9, 60),
        })
        synth_df = pd.DataFrame({
            "age": rng.integers(20, 70, 60),
            "score": rng.uniform(0.1, 0.9, 60),
        })

        clean_df, report = validator.run_validation(
            synth_df,
            contract,
            reference_df=ref_df,
            audit_privacy=True,
        )

        self.assertIn("privacy_audit", report)
        audit_meta = report["privacy_audit"]
        self.assertIn("dcr", audit_meta)
        self.assertIn("nndr", audit_meta)
        self.assertIn("hipaa", audit_meta)
        self.assertTrue(audit_meta["hipaa"]["passed"])


if __name__ == "__main__":
    unittest.main()
