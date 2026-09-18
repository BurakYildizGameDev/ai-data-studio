"""Orchestrator ve pipeline entegrasyon testleri.

Gerçek LLM çağrısı yapılmaz - FakeLLMClient kullanılır; testler deterministiktir.
"""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from ai_data_studio.core import orchestrator
from ai_data_studio.core.generator import GenerationFailedError, generate_and_execute
from ai_data_studio.core.schema_contract import SchemaContract
from ai_data_studio.core.state_manager import STATUS_DONE, STATUS_FAILED, StateManager
from ai_data_studio.services.llm_base import strip_code_fences
from ai_data_studio.tests import fake_llm


class TestSelfHealingLoop(unittest.TestCase):
    """Self-healing: hatalı kod üretildiğinde geri besleme ile düzeltilmeli."""

    def setUp(self):
        self.schema = SchemaContract.from_dict({**fake_llm.SCHEMA_JSON,
                                                "row_count_target": 3000})

    def test_succeeds_first_try(self):
        client = fake_llm.FakeLLMClient([fake_llm.GOOD_CODE])
        df, code, meta = generate_and_execute(self.schema, client, timeout=90)
        self.assertEqual(meta["attempts"], 1)
        self.assertEqual(len(df), 3000)
        self.assertEqual(client.feedback_received, [])

    def test_heals_runtime_error(self):
        client = fake_llm.FakeLLMClient([fake_llm.BROKEN_RUNTIME_CODE, fake_llm.GOOD_CODE])
        df, code, meta = generate_and_execute(self.schema, client, timeout=90)
        self.assertEqual(meta["attempts"], 2)
        self.assertEqual(len(df), 3000)
        # Hata gercekten LLM'e geri beslenmis olmali
        self.assertEqual(len(client.feedback_received), 1)
        self.assertIn("The code raised an error while running", client.feedback_received[0])

    def test_heals_schema_mismatch(self):
        client = fake_llm.FakeLLMClient([fake_llm.SCHEMA_MISMATCH_CODE, fake_llm.GOOD_CODE])
        df, code, meta = generate_and_execute(self.schema, client, timeout=90)
        self.assertEqual(meta["attempts"], 2)
        self.assertIn("does not match the schema", client.feedback_received[0])
        self.assertIn("Missing columns", client.feedback_received[0])

    def test_heals_on_third_attempt(self):
        client = fake_llm.FakeLLMClient([
            fake_llm.BROKEN_RUNTIME_CODE,
            fake_llm.SCHEMA_MISMATCH_CODE,
            fake_llm.GOOD_CODE,
        ])
        df, code, meta = generate_and_execute(self.schema, client, timeout=90)
        self.assertEqual(meta["attempts"], 3)
        self.assertEqual(len(df), 3000)

    def test_gives_up_after_max_retries(self):
        client = fake_llm.FakeLLMClient([fake_llm.BROKEN_RUNTIME_CODE])
        with self.assertRaises(GenerationFailedError) as ctx:
            generate_and_execute(self.schema, client, max_retries=3, timeout=90)
        from ai_data_studio.i18n import t as _t

        # Sablonun ilk satiri dilden bagimsiz karsilastirma noktasi.
        first_line = _t("codegen.gave_up", attempts=3, error="").splitlines()[0]
        self.assertIn(first_line, str(ctx.exception))

    def test_forbidden_import_is_reported_as_feedback(self):
        """SecurityError sandbox'ta yakalanip LLM'e geri beslenmeli, sizmamali."""
        client = fake_llm.FakeLLMClient([fake_llm.FORBIDDEN_IMPORT_CODE, fake_llm.GOOD_CODE])
        df, code, meta = generate_and_execute(self.schema, client, timeout=90)
        self.assertEqual(meta["attempts"], 2)
        self.assertEqual(len(df), 3000)
        self.assertEqual(code, fake_llm.GOOD_CODE.strip())
        self.assertEqual(len(client.feedback_received), 1)
        feedback = client.feedback_received[0]
        self.assertIn("import not allowed: os", feedback)
        self.assertIn("never ran", feedback)
        self.assertIn("FORBIDDEN IMPORT", feedback)

    def test_repeated_forbidden_import_gives_up_with_reason(self):
        client = fake_llm.FakeLLMClient([fake_llm.FORBIDDEN_IMPORT_CODE])
        with self.assertRaises(GenerationFailedError) as ctx:
            generate_and_execute(self.schema, client, max_retries=3, timeout=90)
        self.assertIn("import not allowed", str(ctx.exception))
        self.assertEqual(len(client.feedback_received), 2)


class TestAutoAlignDoesNotMaskErrors(unittest.TestCase):
    """Tip hizalama sistematik hatayi gizlememeli (canli Job #38 senaryosu)."""

    def setUp(self):
        from ai_data_studio.core.dataset_contract import DatasetContract

        self.schema = SchemaContract.from_dict({**fake_llm.SCHEMA_JSON,
                                                "row_count_target": 2000})
        self.contract = DatasetContract.from_schema(self.schema)

    def _frame(self, **overrides):
        import numpy as np
        import pandas as pd

        rng = np.random.default_rng(1)
        n = self.schema.row_count_target
        data = {
            "customer_age": rng.normal(38, 12, n).clip(18, 80),
            "basket_value": rng.lognormal(3.0, 0.6, n),
            "item_count": rng.integers(1, 30, n),
            "shipping_cost": rng.uniform(0, 25, n),
            "returned": rng.random(n) < 0.08,
        }
        data.update(overrides)
        return pd.DataFrame(data)

    def test_overflowing_lognormal_is_still_reported(self):
        import numpy as np
        from ai_data_studio.core.generator import _auto_align_tables, _sanity_check_tables

        n = self.schema.row_count_target
        tables = {self.contract.root_table: self._frame(basket_value=np.full(n, np.inf))}
        _auto_align_tables(tables, self.contract)
        issues = _sanity_check_tables(tables, self.contract)
        self.assertTrue(any("basket_value" in i and "above max" in i for i in issues),
                        issues)
        self.assertTrue(any("LOG-scale" in i for i in issues), issues)
        self.assertTrue(np.isinf(tables[self.contract.root_table]["basket_value"]).all())

    def test_out_of_bounds_noise_is_left_for_discriminator(self):
        from ai_data_studio.core.generator import _auto_align_tables

        frame = self._frame()
        frame.loc[frame.index[:100], "customer_age"] = 150.0
        tables = {self.contract.root_table: frame}
        _auto_align_tables(tables, self.contract)
        self.assertEqual(int((tables[self.contract.root_table]["customer_age"] == 150).sum()),
                         100)

    def test_float_int_column_is_rounded(self):
        import pandas as pd
        from ai_data_studio.core.generator import _auto_align_tables, _sanity_check_tables

        tables = {self.contract.root_table: self._frame()}
        _auto_align_tables(tables, self.contract)
        self.assertTrue(pd.api.types.is_integer_dtype(
            tables[self.contract.root_table]["customer_age"]))
        self.assertEqual(_sanity_check_tables(tables, self.contract), [])


class TestStripCodeFences(unittest.TestCase):
    def test_removes_python_fence(self):
        self.assertEqual(strip_code_fences("```python\nx = 1\n```"), "x = 1")

    def test_removes_bare_fence(self):
        self.assertEqual(strip_code_fences("```\nx = 1\n```"), "x = 1")

    def test_leaves_plain_code_untouched(self):
        self.assertEqual(strip_code_fences("def f():\n    return 1"), "def f():\n    return 1")

    def test_ignores_prose_around_fence(self):
        self.assertEqual(
            strip_code_fences("Here you go:\n```python\ndef f():\n    pass\n```\nEnjoy!"),
            "def f():\n    pass",
        )


