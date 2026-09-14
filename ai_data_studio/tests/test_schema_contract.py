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

    def test_unreachable_correlation_on_rare_bool_is_lowered(self):
        """Orani %5 olan bool icin tavan ~0.47; canli 1.5b semalari 0.6-0.9 istedi."""
        data = {**SAMPLE, "correlations": [
            {"columns": ["income", "clicked"], "expected_sign": "positive", "min_r": 0.9},
            {"columns": ["age", "clicked"], "expected_sign": "negative", "min_r": 0.2},
        ]}
        sc = SchemaContract.from_dict(data)
        high, low = sc.correlations
        self.assertAlmostEqual(high.min_r, 0.37)       # floor(0.4717 * 0.8, 2)
        self.assertEqual(low.min_r, 0.2)                # ulasilabilir hedefe dokunulmaz
        self.assertEqual(len(sc.warnings), 1)
        self.assertIn("0.47", sc.warnings[0])

    def test_bool_pair_ceiling_uses_phi_bound(self):
        columns = SAMPLE["columns"] + [{"name": "vip", "type": "bool", "target_ratio": 0.5}]
        data = {**SAMPLE, "columns": columns, "correlations": [
            {"columns": ["vip", "clicked"], "expected_sign": "positive", "min_r": 0.5}]}
        sc = SchemaContract.from_dict(data)
        # sqrt(0.05 * 0.5 / (0.5 * 0.95)) = 0.229
        self.assertAlmostEqual(sc.correlations[0].min_r, 0.18)

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


