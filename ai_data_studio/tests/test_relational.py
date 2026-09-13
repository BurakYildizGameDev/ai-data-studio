"""Cok tablolu sandbox uretimi ve iliskisel butunluk dogrulamasi testleri."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ai_data_studio.core.dataset_contract import DatasetContract
from ai_data_studio.core.generator import (
    execute_in_sandbox,
    generate_dataset_and_execute,
)
from ai_data_studio.core.relational_validator import (
    check_cardinality,
    check_foreign_keys,
    check_primary_keys,
    repair_orphans,
    validate_relationships,
)

ID = {"type": "int", "min": 1, "max": 10 ** 9}

RELATIONAL_CODE = '''
import numpy as np
import pandas as pd

def generate_dataset(n_rows, seed):
    rng = np.random.default_rng(seed)
    customer_id = np.arange(1, n_rows + 1)
    customers = pd.DataFrame({
        "customer_id": customer_id,
        "tenure_months": rng.integers(1, 120, n_rows),
    })
    per_customer = rng.poisson(3.0, n_rows).clip(0, 50)
    oc = np.repeat(customer_id, per_customer)
    orders = pd.DataFrame({
        "order_id": np.arange(1, oc.size + 1),
        "customer_id": oc,
        "amount": rng.gamma(2.0, 60.0, oc.size).round(2),
    })
    return {"customers": customers, "orders": orders}
'''


def _contract(mean_per_parent=3.0, max_per_parent=50, nullable=False):
    return DatasetContract.from_dict({
        "domain": "saas", "root_table": "customers", "random_seed": 42,
        "tables": [
            {"name": "customers", "domain": "customers", "row_count_target": 2000,
             "primary_key": "customer_id",
             "columns": [dict(name="customer_id", **ID),
                         {"name": "tenure_months", "type": "int", "min": 0, "max": 120}]},
            {"name": "orders", "domain": "orders", "row_count_target": 6000,
             "primary_key": "order_id", "foreign_keys": ["customer_id"],
             "columns": [dict(name="order_id", **ID), dict(name="customer_id", **ID),
                         {"name": "amount", "type": "float", "min": 0, "max": 5000,
                          "distribution": "gamma"}]},
        ],
        "relationships": [
            {"parent_table": "customers", "parent_key": "customer_id",
             "child_table": "orders", "child_key": "customer_id",
             "mean_per_parent": mean_per_parent, "min_per_parent": 0,
             "max_per_parent": max_per_parent, "nullable": nullable},
        ],
    })


def _frames(n_customers=500, seed=3):
    rng = np.random.default_rng(seed)
    cid = np.arange(1, n_customers + 1)
    customers = pd.DataFrame({"customer_id": cid,
                              "tenure_months": rng.integers(1, 120, n_customers)})
    per = rng.poisson(3.0, n_customers).clip(0, 50)
    oc = np.repeat(cid, per)
    orders = pd.DataFrame({"order_id": np.arange(1, oc.size + 1),
                           "customer_id": oc,
                           "amount": rng.gamma(2.0, 60.0, oc.size)})
    return {"customers": customers, "orders": orders}


class TestMultiTableSandbox(unittest.TestCase):
    """generate_dataset -> {tablo: DataFrame} yolu."""

    @classmethod
    def setUpClass(cls):
        cls.result = execute_in_sandbox(RELATIONAL_CODE, n_rows=2000, seed=42)

    def test_execution_succeeds(self):
        self.assertTrue(self.result.success, self.result.traceback)

    def test_returns_all_tables(self):
        self.assertTrue(self.result.is_relational)
        self.assertEqual(sorted(self.result.tables), ["customers", "orders"])

    def test_root_row_count_is_requested_rows(self):
        """--rows kok tablonun sayisidir; cocuklar kardinaliteden turer."""
        self.assertEqual(len(self.result.tables["customers"]), 2000)
        self.assertGreater(len(self.result.tables["orders"]), 2000)

    def test_primary_dataframe_is_backward_compatible(self):
        self.assertIsNotNone(self.result.dataframe)
        self.assertEqual(len(self.result.dataframe), 2000)

    def test_row_counts_helper(self):
        self.assertEqual(self.result.row_counts["customers"], 2000)

    def test_foreign_keys_are_consistent(self):
        cust = self.result.tables["customers"]
        orders = self.result.tables["orders"]
        self.assertTrue(orders["customer_id"].isin(cust["customer_id"]).all())

    def test_single_table_code_still_works(self):
        code = ("import numpy as np, pandas as pd\n"
                "def generate_data(n_rows, seed):\n"
                "    rng = np.random.default_rng(seed)\n"
                "    return pd.DataFrame({'a': rng.normal(0, 1, n_rows)})\n")
        res = execute_in_sandbox(code, n_rows=800, seed=1)
        self.assertTrue(res.success, res.traceback)
        self.assertFalse(res.is_relational)
        self.assertEqual(len(res.dataframe), 800)

    def test_dict_with_non_dataframe_is_rejected(self):
        code = ("import pandas as pd\n"
                "def generate_dataset(n_rows, seed):\n"
                "    return {'a': pd.DataFrame({'x': range(n_rows)}), 'b': 42}\n")
        res = execute_in_sandbox(code, n_rows=100, seed=1)
        self.assertFalse(res.success)
        self.assertIn("DataFrame degil", res.traceback)

    def test_invalid_table_name_is_rejected(self):
        code = ("import pandas as pd\n"
                "def generate_dataset(n_rows, seed):\n"
                "    return {'2bad name': pd.DataFrame({'x': range(n_rows)})}\n")
        res = execute_in_sandbox(code, n_rows=100, seed=1)
        self.assertFalse(res.success)
        self.assertIn("Gecersiz tablo adlari", res.traceback)

    def test_empty_table_is_rejected(self):
        code = ("import pandas as pd\n"
                "def generate_dataset(n_rows, seed):\n"
                "    return {'a': pd.DataFrame({'x': range(n_rows)}),\n"
                "            'b': pd.DataFrame({'y': []})}\n")
        res = execute_in_sandbox(code, n_rows=100, seed=1)
        self.assertFalse(res.success)
        self.assertIn("bos", res.traceback.lower())


class TestPrimaryKeyChecks(unittest.TestCase):
    def test_clean_keys_pass(self):
        results = check_primary_keys(_frames(), _contract())
        self.assertTrue(all(r["pass"] for r in results))

    def test_duplicate_key_detected(self):
        tables = _frames()
        tables["customers"] = pd.concat(
            [tables["customers"], tables["customers"].head(3)], ignore_index=True)
        results = check_primary_keys(tables, _contract())
        row = next(r for r in results if r["table"] == "customers")
        self.assertEqual(row["duplicates"], 3)
        self.assertFalse(row["pass"])

    def test_null_key_detected(self):
        tables = _frames()
        tables["customers"].loc[0, "customer_id"] = None
        results = check_primary_keys(tables, _contract())
        row = next(r for r in results if r["table"] == "customers")
        self.assertGreaterEqual(row["nulls"], 1)
        self.assertFalse(row["pass"])


class TestForeignKeyChecks(unittest.TestCase):
    def test_clean_relationship_passes(self):
        results = check_foreign_keys(_frames(), _contract())
        self.assertTrue(results[0]["pass"])
        self.assertEqual(results[0]["orphan_rows"], 0)

    def test_orphans_detected(self):
        tables = _frames()
        tables["customers"] = tables["customers"].iloc[:100].reset_index(drop=True)
        results = check_foreign_keys(tables, _contract())
        self.assertFalse(results[0]["pass"])
        self.assertGreater(results[0]["orphan_rows"], 0)
        self.assertGreater(results[0]["orphan_pct"], 0)

    def test_null_fk_fails_when_not_nullable(self):
        tables = _frames()
        tables["orders"].loc[0, "customer_id"] = None
        results = check_foreign_keys(tables, _contract(nullable=False))
        self.assertFalse(results[0]["pass"])

    def test_null_fk_allowed_when_nullable(self):
        tables = _frames()
        tables["orders"].loc[0, "customer_id"] = None
        results = check_foreign_keys(tables, _contract(nullable=True))
        self.assertTrue(results[0]["pass"])


class TestCardinalityChecks(unittest.TestCase):
    def test_matching_cardinality_passes(self):
        results = check_cardinality(_frames(), _contract(mean_per_parent=3.0))
        self.assertTrue(results[0]["pass"], results[0])
        self.assertAlmostEqual(results[0]["observed_mean"], 3.0, delta=0.5)

    def test_deviation_is_flagged(self):
        results = check_cardinality(_frames(), _contract(mean_per_parent=20.0))
        self.assertFalse(results[0]["pass"])
        self.assertTrue(results[0]["violations"])

    def test_max_per_parent_violation_is_flagged(self):
        results = check_cardinality(_frames(), _contract(max_per_parent=2))
        self.assertFalse(results[0]["pass"])
        self.assertTrue(any("ust sinir" in v for v in results[0]["violations"]))


class TestOrphanRepair(unittest.TestCase):
    """Tek tablo temizligi ebeveyn silince cocuklar yetim kalir; onarim bunu toplar."""

    def test_repair_removes_orphans(self):
        tables = _frames()
        before = len(tables["orders"])
        tables["customers"] = tables["customers"].iloc[:200].reset_index(drop=True)

        repaired, detail = repair_orphans(tables, _contract())
        self.assertGreater(detail["removed_total"], 0)
        self.assertLess(len(repaired["orders"]), before)
        self.assertTrue(
            repaired["orders"]["customer_id"].isin(repaired["customers"]["customer_id"]).all())

    def test_repair_is_noop_on_clean_data(self):
        tables = _frames()
        repaired, detail = repair_orphans(tables, _contract())
        self.assertEqual(detail["removed_total"], 0)
        self.assertEqual(len(repaired["orders"]), len(tables["orders"]))

    def test_cascade_repair_follows_generation_order(self):
        """Zincirleme yetim: ebeveyn silinince torun de temizlenmeli."""
        rng = np.random.default_rng(5)
        cid = np.arange(1, 201)
        customers = pd.DataFrame({"customer_id": cid})
        oc = np.repeat(cid, 2)
        orders = pd.DataFrame({"order_id": np.arange(1, oc.size + 1), "customer_id": oc})
        io = np.repeat(orders["order_id"].to_numpy(), 2)
        items = pd.DataFrame({"item_id": np.arange(1, io.size + 1), "order_id": io,
                              "qty": rng.integers(1, 5, io.size)})

        contract = DatasetContract.from_dict({
            "domain": "shop", "root_table": "customers", "random_seed": 1,
            "tables": [
                {"name": "customers", "domain": "c", "row_count_target": 200,
                 "primary_key": "customer_id", "columns": [dict(name="customer_id", **ID)]},
                {"name": "orders", "domain": "o", "row_count_target": 400,
                 "primary_key": "order_id", "foreign_keys": ["customer_id"],
                 "columns": [dict(name="order_id", **ID), dict(name="customer_id", **ID)]},
                {"name": "order_items", "domain": "i", "row_count_target": 800,
                 "primary_key": "item_id", "foreign_keys": ["order_id"],
                 "columns": [dict(name="item_id", **ID), dict(name="order_id", **ID),
                             {"name": "qty", "type": "int", "min": 1, "max": 10}]},
            ],
            "relationships": [
                {"parent_table": "customers", "parent_key": "customer_id",
                 "child_table": "orders", "child_key": "customer_id", "mean_per_parent": 2.0},
                {"parent_table": "orders", "parent_key": "order_id",
                 "child_table": "order_items", "child_key": "order_id", "mean_per_parent": 2.0},
            ],
        })

        tables = {"customers": customers.iloc[:50].reset_index(drop=True),
                  "orders": orders, "order_items": items}
        repaired, detail = repair_orphans(tables, contract)

        self.assertEqual(len(repaired["orders"]), 100)
        self.assertEqual(len(repaired["order_items"]), 200)
        self.assertEqual(len(detail["removed_per_relationship"]), 2)


class TestValidateRelationships(unittest.TestCase):
    def test_clean_dataset_passes(self):
        _, report = validate_relationships(_frames(), _contract())
        self.assertTrue(report["pass"])
        self.assertTrue(report["relational"])
        self.assertIn("row_counts", report)

    def test_repair_enabled_by_default(self):
        tables = _frames()
        tables["customers"] = tables["customers"].iloc[:100].reset_index(drop=True)
        repaired, report = validate_relationships(tables, _contract())
        self.assertGreater(report["repair"]["removed_total"], 0)
        self.assertTrue(report["pass"], "onarim sonrasi butunluk saglanmaliydi")

    def test_repair_disabled_reports_failure(self):
        tables = _frames()
        tables["customers"] = tables["customers"].iloc[:100].reset_index(drop=True)
        _, report = validate_relationships(tables, _contract(), repair=False)
        self.assertFalse(report["pass"])
        self.assertNotIn("repair", report)

    def test_emit_receives_messages(self):
        from ai_data_studio.i18n import t

        # emit artik (mesaj, seviye) ikilisi aliyor - severity metinden degil
        # olaydan geliyor (bkz. config.PROGRESS_*).
        messages = []

        def collect(message, level="info"):
            messages.append((message, level))

        validate_relationships(_frames(), _contract(), emit=collect)
        prefix = t("relational.fk_line", relationship="", orphans="",
                   pct="", verdict="").split("[")[0].strip()
        self.assertTrue(any(prefix in m for m, _ in messages))
        card_prefix = t("relational.cardinality_line", relationship="",
                        observed="", expected="", verdict="").split("[")[0].strip()
        self.assertTrue(any(card_prefix in m for m, _ in messages))

    def test_single_table_contract_is_trivially_valid(self):
        contract = DatasetContract.from_dict({
            "domain": "t", "row_count_target": 10,
            "columns": [{"name": "a", "type": "int", "min": 0, "max": 5}]})
        tables = {"t": pd.DataFrame({"a": [1, 2, 3]})}
        _, report = validate_relationships(tables, contract)
        self.assertTrue(report["pass"])
        self.assertFalse(report["relational"])


GOOD_RELATIONAL = RELATIONAL_CODE

MISSING_TABLE_CODE = """
import numpy as np
import pandas as pd