class TestOrchestratorEndToEnd(unittest.TestCase):
    """Uçtan uca pipeline yürütme, çıktı üretimi ve durum kaydı testleri."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.state = StateManager(self.tmp / "state.db")
        self.cfg = orchestrator.PipelineConfig(
            domain_prompt="e-ticaret sipariş verisi",
            provider="fake",
            row_count=5000,
            random_seed=42,
            export_formats=["csv", "parquet", "json"],
            output_dir=self.tmp / "out",
        )

    def tearDown(self):
        self.state.close()
        self._tmp.cleanup()

    def _run(self, client=None, cancel_event=None):
        client = client or fake_llm.FakeLLMClient()
        iterator = orchestrator.run_pipeline(
            self.cfg, cancel_event or threading.Event(), self.state, llm_client=client
        )
        events = []
        while True:
            try:
                events.append(next(iterator))
            except StopIteration as stop:
                return events, stop.value

    def test_full_pipeline(self):
        events, result = self._run()

        # 7 adimin hepsi gorulmus
        self.assertEqual(sorted({e["step"] for e in events}), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(events[-1]["percent"], 100.0)

        # Sonuc dogru
        self.assertIsNotNone(result)
        self.assertEqual(result.schema.domain, "ecommerce_orders")
        self.assertGreater(len(result.dataframe), 0)
        self.assertLess(len(result.dataframe), 5000)  # validasyon satir ayiklamis
        self.assertEqual(list(result.dataframe.columns),
                         [c.name for c in result.schema.columns])

        # Cikti dosyalari gercekten yazilmis
        for kind in ("csv", "parquet", "json", "schema", "code", "report"):
            self.assertIn(kind, result.output_paths, "%s çıktısı yok" % kind)
            self.assertTrue(Path(result.output_paths[kind]).exists(),
                            "%s dosyasi diskte yok" % kind)

        # CSV UTF-8 ve okunabilir (Bolum 10.5)
        import pandas as pd
        reread = pd.read_csv(result.output_paths["csv"], encoding="utf-8")
        self.assertEqual(len(reread), len(result.dataframe))

        # SQLite checkpoint dogru guncellenmis
        job = self.state.get_job(result.job_id)
        self.assertEqual(job["status"], STATUS_DONE)
        self.assertEqual(job["current_step"], 7)
        self.assertEqual(job["progress"], 100.0)
        self.assertEqual(job["domain"], "ecommerce_orders")
        self.assertEqual(job["generated_rows_count"], 5000)
        self.assertEqual(job["validated_rows_count"], len(result.dataframe))
        self.assertEqual(self.state.get_schema(result.job_id)["domain"], "ecommerce_orders")

        # Rapor kaydedilmis
        stored = self.state.get_report(result.job_id)
        self.assertEqual(stored["rows_out"], len(result.dataframe))
        self.assertIn("correlations", stored)

    def test_token_totals_reach_the_summary(self):
        """get_cost_summary input/output_tokens dondurur; ozet eskiden hep 0 token basiyordu."""
        from ai_data_studio.i18n import t

        class _Metered(fake_llm.FakeLLMClient):
            def _complete(self, system, user, max_tokens=16000, temperature=None):
                self._log_usage(1000, 250, purpose="chat")
                return super()._complete(system, user, max_tokens, temperature)

        job_id = self.state.create_job(self.cfg.domain_prompt, provider="fake",
                                       model="fake-model", random_seed=42)
        client = _Metered(state_manager=self.state, job_id=job_id)
        iterator = orchestrator.run_pipeline(self.cfg, threading.Event(), self.state,
                                             job_id=job_id, llm_client=client)
        events = []
        while True:
            try:
                events.append(next(iterator))
            except StopIteration as stop:
                result = stop.value
                break
        calls = result.cost["calls"]
        self.assertGreater(calls, 0)
        self.assertEqual(result.cost["input_tokens"] + result.cost["output_tokens"], 1250 * calls)
        expected = t("run.cost.summary", calls=calls, tokens=format(1250 * calls, ","),
                     cost="%.4f" % result.cost["cost_usd"])
        self.assertTrue(any(expected in e["message"] for e in events),
                        [e["message"] for e in events if e["step"] == 7])

    def test_business_rules_enforced_in_output(self):
        _, result = self._run()
        df = result.dataframe
        self.assertTrue((df["shipping_cost"] <= df["basket_value"]).all())
        self.assertTrue(df["customer_age"].between(18, 80).all())

    def test_correlation_is_validated(self):
        _, result = self._run()
        corr = result.report["correlations"]
        self.assertEqual(len(corr), 1)
        self.assertEqual(corr[0]["pair"], ["item_count", "basket_value"])
        self.assertTrue(corr[0]["pass"], "Beklenen korelasyon olusmamis: %s" % corr[0])

    def test_reproducible_across_runs(self):
        _, first = self._run()
        _, second = self._run()
        self.assertEqual(len(first.dataframe), len(second.dataframe))
        self.assertEqual(first.dataframe["customer_age"].tolist(),
                         second.dataframe["customer_age"].tolist())

    def test_self_healing_inside_pipeline(self):
        client = fake_llm.FakeLLMClient([fake_llm.BROKEN_RUNTIME_CODE, fake_llm.GOOD_CODE])
        events, result = self._run(client)
        self.assertEqual(result.generation_meta["attempts"], 2)
        from ai_data_studio.i18n import t as _t

        self.assertTrue(any(_t("codegen.feeding_back") in e["message"]
                            for e in events))

    def test_failure_is_recorded_in_state(self):
        client = fake_llm.FakeLLMClient([fake_llm.BROKEN_RUNTIME_CODE])
        iterator = orchestrator.run_pipeline(self.cfg, threading.Event(), self.state,
                                             llm_client=client)
        with self.assertRaises(GenerationFailedError):
            while True:
                next(iterator)
        job = self.state.list_jobs(1)[0]
        self.assertEqual(job["status"], STATUS_FAILED)
        from ai_data_studio.i18n import t as _t

        first_line = _t("codegen.gave_up", attempts=3, error="").splitlines()[0]
        self.assertIn(first_line, job["error"])

    def test_cancel_stops_pipeline(self):
        cancel = threading.Event()
        iterator = orchestrator.run_pipeline(self.cfg, cancel, self.state,
                                             llm_client=fake_llm.FakeLLMClient())
        next(iterator)          # [1] servis kontrolu
        cancel.set()
        with self.assertRaises(orchestrator.PipelineCancelled):
            while True:
                next(iterator)
        self.assertEqual(self.state.list_jobs(1)[0]["status"], "cancelled")


class TestPipelineWorker(unittest.TestCase):
    """Worker thread widget'a dokunmaz, sadece queue'ya event basar."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.state = StateManager(self.tmp / "state.db")

    def tearDown(self):
        self.state.close()
        self._tmp.cleanup()

    def _task(self, cfg, client):
        def task_fn(cancel_event):
            return orchestrator.run_pipeline(cfg, cancel_event, self.state, llm_client=client)
        return task_fn

    def test_llm_progress_callback_is_attached_to_the_client(self):
        """Cagri suruyorken gelen ara durumlar icin istemciye kanci takilmali.

        Generator LLM cagrisinin icindeyken yield edemez; canli akis ancak bu
        geri cagirma ile disari cikabiliyor.
        """
        cfg = orchestrator.PipelineConfig(
            domain_prompt="test", provider="fake", row_count=2000,
            export_formats=["csv"], output_dir=self.tmp / "out",
        )
        client = fake_llm.FakeLLMClient()
        seen = []
        iterator = orchestrator.run_pipeline(
            cfg, threading.Event(), self.state, llm_client=client,
            llm_progress_cb=seen.append)

        # [1] adimi istemciyi hazirlar; ilk birkac olay yeterli.
        for _ in range(3):
            next(iterator)
        iterator.close()

        self.assertIsNotNone(client.progress_cb)
        client.progress_cb("agy adımı: agent_response (DONE)")
        self.assertEqual(seen, ["agy adımı: agent_response (DONE)"])

    def test_worker_emits_progress_then_done(self):
        import queue as queue_mod

        cfg = orchestrator.PipelineConfig(
            domain_prompt="test", provider="fake", row_count=2000,
            export_formats=["csv"], output_dir=self.tmp / "out",
        )
        ui_queue: "queue_mod.Queue" = queue_mod.Queue()
        cancel = threading.Event()
        worker = orchestrator.PipelineWorker(
            self._task(cfg, fake_llm.FakeLLMClient()), ui_queue, cancel
        )
        worker.start()
        worker.join(timeout=180)
        self.assertFalse(worker.is_alive(), "Worker zamaninda bitmedi")

        events = []
        while not ui_queue.empty():
            events.append(ui_queue.get_nowait())

        kinds = [k for k, _ in events]
        self.assertIn("progress", kinds)
        self.assertEqual(kinds[-1], "done")
        self.assertIsInstance(events[-1][1], orchestrator.PipelineResult)

    def test_worker_reports_error_without_raising(self):
        import queue as queue_mod

        cfg = orchestrator.PipelineConfig(
            domain_prompt="test", provider="fake", row_count=2000,
            export_formats=["csv"], output_dir=self.tmp / "out",
        )
        ui_queue: "queue_mod.Queue" = queue_mod.Queue()
        client = fake_llm.FakeLLMClient([fake_llm.BROKEN_RUNTIME_CODE])
        worker = orchestrator.PipelineWorker(
            self._task(cfg, client), ui_queue, threading.Event()
        )
        worker.start()
        worker.join(timeout=180)

        events = []
        while not ui_queue.empty():
            events.append(ui_queue.get_nowait())
        self.assertEqual(events[-1][0], "error")
        self.assertIsInstance(events[-1][1], str)


