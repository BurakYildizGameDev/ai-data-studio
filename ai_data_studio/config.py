"""Uygulama genelinde yapılandırma, yol yönetimi ve güvenli kimlik saklama.

Sistem geneli yol ve I/O prensipleri:
  * Tüm uygulama verisi işletim sisteminin yerel uygulama dizini altında toplanır
    (%LOCALAPPDATA%\\AIDataStudio veya platform karşılığı).
  * Tüm dosya I/O işlemleri standart UTF-8 kodlaması kullanır (read_text, write_text,
    read_json, write_json yardımcıları).

Kimlik bilgileri ve API anahtarları işletim sistemi seviyesinde güvenli credential store
(keyring) üzerinde saklanır; ortam değişkenleri ikincil kaynak olarak desteklenir.
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

# i18n modul duzeyinde config'i import etmez (dili ilk t() cagrisinda tembelce cozer),
# bu yuzden bu import dongu olusturmaz.
from .i18n import t

APP_NAME = "AIDataStudio"
KEYRING_SERVICE = "AIDataStudio"

# --------------------------------------------------------------------------- #
# Sistem Yolları
# --------------------------------------------------------------------------- #
# AIDATASTUDIO_DATA_DIR tanımlıysa tüm uygulama verisi oraya yazılır. Testler ve
# headless CI bunu geçici bir dizine yönlendirir; aksi hâlde test koşusu kullanıcının
# canlı app_state.db dosyasını paylaşır ve bozabilir.
_DATA_DIR_ENV = "AIDATASTUDIO_DATA_DIR"


def _resolve_app_data_dir() -> Path:
    override = os.getenv(_DATA_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path(os.getenv("LOCALAPPDATA") or Path.home()) / APP_NAME


APP_DATA_DIR = _resolve_app_data_dir()
DB_PATH = APP_DATA_DIR / "app_state.db"
OUTPUT_DIR = APP_DATA_DIR / "outputs"      # Doğrulanmış temiz veri setleri
RAW_DIR = APP_DATA_DIR / "raw"             # Sandbox ham çıktıları
WORK_DIR = APP_DATA_DIR / "work"           # İzole sandbox çalışma dizini
LOG_DIR = APP_DATA_DIR / "logs"
SETTINGS_PATH = APP_DATA_DIR / "settings.json"

for _d in (APP_DATA_DIR, OUTPUT_DIR, RAW_DIR, WORK_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Paketlenmiş .exe içinde kaynak dosyalar PyInstaller _MEIPASS dizinindedir.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

# --------------------------------------------------------------------------- #
# Pipeline Sabitleri
# --------------------------------------------------------------------------- #
MAX_CODEGEN_RETRIES = 3         # Self-healing kod düzeltme limiti
SANDBOX_TIMEOUT_S = 90          # Üretici kod çalıştırma zaman aşımı (saniye)
SANDBOX_MEMORY_LIMIT_MB = 2048  # psutil bellek watchdog üst sınırı (MB)
DEFAULT_ROW_TARGET = 100_000
DEFAULT_RANDOM_SEED = 42

# Sandbox içinde izin verilen kütüphane allowlist'i
ALLOWED_IMPORTS = {
    "pandas", "numpy", "scipy", "faker", "random", "math", "datetime", "json",
    "string", "itertools", "collections", "decimal", "statistics", "uuid", "re",
    "time", "calendar", "typing", "copy", "bisect", "hashlib",
}

# --------------------------------------------------------------------------- #
# LLM Sağlayıcıları
# --------------------------------------------------------------------------- #
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GEMINI = "gemini"
PROVIDER_OLLAMA = "ollama"

DEFAULT_MODELS = {
    PROVIDER_ANTHROPIC: "claude-opus-5",
    PROVIDER_GEMINI: "gemini-2.5-pro",
    PROVIDER_OLLAMA: "qwen2.5-coder:7b",
}

# Model token maliyet tarifesi (USD / 1M token).
# Yerel Ollama modelleri ücretsizdir ($0.00).
MODEL_PRICING_USD_PER_MTOK = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
}

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


def _resolve_ollama_num_ctx(default: int = 16384) -> int:
    """Ollama bağlam penceresi (token).

    İstekte num_ctx verilmezse Ollama modeli 4096 ile yükler ve sığmayan prompt'un
    başını sessizce keser - hata vermez, model sadece talimatları "unutur". İlişkisel
    kod prompt'u tek başına ~3k token; düzeltme adımında önceki kod ve traceback de
    eklenir. Pencere büyüdükçe KV önbelleği VRAM tüketir; düşük VRAM'de
    AIDATASTUDIO_OLLAMA_NUM_CTX ile küçültülebilir.
    """
    raw = os.getenv("AIDATASTUDIO_OLLAMA_NUM_CTX", "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if value >= 2048 else default


OLLAMA_NUM_CTX = _resolve_ollama_num_ctx()

# --------------------------------------------------------------------------- #
# Gemini Arka Uçları
# --------------------------------------------------------------------------- #
#   aistudio - Google AI Studio API anahtarı (hızlı, yüksek kota, varsayılan).
#   cli      - Antigravity CLI (`agy`) oturumu (ek API anahtarı gerektirmez).
GEMINI_BACKEND_AISTUDIO = "aistudio"
GEMINI_BACKEND_CLI = "cli"

# Antigravity CLI komutu ve varsayilan modeli. Model listesi calisma aninda
# `agy models` ile alinir; bu yalnizca ilk acilistaki secimdir.
AGY_EXECUTABLE = "agy"
DEFAULT_AGY_MODEL = "gemini-3.8-flash-high"

# Kullanicinin ucretsiz/kendi anahtarini alabilecegi adresler (GUI link butonu).
API_KEY_URLS = {
    PROVIDER_ANTHROPIC: "https://console.anthropic.com/settings/keys",
    PROVIDER_GEMINI: "https://aistudio.google.com/apikey",
    "huggingface": "https://huggingface.co/settings/tokens",
}

# --------------------------------------------------------------------------- #
# Kimlik bilgisi kaynaklari
# --------------------------------------------------------------------------- #
# Her saglayici icin: keyring hesap adi + oncelik sirasiyla ortam degiskenleri.
# Ortam degiskeni listesi SDK'larin kendi okudugu adlari da icerir - aksi halde
# gecerli kimlik bilgisi olan kullaniciya "key bulunamadi" denir.
_KEYRING_ACCOUNTS = {
    PROVIDER_ANTHROPIC: "anthropic_api_key",
    PROVIDER_GEMINI: "gemini_api_key",
    "huggingface": "hf_token",
}
CREDENTIAL_ENV_VARS = {
    PROVIDER_ANTHROPIC: ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
    PROVIDER_GEMINI: ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "huggingface": ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"),
}
# Bearer token olarak gonderilmesi gereken degiskenler (x-api-key degil).
_AUTH_TOKEN_VARS = {"ANTHROPIC_AUTH_TOKEN"}

# Geriye donuk uyumluluk: (keyring_hesabi, birincil_env_var)
_KEY_ACCOUNTS = {
    provider: (_KEYRING_ACCOUNTS[provider], CREDENTIAL_ENV_VARS[provider][0])
    for provider in _KEYRING_ACCOUNTS
}

KIND_API_KEY = "api_key"
KIND_AUTH_TOKEN = "auth_token"
KIND_SDK_DEFAULT = "sdk_default"
KIND_NONE = "none"

# --------------------------------------------------------------------------- #
# Ilerleme olayi onem dereceleri
# --------------------------------------------------------------------------- #
# Konsol rengini BU alan belirler. Mesajin metnine bakmak ("UYARI ile mi
# basliyor") dile bagimlidir ve arayuz cevrildigi anda sessizce bozulur; bu
# yuzden severity olayin kendisinde tasiniyor.
PROGRESS_INFO = "info"
PROGRESS_SUCCESS = "success"
PROGRESS_WARNING = "warning"
PROGRESS_ERROR = "error"
PROGRESS_LEVELS = (PROGRESS_INFO, PROGRESS_SUCCESS, PROGRESS_WARNING, PROGRESS_ERROR)

DEFAULT_SETTINGS: Dict[str, Any] = {
    "provider": PROVIDER_ANTHROPIC,
    "model": DEFAULT_MODELS[PROVIDER_ANTHROPIC],
    "faker_locale": "tr_TR",
    "row_count_target": DEFAULT_ROW_TARGET,
    "random_seed": DEFAULT_RANDOM_SEED,
    "use_hf_seed": False,
    "hf_seed_query": "",
    "export_formats": ["csv", "parquet"],
    "export_pdf": False,
    "appearance": "dark",
    # Arayuz dili (bkz. ai_data_studio/i18n.py). Varsayilan Ingilizce; degisiklik
    # yeniden baslatma ister, widget metinleri canli degistirilmiyor.
    "language": "en",
    "gemini_backend": GEMINI_BACKEND_AISTUDIO,
    # Uretim / zenginlestirme motorlari (bkz. core/orchestrator ENGINES).
    # Deger olarak motor ADI saklanir, arayuz etiketi degil.
    "engine": "llm",
    "time_series": False,
    "expand_features": False,
    "dirty_rate": 0.0,
}


# --------------------------------------------------------------------------- #
# UTF-8 zorunlu dosya yardimcilari (Bolum 10.5)
# --------------------------------------------------------------------------- #
def read_text(path) -> str:
    """Her zaman UTF-8 okur."""
    return Path(path).read_text(encoding="utf-8")


def write_text(path, content: str) -> None:
    """Her zaman UTF-8 yazar, üst dizini oluşturur."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def read_json(path, default: Any = None) -> Any:
    try:
        return json.loads(read_text(path))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# Kullanici ayarlari
