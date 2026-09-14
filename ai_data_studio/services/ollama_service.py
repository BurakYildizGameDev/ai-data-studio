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
import re
import threading
from typing import Any, Callable, Dict, List, Optional

import requests

from .. import config
from ..i18n import t
from .llm_base import BaseLLMClient, LLMError, LLMNotConfiguredError

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15          # kisa metadata cagrilari
COMPLETION_TIMEOUT = 900      # yerel model uretimi yavas olabilir

# Dusunen (reasoning) modeller - deepseek-r1, qwen3 - cevaptan once uzun bir `thinking`
# metni uretir ve Ollama onu CEVAPLA AYNI num_predict butcesinden harcar. Olcum
# (2026-09-14, deepseek-r1:8b, sema cagrisi, num_predict=8000): dusunme ~25 bin karakter,
# 7138/8000 token; ayni istem bir sonraki kosuda 8000'e carpip JSON'u yarida kesti,
# canli pipeline'da da cevap tamamen bos geldi. `"think": false` bu modelde dusunmeyi
# KAPATMADI (ayni olcumde yine 25 bin karakter), bu yuzden cozum butceyi buyutmek.
THINKING_EXTRA_TOKENS = 8000

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

# Kod uretimine uygun, kurulu olmasa da secilip indirilebilecek modeller.
# (ad, yaklasik boyut, aciklamanin ceviri anahtari)
RECOMMENDED_MODELS = [
    ("qwen2.5-coder:7b", "4.7 GB", "ollama.model.balanced"),
    ("qwen2.5-coder:14b", "9.0 GB", "ollama.model.better_code"),
    ("qwen2.5-coder:32b", "20 GB", "ollama.model.best_code"),
    ("deepseek-coder-v2:16b", "8.9 GB", "ollama.model.strong_code"),
    ("llama3.1:8b", "4.9 GB", "ollama.model.general"),
    ("gemma2:9b", "5.4 GB", "ollama.model.general_fast"),
    ("mistral:7b", "4.1 GB", "ollama.model.light_fast"),
    ("phi4:14b", "9.1 GB", "ollama.model.reasoning"),
]


# Bu boyutun altindaki modeller LLM kod uretiminde neredeyse hep dusuyor. Canli olcum
# (2026-09-14, qwen2.5-coder:1.5b, 20.000 satir): `--engine llm` 3 promptun 3'unde
# FAILED, ayni model `auto` ve `parametric` motorla hepsinde basarili.
SMALL_MODEL_MAX_BILLIONS = 3.0

_PARAMETER_SIZE_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*b\b", re.IGNORECASE)


def parameter_billions(name: str, parameter_size: str = "") -> Optional[float]:
    """Model boyutu (milyar parametre); bilinmiyorsa ``None``.

    Once Ollama'nin bildirdigi ``parameter_size`` ("1.5B", "7.6B"), yoksa model adi
    ("qwen2.5-coder:1.5b", "dolphin-2.9.2-qwen2-7b") okunur. Etiket hic boyut
    tasimiyorsa ("phi3:mini") tahmin yurutulmez.
    """
    tag = name.rsplit(":", 1)[1] if ":" in (name or "") else ""
    for text in (parameter_size, tag, name):
        match = _PARAMETER_SIZE_RE.search(text or "")
        if match:
            return float(match.group(1))
    return None


def is_small_model(name: str, parameter_size: str = "") -> bool:
    """Model, LLM kod uretiminin guvenilir olmadigi kadar kucuk mu?"""
    size = parameter_billions(name, parameter_size)
    return size is not None and size <= SMALL_MODEL_MAX_BILLIONS


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
    for name, size, detail_key in RECOMMENDED_MODELS:
        if name in installed_names or name.split(":")[0] in installed_bases:
            continue
        entries.append({"name": name, "installed": False, "size": size,
                        "detail": t(detail_key)})
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
        # Model dusunen (reasoning) bir model mi? Ilk cagrida /api/show'dan ogrenilir.
        self._thinks: Optional[bool] = None
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

    def supports_thinking(self) -> bool:
        """Model cevaptan once dusunme metni uretiyor mu (``/api/show`` capabilities)?

        Sonuc istemci basina bir kez sorulur. Sorgu basarisizsa ``False`` kabul edilir;
        o durumda bile :meth:`_complete` kesilen yanitta dusunmeyi gorup telafi eder.
        """
        if self._thinks is None:
            try:
                response = requests.post(_url("/api/show", self.host),
                                         json={"model": self.model},
                                         timeout=DEFAULT_TIMEOUT)
                response.raise_for_status()
                capabilities = response.json().get("capabilities") or []
                self._thinks = "thinking" in capabilities
            except (requests.RequestException, ValueError, AttributeError, TypeError):
                self._thinks = False
        return self._thinks

    def _complete(self, system: str, user: str, max_tokens: int = 16000,
                  temperature: Optional[float] = None) -> str:
        budget = max_tokens + (THINKING_EXTRA_TOKENS if self.supports_thinking() else 0)
        text, thinking, done_reason = self._chat(system, user, budget, temperature)

        # Tek bir telafi denemesi. Dusunme butceyi yiyip cevabi kestiyse ya da bos
        # biraktiysa pay eklenerek; dusunmesiz bos yanitta ayni butceyle. Dusunmesiz
        # bir modelin sinira carpmasi (sonsuz tekrar) yeniden denenmez - ayni
        # butceyi bir kez daha yakmaktan baska bir sey yapmaz.
        exhausted = done_reason == "length" and bool(thinking)
        if exhausted or not text:
            if exhausted:
                self._thinks = True
                budget += THINKING_EXTRA_TOKENS
                log.warning("Ollama %s: düşünme çıktı bütçesini tüketti, %d token ile "
                            "yeniden deneniyor", self.model, budget)
                self._report_progress(t("service.ollama.thinking_retry",
                                        model=self.model, tokens=budget))
            else:
                log.warning("Ollama %s boş yanıt döndürdü, yeniden deneniyor", self.model)
                self._report_progress(t("service.ollama.empty_retry", model=self.model))
            text, thinking, done_reason = self._chat(system, user, budget, temperature)

        if not text:
            if thinking:
                raise LLMError(t("service.error.ollama_thinking_exhausted",
                                 model=self.model, tokens=budget))
            raise LLMError(t("service.error.ollama_empty"))
        if done_reason == "length":
            log.warning("Ollama %s yanıtı %d token sınırında kesildi", self.model, budget)
        return text

    def _chat(self, system: str, user: str, num_predict: int,
              temperature: Optional[float]):
        """Tek ``/api/chat`` cagrisi -> (cevap, dusunme metni, done_reason)."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "temperature": self.temperature if temperature is None else temperature,
                "num_predict": num_predict,
                # Verilmezse Ollama 4096'da kalir ve uzun prompt'un basini sessizce keser.
                "num_ctx": config.OLLAMA_NUM_CTX,
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

        message = data.get("message") or {}
        thinking = message.get("thinking") or ""
        text = message.get("content") or ""
        # Eski Ollama surumleri/sablonlari dusunmeyi ayri alana degil cevabin icine
        # <think>...</think> olarak koyar; JSON/kod ayiklayicisi onu cevap sanmasin.
        inline = _THINK_TAG_RE.findall(text)
        if inline:
            thinking = thinking or "".join(inline)
            text = _THINK_TAG_RE.sub("", text)
        elif text.lstrip().lower().startswith("<think>"):
            # Kapanmamis etiket: sinira dusunurken carpti, cevap hic baslamadi.
            thinking, text = thinking or text, ""
        return text.strip(), thinking, data.get("done_reason") or ""
