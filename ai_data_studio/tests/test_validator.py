"""Validatör testleri: iş kuralları, aykırı değer temizliği ve korelasyon kontrolleri."""
import threading
import unittest

import numpy as np
import pandas as pd

from ai_data_studio.core import validator
from ai_data_studio.core.schema_contract import SchemaContract

SCHEMA_DICT = {
    "domain": "gaming_ad_interaction",
    "row_count_target": 20000,
    "random_seed": 42,
    "columns": [
        {"name": "age", "type": "int", "min": 13, "max": 65,
         "distribution": "normal", "mean": 28, "std": 8},
        {"name": "income", "type": "float", "min": 0, "max": 500000},
        {"name": "ad_duration_s", "type": "int", "min": 5, "max": 60},
        {"name": "watch_time_s", "type": "float", "min": 0, "max": 60},
        {"name": "clicked", "type": "bool", "target_ratio": 0.05},
    ],
    "business_rules": [
        "watch_time_s <= ad_duration_s",
        "not (age < 18 and income > 200000)",
    ],
    "correlations": [
        {"columns": ["age", "income"], "expected_sign": "positive", "min_r": 0.15}
    ],
}


def make_noisy_data(n=20000, seed=42):
    """Gercekci gurultu iceren ham veri: kural ihlalleri, aykırı degerler, duplicate."""
    rng = np.random.default_rng(seed)
    age = np.clip(rng.normal(28, 8, n), 13, 65).astype(int)
    income = np.clip(rng.normal(45000, 20000, n) + (age - 28) * 1500, 0, 500000)
    ad_duration_s = rng.integers(5, 61, n)
    watch_time_s = ad_duration_s * rng.beta(2, 2, n)
    clicked = rng.random(n) < 0.05
    df = pd.DataFrame({
        "age": age, "income": income, "ad_duration_s": ad_duration_s,
        "watch_time_s": watch_time_s, "clicked": clicked,
    })

    # --- kasitli gurultu ---
    # 1) is kurali ihlali: izleme suresi reklam suresinden uzun
    idx = rng.choice(n, size=int(n * 0.08), replace=False)
    df.loc[idx, "watch_time_s"] = df.loc[idx, "ad_duration_s"] + rng.uniform(1, 20, len(idx))
    # 2) sema sinir ihlali: yas araligin disinda
    idx = rng.choice(n, size=int(n * 0.03), replace=False)
    df.loc[idx, "age"] = rng.integers(80, 140, len(idx))
    # 3) tek degiskenli aykiri deger: asiri gelir
    idx = rng.choice(n, size=int(n * 0.02), replace=False)
    df.loc[idx, "income"] = rng.uniform(400000, 500000, len(idx))
    # 4) duplicate satirlar
    df = pd.concat([df, df.head(int(n * 0.02))], ignore_index=True)
    return df