# --------------------------------------------------------------------------- #
def load_settings() -> Dict[str, Any]:
    stored = read_json(SETTINGS_PATH, default={}) or {}
    settings = dict(DEFAULT_SETTINGS)
    settings.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
    return settings


def save_settings(settings: Dict[str, Any]) -> None:
    merged = load_settings()
    merged.update(settings)
    write_json(SETTINGS_PATH, merged)


# --------------------------------------------------------------------------- #
# API key yonetimi (keyring + env fallback)
# --------------------------------------------------------------------------- #
def _keyring():
    try:
        import keyring
        return keyring
    except Exception:  # pragma: no cover - keyring backend yoksa
        return None


class Credential(NamedTuple):
    """Çözülmüş kimlik bilgisi.

    kind:
        api_key      - x-api-key / api_key olarak gönderilir
        auth_token   - Authorization: Bearer olarak gönderilir
        sdk_default  - Değer bizde yok; SDK kendi zincirini çözecek
                       (ant auth login profili, Antigravity CLI, hf login ...)
        none         - Hiçbir yerde kimlik bilgisi bulunamadı
    """

    kind: str
    value: Optional[str]
    source: str


def _keyring_value(provider: str) -> Optional[str]:
    account = _KEYRING_ACCOUNTS.get(provider)
    if account is None:
        return None
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(KEYRING_SERVICE, account) or None
    except Exception as exc:  # pragma: no cover
        logging.getLogger(__name__).warning("keyring okunamadı: %s", exc)
        return None


