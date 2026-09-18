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

    def test_independent_low_dimensional_data_is_not_flagged(self):
        """Sabit eşiklerle 1-2 sayısal kolonda kopya olmayan veri de HIGH çıkıyordu:
        yerel yoğunlukta P(d1/d2 < 0.2) ~ 0.2^d (d=2, n=2000 -> %3,8 > %2 eşik)."""
        for d in (1, 2):
            for seed in (0, 1, 2):
                rng = np.random.default_rng(seed)
                cols = ["c%d" % i for i in range(d)]
                ref = pd.DataFrame(rng.normal(size=(2000, d)), columns=cols)
                synth = pd.DataFrame(rng.normal(size=(2000, d)), columns=cols)
                dcr, nndr = PrivacyAuditor().compute_dcr_nndr(synth, ref)
                self.assertNotEqual(nndr.memorization_risk, "HIGH", (d, seed, nndr))
                self.assertNotEqual(dcr.risk_level, "HIGH", (d, seed, dcr))
                self.assertGreater(nndr.baseline_low_ratio_rate, 0.02 if d == 2 else 0.1)

    def test_near_copies_are_flagged_against_the_baseline(self):
        """Satırların %10'u referans kaydın gürültülü kopyası: birebir eşleşme yok ama
        NNDR < 0.2 payı taban çizgisini belirgin aşar."""
        rng = np.random.default_rng(5)
        cols = ["a", "b", "c"]
        ref = pd.DataFrame(rng.normal(size=(1500, 3)), columns=cols)
        synth = pd.DataFrame(rng.normal(size=(1500, 3)), columns=cols)
        copied = rng.choice(len(ref), 150, replace=False)
        synth.iloc[:150] = ref.iloc[copied].to_numpy() + rng.normal(0, 1e-3, size=(150, 3))

        dcr, nndr = PrivacyAuditor().compute_dcr_nndr(synth, ref)

        self.assertEqual(dcr.identical_matches, 0)
        self.assertEqual(nndr.memorization_risk, "HIGH")
        self.assertGreater(nndr.low_ratio_rate, nndr.baseline_low_ratio_rate + 0.05)

    def test_natural_ties_in_discrete_data_are_not_memorisation(self):
        """Az değerli kesikli kolonlarda birebir eşleşme doğaldır; referansın kendi
        içindeki tekrar oranı taban çizgisidir."""
        rng = np.random.default_rng(9)
        ref = pd.DataFrame({"visits": rng.integers(0, 5, 800), "items": rng.integers(0, 4, 800)})
        synth = pd.DataFrame({"visits": rng.integers(0, 5, 800), "items": rng.integers(0, 4, 800)})

        dcr, nndr = PrivacyAuditor().compute_dcr_nndr(synth, ref)

        self.assertGreater(dcr.identical_matches, 0)
        self.assertGreater(dcr.baseline_identical_rate, 0.5)
        self.assertNotEqual(dcr.risk_level, "HIGH")
        self.assertFalse(dcr.memorization_risk)

    def test_single_exact_copy_of_continuous_data_is_high(self):
        """Referansta hiç tekrar yoksa tek bir birebir kopya gerçek bir kaydın sızmasıdır."""
        rng = np.random.default_rng(11)
        cols = ["a", "b", "c", "d"]
        ref = pd.DataFrame(rng.normal(size=(500, 4)), columns=cols)
        synth = pd.DataFrame(rng.normal(size=(500, 4)), columns=cols)
        synth.iloc[0] = ref.iloc[42]

        dcr = PrivacyAuditor().compute_dcr(synth, ref)

        self.assertEqual(dcr.identical_matches, 1)
        self.assertEqual(dcr.risk_level, "HIGH")


