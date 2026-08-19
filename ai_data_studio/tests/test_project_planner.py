"""Proje planlayici testleri - planin IC TUTARLILIGI.

Planin kendisi bir yargidir; karsilastirilacak bir dogru cevap yoktur. Test edilebilen
sey tutarliliktir: hedef degisken sozlesmede var mi, sizintili ilan edilen kolon
gercekten disarida mi, sinif dengesi verilmis ve semayla ayni seyi mi soyluyor,
bolme stratejisinin dayandigi kolon dogru turde mi.
"""
from __future__ import annotations

import copy
import json
import unittest

from ai_data_studio.core.project_planner import ProjectPlan, SplitStrategy
from ai_data_studio.core.schema_contract import SchemaValidationError

ID = {"type": "int", "min": 1, "max": 10 ** 9}

PLAN = {
    "rationale": "Churn tahmini icin musteri ve siparis gecmisi gerekir.",
    "task_type": "binary_classification",
    "target": {"table": "customers", "column": "churned"},
    "positive_class_ratio": 0.18,
    "excluded_leakage": [
        {"column": "cancellation_reason",
         "reason": "yalnizca churn gerceklestikten sonra bilinir"},
    ],
    "split": {"kind": "temporal", "column": "signup_at", "table": "customers",
              "reason": "gelecegi tahmin ediyoruz, rastgele bolme sizdirir"},
    "dataset": {
        "domain": "saas_churn",
        "root_table": "customers",
        "random_seed": 42,
        "tables": [
            {
                "name": "customers", "domain": "customers", "row_count_target": 5000,
                "primary_key": "customer_id",
                "columns": [
                    dict(name="customer_id", **ID),
                    {"name": "signup_at", "type": "datetime",
                     "description": "kayit tarihi, 2020-01-01 ile 2024-12-31 arasi"},
                    {"name": "tenure_months", "type": "int", "min": 0, "max": 120},
                    {"name": "churned", "type": "bool"},
                ],
            },
            {
                "name": "orders", "domain": "orders", "row_count_target": 15000,
                "primary_key": "order_id", "foreign_keys": ["customer_id"],
                "columns": [
                    dict(name="order_id", **ID),
                    dict(name="customer_id", **ID),
                    {"name": "amount", "type": "float", "min": 0, "max": 5000,
                     "distribution": "gamma"},
                ],
            },
        ],
        "relationships": [
            {"parent_table": "customers", "parent_key": "customer_id",
             "child_table": "orders", "child_key": "customer_id",
             "mean_per_parent": 3.0},
        ],
    },
}


def plan_dict(**overrides):
    """PLAN'in derin kopyasi; ust duzey anahtarlar override edilebilir."""
    data = copy.deepcopy(PLAN)
    for key, value in overrides.items():
        if value is _REMOVE:
            data.pop(key, None)
        else:
            data[key] = value
    return data


class _Remove:
    pass


_REMOVE = _Remove()


class TestValidPlan(unittest.TestCase):
    def test_parses(self):
        plan = ProjectPlan.from_dict(plan_dict(), project="churn projesi")
        self.assertEqual(plan.task_type, "binary_classification")
        self.assertEqual(plan.target.label(), "customers.churned")
        self.assertEqual(plan.contract.table_names, ["customers", "orders"])
        self.assertEqual(plan.project, "churn projesi")
        self.assertTrue(plan.is_supervised)

    def test_summary_mentions_the_decisions(self):
        summary = ProjectPlan.from_dict(plan_dict()).summary()
        self.assertIn("binary_classification", summary)
        self.assertIn("customers.churned", summary)
        self.assertIn("2 tablo", summary)

    def test_no_warnings_on_a_complete_plan(self):
        self.assertEqual(ProjectPlan.from_dict(plan_dict()).warnings, [])

    def test_round_trips_through_json(self):
        plan = ProjectPlan.from_dict(plan_dict())
        again = ProjectPlan.from_dict(json.loads(plan.to_json()))
        self.assertEqual(again.target.label(), plan.target.label())
        self.assertEqual(again.positive_class_ratio, plan.positive_class_ratio)
        self.assertEqual(again.contract.table_names, plan.contract.table_names)
        self.assertEqual([e.column for e in again.excluded_leakage],
                         [e.column for e in plan.excluded_leakage])

    def test_single_table_plan_is_valid(self):
        data = plan_dict()
        data["dataset"]["tables"] = [data["dataset"]["tables"][0]]
        data["dataset"].pop("relationships")
        data["split"]["table"] = "customers"
        plan = ProjectPlan.from_dict(data)
        self.assertFalse(plan.contract.is_relational)
        self.assertEqual(plan.contract.root_table, "customers")


