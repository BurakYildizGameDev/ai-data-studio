"""Kimlik doğrulama katmanı: coklu kaynak cozumu, SDK'ya devretme, hata mesajlari.

Gerçek ag çağrısı yapilmaz; SDK istemcileri taklit edilir.
"""
import unittest
from unittest import mock

from ai_data_studio import config

ALL_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY",
           "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "HF_TOKEN",
           "HUGGING_FACE_HUB_TOKEN", "ANTHROPIC_FEDERATION_RULE_ID")


def clean_env(**overrides):
    """Tüm kimlik degiskenlerini temizleyip yalnızca verilenleri kurar."""
    env = {k: "" for k in ALL_ENV}
    env.update(overrides)
    patch = mock.patch.dict("os.environ", env, clear=False)
    return patch


class TestCredentialResolution(unittest.TestCase):
    def setUp(self):
        # keyring'i her testte bos say - gercek makinedeki anahtarlar testi etkilemesin
        self._kr = mock.patch.object(config, "_keyring", return_value=None)
        self._kr.start()
        self.addCleanup(self._kr.stop)
        self._sdk = mock.patch.object(config, "_sdk_default_source", return_value=None)
        self._sdk.start()
        self.addCleanup(self._sdk.stop)
        self._claude_oauth = mock.patch.object(config, "claude_code_oauth_token", return_value=None)
        self._claude_oauth.start()
        self.addCleanup(self._claude_oauth.stop)

    def test_no_credential_anywhere(self):
        with clean_env():
            cred = config.resolve_credential(config.PROVIDER_ANTHROPIC)
        self.assertEqual(cred.kind, config.KIND_NONE)
        self.assertFalse(config.credential_status(config.PROVIDER_ANTHROPIC)["configured"]
                         if cred.kind == config.KIND_NONE else True)

    def test_claude_code_oauth_token_detected(self):
        with clean_env(), mock.patch.object(config, "claude_code_oauth_token", return_value="tok-123"):
            cred = config.resolve_credential(config.PROVIDER_ANTHROPIC)
        self.assertEqual(cred.kind, config.KIND_AUTH_TOKEN)
        self.assertEqual(cred.value, "tok-123")
        self.assertIn("Claude Code", cred.source)

    def test_anthropic_api_key_env(self):
        with clean_env(ANTHROPIC_API_KEY="sk-ant-1"):
            cred = config.resolve_credential(config.PROVIDER_ANTHROPIC)
        self.assertEqual(cred.kind, config.KIND_API_KEY)
        self.assertEqual(cred.value, "sk-ant-1")
        self.assertIn("ANTHROPIC_API_KEY", cred.source)

    def test_anthropic_auth_token_is_bearer_kind(self):
        """ANTHROPIC_AUTH_TOKEN bearer olarak siniflandirilmali, api_key olarak değil."""
        with clean_env(ANTHROPIC_AUTH_TOKEN="oauth-xyz"):
            cred = config.resolve_credential(config.PROVIDER_ANTHROPIC)
        self.assertEqual(cred.kind, config.KIND_AUTH_TOKEN)
        self.assertEqual(cred.value, "oauth-xyz")

    def test_anthropic_api_key_wins_over_auth_token(self):
        with clean_env(ANTHROPIC_API_KEY="sk-ant-1", ANTHROPIC_AUTH_TOKEN="oauth-xyz"):
            cred = config.resolve_credential(config.PROVIDER_ANTHROPIC)
        self.assertEqual(cred.value, "sk-ant-1")

    def test_gemini_accepts_google_api_key(self):
        """google-genai kendi GOOGLE_API_KEY'ini okur - biz de okumaliyiz."""
        with clean_env(GOOGLE_API_KEY="g-123"):
            cred = config.resolve_credential(config.PROVIDER_GEMINI)
        self.assertEqual(cred.kind, config.KIND_API_KEY)
        self.assertEqual(cred.value, "g-123")
        self.assertIn("GOOGLE_API_KEY", cred.source)

    def test_gemini_api_key_wins_over_google_api_key(self):
        with clean_env(GEMINI_API_KEY="gem-1", GOOGLE_API_KEY="g-2"):
            self.assertEqual(config.resolve_credential(config.PROVIDER_GEMINI).value, "gem-1")

    def test_hf_accepts_both_env_names(self):
        with clean_env(HUGGING_FACE_HUB_TOKEN="hf-2"):
            self.assertEqual(config.resolve_credential("huggingface").value, "hf-2")

    def test_keyring_wins_over_every_env_var(self):
        fake = mock.Mock()
        fake.get_password.return_value = "from-keyring"
        with mock.patch.object(config, "_keyring", return_value=fake), \
             clean_env(ANTHROPIC_API_KEY="from-env"):
            cred = config.resolve_credential(config.PROVIDER_ANTHROPIC)
        self.assertEqual(cred.value, "from-keyring")
        self.assertIn("keyring", cred.source)

    def test_unknown_provider_returns_none_kind(self):
        self.assertEqual(config.resolve_credential("yokboyle").kind, config.KIND_NONE)


