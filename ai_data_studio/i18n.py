"""Kullanıcıya görünen metinler için sözlük tabanlı çeviri katalogu.

Neden `gettext` değil: `.mo` dosyalarını PyInstaller paketine taşıtmak fazladan
iş ve Faz 9'u (tek dosyalık `.exe`) zorlaştırır. Katalog düz Python sözlüğü
olduğu için pakete kendiliğinden girer, derlenmesi gerekmez.

Kullanım::

    from .i18n import t

    print(t("cli.auth.header"))
    print(t("pipeline.rows.summary", rows=5000))

Kurallar
--------

* **Anahtarlar ASCII** ve ``modul.baglam.kisa_ad`` biçiminde. Karşılaştırmalar
  her zaman ANAHTAR üzerinden yapılır, çeviri metni üzerinden değil - aksi hâlde
  dil değişince mantık bozulur (bkz. ``gui/app_window.py`` içindeki ``_fold``).
* **Varsayılan dil İngilizce**, Türkçe tam çeviri. Doğrulanamayan üçüncü bir dil
  yayınlanmıyor: yarım çeviri temiz İngilizce'den daha özensiz görünür.
* Bir anahtarın seçili dilde karşılığı yoksa İngilizce'ye, o da yoksa anahtarın
  kendisine düşülür. Sessiz eksik çeviri olmasın diye
  ``tests/test_i18n.py`` bütün ``t("...")`` çağrılarını AST ile tarar.

Çeviri DIŞINDA kalanlar
-----------------------

* **LLM istemleri** (``services/prompt_blocks.py``, ``planner_prompts.py``,
  ``relational_prompts.py``, ``llm_base.py``). Model çıktısının kullanıcının
  arayüz diline göre değişmesi kabul edilemez.
* **Log kayıtları** (``log.info`` / ``log.warning`` / ``log.error``). Log'un dili
  sabit olmalı, yoksa aynı hatanın iki dilde iki farklı kaydı olur ve arama
  yapılamaz.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List

log = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "en"

# Dil kodu -> kullanıcıya gösterilecek ad. Ayarlar sekmesindeki seçici bunu okur.
LANGUAGE_NAMES: Dict[str, str] = {
    "en": "English",
    "tr": "Türkçe",
    "de": "Deutsch",
    "fr": "Français",
    "ru": "Русский",
    "zh": "简体中文",
    "ja": "日本語",
}

_LOCALE_PREFIX_MAP = {
    "tr": "tr", "turkish": "tr",
    "de": "de", "german": "de",
    "fr": "fr", "french": "fr",
    "ru": "ru", "russian": "ru",
    "zh": "zh", "chinese": "zh",
    "ja": "ja", "japanese": "ja",
    "en": "en", "english": "en",
}


def detect_system_language() -> str:
    """Detects system language code if supported, falling back to DEFAULT_LANGUAGE."""
    import locale
    import os
    try:
        env_lang = os.getenv("LC_ALL") or os.getenv("LC_MESSAGES") or os.getenv("LANG")
        if env_lang:
            code = env_lang.split(".")[0].split("_")[0].lower()
            if code in _LOCALE_PREFIX_MAP:
                return _LOCALE_PREFIX_MAP[code]
        loc = locale.getlocale()[0]
        if loc:
            code = loc.split("_")[0].lower()
            if code in _LOCALE_PREFIX_MAP:
                return _LOCALE_PREFIX_MAP[code]
    except Exception:
        pass
    return DEFAULT_LANGUAGE


_catalogs: Dict[str, Dict[str, str]] = {}
_language: str = DEFAULT_LANGUAGE
_resolved = False
# Yalnizca o anki is parcacigini etkileyen dil (bkz. language_override).
_thread_state = threading.local()


def _load_catalog(language: str) -> Dict[str, str]:
    """Bir dilin katalogunu yükler; bulunamazsa boş sözlük döner."""
    if language in _catalogs:
        return _catalogs[language]
    try:
        from importlib import import_module
        module = import_module("ai_data_studio.locales.%s" % language)
        catalog = dict(getattr(module, "MESSAGES", {}))
    except Exception as exc:  # pragma: no cover - eksik/bozuk katalog
        log.warning("Language catalog could not be loaded (%s): %s", language, exc)
        catalog = {}
    _catalogs[language] = catalog
    return catalog


def available_languages() -> List[str]:
    """Katalogu bulunan dil kodları."""
    return [code for code in LANGUAGE_NAMES if _load_catalog(code)]


def set_language(language: str) -> str:
    """Aktif dili değiştirir ve gerçekten ayarlanan kodu döndürür."""
    global _language, _resolved
    code = (language or "").strip().lower()
    if code not in LANGUAGE_NAMES:
        log.warning("Unknown language %r, falling back to %r", language, DEFAULT_LANGUAGE)
        code = DEFAULT_LANGUAGE
    _language = code
    _resolved = True
    return _language


@contextmanager
def language_override(language: str) -> Iterator[None]:
    """Blok süresince YALNIZCA bu iş parçacığında ``t()`` başka dilde çalışır.

    Neden: sözleşme doğrulama hataları ``t()`` ile arayüz dilinde üretiliyor ve aynı
    metin self-healing isteminde modele geri gönderiliyordu - Türkçe arayüzde model
    Türkçe düzeltme talimatı alıyordu ("LLM metni çeviri dışı" kuralına aykırı).
    Global ``set_language`` kullanılamaz: pipeline işçi iş parçacığında koşarken arayüz
    iş parçacığı aynı anda ``t()`` çağırıyor ve bir anlığına İngilizce metin basardı.
    """
    code = (language or "").strip().lower()
    if code not in LANGUAGE_NAMES:
        code = DEFAULT_LANGUAGE
    previous = getattr(_thread_state, "language", None)
    _thread_state.language = code
    try:
        yield
    finally:
        _thread_state.language = previous


def get_language() -> str:
    """Aktif dil kodu; ilk çağrıda ayarlardan çözülür."""
    override = getattr(_thread_state, "language", None)
    if override:
        return override
    if not _resolved:
        try:
            from . import config
            set_language(config.load_settings().get("language", DEFAULT_LANGUAGE))
        except Exception as exc:  # pragma: no cover - ayarlar okunamadi
            log.debug("Language could not be resolved from settings: %s", exc)
            set_language(DEFAULT_LANGUAGE)
    return _language


def t(key: str, **kwargs: Any) -> str:
    """Anahtarın aktif dildeki karşılığını döndürür.

    ``kwargs`` verilirse metin ``str.format`` ile doldurulur. Biçimlendirme
    hatası metni düşürmez: ham metin döner ve durum log'a yazılır - bir çeviri
    kusuru yüzünden arayüzün çökmesi kabul edilemez.
    """
    language = get_language()
    text = _load_catalog(language).get(key)
    if text is None and language != DEFAULT_LANGUAGE:
        text = _load_catalog(DEFAULT_LANGUAGE).get(key)
    if text is None:
        log.warning("Missing translation key: %s", key)
        return key
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError, ValueError) as exc:
        log.warning("Translation formatting failed for %s: %s", key, exc)
        return text


def reset_for_tests() -> None:
    """Test izolasyonu: yüklenmiş katalogları ve çözülmüş dili unutur."""
    global _resolved, _language
    _catalogs.clear()
    _resolved = False
    _language = DEFAULT_LANGUAGE