def generate_dataset(n_rows, seed):
    rng = np.random.default_rng(seed)
    cid = np.arange(1, n_rows + 1)
    return {"customers": pd.DataFrame({
        "customer_id": cid,
        "tenure_months": rng.integers(0, 120, n_rows),
    })}
"""

SINGLE_TABLE_CODE = """
import numpy as np, pandas as pd
def generate_data(n_rows, seed):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"a": rng.normal(0, 1, n_rows)})
"""


class _StubClient:
    """generate_dataset_code / generate_code / fix_code saglayan asgari istemci."""

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.calls = []
        self.last_schema_type = None
        self.last_feedback = ""

    def _next(self):
        return self.sequence.pop(0) if self.sequence else GOOD_RELATIONAL

    def generate_dataset_code(self, contract):
        self.calls.append("generate_dataset_code")
        return self._next()

    def generate_code(self, schema):
        self.calls.append("generate_code")
        return self._next()

    def fix_code(self, previous_code, error_feedback, schema, history=None, escalate=False):
        self.calls.append("fix_code")
        self.last_feedback = error_feedback
        self.last_schema_type = type(schema).__name__
        return self._next()


class TestRelationalGenerationLoop(unittest.TestCase):
    """generate_dataset_and_execute - uretim + self-healing."""

    def test_generates_all_tables(self):
        client = _StubClient([GOOD_RELATIONAL])
        tables, _, meta = generate_dataset_and_execute(_contract(), client)
        self.assertEqual(sorted(tables), ["customers", "orders"])
        self.assertEqual(meta["attempts"], 1)
        self.assertTrue(meta["relational"])
        self.assertEqual(client.calls, ["generate_dataset_code"])

    def test_root_row_count_reported(self):
        client = _StubClient([GOOD_RELATIONAL])
        _, _, meta = generate_dataset_and_execute(_contract(), client)
        self.assertEqual(meta["row_count"], meta["row_counts"]["customers"])

    def test_missing_table_triggers_self_healing(self):
        client = _StubClient([MISSING_TABLE_CODE, GOOD_RELATIONAL])
        tables, _, meta = generate_dataset_and_execute(_contract(), client)
        self.assertEqual(meta["attempts"], 2)
        self.assertEqual(client.calls, ["generate_dataset_code", "fix_code"])
        self.assertIn("orders", client.last_feedback)
        self.assertEqual(sorted(tables), ["customers", "orders"])

    def test_fix_code_receives_dataset_contract(self):
        client = _StubClient([MISSING_TABLE_CODE, GOOD_RELATIONAL])
        generate_dataset_and_execute(_contract(), client)
        self.assertEqual(client.last_schema_type, "DatasetContract")

    def test_child_row_count_target_is_only_a_hint(self):
        """Cocuk tablo hedefin altinda kalirsa bu uyumsuzluk sayilmamali."""
        contract = _contract()
        contract.table("orders").row_count_target = 10 ** 7   # ulasilamaz hedef
        client = _StubClient([GOOD_RELATIONAL])
        tables, _, meta = generate_dataset_and_execute(contract, client)
        self.assertEqual(meta["attempts"], 1, "cocuk satir sayisi yuzunden yeniden denendi")
        self.assertLess(len(tables["orders"]), 10 ** 7)

    def test_single_table_contract_uses_single_table_path(self):
        contract = DatasetContract.from_dict({
            "domain": "t", "row_count_target": 800,
            "columns": [{"name": "a", "type": "float", "min": -10, "max": 10,
                         "distribution": "normal", "mean": 0}]})
        client = _StubClient([SINGLE_TABLE_CODE])
        tables, _, meta = generate_dataset_and_execute(contract, client)
        self.assertFalse(meta["relational"])
        self.assertEqual(client.calls, ["generate_code"])
        self.assertEqual(sorted(tables), ["t"])

    def test_legacy_generate_and_execute_still_returns_dataframe(self):
        from ai_data_studio.core.generator import generate_and_execute
        from ai_data_studio.core.schema_contract import SchemaContract

        schema = SchemaContract.from_dict({
            "domain": "t", "row_count_target": 800,
            "columns": [{"name": "a", "type": "float", "min": -10, "max": 10,
                         "distribution": "normal", "mean": 0}]})
        client = _StubClient([SINGLE_TABLE_CODE])
        df, code, meta = generate_and_execute(schema, client)
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(len(df), 800)
        self.assertTrue(code.strip())
        self.assertEqual(client.calls, ["generate_code"])


class TestRelationalPromptContract(unittest.TestCase):
    """Istem ile dogrulayici ayrisirsa canli kosu dusuyor - bunu teste bagla.

    Gercek olay: istem gecerli dagilimlari hic saymadigi icin model sinirli bir
    skor kolonu icin "beta" uydurdu, Dataset Contract dogrulamasi dustu ve
    self-healing bir tur bosa dondu.
    """

    def _rendered(self):
        from ai_data_studio.services.relational_prompts import DATASET_SCHEMA_SYSTEM_PROMPT

        return DATASET_SCHEMA_SYSTEM_PROMPT.format(min_tables=2, max_tables=6,
                                                   row_count=5000)

    def test_prompt_lists_every_valid_distribution(self):
        from ai_data_studio.core.schema_contract import VALID_DISTRIBUTIONS

        text = self._rendered()
        for name in VALID_DISTRIBUTIONS:
            self.assertIn('"%s"' % name, text,
                          "'%s' dağılımı istemde geçmiyor" % name)

    def test_prompt_pins_business_rules_to_pandas_eval(self):
        """Canli kosuda model SQL yazdi: IS NOT NULL / AND / OR kural motorunu dusurdu."""
        text = self._rendered()
        self.assertIn("df.eval", text)
        self.assertIn("NOT SQL", text)
        for sql_form in ("IS NULL", "IS NOT NULL"):
            self.assertIn(sql_form, text, "'%s' acikca yasaklanmali" % sql_form)

    def test_prompt_pins_min_max_to_numeric_columns(self):
        """Canli kosuda model datetime kolonuna min: '2020-01-01' yazip sozlesmeyi dusurdu."""
        text = self._rendered()
        self.assertIn("NUMBERS", text)
        self.assertIn("datetime", text)
        self.assertIn("date string", text)

    def test_prompt_rejects_inventing_distributions(self):
        text = self._rendered()
        self.assertIn("do not invent one", text)
        self.assertIn('"beta"', text)

    def test_prompt_has_no_unresolved_placeholders(self):
        """Sablon degiskenleri render sonrasi metinde kalmamali.

        JSON ornegindeki suslu parantezler bilerek durur ({{ }} olarak kacirilmis);
        aranan sey yalnizca doldurulmamis {isim} yer tutuculari.
        """
        import re

        leftovers = re.findall(r"\{[a-z_]+\}", self._rendered())
        self.assertEqual(leftovers, [])


class TestCodePromptParity(unittest.TestCase):
    """Tek tablolu ve iliskisel kod istemleri ayni seyleri ogretmeli.

    Canli kosuda olculen uc kusurun ucu de su kaliptaydi: iliskisel istem, tek tablolu
    istemin soyledigi bir kisiti tekrarlamiyordu. Ortak bloklar artik tek yerde duruyor
    (`services/prompt_blocks.py`); bu test ikisinin de gercekten kullandigini dogrular,
    yoksa bir sonraki kopyala-yapistir ayni sinif hatayi geri getirir.
    """

    def _rendered(self):
        from ai_data_studio import config
        from ai_data_studio.services.llm_base import CODE_SYSTEM_PROMPT
        from ai_data_studio.services.relational_prompts import DATASET_CODE_SYSTEM_PROMPT

        fields = dict(
            allowed_imports=", ".join(sorted(config.ALLOWED_IMPORTS)),
            timeout=config.SANDBOX_TIMEOUT_S,
            memory_mb=config.SANDBOX_MEMORY_LIMIT_MB,
        )
        return (CODE_SYSTEM_PROMPT.format(locale="en_US", **fields),
                DATASET_CODE_SYSTEM_PROMPT.format(locale="en_US", **fields))

    def test_shared_blocks_appear_in_both_prompts(self):
        from ai_data_studio.services import prompt_blocks

        single, relational = self._rendered()
        shared = ("COPULA_BLOCK", "MONOTONICITY_BLOCK", "HEAVY_TAIL_BLOCK",
                  "DATETIME_BLOCK", "FAKER_BLOCK")
        for name in shared:
            # Blogun ilk satiri (baslik) her iki istemde de bulunmali.
            title = getattr(prompt_blocks, name).split("\n")[0]
            title = title.format(locale="en_US") if "{" in title else title
            self.assertIn(title, single, "%s tek tablolu istemde yok" % name)
            self.assertIn(title, relational, "%s ilişkisel istemde yok" % name)

    def test_lognormal_log_scale_conversion_in_both(self):
        """Sozlesmedeki mean/std gercek olcekli; numpy log olcekli bekler (canli Job #38)."""
        single, relational = self._rendered()
        for prompt in (single, relational):
            self.assertIn("rng.lognormal(mu, sigma, n_rows)", prompt)
            self.assertIn("never `scale`", prompt)

    def test_faker_template_apis_are_banned_in_both(self):
        """'Unknown formatter' hatasinin kaynagi; ikisinde de yasakli olmali."""
        single, relational = self._rendered()
        for prompt in (single, relational):
            for api in ("pystr_format", "bothify", "lexify", "numerify"):
                self.assertIn(api, prompt)

    def test_datetime_guidance_matches_schema_contract(self):
        """Sema istemi datetime araligini description'a yaziyor - kod istemi oradan okumali."""
        single, relational = self._rendered()
        for prompt in (single, relational):
            self.assertIn("DATETIME COLUMNS", prompt)
            self.assertIn("description", prompt)

    def test_numbered_helper_aligns_continuation_lines(self):
        from ai_data_studio.services.prompt_blocks import numbered

        self.assertEqual(numbered(9, "TITLE:\nbody"), "9. TITLE:\n   body")
        self.assertEqual(numbered(12, "TITLE:\nbody"), "12. TITLE:\n    body")

    def test_locale_placeholder_survives_composition(self):
        """FAKER_BLOCK ucgen tirnak disinda birlestiriliyor - {locale} bozulmamali."""
        single, relational = self._rendered()
        for prompt in (single, relational):
            self.assertIn('Faker("en_US")', prompt)
            self.assertNotIn("{locale}", prompt)


class TestSchemaPromptParity(unittest.TestCase):
    """Iki sema istemi de sozlesme nesnelerinin SEKLINI gostermeli.

    Canli kosuda iliskisel istem korelasyon nesnesini "[...]" diye gecistiriyordu;
    model sekli tahmin etti, 'columns' tek elemanli geldi ve ayni hata uc denemede
    de tekrarlandi. Sekil artik ortak sabitten geliyor.
    """

    def _rendered(self):
        from ai_data_studio.services.llm_base import SCHEMA_SYSTEM_PROMPT
        from ai_data_studio.services.relational_prompts import DATASET_SCHEMA_SYSTEM_PROMPT

        return (SCHEMA_SYSTEM_PROMPT,
                DATASET_SCHEMA_SYSTEM_PROMPT.format(min_tables=2, max_tables=6,
                                                    row_count=5000))

    def test_both_show_the_correlation_object_shape(self):
        for prompt in self._rendered():
            self.assertIn('"expected_sign"', prompt)
            self.assertIn('"min_r"', prompt)
            self.assertIn('"columns": ["<col_a>", "<col_b>"]', prompt)

    def test_both_state_the_two_column_rule(self):
        for prompt in self._rendered():
            self.assertIn("EXACTLY TWO", prompt)

    def test_relational_prompt_has_no_leftover_placeholders(self):
        """Sekiller metne .replace ile gomuluyor - yer tutucu kalmamali."""
        from ai_data_studio.services.relational_prompts import DATASET_SCHEMA_SYSTEM_PROMPT

        for token in ("CORR_SHAPE", "MONO_SHAPE", "CONTRACT_RULES"):
            self.assertNotIn(token, DATASET_SCHEMA_SYSTEM_PROMPT)

    def test_relational_prompt_still_formats(self):
        """Gomulen JSON ornegi kacirilmazsa .format() patlar."""
        from ai_data_studio.services.relational_prompts import DATASET_SCHEMA_SYSTEM_PROMPT

        rendered = DATASET_SCHEMA_SYSTEM_PROMPT.format(min_tables=3, max_tables=5,
                                                       row_count=1234)
        self.assertIn("Between 3 and 5 tables", rendered)
        self.assertIn("exactly 1234", rendered)


class TestDatasetShapeParity(unittest.TestCase):
    """Sozlesme sekli kisaltilmamali - kisaltilan alan modelin tahmin ettigi alandir.

    Canli kosuda planlayici istemi veri seti seklini "<a full Dataset Contract>" diye
    gecistiriyordu; yerel model her tablodaki zorunlu `domain` alanini atladi ve plan
    uc denemede de reddedildi. Sekil artik ortak sabitten geliyor.
    """

    def _prompts(self):
        from ai_data_studio.services.planner_prompts import PROJECT_PLAN_SYSTEM_PROMPT
        from ai_data_studio.services.relational_prompts import DATASET_SCHEMA_SYSTEM_PROMPT

        return {
            "iliskisel sema": DATASET_SCHEMA_SYSTEM_PROMPT.format(
                min_tables=2, max_tables=6, row_count=5000),
            "proje plani": PROJECT_PLAN_SYSTEM_PROMPT,
        }

    def test_every_required_contract_field_is_shown(self):
        required = ('"domain"', '"root_table"', '"tables"', '"name"',
                    '"row_count_target"', '"primary_key"', '"foreign_keys"',
                    '"columns"', '"relationships"', '"mean_per_parent"')
        for label, prompt in self._prompts().items():
            for field in required:
                self.assertIn(field, prompt, "%s isteminde %s yok" % (label, field))

    def test_column_object_fields_are_shown(self):
        for label, prompt in self._prompts().items():
            for field in ('"type"', '"min"', '"max"', '"distribution"',
                          '"target_ratio"', '"categories"', '"nullable"'):
                self.assertIn(field, prompt, "%s isteminde %s yok" % (label, field))

    def test_shape_is_the_shared_constant(self):
        from ai_data_studio.services.prompt_blocks import DATASET_SHAPE

        # Sekildeki ayirt edici bir satir her iki istemde de birebir gecmeli.
        marker = '"row_count_target": <int>,'
        self.assertIn(marker, DATASET_SHAPE)
        for label, prompt in self._prompts().items():
            self.assertIn(marker, prompt, "%s paylasilan sekli kullanmiyor" % label)

    def test_no_placeholder_tokens_leak_into_the_prompts(self):
        for label, prompt in self._prompts().items():
            for token in ("DATASET_SHAPE", "COLUMN_SHAPE", "CORR_SHAPE",
                          "MONO_SHAPE", "CONTRACT_RULES", "TASK_TYPES", "SPLIT_KINDS"):
                self.assertNotIn(token, prompt,
                                 "%s isteminde '%s' yer tutucusu kalmis" % (label, token))


if __name__ == "__main__":
    unittest.main()
