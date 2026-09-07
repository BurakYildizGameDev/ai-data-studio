"""Yerel Ollama entegrasyonu - REST API tabanlı yerel model istemcisi.

CLI çıktısı parse etmek yerine doğrudan standart REST uç noktaları kullanılır:
  GET  /api/tags      -> kurulu modeller (JSON)
  POST /api/chat      -> prompt tamamlama
  POST /api/pull      -> model indirme (NDJSON progress stream)
  GET  /api/version   -> servis sağlık kontrolü
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

import requests

from .. import config
from ..i18n import t
from .llm_base import BaseLLMClient, LLMError, LLMNotConfiguredError

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15          # kisa metadata cagrilari
COMPLETION_TIMEOUT = 900      # yerel model uretimi yavas olabilir

# Kod uretimine uygun, kurulu olmasa da secilip indirilebilecek modeller.
# (ad, yaklasik boyut, kisa aciklama)
RECOMMENDED_MODELS = [
    ("qwen2.5-coder:7b", "4.7 GB", "Kod üretimi için dengeli - onerilen"),
    ("qwen2.5-coder:14b", "9.0 GB", "Daha iyi kod, daha fazla RAM"),
    ("qwen2.5-coder:32b", "20 GB", "En iyi kod kalitesi, 32 GB+ RAM"),
    ("deepseek-coder-v2:16b", "8.9 GB", "Guclu kod modeli"),
    ("llama3.1:8b", "4.9 GB", "Genel amacli"),
    ("gemma2:9b", "5.4 GB", "Genel amacli, hızlı"),
    ("mistral:7b", "4.1 GB", "Hafif, hızlı"),
    ("phi4:14b", "9.1 GB", "Guclu akil yurutme"),
]


class OllamaUnavailableError(LLMNotConfiguredError):
    """Ollama daemon çalışmıyor veya erisilemiyor."""


def _url(path: str, host: Optional[str] = None) -> str:
    return (host or config.OLLAMA_HOST).rstrip("/") + path


# --------------------------------------------------------------------------- #
# Servis seviyesi yardimcilar (istemci ornegi gerektirmez)
# --------------------------------------------------------------------------- #
def is_available(host: Optional[str] = None, timeout: int = 3) -> bool:
    """Daemon ayakta mi? Hiçbir zaman exception firlatmaz."""
    try:
        r = requests.get(_url("/api/version", host), timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def get_version(host: Optional[str] = None) -> Optional[str]:
    try:
        r = requests.get(_url("/api/version", host), timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json().get("version")
    except requests.RequestException:
        return None


def list_models(host: Optional[str] = None) -> List[Dict[str, Any]]:
    """GET /api/tags -> kurulu Modeller. Daemon yoksa OllamaUnavailableError."""
    try:
        r = requests.get(_url("/api/tags", host), timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
    except requests.RequestException as exc:
        raise OllamaUnavailableError(
            t("service.error.ollama_unreachable", host=host or config.OLLAMA_HOST)
        ) from exc
    except ValueError as exc:
        raise LLMError(t("service.error.ollama_bad_json_tags")) from exc

    models = []
    for entry in payload.get("models", []) or []:
        details = entry.get("details") or {}
        models.append({
            "name": entry.get("name") or entry.get("model") or "",
            "size_bytes": entry.get("size", 0),
            "size_gb": round((entry.get("size", 0) or 0) / 1e9, 2),
            "parameter_size": details.get("parameter_size", ""),
            "quantization": details.get("quantization_level", ""),
            "family": details.get("family", ""),
            "modified_at": entry.get("modified_at", ""),
        })
    return sorted(models, key=lambda m: m["name"])


def list_model_names(host: Optional[str] = None) -> List[str]:
    """Daemon yoksa boş liste dondurur - GUI'yi cokertmez."""
    try:
        return [m["name"] for m in list_models(host)]
    except LLMError:
        return []


def has_model(name: str, host: Optional[str] = None) -> bool:
    """Model kurulu mu? Etiketsiz ad da eslesir (ornek: 'llama3' -> 'llama3:latest')."""
    names = list_model_names(host)
    if name in names:
        return True
    base = name.split(":")[0]
    return any(n.split(":")[0] == base for n in names)


