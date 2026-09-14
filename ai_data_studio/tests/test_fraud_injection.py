"""Fraud senaryo enjeksiyonu ve anomali koruma testleri."""
from __future__ import annotations

import unittest
import numpy as np
import pandas as pd

from ai_data_studio.core import validator
from ai_data_studio.core.schema_contract import SchemaContract
from ai_data_studio.core.fraud_injector import (
    FraudScenarioConfig,
    FraudScenarioInjector,
    inject_fraud_scenarios,
)
from ai_data_studio.core.orchestrator import _build_arg_parser


class TestAnomalyPreservationInValidator(unittest.TestCase):
    """Z-Score ve IsolationForest'ta anomali kolonunun korunmasını test eder."""

    def setUp(self):
        rng = np.random.default_rng(42)
        n = 500
        # Normal dağılımlı veriler
        self.df = pd.DataFrame({
            "amount": rng.normal(100.0, 15.0, n),
            "distance_km": rng.normal(10.0, 3.0, n),
            "is_fraud": 0,
        })
        # 3 adet aşırı uç fraud işlemi ekle
        self.df.loc[0, ["amount", "distance_km", "is_fraud"]] = [5000.0, 500.0, 1]
        self.df.loc[1, ["amount", "distance_km", "is_fraud"]] = [7500.0, 800.0, 1]
        self.df.loc[2, ["amount", "distance_km", "is_fraud"]] = [9000.0, 1200.0, 1]
        # 1 adet normal işlem ama aykırı değer (hatalı veri, is_fraud=0)
        self.df.loc[3, ["amount", "distance_km", "is_fraud"]] = [6000.0, 600.0, 0]

    def test_z_score_without_protection_drops_all_extremes(self):
        """Koruma bayrağı yokken hem fraud hem normal aykırılar silinmeli."""
        kept, detail = validator.remove_z_score_outliers(
            self.df, ["amount", "distance_km"], threshold=3.0
        )
        self.assertNotIn(0, kept.index)
        self.assertNotIn(1, kept.index)
        self.assertNotIn(2, kept.index)
        self.assertNotIn(3, kept.index)
        self.assertEqual(detail.get("preserved_anomalies", 0), 0)

    def test_z_score_with_protection_preserves_fraud_rows(self):
        """is_fraud=1 satırları Z-score eşiğini aşsa bile korunmalı, is_fraud=0 silinmeli."""
        kept, detail = validator.remove_z_score_outliers(
            self.df, ["amount", "distance_km"], threshold=3.0,
            preserve_anomaly_column="is_fraud", preserve_anomaly_value=1
        )
        # Fraud satırları korunmuş olmalı
        self.assertIn(0, kept.index)
        self.assertIn(1, kept.index)
        self.assertIn(2, kept.index)
        # Normal aykırı değer (is_fraud=0) ise silinmiş olmalı
        self.assertNotIn(3, kept.index)
        self.assertEqual(detail["preserved_anomalies"], 3)

    def test_isolation_forest_with_protection_preserves_fraud_rows(self):
        """Isolation Forest'ta is_fraud=1 satırları korunmalı."""
        # Koruma olmadan çalıştır
        kept_no_prot, detail_no_prot = validator.remove_isolation_forest_outliers(
            self.df, ["amount", "distance_km"], contamination=0.05, random_state=42
        )
        # Koruma ile çalıştır
        kept_prot, detail_prot = validator.remove_isolation_forest_outliers(
            self.df, ["amount", "distance_km"], contamination=0.05, random_state=42,
            preserve_anomaly_column="is_fraud", preserve_anomaly_value=1
        )
        self.assertIn(0, kept_prot.index)
        self.assertIn(1, kept_prot.index)
        self.assertIn(2, kept_prot.index)
        self.assertGreaterEqual(detail_prot.get("preserved_anomalies", 0), 1)

    def test_run_validation_end_to_end_preserves_anomalies(self):
        """run_validation Discriminator hattında anomali koruma raporu oluşturmalı."""
        schema_dict = {
            "domain": "fintech_fraud_test",
            "row_count_target": len(self.df),
            "columns": [
                {"name": "amount", "type": "float", "min": 0, "max": 100000},
                {"name": "distance_km", "type": "float", "min": 0, "max": 5000},
                {"name": "is_fraud", "type": "int", "min": 0, "max": 1},
            ],
            "preserve_anomaly_column": "is_fraud",
            "preserve_anomaly_value": 1,
        }
        schema = SchemaContract.from_dict(schema_dict)

        clean_df, report = validator.run_validation(self.df, schema)

        # Fraud satırları temiz veride mevcut olmalı
        self.assertIn(0, clean_df.index)
        self.assertIn(1, clean_df.index)
        self.assertIn(2, clean_df.index)

        # Rapor içinde korunan anomali bilgisi bulunmalı
        self.assertIn("preserved_anomalies", report)
        pres_info = report["preserved_anomalies"]
        self.assertEqual(pres_info["column"], "is_fraud")
        self.assertGreater(pres_info["total_preserved"], 0)