class TestTargetVariable(unittest.TestCase):
    """Hedef degiskeni olmayan bir veri seti egitime hazir degildir."""

    def test_supervised_plan_requires_target(self):
        with self.assertRaises(SchemaValidationError) as ctx:
            ProjectPlan.from_dict(plan_dict(target=_REMOVE))
        self.assertIn("target", str(ctx.exception))

    def test_target_column_must_exist_in_contract(self):
        data = plan_dict(target={"table": "customers", "column": "will_churn"})
        with self.assertRaises(SchemaValidationError) as ctx:
            ProjectPlan.from_dict(data)
        self.assertIn("will_churn", str(ctx.exception))

    def test_target_table_must_exist(self):
        data = plan_dict(target={"table": "accounts", "column": "churned"})
        with self.assertRaises(SchemaValidationError) as ctx:
            ProjectPlan.from_dict(data)
        self.assertIn("accounts", str(ctx.exception))

    def test_unsupervised_plan_drops_target_with_a_warning(self):
        data = plan_dict(task_type="unsupervised", positive_class_ratio=_REMOVE)
        plan = ProjectPlan.from_dict(data)
        self.assertIsNone(plan.target)
        self.assertTrue(any("unsupervised" in w for w in plan.warnings))


class TestLeakage(unittest.TestCase):
    """Ayiklandigi soylenen kolon sozlesmede duruyorsa plan kendiyle celisir."""

    def test_excluded_column_must_not_be_in_the_contract(self):
        data = plan_dict(excluded_leakage=[
            {"column": "tenure_months", "reason": "uydurma gerekce"},
        ])
        with self.assertRaises(SchemaValidationError) as ctx:
            ProjectPlan.from_dict(data)
        self.assertIn("tenure_months", str(ctx.exception))

    def test_excluded_column_in_a_child_table_is_also_caught(self):
        data = plan_dict(excluded_leakage=[
            {"column": "amount", "reason": "siparis tablosunda duruyor"},
        ])
        with self.assertRaises(SchemaValidationError):
            ProjectPlan.from_dict(data)

    def test_target_cannot_be_declared_as_leakage(self):
        data = plan_dict()
        data["dataset"]["tables"][0]["columns"] = [
            c for c in data["dataset"]["tables"][0]["columns"] if c["name"] != "churned"
        ]
        data["excluded_leakage"] = [{"column": "churned", "reason": "hedefin kendisi"}]
        with self.assertRaises(SchemaValidationError):
            ProjectPlan.from_dict(data)

    def test_field_is_mandatory(self):
        """Alan hic yoksa plan sizintiyi dusunmemis demektir - reddedilir."""
        with self.assertRaises(SchemaValidationError) as ctx:
            ProjectPlan.from_dict(plan_dict(excluded_leakage=_REMOVE))
        self.assertIn("excluded_leakage", str(ctx.exception))

    def test_empty_list_is_allowed_but_warns(self):
        plan = ProjectPlan.from_dict(plan_dict(excluded_leakage=[]))
        self.assertTrue(any("sizinti" in w.lower() for w in plan.warnings))

    def test_exclusion_needs_a_reason(self):
        with self.assertRaises(SchemaValidationError):
            ProjectPlan.from_dict(plan_dict(excluded_leakage=[{"column": "refund_at"}]))