class TestSdkDefaultFallback(unittest.TestCase):
    """Anahtar yokken SDK'nin kendi çözebileceği kimlikler tespit edilmeli."""

    def setUp(self):
        self._kr = mock.patch.object(config, "_keyring", return_value=None)
        self._kr.start()
        self.addCleanup(self._kr.stop)
        self._claude_oauth = mock.patch.object(config, "claude_code_oauth_token", return_value=None)
        self._claude_oauth.start()
        self.addCleanup(self._claude_oauth.stop)

    def test_anthropic_profile_directory_detected(self):
        with clean_env(), \
             mock.patch.object(config, "_sdk_default_source",
                               return_value="ant auth login profili"):
            cred = config.resolve_credential(config.PROVIDER_ANTHROPIC)
        self.assertEqual(cred.kind, config.KIND_SDK_DEFAULT)
        self.assertIsNone(cred.value)
        status = None
        with clean_env(), \
             mock.patch.object(config, "_sdk_default_source",
                               return_value="ant auth login profili"):
            status = config.credential_status(config.PROVIDER_ANTHROPIC)
        self.assertTrue(status["configured"])
        self.assertFalse(status["explicit"])   # anahtar yok, ama denenebilir

    def test_aistudio_backend_has_no_valueless_credential_source(self):
        """AI Studio yolunda değeri olmayan kimlik kaynağı OLAMAZ.

        GeminiClient bu yolda gerçek bir anahtar değeri ister; kaynağın
        "var ama değeri yok" olması arayüzü yeşil gösterip istemciyi
        patlatıyordu. CLI yolu ayrı: orada değersiz kimlik meşrudur
        (bkz. test_cli_backend_makes_credential_sdk_default).

        NOT: gemini_backend() gerçek settings.json'u okur - makinedeki ayara
        bağlı kalmamak için burada açıkça sabitleniyor.
        """
        with clean_env(GOOGLE_GENAI_USE_VERTEXAI="1"),              mock.patch.object(config, "gemini_backend",
                               return_value=config.GEMINI_BACKEND_AISTUDIO):
            self.assertIsNone(config._sdk_default_source(config.PROVIDER_GEMINI))

    def test_cli_backend_needs_agy_installed(self):
        """CLI yolu seçili ama `agy` yoksa kaynak yine None olmalı."""
        with clean_env(),              mock.patch.object(config, "gemini_backend",
                               return_value=config.GEMINI_BACKEND_CLI),              mock.patch.object(config, "agy_available", return_value=False):
            self.assertIsNone(config._sdk_default_source(config.PROVIDER_GEMINI))

    def test_federation_env_detected(self):
        with clean_env(ANTHROPIC_FEDERATION_RULE_ID="rule-1"), \
             mock.patch("pathlib.Path.is_dir", return_value=False):
            source = config._sdk_default_source(config.PROVIDER_ANTHROPIC)
        self.assertIn("Federation", source)

    def test_has_api_key_is_strict_but_has_credential_is_not(self):
        with clean_env(), \
             mock.patch.object(config, "_sdk_default_source", return_value="bir profil"):
            self.assertFalse(config.has_api_key(config.PROVIDER_ANTHROPIC))
            self.assertTrue(config.has_credential(config.PROVIDER_ANTHROPIC))