# Anthropic OAuth token'lari `sk-ant-oat...` ile baslar ve Authorization: Bearer
# olarak gonderilmelidir; API anahtarlari (`sk-ant-api...`) x-api-key olarak.
# Yanlis basligi kullanmak 401 verir, o yuzden degere bakip karar veriyoruz.
_OAUTH_TOKEN_PREFIX = "sk-ant-oat"


def anthropic_value_kind(value: str) -> str:
    """Bir Anthropic kimlik değerinin api_key mi auth_token mi olduğunu söyler."""
    return (KIND_AUTH_TOKEN if (value or "").startswith(_OAUTH_TOKEN_PREFIX)
            else KIND_API_KEY)


def claude_code_credentials() -> Dict[str, Any]:
    """Claude Code CLI oturumunun ham durumu (~/.claude/.credentials.json).

    Döner: {"found", "token", "expires_at" (epoch sn | None), "expired"}

    ÖNEMLİ: accessToken tipik olarak ~8 saatte doluyor. Eskiden dosyanın
    varlığına bakıp "giriş yapılmış" deniyordu; token dolmuşsa uygulama
    401 alıyor ve kullanıcı "giriş yaptım ama kabul etmiyor" çıkmazına
    düşüyordu. Artık son kullanma tarihi de kontrol ediliyor.
    """
    blank = {"found": False, "token": None, "expires_at": None, "expired": False}
    p = Path.home() / ".claude" / ".credentials.json"
    if not p.is_file():
        return blank
    try:
        data = read_json(p, default={}) or {}
        oauth = data.get("claudeAiOauth") or {}
        token = oauth.get("accessToken")
        if not token or not isinstance(token, str):
            return blank
        expires_at = oauth.get("expiresAt")
        expires_s = None
        if isinstance(expires_at, (int, float)) and expires_at > 0:
            expires_s = float(expires_at) / 1000.0   # CLI milisaniye yaziyor
        import time
        expired = bool(expires_s is not None and expires_s <= time.time())
        return {"found": True, "token": token.strip(),
                "expires_at": expires_s, "expired": expired}
    except Exception:
        return blank


