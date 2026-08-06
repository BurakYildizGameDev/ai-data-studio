# -*- coding: utf-8 -*-
"""Antigravity CLI (`agy`) üzerinden Gemini - kullanıcının mevcut CLI oturumu.

Bu yol API anahtarı, GCP projesi veya faturalandırma İSTEMEZ. Uygulama
kullanıcının kimlik bilgisine hiç dokunmaz: `agy --print` çağrılır, CLI kendi
oturumunu kendisi kullanır ve yanıtı NDJSON akışı olarak döndürür.

    agy -p "<istem>" --model <model> --output-format stream-json

Akış NDJSON'dur; satır başına bir olay: `init`, `step_update`(ler), `result`.
Sondaki `result` olayı `{"status": "SUCCESS", "response": "...", "usage": {...}}`
taşır. `step_update` olayları ajanın adımlarını ve `text_delta` parçalarını verir.

Neden akış: ajan bazen final metni boş bırakıp aracı çağırıyor; metin o zaman
yalnızca `text_delta` parçalarında kalıyor ve akış sayesinde kurtarılabiliyor.

ÖNEMLİ - hız: `agy` etkileşimli bir ajan CLI'ıdır, her çağrıda kendi sistem
istemini ve çalışma alanı bağlamını yükler. Basit bir istem bile dakikalar
sürebilir. Bu yüzden:
  * çağrılar izole ve BOŞ bir çalışma dizininde koşar (kullanıcının projesi
    bağlama girmesin, hem hız hem gizlilik için),
  * zaman aşımı bol tutulur ve aşıldığında ne yapılacağı söylenir.
"""
from __future__ import annotations

import json
import logging
import queue
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from .. import config
from .llm_base import BaseLLMClient, LLMError, LLMNotConfiguredError

log = logging.getLogger(__name__)

EXECUTABLE = "agy"
# Ajan CLI yavas; pipeline'in kod uretim adimlari birkac dakika surebiliyor.
CALL_TIMEOUT_S = 900
MODELS_TIMEOUT_S = 60
# Windows komut satiri ~32k karakterle sinirli; istemi argumanla geciriyoruz.
MAX_PROMPT_CHARS = 24000

# Ajan CLI bazen final metni bos birakiyor: yaniti yazmak yerine `write_to_file`
# gibi bir arac cagiriyor (Job #78 boyle dustu). Istemde araclar yasaklanmis olsa da
# bu ara sira oluyor ve GECICI: ayni istem ikinci denemede genellikle metin donduruyor.
# Bu yuzden bos yanit hemen hata degil, once bir kez daha denenir.
EMPTY_RESPONSE_ATTEMPTS = 2
# Bos yanitin ham govdesi log'a yazilir. Ne kadari yeter: arac cagrisi izi bas
# taraftadir, tamamini yazmak log'u sisirir.
RAW_EXCERPT_CHARS = 1500
# CLI acilisi olculdu: ~200 sn boyunca CLI TEK BIR SATIR basmiyor, ilk `step_update`
# ancak modele gidildiginde geliyor. Akisi dinlemek bu sessizligi doldurmuyor; bu
# yuzden cikti olmayan surede kendi kalp atisimizi uretiyoruz.
HEARTBEAT_S = 30

INSTALL_URL = "https://antigravity.google/download"


def _excerpt(text: str) -> str:
    """Ham CLI çıktısının log'a yazılacak kısaltılmış hali."""
    text = (text or "").strip()
    if not text:
        return "(çıktı yok)"
    if len(text) <= RAW_EXCERPT_CHARS:
        return text
    return "%s... (+%d karakter)" % (text[:RAW_EXCERPT_CHARS],
                                     len(text) - RAW_EXCERPT_CHARS)


