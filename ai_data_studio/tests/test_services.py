"""Servis entegrasyon testleri: Ollama REST, HF dataset card, keyring, locale ve maliyet takibi."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_data_studio import config
from ai_data_studio.core.schema_contract import SchemaContract
from ai_data_studio.services import hf_service, ollama_service
from ai_data_studio.services.llm_base import LLMError
from ai_data_studio.tests.fake_llm import SCHEMA_JSON, FakeLLMClient


class _Response:
    """requests.Response taklidi."""

    def __init__(self, payload=None, status_code=200, lines=None):
        self._payload = payload
        self.status_code = status_code
        self._lines = lines or []

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError("status %d" % self.status_code)

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def close(self):
        pass


TAGS_PAYLOAD = {
    "models": [
        {"name": "qwen2.5-coder:7b", "size": 4_700_000_000,
         "details": {"parameter_size": "7B", "quantization_level": "Q4_K_M",
                     "family": "qwen2"}},
        {"name": "llama3.1:8b", "size": 4_900_000_000,
         "details": {"parameter_size": "8B", "quantization_level": "Q4_0",
                     "family": "llama"}},
    ]
}


class TestOllamaREST(unittest.TestCase):
    """Ollama REST API (/api/tags) entegrasyon testleri."""

    def test_list_models_parses_rest_payload(self):
        with mock.patch.object(ollama_service.requests, "get",
                               return_value=_Response(TAGS_PAYLOAD)) as get:
            models = ollama_service.list_models()
        self.assertTrue(get.call_args[0][0].endswith("/api/tags"))
        self.assertEqual([m["name"] for m in models], ["llama3.1:8b", "qwen2.5-coder:7b"])
        self.assertEqual(models[1]["parameter_size"], "7B")
        self.assertAlmostEqual(models[1]["size_gb"], 4.7, places=1)

    def test_daemon_down_raises_typed_error(self):
        import requests
        with mock.patch.object(ollama_service.requests, "get",
                               side_effect=requests.ConnectionError("refused")):
            with self.assertRaises(ollama_service.OllamaUnavailableError) as ctx:
                ollama_service.list_models()
        self.assertIn("ollama serve", str(ctx.exception))

    def test_list_model_names_is_graceful_when_down(self):
        """GUI bu fonksiyonu çağırır - daemon yoksa cokmemeli, boş liste donmeli."""
        import requests
        with mock.patch.object(ollama_service.requests, "get",
                               side_effect=requests.ConnectionError("refused")):
            self.assertEqual(ollama_service.list_model_names(), [])
            self.assertFalse(ollama_service.is_available())

    def test_has_model_matches_untagged_name(self):
        with mock.patch.object(ollama_service.requests, "get",
                               return_value=_Response(TAGS_PAYLOAD)):
            self.assertTrue(ollama_service.has_model("qwen2.5-coder:7b"))
            self.assertTrue(ollama_service.has_model("llama3.1"))
            self.assertFalse(ollama_service.has_model("mistral"))

    def test_pull_model_streams_progress(self):
        lines = [
            json.dumps({"status": "pulling manifest"}),
            json.dumps({"status": "downloading", "completed": 500, "total": 1000}),
            json.dumps({"status": "downloading", "completed": 1000, "total": 1000}),
            json.dumps({"status": "success"}),
        ]
        events = []
        with mock.patch.object(ollama_service.requests, "post",
                               return_value=_Response(lines=lines)):
            ok = ollama_service.pull_model("qwen2.5-coder:7b", on_progress=events.append)
        self.assertTrue(ok)
        self.assertEqual([e["percent"] for e in events], [None, 50.0, 100.0, None])

    def test_pull_model_reports_server_error(self):
        lines = [json.dumps({"error": "model not found"})]
        with mock.patch.object(ollama_service.requests, "post",
                               return_value=_Response(lines=lines)):
            with self.assertRaises(LLMError) as ctx:
                ollama_service.pull_model("yok-boyle-model")
        self.assertIn("model not found", str(ctx.exception))

    def test_pull_model_honours_cancel_event(self):
        import threading
        cancel = threading.Event()
        cancel.set()
        lines = [json.dumps({"status": "downloading", "completed": 1, "total": 10})]
        with mock.patch.object(ollama_service.requests, "post",
                               return_value=_Response(lines=lines)):
            self.assertFalse(ollama_service.pull_model("x", cancel_event=cancel))

    def test_chat_completion_parses_response_and_logs_usage(self):
        payload = {"message": {"content": "merhaba"},
                   "prompt_eval_count": 120, "eval_count": 45}
        logged = {}

        class _State:
            def log_llm_call(self, job_id, provider, model, input_tokens=0,
                             output_tokens=0, purpose=""):
                logged.update(input_tokens=input_tokens, output_tokens=output_tokens,
                              purpose=purpose)

        with mock.patch.object(ollama_service, "is_available", return_value=True):
            client = ollama_service.OllamaClient("qwen2.5-coder:7b", state_manager=_State())
        with mock.patch.object(ollama_service.requests, "post",
                               return_value=_Response(payload)) as post:
            text = client._complete("sys", "user")

        self.assertEqual(text, "merhaba")
        self.assertTrue(post.call_args[0][0].endswith("/api/chat"))
        body = post.call_args[1]["json"]
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertFalse(body["stream"])
        self.assertEqual(logged, {"input_tokens": 120, "output_tokens": 45, "purpose": "chat"})


class TestDatasetCard(unittest.TestCase):
    """HuggingFace Hub için otomatik README.md dataset card üretim testleri."""

    def setUp(self):
        self.schema = SchemaContract.from_dict(SCHEMA_JSON)
        self.report = {
            "rows_in": 100000, "rows_out": 71234, "retention_pct": 71.2,
            "business_rules": [{"rule": "shipping_cost <= basket_value",
                                "status": "applied", "violations": 6000}],
            "correlations": [{"pair": ["item_count", "basket_value"],
                              "expected_sign": "positive", "min_r": 0.3,
                              "actual_r": 0.62, "pass": True}],
            "distributions": {"skipped": True},
            "column_stats": {},
        }

    def test_fallback_card_has_required_sections(self):
        card = hf_service.build_dataset_card(self.schema, self.report, llm_client=None,
                                             repo_id="user/test")
        self.assertTrue(card.startswith("---"))
        for section in ("license: mit", "size_categories", "# ", "## Dataset Summary",
                        "## Columns", "## Generation Method", "## Validation",
                        "## Limitations and Intended Use"):
            self.assertIn(section, card, "eksik bölüm: %s" % section)

    def test_card_states_data_is_synthetic(self):
        card = hf_service.build_dataset_card(self.schema, self.report)
        self.assertIn("synthetic", card.lower())
        self.assertIn("not", card.lower())

    def test_card_lists_every_column(self):
        card = hf_service.build_dataset_card(self.schema, self.report)
        for column in self.schema.columns:
            self.assertIn("`%s`" % column.name, card)

    def test_card_quotes_validation_stats(self):
        card = hf_service.build_dataset_card(self.schema, self.report)
        self.assertIn("71,234", card)
        self.assertIn("r = 0.62", card)

    def test_llm_path_card_claims_code_generation(self):
        """Varsayılan koşuda kart kod üretimi + sandbox anlatmalı."""
        card = hf_service.build_dataset_card(self.schema, self.report)
        self.assertIn("Code generation", card)
        self.assertIn("Sandboxed execution", card)
        self.assertNotIn("Post-Generation Engines", card)

    def test_parametric_card_does_not_claim_generated_code(self):
        """Parametrik koşuda LLM kod yazmadı; kart bunu iddia ederse yanlış beyan olur."""
        report = dict(self.report, engines={"generation": "parametric"})
        card = hf_service.build_dataset_card(self.schema, report)
        self.assertIn("Parametric compilation", card)
        self.assertNotIn("Sandboxed execution", card)
        self.assertNotIn("wrote a Python generator", card)

    def test_card_documents_injected_corruption(self):
        """Kirlilik enjekte edildiyse kart bunu söylemeli - okuyan hata sanmasın."""
        report = dict(self.report, engines={
            "generation": "parametric",
            "dirty_data": {"corrupted_rows": 3561, "corrupted_rate": 0.05,
                           "corruption_breakdown": {"missing": 1200, "typo": 900,
                                                    "outlier_spike": 700, "casing": 800}},
        })
        card = hf_service.build_dataset_card(self.schema, report)
        self.assertIn("Post-Generation Engines", card)
        self.assertIn("3,561", card)
        self.assertIn("is_corrupted", card)
        self.assertIn("after* validation", card)

    def test_card_lists_enrichment_engines(self):
        report = dict(self.report, engines={
            "generation": "llm",
            "time_series": {"unique_entities": 250, "burst_anomalies_count": 40,
                            "time_range": "2026-08-01 to 2026-09-01"},
            "feature_expander": {"added_columns_count": 2, "total_columns": 9,
                                 "added_columns": ["age_group", "hour_of_day"]},
        })
        card = hf_service.build_dataset_card(self.schema, report)
        self.assertIn("Time series & velocity", card)
        self.assertIn("Feature expansion", card)
        self.assertIn("`age_group`", card)

    def test_llm_card_is_used_when_valid(self):
        card = hf_service.build_dataset_card(self.schema, self.report,
                                             llm_client=FakeLLMClient())
        self.assertIn("Fake card", card)

    def test_falls_back_when_llm_raises(self):
        class _Broken:
            def generate_dataset_card(self, schema, stats):
                raise RuntimeError("kota doldu")

        card = hf_service.build_dataset_card(self.schema, self.report, llm_client=_Broken())
        self.assertIn("## Dataset Summary", card)

    def test_falls_back_when_llm_returns_prose(self):
        class _Chatty:
            def generate_dataset_card(self, schema, stats):
                return "Sure! Here is your dataset card..."

        card = hf_service.build_dataset_card(self.schema, self.report, llm_client=_Chatty())
        self.assertTrue(card.startswith("---"))

    def test_push_requires_token(self):
        import pandas as pd
        with mock.patch.object(hf_service, "get_token", return_value=None):
            with self.assertRaises(hf_service.HFNotConfiguredError):
                hf_service.push_dataset(pd.DataFrame({"a": [1]}), "user/test", self.schema)

    def test_size_category_buckets(self):
        self.assertEqual(hf_service._size_category(500), "n<1K")
        self.assertEqual(hf_service._size_category(70_000), "10K<n<100K")
        self.assertEqual(hf_service._size_category(2_000_000), "1M<n<10M")


class TestConfigAndChecklist(unittest.TestCase):
    """Yapılandırma ve sistem genel kuralları testleri."""

    def test_app_data_dir_under_localappdata(self):
        self.assertTrue(config.APP_DATA_DIR.exists())
        self.assertEqual(config.APP_DATA_DIR.name, "AIDataStudio")
        self.assertTrue(config.DB_PATH.parent == config.APP_DATA_DIR)

    def test_gemini_backend_env_overrides_settings(self):
        """Headless kosu kalici ayari degistirmeden arka ucu secebilmeli."""
        original = os.environ.get(config.GEMINI_BACKEND_ENV)
        self.addCleanup(
            lambda: os.environ.__setitem__(config.GEMINI_BACKEND_ENV, original)
            if original is not None else os.environ.pop(config.GEMINI_BACKEND_ENV, None))

        stored = config.load_settings().get("gemini_backend")

        os.environ[config.GEMINI_BACKEND_ENV] = config.GEMINI_BACKEND_CLI
        self.assertEqual(config.gemini_backend(), config.GEMINI_BACKEND_CLI)

        os.environ[config.GEMINI_BACKEND_ENV] = config.GEMINI_BACKEND_AISTUDIO
        self.assertEqual(config.gemini_backend(), config.GEMINI_BACKEND_AISTUDIO)

        # Gecersiz deger yok sayilir, kalici ayara donulur.
        os.environ[config.GEMINI_BACKEND_ENV] = "vertex"
        self.assertIn(config.gemini_backend(),
                      (config.GEMINI_BACKEND_AISTUDIO, config.GEMINI_BACKEND_CLI))

        # Gecersiz kilma kalici ayari kirletmemeli.
        self.assertEqual(config.load_settings().get("gemini_backend"), stored)

    def test_cli_exposes_gemini_backend_flag(self):
        from ai_data_studio.core.orchestrator import _build_arg_parser

        args = _build_arg_parser().parse_args(
            ["--domain", "x", "--gemini-backend", "aistudio"])
        self.assertEqual(args.gemini_backend, config.GEMINI_BACKEND_AISTUDIO)
        self.assertIsNone(_build_arg_parser().parse_args(["--domain", "x"]).gemini_backend)

    def test_write_and_read_text_roundtrip_turkish(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alt" / "türkçe_ölçüm.txt"
            content = "Şeker portakalı — ığüşöçİĞÜŞÖÇ 😀"
            config.write_text(path, content)
            self.assertEqual(config.read_text(path), content)
            self.assertEqual(path.read_bytes().decode("utf-8"), content)

    def test_json_roundtrip_preserves_non_ascii(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            config.write_json(path, {"domain": "müşteri_verisi"})
            self.assertEqual(config.read_json(path)["domain"], "müşteri_verisi")
            self.assertIn("müşteri", config.read_text(path))   # ensure_ascii=False

    def test_read_json_returns_default_when_missing(self):
        self.assertEqual(config.read_json(Path("yok") / "olmayan.json", default={"a": 1}),
                         {"a": 1})

    def test_api_key_falls_back_to_env(self):
        with mock.patch.object(config, "_keyring", return_value=None), \
             mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
            self.assertEqual(config.get_api_key(config.PROVIDER_ANTHROPIC), "sk-test-123")
            self.assertTrue(config.has_api_key(config.PROVIDER_ANTHROPIC))

    def test_api_key_prefers_keyring_over_env(self):
        fake_keyring = mock.Mock()
        fake_keyring.get_password.return_value = "sk-from-keyring"
        with mock.patch.object(config, "_keyring", return_value=fake_keyring), \
             mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-from-env"}):
            self.assertEqual(config.get_api_key(config.PROVIDER_ANTHROPIC), "sk-from-keyring")

    def test_api_key_never_written_to_settings_file(self):
        """Anahtarlar keyring'de durur; settings.json'a asla yazılmaz."""
        settings = config.load_settings()
        joined = json.dumps(settings).lower()
        for token in ("api_key", "token", "sk-", "secret"):
            self.assertNotIn(token, joined)

    def test_set_api_key_rejects_unknown_provider(self):
        with self.assertRaises(ValueError):
            config.set_api_key("bilinmeyen", "x")

    def test_settings_roundtrip_ignores_unknown_keys(self):
        original = config.load_settings()
        try:
            config.save_settings({"faker_locale": "de_DE", "zararli_alan": "x"})
            reloaded = config.load_settings()
            self.assertEqual(reloaded["faker_locale"], "de_DE")
            self.assertNotIn("zararli_alan", reloaded)
        finally:
            config.save_settings(original)

    def test_cost_estimation_matches_price_table(self):
        from ai_data_studio.core.state_manager import estimate_cost
        self.assertAlmostEqual(estimate_cost("claude-opus-5", 1_000_000, 0), 5.0, places=4)
        self.assertAlmostEqual(estimate_cost("claude-opus-5", 0, 1_000_000), 25.0, places=4)
        self.assertEqual(estimate_cost("ollama-local-model", 999_999, 999_999), 0.0)


class TestFakerLocalePropagation(unittest.TestCase):
    """Locale seçiminin kod üretim istemine aktarılması testleri."""

    def test_locale_reaches_code_generation_prompt(self):
        client = FakeLLMClient()
        captured = {}
        original = client._complete

        def spy(system, user, max_tokens=16000, temperature=None):
            captured.setdefault("systems", []).append(system)
            return original(system, user, max_tokens, temperature)

        client._complete = spy
        schema = client.generate_schema("test", row_count=1000, seed=7, locale="tr_TR")
        self.assertEqual(schema.faker_locale, "tr_TR")
        self.assertEqual(schema.random_seed, 7)
        self.assertEqual(schema.row_count_target, 1000)

        client.generate_code(schema)
        code_prompt = captured["systems"][-1]
        self.assertIn('Faker("tr_TR")', code_prompt)
        self.assertIn("generate_data(n_rows: int, seed: int)", code_prompt)

    def test_user_settings_override_llm_schema_values(self):
        """Kullanicinin sectigi satır sayısı/seed, LLM'in tahminini ezmeli."""
        client = FakeLLMClient()   # sema JSON'i 20000 satir / seed 42 diyor
        schema = client.generate_schema("test", row_count=333, seed=99, locale="de_DE")
        self.assertEqual(schema.row_count_target, 333)
        self.assertEqual(schema.random_seed, 99)
        self.assertEqual(schema.faker_locale, "de_DE")

    def test_sandbox_prompt_states_real_limits(self):
        client = FakeLLMClient()
        variables = client._sandbox_prompt_vars()
        self.assertEqual(variables["timeout"], config.SANDBOX_TIMEOUT_S)
        self.assertEqual(variables["memory_mb"], config.SANDBOX_MEMORY_LIMIT_MB)
        for module in ("pandas", "numpy", "faker"):
            self.assertIn(module, variables["allowed_imports"])
        for module in ("os", "subprocess", "socket"):
            self.assertNotIn(module, variables["allowed_imports"].split(", "))


