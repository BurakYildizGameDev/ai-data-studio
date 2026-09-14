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

    def test_catalog_descriptions_are_translated(self):
        """Onerilen model aciklamalari eskiden sabit Turkce metindi."""
        from ai_data_studio.i18n import t

        with mock.patch.object(ollama_service, "list_models", return_value=[]):
            entries = ollama_service.catalog()
        by_name = {e["name"]: e for e in entries}
        self.assertEqual(by_name["qwen2.5-coder:7b"]["detail"], t("ollama.model.balanced"))
        for entry in entries:
            self.assertFalse(entry["detail"].startswith("ollama.model."), entry)

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
        # num_ctx verilmezse Ollama 4096'da kalir ve uzun prompt'u sessizce keser.
        self.assertEqual(body["options"]["num_ctx"], config.OLLAMA_NUM_CTX)
        self.assertGreaterEqual(body["options"]["num_ctx"], 8192)
        self.assertEqual(logged, {"input_tokens": 120, "output_tokens": 45, "purpose": "chat"})


class TestSmallModelDetection(unittest.TestCase):
    def test_parameter_size_from_ollama_details_wins(self):
        self.assertEqual(ollama_service.parameter_billions("custom:latest", "1.5B"), 1.5)

    def test_parameter_size_from_name(self):
        cases = {
            "qwen2.5-coder:1.5b": 1.5,
            "qwen2.5-coder:14b": 14.0,
            "deepseek-r1:8b": 8.0,
            "llama3.2:3b": 3.0,
            "dagbs/dolphin-2.9.2-qwen2-7b:latest": 7.0,
        }
        for name, size in cases.items():
            self.assertEqual(ollama_service.parameter_billions(name), size, name)
        self.assertIsNone(ollama_service.parameter_billions("phi3:mini"))

    def test_small_model_threshold(self):
        self.assertTrue(ollama_service.is_small_model("qwen2.5-coder:1.5b"))
        self.assertTrue(ollama_service.is_small_model("llama3.2:3b"))
        self.assertFalse(ollama_service.is_small_model("qwen2.5-coder:7b"))
        self.assertFalse(ollama_service.is_small_model("phi3:mini"))   # bilinmiyor -> dokunma