class TestProgressLevels(unittest.TestCase):
    """İlerleme olayları önem derecesini KENDİLERİ taşımalı.

    Arayüz eskiden mesajın metninde "uyari"/"hata" arıyordu. Metne bağlı bir
    eşleşme, mesajlar çevrildiği anda sessizce bozulur ve uyarılar normal
    satır gibi görünür.
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

    def _events(self, client=None, **overrides):
        import threading
        from ai_data_studio.core import orchestrator
        from ai_data_studio.tests import fake_llm

        params = dict(domain_prompt="e-ticaret", provider="fake", row_count=2000,
                      export_formats=["csv"], output_dir=self.tmp / "out")
        params.update(overrides)
        cfg = orchestrator.PipelineConfig(**params)
        iterator = orchestrator.run_pipeline(
            cfg, threading.Event(), self.state,
            llm_client=client or fake_llm.FakeLLMClient())
        events = []
        while True:
            try:
                events.append(next(iterator))
            except StopIteration:
                return events

    def test_every_event_carries_a_valid_level(self):
        from ai_data_studio import config

        for event in self._events():
            self.assertIn("level", event, event["message"])
            self.assertIn(event["level"], config.PROGRESS_LEVELS, event["message"])

    def test_default_level_is_info(self):
        from ai_data_studio import config

        events = self._events()
        self.assertTrue(any(e["level"] == config.PROGRESS_INFO for e in events))

    def test_warnings_are_marked_as_warnings(self):
        """Şema uyarıları metinden değil alandan anlaşılmalı."""
        import json
        from ai_data_studio import config
        from ai_data_studio.tests import fake_llm

        # Bilinmeyen kolona bakan bir korelasyon kurali sema UYARISI uretir
        # (hata degil: kural dusurulur, kosu devam eder).
        schema = json.loads(json.dumps(fake_llm.SCHEMA_JSON))
        schema["correlations"].append({"columns": ["boyle_bir_kolon_yok", "item_count"],
                                      "expected_sign": "positive", "min_r": 0.3})
        client = fake_llm.FakeLLMClient(
            schema_override="```json\n%s\n```" % json.dumps(schema))

        events = self._events(client=client)
        warnings = [e for e in events if e["level"] == config.PROGRESS_WARNING]
        self.assertTrue(warnings, "hicbir olay uyari olarak isaretlenmedi")

    def test_sandbox_step_comes_from_a_flag_not_the_word_sandbox(self):
        """Adım numarası mesajda 'sandbox' kelimesi aranarak seçilmemeli."""
        events = self._events()
        sandbox_events = [e for e in events if e["step"] == 5 and e["percent"] < 100]
        self.assertTrue(sandbox_events, "sandbox adimi hic raporlanmadi")

    def test_generator_passes_level_through(self):
        """Kod üretimi başarısız olduğunda satır uyarı seviyesinde gelmeli."""
        from ai_data_studio import config
        from ai_data_studio.core.generator import generate_and_execute
        from ai_data_studio.core.schema_contract import SchemaContract
        from ai_data_studio.tests import fake_llm

        seen = []
        client = fake_llm.FakeLLMClient([fake_llm.BROKEN_RUNTIME_CODE,
                                         fake_llm.GOOD_CODE])
        schema = SchemaContract.from_dict({**fake_llm.SCHEMA_JSON,
                                           "row_count_target": 1000})
        generate_and_execute(schema, client, timeout=90,
                             on_progress=lambda m, lv=config.PROGRESS_INFO,
                             sb=False: seen.append((m, lv)))

        self.assertTrue([m for m, lv in seen if lv == config.PROGRESS_WARNING],
                        "basarisiz deneme uyari olarak bildirilmedi")

    def test_validator_passes_level_through(self):
        """Korelasyon uyarısı validator'dan uyarı seviyesiyle çıkmalı."""
        import pandas as pd
        from ai_data_studio import config
        from ai_data_studio.core import validator
        from ai_data_studio.core.schema_contract import SchemaContract

        schema = SchemaContract.from_dict({
            "domain": "test", "description": "test", "row_count_target": 300,
            "columns": [
                {"name": "a", "type": "float", "min": 0, "max": 100},
                {"name": "b", "type": "float", "min": 0, "max": 100},
            ],
            "correlations": [{"columns": ["a", "b"], "expected_sign": "positive",
                              "min_r": 0.9}],
        })
        rng = __import__("numpy").random.default_rng(3)
        df = pd.DataFrame({"a": rng.uniform(0, 100, 300),
                           "b": rng.uniform(0, 100, 300)})

        seen = []
        validator.run_validation(
            df, schema,
            on_progress=lambda m, lv=config.PROGRESS_INFO: seen.append((m, lv)))

        self.assertTrue([m for m, lv in seen if lv == config.PROGRESS_WARNING],
                        "karsilanmayan korelasyon uyari olarak bildirilmedi")


if __name__ == "__main__":
    unittest.main()