def _token_counts(payload: Dict, prompt: str, text: str) -> Tuple[int, int]:
    """Yanıttaki usage nesnesinden token sayıları; yoksa metin boyutundan tahmin."""
    usage = payload.get("usage") or {}
    in_tok = int(usage.get("input_tokens", 0) or 0) if isinstance(usage, dict) else 0
    out_tok = int(usage.get("output_tokens", 0) or 0) if isinstance(usage, dict) else 0
    if in_tok == 0 and out_tok == 0:
        # usage nesnesi yoksa yaklasik hesap: ~4 karakter = 1 token
        in_tok = max(1, len(prompt) // 4)
        out_tok = max(1, len(text) // 4)
    return in_tok, out_tok


def _no_window_flags() -> int:
    """GUI'de alt surec calisirken konsol penceresi acilmasin."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def executable_path() -> Optional[str]:
    """`agy` PATH'te mi? Tam yolu ya da None."""
    return shutil.which(EXECUTABLE)


def is_available() -> bool:
    return executable_path() is not None


def _run(args: List[str], timeout: int, cwd: Optional[str] = None):
    """agy'yi alt surec olarak calistirir. shell=False - istem argumanini kabuk yorumlamasin."""
    exe = executable_path()
    if exe is None:
        raise LLMNotConfiguredError(
            "`agy` komutu bulunamadı. Antigravity CLI kurulu değil: %s" % INSTALL_URL
        )
    return subprocess.run(
        [exe] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=cwd,
        creationflags=_no_window_flags(),
    )


def _stream(args: List[str], timeout: int, cwd: Optional[str] = None,
            on_line: Optional[Callable[[str], None]] = None,
            on_heartbeat: Optional[Callable[[float], None]] = None,
            heartbeat_s: float = HEARTBEAT_S) -> Tuple[int, str, str]:
    """agy'yi çalıştırır ve stdout'u SATIR SATIR okur.

    `_run` gibi bloklamak yerine akışı canlı tüketir: her tam satır için `on_line`
    çağrılır, böylece dakikalarca süren bir çağrının içinde ne olduğu görülebilir.

    `on_heartbeat`, çıktı gelmeden `heartbeat_s` saniye geçtiğinde başlangıçtan bu yana
    geçen süreyle çağrılır: `agy` açılış boyunca hiçbir şey basmadığı için konsolun
    "donmuş mu?" sorusuna verecek tek cevabı bu.

    Döner: ``(returncode, stdout, stderr)``. Zaman aşımında süreci öldürür ve
    `subprocess.TimeoutExpired` yükseltir - çağıran taraf `_run` ile aynı hatayı görür.

    Okuma neden ayrı thread'de: Windows'ta `readline()` bloklar; süreç hiç çıktı
    vermeden asılırsa zaman aşımını ana döngüde ancak böyle kontrol edebiliyoruz.
    """
    exe = executable_path()
    if exe is None:
        raise LLMNotConfiguredError(
            "`agy` komutu bulunamadı. Antigravity CLI kurulu değil: %s" % INSTALL_URL
        )

    proc = subprocess.Popen(
        [exe] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        creationflags=_no_window_flags(),
    )

    lines: "queue.Queue[Tuple[str, Optional[str]]]" = queue.Queue()

    def pump(stream, tag: str) -> None:
        try:
            for line in stream:
                lines.put((tag, line))
        finally:
            lines.put((tag, None))

    readers = [threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True)]
    for reader in readers:
        reader.start()

    out_parts: List[str] = []
    err_parts: List[str] = []
    open_streams = 2
    started = time.monotonic()
    deadline = started + timeout
    last_beat = started

    try:
        while open_streams:
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                raise subprocess.TimeoutExpired(exe, timeout)
            try:
                # Yoklama araligi kalp atisini gecmemeli, yoksa atis gecikir.
                wait_s = min(remaining, 1.0, heartbeat_s if on_heartbeat else 1.0)
                tag, line = lines.get(timeout=max(wait_s, 0.05))
            except queue.Empty:
                now = time.monotonic()
                if on_heartbeat is not None and now - last_beat >= heartbeat_s:
                    last_beat = now
                    on_heartbeat(now - started)
                continue
            if line is None:
                open_streams -= 1
                continue
            if tag == "out":
                out_parts.append(line)
                if on_line is not None:
                    on_line(line)
            else:
                err_parts.append(line)

        proc.wait(timeout=max(1.0, deadline - time.monotonic()))
    except BaseException:
        # Zaman asimi, iptal ya da beklenmeyen bir hata: alt sureci arkamizda
        # birakmayalim - 200 saniye bosuna model yakan bir zombi olurdu.
        proc.kill()
        raise
    finally:
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except Exception:  # pragma: no cover - savunma amacli
                pass
    return proc.returncode, "".join(out_parts), "".join(err_parts)


def _work_dir() -> str:
    """Cagrilarin kosacagi izole, bos dizin.

    Kullanicinin proje klasorunde calistirmak hem ajanin tum depoyu baglama
    almasina (yavaslik + istenmeyen veri paylasimi) hem de dosyalara dokunma
    riskine yol acar.
    """
    path = config.WORK_DIR / "agy"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def list_models(timeout: int = MODELS_TIMEOUT_S) -> List[Tuple[str, str]]:
    """`agy models` çıktısı -> [(model_id, görünen_ad), ...]

    Aynı zamanda oturumun geçerli olduğunun kanıtıdır: kimlik yoksa bu komut
    model döndürmez.
    """
    try:
        res = _run(["models"], timeout=timeout, cwd=_work_dir())
    except (LLMNotConfiguredError, subprocess.TimeoutExpired, OSError) as exc:
        log.warning("agy models başarısız: %s", exc)
        return []
    if res.returncode != 0:
        log.warning("agy models çıkış kodu %s: %s", res.returncode, (res.stderr or "")[:200])
        return []

    models: List[Tuple[str, str]] = []
    for line in (res.stdout or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("fetching"):
            continue
        parts = line.split("\t", 1)
        model_id = parts[0].strip()
        label = parts[1].strip() if len(parts) > 1 else model_id
        if model_id:
            models.append((model_id, label))
    return models


def check_login(timeout: int = MODELS_TIMEOUT_S) -> Tuple[bool, str]:
    """Oturum gerçekten çalışıyor mu? -> (tamam_mi, açıklama)

    Tek güvenilir yol CLI'a sormaktır; `agy` kimliğini kendi saklar, biz
    kimlik dosyası okumayız.
    """
    if not is_available():
        return False, "`agy` komutu bulunamadı - Antigravity CLI kurulu değil"
    models = list_models(timeout=timeout)
    if not models:
        return False, ("Antigravity CLI kurulu ama oturum doğrulanamadı. "
                       "Bir terminalde `agy` çalıştırıp giriş yapın.")
    return True, "Antigravity CLI oturumu açık - %d model kullanılabilir" % len(models)


def _error_text(stdout: str, stderr: str, model: str) -> str:
    """CLI'nin hata cikisini kullanicinin okuyabilecegi tek satira indirir.

    `agy` hatayi da JSON govdesinde dondurur; ham govdeyi konsola basmak
    kullaniciya "invalid model selection" gibi asil mesaji kaybettiriyordu.

    Akis (stream-json) kipinde govde satir satir gelir, tek parca JSON degil; bu
    yuzden once satirlar taranir, bulunamazsa eski tek-govde yolu denenir.
    """
    raw = (stdout or "").strip() or (stderr or "").strip()
    message = raw

    found = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        body = event.get("result") if isinstance(event.get("result"), dict) else event
        found = str(body.get("error") or body.get("response") or "")
        if found:
            break

    if found:
        message = found
    else:
        start = raw.find("{")
        if start != -1:
            try:
                payload = json.loads(raw[start:])
                message = str(payload.get("error") or payload.get("response") or raw)
            except json.JSONDecodeError:
                pass
    message = " ".join(message.split())          # cok satirli listeyi tek satira indir
    if "not recognized as a known model" in message or "invalid model selection" in message:
        names = [model_id for model_id, _label in list_models()]
        return ("Model '%s' Antigravity CLI'da tanımlı değil. Pipeline sekmesinde "
                "Model listesini açıp geçerli bir tane seçin%s"
                % (model, (" (örn. %s)" % names[0]) if names else ""))
    return message[:400] or "ayrıntı yok"


class AgyClient(BaseLLMClient):
    """Gemini'yi Antigravity CLI üzerinden kullanır (anahtarsız)."""

    provider = config.PROVIDER_GEMINI

    def __init__(self, model: Optional[str] = None, **kwargs):
        super().__init__(model or config.DEFAULT_AGY_MODEL, **kwargs)
        if not is_available():
            raise LLMNotConfiguredError(
                "Antigravity CLI (`agy`) bulunamadı. Kurulum: %s - ya da Gemini "
                "için AI Studio API anahtarı girin." % INSTALL_URL
            )
        self.backend = config.GEMINI_BACKEND_CLI
        self.credential = config.Credential(
            config.KIND_SDK_DEFAULT, None, "Antigravity CLI (agy) oturumu"
        )
        log.info("Gemini kimliği: agy CLI / model %s", self.model)

    # ------------------------------------------------------------------ #
    def health_check(self) -> bool:
        """Oturum geçerli mi VE seçili model bu CLI'da var mı?

        Model doğrulaması burada yapılır çünkü pipeline'in 1. adımı health_check
        çağırır; yanlış model dakikalarca süren bir üretim çağrısından sonra
        değil, hemen başında bildirilmeli.
        """
        self.last_health_error = ""
        if not is_available():
            self.last_health_error = (
                "`agy` komutu bulunamadı - Antigravity CLI kurulu değil: %s" % INSTALL_URL)
            return False

        models = list_models()
        if not models:
            self.last_health_error = (
                "Antigravity CLI oturumu doğrulanamadı. Bir terminalde `agy` "
                "çalıştırıp giriş yapın.")
            return False

        names = [model_id for model_id, _label in models]
        if self.model not in names:
            self.last_health_error = (
                "Model '%s' Antigravity CLI'da yok. Kullanılabilir modeller: %s"
                % (self.model, ", ".join(names[:6]) + ("..." if len(names) > 6 else "")))
            return False
        return True

    # ------------------------------------------------------------------ #
    def _complete(self, system: str, user: str, max_tokens: int = 16000,
                  temperature: Optional[float] = None) -> str:
        # agy'de ayri bir "system" alani yok; tek istemde birlestiriyoruz.
        prompt = "%s\n\n%s" % (system.strip(), user.strip()) if system else user.strip()
        prompt += "\n\nCRITICAL INSTRUCTION: Do NOT invoke any tools or execute terminal commands. Output the response directly as raw text or code."
        if len(prompt) > MAX_PROMPT_CHARS:
            raise LLMError(
                "İstem Antigravity CLI için çok uzun (%d karakter, sınır %d). "
                "Satır sayısını düşürün ya da AI Studio API anahtarına geçin."
                % (len(prompt), MAX_PROMPT_CHARS)
            )

        args = [
            "--print", prompt,
            "--model", self.model,
            "--output-format", "stream-json",
            "--disable-slash-commands",
            "--dangerously-skip-permissions",
            "--print-timeout", "%ds" % CALL_TIMEOUT_S,
        ]

        last_stdout = ""
        for attempt in range(1, EMPTY_RESPONSE_ATTEMPTS + 1):
            payload, last_stdout = self._call_cli(args)
            text = str(payload.get("response", "") or "")
            in_tok, out_tok = _token_counts(payload, prompt, text)

            if text.strip():
                self._log_usage(in_tok, out_tok, purpose="agy_print")
                return text

            # Bos yanit da token harciyor; maliyet dokumu eksik kalmasin.
            self._log_usage(in_tok, out_tok, purpose="agy_print_empty")
            log.warning(
                "Antigravity CLI boş yanıt döndürdü (deneme %d/%d). Ham gövde: %s",
                attempt, EMPTY_RESPONSE_ATTEMPTS, _excerpt(last_stdout))

        raise LLMError(
            "Antigravity CLI %d denemede de boş yanıt döndürdü. Ajan CLI'ı yanıt "
            "yerine bir araç çağırmış olabilir; AI Studio API anahtarına geçmek bu "
            "davranışı tamamen ortadan kaldırır. Ham çıktı: %s"
            % (EMPTY_RESPONSE_ATTEMPTS, _excerpt(last_stdout))
        )

    def _call_cli(self, args: List[str]) -> Tuple[Dict, str]:
        """CLI'yi bir kez çağırır; (JSON gövdesi, ham stdout) döndürür.

        Ham stdout da döner: boş yanıtta teşhis izi olarak log'a yazılıyor.
        """
        self._report_progress(
            "agy çağrısı başladı - CLI açılışı tek başına ~200 sn sürüyor, "
            "ilk adım olayı ondan sonra gelir.")
        try:
            code, stdout, stderr = _stream(args, timeout=CALL_TIMEOUT_S + 60,
                                           cwd=_work_dir(), on_line=self._on_stream_line,
                                           on_heartbeat=self._on_stream_idle)
        except subprocess.TimeoutExpired as exc:
            raise LLMError(
                "Antigravity CLI %d saniyede yanıt vermedi. Ajan CLI'ı yavaştır; "
                "daha küçük bir model (örn. gemini-3.8-flash-low) deneyin ya da "
                "AI Studio API anahtarına geçin." % CALL_TIMEOUT_S
            ) from exc
        except OSError as exc:
            raise LLMError("Antigravity CLI çalıştırılamadı: %s" % exc) from exc

        if code != 0:
            raise LLMError("Antigravity CLI hata verdi: %s"
                           % _error_text(stdout, stderr, self.model))

        payload = self._parse(stdout)
        status = str(payload.get("status", "")).upper()
        if status and status != "SUCCESS":
            raise LLMError("Antigravity CLI '%s' durumu döndürdü: %s"
                           % (status, str(payload.get("error", ""))[:300]))

        log.debug("Antigravity CLI adımları: %s", " -> ".join(payload.get("steps") or []))
        if payload.get("recovered_from_deltas"):
            # Final yanit bostu ama metin akis parcalarindan toplandi: bu, Job #78'i
            # dusuren durumun ta kendisi - artik cagriyi kaybetmiyoruz.
            log.warning("Antigravity CLI final yanıtı boştu; metin akış "
                        "parçalarından toplandı (%d karakter).",
                        len(str(payload.get("response", ""))))
        return payload, stdout

    def _on_stream_idle(self, elapsed_s: float) -> None:
        """Çıktı gelmeyen sürede konsolun donmadığını gösterir."""
        self._report_progress("agy hâlâ çalışıyor (%d sn)" % int(elapsed_s))

    def _on_stream_line(self, line: str) -> None:
        """Akıştan gelen tek satırı canlı ilerleme mesajına çevirir.

        Adım 2'den sonra dakikalarca sessiz kalan konsolun tek bilgi kaynağı bu.
        Hiçbir koşulda hata yükseltmez: bozuk bir satır çağrıyı düşürmemeli.
        """
        line = line.strip()
        if not line.startswith("{"):
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict) or event.get("event") != "step_update":
            return

        update = event.get("step_update")
        if not isinstance(update, dict):
            return
        message = "agy adımı: %s (%s)" % (update.get("step_type", "?"),
                                          update.get("state", "?"))
        duration = update.get("duration_seconds")
        if isinstance(duration, (int, float)):
            message += " - %.1f sn" % duration
        self._report_progress(message)

    @staticmethod
    def _parse(stdout: str) -> Dict:
        """NDJSON akışını tek bir yanıt gövdesine indirger.

        Dönen sözlük `--output-format json` gövdesiyle aynı şekildedir
        (``status`` / ``response`` / ``usage``), böylece çağıran taraf akışı bilmek
        zorunda kalmaz. Ek olarak ``steps`` (adım özetleri) ve
        ``recovered_from_deltas`` (metin final yanıttan değil parçalardan toplandı mı)
        alanları döner.

        JSON olmayan satırlar (CLI'nin ilerleme yazıları) sessizce atlanır.
        """
        deltas: List[str] = []
        steps: List[str] = []
        result: Optional[Dict] = None

        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue

            kind = event.get("event")
            if kind == "step_update":
                update = event.get("step_update") or {}
                if not isinstance(update, dict):
                    continue
                steps.append("%s/%s" % (update.get("step_type", "?"),
                                        update.get("state", "?")))
                delta = update.get("text_delta")
                if isinstance(delta, str):
                    deltas.append(delta)
            elif kind == "result":
                payload = event.get("result")
                if isinstance(payload, dict):
                    result = payload

        if result is None:
            raise LLMError("Antigravity CLI sonuç olayı döndürmedi: %s" % _excerpt(stdout))

        payload = dict(result)
        payload["steps"] = steps
        payload["recovered_from_deltas"] = False

        # Ajan final metni bos birakip araci cagirdiysa metin parcalarda kalir.
        if not str(payload.get("response", "") or "").strip():
            joined = "".join(deltas).strip()
            if joined:
                payload["response"] = joined
                payload["recovered_from_deltas"] = True
        return payload