class TestFraudScenarioInjector(unittest.TestCase):
    """FraudScenarioInjector modülünün işlevselliğini test eder."""

    def test_inject_creates_target_column_if_missing(self):
        df = pd.DataFrame({
            "amount": [10.0, 20.0, 30.0, 40.0, 50.0] * 20,
            "failed_attempts": [0, 0, 1, 0, 0] * 20,
        })
        cfg = FraudScenarioConfig(fraud_rate=0.05, target_column="is_fraud", random_seed=42)
        injector = FraudScenarioInjector(cfg)
        out_df, report = injector.inject(df)

        self.assertIn("is_fraud", out_df.columns)
        self.assertEqual(report["injected_fraud_count"], 5)
        self.assertEqual((out_df["is_fraud"] == 1).sum(), 5)
        self.assertIn("high_amount_burst", report["scenarios_applied"])

    def test_inject_multiple_scenarios_modifies_features(self):
        df = pd.DataFrame({
            "transaction_amount": [100.0] * 200,
            "distance_km": [5.0] * 200,
            "failed_attempts": [0] * 200,
            "hour": [12] * 200,
            "is_international": [False] * 200,
        })
        out_df, report = inject_fraud_scenarios(
            df, fraud_rate=0.02, target_column="is_fraud", seed=99
        )
        fraud_rows = out_df[out_df["is_fraud"] == 1]
        self.assertEqual(len(fraud_rows), 4)

        # Aşırı tutar patlaması doğrula (tutar 500'den büyük olmalı)
        self.assertTrue((fraud_rows["transaction_amount"] > 400.0).all())
        # Mesafe anomalisini doğrula (mesafe 2000'den büyük olmalı)
        self.assertTrue((fraud_rows["distance_km"] > 1000.0).all())
        # Başarısız deneme artışını doğrula
        self.assertTrue((fraud_rows["failed_attempts"] >= 4).all())
        # Gece saatlerini doğrula (2, 3, 4, 5)
        self.assertTrue(fraud_rows["hour"].isin([2, 3, 4, 5]).all())
        # Risk bayrağını doğrula
        self.assertTrue(fraud_rows["is_international"].all())

    def test_inject_empty_dataframe(self):
        df = pd.DataFrame()
        out_df, report = inject_fraud_scenarios(df)
        self.assertTrue(out_df.empty)
        self.assertEqual(report["injected_fraud_count"], 0)


class TestSchemaContractAnomalySupport(unittest.TestCase):
    """SchemaContract'ın anomali alanlarını doğru saklayıp serileştirdiğini test eder."""

    def test_schema_contract_preserve_anomaly_serialization(self):
        contract = SchemaContract.from_dict({
            "domain": "test_anomaly",
            "columns": [
                {"name": "amount", "type": "float"},
                {"name": "is_fraud", "type": "int"},
            ],
            "preserve_anomaly_column": "is_fraud",
            "preserve_anomaly_value": 1,
        })
        self.assertEqual(contract.preserve_anomaly_column, "is_fraud")
        self.assertEqual(contract.preserve_anomaly_value, 1)

        d = contract.to_dict()
        self.assertEqual(d["preserve_anomaly_column"], "is_fraud")
        self.assertEqual(d["preserve_anomaly_value"], 1)
        from ai_data_studio.i18n import t
        self.assertIn(t("schema.summary.anomaly", column="is_fraud"), contract.summary())

    def test_schema_contract_warns_on_unknown_preserve_column(self):
        contract = SchemaContract.from_dict({
            "domain": "test_warn",
            "columns": [{"name": "amount", "type": "float"}],
            "preserve_anomaly_column": "non_existing_col",
        })
        self.assertTrue(any("non_existing_col" in w for w in contract.warnings))