class TestOllamaReasoningModels(unittest.TestCase):
    """Dusunen modeller (deepseek-r1) cikti butcesini dusunmeye harciyor.

    Canli olcum (2026-09-14, deepseek-r1:8b, num_predict=8000): bir kosuda 7138 token
    ile gecerli sozlesme, ayni istemin sonraki kosusunda done_reason=length ve yarida
    kesik JSON, pipeline icinde de tamamen bos cevap.
    """

    def _client(self):
        with mock.patch.object(ollama_service, "is_available", return_value=True):
            return ollama_service.OllamaClient("deepseek-r1:8b")

    @staticmethod
    def _router(capabilities, chats):
        """/api/show ve /api/chat'i ayiran sahte requests.post; chat govdelerini kaydeder."""
        sent = []

        def fake_post(url, json=None, timeout=None):
            if url.endswith("/api/show"):
                return _Response({"capabilities": capabilities})
            sent.append(json)
            return _Response(chats[len(sent) - 1])
        return fake_post, sent

    @staticmethod
    def _chat(content="", thinking="", done_reason="stop"):
        return {"message": {"content": content, "thinking": thinking},
                "done_reason": done_reason, "prompt_eval_count": 10, "eval_count": 20}

    def test_thinking_model_gets_extra_budget_up_front(self):
        client = self._client()
        post, sent = self._router(["completion", "thinking"], [self._chat("{}", "hmm")])
        with mock.patch.object(ollama_service.requests, "post", side_effect=post):
            self.assertEqual(client._complete("s", "u", max_tokens=8000), "{}")
        self.assertEqual(sent[0]["options"]["num_predict"],
                         8000 + ollama_service.THINKING_EXTRA_TOKENS)

    def test_plain_model_budget_is_unchanged(self):
        client = self._client()
        post, sent = self._router(["completion", "tools"], [self._chat("{}")])
        with mock.patch.object(ollama_service.requests, "post", side_effect=post):
            client._complete("s", "u", max_tokens=8000)
        self.assertEqual(sent[0]["options"]["num_predict"], 8000)

    def test_capabilities_are_queried_once_per_client(self):
        client = self._client()
        shows = []

        def post(url, json=None, timeout=None):
            if url.endswith("/api/show"):
                shows.append(url)
                return _Response({"capabilities": []})
            return _Response(self._chat("ok"))
        with mock.patch.object(ollama_service.requests, "post", side_effect=post):
            client._complete("s", "u")
            client._complete("s", "u")
        self.assertEqual(len(shows), 1)

    def test_show_failure_is_not_fatal(self):
        import requests

        client = self._client()

        def post(url, json=None, timeout=None):
            if url.endswith("/api/show"):
                raise requests.ConnectionError("yok")
            return _Response(self._chat("ok"))
        with mock.patch.object(ollama_service.requests, "post", side_effect=post):
            self.assertEqual(client._complete("s", "u"), "ok")

    def test_truncated_by_thinking_is_retried_with_more_budget(self):
        client = self._client()
        seen = []
        client.progress_cb = seen.append
        post, sent = self._router([], [
            self._chat('{"domain": "x", "col', "uzun dusunme", done_reason="length"),
            self._chat('{"domain": "x"}', "dusunme"),
        ])
        with mock.patch.object(ollama_service.requests, "post", side_effect=post):
            text = client._complete("s", "u", max_tokens=8000)
        self.assertEqual(text, '{"domain": "x"}')
        self.assertEqual([b["options"]["num_predict"] for b in sent],
                         [8000, 8000 + ollama_service.THINKING_EXTRA_TOKENS])
        self.assertTrue(client.supports_thinking())   # ogrenildi, sonraki cagri bastan pay alir
        self.assertEqual(len(seen), 1)

    def test_thinking_that_never_answers_raises_a_clear_error(self):
        from ai_data_studio.i18n import t

        client = self._client()
        post, sent = self._router(["thinking"], [
            self._chat("", "dusunme", done_reason="length"),
            self._chat("", "daha fazla dusunme", done_reason="length"),
        ])
        with mock.patch.object(ollama_service.requests, "post", side_effect=post):
            with self.assertRaises(LLMError) as ctx:
                client._complete("s", "u", max_tokens=8000)
        self.assertEqual(len(sent), 2)   # tek yeniden deneme, sonsuz dongu yok
        budget = 8000 + 2 * ollama_service.THINKING_EXTRA_TOKENS
        self.assertEqual(str(ctx.exception),
                         t("service.error.ollama_thinking_exhausted",
                           model="deepseek-r1:8b", tokens=budget))

    def test_empty_answer_is_retried_once(self):
        client = self._client()
        post, sent = self._router([], [self._chat(""), self._chat("kod")])
        with mock.patch.object(ollama_service.requests, "post", side_effect=post):
            self.assertEqual(client._complete("s", "u"), "kod")
        self.assertEqual(sent[0]["options"]["num_predict"], sent[1]["options"]["num_predict"])

    def test_plain_model_hitting_the_limit_is_not_retried(self):
        """Dusunmesiz modelin sinira carpmasi (sonsuz tekrar) ikinci kez ayni butceyi yakmasin."""
        client = self._client()
        post, sent = self._router([], [self._chat("def generate_data(", done_reason="length")])
        with mock.patch.object(ollama_service.requests, "post", side_effect=post):
            self.assertEqual(client._complete("s", "u"), "def generate_data(")
        self.assertEqual(len(sent), 1)

    def test_inline_think_tags_are_stripped(self):
        client = self._client()
        post, _ = self._router([], [self._chat("<think>plan...</think>\n{\"a\": 1}")])
        with mock.patch.object(ollama_service.requests, "post", side_effect=post):
            self.assertEqual(client._complete("s", "u"), '{"a": 1}')

    def test_unclosed_inline_think_counts_as_no_answer(self):
        client = self._client()
        post, sent = self._router([], [
            self._chat("<think>plan plan plan", done_reason="length"),
            self._chat("<think>kisa</think>{}"),
        ])
        with mock.patch.object(ollama_service.requests, "post", side_effect=post):
            self.assertEqual(client._complete("s", "u"), "{}")
        self.assertEqual(len(sent), 2)


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
        err_msg = str(ctx.exception)
        self.assertTrue("boş yanıt" in err_msg or "empty response" in err_msg)
        self.assertIn("AI Studio", err_msg)
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

        err_msg = str(ctx.exception)
        self.assertTrue("sonuç olayı" in err_msg or "no result event" in err_msg)

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
        self.assertTrue("~200 sn" in seen[0] or "~200 s" in seen[0])

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

        steps = [m for m in seen if m.startswith("agy adımı") or m.startswith("agy step:")]
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