class TestBusinessRules(unittest.TestCase):
    def test_simple_comparison_rule(self):
        df = pd.DataFrame({"a": [1, 5, 9], "b": [3, 3, 3]})
        kept, detail = validator.apply_business_rules(df, ["a <= b"])
        self.assertEqual(len(kept), 1)
        self.assertEqual(detail["rules"][0]["violations"], 2)

    def test_not_and_rule_from_spec(self):
        """Karmaşık mantıksal 'not (age < 10 and purchase_amount > 1000)' kuralı çalışmalı."""
        df = pd.DataFrame({"age": [8, 8, 30, 30], "purchase_amount": [2000, 10, 2000, 10]})
        kept, detail = validator.apply_business_rules(
            df, ["not (age < 10 and purchase_amount > 1000)"]
        )
        self.assertEqual(detail["rules"][0]["status"], "applied")
        self.assertEqual(len(kept), 3)

    def test_unparseable_rule_is_skipped_not_fatal(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        kept, detail = validator.apply_business_rules(df, ["yok_boyle_kolon > 5", "a > 1"])
        self.assertEqual(detail["rules"][0]["status"], "skipped")
        self.assertEqual(detail["rules"][1]["status"], "applied")
        self.assertEqual(len(kept), 2)

    def test_never_uses_bare_eval(self):
        """Kotu niyetli 'kural' Python olarak calistirilmamali."""
        df = pd.DataFrame({"a": [1, 2, 3]})
        kept, detail = validator.apply_business_rules(df, ["__import__('os').getcwd() == 1"])
        self.assertEqual(detail["rules"][0]["status"], "skipped")
        self.assertEqual(len(kept), 3)

    def test_sql_style_null_checks_are_applied(self):
        """Canli kosu: 'not is_returned and return_date is null' atlaniyordu."""
        df = pd.DataFrame({"is_returned": [True, False, False],
                           "return_date": [1.0, np.nan, 5.0]})
        kept, detail = validator.apply_business_rules(
            df, ["is_returned or return_date is null"])
        self.assertEqual(detail["rules"][0]["status"], "applied")
        self.assertEqual(len(kept), 2)       # returned + (not returned, no date)
        self.assertEqual(detail["rules"][0]["rule"], "is_returned or return_date is null")

    def test_rule_violated_by_every_row_is_skipped_not_applied(self):
        """Uygulansaydi cikti bos kalirdi (canli 1.5b P2: tutulan satir %0)."""
        df = pd.DataFrame({"a": [1, 2, 3], "b": [5, 5, 5]})
        kept, detail = validator.apply_business_rules(df, ["a > 10", "a <= b"])
        self.assertEqual(len(kept), 3)
        self.assertEqual(detail["rules"][0]["status"], "skipped")
        self.assertTrue(detail["rules"][0]["suspicious"])
        self.assertEqual(detail["rules"][1]["status"], "applied")

    def test_normalize_rule_sql_forms(self):
        norm = validator.normalize_rule
        self.assertEqual(norm("a IS NOT NULL AND b = 3"), "(a == a) and b == 3")
        self.assertEqual(norm("x is null OR NOT y"), "(x != x) or not y")
        # Zaten gecerli ifadeler degismez; <=, >=, !=, == bozulmaz.
        for rule in ("a <= b", "a >= b", "a != b", "a == b", "not (a < 1 and b > 2)"):
            self.assertEqual(norm(rule), rule)


class TestOutlierRemoval(unittest.TestCase):
    def test_z_score_removes_extremes(self):
        df = pd.DataFrame({"x": list(np.random.default_rng(0).normal(0, 1, 1000)) + [50.0, -50.0]})
        kept, detail = validator.remove_z_score_outliers(df, ["x"], threshold=3.0)
        self.assertGreaterEqual(detail["removed"], 2)
        self.assertLess(kept["x"].abs().max(), 50)

    def test_z_score_ignores_constant_column(self):
        df = pd.DataFrame({"x": [5.0] * 100})
        kept, detail = validator.remove_z_score_outliers(df, ["x"])
        self.assertEqual(len(kept), 100)
        self.assertEqual(detail["removed"], 0)

    def test_isolation_forest_removes_roughly_contamination(self):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({"a": rng.normal(0, 1, 3000), "b": rng.normal(0, 1, 3000)})
        kept, detail = validator.remove_isolation_forest_outliers(df, ["a", "b"], 0.05)
        self.assertFalse(detail["skipped"])
        self.assertAlmostEqual(detail["removed"] / 3000, 0.05, delta=0.02)

    def test_isolation_forest_skips_when_single_column(self):
        df = pd.DataFrame({"a": range(100)})
        _, detail = validator.remove_isolation_forest_outliers(df, ["a"])
        self.assertTrue(detail["skipped"])


class TestCorrelationAndDistribution(unittest.TestCase):
    def setUp(self):
        self.schema = SchemaContract.from_dict(SCHEMA_DICT)

    def test_positive_correlation_passes(self):
        rng = np.random.default_rng(0)
        age = rng.normal(30, 8, 5000)
        df = pd.DataFrame({"age": age, "income": age * 1500 + rng.normal(0, 8000, 5000),
                           "ad_duration_s": 30.0, "watch_time_s": 10.0})
        results = validator.validate_correlations(df, self.schema)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["pass"])
        self.assertGreater(results[0]["actual_r"], 0.15)

    def test_missing_correlation_is_reported_as_failure(self):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({"age": rng.normal(30, 8, 5000), "income": rng.normal(50000, 20000, 5000),
                           "ad_duration_s": 30.0, "watch_time_s": 10.0})
        results = validator.validate_correlations(df, self.schema)
        self.assertFalse(results[0]["pass"])

    def test_ks_skipped_without_seed_data(self):
        report = validator.validate_distributions(pd.DataFrame({"age": [1, 2]}), None, self.schema)
        self.assertTrue(report["skipped"])
        from ai_data_studio.i18n import t
        self.assertEqual(report["reason"], t("validation.dist_skip.no_seed"))

    def test_ks_passes_for_same_distribution(self):
        # p-degeri ayni dagilimda bile %5 olasilikla 0.05'in altina duser, bu yuzden
        # esas iddia KS istatistiginin kucuk olmasi uzerinden kuruluyor.
        rng = np.random.default_rng(1)
        a = pd.DataFrame({"age": rng.normal(30, 8, 3000), "income": rng.normal(5e4, 2e4, 3000)})
        b = pd.DataFrame({"age": rng.normal(30, 8, 3000), "income": rng.normal(5e4, 2e4, 3000)})
        report = validator.validate_distributions(a, b, self.schema)
        self.assertFalse(report["skipped"])
        self.assertLess(report["columns"]["age"]["ks_stat"], 0.05)
        self.assertTrue(report["columns"]["age"]["pass"])

    def test_ks_fails_for_shifted_distribution(self):
        rng = np.random.default_rng(0)
        a = pd.DataFrame({"age": rng.normal(30, 8, 3000)})
        b = pd.DataFrame({"age": rng.normal(55, 8, 3000)})
        report = validator.validate_distributions(a, b, self.schema)
        self.assertGreater(report["columns"]["age"]["ks_stat"], 0.5)
        self.assertFalse(report["columns"]["age"]["pass"])


