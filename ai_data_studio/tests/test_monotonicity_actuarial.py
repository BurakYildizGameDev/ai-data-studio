"""Monotonluk, Kredi Riski Skor Kartı ve Aktüeryal Dağılım Testleri."""
from __future__ import annotations

import unittest
import numpy as np
import pandas as pd

from ai_data_studio.core.schema_contract import (
    ColumnSpec,
    CorrelationRule,
    MonotonicityRule,
    SchemaContract,
    SchemaValidationError,
)
from ai_data_studio.core.monotonicity_validator import (
    MonotonicityCheckResult,
    MonotonicityReport,
    MonotonicityValidator,
    compute_woe_iv,
    validate_monotonicity,
)
from ai_data_studio.core import validator


class TestActuarialDistributionsSchema(unittest.TestCase):
    """Aktüerya ve kuyruk dağılımlarının şema sözleşmesi testleri."""

    def test_valid_actuarial_columns(self):
        """Gamma, Tweedie, ZIP ve GPD/Pareto dağılımları geçerli kabul edilmelidir."""
        spec_gamma = ColumnSpec.from_dict({
            "name": "claim_severity",
            "type": "float",
            "distribution": "gamma",
            "shape": 2.5,
            "scale": 1500.0,
        }, 0)
        self.assertEqual(spec_gamma.distribution, "gamma")
        self.assertEqual(spec_gamma.shape, 2.5)
        self.assertEqual(spec_gamma.scale, 1500.0)

        spec_zip = ColumnSpec.from_dict({
            "name": "claim_count",
            "type": "int",
            "distribution": "zip",
            "mean": 0.3,
            "zero_prob": 0.85,
        }, 1)
        self.assertEqual(spec_zip.distribution, "zip")
        self.assertEqual(spec_zip.zero_prob, 0.85)

        spec_tweedie = ColumnSpec.from_dict({
            "name": "pure_premium",
            "type": "float",
            "distribution": "tweedie",
            "mean": 250.0,
            "p_index": 1.65,
        }, 2)
        self.assertEqual(spec_tweedie.distribution, "tweedie")
        self.assertEqual(spec_tweedie.p_index, 1.65)

        spec_gpd = ColumnSpec.from_dict({
            "name": "catastrophic_loss",
            "type": "float",
            "distribution": "gpd",
            "shape": 0.25,
            "scale": 50000.0,
        }, 3)
        self.assertEqual(spec_gpd.distribution, "gpd")

    def test_invalid_actuarial_parameters_raise_error(self):
        """Hatalı aktüeryal parametreler SchemaValidationError fırlatmalıdır."""
        # zero_prob > 1.0
        with self.assertRaises(SchemaValidationError):
            ColumnSpec.from_dict({
                "name": "claim_count",
                "type": "int",
                "distribution": "zip",
                "zero_prob": 1.5,
            }, 0)

        # tweedie p_index not in (1, 2)
        with self.assertRaises(SchemaValidationError):
            ColumnSpec.from_dict({
                "name": "pure_premium",
                "type": "float",
                "distribution": "tweedie",
                "p_index": 2.5,
            }, 0)

        # shape <= 0
        with self.assertRaises(SchemaValidationError):
            ColumnSpec.from_dict({
                "name": "claim_severity",
                "type": "float",
                "distribution": "gamma",
                "shape": -1.0,
            }, 0)