class TestDistributionDivergence(unittest.TestCase):
    def test_score_is_bounded_and_separates_shifted_data(self):
        """Eski skor aynı dağılımdan 300'er satırda 3,19 veriyordu (sınırsız)."""
        rng = np.random.default_rng(2)
        ref = pd.DataFrame({"x": rng.normal(0, 1, 5000), "y": rng.gamma(2, 1, 5000)})
        same = pd.DataFrame({"x": rng.normal(0, 1, 5000), "y": rng.gamma(2, 1, 5000)})
        shifted = pd.DataFrame({"x": rng.normal(2, 1, 5000), "y": rng.gamma(6, 1, 5000)})
        auditor = PrivacyAuditor()

        close, per_column = auditor.estimate_distribution_divergence(same, ref)
        far, _ = auditor.estimate_distribution_divergence(shifted, ref)

        self.assertEqual(sorted(per_column), ["x", "y"])
        self.assertLess(close, 0.1)
        self.assertGreater(far, 0.5)
        self.assertLessEqual(far, 1.0)

    def test_no_shared_numeric_columns_gives_none(self):
        score, per_column = PrivacyAuditor().estimate_distribution_divergence(
            pd.DataFrame({"a": ["x"] * 30}), pd.DataFrame({"a": ["y"] * 30}))
        self.assertIsNone(score)
        self.assertEqual(per_column, {})


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

    def test_every_rule_points_to_catalog_keys(self):
        """Kural başlıkları anahtar olarak tutuluyor; katalog kapsama testi
        dinamik t() çağrılarını göremediği için burada ayrıca denetlenir."""
        from ai_data_studio.core.privacy_auditor import HIPAA_IDENTIFIER_RULES
        from ai_data_studio.locales import en

        for name, rule in HIPAA_IDENTIFIER_RULES.items():
            self.assertIn(rule["title_key"], en.MESSAGES, name)
            self.assertIn(rule["category_key"], en.MESSAGES, name)

    def test_titles_follow_the_language_chosen_after_import(self):
        """Başlıklar eskiden modül yüklenirken çevriliyordu; sonradan seçilen dil
        rapora hiç yansımıyordu (ve dört kuralın başlığı sabit Türkçe'ydi)."""
        from ai_data_studio import i18n

        df = pd.DataFrame({"email": ["a@b.c"], "tckn": ["1"]})
        self.addCleanup(i18n.reset_for_tests)
        titles = {}
        for lang in ("en", "de"):
            i18n.set_language(lang)
            audit = PrivacyAuditor().scan_hipaa_identifiers(df)
            titles[lang] = {item["column"]: (item["title"], item["category"])
                            for item in audit.identifiers_found}
        self.assertEqual(titles["en"]["email"], ("Email addresses", "Direct identifier"))
        self.assertEqual(titles["en"]["tckn"][1], "Government-issued identifier")
        self.assertEqual(titles["de"]["email"][0], "E-Mail-Adressen")


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
        from ai_data_studio.i18n import t

        self.assertIn("HIPAA Safe Harbor", md)
        self.assertIn("DCR (Distance to Closest Record)", md)
        self.assertIn("NNDR", md)
        self.assertIn(t("privacy.report.title"), md)

        summary = report.to_dict()
        self.assertIn("dcr", summary)
        self.assertIn("nndr", summary)
        self.assertIn("distribution_divergence", summary)
        self.assertIn("baseline_low_ratio_rate", summary["nndr"])
        self.assertIn("hipaa", summary)

    def test_report_does_not_claim_guarantees_it_cannot_give(self):
        """Histogram oranı bir DP epsilon'u değil, kolon adı taraması bir HIPAA
        uyumluluğu değil; rapor bunları garanti gibi sunmamalı."""
        from ai_data_studio.i18n import language_override, t

        # Dört kolon: 1-2 sayısal kolonda bağımsız veri de NNDR eşiğine takılıyor
        # (yerel yoğunlukta P(d1/d2 < 0.2) ~ 0.2^d); burada o sınır test edilmiyor.
        rng = np.random.default_rng(7)
        cols = ["age", "cholesterol", "systolic_bp", "hba1c"]
        ref_df = pd.DataFrame(rng.normal(size=(200, 4)), columns=cols)
        synth_df = pd.DataFrame(rng.normal(size=(200, 4)), columns=cols)
        with language_override("en"):
            report = audit_dataset_privacy(synth_df, ref_df)
            md = report.to_markdown()

        self.assertEqual(report.overall_privacy_status, "NO_ISSUES_FOUND")
        lowered = md.lower()
        for claim in ("compliant", "verified", "high differential privacy", "epsilon"):
            self.assertNotIn(claim, lowered)
        with language_override("en"):
            self.assertIn(t("privacy.report.scope"), md)
            self.assertIn(t("privacy.report.divergence_note"), md)
            self.assertIn(t("privacy.report.hipaa_scope"), md)

    def test_without_reference_memorisation_is_reported_as_not_measured(self):
        from ai_data_studio.i18n import language_override, t

        with language_override("en"):
            report = audit_dataset_privacy(pd.DataFrame({"score": [1.0, 2.0, 3.0]}))
            self.assertEqual(report.privacy_guarantee, t("privacy.assessment.not_measured"))
        self.assertEqual(report.overall_privacy_status, "NO_ISSUES_FOUND")
        self.assertIsNone(report.distribution_divergence)

    def test_identifier_finding_needs_review_even_with_reference_data(self):
        """Referans veri varken tarama bulgusu eskiden durumu etkilemiyordu."""
        rng = np.random.default_rng(3)
        cols = ["phone", "score", "visits", "spend"]
        ref_df = pd.DataFrame(rng.normal(size=(200, 4)), columns=cols)
        synth_df = pd.DataFrame(rng.normal(size=(200, 4)), columns=cols)

        report = audit_dataset_privacy(synth_df, ref_df)

        self.assertFalse(report.hipaa_audit.passed)
        self.assertEqual(report.dcr.identical_matches, 0)
        self.assertNotEqual(report.nndr.memorization_risk, "HIGH")
        self.assertEqual(report.overall_privacy_status, "REVIEW_REQUIRED")


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