def claude_code_oauth_token() -> Optional[str]:
    """Claude Code CLI OAuth token'i - YALNIZCA süresi dolmamışsa."""
    info = claude_code_credentials()
    return info["token"] if (info["found"] and not info["expired"]) else None


def resolve_credential(provider: str) -> Credential:
    """Bir sağlayıcının kimlik bilgisini TÜM kaynaklarda öncelik sırasıyla arar.

    Sıra: keyring -> ortam değişkenleri (SDK'nin kendi adları dahil) ->
    Claude Code OAuth token'i -> SDK'nin kendi çözüm zinciri (profil / ADC / hf login) -> yok.
    """
    if provider not in _KEYRING_ACCOUNTS:
        return Credential(KIND_NONE, None, t("auth.source.unknown_provider"))

    value = _keyring_value(provider)
    if value:
        kind = (anthropic_value_kind(value) if provider == PROVIDER_ANTHROPIC
                else KIND_API_KEY)
        return Credential(kind, value, t("auth.source.keyring"))

    for env_var in CREDENTIAL_ENV_VARS[provider]:
        value = os.getenv(env_var)
        if value:
            if env_var in _AUTH_TOKEN_VARS:
                kind = KIND_AUTH_TOKEN
            elif provider == PROVIDER_ANTHROPIC:
                kind = anthropic_value_kind(value)
            else:
                kind = KIND_API_KEY
            return Credential(kind, value, t("auth.source.env_var", var=env_var))

    if provider == PROVIDER_ANTHROPIC:
        claude_token = claude_code_oauth_token()
        if claude_token:
            return Credential(KIND_AUTH_TOKEN, claude_token, t("auth.source.claude_code"))

    fallback = _sdk_default_source(provider)
    if fallback:
        return Credential(KIND_SDK_DEFAULT, None, fallback)

    return Credential(KIND_NONE, None, t("auth.source.not_found"))


# --------------------------------------------------------------------------- #
# OAuth / CLI girisi (API anahtari yerine tarayici ile oturum acma)
# --------------------------------------------------------------------------- #
def _appdata() -> Optional[Path]:
    value = os.getenv("APPDATA")
    return Path(value) if value else None


def anthropic_profile_dir() -> Optional[Path]:
    """`ant auth login` profillerinin bulunduğu dizin (varsa)."""
    candidates = [Path.home() / ".config" / "anthropic"]
    appdata = _appdata()
    if appdata:
        candidates.append(appdata / "anthropic")
    for path in candidates:
        try:
            if path.is_dir() and any(path.iterdir()):
                return path
        except OSError:
            continue
    return None