class TestBusinessRuleValidation(unittest.TestCase):
    """Kurallar sozlesmede validator'la ayni dilde denetlenir; gecersizler dusurulur."""

    COLUMNS = [
        {"name": "age", "type": "int", "min": 18, "max": 80},
        {"name": "income", "type": "float", "min": 0, "max": 500000},
        {"name": "loan_amount", "type": "float", "min": 0, "max": 100000},
        {"name": "status", "type": "category", "categories": ["active", "closed"]},
        {"name": "defaulted", "type": "bool", "target_ratio": 0.1},
        {"name": "closed_at", "type": "datetime", "nullable": True},
    ]

    def _contract(self, rules):
        return SchemaContract.from_dict({"domain": "loans", "row_count_target": 100,
                                         "columns": self.COLUMNS, "business_rules": rules})

    def test_rule_copied_from_the_prompt_example_is_dropped(self):
        """1.5b, istemdeki `watch_time_s <= ad_duration_s` ornegini mobil oyun semasina kopyaladi."""
        sc = self._contract(["loan_amount <= income", "watch_time_s <= ad_duration_s"])
        self.assertEqual(sc.business_rules, ["loan_amount <= income"])
        self.assertEqual(len(sc.warnings), 1)
        self.assertIn("watch_time_s", sc.warnings[0])

    def test_non_expression_rule_is_dropped(self):
        """deepseek-r1 canli kosuda `'defaulted is boolean'` yazdi."""
        sc = self._contract(["defaulted is boolean", "age >= 18 and"])
        self.assertEqual(sc.business_rules, [])
        self.assertEqual(len(sc.warnings), 2)

    def test_rule_without_any_column_is_dropped(self):
        sc = self._contract(["1 < 2"])
        self.assertEqual(sc.business_rules, [])
        self.assertEqual(len(sc.warnings), 1)

    def test_sql_style_rule_raises_no_false_warning(self):
        """Validator bu kurali normalize edip uyguluyor; sozlesme 'tanimsiz ad' dememeli."""
        sc = self._contract(["NOT defaulted OR loan_amount <= income",
                             "status == 'closed' AND closed_at IS NOT NULL"])
        self.assertEqual(len(sc.business_rules), 2)
        self.assertEqual(sc.warnings, [])

    def test_string_literals_are_not_taken_for_column_names(self):
        sc = self._contract(["status in ['active', 'closed']", 'status != "unknown"'])
        self.assertEqual(len(sc.business_rules), 2)
        self.assertEqual(sc.warnings, [])

    def test_bool_column_compared_with_text_is_dropped(self):
        """Canli 1.5b: `churned in ['True', 'False']` validator'da verinin %100'unu sildi."""
        sc = self._contract(["defaulted in ['True', 'False']", "age == '30'",
                             "status in ['active', 'closed']", "loan_amount <= income"])
        self.assertEqual(sc.business_rules, ["status in ['active', 'closed']",
                                             "loan_amount <= income"])
        self.assertEqual(len(sc.warnings), 2)
        self.assertIn("defaulted", sc.warnings[0])

    def test_condition_pinning_a_two_class_bool_is_removed(self):
        """Canli 1.5b: `loan_default == False` pozitif sinifin tamamini siliyordu."""
        sc = self._contract([
            "defaulted == False",
            "age >= 18 and income > 0 and defaulted = 0",        # SQL '=' + and zinciri
            "not defaulted or loan_amount <= income",            # 'or' secenekli: dokunma
        ])
        self.assertEqual(sc.business_rules, ["age >= 18 and income > 0",
                                             "not defaulted or loan_amount <= income"])
        self.assertEqual(len(sc.warnings), 2)
        self.assertIn("defaulted", sc.warnings[0])

    def test_single_class_bool_may_be_pinned(self):
        columns = [dict(c) for c in self.COLUMNS]
        columns[4] = {"name": "defaulted", "type": "bool", "target_ratio": 0.0}
        sc = SchemaContract.from_dict({"domain": "loans", "row_count_target": 100,
                                       "columns": columns,
                                       "business_rules": ["defaulted == False"]})
        self.assertEqual(sc.business_rules, ["defaulted == False"])
        self.assertEqual(sc.warnings, [])

    def test_uppercase_sql_in_is_accepted(self):
        """Canli 1.5b: `return_status IN (True, False)` ifade degil diye dusuyordu."""
        sc = self._contract(["status IN ('active', 'closed')", "age NOT IN (0, 1)"])
        self.assertEqual(len(sc.business_rules), 2)
        self.assertEqual(sc.warnings, [])

    def test_bool_mean_becomes_target_ratio(self):
        """Canli 1.5b: `{"type": "bool", "mean": 0.1}` -> parametrik motor %50 uretiyordu."""
        columns = [dict(c) for c in self.COLUMNS]
        columns[4] = {"name": "defaulted", "type": "bool", "mean": 0.1}
        sc = SchemaContract.from_dict({"domain": "loans", "row_count_target": 100,
                                       "columns": columns})
        self.assertEqual(sc.column("defaulted").target_ratio, 0.1)
        self.assertIsNone(sc.column("defaulted").mean)
        self.assertEqual(len(sc.warnings), 1)

    def test_kept_rules_are_the_ones_validator_applies(self):
        import pandas as pd

        from ai_data_studio.core.validator import apply_business_rules

        sc = self._contract(["NOT defaulted OR loan_amount <= income",
                             "watch_time_s <= ad_duration_s", "defaulted is boolean"])
        df = pd.DataFrame({"age": [30, 40], "income": [100.0, 50.0],
                           "loan_amount": [50.0, 80.0], "status": ["active", "closed"],
                           "defaulted": [True, False],
                           "closed_at": [pd.NaT, pd.Timestamp("2024-01-01")]})
        _, details = apply_business_rules(df, sc.business_rules)
        self.assertEqual([d["status"] for d in details["rules"]], ["applied"])

    def test_row_count_must_be_positive(self):
        with self.assertRaises(SchemaValidationError):
            SchemaContract.from_dict({**SAMPLE, "row_count_target": 0})