class TestSchemaSelfHealing(unittest.TestCase):
    """Şema üretimi de kod üretimi gibi hatayi LLM'e geri besleyip duzeltmeli."""

    def _client(self, responses):
        from ai_data_studio.services.llm_base import BaseLLMClient

        class _Seq(BaseLLMClient):
            provider = "fake"

            def __init__(self):
                super().__init__("fake-model")
                self.sent = []
                self._i = 0

            def health_check(self):
                return True

            def _complete(self, system, user, max_tokens=16000, temperature=None):
                self.sent.append(user)
                out = responses[min(self._i, len(responses) - 1)]
                self._i += 1
                return out

        return _Seq()

    def test_invalid_schema_is_corrected_on_retry(self):
        import json
        bad = json.dumps({
            "domain": "t", "columns": [{"name": "a", "type": "int"}],
            "correlations": [{"columns": ["a", "yok"], "expected_sign": "positive"}],
            "business_rules": [],
        })
        good = json.dumps({
            "domain": "t",
            "columns": [{"name": "a", "type": "int"}, {"name": "b", "type": "float"}],
            "correlations": [{"columns": ["a", "b"], "expected_sign": "positive"}],
            "business_rules": [],
        })
        # Ilk yanit gecerli ama korelasyonu dusurulur (olumcul degil) -> tek atista biter
        client = self._client([bad, good])
        schema = client.generate_schema("test", row_count=100, seed=1)
        self.assertEqual(schema.domain, "t")

    def test_hard_error_triggers_feedback_retry(self):
        import json
        broken = "bu bir JSON değil"
        good = json.dumps({"domain": "t", "columns": [{"name": "a", "type": "int"}]})
        client = self._client([broken, good])
        schema = client.generate_schema("test", row_count=100, seed=1)
        self.assertEqual(schema.domain, "t")
        self.assertEqual(len(client.sent), 2)
        self.assertIn("REJECTED by the schema validator", client.sent[1])

    def test_gives_up_after_max_retries_with_clear_message(self):
        from ai_data_studio.core.schema_contract import SchemaValidationError
        client = self._client(["hâlâ JSON değil"])
        with self.assertRaises(SchemaValidationError) as ctx:
            client.generate_schema("test", row_count=100, seed=1)
        from ai_data_studio.i18n import t

        self.assertIn(t("service.error.schema_retries", attempts=3,
                        error="").split(".")[0], str(ctx.exception))

    def test_feedback_to_the_llm_is_english_whatever_the_ui_language(self):
        """Türkçe arayüzde doğrulama hatası modele Türkçe gidiyordu."""
        import json

        from ai_data_studio import i18n

        i18n.set_language("tr")
        self.addCleanup(i18n.reset_for_tests)
        bad = json.dumps({"domain": "t", "columns": [{"name": "tier", "type": "category"}]})
        good = json.dumps({"domain": "t", "columns": [{"name": "a", "type": "int"}]})
        client = self._client([bad, good])
        client.generate_schema("test", row_count=100, seed=1)

        with i18n.language_override("en"):
            english = i18n.t("schema.error.categories_required", where="columns[0]",
                             name="tier")
        turkish = i18n.t("schema.error.categories_required", where="columns[0]", name="tier")
        self.assertNotEqual(english, turkish)
        self.assertIn(english, client.sent[1])
        self.assertNotIn(turkish, client.sent[1])
        # Kullanıcıya dönen metinler hâlâ arayüz dilinde.
        self.assertEqual(i18n.get_language(), "tr")

    def test_final_error_to_the_user_stays_in_the_ui_language(self):
        from ai_data_studio import i18n
        from ai_data_studio.core.schema_contract import SchemaValidationError

        i18n.set_language("tr")
        self.addCleanup(i18n.reset_for_tests)
        client = self._client(["hâlâ JSON değil"])
        with self.assertRaises(SchemaValidationError) as ctx:
            client.generate_dataset_schema("test", row_count=100, seed=1)
        self.assertIn(i18n.t("service.error.contract_retries", attempts=3,
                             error="").split(":")[0], str(ctx.exception))

    def test_user_settings_still_override_after_retry(self):
        import json
        good = json.dumps({"domain": "t", "row_count_target": 999999,
                           "random_seed": 7, "columns": [{"name": "a", "type": "int"}]})
        client = self._client(["bozuk", good])
        schema = client.generate_schema("test", row_count=250, seed=99, locale="tr_TR")
        self.assertEqual(schema.row_count_target, 250)
        self.assertEqual(schema.random_seed, 99)
        self.assertEqual(schema.faker_locale, "tr_TR")


class TestRepeatedErrorEscalation(unittest.TestCase):
    """Aynı hata tekrarlaninca dongü 'yamala' demeyi birakip yaklasim degistirtmeli."""

    def setUp(self):
        self.schema = SchemaContract.from_dict({**fake_llm.SCHEMA_JSON,
                                                "row_count_target": 1000})

    def test_error_signature_ignores_paths_and_line_numbers(self):
        """Aynı kök hata, farkli geçici dosya/satirda -> aynı imza."""
        from ai_data_studio.core.generator import _error_signature
        a = _error_signature(
            "Traceback (most recent call last):\n"
            "  File \"C:\\work\\aids_sbx_abc\\user_code.py\", line 39, in generate_data\n"
            "AttributeError: Unknown formatter '0' with locale 'en_US'")
        b = _error_signature(
            "Traceback (most recent call last):\n"
            "  File \"C:\\work\\aids_sbx_xyz\\user_code.py\", line 77, in generate_data\n"
            "AttributeError: Unknown formatter '0' with locale 'en_US'")
        self.assertEqual(a, b)

    def test_error_signature_strips_windows_paths_in_message(self):
        from ai_data_studio.core.generator import _error_signature
        a = _error_signature(r"FileNotFoundError: C:\work\aids_sbx_abc\out.parquet yok")
        b = _error_signature(r"FileNotFoundError: C:\work\aids_sbx_xyz\out.parquet yok")
        self.assertEqual(a, b)
        self.assertIn("<yol>", a)

    def test_different_errors_have_different_signatures(self):
        from ai_data_studio.core.generator import _error_signature
        self.assertNotEqual(_error_signature("AttributeError: Unknown formatter"),
                            _error_signature("ValueError: shapes do not match"))

    def test_escalation_after_repeated_failure(self):
        """Aynı hatayi iki kez veren modele escalate=True gonderilmeli."""
        calls = []

        class _Stubborn(fake_llm.FakeLLMClient):
            def fix_code(self, previous_code, error_feedback, schema,
                         history=None, escalate=False):
                calls.append({"escalate": escalate, "history": list(history or [])})
                # 3. denemede duzgun kod ver
                return fake_llm.GOOD_CODE if len(calls) >= 2 else fake_llm.BROKEN_RUNTIME_CODE

        client = _Stubborn([fake_llm.BROKEN_RUNTIME_CODE])
        df, _, meta = generate_and_execute(self.schema, client, timeout=90)

        self.assertEqual(meta["attempts"], 3)
        self.assertFalse(calls[0]["escalate"])   # ilk hata - normal geri besleme
        self.assertTrue(calls[1]["escalate"])    # ayni hata tekrarlandi - yaklasim degistir
        self.assertGreater(len(calls[1]["history"]), 1)

    def test_history_is_passed_to_fix_code(self):
        captured = {}

        class _Recorder(fake_llm.FakeLLMClient):
            def fix_code(self, previous_code, error_feedback, schema,
                         history=None, escalate=False):
                captured["history"] = list(history or [])
                return fake_llm.GOOD_CODE

        client = _Recorder([fake_llm.BROKEN_RUNTIME_CODE])
        generate_and_execute(self.schema, client, timeout=90)
        self.assertEqual(len(captured["history"]), 1)
        self.assertIn("NameError", captured["history"][0])

    def test_old_signature_clients_still_work(self):
        """history/escalate bilmeyen eski istemciler kirilmamali."""
        class _Legacy(fake_llm.FakeLLMClient):
            def fix_code(self, previous_code, error_feedback, schema):
                return fake_llm.GOOD_CODE

        client = _Legacy([fake_llm.BROKEN_RUNTIME_CODE])
        df, _, meta = generate_and_execute(self.schema, client, timeout=90)
        self.assertEqual(meta["attempts"], 2)
        self.assertEqual(len(df), 1000)


