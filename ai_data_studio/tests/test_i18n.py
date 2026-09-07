# -*- coding: utf-8 -*-
"""Çeviri katalogu testleri.

En önemlisi `TestCatalogCoverage`: kaynak kodda kullanılan her `t("...")`
anahtarının katalogda karşılığı olmalı ve İngilizce katalogdaki her anahtarın
Türkçe karşılığı bulunmalı. Eksik çeviri sessizce İngilizce'ye düşmemeli -
yarım çeviri temiz İngilizce'den daha özensiz görünür.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import Dict, Set

from ai_data_studio import i18n
from ai_data_studio.locales import en as en_catalog
from ai_data_studio.locales import tr as tr_catalog

PACKAGE_ROOT = Path(__file__).resolve().parent.parent

# Ceviri DISINDA kalan moduller: LLM istemleri model ciktisini belirler, kullanici
# arayuz dili degistirdi diye degismemeli (bkz. i18n modul aciklamasi).
PROMPT_MODULES = {
    "prompt_blocks.py",
    "planner_prompts.py",
    "relational_prompts.py",
}


def _iter_source_files():
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path.parent.name in ("tests", "locales", "__pycache__"):
            continue
        yield path


def _collect_translation_keys() -> Dict[str, Set[str]]:
    """Kaynaktaki her `t("anahtar")` çağrısını dosyasıyla birlikte toplar."""
    found: Dict[str, Set[str]] = {}
    for path in _iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name != "t" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.setdefault(first.value, set()).add(path.name)
    return found


class TestCatalogCoverage(unittest.TestCase):
    def test_every_used_key_exists_in_english(self):
        used = _collect_translation_keys()
        missing = {key: sorted(files) for key, files in used.items()
                   if key not in en_catalog.MESSAGES}
        self.assertEqual(missing, {},
                         "İngilizce katalogda olmayan anahtarlar kullanılıyor")

    def test_turkish_catalog_covers_english(self):
        missing = sorted(set(en_catalog.MESSAGES) - set(tr_catalog.MESSAGES))
        self.assertEqual(missing, [], "Türkçe karşılığı olmayan anahtarlar")

    def test_turkish_catalog_has_no_extra_keys(self):
        """Fazla anahtar da bir kusur: silinmiş bir metnin kalıntısı demek."""
        extra = sorted(set(tr_catalog.MESSAGES) - set(en_catalog.MESSAGES))
        self.assertEqual(extra, [], "İngilizce katalogda karşılığı olmayan anahtarlar")

    def test_placeholders_match_between_languages(self):
        """`{ad}` yer tutucuları iki dilde aynı olmalı - yoksa format() patlar."""
        import re

        pattern = re.compile(r"\{(\w+)\}")
        mismatched = {}
        for key, english in en_catalog.MESSAGES.items():
            turkish = tr_catalog.MESSAGES.get(key, "")
            if set(pattern.findall(english)) != set(pattern.findall(turkish)):
                mismatched[key] = (sorted(pattern.findall(english)),
                                   sorted(pattern.findall(turkish)))
        self.assertEqual(mismatched, {}, "Yer tutucular eşleşmiyor")

    def test_keys_are_ascii_and_dotted(self):
        for key in en_catalog.MESSAGES:
            self.assertTrue(key.isascii(), "ASCII olmayan anahtar: %s" % key)
            self.assertIn(".", key, "Anahtar modul.baglam.ad biçiminde olmalı: %s" % key)


class TestPromptsAreNotTranslated(unittest.TestCase):
    """LLM istemleri çeviri dışıdır: model çıktısı arayüz diline bağlı olamaz."""

    def test_prompt_modules_do_not_call_t(self):
        offenders = []
        for path in _iter_source_files():
            if path.name not in PROMPT_MODULES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                    if name == "t":
                        offenders.append(path.name)
        self.assertEqual(offenders, [])


class TestTranslationLookup(unittest.TestCase):
    def setUp(self):
        i18n.reset_for_tests()
        self.addCleanup(i18n.reset_for_tests)

    def test_default_language_is_english(self):
        i18n.set_language("en")
        self.assertEqual(i18n.t("settings.defaults.theme"), "Theme")

    def test_turkish_lookup(self):
        i18n.set_language("tr")
        self.assertEqual(i18n.t("settings.defaults.theme"), "Tema")

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(i18n.set_language("de"), "en")
        self.assertEqual(i18n.t("settings.defaults.theme"), "Theme")

    def test_unknown_key_returns_the_key_itself(self):
        """Arayüz bir çeviri kusuru yüzünden çökmemeli."""
        i18n.set_language("tr")
        self.assertEqual(i18n.t("boyle.bir.anahtar.yok"), "boyle.bir.anahtar.yok")

    def test_formatting_arguments(self):
        i18n.set_language("en")
        text = i18n.t("settings.keys.placeholder", env_var="HF_TOKEN")
        self.assertIn("HF_TOKEN", text)

    def test_bad_formatting_returns_raw_text_instead_of_crashing(self):
        i18n.set_language("en")
        text = i18n.t("settings.keys.placeholder")     # env_var verilmedi
        self.assertIn("{env_var}", text)

    def test_available_languages(self):
        self.assertEqual(sorted(i18n.available_languages()), ["en", "tr"])

    def test_language_comes_from_settings(self):
        from unittest import mock
        from ai_data_studio import config

        with mock.patch.object(config, "load_settings",
                               return_value={"language": "tr"}):
            self.assertEqual(i18n.get_language(), "tr")


class TestSettingsIntegration(unittest.TestCase):
    def test_language_is_a_persisted_setting(self):
        from ai_data_studio import config

        self.assertIn("language", config.DEFAULT_SETTINGS)
        self.assertEqual(config.DEFAULT_SETTINGS["language"], "en")

    def test_language_survives_load_settings_filter(self):
        """load_settings DEFAULT_SETTINGS'te olmayan anahtarları süzüyor."""
        from unittest import mock
        from ai_data_studio import config

        with mock.patch.object(config, "read_json", return_value={"language": "tr"}):
            self.assertEqual(config.load_settings()["language"], "tr")


if __name__ == "__main__":
    unittest.main()