class TestClientWiring(unittest.TestCase):
    """Çözülen kimliğin SDK istemcisine doğru sekilde gecirildigi."""

    def setUp(self):
        self._kr = mock.patch.object(config, "_keyring", return_value=None)
        self._kr.start()
        self.addCleanup(self._kr.stop)
        self._sdk = mock.patch.object(config, "_sdk_default_source", return_value=None)
        self._sdk.start()
        self.addCleanup(self._sdk.stop)
        self._claude_oauth = mock.patch.object(config, "claude_code_oauth_token", return_value=None)
        self._claude_oauth.start()
        self.addCleanup(self._claude_oauth.stop)
        self._settings_patch = mock.patch.object(
            config, "load_settings", return_value=dict(config.DEFAULT_SETTINGS)
        )
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)

    def test_anthropic_api_key_passed_as_api_key(self):
        import anthropic
        from ai_data_studio.services.cloud_llm_service import AnthropicClient
        with clean_env(ANTHROPIC_API_KEY="sk-ant-1"), \
             mock.patch.object(anthropic, "Anthropic") as ctor:
            client = AnthropicClient()
        self.assertEqual(ctor.call_args[1]["api_key"], "sk-ant-1")
        self.assertNotIn("auth_token", ctor.call_args[1])
        self.assertEqual(client.credential.kind, config.KIND_API_KEY)

    def test_anthropic_auth_token_passed_as_auth_token(self):
        import anthropic
        from ai_data_studio.services.cloud_llm_service import AnthropicClient
        with clean_env(ANTHROPIC_AUTH_TOKEN="oauth-xyz"), \
             mock.patch.object(anthropic, "Anthropic") as ctor:
            AnthropicClient()
        self.assertEqual(ctor.call_args[1]["auth_token"], "oauth-xyz")
        self.assertNotIn("api_key", ctor.call_args[1])

    def test_anthropic_sdk_default_passes_neither(self):
        """Profil varsa SDK kendi zincirini cozsun - api_key/auth_token gecilmemeli."""
        import anthropic
        from ai_data_studio.services.cloud_llm_service import AnthropicClient
        with clean_env(), \
             mock.patch.object(config, "_sdk_default_source", return_value="profil"), \
             mock.patch.object(anthropic, "Anthropic") as ctor:
            AnthropicClient()
        self.assertNotIn("api_key", ctor.call_args[1])
        self.assertNotIn("auth_token", ctor.call_args[1])

    def test_anthropic_raises_only_when_nothing_found(self):
        from ai_data_studio.services.cloud_llm_service import AnthropicClient
        from ai_data_studio.services.llm_base import LLMNotConfiguredError
        with clean_env():
            with self.assertRaises(LLMNotConfiguredError) as ctx:
                AnthropicClient()
        message = str(ctx.exception)
        # Hata mesaji nerelere bakildigini soylemeli
        self.assertIn("ANTHROPIC_API_KEY", message)
        self.assertIn("ANTHROPIC_AUTH_TOKEN", message)
        self.assertIn("claude", message)

    def test_gemini_uses_google_api_key(self):
        from google import genai
        from ai_data_studio.services.cloud_llm_service import GeminiClient
        with clean_env(GOOGLE_API_KEY="g-123"), \
             mock.patch.object(genai, "Client") as ctor:
            client = GeminiClient()
        self.assertEqual(ctor.call_args[1]["api_key"], "g-123")
        self.assertEqual(client.credential.source, "GOOGLE_API_KEY ortam değişkeni")

    def test_gemini_error_message_lists_sources(self):
        from ai_data_studio.services.cloud_llm_service import GeminiClient
        from ai_data_studio.services.llm_base import LLMNotConfiguredError
        with clean_env():
            with self.assertRaises(LLMNotConfiguredError) as ctx:
                GeminiClient()
        self.assertIn("GOOGLE_API_KEY", str(ctx.exception))
        self.assertIn("aistudio.google.com", str(ctx.exception))

    def test_explicit_api_key_argument_overrides_environment(self):
        import anthropic
        from ai_data_studio.services.cloud_llm_service import AnthropicClient
        with clean_env(ANTHROPIC_API_KEY="from-env"), \
             mock.patch.object(anthropic, "Anthropic") as ctor:
            AnthropicClient(api_key="explicit")
        self.assertEqual(ctor.call_args[1]["api_key"], "explicit")