def agy_available() -> bool:
    """Antigravity CLI (`agy`) PATH'te mi? Ucuz kontrol - alt surec baslatmaz."""
    return cli_available(AGY_EXECUTABLE)


# --------------------------------------------------------------------------- #
# Gemini arka uç seçimi
# --------------------------------------------------------------------------- #
# Surec-yerel gecersiz kilma. Arka uc yalnizca kalici settings.json'dan gelseydi
# headless bir kosu (CI, --gemini-backend) kullanicinin ayarini kalici olarak
# degistirmek zorunda kalirdi.
GEMINI_BACKEND_ENV = "AIDATASTUDIO_GEMINI_BACKEND"


def gemini_backend() -> str:
    """Seçili Gemini arka ucu: 'aistudio' (varsayılan) veya 'cli'.

    Oncelik sirasi: ortam degiskeni (surec-yerel) -> settings.json -> varsayilan.
    """
    override = os.getenv(GEMINI_BACKEND_ENV, "").strip().lower()
    if override in (GEMINI_BACKEND_AISTUDIO, GEMINI_BACKEND_CLI):
        return override
    value = load_settings().get("gemini_backend", GEMINI_BACKEND_AISTUDIO)
    return value if value in (GEMINI_BACKEND_AISTUDIO, GEMINI_BACKEND_CLI) \
        else GEMINI_BACKEND_AISTUDIO


def set_gemini_backend(backend: str) -> None:
    """Arka ucu kalıcı olarak kaydeder."""
    if backend not in (GEMINI_BACKEND_AISTUDIO, GEMINI_BACKEND_CLI):
        raise ValueError("Unknown Gemini backend: %s" % backend)
    save_settings({"gemini_backend": backend})


def _sdk_default_source(provider: str) -> Optional[str]:
    """SDK'nin kendi çözebileceği bir kimlik var mi? Varsa insan okunur adı.

    Ucuz kontroller - ag çağrısı yapmaz, yalnızca dosya/ortam bakar.
    """
    if provider == PROVIDER_ANTHROPIC:
        if anthropic_profile_dir():
            return t("auth.source.ant_profile")
        if os.getenv("ANTHROPIC_FEDERATION_RULE_ID"):
            return "Workload Identity Federation"
    elif provider == PROVIDER_GEMINI:
        # Yalnızca kullanıcı CLI yolunu açıkça seçtiyse ve `agy` kuruluysa.
        # Oturumun gerçekten geçerli olduğu ancak CLI'a sorularak anlaşılır;
        # bunu health_check() / "Bağlantıyı test et" yapar.
        if gemini_backend() == GEMINI_BACKEND_CLI and agy_available():
            return t("auth.source.agy_session")
    elif provider == "huggingface":
        try:
            from huggingface_hub import get_token
            if get_token():
                return t("auth.source.hf_login")
        except Exception:
            pass
    return None