class TestClassBalance(unittest.TestCase):
    def test_classification_requires_a_ratio(self):
        with self.assertRaises(SchemaValidationError) as ctx:
            ProjectPlan.from_dict(plan_dict(positive_class_ratio=_REMOVE))
        self.assertIn("positive_class_ratio", str(ctx.exception))

    def test_ratio_must_be_between_zero_and_one(self):
        for bad in (0.0, 1.0, 1.5, -0.2):
            with self.assertRaises(SchemaValidationError):
                ProjectPlan.from_dict(plan_dict(positive_class_ratio=bad))

    def test_extreme_ratio_warns(self):
        plan = ProjectPlan.from_dict(plan_dict(positive_class_ratio=0.0001))
        self.assertTrue(any("asiri" in w.lower() or "aşırı" in w.lower()
                            for w in plan.warnings))

    def test_regression_ignores_ratio_with_a_warning(self):
        data = plan_dict(task_type="regression",
                         target={"table": "customers", "column": "tenure_months"})
        plan = ProjectPlan.from_dict(data)
        self.assertIsNone(plan.positive_class_ratio)
        self.assertTrue(any("regression" in w for w in plan.warnings))

    def test_bool_target_ratio_is_filled_from_the_plan(self):
        """Plan sinif dengesine karar veriyorsa uretimi de o yonlendirmeli."""
        plan = ProjectPlan.from_dict(plan_dict())
        self.assertAlmostEqual(plan.target_column_spec().target_ratio, 0.18)

    def test_conflicting_target_ratio_is_rejected(self):
        data = plan_dict()
        for column in data["dataset"]["tables"][0]["columns"]:
            if column["name"] == "churned":
                column["target_ratio"] = 0.45
        with self.assertRaises(SchemaValidationError) as ctx:
            ProjectPlan.from_dict(data)
        self.assertIn("target_ratio", str(ctx.exception))

    def test_matching_target_ratio_is_accepted(self):
        data = plan_dict()
        for column in data["dataset"]["tables"][0]["columns"]:
            if column["name"] == "churned":
                column["target_ratio"] = 0.18
        self.assertAlmostEqual(
            ProjectPlan.from_dict(data).target_column_spec().target_ratio, 0.18)


class TestSplitStrategy(unittest.TestCase):
    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(SchemaValidationError):
            ProjectPlan.from_dict(plan_dict(
                split={"kind": "stratified", "reason": "x"}))

    def test_temporal_split_needs_a_datetime_column(self):
        data = plan_dict(split={"kind": "temporal", "column": "tenure_months",
                                "table": "customers", "reason": "x"})
        with self.assertRaises(SchemaValidationError) as ctx:
            ProjectPlan.from_dict(data)
        self.assertIn("datetime", str(ctx.exception))

    def test_split_column_must_exist(self):
        data = plan_dict(split={"kind": "group", "column": "account_id",
                                "table": "customers", "reason": "x"})
        with self.assertRaises(SchemaValidationError) as ctx:
            ProjectPlan.from_dict(data)
        self.assertIn("account_id", str(ctx.exception))

    def test_random_split_needs_no_column(self):
        plan = ProjectPlan.from_dict(plan_dict(
            split={"kind": "random", "reason": "satirlar bagimsiz"}))
        self.assertEqual(plan.split.kind, "random")

    def test_group_split_resolves_the_key(self):
        plan = ProjectPlan.from_dict(plan_dict(
            split={"kind": "group", "column": "customer_id", "table": "customers",
                   "reason": "ayni musteri iki tarafa dusmesin"}))
        self.assertEqual(plan.split.column, "customer_id")

    def test_missing_split_warns_on_supervised_plans(self):
        plan = ProjectPlan.from_dict(plan_dict(split=_REMOVE))
        self.assertTrue(any("train/test" in w.lower() for w in plan.warnings))

    def test_table_defaults_to_the_target_table(self):
        data = plan_dict(split={"kind": "temporal", "column": "signup_at",
                                "reason": "x"})
        plan = ProjectPlan.from_dict(data)
        self.assertEqual(plan.split.table, "customers")


class TestMalformedInput(unittest.TestCase):
    def test_dataset_is_required(self):
        with self.assertRaises(SchemaValidationError) as ctx:
            ProjectPlan.from_dict(plan_dict(dataset=_REMOVE))
        self.assertIn("dataset", str(ctx.exception))

    def test_unknown_task_type_is_rejected(self):
        with self.assertRaises(SchemaValidationError):
            ProjectPlan.from_dict(plan_dict(task_type="ranking"))

    def test_non_object_is_rejected(self):
        with self.assertRaises(SchemaValidationError):
            ProjectPlan.from_dict(["not", "a", "plan"])

    def test_parses_from_json_with_prose_around_it(self):
        text = "Here you go:\n```json\n%s\n```\nHope that helps!" % json.dumps(PLAN)
        plan = ProjectPlan.from_json(text, project="p")
        self.assertEqual(plan.target.column, "churned")

    def test_split_strategy_rejects_non_object(self):
        with self.assertRaises(SchemaValidationError):
            SplitStrategy.from_dict("temporal")


if __name__ == "__main__":
    unittest.main()