class TestJsonRepair(unittest.TestCase):
    """Yerel modelin JSON kusurlari bir LLM turuna mal olmamali."""

    # qwen2.5-coder:14b'nin sema DUZELTME turunda gercekten dondurdugu satirlar
    # (canli sonda). Hata: "Expecting property name enclosed in double quotes:
    # line 132 column 26" - canli kosulardaki "column 27" ile ayni desen.
    LIVE_RETRY_EXCERPT = """{
      "domain": "bank_loans",
      "columns": [
        {
          "name": "application_date",
          "type": "datetime",
          "distribution": "uniform",
          "min": 1640995200, // Timestamp for 2022-01-01
          "max": 1704096000, // Timestamp for 2023-12-31
          "nullable": false,
        }
      ],
    }"""

    def test_live_retry_answer_with_line_comments_parses(self):
        with self.assertRaises(json.JSONDecodeError):
            json.loads(self.LIVE_RETRY_EXCERPT)
        data = extract_json_block(self.LIVE_RETRY_EXCERPT)
        self.assertEqual(data["columns"][0]["min"], 1640995200)
        self.assertFalse(data["columns"][0]["nullable"])

    def test_python_literals_and_block_comments(self):
        text = '{"a": True, /* note */ "b": None, "c": [1, 2, ], "d": False}'
        self.assertEqual(extract_json_block(text), {"a": True, "b": None, "c": [1, 2], "d": False})

    def test_strings_are_never_touched(self):
        from ai_data_studio.core.schema_contract import repair_json

        text = '{"url": "https://x.io/a#b", "rule": "a, }", "t": "True // None"}'
        self.assertEqual(json.loads(repair_json(text)),
                         {"url": "https://x.io/a#b", "rule": "a, }", "t": "True // None"})

    def test_valid_json_is_unchanged(self):
        from ai_data_studio.core.schema_contract import repair_json

        text = json.dumps(SAMPLE)
        self.assertEqual(json.loads(repair_json(text)), SAMPLE)


class TestColumnNormalization(unittest.TestCase):
    """Anlami belli kusurlar reddedilmek yerine uyariyla duzeltilir (canli 14b sondasi)."""

    def _contract(self, *columns):
        from ai_data_studio.i18n import set_language

        set_language("en")
        return SchemaContract.from_dict({**SAMPLE, "columns": list(columns),
                                         "business_rules": [], "correlations": []})

    def test_datetime_date_string_bounds_move_to_description(self):
        sc = self._contract({"name": "signup_date", "type": "datetime",
                             "min": "2022-01-01", "max": "2023-01-01",
                             "description": "Signup timestamp"})
        col = sc.columns[0]
        self.assertIsNone(col.min)
        self.assertIsNone(col.max)
        self.assertIn("between 2022-01-01 and 2023-01-01", col.description)
        self.assertEqual(len(sc.warnings), 1)
        self.assertIn("signup_date", sc.warnings[0])

    def test_invented_distribution_is_dropped_with_warning(self):
        sc = self._contract({"name": "return_rate", "type": "float", "min": 0, "max": 1,
                             "distribution": "beta"})
        self.assertIsNone(sc.columns[0].distribution)
        self.assertTrue(any("beta" in w for w in sc.warnings))

    def test_bernoulli_on_bool_is_dropped_silently(self):
        sc = self._contract({"name": "churned", "type": "bool", "target_ratio": 0.2,
                             "distribution": "bernoulli"})
        self.assertIsNone(sc.columns[0].distribution)
        self.assertEqual(sc.warnings, [])

    def test_aliases_map_to_valid_names(self):
        sc = self._contract({"name": "a", "type": "float", "distribution": "Gaussian", "mean": 1},
                            {"name": "b", "type": "float", "distribution": "log-normal"},
                            {"name": "c", "type": "int", "distribution": "zero inflated poisson"})
        self.assertEqual([c.distribution for c in sc.columns],
                         ["normal", "lognormal", "zero_inflated_poisson"])
        self.assertEqual(sc.warnings, [])

    def test_normal_without_mean_uses_bound_midpoint(self):
        sc = self._contract({"name": "age", "type": "int", "min": 18, "max": 80,
                             "distribution": "normal"})
        self.assertEqual(sc.columns[0].mean, 49.0)
        self.assertEqual(len(sc.warnings), 1)

    def test_ambiguous_problems_are_still_rejected(self):
        with self.assertRaises(SchemaValidationError):
            self._contract({"name": "age", "type": "int", "min": "young"})
        with self.assertRaises(SchemaValidationError):
            self._contract({"name": "tier", "type": "category"})

    def test_summary_follows_ui_language(self):
        from ai_data_studio.i18n import set_language, t

        sc = SchemaContract.from_dict(SAMPLE)
        set_language("en")
        self.assertIn("5 columns", sc.summary())
        set_language("tr")
        try:
            self.assertIn("5 kolon", sc.summary())
        finally:
            set_language("en")
        self.assertEqual(sc.summary(), t("schema.summary", domain=sc.domain, columns=5,
                                         rows="100,000", seed=42, rules=1, correlations=1))


if __name__ == "__main__":
    unittest.main()