class TestFakerGuidance(unittest.TestCase):
    """Kod prompt'u Faker'in tuzakli sablon API'lerini açıkça yasaklamali."""

    def test_prompt_forbids_faker_template_apis(self):
        client = fake_llm.FakeLLMClient()
        prompt = client._sandbox_prompt_vars()
        from ai_data_studio.services.llm_base import CODE_SYSTEM_PROMPT
        text = CODE_SYSTEM_PROMPT.format(locale="tr_TR", **prompt)
        for trap in ("pystr_format", "bothify", "lexify", "numerify"):
            self.assertIn(trap, text, "%s yasagi prompt'ta yok" % trap)
        self.assertIn("PREFER numpy", text)


class TestDiagnosticHints(unittest.TestCase):
    """Ham traceback yerine somut duzeltme talimati - kucuk Modeller için kritik."""

    def test_dtype_cast_error(self):
        from ai_data_studio.core.generator import diagnostic_hint
        hint = diagnostic_hint(
            "numpy._core._exceptions._UFuncOutputCastingError: Cannot cast ufunc 'add' "
            "output from dtype('float64') to dtype('int64')")
        self.assertIn("DTYPE", hint)
        self.assertIn("astype(int)", hint)

    def test_faker_formatter_error(self):
        from ai_data_studio.core.generator import diagnostic_hint
        hint = diagnostic_hint("AttributeError: Unknown formatter '0' with locale 'en_US'")
        self.assertIn("FAKER", hint)
        self.assertIn("pystr_format", hint)

    def test_timeout_hint(self):
        from ai_data_studio.core.generator import diagnostic_hint
        hint = diagnostic_hint("Timeout: the code did not finish within 90 seconds")
        self.assertIn("PERFORMANCE", hint)

    def test_memory_hint(self):
        from ai_data_studio.core.generator import diagnostic_hint
        self.assertIn("MEMORY", diagnostic_hint("Memory limit exceeded: 2400 MB > 2048 MB"))

    def test_broadcast_hint(self):
        from ai_data_studio.core.generator import diagnostic_hint
        self.assertIn("SHAPE", diagnostic_hint("ValueError: could not broadcast input array"))

    def test_forbidden_import_hint_lists_allowed_modules(self):
        from ai_data_studio.core.generator import diagnostic_hint
        hint = diagnostic_hint("Sandbox policy violation -> import not allowed: os (line 2)")
        self.assertIn("FORBIDDEN IMPORT", hint)
        self.assertIn("numpy", hint)
        self.assertNotIn("{allowed_imports}", hint)

    def test_syntax_error_hint(self):
        from ai_data_studio.core.generator import diagnostic_hint
        hint = diagnostic_hint("The generated code could not be parsed (line 3): invalid syntax")
        self.assertIn("SYNTAX ERROR", hint)

    def test_wrong_numpy_keyword_hint_explains_lognormal(self):
        """Canli Job #38: rng.lognormal(mean=50000, scale=10000) uc denemede tekrarlandi."""
        from ai_data_studio.core.generator import diagnostic_hint
        hint = diagnostic_hint(
            "TypeError: lognormal() got an unexpected keyword argument 'scale'")
        self.assertIn("WRONG PARAMETER NAME", hint)
        self.assertIn("rng.lognormal(mean, sigma, size)", hint)
        self.assertIn("log1p", hint)

    def test_missing_import_hint_names_the_import_line(self):
        """Canli Job #37: Faker import edilmeden kullanildi."""
        from ai_data_studio.core.generator import diagnostic_hint
        hint = diagnostic_hint("NameError: name 'Faker' is not defined")
        self.assertIn("MISSING IMPORT", hint)
        self.assertIn("from faker import Faker", hint)
        self.assertIn("import numpy as np",
                      diagnostic_hint("NameError: name 'np' is not defined"))

    def test_unknown_undefined_name_keeps_generic_hint(self):
        from ai_data_studio.core.generator import diagnostic_hint
        hint = diagnostic_hint("NameError: name 'undefined_name' is not defined")
        self.assertIn("UNDEFINED NAME", hint)

    def test_ndtr_missing_import_names_scipy_special(self):
        """Canli 1.5b kosusu: COPULA ornegi `ndtr(z_corr)` oldu, import yoktu."""
        from ai_data_studio.core.generator import diagnostic_hint
        hint = diagnostic_hint("NameError: name 'ndtr' is not defined")
        self.assertIn("from scipy.special import ndtr", hint)

    def test_wrong_module_import_hint_points_to_scipy_special(self):
        """Canli 1.5b: `from scipy.stats import ndtr`."""
        from ai_data_studio.core.generator import diagnostic_hint
        hint = diagnostic_hint("ImportError: cannot import name 'ndtr' from 'scipy.stats'")
        self.assertIn("from scipy.special import ndtr", hint)

    def test_faker_instance_seed_hint(self):
        """Canli 1.5b: `fake.seed(seed)` iki denemede ayni TypeError."""
        from ai_data_studio.core.generator import diagnostic_hint
        hint = diagnostic_hint("TypeError: Calling `.seed()` on instances is deprecated. "
                               "Use the class method `Faker.seed()` instead.")
        self.assertIn("Faker.seed(seed)", hint)

    def test_key_error_hint_says_contract_is_not_available_at_runtime(self):
        """Canli 1.5b kosusu: `schema["churned"]["min"]` iki denemede KeyError."""
        from ai_data_studio.core.generator import diagnostic_hint
        hint = diagnostic_hint('File "user_code.py", line 39\nKeyError: \'min\'')
        self.assertIn("KEY ERROR", hint)
        self.assertIn("NOT available", hint)


class TestAutoImportRepair(unittest.TestCase):
    """Eksik import LLM turu harcamadan onarilir (canli 1.5b: `Faker.seed` importsuz)."""

    MISSING_FAKER = (
        "import numpy as np\n"
        "import pandas as pd\n"
        "\n"
        "def generate_data(n_rows, seed):\n"
        "    Faker.seed(seed)\n"
    ) + fake_llm.GOOD_CODE.split("def generate_data(n_rows, seed):\n", 1)[1]

    def test_patch_inserts_the_import_line(self):
        from ai_data_studio.core.generator import patch_missing_import

        code, line = patch_missing_import("x = ndtr(1)\n", "NameError: name 'ndtr' is not defined")
        self.assertEqual(line, "from scipy.special import ndtr")
        self.assertEqual(code, "from scipy.special import ndtr\nx = ndtr(1)\n")

    def test_patch_keeps_future_import_first(self):
        from ai_data_studio.core.generator import patch_missing_import

        code, _ = patch_missing_import("from __future__ import annotations\nx = np.ones(2)\n",
                                       "NameError: name 'np' is not defined")
        self.assertTrue(code.startswith("from __future__ import annotations\nimport numpy as np\n"))

    def test_patch_leaves_unknown_or_already_imported_names_alone(self):
        from ai_data_studio.core.generator import patch_missing_import

        self.assertIsNone(patch_missing_import("x = y\n", "NameError: name 'y' is not defined"))
        self.assertIsNone(patch_missing_import("import numpy as np\n",
                                               "NameError: name 'np' is not defined"))
        self.assertIsNone(patch_missing_import("x = 1\n", "ValueError: bad"))

    def test_loop_repairs_missing_import_without_a_fix_call(self):
        schema = SchemaContract.from_dict({**fake_llm.SCHEMA_JSON, "row_count_target": 300})
        client = fake_llm.FakeLLMClient([self.MISSING_FAKER])
        messages = []
        df, code, meta = generate_and_execute(
            schema, client, timeout=60,
            on_progress=lambda message, *args: messages.append(message))
        self.assertEqual(len(df), 300)
        self.assertEqual(client.feedback_received, [])        # LLM'e hic geri beslenmedi
        self.assertEqual(meta["attempts"], 1)                  # deneme hakki harcanmadi
        self.assertEqual(meta["auto_imports"], ["from faker import Faker"])
        self.assertTrue(code.startswith("from faker import Faker\n"))
        self.assertTrue(any("from faker import Faker" in m for m in messages))

    def test_unknown_error_gives_no_hint(self):
        from ai_data_studio.core.generator import diagnostic_hint
        self.assertEqual(diagnostic_hint("SomeWeirdError: hiç gorulmemis bir sey"), "")

    def test_hint_is_appended_to_feedback(self):
        """Dongü ipucunu gercekten LLM'e iletmeli."""
        captured = {}

        class _Recorder(fake_llm.FakeLLMClient):
            def fix_code(self, previous_code, error_feedback, schema,
                         history=None, escalate=False):
                captured["feedback"] = error_feedback
                return fake_llm.GOOD_CODE

        dtype_bug = (
            "import numpy as np\n"
            "import pandas as pd\n"
            "\n"
            "def generate_data(n_rows, seed):\n"
            "    rng = np.random.default_rng(seed)\n"
            "    x = rng.integers(0, 10, n_rows)\n"
            "    x += 0.5\n"
            "    return pd.DataFrame({'customer_age': x})\n"
        )
        schema = SchemaContract.from_dict({**fake_llm.SCHEMA_JSON, "row_count_target": 500})
        client = _Recorder([dtype_bug])
        generate_and_execute(schema, client, timeout=60)
        self.assertIn("HOW TO FIX", captured["feedback"])
        self.assertIn("DTYPE", captured["feedback"])

    def test_escalation_text_is_not_faker_specific(self):
        from ai_data_studio.services.llm_base import ESCALATION_BLOCK
        self.assertIn("float64", ESCALATION_BLOCK)
        self.assertIn("in-place", ESCALATION_BLOCK)