class TestMonotonicityRuleAndContract(unittest.TestCase):
    """MonotonicityRule ve SchemaContract entegrasyon testleri."""

    def test_monotonicity_rule_parsing(self):
        rule = MonotonicityRule.from_dict({
            "column_x": "credit_score",
            "column_y": "approved_limit",
            "direction": "increasing",
            "min_compliance_ratio": 0.95,
        }, 0)
        self.assertEqual(rule.column_x, "credit_score")
        self.assertEqual(rule.column_y, "approved_limit")
        self.assertEqual(rule.direction, "increasing")
        self.assertEqual(rule.min_compliance_ratio, 0.95)

    def test_schema_contract_with_monotonicity(self):
        contract_dict = {
            "domain": "credit_card_scorecard",
            "row_count_target": 1000,
            "columns": [
                {"name": "credit_score", "type": "int", "min": 300, "max": 850},
                {"name": "approved_limit", "type": "float", "min": 1000, "max": 50000},
                {"name": "is_default", "type": "bool", "target_ratio": 0.05},
            ],
            "monotonicity_rules": [
                {"column_x": "credit_score", "column_y": "approved_limit", "direction": "increasing"},
                {"column_x": "credit_score", "column_y": "is_default", "direction": "decreasing"},
            ],
        }
        contract = SchemaContract.from_dict(contract_dict)
        self.assertEqual(len(contract.monotonicity_rules), 2)
        self.assertEqual(contract.monotonicity_rules[0].column_x, "credit_score")

        # Serializasyon kontrolü
        out = contract.to_dict()
        self.assertIn("monotonicity_rules", out)
        self.assertEqual(len(out["monotonicity_rules"]), 2)

    def test_unknown_column_dropped_with_warning(self):
        """Tanımsız kolon içeren monotonluk kuralı uyarıyla düşürülmelidir."""
        contract_dict = {
            "domain": "credit_risk",
            "columns": [
                {"name": "score", "type": "int"},
            ],
            "monotonicity_rules": [
                {"column_x": "score", "column_y": "non_existent_target", "direction": "increasing"},
            ],
        }
        contract = SchemaContract.from_dict(contract_dict)
        self.assertEqual(len(contract.monotonicity_rules), 0)
        self.assertTrue(any("Monotonluk kuralı düşürüldü" in w for w in contract.warnings))


class TestMonotonicityValidator(unittest.TestCase):
    """MonotonicityValidator binned ve pairwise uyum testleri."""

    def setUp(self):
        self.rng = np.random.default_rng(42)
        n = 500
        x = np.sort(self.rng.uniform(10, 100, n))
        self.increasing_df = pd.DataFrame({
            "credit_score": x,
            "approved_limit": 2.5 * x + 50.0,
            "unrelated_noise": self.rng.normal(0, 100, n),
        })

    def test_strictly_increasing_relationship(self):
        rule = MonotonicityRule(column_x="credit_score", column_y="approved_limit", direction="increasing")
        validator_inst = MonotonicityValidator()
        result = validator_inst.validate_rule(self.increasing_df, rule)

        self.assertTrue(result.passed)
        self.assertAlmostEqual(result.binned_compliance_ratio, 1.0, places=2)
        self.assertAlmostEqual(result.spearman_r, 1.0, places=2)
        self.assertAlmostEqual(result.pairwise_compliance_ratio, 1.0, places=2)

    def test_non_monotonic_noise_fails_check(self):
        rule = MonotonicityRule(column_x="credit_score", column_y="unrelated_noise", direction="increasing")
        validator_inst = MonotonicityValidator()
        result = validator_inst.validate_rule(self.increasing_df, rule)

        self.assertFalse(result.passed)
        self.assertLess(result.binned_compliance_ratio, 0.90)

    def test_decreasing_monotonicity(self):
        df_dec = pd.DataFrame({
            "debt_ratio": np.linspace(0.1, 0.9, 200),
            "savings": -1000 * np.linspace(0.1, 0.9, 200) + 2000,
        })
        rule = MonotonicityRule(column_x="debt_ratio", column_y="savings", direction="decreasing")
        result = MonotonicityValidator().validate_rule(df_dec, rule)

        self.assertTrue(result.passed)
        self.assertEqual(result.direction, "decreasing")
        self.assertAlmostEqual(result.spearman_r, -1.0, places=2)