class TestHealthCheckReporting(unittest.TestCase):
    """health_check başarısız oldugunda NEDEN'i taniyor mu?"""

    def setUp(self):
        self._kr = mock.patch.object(config, "_keyring", return_value=None)
        self._kr.start()
        self.addCleanup(self._kr.stop)

    def _anthropic_client(self, list_side_effect):
        import anthropic
        from ai_data_studio.services.cloud_llm_service import AnthropicClient
        with clean_env(ANTHROPIC_API_KEY="sk-ant-1"), \
             mock.patch.object(anthropic, "Anthropic") as ctor:
            ctor.return_value.models.list.side_effect = list_side_effect
            return AnthropicClient()

    def test_auth_error_is_named_as_auth_error(self):
        import anthropic
        error = anthropic.AuthenticationError(
            "invalid key", response=mock.Mock(status_code=401, headers={}), body=None)
        client = self._anthropic_client(error)
        self.assertFalse(client.health_check())
        self.assertIn("Kimlik doğrulanamadı", client.last_health_error)
        self.assertIn("ANTHROPIC_API_KEY", client.last_health_error)

    def test_network_error_is_not_reported_as_auth_error(self):
        client = self._anthropic_client(ConnectionError("dns yok"))
        self.assertFalse(client.health_check())
        self.assertIn("ulaşılamadı", client.last_health_error)
        self.assertNotIn("Kimlik doğrulanamadı", client.last_health_error)

    def test_success_clears_error(self):
        client = self._anthropic_client(None)
        self.assertTrue(client.health_check())
        self.assertEqual(client.last_health_error, "")

    def test_orchestrator_surfaces_health_reason(self):
        """Adım 1 hatası kullanıcıya asil nedeni gostermeli."""
        from ai_data_studio.core import orchestrator
        from ai_data_studio.services.llm_base import LLMError

        class _Client:
            model = "claude-opus-5"
            last_health_error = "Kimlik doğrulanamadı (ANTHROPIC_API_KEY ortam değişkeni)."

            def health_check(self):
                return False

        with mock.patch("ai_data_studio.services.cloud_llm_service.create_client",
                        return_value=_Client()):
            with self.assertRaises(LLMError) as ctx:
                orchestrator._build_llm_client(
                    orchestrator.PipelineConfig(domain_prompt="x"), mock.Mock(), 1)
        self.assertIn("Kimlik doğrulanamadı", str(ctx.exception))


class TestOllamaHealthReporting(unittest.TestCase):
    def test_daemon_down_reason(self):
        from ai_data_studio.services import ollama_service
        with mock.patch.object(ollama_service, "is_available", return_value=True):
            client = ollama_service.OllamaClient("qwen2.5-coder:7b")
        with mock.patch.object(ollama_service, "is_available", return_value=False):
            self.assertFalse(client.health_check())
        self.assertIn("ollama serve", client.last_health_error)

    def test_missing_model_reason(self):
        from ai_data_studio.services import ollama_service
        with mock.patch.object(ollama_service, "is_available", return_value=True):
            client = ollama_service.OllamaClient("qwen2.5-coder:7b")
            with mock.patch.object(ollama_service, "has_model", return_value=False):
                self.assertFalse(client.health_check())
        self.assertIn("ollama pull", client.last_health_error)