class TestFullPipeline(unittest.TestCase):
    def setUp(self):
        self.schema = SchemaContract.from_dict(SCHEMA_DICT)
        self.raw = make_noisy_data(20000)

    def test_end_to_end_removal_and_report(self):
        clean, report = validator.run_validation(self.raw, self.schema)

        # make_noisy_data kasitli olarak ~%13 gurultu enjekte ediyor (%8 kural
        # ihlali + %3 sinir ihlali + %2 duplicate; %2 gelir aykiriligi sinir
        # ihlaliyle ortusuyor). Beklenen ayiklama bu bandin icinde olmali.
        # IsolationForest varsayilan olarak kapali oldugu icin buna ek bir
        # "sabit oran" silme yapilmaz - eskiden bandi %5 sisiren buydu.
        self.assertGreater(report["removed_total"], 0)
        self.assertTrue(10 <= 100 - report["retention_pct"] <= 20,
                        "Ayıklanan oran %%%.1f - beklenen ~%%13 bandinin disinda"
                        % (100 - report["retention_pct"]))

        # Duplicate kalmadi
        self.assertFalse(clean.duplicated().any())

        # Is kurallari artik ihlal edilmiyor
        self.assertTrue((clean["watch_time_s"] <= clean["ad_duration_s"]).all())

        # Sema sinirlari korunuyor
        self.assertTrue(clean["age"].between(13, 65).all())

        # Rapor beklenen bolumleri iceriyor
        for key in ("rows_in", "rows_out", "stages", "business_rules",
                    "correlations", "distributions", "column_stats"):
            self.assertIn(key, report)
        self.assertEqual(len(report["stages"]), 5)

        # Is kurali ihlalleri raporlanmis
        applied = [r for r in report["business_rules"] if r["status"] == "applied"]
        self.assertEqual(len(applied), 2)
        self.assertGreater(applied[0]["violations"], 0)

        # Korelasyon dogrulanmis
        self.assertEqual(len(report["correlations"]), 1)
        self.assertTrue(report["correlations"][0]["pass"])

    def test_cancel_event_aborts(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(validator.ValidationCancelled):
            validator.run_validation(self.raw, self.schema, cancel_event=cancel)

    def test_unmeasurable_correlation_does_not_crash_the_run(self):
        """Canli kosu: sabit kolonlu korelasyonda "%.3f" % None tum pipeline'i dusurdu."""
        raw = self.raw.copy()
        raw["income"] = 1000.0                       # sabit -> r hesaplanamaz
        messages = []
        _, report = validator.run_validation(
            raw, self.schema, on_progress=lambda m, *a, **k: messages.append(m))
        corr = report["correlations"][0]
        self.assertIsNone(corr["actual_r"])
        self.assertFalse(corr["pass"])
        from ai_data_studio.i18n import t
        prefix = t("validation.correlation_skipped", pair="age - income", reason="")
        self.assertTrue(any(prefix.rstrip() in m for m in messages), messages[-5:])

    def test_rule_removing_most_rows_is_flagged_but_still_applied(self):
        """Canli kosularda tek kural veriyi %4.5'e indirdi; kullanici nedenini gormeli."""
        from ai_data_studio import config
        from ai_data_studio.i18n import t

        raw = self.raw.copy()
        raw["watch_time_s"] = raw["ad_duration_s"] + 1.0        # hepsi kurali ihlal eder
        raw.loc[raw.index[:1000], "watch_time_s"] = 0.0
        events = []
        clean, report = validator.run_validation(
            raw, self.schema, on_progress=lambda m, *a, **k: events.append((m, a)))
        rule = report["business_rules"][0]
        self.assertTrue(rule["suspicious"])
        self.assertLessEqual(len(clean), 1000)                  # kural yine uygulandi
        expected = t("validation.rule_suspicious", rule=rule["rule"],
                     pct="%.1f" % rule["violation_pct"])
        self.assertIn((expected.join(["    -> ", ""]), (config.PROGRESS_WARNING,)),
                      [(m, a[:1]) for m, a in events])

    def test_column_order_normalised_to_schema(self):
        shuffled = self.raw[["clicked", "income", "age", "watch_time_s", "ad_duration_s"]]
        clean, _ = validator.run_validation(shuffled, self.schema)
        self.assertEqual(list(clean.columns),
                         ["age", "income", "ad_duration_s", "watch_time_s", "clicked"])


if __name__ == "__main__":
    unittest.main()


class TestHeavyTailPreservation(unittest.TestCase):
    """Z-Score'un agir kuyruklu / sifir-sisirilmis kolonlari kesmedigini dogrular.

    Regresyon kaydi: sabit |Z|>3 esigi, %79'u sifir olan bir ZIP kolonunda
    ~2.4'e denk geliyor ve 3+ olan her gozlemi siliyordu; korelasyonu tasiyan
    satirlar tam da bunlar oldugu icin semadaki hedef korelasyonlar temizlik
    sonrasi esik altina dusuyordu.
    """

    @staticmethod
    def _zip_column(n=5000, zero_prob=0.79, seed=7):
        rng = np.random.default_rng(seed)
        counts = rng.poisson(1.6, n)
        counts[rng.random(n) < zero_prob] = 0
        return counts

    def test_zip_column_skipped_via_schema_distribution(self):
        df = pd.DataFrame({"tickets": self._zip_column()})
        schema = SchemaContract.from_dict({
            "domain": "d", "row_count_target": 5000, "random_seed": 42,
            "columns": [{"name": "tickets", "type": "int", "min": 0, "max": 20,
                         "distribution": "zip"}],
        })
        eligible, skipped = validator.zscore_eligible_columns(df, ["tickets"], schema)
        self.assertEqual(eligible, [])
        self.assertIn("tickets", skipped)

        kept, detail = validator.remove_z_score_outliers(
            df, ["tickets"], threshold=3.0, schema=schema)
        self.assertEqual(detail["removed"], 0)
        self.assertEqual(kept["tickets"].max(), df["tickets"].max())

    def test_zero_inflated_column_skipped_without_schema(self):
        """Sema dagilim bilgisi vermese de sifir orani ampirik olarak yakalanmali."""
        df = pd.DataFrame({"tickets": self._zip_column()})
        kept, detail = validator.remove_z_score_outliers(df, ["tickets"], threshold=3.0)
        self.assertEqual(detail["removed"], 0)
        self.assertIn("tickets", detail["skipped_columns"])
        self.assertEqual(kept["tickets"].max(), df["tickets"].max())

    def test_symmetric_column_still_filtered(self):
        """Kuyruk korumasi, gercekten normal dagilan kolonlarda filtreyi kapatmamali."""
        rng = np.random.default_rng(0)
        df = pd.DataFrame({"x": np.concatenate([rng.normal(100, 15, 1000), [5000.0, -5000.0]])})
        kept, detail = validator.remove_z_score_outliers(df, ["x"], threshold=3.0)
        self.assertEqual(detail["skipped_columns"], {})
        self.assertGreaterEqual(detail["removed"], 2)
        self.assertLess(kept["x"].max(), 5000)

    def test_outlier_contaminated_normal_is_not_masked(self):
        """Birkac uc deger, moment carpikligini sisirip filtreyi kapatmamali."""
        rng = np.random.default_rng(3)
        base = rng.normal(100.0, 15.0, 500)
        df = pd.DataFrame({"amount": np.concatenate([base, [5000.0, 7500.0, 9000.0]])})
        eligible, skipped = validator.zscore_eligible_columns(df, ["amount"])
        self.assertEqual(eligible, ["amount"])
        self.assertEqual(skipped, {})


class TestIsolationForestOptIn(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.df = pd.DataFrame({"a": rng.normal(0, 1, 3000), "b": rng.normal(0, 1, 3000)})

    def test_disabled_by_default(self):
        _, detail = validator.remove_isolation_forest_outliers(self.df, ["a", "b"])
        self.assertTrue(detail["skipped"])
        self.assertEqual(detail["removed"], 0)

    def test_enabled_with_explicit_contamination(self):
        _, detail = validator.remove_isolation_forest_outliers(self.df, ["a", "b"], 0.05)
        self.assertFalse(detail["skipped"])
        self.assertGreater(detail["removed"], 0)


class TestCorrelationGuard(unittest.TestCase):
    """Outlier temizligi hedef korelasyonu bozarsa geri alinmali.

    Kurgu, Job #100'de gozlenen gercek arizayi taklit ediyor: iliskiyi tasiyan
    satirlar dagilimin kuyrugunda; IsolationForest agir kuyruklu `amount`
    kolonundan dolayi tam o satirlari secip siliyor ve temizlik sonrasi
    korelasyon esigin altina dusuyor.
    """

    MIN_R = 0.60          # ham veride r ~= 0.62, temizlik sonrasi ~= 0.49
    CONTAMINATION = 0.10

    def setUp(self):
        rng = np.random.default_rng(11)
        n = 4000
        delay = rng.poisson(1.2, n)
        delay[rng.random(n) < 0.72] = 0
        tickets = np.clip(np.round(delay * 0.8 + rng.normal(0, 0.9, n)), 0, None)
        self.raw = pd.DataFrame({
            "delay": delay.astype(float),
            "tickets": tickets.astype(float),
            "amount": rng.gamma(2.0, 60.0, n) + delay * 25.0,
            "filler": rng.normal(50, 10, n),
        })
        self.schema = SchemaContract.from_dict({
            "domain": "d", "row_count_target": n, "random_seed": 42,
            "columns": [
                {"name": "delay", "type": "float", "min": 0, "max": 50, "distribution": "zip"},
                {"name": "tickets", "type": "float", "min": 0, "max": 50, "distribution": "zip"},
                {"name": "amount", "type": "float", "min": 0, "max": 5000, "distribution": "gamma"},
                {"name": "filler", "type": "float", "min": 0, "max": 100,
                 "distribution": "normal", "mean": 50},
            ],
            "correlations": [
                {"columns": ["delay", "tickets"], "expected_sign": "positive", "min_r": self.MIN_R},
            ],
        })

    def test_cleaning_would_break_correlation_without_guard(self):
        """Once ariza gercekten olusuyor mu - koruma testinin on kosulu."""
        _, report = validator.run_validation(
            self.raw.copy(), self.schema,
            contamination=self.CONTAMINATION, correlation_guard=False)
        self.assertFalse(report["correlation_guard"]["enabled"])
        self.assertFalse(report["correlations"][0]["pass"])
        self.assertLess(report["correlations"][0]["actual_r"], self.MIN_R)

    def test_guard_reverts_and_restores_correlation(self):
        clean, report = validator.run_validation(
            self.raw.copy(), self.schema,
            contamination=self.CONTAMINATION, correlation_guard=True)
        guard = report["correlation_guard"]
        self.assertTrue(guard["enabled"])
        self.assertTrue(guard["reverted"], "koruma geri alma yolunu tetiklemedi")
        self.assertGreater(guard["rows_restored"], 0)
        self.assertEqual(len(guard["regressions"]), 1)
        self.assertEqual(guard["regressions"][0]["pair"], ["delay", "tickets"])
        # Geri alindiktan sonra hedef korelasyon yeniden saglanmali.
        self.assertTrue(report["correlations"][0]["pass"])
        self.assertGreaterEqual(report["correlations"][0]["actual_r"], self.MIN_R)
        # Kuyruk satirlari da geri gelmis olmali.
        self.assertEqual(clean["amount"].max(), self.raw["amount"].max())