class TestOrchestratorCLIArgs(unittest.TestCase):
    """CLI argümanlarının yeni bayrakları doğru parse ettiğini test eder."""

    def test_cli_parser_recognizes_fraud_flags(self):
        parser = _build_arg_parser()
        args = parser.parse_args([
            "--domain", "fintech fraud test",
            "--preserve-anomaly-col", "is_fraud",
            "--preserve-anomaly-val", "1",
            "--inject-fraud",
            "--fraud-rate", "0.01",
            "--fraud-target-col", "fraud_label",
        ])
        self.assertEqual(args.preserve_anomaly_col, "is_fraud")
        self.assertEqual(args.preserve_anomaly_val, "1")
        self.assertTrue(args.inject_fraud)
        self.assertEqual(args.fraud_rate, 0.01)
        self.assertEqual(args.fraud_target_col, "fraud_label")


class TestFraudTargetTable(unittest.TestCase):
    """--fraud-table: enjeksiyon artık kök tabloyla sınırlı değil.

    Asıl risk enjeksiyonun kendisi değil, muafiyet: anomali koruması köke
    sabitliyken çocuk tabloya enjekte edilen satırlar temizlik adımında
    silinip gidiyordu. Bu yüzden testler "hata vermedi"yi değil, enjekte
    edilen satırların SAYISINI ölçüyor.
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
                      row_count=1200, relational=True, inject_fraud=True,
                      fraud_rate=0.02, contamination=0.05,
                      export_formats=["csv"], output_dir=self.tmp / "out")
        params.update(overrides)
        cfg = orchestrator.PipelineConfig(**params)
        iterator = orchestrator.run_pipeline(
            cfg, threading.Event(), self.state,
            llm_client=fake_llm.FakeRelationalLLMClient())
        while True:
            try:
                next(iterator)
            except StopIteration as stop:
                return stop.value

    def test_injects_into_the_named_child_table(self):
        result = self._run(fraud_table="orders")
        self.assertIn("is_fraud", result.tables["orders"].columns)
        self.assertNotIn("is_fraud", result.tables["customers"].columns)

    def test_injected_rows_survive_cleaning_in_a_child_table(self):
        """Muafiyet enjeksiyonun yapıldığı tabloya bağlı olmasaydı bu test düşerdi.

        Hedef kolon bilerek ``is_fraud`` DEĞİL: validator tanıdığı adları
        (`is_fraud`, `is_anomaly`, `fraud_label`, ...) kendiliğinden koruyor, o
        yüzden varsayılan adla koşulan bir test muafiyetin doğru tabloya bağlı
        olup olmadığını ölçmez. Ölçüm (1.200 satır, `--contamination 0.05`):
        özel kolon adıyla düzeltmeden önce **0**, düzeltmeden sonra **69** satır
        sağ kalıyor.
        """
        result = self._run(fraud_table="orders", fraud_target_column="suspicious_flag")
        survivors = int(result.tables["orders"]["suspicious_flag"].astype(float).sum())
        self.assertGreater(survivors, 0,
                           "cocuk tabloya enjekte edilen dolandiricilik satirlari silindi")

    def test_root_table_is_untouched_when_a_child_is_targeted(self):
        result = self._run(fraud_table="orders", fraud_target_column="suspicious_flag")
        self.assertNotIn("suspicious_flag", result.tables["customers"].columns)

    def test_default_still_targets_the_root_table(self):
        result = self._run()
        self.assertIn("is_fraud", result.tables[result.contract.root_table].columns)

    def test_unknown_table_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._run(fraud_table="boyle_bir_tablo_yok")
        self.assertIn("boyle_bir_tablo_yok", str(ctx.exception))

    def test_cli_exposes_the_flag(self):
        from ai_data_studio.core import orchestrator

        parser = orchestrator._build_arg_parser()
        self.assertEqual(parser.parse_args(["--domain", "x"]).fraud_table, "")
        self.assertEqual(
            parser.parse_args(["--domain", "x", "--fraud-table", "orders"]).fraud_table,
            "orders")


if __name__ == "__main__":
    unittest.main()