class TestCheckAuthCommand(unittest.TestCase):
    def test_reports_failure_when_nothing_configured(self):
        from ai_data_studio.core import orchestrator
        from ai_data_studio.services import ollama_service
        with clean_env(), \
             mock.patch.object(config, "_keyring", return_value=None), \
             mock.patch.object(config, "claude_code_oauth_token", return_value=None), \
             mock.patch.object(config, "_sdk_default_source", return_value=None), \
             mock.patch.object(ollama_service, "is_available", return_value=False):
            self.assertEqual(orchestrator.check_auth(), 1)

    def test_reports_success_when_one_provider_works(self):
        from ai_data_studio.core import orchestrator
        from ai_data_studio.services import ollama_service
        with clean_env(GEMINI_API_KEY="g-1"), \
             mock.patch.object(config, "_keyring", return_value=None), \
             mock.patch.object(config, "claude_code_oauth_token", return_value=None), \
             mock.patch.object(config, "_sdk_default_source", return_value=None), \
             mock.patch.object(ollama_service, "is_available", return_value=False):
            self.assertEqual(orchestrator.check_auth(), 0)

    def test_domain_required_unless_check_auth(self):
        from ai_data_studio.core import orchestrator
        self.assertEqual(orchestrator.main([]), 2)


if __name__ == "__main__":
    unittest.main()


class TestOAuthDetection(unittest.TestCase):
    """OAuth / CLI girişi tespiti - API anahtarı olmadan oturum acma yolu."""

    def test_gemini_offers_both_paths(self):
        """Gemini iki yol sunar: AI Studio anahtarı + Antigravity CLI oturumu."""
        with clean_env():
            info = config.oauth_status(config.PROVIDER_GEMINI)
        self.assertTrue(info["supported"])
        self.assertEqual(info["command"], [config.AGY_EXECUTABLE])
        self.assertIn("aistudio.google.com", info["api_key_url"])

    def test_gemini_backend_defaults_to_aistudio(self):
        """Varsayılan anahtar yolu; CLI ancak açıkça seçilirse devreye girer."""
        with clean_env(), mock.patch.object(
                config, "load_settings", return_value=dict(config.DEFAULT_SETTINGS)):
            self.assertEqual(config.gemini_backend(), config.GEMINI_BACKEND_AISTUDIO)

    def test_cli_backend_makes_credential_sdk_default(self):
        """CLI seçili ve `agy` kuruluysa kimlik 'değeri olmayan' SDK kimliğidir."""
        settings = dict(config.DEFAULT_SETTINGS)
        settings["gemini_backend"] = config.GEMINI_BACKEND_CLI
        with clean_env(), mock.patch.object(config, "_keyring", return_value=None), \
             mock.patch.object(config, "load_settings", return_value=settings), \
             mock.patch.object(config, "agy_available", return_value=True):
            cred = config.resolve_credential(config.PROVIDER_GEMINI)
        self.assertEqual(cred.kind, config.KIND_SDK_DEFAULT)
        self.assertIsNone(cred.value)
        self.assertIn("Antigravity", cred.source)

    def test_cli_backend_without_agy_is_not_configured(self):
        """`agy` kurulu değilse CLI seçili olsa bile kimlik yok sayılır."""
        settings = dict(config.DEFAULT_SETTINGS)
        settings["gemini_backend"] = config.GEMINI_BACKEND_CLI
        with clean_env(), mock.patch.object(config, "_keyring", return_value=None), \
             mock.patch.object(config, "load_settings", return_value=settings), \
             mock.patch.object(config, "agy_available", return_value=False):
            self.assertFalse(config.credential_status(config.PROVIDER_GEMINI)["configured"])

    def test_create_client_routes_to_agy_when_cli_selected(self):
        """Arka uç CLI ise Gemini istekleri AgyClient'a gitmeli."""
        from ai_data_studio.services import agy_service
        from ai_data_studio.services.cloud_llm_service import create_client
        with clean_env(), \
             mock.patch.object(config, "gemini_backend",
                               return_value=config.GEMINI_BACKEND_CLI), \
             mock.patch.object(agy_service, "is_available", return_value=True):
            client = create_client(config.PROVIDER_GEMINI)
        self.assertIsInstance(client, agy_service.AgyClient)
        self.assertEqual(client.credential.kind, config.KIND_SDK_DEFAULT)

    def test_agy_parses_cli_stream(self):
        """CLI'nin NDJSON akışından yanıt ve token kullanımı ayıklanmalı.

        JSON olmayan ilerleme satırları atlanmalı - CLI bunları basıyor.
        """
        from ai_data_studio.services.agy_service import AgyClient
        payload = AgyClient._parse(
            'Fetching available models...\n'
            '{"event":"init","conversation_id":"c1"}\n'
            '{"event":"step_update","step_update":{"step_type":"agent_response",'
            '"state":"DONE","text_delta":"merhaba"}}\n'
            '{"event":"result","result":{"status":"SUCCESS","response":"merhaba",'
            '"usage":{"input_tokens":10,"output_tokens":2}}}\n')
        self.assertEqual(payload["status"], "SUCCESS")
        self.assertEqual(payload["response"], "merhaba")
        self.assertEqual(payload["usage"]["input_tokens"], 10)
        self.assertEqual(payload["steps"], ["agent_response/DONE"])
        self.assertFalse(payload["recovered_from_deltas"])

    def test_anthropic_oauth_command_resolution(self):
        blank = {"found": False, "token": None, "expires_at": None, "expired": False}
        with clean_env(), mock.patch.object(config, "anthropic_profile_dir", return_value=None), \
             mock.patch.object(config, "claude_code_credentials", return_value=blank), \
             mock.patch.object(config, "claude_code_oauth_token", return_value=None):
            info = config.oauth_status(config.PROVIDER_ANTHROPIC)
        self.assertIn(info["command"][0], ["claude", "ant"])
        self.assertFalse(info["logged_in"])

    def test_anthropic_profile_detected_on_windows_appdata(self):
        import pathlib
        with mock.patch.dict("os.environ", {"APPDATA": r"C:\Fake\AppData"}), \
             mock.patch.object(pathlib.Path, "is_dir",
                               lambda self: "AppData" in str(self)), \
             mock.patch.object(pathlib.Path, "iterdir", lambda self: iter(["profile.json"])):
            found = config.anthropic_profile_dir()
        self.assertIsNotNone(found)
        self.assertIn("anthropic", str(found))

    def test_cli_available(self):
        self.assertTrue(config.cli_available("python") or config.cli_available("python.exe"))
        self.assertFalse(config.cli_available("kesinlikle-yok-boyle-komut-42"))


