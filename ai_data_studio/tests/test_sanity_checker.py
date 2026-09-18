# -*- coding: utf-8 -*-
"""Heuristic Sanity Checker testleri.

Küçük yerel modellerin (1.5B) ürettiği şemalardaki mantıksal terslik,
semantik yön hatası ve geçişlilik çelişkilerinin doğru tespit edildiğini
ve auto-correct'in çalıştığını doğrular.

Not: Testler ``SchemaContract`` dataclass'ını **doğrudan** oluşturur
(``from_dict()`` kullanmaz) — çünkü ``from_dict()`` zaten
``check_schema_sanity()``'yi otomatik çağırır ve kuralları düzeltir.
Biz burada sanity checker'ı izole olarak test ediyoruz.
"""
from __future__ import annotations

import unittest
from typing import Any, Dict, List

from ai_data_studio.core.schema_contract import (
    ColumnSpec,
    CorrelationRule,
    MonotonicityRule,
    SchemaContract,
)
from ai_data_studio.core.schema_sanity_checker import (
    SanityReport,
    _classify_column,
    _is_positive_pair,
    check_schema_sanity,
)


def _raw_schema(
    correlations: List[CorrelationRule] = None,
    monotonicity_rules: List[MonotonicityRule] = None,
    columns: List[ColumnSpec] = None,
) -> SchemaContract:
    """Minimum geçerli bir SchemaContract'ı from_dict() KULLANMADAN oluşturur.

    Böylece ``from_dict()`` içindeki otomatik sanity check devreye girmez
    ve biz checker'ı izole test edebiliriz.
    """
    if columns is None:
        columns = [
            ColumnSpec(name="income", type="float", min=0, max=200000),
            ColumnSpec(name="credit_score", type="int", min=300, max=850),
            ColumnSpec(name="default_rate", type="float", min=0, max=1),
            ColumnSpec(name="is_fraud", type="bool", target_ratio=0.05),
            ColumnSpec(name="churn", type="bool", target_ratio=0.10),
            ColumnSpec(name="tenure", type="int", min=0, max=30),
            ColumnSpec(name="satisfaction", type="int", min=1, max=10),
            ColumnSpec(name="loyalty_score", type="float", min=0, max=100),
        ]
    return SchemaContract(
        domain="test",
        row_count_target=1000,
        columns=columns,
        correlations=correlations or [],
        monotonicity_rules=monotonicity_rules or [],
    )


class TestColumnClassification(unittest.TestCase):
    """_classify_column substring eşleme testleri."""

    def test_risk_indicators(self):
        self.assertEqual(_classify_column("default_rate"), "risk")
        self.assertEqual(_classify_column("is_fraud"), "risk")
        self.assertEqual(_classify_column("customer_churn"), "risk")
        self.assertEqual(_classify_column("late_payment_count"), "risk")
        self.assertEqual(_classify_column("has_defaulted"), "risk")

    def test_asset_indicators(self):
        self.assertEqual(_classify_column("income"), "asset")
        self.assertEqual(_classify_column("annual_salary"), "asset")
        self.assertEqual(_classify_column("credit_score"), "asset")
        self.assertEqual(_classify_column("customer_tenure"), "asset")
        self.assertEqual(_classify_column("account_balance"), "asset")

    def test_unknown_columns(self):
        self.assertIsNone(_classify_column("transaction_id"))
        self.assertIsNone(_classify_column("timestamp"))
        self.assertIsNone(_classify_column("product_name"))

    def test_case_insensitive(self):
        self.assertEqual(_classify_column("Income"), "asset")
        self.assertEqual(_classify_column("DEFAULT_RATE"), "risk")
        self.assertEqual(_classify_column("Credit-Score"), "asset")


