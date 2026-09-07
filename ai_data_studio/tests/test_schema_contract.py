"""Schema Contract doğrulama, model dönüşümü ve JSON ayrıştırma testleri."""
import json
import unittest

from ai_data_studio.core.schema_contract import (
    SchemaContract,
    SchemaValidationError,
    extract_json_block,
)

# Bolum 4'teki ornek sema
SAMPLE = {
    "domain": "gaming_ad_interaction",
    "row_count_target": 100000,
    "random_seed": 42,
    "columns": [
        {"name": "age", "type": "int", "min": 13, "max": 65,
         "distribution": "normal", "mean": 28, "std": 8},
        {"name": "income", "type": "float", "min": 0, "max": 500000},
        {"name": "ad_duration_s", "type": "int", "min": 5, "max": 60},
        {"name": "watch_time_s", "type": "float"},
        {"name": "clicked", "type": "bool", "target_ratio": 0.05},
    ],
    "business_rules": ["watch_time_s <= ad_duration_s"],
    "correlations": [
        {"columns": ["age", "income"], "expected_sign": "positive", "min_r": 0.15}
    ],
}


class TestExtractJsonBlock(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(extract_json_block('{"a": 1}'), {"a": 1})

    def test_wrapped_in_prose(self):
        text = 'Here is your JSON: {"a": 1, "b": [2, 3]} Hope that helps!'
        self.assertEqual(extract_json_block(text), {"a": 1, "b": [2, 3]})

    def test_markdown_fence(self):
        text = 'Sure!\n```json\n{"domain": "x", "n": 2}\n```\nDone.'
        self.assertEqual(extract_json_block(text), {"domain": "x", "n": 2})

    def test_braces_inside_string_do_not_break_balance(self):
        text = 'prefix {"note": "a } brace in text", "ok": true} suffix'
        self.assertEqual(extract_json_block(text)["ok"], True)

    def test_nested_objects(self):
        text = 'x {"a": {"b": {"c": 1}}, "d": 2} y'
        self.assertEqual(extract_json_block(text)["a"]["b"]["c"], 1)

    def test_no_json_raises(self):
        with self.assertRaises(SchemaValidationError):
            extract_json_block("Uzgunum, bu isteği yerine getiremem.")


class TestSchemaContract(unittest.TestCase):
    def test_sample_schema_parses(self):
        sc = SchemaContract.from_dict(SAMPLE)
        self.assertEqual(sc.domain, "gaming_ad_interaction")
        self.assertEqual(sc.row_count_target, 100000)
        self.assertEqual(sc.random_seed, 42)
        self.assertEqual(len(sc.columns), 5)
        self.assertEqual(sc.column("clicked").target_ratio, 0.05)
        self.assertEqual(sc.numeric_columns, ["age", "income", "ad_duration_s", "watch_time_s"])
        self.assertEqual(sc.warnings, [])

    def test_roundtrip_json(self):
        sc = SchemaContract.from_dict(SAMPLE)
        again = SchemaContract.from_json(sc.to_json())
        self.assertEqual(again.to_dict(), sc.to_dict())

    def test_from_json_tolerates_llm_prose(self):
        sc = SchemaContract.from_json("Iste şema:\n```json\n" + json.dumps(SAMPLE) + "\n```")
        self.assertEqual(sc.domain, "gaming_ad_interaction")

    # -- anlamli hatalar ------------------------------------------------- #
    def test_missing_required_field(self):
        data = dict(SAMPLE)
        data.pop("columns")
        with self.assertRaises(SchemaValidationError) as ctx:
            SchemaContract.from_dict(data)
        self.assertIn("columns", str(ctx.exception))

    def test_empty_columns(self):
        with self.assertRaises(SchemaValidationError):
            SchemaContract.from_dict({**SAMPLE, "columns": []})

    def test_unknown_column_type(self):
        bad = {**SAMPLE, "columns": [{"name": "x", "type": "blob"}]}
        with self.assertRaises(SchemaValidationError) as ctx:
            SchemaContract.from_dict(bad)
        self.assertIn("type", str(ctx.exception))

    def test_invalid_column_name(self):
        bad = {**SAMPLE, "columns": [{"name": "yaş (yil)", "type": "int"}]}
        with self.assertRaises(SchemaValidationError) as ctx:
            SchemaContract.from_dict(bad)
        from ai_data_studio.i18n import t

        self.assertEqual(str(ctx.exception),
                         t("schema.error.bad_identifier", where="columns[0]",
                           name="yaş (yil)"))

    def test_min_greater_than_max(self):
        bad = {**SAMPLE, "columns": [{"name": "age", "type": "int", "min": 90, "max": 10}]}
        with self.assertRaises(SchemaValidationError):
            SchemaContract.from_dict(bad)

    def test_duplicate_columns(self):
        bad = {**SAMPLE, "columns": [{"name": "a", "type": "int"}, {"name": "a", "type": "int"}]}
        with self.assertRaises(SchemaValidationError) as ctx:
            SchemaContract.from_dict(bad)
        from ai_data_studio.i18n import t

        # Sablonun sabit basi - kolon listesi degisken.
        self.assertIn(t("schema.error.duplicate_columns", columns="").rstrip(),
                      str(ctx.exception))

    def test_target_ratio_out_of_range(self):
        bad = {**SAMPLE, "columns": [{"name": "c", "type": "bool", "target_ratio": 1.7}]}
        with self.assertRaises(SchemaValidationError):
            SchemaContract.from_dict(bad)

    def test_correlation_on_unknown_column_is_dropped_not_fatal(self):
        """Hatali korelasyon kuralı tüm pipeline'i dusurmemeli - dusurulup uyarilir."""
        data = {**SAMPLE, "correlations": [{"columns": ["age", "yok_boyle_kolon"],
                                            "expected_sign": "positive"}]}
        sc = SchemaContract.from_dict(data)
        self.assertEqual(sc.correlations, [])
        from ai_data_studio.i18n import t

        prefix = t("schema.warning.correlation_unknown_columns",
                   columns="", known="").split("(")[0].rstrip()
        self.assertTrue(any(prefix in w for w in sc.warnings))

    def test_correlation_with_bool_column_is_valid(self):
        """bool <-> sayısal korelasyon gecerlidir (point-biserial); pandas hesaplar."""
        data = {**SAMPLE, "correlations": [{"columns": ["watch_time_s", "clicked"],
                                            "expected_sign": "positive", "min_r": 0.2}]}
        sc = SchemaContract.from_dict(data)
        self.assertEqual(len(sc.correlations), 1)
        self.assertEqual(sc.warnings, [])

    def test_correlation_on_text_column_is_dropped(self):
        data = {**SAMPLE,
                "columns": SAMPLE["columns"] + [{"name": "tier", "type": "category",
                                                 "categories": ["a", "b"]}],
                "correlations": [{"columns": ["age", "tier"], "expected_sign": "positive"}]}
        sc = SchemaContract.from_dict(data)
        self.assertEqual(sc.correlations, [])
        from ai_data_studio.i18n import t

        prefix = t("schema.warning.correlation_not_numeric",
                   columns="").split("{")[0].split(" - ")[0].rstrip()
        self.assertTrue(any(prefix in w for w in sc.warnings))

    def test_category_requires_categories(self):
        bad = {**SAMPLE, "columns": [{"name": "tier", "type": "category"}]}
        with self.assertRaises(SchemaValidationError):
            SchemaContract.from_dict(bad)

    def test_unknown_rule_identifier_is_warning_not_error(self):
        data = {**SAMPLE, "business_rules": ["purchase_amount < 1000"]}
        sc = SchemaContract.from_dict(data)
        self.assertTrue(any("purchase_amount" in w for w in sc.warnings))

    def test_row_count_must_be_positive(self):
        with self.assertRaises(SchemaValidationError):
            SchemaContract.from_dict({**SAMPLE, "row_count_target": 0})


if __name__ == "__main__":
    unittest.main()