class TestGeminiClientWiring(unittest.TestCase):
    """Gemini API anahtarı ve istemci olusturma kontrolleri."""

    def setUp(self):
        self._kr = mock.patch.object(config, "_keyring", return_value=None)
        self._kr.start()
        self.addCleanup(self._kr.stop)

    def test_gemini_client_with_api_key_env(self):
        from google import genai
        from ai_data_studio.services.cloud_llm_service import GeminiClient
        with clean_env(GEMINI_API_KEY="test-api-key"), \
             mock.patch.object(genai, "Client") as ctor:
            client = GeminiClient()
        self.assertEqual(ctor.call_args[1]["api_key"], "test-api-key")
        self.assertIn("GEMINI_API_KEY", client.credential.source)

    def test_gemini_client_with_explicit_arg(self):
        from google import genai
        from ai_data_studio.services.cloud_llm_service import GeminiClient
        with clean_env(), mock.patch.object(genai, "Client") as ctor:
            client = GeminiClient(api_key="direct-key")
        self.assertEqual(ctor.call_args[1]["api_key"], "direct-key")
        self.assertEqual(client.credential.source, "dogrudan verildi")

    def test_gemini_without_credentials_raises(self):
        from ai_data_studio.services.cloud_llm_service import GeminiClient
        from ai_data_studio.services.llm_base import LLMNotConfiguredError
        with clean_env():
            with self.assertRaises(LLMNotConfiguredError) as ctx:
                GeminiClient()
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))