class TestPositivePairs(unittest.TestCase):
    """Bilinen pozitif çift tanıma testleri."""

    def test_known_positive_pairs(self):
        self.assertTrue(_is_positive_pair("income", "credit_score"))
        self.assertTrue(_is_positive_pair("annual_salary", "credit_score"))
        self.assertTrue(_is_positive_pair("customer_tenure", "loyalty_score"))

    def test_order_independence(self):
        self.assertTrue(_is_positive_pair("credit_score", "income"))

    def test_unknown_pair(self):
        self.assertFalse(_is_positive_pair("income", "is_fraud"))
        self.assertFalse(_is_positive_pair("transaction_id", "amount"))


class TestCorrelationSemanticInversion(unittest.TestCase):
    """Risk ↔ Asset korelasyon terslik tespiti."""

    def test_income_default_positive_is_inverted(self):
        """income ↑ → default_rate ↑ (positive) yanlış; negatif olmalı."""
        schema = _raw_schema(correlations=[
            CorrelationRule(columns=["income", "default_rate"],
                           expected_sign="positive", min_r=0.3),
        ])
        report = check_schema_sanity(schema, auto_correct=True)
        self.assertTrue(report.has_warnings)
        self.assertEqual(report.corrections_applied, 1)
        self.assertEqual(schema.correlations[0].expected_sign, "negative")

    def test_credit_score_fraud_positive_is_inverted(self):
        """credit_score ↑ → is_fraud ↑ (positive) yanlış; negatif olmalı."""
        schema = _raw_schema(correlations=[
            CorrelationRule(columns=["credit_score", "is_fraud"],
                           expected_sign="positive", min_r=0.3),
        ])
        report = check_schema_sanity(schema, auto_correct=True)
        self.assertTrue(report.has_warnings)
        self.assertEqual(schema.correlations[0].expected_sign, "negative")

    def test_correct_negative_not_flagged(self):
        """income ↑ → default_rate ↓ (negative) doğru; bulgu olmamalı."""
        schema = _raw_schema(correlations=[
            CorrelationRule(columns=["income", "default_rate"],
                           expected_sign="negative", min_r=0.3),
        ])
        report = check_schema_sanity(schema, auto_correct=True)
        self.assertTrue(report.clean)

    def test_no_auto_correct_when_disabled(self):
        """auto_correct=False iken kural değişmemeli ama bulgu olmalı."""
        schema = _raw_schema(correlations=[
            CorrelationRule(columns=["income", "default_rate"],
                           expected_sign="positive", min_r=0.3),
        ])
        report = check_schema_sanity(schema, auto_correct=False)
        self.assertTrue(report.has_warnings)
        self.assertEqual(report.corrections_applied, 0)
        # Kural değişmemiş olmalı
        self.assertEqual(schema.correlations[0].expected_sign, "positive")

    def test_unknown_columns_pass_through(self):
        """Bilinmeyen kolonlar kontrol edilmemeli."""
        schema = _raw_schema(
            columns=[
                ColumnSpec(name="transaction_amount", type="float", min=0, max=10000),
                ColumnSpec(name="shipping_cost", type="float", min=0, max=500),
            ],
            correlations=[
                CorrelationRule(columns=["transaction_amount", "shipping_cost"],
                                expected_sign="positive", min_r=0.3),
            ],
        )
        report = check_schema_sanity(schema, auto_correct=True)
        self.assertTrue(report.clean)

    def test_positive_pair_negative_is_inverted(self):
        """income ↔ credit_score bilinen pozitif çift; negatif tanımlı ise uyarı."""
        schema = _raw_schema(correlations=[
            CorrelationRule(columns=["income", "credit_score"],
                           expected_sign="negative", min_r=0.3),
        ])
        report = check_schema_sanity(schema, auto_correct=True)
        self.assertTrue(report.has_warnings)
        self.assertEqual(schema.correlations[0].expected_sign, "positive")


