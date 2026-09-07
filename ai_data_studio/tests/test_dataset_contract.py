"""Iliskisel (cok tablolu) veri sozlesmesi testleri."""
from __future__ import annotations

import unittest

from ai_data_studio.core.dataset_contract import DatasetContract, Relationship
from ai_data_studio.core.schema_contract import SchemaContract, SchemaValidationError


def _table(name, columns, pk=None, fks=None, rows=1000):
    return {
        "name": name,
        "domain": name,
        "row_count_target": rows,
        "primary_key": pk,
        "foreign_keys": fks or [],
        "columns": columns,
    }


ID = {"type": "int", "min": 1, "max": 10 ** 9}

DATASET = {
    "domain": "saas_churn",
    "root_table": "customers",
    "random_seed": 42,
    "tables": [
        _table("customers", [dict(name="customer_id", **ID),
                             {"name": "tenure_months", "type": "int", "min": 0, "max": 120}],
               pk="customer_id", rows=5000),
        _table("orders", [dict(name="order_id", **ID),
                          dict(name="customer_id", **ID),
                          {"name": "amount", "type": "float", "min": 0, "max": 5000,
                           "distribution": "gamma"}],
               pk="order_id", fks=["customer_id"], rows=15000),
        _table("order_items", [dict(name="item_id", **ID),
                               dict(name="order_id", **ID),
                               {"name": "qty", "type": "int", "min": 1, "max": 20,
                                "distribution": "poisson"}],
               pk="item_id", fks=["order_id"], rows=40000),
    ],
    "relationships": [
        {"parent_table": "customers", "parent_key": "customer_id",
         "child_table": "orders", "child_key": "customer_id",
         "mean_per_parent": 3.0, "min_per_parent": 0, "max_per_parent": 50},
        {"parent_table": "orders", "parent_key": "order_id",
         "child_table": "order_items", "child_key": "order_id",
         "mean_per_parent": 2.6, "min_per_parent": 1},
    ],
}


class TestRelationship(unittest.TestCase):
    def test_parses_and_round_trips(self):
        rel = Relationship.from_dict(DATASET["relationships"][0], 0)
        self.assertEqual(rel.parent_table, "customers")
        self.assertEqual(rel.max_per_parent, 50)
        again = Relationship.from_dict(rel.to_dict(), 0)
        self.assertEqual(again.to_dict(), rel.to_dict())

    def test_label(self):
        rel = Relationship.from_dict(DATASET["relationships"][0], 0)
        self.assertEqual(rel.label(), "customers.customer_id -> orders.customer_id")

    def test_rejects_missing_fields(self):
        for missing in ("parent_table", "parent_key", "child_table", "child_key"):
            payload = dict(DATASET["relationships"][0])
            payload.pop(missing)
            with self.assertRaises(SchemaValidationError):
                Relationship.from_dict(payload, 0)

    def test_rejects_bad_cardinality(self):
        base = DATASET["relationships"][0]
        for bad in ({"mean_per_parent": 0}, {"mean_per_parent": -1},
                    {"min_per_parent": -3}, {"min_per_parent": 5, "max_per_parent": 2}):
            with self.assertRaises(SchemaValidationError):
                Relationship.from_dict({**base, **bad}, 0)


class TestDatasetContract(unittest.TestCase):
    def setUp(self):
        self.dc = DatasetContract.from_dict(DATASET)

    def test_tables_and_root(self):
        self.assertEqual(self.dc.table_names, ["customers", "orders", "order_items"])
        self.assertEqual(self.dc.root_table, "customers")
        self.assertTrue(self.dc.is_relational)

    def test_generation_order_puts_parents_first(self):
        order = self.dc.generation_order()
        self.assertEqual(order, ["customers", "orders", "order_items"])
        for rel in self.dc.relationships:
            self.assertLess(order.index(rel.parent_table), order.index(rel.child_table))

    def test_parent_and_child_lookup(self):
        self.assertEqual([r.child_table for r in self.dc.children_of("customers")], ["orders"])
        self.assertEqual([r.parent_table for r in self.dc.parents_of("order_items")], ["orders"])
        self.assertEqual(self.dc.parents_of("customers"), [])

    def test_table_lookup(self):
        self.assertIsInstance(self.dc.table("orders"), SchemaContract)
        with self.assertRaises(KeyError):
            self.dc.table("yok")

    def test_round_trip(self):
        again = DatasetContract.from_dict(self.dc.to_dict())
        self.assertEqual(again.table_names, self.dc.table_names)
        self.assertEqual(again.generation_order(), self.dc.generation_order())
        self.assertEqual(len(again.relationships), len(self.dc.relationships))

    def test_json_round_trip(self):
        again = DatasetContract.from_json(self.dc.to_json())
        self.assertEqual(again.table_names, self.dc.table_names)

    def test_root_inferred_when_absent(self):
        payload = {k: v for k, v in DATASET.items() if k != "root_table"}
        self.assertEqual(DatasetContract.from_dict(payload).root_table, "customers")


