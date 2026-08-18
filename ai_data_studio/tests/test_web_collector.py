# -*- coding: utf-8 -*-
"""Web Collector & Extractor birim testleri."""
import unittest
from unittest import mock

import pandas as pd

from ai_data_studio.services import web_collector
from ai_data_studio.tests.fake_llm import FakeLLMClient


class TestWebCollectorHelpers(unittest.TestCase):
    def test_is_url(self):
        self.assertTrue(web_collector.is_url("http://example.com"))
        self.assertTrue(web_collector.is_url("https://sub.domain.org/path?a=1"))
        self.assertFalse(web_collector.is_url("arabalar ve fiyatlar"))
        self.assertFalse(web_collector.is_url("ftp://example.com"))
        self.assertFalse(web_collector.is_url(""))

    def test_clean_html_removes_scripts_and_tags(self):
        sample_html = """
        <html>
        <head>
            <script>var x = 10;</script>
            <style>body { color: red; }</style>
        </head>
        <body>
            <header>Site Header</header>
            <nav>Navigation links here</nav>
            <h1>Otomobil Fiyat Listesi 2026</h1>
            <p>Model X için başlangıç fiyatı 1.250.000 TL olarak belirlendi.</p>
            <p>Model Y hibrit versiyonu ise 1.850.000 TL seviyesinde satışa sunuldu.</p>
            <footer>Copyright 2026</footer>
        </body>
        </html>
        """
        cleaned = web_collector.clean_html(sample_html)
        self.assertNotIn("<script>", cleaned)
        self.assertNotIn("var x", cleaned)
        self.assertNotIn("<style>", cleaned)
        self.assertNotIn("Site Header", cleaned)
        self.assertIn("Otomobil Fiyat Listesi", cleaned)
        self.assertIn("Model X", cleaned)

    def test_clean_html_unescapes_entities(self):
        text = "Fiyat &amp; Performans &gt; 100"
        cleaned = web_collector.clean_html(text)
        self.assertIn("&", cleaned)
        self.assertIn(">", cleaned)


class TestWebDataExtraction(unittest.TestCase):
    def test_extract_seed_dataframe_success(self):
        fake_llm = FakeLLMClient()
        fake_json = (
            '[\n'
            '  {"car_model": "Model A", "price_try": 1200000, "is_electric": true},\n'
            '  {"car_model": "Model B", "price_try": 1500000, "is_electric": false}\n'
            ']'
        )
        fake_llm.complete = mock.MagicMock(return_value=fake_json)

        web_text = "Örnek web içeriği otomobil fiyatları..."
        df = web_collector.extract_seed_dataframe(web_text, "otomobil", fake_llm)

        self.assertIsNotNone(df)
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(len(df), 2)
        self.assertIn("car_model", df.columns)
        self.assertIn("price_try", df.columns)
        self.assertEqual(df["price_try"].iloc[0], 1200000)

    def test_extract_seed_dataframe_handles_invalid_json(self):
        fake_llm = FakeLLMClient()
        fake_llm.complete = mock.MagicMock(return_value="Maalesef veri bulunamadı.")
        df = web_collector.extract_seed_dataframe("metin", "domain", fake_llm)
        self.assertNil = self.assertIsNone(df)

    def test_collect_web_seed_url_flow(self):
        with mock.patch("ai_data_studio.services.web_collector.fetch_url_content",
                        return_value="Telefon fiyatları: Model X 25000 TL, Model Y 35000 TL"):
            fake_llm = FakeLLMClient()
            fake_llm.complete = mock.MagicMock(return_value='[{"model": "X", "price": 25000}]')

            df, source = web_collector.collect_web_seed("https://example.com/phones", "telefon", fake_llm)
            self.assertIsNotNone(df)
            self.assertEqual(len(df), 1)
            self.assertIn("https://example.com/phones", source)


if __name__ == "__main__":
    unittest.main()