class TestMonotonicitySemanticInversion(unittest.TestCase):
    """Risk ↔ Asset monotonluk yön terslik tespiti."""

    def test_income_up_default_up_is_inverted(self):
        """income ↑ → default_rate ↑ (increasing) yanlış; decreasing olmalı."""
        schema = _raw_schema(monotonicity_rules=[
            MonotonicityRule(column_x="income", column_y="default_rate",
                            direction="increasing"),
        ])
        report = check_schema_sanity(schema, auto_correct=True)
        self.assertTrue(report.has_warnings)
        self.assertEqual(schema.monotonicity_rules[0].direction, "decreasing")

    def test_correct_decreasing_not_flagged(self):
        """income ↑ → default_rate ↓ (decreasing) doğru."""
        schema = _raw_schema(monotonicity_rules=[
            MonotonicityRule(column_x="income", column_y="default_rate",
                            direction="decreasing"),
        ])
        report = check_schema_sanity(schema, auto_correct=True)
        # Monotonluk düzeltmesi bulgusu olmamalı
        mono_findings = [f for f in report.findings
                         if f.category == "monotonicity_inversion"]
        self.assertEqual(len(mono_findings), 0)

    def test_risk_x_asset_y_increasing_is_inverted(self):
        """default_rate ↑ → income ↑ (increasing) yanlış."""
        schema = _raw_schema(monotonicity_rules=[
            MonotonicityRule(column_x="default_rate", column_y="income",
                            direction="increasing"),
        ])
        report = check_schema_sanity(schema, auto_correct=True)
        mono_findings = [f for f in report.findings
                         if f.category == "monotonicity_inversion"]
        self.assertEqual(len(mono_findings), 1)
        self.assertEqual(schema.monotonicity_rules[0].direction, "decreasing")


class TestTransitivityViolation(unittest.TestCase):
    """Korelasyon üçgen geçişlilik çelişki tespiti."""

    def test_contradictory_triangle(self):
        """A~B (+), B~C (−), A~C (+) → çelişki.
        Beklenen: A~B (+) × B~C (−) = A~C (−) ama tanımlı (+).

        Semantik sözlüğe girmeyen kolon adları kullanıyoruz — böylece
        semantic auto-correct geçişlilik denetimini maskelemez.
        """
        schema = _raw_schema(
            columns=[
                ColumnSpec(name="feature_a", type="float", min=0, max=100),
                ColumnSpec(name="feature_b", type="float", min=0, max=100),
                ColumnSpec(name="feature_c", type="float", min=0, max=100),
            ],
            correlations=[
                CorrelationRule(columns=["feature_a", "feature_b"],
                                expected_sign="positive", min_r=0.5),
                CorrelationRule(columns=["feature_b", "feature_c"],
                                expected_sign="negative", min_r=0.5),
                CorrelationRule(columns=["feature_a", "feature_c"],
                                expected_sign="positive", min_r=0.5),
            ],
        )
        report = check_schema_sanity(schema, auto_correct=False)
        trans_findings = [f for f in report.findings
                          if f.category == "transitivity_violation"]
        self.assertGreaterEqual(len(trans_findings), 1)

    def test_consistent_triangle_no_finding(self):
        """A~B (+), B~C (−), A~C (−) → tutarlı."""
        schema = _raw_schema(correlations=[
            CorrelationRule(columns=["income", "credit_score"],
                           expected_sign="positive", min_r=0.5),
            CorrelationRule(columns=["credit_score", "default_rate"],
                           expected_sign="negative", min_r=0.5),
            CorrelationRule(columns=["income", "default_rate"],
                           expected_sign="negative", min_r=0.5),
        ])
        report = check_schema_sanity(schema, auto_correct=False)
        trans_findings = [f for f in report.findings
                          if f.category == "transitivity_violation"]
        self.assertEqual(len(trans_findings), 0)

    def test_weak_correlations_not_flagged(self):
        """min_r < 0.3 olan kurallar geçişlilik denetimini tetiklememeli."""
        schema = _raw_schema(correlations=[
            CorrelationRule(columns=["income", "credit_score"],
                           expected_sign="positive", min_r=0.2),
            CorrelationRule(columns=["credit_score", "default_rate"],
                           expected_sign="negative", min_r=0.2),
            CorrelationRule(columns=["income", "default_rate"],
                           expected_sign="positive", min_r=0.2),
        ])
        report = check_schema_sanity(schema, auto_correct=False)
        trans_findings = [f for f in report.findings
                          if f.category == "transitivity_violation"]
        self.assertEqual(len(trans_findings), 0)