class TestSingleTableCompatibility(unittest.TestCase):
    """Tek tablolu sozlesme, iliskisel modelin N=1 ozel durumu olmali."""

    SINGLE = {"domain": "orders", "row_count_target": 100,
              "columns": [{"name": "a", "type": "int", "min": 0, "max": 5}]}

    def test_plain_schema_dict_is_accepted(self):
        dc = DatasetContract.from_dict(self.SINGLE)
        self.assertEqual(dc.table_names, ["orders"])
        self.assertEqual(dc.root_table, "orders")
        self.assertFalse(dc.is_relational)
        self.assertEqual(dc.generation_order(), ["orders"])

    def test_from_schema_wraps(self):
        schema = SchemaContract.from_dict(self.SINGLE)
        dc = DatasetContract.from_schema(schema)
        self.assertEqual(dc.tables[0], schema)
        self.assertEqual(dc.relationships, [])

    def test_table_name_falls_back_to_domain(self):
        schema = SchemaContract.from_dict(self.SINGLE)
        self.assertEqual(schema.name, "")
        self.assertEqual(schema.table_name, "orders")


class TestDatasetValidation(unittest.TestCase):
    def test_rejects_cycle(self):
        payload = {**DATASET, "relationships": [
            {"parent_table": "customers", "parent_key": "customer_id",
             "child_table": "orders", "child_key": "customer_id"},
            {"parent_table": "orders", "parent_key": "order_id",
             "child_table": "customers", "child_key": "customer_id"},
        ]}
        with self.assertRaises(SchemaValidationError) as ctx:
            DatasetContract.from_dict(payload)
        from ai_data_studio.i18n import t

        self.assertIn(t("contract.error.cycle", tables="").split("{")[0].rstrip(":"),
                      str(ctx.exception))

    def test_rejects_unknown_table(self):
        payload = {**DATASET, "relationships": [
            {"parent_table": "yok", "parent_key": "a",
             "child_table": "orders", "child_key": "customer_id"}]}
        with self.assertRaises(SchemaValidationError):
            DatasetContract.from_dict(payload)

    def test_rejects_unknown_column(self):
        payload = {**DATASET, "relationships": [
            {"parent_table": "customers", "parent_key": "yok_kolon",
             "child_table": "orders", "child_key": "customer_id"}]}
        with self.assertRaises(SchemaValidationError):
            DatasetContract.from_dict(payload)

    def test_rejects_self_reference(self):
        payload = {**DATASET, "relationships": [
            {"parent_table": "orders", "parent_key": "order_id",
             "child_table": "orders", "child_key": "customer_id"}]}
        with self.assertRaises(SchemaValidationError):
            DatasetContract.from_dict(payload)

    def test_rejects_duplicate_table_names(self):
        payload = {**DATASET, "tables": DATASET["tables"] + [DATASET["tables"][0]],
                   "relationships": []}
        with self.assertRaises(SchemaValidationError):
            DatasetContract.from_dict(payload)

    def test_rejects_empty_tables(self):
        with self.assertRaises(SchemaValidationError):
            DatasetContract.from_dict({"domain": "x", "tables": []})

    def test_rejects_unknown_root(self):
        with self.assertRaises(SchemaValidationError):
            DatasetContract.from_dict({**DATASET, "root_table": "yok"})

    def test_rejects_too_many_tables(self):
        many = [_table("t%d" % i, [dict(name="a", **ID)]) for i in range(20)]
        with self.assertRaises(SchemaValidationError):
            DatasetContract.from_dict({"domain": "x", "tables": many, "relationships": []})


class TestSchemaContractKeys(unittest.TestCase):
    def test_primary_key_must_exist(self):
        with self.assertRaises(SchemaValidationError):
            SchemaContract.from_dict(_table("t", [dict(name="a", **ID)], pk="yok"))

    def test_foreign_key_must_exist(self):
        with self.assertRaises(SchemaValidationError):
            SchemaContract.from_dict(_table("t", [dict(name="a", **ID)], fks=["yok"]))

    def test_keys_survive_round_trip(self):
        schema = SchemaContract.from_dict(
            _table("orders", [dict(name="order_id", **ID), dict(name="customer_id", **ID)],
                   pk="order_id", fks=["customer_id"]))
        again = SchemaContract.from_dict(schema.to_dict())
        self.assertEqual(again.name, "orders")
        self.assertEqual(again.primary_key, "order_id")
        self.assertEqual(again.foreign_keys, ["customer_id"])


if __name__ == "__main__":
    unittest.main()