class TestPerTablePrivacyAudit(unittest.TestCase):
    """--audit-table: denetim artık kök tabloyla sınırlı değil.

    Önceki davranışta bayrak açık olsa bile denetim yalnız kök tabloya
    uygulanıyordu; 4 tablolu bir veri setinde bu, denetimin dörtte birini
    yapıp tamamını yaptığını sanmak demekti.
    """

    def setUp(self):
        import tempfile
        from pathlib import Path
        from ai_data_studio.core.state_manager import StateManager

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.state = StateManager(self.tmp / "state.db")

    def tearDown(self):
        self.state.close()
        self._tmp.cleanup()

    def _run(self, **overrides):
        import threading
        from ai_data_studio.core import orchestrator
        from ai_data_studio.tests import fake_llm

        params = dict(domain_prompt="saas faturalama", provider="fake",
                      row_count=1200, relational=True, audit_privacy=True,
                      export_formats=["csv"], output_dir=self.tmp / "out")
        params.update(overrides)
        cfg = orchestrator.PipelineConfig(**params)
        iterator = orchestrator.run_pipeline(
            cfg, threading.Event(), self.state,
            llm_client=fake_llm.FakeRelationalLLMClient())
        events = []
        while True:
            try:
                events.append(next(iterator))
            except StopIteration as stop:
                return events, stop.value

    def _audited_tables(self, result):
        return sorted(name for name, rep in (result.report.get("tables") or {}).items()
                      if rep.get("privacy_audit"))

    def test_default_audits_only_the_root_table(self):
        """Varsayılan davranış bozulmamalı."""
        _, result = self._run()
        self.assertEqual(self._audited_tables(result), [result.contract.root_table])

    def test_all_audits_every_table(self):
        _, result = self._run(audit_table="all")
        self.assertEqual(self._audited_tables(result),
                         sorted(result.contract.table_names))

    def test_named_table_audits_only_that_table(self):
        _, result = self._run(audit_table="orders")
        self.assertEqual(self._audited_tables(result), ["orders"])

    def test_unknown_table_is_rejected_loudly(self):
        """Sessiz kabul en kötüsü: kullanıcı denetim yaptığını sanır."""
        with self.assertRaises(ValueError) as ctx:
            self._run(audit_table="boyle_bir_tablo_yok")
        self.assertIn("boyle_bir_tablo_yok", str(ctx.exception))
        self.assertIn("customers", str(ctx.exception))

    def test_one_markdown_report_per_audited_table(self):
        _, result = self._run(audit_table="all")
        for name in result.contract.table_names:
            key = "privacy_report:%s" % name
            self.assertIn(key, result.output_paths, "%s icin rapor yazilmadi" % name)
            from pathlib import Path
            body = Path(result.output_paths[key]).read_text(encoding="utf-8")
            from ai_data_studio.i18n import t

            self.assertIn("**%s:** `%s`" % (t("privacy.report.table"), name), body)

    def test_child_report_says_memorisation_was_not_measured(self):
        """Seed veri kök tabloya ait; çocuk tabloda boş epsilon 'sorun yok' gibi
        okunmamalı."""
        from pathlib import Path
        _, result = self._run(audit_table="all")
        child = [n for n in result.contract.table_names
                 if n != result.contract.root_table][0]
        body = Path(result.output_paths["privacy_report:%s" % child]).read_text(
            encoding="utf-8")
        from ai_data_studio.i18n import t

        # Cocuk tabloda "olculmedi" ibaresi mutlaka bulunmali - bos bir epsilon
        # "sorun yok" gibi okunmamali.
        self.assertIn(t("privacy.report.no_reference_table"), body)

    def test_manifest_lists_every_privacy_report(self):
        import json
        from pathlib import Path
        _, result = self._run(audit_table="all")
        manifest = json.loads(Path(result.output_paths["manifest"]).read_text(
            encoding="utf-8"))
        for name in result.contract.table_names:
            self.assertIn("privacy_report:%s" % name, manifest["files"])

    def test_single_table_output_name_is_unchanged(self):
        """Tek tabloda dosya adı ve çıktı anahtarı birebir eskisi gibi kalmalı."""
        import threading
        from ai_data_studio.core import orchestrator
        from ai_data_studio.tests import fake_llm

        cfg = orchestrator.PipelineConfig(
            domain_prompt="e-ticaret", provider="fake", row_count=1200,
            audit_privacy=True, export_formats=["csv"], output_dir=self.tmp / "out2")
        iterator = orchestrator.run_pipeline(cfg, threading.Event(), self.state,
                                             llm_client=fake_llm.FakeLLMClient())
        while True:
            try:
                next(iterator)
            except StopIteration as stop:
                result = stop.value
                break

        self.assertIn("privacy_report", result.output_paths)
        self.assertTrue(result.output_paths["privacy_report"].endswith(
            "_privacy_report.md"))
        from pathlib import Path
        body = Path(result.output_paths["privacy_report"]).read_text(encoding="utf-8")
        from ai_data_studio.i18n import t

        self.assertNotIn("**%s:**" % t("privacy.report.table"), body)