class TestCleanSchema(unittest.TestCase):
    """Temiz şemaların bulgu üretmemesi."""

    def test_no_correlations_clean(self):
        schema = _raw_schema()
        report = check_schema_sanity(schema)
        self.assertTrue(report.clean)

    def test_correct_signs_clean(self):
        """Doğru işaretlenmiş şema temiz olmalı."""
        schema = _raw_schema(
            correlations=[
                CorrelationRule(columns=["income", "default_rate"],
                                expected_sign="negative", min_r=0.3),
                CorrelationRule(columns=["credit_score", "is_fraud"],
                                expected_sign="negative", min_r=0.3),
            ],
            monotonicity_rules=[
                MonotonicityRule(column_x="income", column_y="default_rate",
                                direction="decreasing"),
            ],
        )
        report = check_schema_sanity(schema, auto_correct=True)
        self.assertTrue(report.clean)


class TestSanityReportSummary(unittest.TestCase):
    """SanityReport.summary_lines() biçimlendirme testleri."""

    def test_clean_report_single_line(self):
        report = SanityReport()
        lines = report.summary_lines()
        self.assertEqual(len(lines), 1)

    def test_findings_produce_lines(self):
        schema = _raw_schema(correlations=[
            CorrelationRule(columns=["income", "default_rate"],
                           expected_sign="positive", min_r=0.3),
            CorrelationRule(columns=["credit_score", "is_fraud"],
                           expected_sign="positive", min_r=0.3),
        ])
        report = check_schema_sanity(schema, auto_correct=True)
        lines = report.summary_lines()
        self.assertGreaterEqual(len(lines), 2)


class TestFromDictIntegration(unittest.TestCase):
    """from_dict() ile entegre sanity check'in çalıştığını doğrular."""

    def test_from_dict_auto_corrects_inversion(self):
        """from_dict() income~default_rate pozitif kuralını negatife çevirmeli."""
        schema = SchemaContract.from_dict({
            "domain": "credit",
            "row_count_target": 1000,
            "columns": [
                {"name": "income", "type": "float", "min": 0, "max": 200000},
                {"name": "default_rate", "type": "float", "min": 0, "max": 1},
            ],
            "correlations": [
                {"columns": ["income", "default_rate"],
                 "expected_sign": "positive", "min_r": 0.3},
            ],
        })
        # from_dict() sanity check'i çağırdığı için kural zaten düzeltilmiş olmalı
        self.assertEqual(schema.correlations[0].expected_sign, "negative")
        # Uyarı warnings listesine eklenmeli
        sanity_warnings = [w for w in schema.warnings if "income" in w and "default_rate" in w]
        self.assertGreaterEqual(len(sanity_warnings), 1)



