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
from ai_data_studio.locales import de as de_catalog
from ai_data_studio.locales import en as en_catalog
from ai_data_studio.locales import fr as fr_catalog
from ai_data_studio.locales import ja as ja_catalog
from ai_data_studio.locales import ru as ru_catalog
from ai_data_studio.locales import tr as tr_catalog
from ai_data_studio.locales import zh as zh_catalog

OTHER_CATALOGS = {
    "tr": tr_catalog,
    "de": de_catalog,
    "fr": fr_catalog,
    "ru": ru_catalog,
    "zh": zh_catalog,
    "ja": ja_catalog,
}

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

    def test_all_catalogs_cover_english(self):
        for lang_code, cat in OTHER_CATALOGS.items():
            missing = sorted(set(en_catalog.MESSAGES) - set(cat.MESSAGES))
            self.assertEqual(missing, [], f"{lang_code} katalogunda karşılığı olmayan anahtarlar")

    def test_all_catalogs_have_no_extra_keys(self):
        """Fazla anahtar da bir kusur: silinmiş bir metnin kalıntısı demek."""
        for lang_code, cat in OTHER_CATALOGS.items():
            extra = sorted(set(cat.MESSAGES) - set(en_catalog.MESSAGES))
            self.assertEqual(extra, [], f"{lang_code} katalogunda İngilizce karşılığı olmayan anahtarlar")

    def test_placeholders_match_between_languages(self):
        """`{ad}` yer tutucuları bütün dillerde aynı olmalı - yoksa format() patlar."""
        import re

        pattern = re.compile(r"\{(\w+)\}")
        for lang_code, cat in OTHER_CATALOGS.items():
            mismatched = {}
            for key, english in en_catalog.MESSAGES.items():
                target_text = cat.MESSAGES.get(key, "")
                if set(pattern.findall(english)) != set(pattern.findall(target_text)):
                    mismatched[key] = (sorted(pattern.findall(english)),
                                       sorted(pattern.findall(target_text)))
            self.assertEqual(mismatched, {}, f"{lang_code} yer tutucuları eşleşmiyor")

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
        self.assertEqual(i18n.set_language("xx"), "en")
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
        self.assertEqual(
            sorted(i18n.available_languages()),
            ["de", "en", "fr", "ja", "ru", "tr", "zh"],
        )

    def test_language_override_is_scoped_and_thread_local(self):
        """GUI işçi iş parçacığında İngilizce üretirken arayüz Türkçe kalmalı."""
        import threading

        i18n.set_language("tr")
        seen = {}
        inside = threading.Event()
        release = threading.Event()

        def worker():
            with i18n.language_override("en"):
                seen["worker"] = i18n.t("settings.defaults.theme")
                inside.set()
                release.wait(5)

        thread = threading.Thread(target=worker)
        thread.start()
        inside.wait(5)
        seen["ui_during"] = i18n.t("settings.defaults.theme")
        release.set()
        thread.join(5)

        self.assertEqual(seen, {"worker": "Theme", "ui_during": "Tema"})
        self.assertEqual(i18n.t("settings.defaults.theme"), "Tema")
        with i18n.language_override("en"):
            with i18n.language_override("de"):
                pass
            self.assertEqual(i18n.get_language(), "en")     # iç içe blok önceki dile döner
        self.assertEqual(i18n.get_language(), "tr")

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