class TestAuditTableCli(unittest.TestCase):
    def test_flag_exists_and_defaults_to_root(self):
        from ai_data_studio.core import orchestrator

        parser = orchestrator._build_arg_parser()
        self.assertEqual(parser.parse_args(["--domain", "x"]).audit_table, "")
        self.assertEqual(
            parser.parse_args(["--domain", "x", "--audit-table", "all"]).audit_table,
            "all")


class TestHipaaResultAlias(unittest.TestCase):
    """``hipaa_result`` disaridaki kosumlarin kullandigi eski ad.

    Bir benchmark kosumu alani bu adla okudu; 996 temiz satir uretilmis,
    dogrulama gecmis bir kosu raporlama adiminda AttributeError ile dustu.
    Takma ad GERCEK nesneyi dondurur: varsayilani None olan bir alan eklemek
    veriyi sessizce "HIPAA verisi yok"a cevirirdi.
    """

    def test_the_alias_returns_the_same_object_not_a_copy(self):
        report = PrivacyAuditReport()

        self.assertIs(report.hipaa_result, report.hipaa_audit)

    def test_the_alias_carries_the_findings(self):
        audit = HIPAAAuditResult(
            identifiers_found=[{"column": "ssn", "title": "SSN",
                                "category": "direct"}],
            passed=False,
            summary="1 identifier",
        )
        report = PrivacyAuditReport(hipaa_audit=audit)

        self.assertFalse(report.hipaa_result.passed)
        self.assertEqual(report.hipaa_result.flagged_columns, ["ssn"])
        self.assertEqual(report.to_dict()["hipaa"]["passed"], False)


if __name__ == "__main__":
    unittest.main()