class TestRelationalPipeline(unittest.TestCase):
    """Iliskisel mod: orchestrator cok tabloyu uctan uca tasiyor mu (Bolum 1-A)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.state = StateManager(self.tmp / "state.db")
        self.addCleanup(self.state.close)
        self.cfg = orchestrator.PipelineConfig(
            domain_prompt="saas faturalama",
            provider="fake",
            row_count=2000,
            random_seed=42,
            export_formats=["csv"],
            output_dir=self.tmp / "out",
            relational=True,
        )

    def _run(self, client=None):
        client = client or fake_llm.FakeRelationalLLMClient()
        iterator = orchestrator.run_pipeline(
            self.cfg, threading.Event(), self.state, llm_client=client
        )
        events = []
        while True:
            try:
                events.append(next(iterator))
            except StopIteration as stop:
                return events, stop.value

    # -- sozlesme ve veri --------------------------------------------------- #
    def test_all_tables_are_produced(self):
        _, result = self._run()
        self.assertEqual(sorted(result.tables), ["customers", "orders"])
        for name, df in result.tables.items():
            self.assertGreater(len(df), 0, "%s tablosu bos" % name)

    def test_root_table_is_backward_compatible(self):
        """dataframe ve schema kok tabloyu gostermeye devam etmeli."""
        _, result = self._run()
        self.assertEqual(result.contract.root_table, "customers")
        self.assertIs(result.dataframe, result.tables["customers"])
        self.assertEqual(result.schema.table_name, "customers")

    def test_row_count_applies_to_root_table_only(self):
        _, result = self._run()
        # Kok tablo istenen satir sayisindan cikar (validasyon biraz eler),
        # cocuk tablonun buyuklugu kardinaliteden turer.
        self.assertLessEqual(len(result.tables["customers"]), 2000)
        self.assertGreater(len(result.tables["orders"]), len(result.tables["customers"]))

    # -- iliskisel butunluk ------------------------------------------------- #
    def test_no_orphan_foreign_keys_remain(self):
        _, result = self._run()
        known = set(result.tables["customers"]["customer_id"])
        self.assertTrue(set(result.tables["orders"]["customer_id"]).issubset(known))
        self.assertTrue(result.report["relational"]["pass"],
                        result.report["relational"])

    def test_primary_keys_are_unique(self):
        _, result = self._run()
        for table, pk in (("customers", "customer_id"), ("orders", "order_id")):
            col = result.tables[table][pk]
            self.assertFalse(col.duplicated().any(), "%s.%s tekil degil" % (table, pk))

    def test_orphans_are_repaired_after_single_table_cleaning(self):
        """SIRA TESTI: uydurma yabanci anahtarli kod bile temiz cikti vermeli."""
        client = fake_llm.FakeRelationalLLMClient(
            code_sequence=[fake_llm.ORPHAN_RELATIONAL_CODE])
        _, result = self._run(client)
        rel = result.report["relational"]
        self.assertGreater(rel["repair"]["removed_total"], 0,
                           "yetim satir uretilmedi, test anlamsiz")
        known = set(result.tables["customers"]["customer_id"])
        self.assertTrue(set(result.tables["orders"]["customer_id"]).issubset(known))
        self.assertTrue(all(r["pass"] for r in rel["foreign_keys"]))

    def test_repair_disabled_reports_failure_instead_of_deleting(self):
        client = fake_llm.FakeRelationalLLMClient(
            code_sequence=[fake_llm.ORPHAN_RELATIONAL_CODE])
        self.cfg.repair_orphans = False
        _, result = self._run(client)
        rel = result.report["relational"]
        self.assertNotIn("repair", rel)
        self.assertFalse(rel["pass"])
        # Satirlar silinmemis, yalnizca raporlanmis olmali.
        self.assertGreater(rel["foreign_keys"][0]["orphan_rows"], 0)

    # -- rapor yapisi ------------------------------------------------------- #
    def test_report_has_per_table_and_relational_sections(self):
        _, result = self._run()
        self.assertEqual(sorted(result.report["tables"]), ["customers", "orders"])
        for name in ("customers", "orders"):
            self.assertIn("retention_pct", result.report["tables"][name])
        self.assertIn("foreign_keys", result.report["relational"])
        self.assertIn("cardinality", result.report["relational"])
        # Ust duzey duz alanlar kok tabloyu anlatmaya devam eder.
        self.assertEqual(result.report["rows_out"], len(result.tables["customers"]))

    def test_report_is_json_serialisable(self):
        """report[tables] kok raporu kendi icine koyarsa dongu olusur - olmamali."""
        _, result = self._run()
        text = json.dumps(result.report, ensure_ascii=False, default=str)
        self.assertIn("relational", text)
        stored = self.state.get_report(result.job_id)
        self.assertIn("tables", stored)

    # -- cikti dosyalari ---------------------------------------------------- #
    def test_writes_one_file_per_table_plus_manifest(self):
        _, result = self._run()
        self.assertIn("csv:customers", result.output_paths)
        self.assertIn("csv:orders", result.output_paths)
        self.assertIn("manifest", result.output_paths)
        for key in ("csv:customers", "csv:orders", "manifest", "schema", "code", "report"):
            self.assertTrue(Path(result.output_paths[key]).exists(), "%s yok" % key)
        self.assertTrue(Path(result.output_paths["csv:orders"]).name.endswith("_orders.csv"))

    def test_manifest_describes_tables_and_relationships(self):
        _, result = self._run()
        manifest = json.loads(
            Path(result.output_paths["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["root_table"], "customers")
        self.assertEqual(manifest["generation_order"], ["customers", "orders"])
        self.assertEqual(manifest["tables"]["orders"]["primary_key"], "order_id")
        self.assertEqual(manifest["tables"]["customers"]["rows"],
                         len(result.tables["customers"]))
        self.assertEqual(manifest["relationships"][0]["child_table"], "orders")
        self.assertTrue(manifest["integrity"]["pass"])
        self.assertTrue(Path(manifest["tables"]["orders"]["files"]["csv"]).exists())

    def test_saved_schema_is_the_full_dataset_contract(self):
        from ai_data_studio.core.dataset_contract import DatasetContract

        _, result = self._run()
        stored = self.state.get_schema(result.job_id)
        self.assertEqual(len(stored["tables"]), 2)
        self.assertEqual(stored["root_table"], "customers")
        self.assertEqual(DatasetContract.from_dict(stored).table_names,
                         ["customers", "orders"])

    def test_checkpoint_points_at_manifest(self):
        _, result = self._run()
        job = self.state.get_job(result.job_id)
        self.assertEqual(job["status"], STATUS_DONE)
        self.assertTrue(job["output_path"].endswith("_manifest.json"))
        self.assertEqual(job["validated_rows_count"],
                         sum(len(df) for df in result.tables.values()))

    # -- sinir degerler ----------------------------------------------------- #
    def test_max_tables_below_two_is_rejected(self):
        """Iliskisel mod en az iki tablo demek; aksi halde istem kendisiyle celisir."""
        self.cfg.max_tables = 1
        with self.assertRaises(ValueError) as ctx:
            self._run()
        self.assertIn("max_tables", str(ctx.exception))

    def test_max_tables_above_hard_limit_is_rejected(self):
        from ai_data_studio.core.dataset_contract import MAX_TABLES

        self.cfg.max_tables = MAX_TABLES + 1
        with self.assertRaises(ValueError):
            self._run()

    def test_single_table_mode_ignores_max_tables(self):
        """Kapali modda bu alanin hicbir etkisi olmamali."""
        self.cfg.relational = False
        self.cfg.max_tables = 1
        _, result = self._run(fake_llm.FakeLLMClient())
        self.assertGreater(len(result.dataframe), 0)

    # -- geriye uyum -------------------------------------------------------- #
    def test_single_table_mode_reports_stay_flat(self):
        """relational=False iken rapor bugunku duz yapisini korumali."""
        self.cfg.relational = False
        _, result = self._run(fake_llm.FakeLLMClient())
        self.assertNotIn("tables", result.report)
        self.assertNotIn("relational", result.report)
        self.assertNotIn("manifest", result.output_paths)
        self.assertIn("csv", result.output_paths)
        # tables alani yine de doldurulur: tek elemanli.
        self.assertEqual(list(result.tables), ["ecommerce_orders"])
        self.assertIs(result.tables["ecommerce_orders"], result.dataframe)


class TestProgressIsMonotonic(unittest.TestCase):
    """Ilerleme cubugu geri sarmamali (Bolum 3).

    Seed adimi (3) semadan (2) once kosuyor ve self-healing yeniden denemesi
    sandbox'tan kod uretimine donuyor; ikisi de dogru ama yuzdeyi geri sariyordu.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.state = StateManager(self.tmp / "state.db")
        self.addCleanup(self.state.close)
        self.cfg = orchestrator.PipelineConfig(
            domain_prompt="e-ticaret sipariş verisi",
            provider="fake",
            row_count=3000,
            export_formats=["csv"],
            output_dir=self.tmp / "out",
        )

    def _percents(self, client):
        iterator = orchestrator.run_pipeline(
            self.cfg, threading.Event(), self.state, llm_client=client)
        seen = []
        while True:
            try:
                seen.append(next(iterator)["percent"])
            except StopIteration:
                return seen

    def _assert_non_decreasing(self, percents):
        self.assertTrue(percents, "hiç ilerleme olayı üretilmedi")
        for before, after in zip(percents, percents[1:]):
            self.assertGreaterEqual(after, before,
                                    "yüzde geri gitti: %s -> %s" % (before, after))
        self.assertEqual(percents[-1], 100.0)

    def test_percent_never_decreases_on_clean_run(self):
        self._assert_non_decreasing(self._percents(fake_llm.FakeLLMClient()))

    def test_percent_never_decreases_through_self_healing_retry(self):
        client = fake_llm.FakeLLMClient(
            code_sequence=[fake_llm.BROKEN_RUNTIME_CODE, fake_llm.GOOD_CODE])
        self._assert_non_decreasing(self._percents(client))

    def test_step_labels_keep_their_canonical_numbers(self):
        """Yuzde duzeltmesi adim numaralarini degistirmemeli (spec'teki sira)."""
        iterator = orchestrator.run_pipeline(
            self.cfg, threading.Event(), self.state, llm_client=fake_llm.FakeLLMClient())
        names = {}
        while True:
            try:
                event = next(iterator)
            except StopIteration:
                break
            names[event["step"]] = event["name"]
        self.assertEqual(names[2], orchestrator.STEP_NAMES[2])
        self.assertEqual(names[3], orchestrator.STEP_NAMES[3])


