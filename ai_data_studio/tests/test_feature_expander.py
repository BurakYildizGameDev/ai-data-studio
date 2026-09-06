# -*- coding: utf-8 -*-
"""Birim testleri: FeatureExpander modülü."""
import unittest
import pandas as pd
import numpy as np
from ai_data_studio.core.feature_expander import expand_features


class TestFeatureExpander(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame({
            "customer_id": ["C1", "C2", "C3", "C4"],
            "customer_age": [22, 45, 58, 72],
            "transaction_amount": [50.0, 1500.0, 30.0, 200.0],
            "customer_income": [36000.0, 60000.0, 48000.0, 24000.0],
            "credit_limit": [1000.0, 5000.0, 2500.0, 1000.0],
            "credit_score": [550, 710, 680, 820],
            "failed_attempts": [0, 3, 1, 0],
            "transaction_timestamp": [
                "2026-08-01 03:15:00",
                "2026-08-01 14:30:00",
                "2026-08-02 19:45:00",
                "2026-08-03 09:00:00"
            ]
        })

    def test_expand_features_basic(self):
        df_exp, meta = expand_features(self.df)
        self.assertGreater(len(df_exp.columns), len(self.df.columns))
        self.assertIn("amount_to_income_ratio", df_exp.columns)
        self.assertIn("credit_utilization_ratio", df_exp.columns)
        self.assertIn("age_group", df_exp.columns)
        self.assertIn("credit_rating", df_exp.columns)
        self.assertIn("hour_of_day", df_exp.columns)
        self.assertIn("is_weekend", df_exp.columns)
        self.assertIn("is_night_transaction", df_exp.columns)

    def test_age_group_categories(self):
        df_exp, _ = expand_features(self.df)
        groups = list(df_exp["age_group"])
        self.assertEqual(groups, ["YOUNG", "ADULT", "MATURE", "SENIOR"])

    def test_credit_rating_categories(self):
        df_exp, _ = expand_features(self.df)
        ratings = list(df_exp["credit_rating"])
        self.assertEqual(ratings, ["POOR", "GOOD", "GOOD", "EXCELLENT"])

    def test_night_transaction(self):
        df_exp, _ = expand_features(self.df)
        # 03:15 is night transaction
        self.assertTrue(df_exp.loc[0, "is_night_transaction"])
        # 14:30 is not night transaction
        self.assertFalse(df_exp.loc[1, "is_night_transaction"])


if __name__ == "__main__":
    unittest.main()