def pull_model(
    name: str,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    host: Optional[str] = None,
) -> bool:
    """POST /api/pull - modeli indirir, ilerlemeyi on_progress'e stream eder.

    on_progress'e gonderilen sözlük: {status, completed, total, percent}
    """
    try:
        response = requests.post(
            _url("/api/pull", host),
            json={"model": name, "stream": True},
            stream=True,
            timeout=(DEFAULT_TIMEOUT, None),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise OllamaUnavailableError(t("service.error.ollama_pull_start", error=exc)) from exc

    try:
        for line in response.iter_lines(decode_unicode=True):
            if cancel_event is not None and cancel_event.is_set():
                log.info("Model indirme iptal edildi: %s", name)
                return False
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if "error" in event:
                raise LLMError(t("service.error.ollama_pull", error=event["error"]))
            if on_progress is not None:
                completed = event.get("completed") or 0
                total = event.get("total") or 0
                on_progress({
                    "status": event.get("status", ""),
                    "completed": completed,
                    "total": total,
                    "percent": round(completed / total * 100, 1) if total else None,
                })
            if event.get("status") == "success":
                return True
    finally:
        response.close()
    return has_model(name, host)


def delete_model(name: str, host: Optional[str] = None) -> bool:
    """DELETE /api/delete - kurulu bir modeli siler."""
    try:
        response = requests.delete(_url("/api/delete", host), json={"model": name},
                                   timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        raise OllamaUnavailableError(t("service.error.ollama_delete", error=exc)) from exc


def catalog(host: Optional[str] = None) -> List[Dict[str, Any]]:
    """Kurulu Modeller + kurulu olmayan onerilenler, tek listede.

    Her kayit: {name, installed, size, detail}
    GUI bunu "indirilenler" ve "indirilebilecekler" olarak gösterir.
    """
    try:
        installed = list_models(host)
    except LLMError:
        installed = []
    installed_names = {m["name"] for m in installed}
    installed_bases = {n.split(":")[0] for n in installed_names}

    entries: List[Dict[str, Any]] = []
    for model in installed:
        detail = " ".join(x for x in (model["parameter_size"], model["quantization"]) if x)
        entries.append({
            "name": model["name"],
            "installed": True,
            "size": "%.1f GB" % model["size_gb"] if model["size_gb"] else "",
            "detail": detail or model["family"],
        })
    for name, size, detail in RECOMMENDED_MODELS:
        if name in installed_names or name.split(":")[0] in installed_bases:
            continue
        entries.append({"name": name, "installed": False, "size": size, "detail": detail})
    return entries


# --------------------------------------------------------------------------- #
# LLM istemcisi
# --------------------------------------------------------------------------- #
class OllamaClient(BaseLLMClient):
    """Yerel Ollama modelleri için BaseLLMClient uygulamasi."""

    provider = config.PROVIDER_OLLAMA

    def __init__(self, model: Optional[str] = None, host: Optional[str] = None,
                 auto_pull: bool = False, **kwargs):
        super().__init__(model or config.DEFAULT_MODELS[config.PROVIDER_OLLAMA], **kwargs)
        self.host = host or config.OLLAMA_HOST
        if not is_available(self.host):
            raise OllamaUnavailableError(
                t("service.error.ollama_down", host=self.host)
            )
        if auto_pull and not has_model(self.model, self.host):
            log.info("Model kurulu değil, indiriliyor: %s", self.model)
            pull_model(self.model, host=self.host)

    def health_check(self) -> bool:
        self.last_health_error = ""
        if not is_available(self.host):
            self.last_health_error = (
                t("service.error.ollama_down", host=self.host)
            )
            return False
        if not has_model(self.model, self.host):
            self.last_health_error = (
                t("service.error.ollama_model_missing", model=self.model)
            )
            return False
        return True

    def _complete(self, system: str, user: str, max_tokens: int = 16000,
                  temperature: Optional[float] = None) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "temperature": self.temperature if temperature is None else temperature,
                "num_predict": max_tokens,
            },
        }
        try:
            response = requests.post(
                _url("/api/chat", self.host), json=payload, timeout=COMPLETION_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as exc:
            raise LLMError(
                t("service.error.ollama_timeout", seconds=COMPLETION_TIMEOUT)
            ) from exc
        except requests.RequestException as exc:
            raise OllamaUnavailableError(t("service.error.ollama_call_failed", error=exc)) from exc
        except ValueError as exc:
            raise LLMError(t("service.error.ollama_bad_json")) from exc

        if "error" in data:
            raise LLMError(t("service.error.ollama_generic", error=data["error"]))

        self._log_usage(data.get("prompt_eval_count", 0) or 0,
                        data.get("eval_count", 0) or 0,
                        purpose="chat")

        text = ((data.get("message") or {}).get("content") or "").strip()
        if not text:
            raise LLMError(t("service.error.ollama_empty"))
        return text