class TestMultiTableDatasetCard(unittest.TestCase):
    """Çok tablolu kart: tablo listesi + ilişki şeması.

    Kart LLM olmadan da doğru olmalı, o yüzden bölümler deterministik şablonda
    üretiliyor. Tek tablo çıktısı birebir korunur - yeni bölümler yalnız
    ilişkiselde görünür.
    """

    def setUp(self):
        from ai_data_studio.core.dataset_contract import DatasetContract
        from ai_data_studio.tests.fake_llm import DATASET_CONTRACT_JSON

        self.contract = DatasetContract.from_dict(DATASET_CONTRACT_JSON)
        self.schema = self.contract.table(self.contract.root_table)
        self.report = {
            "rows_in": 8000, "rows_out": 7600, "retention_pct": 95.0,
            "business_rules": [], "correlations": [],
            "distributions": {"skipped": True}, "column_stats": {},
            "relational": {"row_counts": {"customers": 2000, "orders": 5600}},
        }

    def test_lists_every_table_with_its_key_and_size(self):
        card = hf_service.build_dataset_card(self.schema, self.report,
                                             contract=self.contract)
        self.assertIn("## Tables", card)
        for name in self.contract.table_names:
            self.assertIn("`%s`" % name, card)
        self.assertIn("2,000", card)
        self.assertIn("5,600", card)
        self.assertIn("`customer_id`", card)

    def test_documents_the_relationship_schema(self):
        card = hf_service.build_dataset_card(self.schema, self.report,
                                             contract=self.contract)
        self.assertIn("## Relationships", card)
        for rel in self.contract.relationships:
            self.assertIn("`%s.%s`" % (rel.parent_table, rel.parent_key), card)
            self.assertIn("`%s.%s`" % (rel.child_table, rel.child_key), card)

    def test_says_which_table_this_repo_actually_holds(self):
        """Sadece kök tablo yükleniyor; tablo listesini gören okuyucu hepsinin
        burada olduğunu sanmamalı."""
        card = hf_service.build_dataset_card(self.schema, self.report,
                                             contract=self.contract)
        self.assertIn("This repository holds the root table", card)
        self.assertIn("| In this repo |", card)

    def test_single_table_card_is_unchanged(self):
        """N=1 aynı koddan geçer ama çıktıya hiçbir şey eklemez."""
        from ai_data_studio.core.dataset_contract import DatasetContract

        single = DatasetContract.from_schema(SchemaContract.from_dict(SCHEMA_JSON))
        report = {"rows_in": 100, "rows_out": 90, "retention_pct": 90.0,
                  "business_rules": [], "correlations": [],
                  "distributions": {"skipped": True}, "column_stats": {}}

        without = hf_service.build_dataset_card(single.table(single.root_table), report)
        with_contract = hf_service.build_dataset_card(
            single.table(single.root_table), report, contract=single)
        self.assertEqual(without, with_contract)
        self.assertNotIn("## Tables", with_contract)
        self.assertNotIn("## Relationships", with_contract)

    def test_falls_back_to_contract_targets_when_report_is_empty(self):
        """Rapor satır sayısı taşımıyorsa sözleşmedeki hedef kullanılmalı."""
        card = hf_service.build_dataset_card(self.schema, {}, contract=self.contract)
        self.assertIn("## Tables", card)
        self.assertNotIn("| - |", card.split("## Relationships")[0].replace(
            "| Table | Rows | Primary key | Columns | In this repo |", ""))


if __name__ == "__main__":
    unittest.main()