class TestWoEAndInformationValue(unittest.TestCase):
    """Weight of Evidence (WoE) ve Information Value (IV) hesaplama testleri."""

    def test_woe_monotonic_trend(self):
        rng = np.random.default_rng(123)
        n = 600
        score = np.linspace(300, 850, n)
        # Yüksek skorda temerrüt (default) olasılığı daha düşüktür
        prob_default = 1.0 / (1.0 + np.exp((score - 550) / 60))
        target = (rng.uniform(0, 1, n) < prob_default).astype(int)

        df = pd.DataFrame({"score": score, "is_default": target})
        woe_res = compute_woe_iv(df, feature_col="score", target_col="is_default", n_bins=6)

        self.assertGreater(woe_res.total_iv, 0.0)
        self.assertGreaterEqual(len(woe_res.bins), 3)
        self.assertTrue(woe_res.is_monotonic_woe)
        self.assertIn("Strong", woe_res.predictive_power)


class TestSpearmanRankCorrelation(unittest.TestCase):
    """Spearman rank korelasyonu doğrulama testleri."""

    def test_non_linear_monotonic_spearman_vs_pearson(self):
        """Üstel / non-linear ilişkide Pearson düşerken Spearman 1.0 kalmalıdır."""
        x = np.linspace(1, 10, 100)
        y = np.exp(x)  # Katı monotonik ama üstel / non-linear
        df = pd.DataFrame({"x": x, "y": y})

        # Spearman kuralı
        rule_spearman = CorrelationRule(columns=["x", "y"], expected_sign="positive", min_r=0.98, method="spearman")
        rule_pearson = CorrelationRule(columns=["x", "y"], expected_sign="positive", min_r=0.98, method="pearson")

        contract = SchemaContract.from_dict({
            "domain": "test_rank",
            "columns": [
                {"name": "x", "type": "float"},
                {"name": "y", "type": "float"},
            ],
            "correlations": [
                {"columns": ["x", "y"], "expected_sign": "positive", "min_r": 0.98, "method": "spearman"},
                {"columns": ["x", "y"], "expected_sign": "positive", "min_r": 0.98, "method": "pearson"},
            ],
        })

        results = validator.validate_correlations(df, contract)
        self.assertEqual(len(results), 2)

        spearman_res = next(r for r in results if r["method"] == "spearman")
        pearson_res = next(r for r in results if r["method"] == "pearson")

        # Spearman mükemmel 1.0 olmalı ve geçmeli
        self.assertTrue(spearman_res["pass"])
        self.assertAlmostEqual(spearman_res["actual_r"], 1.0, places=2)

        # Pearson üstellik nedeniyle 0.98 eşiğini karşılayamayabilir
        self.assertLess(pearson_res["actual_r"], 0.95)
        self.assertFalse(pearson_res["pass"])


class TestEndToEndValidatorWithMonotonicity(unittest.TestCase):
    """Validator üzerinden uçtan uca monotonluk entegrasyonu."""

    def test_run_validation_executes_monotonicity(self):
        contract = SchemaContract.from_dict({
            "domain": "scorecard_test",
            "columns": [
                {"name": "income", "type": "float", "min": 1000, "max": 100000},
                {"name": "limit", "type": "float", "min": 500, "max": 50000},
            ],
            "monotonicity_rules": [
                {"column_x": "income", "column_y": "limit", "direction": "increasing", "min_compliance_ratio": 0.90},
            ],
        })

        x = np.linspace(2000, 80000, 300)
        y = 0.5 * x + 100.0
        df = pd.DataFrame({"income": x, "limit": y})

        clean_df, report = validator.run_validation(df, contract)

        self.assertIn("monotonicity", report)
        mono_data = report["monotonicity"]
        self.assertTrue(mono_data["all_passed"])
        self.assertEqual(mono_data["total_rules"], 1)
        self.assertEqual(mono_data["passed_rules"], 1)


if __name__ == "__main__":
    unittest.main()