class TestNoOverCorrection(unittest.TestCase):
    """Mesru korelasyonlarin ezilmedigini dogrular.

    Substring eslesmesi ve pozitif-cift kisayolu birlikte, kullanicinin
    bilerek istedigi dogru korelasyonlari ters cevirebiliyordu. Asagidaki
    dordu de olculmus gercek vakalardir.
    """

    def _corrected_sign(self, col_a, col_b, wanted, auto_correct=True):
        rule = CorrelationRule(columns=[col_a, col_b],
                               expected_sign=wanted, min_r=0.5)
        check_schema_sanity(_raw_schema(correlations=[rule]),
                            auto_correct=auto_correct)
        return rule.expected_sign

    def test_satisfaction_vs_churn_stays_negative(self):
        """'loyalty' pozitif cifte esleyip risk mantigini atliyordu."""
        self.assertEqual(
            self._corrected_sign("customer_satisfaction", "loyalty_churn_rate",
                                 "negative"),
            "negative")

    def test_insurance_premium_vs_claim_stays_positive(self):
        """Yuksek riskli musteri yuksek prim oder; bu cift zorlanmamali."""
        self.assertEqual(
            self._corrected_sign("premium_paid", "claim_amount", "positive"),
            "positive")

    def test_investment_return_is_not_a_risk_column(self):
        """'return' iade anlamiyla risk listesinde; getiri ile karistirilmamali."""
        self.assertEqual(_classify_column("annual_return"), "asset")
        self.assertEqual(_classify_column("return_on_equity"), "asset")
        self.assertEqual(
            self._corrected_sign("investment_amount", "annual_return", "positive"),
            "positive")

    def test_default_currency_is_not_a_default_risk(self):
        self.assertIsNone(_classify_column("default_currency_rate"))
        self.assertEqual(
            self._corrected_sign("balance", "default_currency_rate", "positive"),
            "positive")

    def test_genuine_inversion_is_still_corrected(self):
        """Modulun asil isi kaybolmamali: income up -> default up yanlistir."""
        self.assertEqual(
            self._corrected_sign("annual_income", "default_rate", "positive"),
            "negative")

    def test_ambiguous_pair_is_reported_but_not_changed(self):
        rule = CorrelationRule(columns=["premium_paid", "claim_amount"],
                               expected_sign="positive", min_r=0.5)
        report = check_schema_sanity(_raw_schema(correlations=[rule]),
                                     auto_correct=True)
        self.assertEqual(rule.expected_sign, "positive")
        self.assertEqual(report.corrections_applied, 0)
        self.assertTrue(any(f.category == "ambiguous_pair" for f in report.findings))

    def test_auto_correct_false_warns_without_changing_rules(self):
        self.assertEqual(
            self._corrected_sign("annual_income", "default_rate", "positive",
                                 auto_correct=False),
            "positive")


class TestClassifierWordBoundaries(unittest.TestCase):
    """Siniflandirmanin substring degil kelime siniri kullandigini dogrular."""

    def test_inflected_forms_are_still_detected(self):
        for name in ("customer_returned", "defaulted_loans", "claims_count",
                     "churn_rate", "losses_total"):
            with self.subTest(column=name):
                self.assertEqual(_classify_column(name), "risk")

    def test_camel_case_is_split(self):
        self.assertEqual(_classify_column("creditScore"), "asset")
        self.assertEqual(_classify_column("totalReturn"), "asset")
        self.assertIsNone(_classify_column("defaultCurrency"))

    def test_unknown_columns_still_pass_through(self):
        for name in ("widget_id", "shipping_city", "timestamp"):
            with self.subTest(column=name):
                self.assertIsNone(_classify_column(name))


class TestSanityAutoCorrectIsConfigurable(unittest.TestCase):
    """from_dict uzerinden otomatik duzeltme kapatilabilmeli."""

    PAYLOAD = {
        "domain": "insurance",
        "row_count_target": 100,
        "columns": [
            {"name": "annual_income", "type": "float", "min": 0, "max": 200000},
            {"name": "default_rate", "type": "float", "min": 0, "max": 1},
        ],
        "correlations": [{"columns": ["annual_income", "default_rate"],
                          "expected_sign": "positive", "min_r": 0.4}],
    }

    def test_default_still_auto_corrects(self):
        contract = SchemaContract.from_dict(dict(self.PAYLOAD))
        self.assertEqual(contract.correlations[0].expected_sign, "negative")

    def test_opt_out_leaves_the_rule_alone_but_warns(self):
        contract = SchemaContract.from_dict(dict(self.PAYLOAD),
                                            sanity_auto_correct=False)
        self.assertEqual(contract.correlations[0].expected_sign, "positive")
        self.assertTrue(contract.warnings)

    def test_from_json_passes_the_flag_through(self):
        import json
        contract = SchemaContract.from_json(json.dumps(self.PAYLOAD),
                                            sanity_auto_correct=False)
        self.assertEqual(contract.correlations[0].expected_sign, "positive")

if __name__ == "__main__":
    unittest.main()