def oauth_status(provider: str) -> Dict[str, Any]:
    """Bir sağlayıcı için OAuth/CLI girişi durumu ve yapılacak komut.

    GUI ve --check-auth bunu gösterir: giriş yapılmış mi, yapılmadıysa hangi
    komut çalıştırılmalı, ve varsa "yanlış" bir giriş tespit edildi mi.
    """
    if provider == PROVIDER_ANTHROPIC:
        creds = claude_code_credentials()
        profile = anthropic_profile_dir()
        logged_in = bool((creds["found"] and not creds["expired"]) or profile)

        import shutil
        # `claude setup-token` uzun omurlu token uretir - programatik kullanim
        # icin dogru yol budur. Ciplak `claude` yalnizca etkilesimli oturum acar,
        # bir "giris" komutu degildir.
        if shutil.which("claude"):
            cmd = ["claude", "setup-token"]
        elif shutil.which("ant"):
            cmd = ["ant", "auth", "login"]
        else:
            cmd = ["claude", "setup-token"]

        note = t("auth.oauth.claude_note")
        if creds["found"] and creds["expired"]:
            detail = t("auth.oauth.claude_expired")
        elif creds["found"]:
            detail = t("auth.oauth.claude_active")
            if creds["expires_at"]:
                import datetime
                left = creds["expires_at"] - datetime.datetime.now().timestamp()
                hours = max(0, int(left // 3600))
                detail += t("auth.oauth.hours_left", hours=hours)
                if hours < 24:
                    note = t("auth.oauth.claude_expiring_note", hours=hours)
        elif profile:
            detail = t("auth.oauth.profile", path=profile)
        else:
            detail = t("settings.oauth.not_logged_in")

        return {
            "supported": True,
            "logged_in": logged_in,
            "detail": detail,
            "command": cmd,
            "install_hint": "npm install -g @anthropic-ai/claude-code",
            "note": note,
            "api_key_url": API_KEY_URLS[PROVIDER_ANTHROPIC],
        }
    if provider == PROVIDER_GEMINI:
        # Gemini'nin anahtarsız yolu = Antigravity CLI (`agy`). Claude Code
        # oturumunun kullanıldığı yoldaki mantığın aynısı: kimlik dosyasına
        # dokunmayız, CLI'ı çağırırız, o kendi oturumunu kullanır.
        installed = agy_available()
        detail = (t("auth.oauth.agy_installed") if installed
                  else t("auth.oauth.agy_missing"))
        return {
            "supported": True,
            "logged_in": installed,
            "detail": detail,
            "command": [AGY_EXECUTABLE],
            "install_hint": "https://antigravity.google/download",
            "note": t("auth.oauth.agy_note"),
            "api_key_url": API_KEY_URLS[PROVIDER_GEMINI],
        }
    if provider == "huggingface":
        try:
            from huggingface_hub import get_token
            logged_in = bool(get_token())
        except Exception:
            logged_in = False
        return {
            "supported": True,
            "logged_in": logged_in,
            "detail": (t("auth.oauth.hf_token_saved") if logged_in
                       else t("auth.oauth.hf_not_logged_in")),
            "command": ["huggingface-cli", "login"],
            "install_hint": "pip install huggingface_hub[cli]",
            "note": "",
            "api_key_url": API_KEY_URLS["huggingface"],
        }
    return {"supported": False, "logged_in": False, "detail": "", "command": [],
            "install_hint": "", "note": "", "api_key_url": ""}


def launch_login_process(command: List[str]):
    """CLI giriş komutunu yeni bir konsol penceresinde başlatır."""
    import subprocess
    import shutil
    cmd = list(command)
    resolved = shutil.which(cmd[0])
    if resolved:
        cmd[0] = resolved
    if sys.platform == "win32":
        return subprocess.Popen(
            cmd,
            shell=True,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        )
    return subprocess.Popen(cmd)


def cli_available(executable: str) -> bool:
    """Komut PATH'te var mi?"""
    import shutil
    return shutil.which(executable) is not None


def get_api_key(provider: str) -> Optional[str]:
    """Çözülen kimlik bilgisinin ham değeri. SDK'ya bırakılıyorsa None."""
    return resolve_credential(provider).value


def credential_status(provider: str) -> Dict[str, Any]:
    """GUI/CLI'da gösterilecek kimlik durumu özeti."""
    cred = resolve_credential(provider)
    return {
        "provider": provider,
        "kind": cred.kind,
        "source": cred.source,
        "configured": cred.kind != KIND_NONE,
        "explicit": cred.kind in (KIND_API_KEY, KIND_AUTH_TOKEN),
        "checked_env_vars": list(CREDENTIAL_ENV_VARS.get(provider, ())),
    }


def missing_credential_message(provider: str) -> str:
    """Kimlik bulunamadığında nerelere bakıldığını söyleyen hata metni."""
    env_vars = " / ".join(CREDENTIAL_ENV_VARS.get(provider, ()))
    extra_key = {
        PROVIDER_ANTHROPIC: "auth.missing.extra_anthropic",
        PROVIDER_GEMINI: "auth.missing.extra_gemini",
        "huggingface": "auth.missing.extra_huggingface",
    }.get(provider)
    return t("auth.missing.message", provider=provider, env_vars=env_vars,
             extra=t(extra_key) if extra_key else "")


def set_api_key(provider: str, value: str) -> bool:
    """Key'i OS credential store'a yazar. Başarılı olursa True."""
    account = _KEYRING_ACCOUNTS.get(provider)
    if account is None:
        raise ValueError("Unknown provider: " + str(provider))
    kr = _keyring()
    if kr is None:
        return False
    try:
        if value:
            kr.set_password(KEYRING_SERVICE, account, value)
        else:
            try:
                kr.delete_password(KEYRING_SERVICE, account)
            except Exception:
                pass
        return True
    except Exception as exc:  # pragma: no cover
        logging.getLogger(__name__).error("keyring yazılamadı: %s", exc)
        return False


def has_api_key(provider: str) -> bool:
    """Açıkça tanımlanmış bir anahtar/token var mi?

    SDK'nin kendi çözebileceği kimlikler (profil, ADC) buraya dahil DEĞİLDİR -
    onlar için has_credential() kullanın."""
    return resolve_credential(provider).kind in (KIND_API_KEY, KIND_AUTH_TOKEN)


def has_credential(provider: str) -> bool:
    """Herhangi bir kaynakta (SDK'nin kendi zinciri dahil) kimlik var mi?"""
    return resolve_credential(provider).kind != KIND_NONE


# --------------------------------------------------------------------------- #
# Konsol kodlamasi
# --------------------------------------------------------------------------- #
def _utf8_stream(stream):
    """Bir stdio akisini UTF-8'e cevirir; olmazsa sarmalayici dener."""
    if stream is None:
        return None
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
        return stream
    except (AttributeError, ValueError, OSError):
        pass
    try:
        return io.TextIOWrapper(
            stream.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
    except Exception:
        return stream


def force_utf8_stdio() -> None:
    """stdout/stderr'i UTF-8'e sabitler.

    Arayuz metinleri Turkce oldugu icin cp437/cp1252 gibi bir konsolda ciplak
    ``print()`` cagrilari UnicodeEncodeError ile cokuyordu. Giris noktalarinda
    (CLI ``main()`` ve GUI ``launch()``) argparse calismadan once cagrilmalidir.
    """
    if getattr(force_utf8_stdio, "_done", False):
        return
    sys.stdout = _utf8_stream(sys.stdout) or sys.stdout
    sys.stderr = _utf8_stream(sys.stderr) or sys.stderr
    force_utf8_stdio._done = True  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# --------------------------------------------------------------------------- #
# Loglama
# --------------------------------------------------------------------------- #
def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Kök logger'i konsol + dosya handler ile bir kez kurar."""
    if getattr(setup_logging, "_configured", False):
        return logging.getLogger(APP_NAME)
    root = logging.getLogger()
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", datefmt="%H:%M:%S"
    )
    file_handler = logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
    # PyInstaller --noconsole modunda stderr None olabilir.
    if sys.stderr is not None:
        # Windows konsolu cp1252 olabilir; arayuz ve log mesajlari Turkce
        # oldugu icin ciplak stderr'e yazmak UnicodeEncodeError uretiyordu.
        # Konsolu UTF-8'e cevirmeyi dene, olmazsa kodlanamayan karakteri
        # kaybetmeyi log'u tamamen kaybetmeye tercih et.
        force_utf8_stdio()
        target = sys.stderr
        stream = logging.StreamHandler(target)
        stream.setFormatter(fmt)
        root.addHandler(stream)
    root.setLevel(level)
    setup_logging._configured = True  # type: ignore[attr-defined]
    return logging.getLogger(APP_NAME)
