"""Üretim ve zenginleştirme motorlarının pipeline'a bağlanma testleri.

Bu modül motorların kendi birim testlerini tekrarlamaz (onlar
`test_parametric_engine.py`, `test_time_series_engine.py`,
`test_dirty_data_engine.py` içinde). Buradaki soru tek: motorlar orchestrator'ın
İÇİNDEN çağrıldığında gerçekten çalışıyor ve çıktı dosyasına kadar hayatta
kalıyorlar mı?

En kritik test `test_dirty_rows_survive_validation`: kirli veri doğrulamadan
ÖNCE enjekte edilseydi şema sınırları ve kategori denetimi tam da enjekte edilen
satırları silerdi ve kimse fark etmezdi.
"""
import tempfile
import threading
import unittest
from pathlib import Path

from ai_data_studio.core import orchestrator
from ai_data_studio.core.state_manager import StateManager
from ai_data_studio.tests import fake_llm


class _PipelineCase(unittest.TestCase):
    """Geçici veritabanı + çıktı dizini kuran ortak taban."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.state = StateManager(self.tmp / "state.db")

    def tearDown(self):
        self.state.close()
        self._tmp.cleanup()

    def _cfg(self, **overrides):
        params = dict(
            domain_prompt="e-ticaret sipariş verisi",
            provider="fake",
            row_count=2000,
            random_seed=42,
            export_formats=["csv"],
            output_dir=self.tmp / "out",
        )
        params.update(overrides)
        return orchestrator.PipelineConfig(**params)

    def _run(self, cfg, client=None):
        client = client or fake_llm.FakeLLMClient()
        iterator = orchestrator.run_pipeline(cfg, threading.Event(), self.state,
                                             llm_client=client)
        events = []
        while True:
            try:
                events.append(next(iterator))
            except StopIteration as stop:
                return events, stop.value


class TestParametricGeneration(_PipelineCase):
    """--engine parametric: kod üretimi ve sandbox tamamen atlanır."""

    def test_produces_data_without_generating_code(self):
        client = fake_llm.FakeLLMClient()
        _, result = self._run(self._cfg(engine=orchestrator.ENGINE_PARAMETRIC), client)

        self.assertGreater(len(result.dataframe), 0)
        self.assertEqual(result.report["engines"]["generation"],
                         orchestrator.ENGINE_PARAMETRIC)
        self.assertEqual(result.generation_meta["engine"],
                         orchestrator.ENGINE_PARAMETRIC)
        # Sema icin tek cagri yapilir; kod uretimi icin hic cagri yapilmaz.
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.feedback_received, [])

    def test_all_schema_columns_are_present(self):
        _, result = self._run(self._cfg(engine=orchestrator.ENGINE_PARAMETRIC))
        for col in result.schema.columns:
            self.assertIn(col.name, result.dataframe.columns)

    def test_emitted_code_reproduces_the_dataset(self):
        """Parametrik koşuda da bir üretici dosyası yazılır ve gerçekten çalışır."""
        _, result = self._run(self._cfg(engine=orchestrator.ENGINE_PARAMETRIC))
        self.assertIn("compile_schema_to_dataframe", result.code)

        namespace: dict = {}
        exec(compile(result.code, "<parametric>", "exec"), namespace)
        again = namespace["generate_data"](n_rows=200, seed=42)
        self.assertEqual(len(again), 200)
        for col in result.schema.columns:
            self.assertIn(col.name, again.columns)

    def test_is_deterministic_across_runs(self):
        _, first = self._run(self._cfg(engine=orchestrator.ENGINE_PARAMETRIC))
        _, second = self._run(self._cfg(engine=orchestrator.ENGINE_PARAMETRIC))
        self.assertEqual(list(first.dataframe["customer_age"].head(50)),
                         list(second.dataframe["customer_age"].head(50)))

    def test_relational_is_rejected_before_any_llm_call(self):
        """Parametrik motor yabancı anahtar kuramıyor; sessizce yetim üretmemeli."""
        client = fake_llm.FakeRelationalLLMClient()
        cfg = self._cfg(engine=orchestrator.ENGINE_PARAMETRIC, relational=True)
        with self.assertRaises(ValueError) as ctx:
            self._run(cfg, client)
        self.assertIn("ilişkisel", str(ctx.exception).lower())
        # Hata LLM'e gitmeden, sema uretilmeden verilmeli.
        self.assertEqual(client.calls, [])

    def test_unknown_engine_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self._run(self._cfg(engine="quantum"))
        self.assertIn("quantum", str(ctx.exception))


class TestAutoEngineFallback(_PipelineCase):
    """--engine auto: kod üretimi tükenirse pipeline düşmez, parametriğe geçer."""

    def test_falls_back_when_code_generation_fails(self):
        client = fake_llm.FakeLLMClient([fake_llm.BROKEN_RUNTIME_CODE])
        cfg = self._cfg(engine=orchestrator.ENGINE_AUTO, max_retries=1)
        events, result = self._run(cfg, client)

        self.assertEqual(result.report["engines"]["generation"], "llm->parametric")
        self.assertGreater(len(result.dataframe), 0)
        self.assertIn("fallback_reason", result.generation_meta)
        # Kullanici sessizce baska bir motora gectigimizi gormeli.
        self.assertTrue(any("Parametrik motora düşülüyor" in e["message"] for e in events))

    def test_uses_llm_when_code_generation_succeeds(self):
        events, result = self._run(self._cfg(engine=orchestrator.ENGINE_AUTO))
        self.assertEqual(result.report["engines"]["generation"], orchestrator.ENGINE_LLM)
        self.assertFalse(any("Parametrik motora düşülüyor" in e["message"] for e in events))

    def test_default_engine_is_unchanged_llm_path(self):
        _, result = self._run(self._cfg())
        self.assertEqual(result.report["engines"]["generation"], orchestrator.ENGINE_LLM)
        self.assertIn("def generate_data", result.code)


class TestTimeSeriesIntegration(_PipelineCase):
    """--time-series: eklenen kolonlar doğrulamadan sağ çıkmalı."""

    def test_velocity_columns_reach_the_result(self):
        cfg = self._cfg(engine=orchestrator.ENGINE_PARAMETRIC, time_series=True)
        _, result = self._run(cfg)

        for col in ("transaction_timestamp", "seconds_since_last_tx",
                    "is_high_velocity", "customer_id"):
            self.assertIn(col, result.dataframe.columns, "%s kolonu kayboldu" % col)

        ts_meta = result.report["engines"]["time_series"]
        self.assertGreater(ts_meta["unique_entities"], 0)
        self.assertGreater(ts_meta["burst_anomalies_count"], 0)

    def test_custom_column_names_are_honoured(self):
        cfg = self._cfg(engine=orchestrator.ENGINE_PARAMETRIC, time_series=True,
                        ts_timestamp_column="event_time", ts_entity_column="user_ref")
        _, result = self._run(cfg)
        self.assertIn("event_time", result.dataframe.columns)
        self.assertIn("user_ref", result.dataframe.columns)

    def test_written_csv_contains_the_new_columns(self):
        cfg = self._cfg(engine=orchestrator.ENGINE_PARAMETRIC, time_series=True)
        _, result = self._run(cfg)
        csv_path = Path(result.output_paths["csv"])
        header = csv_path.read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("seconds_since_last_tx", header)


class TestFeatureExpanderIntegration(_PipelineCase):
    """--expand-features: türetilmiş kolonlar rapora ve veriye girmeli."""

    def test_adds_derived_columns(self):
        cfg = self._cfg(engine=orchestrator.ENGINE_PARAMETRIC, expand_features=True)
        _, result = self._run(cfg)

        meta = result.report["engines"]["feature_expander"]
        self.assertGreater(meta["added_columns_count"], 0)
        # Sahte sema customer_age tasiyor -> yas grubu turetilebilmeli.
        self.assertIn("age_group", meta["added_columns"])
        self.assertIn("age_group", result.dataframe.columns)

    def test_time_derivations_need_the_timestamp_column(self):
        """Zaman serisiyle birlikte koşulunca saat/gün türevleri de gelmeli."""
        cfg = self._cfg(engine=orchestrator.ENGINE_PARAMETRIC,
                        time_series=True, expand_features=True)
        _, result = self._run(cfg)
        added = result.report["engines"]["feature_expander"]["added_columns"]
        self.assertIn("hour_of_day", added)
        self.assertIn("is_night_transaction", added)


class TestDirtyDataIntegration(_PipelineCase):
    """--dirty-rate: kirlilik doğrulamadan SONRA uygulanır ve çıktıda kalır."""

    def test_dirty_rows_survive_validation(self):
        """Sıranın kanıtı. Doğrulamadan önce enjekte edilseydi hepsi silinirdi.

        Şema sınırları uç değerleri, kategori denetimi yazım hatalarını, null
        denetimi eksik değerleri eler; yani kirletilen satırlar tam olarak
        validator'ın hedefidir.
        """
        cfg = self._cfg(engine=orchestrator.ENGINE_PARAMETRIC, dirty_rate=0.05)
        _, result = self._run(cfg)

        df = result.dataframe
        self.assertIn("is_corrupted", df.columns)
        self.assertIn("corruption_details", df.columns)

        corrupted = int(df["is_corrupted"].sum())
        expected = max(1, round(len(df) * 0.05))
        self.assertEqual(corrupted, expected)
        # Bozulma gerekcesi bos kalmamali - "clean" olmayan satir sayisi eslesmeli.
        self.assertEqual(int((df["corruption_details"] != "clean").sum()), expected)

    def test_report_records_the_ordering(self):
        cfg = self._cfg(engine=orchestrator.ENGINE_PARAMETRIC, dirty_rate=0.05)
        _, result = self._run(cfg)
        meta = result.report["engines"]["dirty_data"]
        self.assertTrue(meta["applied_after_validation"])
        self.assertTrue(meta["column_stats_precede_corruption"])
        self.assertGreater(meta["corrupted_rows"], 0)

    def test_row_count_is_not_changed(self):
        cfg = self._cfg(engine=orchestrator.ENGINE_PARAMETRIC, dirty_rate=0.05)
        _, result = self._run(cfg)
        self.assertEqual(len(result.dataframe), result.report["rows_out"])

    def test_zero_rate_keeps_the_data_clean(self):
        cfg = self._cfg(engine=orchestrator.ENGINE_PARAMETRIC, dirty_rate=0.0)
        _, result = self._run(cfg)
        self.assertNotIn("is_corrupted", result.dataframe.columns)
        self.assertNotIn("dirty_data", result.report["engines"])

    def test_invalid_rate_is_rejected(self):
        with self.assertRaises(ValueError):
            self._run(self._cfg(dirty_rate=1.5))

    def test_key_columns_are_never_corrupted(self):
        """Anahtar kolonlar kirletilmemeli.

        Kirlilik ilişkisel bütünlük denetiminden SONRA çalışıyor; birincil ya da
        yabancı anahtara null enjekte edilseydi denetimden "0 yetim FK" damgası
        almış bir veri seti kirli anahtarlarla dışarı çıkardı.
        """
        client = fake_llm.FakeRelationalLLMClient()
        cfg = self._cfg(relational=True, dirty_rate=0.20, row_count=1500)
        _, result = self._run(cfg, client)

        contract = result.contract
        keys = orchestrator._key_columns(contract)
        self.assertTrue(keys, "sözleşmede hiç anahtar bulunamadı - test anlamsız")

        root = result.dataframe
        self.assertGreater(int(root["is_corrupted"].sum()), 0)
        for column in root.columns:
            if column.lower() in keys:
                self.assertEqual(int(root[column].isna().sum()), 0,
                                 "anahtar kolon '%s' kirletildi" % column)
                self.assertNotIn(column, ",".join(root["corruption_details"].astype(str)))

    def test_relational_integrity_survives_corruption(self):
        """Kirlilikten sonra da yetim FK olmamalı."""
        client = fake_llm.FakeRelationalLLMClient()
        cfg = self._cfg(relational=True, dirty_rate=0.20, row_count=1500)
        _, result = self._run(cfg, client)

        self.assertTrue(result.report["relational"]["pass"])
        for rel in result.contract.relationships:
            parent = result.tables[rel.parent_table][rel.parent_key]
            child = result.tables[rel.child_table][rel.child_key].dropna()
            orphans = (~child.isin(set(parent))).sum()
            self.assertEqual(int(orphans), 0,
                             "%s ilişkisinde %d yetim FK" % (rel.label(), orphans))


class TestEngineFlagsOnCli(unittest.TestCase):
    """CLI yüzeyi: bayraklar var mı ve PipelineConfig'e doğru mu geçiyor."""

    def test_parser_exposes_engine_flags(self):
        parser = orchestrator._build_arg_parser()
        args = parser.parse_args([
            "--domain", "x", "--engine", "parametric", "--time-series",
            "--expand-features", "--dirty-rate", "0.07",
            "--ts-timestamp-col", "event_time", "--ts-entity-col", "user_ref",
        ])
        self.assertEqual(args.engine, "parametric")
        self.assertTrue(args.time_series)
        self.assertTrue(args.expand_features)
        self.assertAlmostEqual(args.dirty_rate, 0.07)
        self.assertEqual(args.ts_timestamp_col, "event_time")
        self.assertEqual(args.ts_entity_col, "user_ref")

    def test_engine_choices_are_limited(self):
        parser = orchestrator._build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--domain", "x", "--engine", "quantum"])

    def test_hardware_flag_exists(self):
        parser = orchestrator._build_arg_parser()
        self.assertTrue(parser.parse_args(["--hardware"]).hardware)

    def test_defaults_preserve_old_behaviour(self):
        args = orchestrator._build_arg_parser().parse_args(["--domain", "x"])
        self.assertEqual(args.engine, orchestrator.ENGINE_LLM)
        self.assertFalse(args.time_series)
        self.assertFalse(args.expand_features)
        self.assertEqual(args.dirty_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
