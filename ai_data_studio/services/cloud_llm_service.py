"""Bulut LLM sağlayıcıları: Anthropic (Claude) ve Google (Gemini).

Tüm harici API çağrıları `tenacity` ile exponential backoff mekanizmasına sarılır;
dakikalık hız/kota limitleri (rate limit) durumunda güvenle yeniden denenir.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .. import config
from .llm_base import BaseLLMClient, LLMError, LLMNotConfiguredError

log = logging.getLogger(__name__)


class RetryableLLMError(LLMError):
    """Geçici hata - backoff ile yeniden denenmeli (rate limit, 5xx, ağ)."""


# Geçici hatalar için exponential backoff. Yalnızca geçici hatalarda yeniden dener;
# 400/401 gibi kalici hatalar aninda yukari firlatilir.
_retry_policy = retry(
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(RetryableLLMError),
    reraise=True,
)


# --------------------------------------------------------------------------- #
# Anthropic / Claude
# --------------------------------------------------------------------------- #
class AnthropicClient(BaseLLMClient):
    """Claude Messages API sarmalayicisi."""

    provider = config.PROVIDER_ANTHROPIC

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None, **kwargs):
        super().__init__(model or config.DEFAULT_MODELS[config.PROVIDER_ANTHROPIC], **kwargs)
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMNotConfiguredError("`anthropic` paketi kurulu değil") from exc
        self._anthropic = anthropic

        if api_key:
            self.credential = config.Credential(config.KIND_API_KEY, api_key, "dogrudan verildi")
        else:
            self.credential = config.resolve_credential(config.PROVIDER_ANTHROPIC)

        if self.credential.kind == config.KIND_NONE:
            raise LLMNotConfiguredError(
                config.missing_credential_message(config.PROVIDER_ANTHROPIC)
            )

        # SDK'nin kendi retry'i (2) uzerine tenacity katmani gelir; toplam bekleme
        # kontrolsuz buyumesin diye SDK retry'ini kapatiyoruz.
        client_kwargs = {"max_retries": 0, "timeout": 600.0}
        if self.credential.kind == config.KIND_API_KEY:
            client_kwargs["api_key"] = self.credential.value
        elif self.credential.kind == config.KIND_AUTH_TOKEN:
            # OAuth / bearer token -> Authorization: Bearer
            client_kwargs["auth_token"] = self.credential.value
        # KIND_SDK_DEFAULT: hicbir sey gecme - SDK profil/WIF zincirini kendisi cozsun.

        self._client = anthropic.Anthropic(**client_kwargs)
        log.info("Anthropic kimliği: %s (%s)", self.credential.kind, self.credential.source)

    def health_check(self) -> bool:
        self.last_health_error = ""
        try:
            self._client.models.list(limit=1)
            return True
        except self._anthropic.AuthenticationError as exc:
            self.last_health_error = (
                "Kimlik doğrulanamadı (%s). Anahtar geçersiz veya süresi dolmuş."
                % self.credential.source
            )
            log.warning("Anthropic kimlik doğrulama hatası: %s", exc)
            return False
        except self._anthropic.PermissionDeniedError as exc:
            self.last_health_error = "Anahtarin bu islem için yetkisi yok (%s)." % exc
            return False
        except Exception as exc:
            self.last_health_error = "Servise ulaşılamadı: %s" % exc
            log.warning("Anthropic health check başarısız: %s", exc)
            return False

    def _complete(self, system: str, user: str, max_tokens: int = 16000,
                  temperature: Optional[float] = None) -> str:
        return self._call(system, user, max_tokens)

    @_retry_policy
    def _call(self, system: str, user: str, max_tokens: int) -> str:
        anthropic = self._anthropic
        try:
            # 128K'ya kadar cikti destekleniyor ancak buyuk max_tokens'ta HTTP
            # timeout'a takilmamak icin streaming kullanilir.
            with self._client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                message = stream.get_final_message()
        except anthropic.RateLimitError as exc:
            raise RetryableLLMError("Anthropic rate limit: %s" % exc) from exc
        except anthropic.APIConnectionError as exc:
            raise RetryableLLMError("Anthropic bağlantı hatası: %s" % exc) from exc
        except anthropic.AuthenticationError as exc:
            raise LLMNotConfiguredError("Anthropic API key geçersiz: %s" % exc) from exc
        except anthropic.NotFoundError as exc:
            raise LLMError("Model bulunamadı: %s (%s)" % (self.model, exc)) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise RetryableLLMError("Anthropic sunucu hatası %s" % exc.status_code) from exc
            raise LLMError("Anthropic API hatası %s: %s" % (exc.status_code, exc)) from exc

        usage = getattr(message, "usage", None)
        if usage is not None:
            self._log_usage(getattr(usage, "input_tokens", 0) or 0,
                            getattr(usage, "output_tokens", 0) or 0,
                            purpose="messages")

        if message.stop_reason == "refusal":
            detail = getattr(message, "stop_details", None)
            raise LLMError(
                "Model isteği reddetti%s"
                % (" (%s)" % detail.category if detail is not None else "")
            )

        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )
        if not text.strip():
            raise LLMError("Anthropic boş yanit dondu (stop_reason=%s)" % message.stop_reason)
        return text


# --------------------------------------------------------------------------- #
# Google / Gemini
# --------------------------------------------------------------------------- #
class GeminiClient(BaseLLMClient):
    """google-genai tabanli Gemini sarmalayicisi."""

    provider = config.PROVIDER_GEMINI

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None, **kwargs):
        super().__init__(model or config.DEFAULT_MODELS[config.PROVIDER_GEMINI], **kwargs)
        try:
            from google import genai
            from google.genai import errors as genai_errors
            from google.genai import types as genai_types
        except ImportError as exc:  # pragma: no cover
            raise LLMNotConfiguredError("`google-genai` paketi kurulu değil") from exc
        self._genai_errors = genai_errors
        self._types = genai_types

        if api_key:
            self.credential = config.Credential(config.KIND_API_KEY, api_key, "dogrudan verildi")
        else:
            self.credential = config.resolve_credential(config.PROVIDER_GEMINI)

        # Bu sinif YALNIZCA AI Studio yolunu konusur (api_key). Anahtarsiz yol
        # ayri bir tasima katmanidir: services/agy_service.AgyClient.
        if not self.credential.value:
            raise LLMNotConfiguredError(
                config.missing_credential_message(config.PROVIDER_GEMINI)
            )
        self.backend = config.GEMINI_BACKEND_AISTUDIO
        self._client = genai.Client(api_key=self.credential.value)
        log.info("Gemini kimliği: %s (%s)", self.credential.kind, self.credential.source)

    def health_check(self) -> bool:
        self.last_health_error = ""
        try:
            next(iter(self._client.models.list()), None)
            return True
        except self._genai_errors.ClientError as exc:
            self.last_health_error = self._format_client_error(exc)
            log.warning("Gemini health check başarısız: %s", exc)
            return False
        except Exception as exc:
            self.last_health_error = "Servise ulaşılamadı: %s" % exc
            log.warning("Gemini health check başarısız: %s", exc)
            return False

    def _format_client_error(self, exc) -> str:
        """Google'ın hata gövdesini kullanıcının yapabileceği bir eyleme çevirir.

        Google'ın ham gövdesi kod dışında bilgi taşır; ham
        mesaj "403 PERMISSION_DENIED" deyip geçtiği için ne yapılacağı
        anlaşılmıyordu.
        """
        text = str(exc)
        code = getattr(exc, "code", None)
        if "API_KEY_INVALID" in text or code in (401, 403):
            return ("Gemini API anahtarı geçersiz veya yetkisiz. "
                    "https://aistudio.google.com/apikey üzerinden kontrol edin - "
                    "ya da anahtarsız çalışmak için Antigravity CLI girişini seçin.")
        if code == 429 or "RESOURCE_EXHAUSTED" in text:
            return ("Gemini kota sınırına takıldı. Biraz bekleyip tekrar deneyin "
                    "ya da daha küçük bir model seçin.")
        if code == 404:
            return ("Model '%s' bulunamadı. Model listesinden başka birini seçin."
                    % self.model)
        return "İstek reddedildi: %s" % exc

    def _complete(self, system: str, user: str, max_tokens: int = 16000,
                  temperature: Optional[float] = None) -> str:
        return self._call(system, user, max_tokens,
                          self.temperature if temperature is None else temperature)

    @_retry_policy
    def _call(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        errors = self._genai_errors
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=user,
                config=self._types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
        except errors.ClientError as exc:
            code = getattr(exc, "code", None)
            if code == 429:
                raise RetryableLLMError("Gemini rate limit: %s" % exc) from exc
            if code in (401, 403):
                raise LLMNotConfiguredError(self._format_client_error(exc)) from exc
            raise LLMError("Gemini istek hatası: %s" % exc) from exc
        except errors.ServerError as exc:
            raise RetryableLLMError("Gemini sunucu hatası: %s" % exc) from exc
        except errors.APIError as exc:
            raise RetryableLLMError("Gemini API hatası: %s" % exc) from exc

        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            self._log_usage(getattr(usage, "prompt_token_count", 0) or 0,
                            getattr(usage, "candidates_token_count", 0) or 0,
                            purpose="generate_content")

        text = getattr(response, "text", None)
        if not text or not text.strip():
            raise LLMError("Gemini boş yanit dondu")
        return text


# --------------------------------------------------------------------------- #
def create_client(provider: str, model: Optional[str] = None, **kwargs) -> BaseLLMClient:
    """Sağlayıcı adina gore uygun istemciyi kurar (Ollama dahil)."""
    provider = (provider or "").lower()
    if provider == config.PROVIDER_ANTHROPIC:
        return AnthropicClient(model, **kwargs)
    if provider == config.PROVIDER_GEMINI:
        # Anahtarsiz yol: kullanicinin Antigravity CLI oturumu.
        if config.gemini_backend() == config.GEMINI_BACKEND_CLI:
            from .agy_service import AgyClient
            return AgyClient(model, **kwargs)
        return GeminiClient(model, **kwargs)
    if provider == config.PROVIDER_OLLAMA:
        from .ollama_service import OllamaClient
        return OllamaClient(model, **kwargs)
    raise ValueError("Bilinmeyen sağlayıcı: %s" % provider)