class TestProjectPlannerPipeline(unittest.TestCase):
    """Proje modu: kullanici veriyi degil PROJEYI anlatir (Bolum 2)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.state = StateManager(self.tmp / "state.db")
        self.addCleanup(self.state.close)
        self.cfg = orchestrator.PipelineConfig(
            domain_prompt="abonelerden hangileri ayrilacak",
            project_prompt="abonelerden hangilerinin gelecek ay ayrilacagini tahmin et",
            provider="fake",
            row_count=2000,
            random_seed=42,
            export_formats=["csv"],
            output_dir=self.tmp / "out",
        )

    def _run(self, client=None):
        client = client or fake_llm.FakePlannerLLMClient()
        iterator = orchestrator.run_pipeline(
            self.cfg, threading.Event(), self.state, llm_client=client)
        events = []
        while True:
            try:
                events.append(next(iterator))
            except StopIteration as stop:
                return events, stop.value

    # -- plan sonuca tasiniyor mu ------------------------------------------ #
    def test_result_carries_the_plan(self):
        _, result = self._run()
        self.assertIsNotNone(result.plan)
        self.assertEqual(result.plan.task_type, "binary_classification")
        self.assertEqual(result.plan.target.label(), "customers.churned")
        self.assertAlmostEqual(result.plan.positive_class_ratio, 0.2)

    def test_planner_decides_the_tables(self):
        _, result = self._run()
        self.assertEqual(sorted(result.tables), ["customers", "orders"])
        self.assertEqual(result.contract.root_table, "customers")

    def test_row_count_applies_to_the_root_table(self):
        _, result = self._run()
        self.assertLessEqual(len(result.tables["customers"]), 2000)
        self.assertGreater(len(result.tables["orders"]), len(result.tables["customers"]))

    # -- planin ISLEVSEL sonuclari ----------------------------------------- #
    def test_leaking_columns_are_absent_from_the_generated_data(self):
        """Ayikladigini soyledigi kolon gercekten uretilmemis olmali."""
        _, result = self._run()
        excluded = {e.column for e in result.plan.excluded_leakage}
        self.assertTrue(excluded, "test anlamsiz: plan hicbir sizinti ayiklamamis")
        for name, df in result.tables.items():
            overlap = excluded & set(df.columns)
            self.assertEqual(overlap, set(), "%s tablosunda sizintili kolon var" % name)

    def test_planned_class_balance_reaches_the_data(self):
        """Plan %20 dediyse uretilen hedef kolon da oralarda olmali."""
        _, result = self._run()
        churn_rate = result.tables["customers"]["churned"].mean()
        self.assertAlmostEqual(churn_rate, 0.2, delta=0.05)

    def test_target_column_exists_in_the_generated_table(self):
        _, result = self._run()
        table = result.tables[result.plan.target.table]
        self.assertIn(result.plan.target.column, table.columns)

    # -- rapor ve cikti ---------------------------------------------------- #
    def test_report_carries_the_plan(self):
        _, result = self._run()
        stored = result.report["project_plan"]
        self.assertEqual(stored["task_type"], "binary_classification")
        self.assertEqual(len(stored["excluded_leakage"]), 2)
        self.assertIn("split", stored)
        # Diske yazilan rapor da tasimali.
        self.assertIn("project_plan", self.state.get_report(result.job_id))

    def test_plan_is_written_next_to_the_data(self):
        _, result = self._run()
        self.assertIn("plan", result.output_paths)
        path = Path(result.output_paths["plan"])
        self.assertTrue(path.exists())
        written = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(written["target"]["column"], "churned")
        self.assertEqual(written["split"]["kind"], "temporal")
        self.assertIn("rationale", written)

    def test_manifest_lists_the_plan_file(self):
        _, result = self._run()
        manifest = json.loads(
            Path(result.output_paths["manifest"]).read_text(encoding="utf-8"))
        self.assertIn("plan", manifest["files"])

    # -- konsol dokumu ----------------------------------------------------- #
    def test_console_explains_the_decisions(self):
        from ai_data_studio.i18n import t

        events, _ = self._run()
        text = "\n".join(e["message"] for e in events)
        # Karsilastirma katalog uzerinden: metin dile bagli, anahtar degil.
        self.assertIn(t("run.plan.target", target="customers.churned"), text)
        self.assertIn(t("run.plan.class_balance", pct="20.0"), text)
        self.assertIn("cancellation_reason", text)
        self.assertIn(t("run.plan.split", kind="temporal (customers.signup_at)",
                        reason="gelecegi tahmin ediyoruz; rastgele bolme zaman sizdirir"),
                      text)

    # -- sinir degerler ---------------------------------------------------- #
    def test_single_table_plan_is_allowed(self):
        """Iliskisel modun aksine planlayici tek tabloya da karar verebilir."""
        self.cfg.max_tables = 1
        _, result = self._run()
        self.assertIsNotNone(result.plan)

    def test_max_tables_above_hard_limit_is_rejected(self):
        from ai_data_studio.core.dataset_contract import MAX_TABLES

        self.cfg.max_tables = MAX_TABLES + 1
        with self.assertRaises(ValueError):
            self._run()

    def test_project_mode_ignores_relational_flag(self):
        """Tablo sayisina plan karar verir; --relational bayragi devre disidir."""
        self.cfg.relational = False
        _, result = self._run()
        self.assertTrue(result.contract.is_relational)
        self.assertIn("relational", result.report)


import pandas as pd


class TestOutputPathTraversal(unittest.TestCase):
    """Cikti dosya adlarinin cikti dizini disina tasamayacagini dogrular.

    ``domain`` ve tablo adlari LLM yanitindan veya paylasilan bir sema
    JSON'undan gelir; sanitize edilmeden dosya adina girdiklerinde
    ``../..`` ile keyfi konuma dosya yazdiriyorlardi.
    """

    def setUp(self):
        import tempfile
        self.temp_dir = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temp_dir.name) / "outputs"
        self.out_dir.mkdir()
        self.outside = Path(self.temp_dir.name) / "outside"
        self.outside.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_safe_stem_strips_traversal_sequences(self):
        from ai_data_studio.core.orchestrator import _safe_stem
        for hostile in ("../../../etc/pwned", r"..\..\Desktop\evil",
                        "C:/abs/path", "....//....//x"):
            stem = _safe_stem(hostile)
            self.assertNotIn("/", stem)
            self.assertNotIn("\\", stem)
            self.assertNotIn("..", stem)
            self.assertNotIn(":", stem)

    def test_safe_stem_falls_back_when_nothing_survives(self):
        from ai_data_studio.core.orchestrator import _safe_stem
        self.assertEqual(_safe_stem(""), "dataset")
        self.assertEqual(_safe_stem("..."), "dataset")
        self.assertEqual(_safe_stem("///"), "dataset")

    def test_out_path_rejects_escaping_filename(self):
        from ai_data_studio.core.orchestrator import _out_path
        with self.assertRaises(ValueError):
            _out_path(self.out_dir, "../outside/pwned.py")

    def test_out_path_accepts_plain_filename(self):
        from ai_data_studio.core.orchestrator import _out_path
        target = _out_path(self.out_dir, "job_1_domain.csv")
        self.assertEqual(target.parent.resolve(), self.out_dir.resolve())

    def test_hostile_domain_writes_stay_inside_output_dir(self):
        """Uctan uca: dusmanca bir domain ile yazilan hicbir dosya disari cikmaz."""
        import pandas as pd
        from ai_data_studio.core.orchestrator import _safe_stem, _write_table_files

        hostile = "../../outside/pwned"
        df = pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
        stem = "job_%d_%s" % (7, _safe_stem(hostile))
        paths = _write_table_files(df, self.out_dir, stem, ["csv", "json"])

        for path in paths.values():
            self.assertEqual(Path(path).resolve().parent, self.out_dir.resolve())
        self.assertEqual(list(self.outside.iterdir()), [])


class TestProvenanceOutputs(unittest.TestCase):
    """CSV, Parquet ve JSON provenance / yasal şerh çıktı testleri."""

    def setUp(self):
        import tempfile
        import pandas as pd
        self.temp_dir = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temp_dir.name)
        self.df = pd.DataFrame({
            "income": [50000.0, 75000.0, 120000.0],
            "credit_score": [650, 720, 800],
            "is_default": [0, 0, 0],
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_csv_has_no_provenance_header(self):
        from ai_data_studio.core.orchestrator import _write_table_files
        paths = _write_table_files(self.df, self.out_dir, "test_clean", ["csv"], provenance=False)
        csv_text = Path(paths["csv"]).read_text(encoding="utf-8")
        self.assertFalse(csv_text.startswith("# PROVENANCE"))
        # Standart pd.read_csv dogrudan okuyabilmeli
        reread = pd.read_csv(paths["csv"])
        self.assertEqual(len(reread), 3)
        self.assertEqual(list(reread.columns), ["income", "credit_score", "is_default"])

    def test_provenance_csv_has_comment_header(self):
        from ai_data_studio.core.orchestrator import _write_table_files
        paths = _write_table_files(self.df, self.out_dir, "test_prov", ["csv"], provenance=True)
        csv_text = Path(paths["csv"]).read_text(encoding="utf-8")
        self.assertTrue(csv_text.startswith("# PROVENANCE: 100% Synthetic Data"))
        self.assertIn("# COMPLIANCE: EU AI Act Art. 50", csv_text)
        # comment='#' ile sorunsuz okunmali
        reread = pd.read_csv(paths["csv"], comment="#")
        self.assertEqual(len(reread), 3)
        self.assertEqual(list(reread.columns), ["income", "credit_score", "is_default"])

    def test_provenance_parquet_has_schema_metadata(self):
        import pyarrow.parquet as pq
        from ai_data_studio.core.orchestrator import _write_table_files
        paths = _write_table_files(self.df, self.out_dir, "test_prov", ["parquet"], provenance=True)
        schema = pq.read_schema(paths["parquet"])
        self.assertIsNotNone(schema.metadata)
        self.assertIn(b"provenance", schema.metadata)
        self.assertIn(b"100% Synthetic Data", schema.metadata[b"provenance"])
        self.assertIn(b"compliance", schema.metadata)
        # Normal pd.read_parquet metadata'dan etkilenmeden okumali
        reread = pd.read_parquet(paths["parquet"])
        self.assertEqual(len(reread), 3)

    def test_provenance_json_has_envelope(self):
        import json
        from ai_data_studio.core.orchestrator import _write_table_files
        paths = _write_table_files(self.df, self.out_dir, "test_prov", ["json"], provenance=True)
        data = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        self.assertIn("_provenance", data)
        self.assertIn("100% Synthetic Data", data["_provenance"]["notice"])
        self.assertIn("data", data)
        self.assertEqual(len(data["data"]), 3)