def _agy_stream(response="", deltas=(), status="SUCCESS", extra_step=None):
    """agy'nin `--output-format stream-json` akisini taklit eder (gercek kayit sekli)."""
    lines = ['{"event":"init","conversation_id":"c1"}']
    for delta in deltas:
        lines.append(json.dumps({"event": "step_update",
                                 "step_update": {"step_type": "agent_response",
                                                 "state": "DONE",
                                                 "text_delta": delta}}))
    if extra_step is not None:
        lines.append(json.dumps({"event": "step_update", "step_update": extra_step}))
    result = {"status": status, "response": response,
              "usage": {"input_tokens": 9, "output_tokens": len(response) // 4}}
    if status != "SUCCESS":
        result["error"] = "model bulunamadi"
    lines.append(json.dumps({"event": "result", "result": result}))
    return "\n".join(lines) + "\n"


class TestAgyEmptyResponse(unittest.TestCase):
    """Antigravity CLI ajan gibi davranip final metni bos birakabiliyor (Job #78).

    Uc savunma katmani var: metin akis parcalarindan kurtarilir, kurtarilamazsa
    cagri bir kez daha denenir, o da bos donerse ham govde log'a ve hata metnine
    yazilir - yoksa neden bos donduguna dair hicbir teshis izi kalmiyor.
    """

    def _client(self):
        from ai_data_studio.services import agy_service
        with mock.patch.object(agy_service, "is_available", return_value=True):
            return agy_service.AgyClient(model="gemini-3.8-flash-low")

    @staticmethod
    def _streamed(stdout):
        """`_stream` donus sekli: (returncode, stdout, stderr)."""
        return 0, stdout, ""

    def test_text_is_recovered_from_stream_deltas(self):
        """Final yanit bos ama parcalar dolu: cagri kaybedilmemeli, tek denemede toparlamali."""
        from ai_data_studio.services import agy_service

        client = self._client()
        stream = _agy_stream(response="", deltas=["def generate", "_data():", " pass"])

        with mock.patch.object(agy_service, "_stream",
                               return_value=self._streamed(stream)) as runner, \
             mock.patch.object(agy_service, "_work_dir", return_value="."):
            text = client._complete("sistem", "kullanici")

        self.assertEqual(text, "def generate_data(): pass")
        self.assertEqual(runner.call_count, 1)   # yeniden denemeye gerek kalmadi
        # Kurtarma yalnizca akis kipinde mumkun; format geri alinirsa bu test dusmeli.
        self.assertIn("stream-json", runner.call_args[0][0])

    def test_empty_response_is_retried_once_and_succeeds(self):
        from ai_data_studio.services import agy_service

        client = self._client()
        bodies = [_agy_stream(response=""), _agy_stream(response="kod")]
        calls = []

        def fake_stream(args, timeout, cwd=None, on_line=None, on_heartbeat=None):
            calls.append(args)
            return self._streamed(bodies[len(calls) - 1])

        with mock.patch.object(agy_service, "_stream", side_effect=fake_stream), \
             mock.patch.object(agy_service, "_work_dir", return_value="."):
            text = client._complete("sistem", "kullanici")

        self.assertEqual(text, "kod")
        self.assertEqual(len(calls), 2)          # bir kez daha denedi

    def test_empty_response_twice_raises_with_raw_body(self):
        from ai_data_studio.services import agy_service

        client = self._client()
        stream = _agy_stream(response="", extra_step={"step_type": "tool_call",
                                                      "state": "DONE",
                                                      "tool_name": "write_to_file"})

        with mock.patch.object(agy_service, "_stream",
                               return_value=self._streamed(stream)) as runner, \
             mock.patch.object(agy_service, "_work_dir", return_value="."), \
             self.assertLogs("ai_data_studio.services.agy_service", level="WARNING") as logs:
            with self.assertRaises(LLMError) as ctx:
                client._complete("sistem", "kullanici")

        self.assertEqual(runner.call_count, agy_service.EMPTY_RESPONSE_ATTEMPTS)
        # Hata metni ne oldugunu ve cikis yolunu soyluyor
        self.assertIn("boş yanıt", str(ctx.exception))
        self.assertIn("AI Studio", str(ctx.exception))
        # Teshis izi: ham govde her denemede log'a yazildi
        self.assertEqual(len(logs.output), agy_service.EMPTY_RESPONSE_ATTEMPTS)
        self.assertIn("write_to_file", logs.output[0])

    def test_missing_result_event_is_reported(self):
        """Akis yarida kesilirse (sonuc olayi yok) sessizce bos donmemeli."""
        from ai_data_studio.services import agy_service

        client = self._client()
        stream = '{"event":"init","conversation_id":"c1"}\n'

        with mock.patch.object(agy_service, "_stream",
                               return_value=self._streamed(stream)), \
             mock.patch.object(agy_service, "_work_dir", return_value="."):
            with self.assertRaises(LLMError) as ctx:
                client._complete("sistem", "kullanici")

        self.assertIn("sonuç olayı", str(ctx.exception))

    def test_error_text_reads_stream_single_json_and_plain_text(self):
        """Hata mesaji uc bicimde de gelebiliyor; ucunde de asil mesaj kaybolmamali."""
        from ai_data_studio.services.agy_service import _error_text

        stream = ('{"event":"init"}\n'
                  '{"event":"result","result":{"status":"ERROR","error":"quota exceeded"}}')
        self.assertEqual(_error_text(stream, "", "m"), "quota exceeded")
        self.assertEqual(
            _error_text('{"status":"ERROR","error":"tek parca"}', "", "m"), "tek parca")
        self.assertEqual(_error_text("", "agy: fatal: not logged in", "m"),
                         "agy: fatal: not logged in")

    def test_error_status_is_not_retried(self):
        """Kalici hata gecici degildir: ikinci bir dakikalik cagri harcanmamali."""
        from ai_data_studio.services import agy_service

        client = self._client()
        stream = _agy_stream(response="", status="ERROR")

        with mock.patch.object(agy_service, "_stream",
                               return_value=self._streamed(stream)) as runner, \
             mock.patch.object(agy_service, "_work_dir", return_value="."):
            with self.assertRaises(LLMError):
                client._complete("sistem", "kullanici")

        self.assertEqual(runner.call_count, 1)

    def test_call_announces_the_slow_startup_before_waiting(self):
        """Ilk mesaj cagri baslarken gelmeli: ~200 sn'lik sessizligin sebebi soylensin."""
        from ai_data_studio.services import agy_service

        client = self._client()
        seen = []
        client.progress_cb = seen.append

        with mock.patch.object(agy_service, "_stream",
                               return_value=self._streamed(_agy_stream(response="kod"))), \
             mock.patch.object(agy_service, "_work_dir", return_value="."):
            client._complete("sistem", "kullanici")

        self.assertTrue(seen)
        self.assertIn("~200 sn", seen[0])

    def test_step_updates_are_reported_live(self):
        """Cagri suruyorken adim olaylari progress_cb'ye dusmeli - konsolun tek bilgisi."""
        from ai_data_studio.services import agy_service

        client = self._client()
        seen = []
        client.progress_cb = seen.append
        stream = _agy_stream(response="kod", deltas=["kod"])

        def fake_stream(args, timeout, cwd=None, on_line=None, on_heartbeat=None):
            for line in stream.splitlines():
                on_line(line + "\n")
            return 0, stream, ""

        with mock.patch.object(agy_service, "_stream", side_effect=fake_stream), \
             mock.patch.object(agy_service, "_work_dir", return_value="."):
            client._complete("sistem", "kullanici")

        steps = [m for m in seen if m.startswith("agy adımı")]
        self.assertTrue(steps, seen)
        self.assertTrue(any("agent_response" in m for m in steps), steps)

    def test_broken_progress_callback_does_not_break_the_call(self):
        """Ilerleme bildirimi kritik yol degil: UI tarafi patlarsa cagri yine bitmeli."""
        from ai_data_studio.services import agy_service

        client = self._client()

        def explode(_message):
            raise RuntimeError("UI kuyruğu kapalı")

        client.progress_cb = explode
        stream = _agy_stream(response="kod", deltas=["kod"])

        def fake_stream(args, timeout, cwd=None, on_line=None, on_heartbeat=None):
            for line in stream.splitlines():
                on_line(line + "\n")
            return 0, stream, ""

        with mock.patch.object(agy_service, "_stream", side_effect=fake_stream), \
             mock.patch.object(agy_service, "_work_dir", return_value="."):
            self.assertEqual(client._complete("sistem", "kullanici"), "kod")

    def test_excerpt_truncates_long_output(self):
        from ai_data_studio.services.agy_service import RAW_EXCERPT_CHARS, _excerpt

        self.assertEqual(_excerpt("   "), "(çıktı yok)")
        self.assertEqual(_excerpt("kısa"), "kısa")

        long_text = "x" * (RAW_EXCERPT_CHARS + 500)
        excerpt = _excerpt(long_text)
        self.assertLess(len(excerpt), len(long_text))
        self.assertIn("+500 karakter", excerpt)


class TestAgyStreamRunner(unittest.TestCase):
    """`_stream` gercek bir alt surecle: satir satir okuma ve zaman asimi.

    Sahte bir `agy` yerine `sys.executable` kullaniliyor - boru hattinin kendisi
    (Popen, okuma thread'leri, zaman asimi) gercekten kosuyor.
    """

    def _patch_exe(self):
        from ai_data_studio.services import agy_service
        return mock.patch.object(agy_service, "executable_path",
                                 return_value=sys.executable)

    def test_lines_arrive_one_by_one(self):
        from ai_data_studio.services.agy_service import _stream

        script = ("import sys, time\n"
                  "for i in range(3):\n"
                  "    print('{\"event\":\"step_update\",\"i\":%d}' % i, flush=True)\n"
                  "    time.sleep(0.05)\n")
        seen = []
        with self._patch_exe():
            code, stdout, stderr = _stream(["-c", script], timeout=30,
                                           on_line=seen.append)

        self.assertEqual(code, 0)
        self.assertEqual(len(seen), 3)                 # her satir ayri geldi
        self.assertEqual(stdout.count("step_update"), 3)
        self.assertEqual(stderr, "")

    def test_stderr_is_captured_separately(self):
        from ai_data_studio.services.agy_service import _stream

        script = ("import sys\n"
                  "print('cikti')\n"
                  "print('hata', file=sys.stderr)\n")
        seen = []
        with self._patch_exe():
            code, stdout, stderr = _stream(["-c", script], timeout=30,
                                           on_line=seen.append)

        self.assertEqual(code, 0)
        self.assertIn("cikti", stdout)
        self.assertIn("hata", stderr)
        self.assertEqual([s.strip() for s in seen], ["cikti"])   # stderr on_line'a gitmez

    def test_heartbeat_fires_while_the_process_is_silent(self):
        """`agy` acilis boyunca tek satir basmiyor; konsolun donmadigini bu gosteriyor."""
        from ai_data_studio.services.agy_service import _stream

        beats = []
        script = "import time; time.sleep(2.5); print('bitti')"
        with self._patch_exe():
            code, stdout, _stderr = _stream(["-c", script], timeout=30,
                                            on_heartbeat=beats.append,
                                            heartbeat_s=0.5)

        self.assertEqual(code, 0)
        self.assertIn("bitti", stdout)
        self.assertGreaterEqual(len(beats), 3)          # 2.5 sn / 0.5 sn
        self.assertTrue(all(b > 0 for b in beats), beats)

    def test_no_heartbeat_when_output_keeps_coming(self):
        """Cikti akiyorsa kalp atisi gereksiz - konsol zaten dolu."""
        from ai_data_studio.services.agy_service import _stream

        beats = []
        script = ("import time\n"
                  "for _ in range(6):\n"
                  "    print('satir', flush=True)\n"
                  "    time.sleep(0.1)\n")
        with self._patch_exe():
            _stream(["-c", script], timeout=30, on_line=lambda _l: None,
                    on_heartbeat=beats.append, heartbeat_s=0.5)

        self.assertEqual(beats, [])

    def test_timeout_kills_the_process(self):
        import subprocess
        from ai_data_studio.services.agy_service import _stream

        script = "import time; time.sleep(30)"
        with self._patch_exe():
            with self.assertRaises(subprocess.TimeoutExpired):
                _stream(["-c", script], timeout=2)

    def test_nonzero_exit_code_is_returned(self):
        from ai_data_studio.services.agy_service import _stream

        with self._patch_exe():
            code, _stdout, _stderr = _stream(["-c", "raise SystemExit(3)"], timeout=30)
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
