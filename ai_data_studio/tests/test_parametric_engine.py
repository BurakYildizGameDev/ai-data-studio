# -*- coding: utf-8 -*-
"""Test suite for ParametricEngine."""
import numpy as np
import pandas as pd
import pytest
from ai_data_studio.core.schema_contract import ColumnSpec, CorrelationRule, SchemaContract
from ai_data_studio.core.parametric_engine import ParametricEngine, compile_schema_to_dataframe

def test_parametric_engine_generates_valid_dataframe():
    schema = SchemaContract(
        domain="test_domain",
        description="test",
        row_count_target=500,
        random_seed=42,
        columns=[
            ColumnSpec(name="age", type="int", min=18, max=70, distribution="normal", mean=40, std=10),
            ColumnSpec(name="income", type="float", min=1000, max=50000, distribution="lognormal", mean=5000),
            ColumnSpec(name="is_active", type="bool", target_ratio=0.8),
            ColumnSpec(name="city", type="category", categories=["Istanbul", "Ankara", "Izmir"]),
        ]
    )
    
    df = compile_schema_to_dataframe(schema, n_rows=500)
    
    assert len(df) == 500
    assert list(df.columns) == ["age", "income", "is_active", "city"]
    assert df["age"].min() >= 18
    assert df["age"].max() <= 70
    assert pd.api.types.is_integer_dtype(df["age"])
    assert df["income"].min() >= 1000
    assert df["city"].isin(["Istanbul", "Ankara", "Izmir"]).all()
    assert abs(df["is_active"].mean() - 0.8) < 0.1


def _fraud_schema(rows=4000, ratio=0.05, label_type="bool"):
    """Ikili hedefli (dolandiricilik) sozlesme: uc surucu, tek etiket."""
    return SchemaContract(
        domain="card_fraud",
        description="test",
        row_count_target=rows,
        random_seed=7,
        columns=[
            ColumnSpec(name="device_risk_score", type="float", min=0, max=100,
                       distribution="uniform"),
            ColumnSpec(name="failed_attempts", type="int", min=0, max=10,
                       distribution="poisson", mean=1),
            ColumnSpec(name="amount", type="float", min=1, max=5000,
                       distribution="lognormal", mean=200),
            ColumnSpec(name="is_fraud", type=label_type, target_ratio=ratio),
        ],
        correlations=[
            CorrelationRule(columns=["device_risk_score", "is_fraud"],
                            expected_sign="positive", min_r=0.30),
            CorrelationRule(columns=["failed_attempts", "is_fraud"],
                            expected_sign="positive", min_r=0.25),
            CorrelationRule(columns=["amount", "is_fraud"],
                            expected_sign="positive", min_r=0.15),
        ],
    )


def test_binary_target_reaches_declared_correlations():
    """Bool hedefe korelasyon kurulabilmeli.

    Once kurulamiyordu: _apply_correlations iki tarafin da sayisal olmasini
    sartliyordu, bool kolonlar sessizce atlaniyordu. Canli olcum (Job #17):
    beklenen r=0.30 icin gerceklesme r=0.0035.
    """
    df = compile_schema_to_dataframe(_fraud_schema(), n_rows=4000, seed=7)
    labels = df["is_fraud"].astype(float)

    for driver, expected in (("device_risk_score", 0.30), ("failed_attempts", 0.25),
                             ("amount", 0.15)):
        r = df[driver].astype(float).corr(labels)
        assert r >= expected * 0.8, "%s -> is_fraud korelasyonu dustu: r=%.3f" % (driver, r)


def test_binary_target_preserves_target_ratio():
    """Korelasyon kurmak sinif dengesini bozmamali - esikleme kuantilden yapilir."""
    df = compile_schema_to_dataframe(_fraud_schema(ratio=0.05), n_rows=4000, seed=7)
    assert abs(df["is_fraud"].astype(float).mean() - 0.05) < 0.01


def test_binary_target_honours_negative_sign():
    schema = _fraud_schema()
    schema.correlations = [CorrelationRule(columns=["device_risk_score", "is_fraud"],
                                           expected_sign="negative", min_r=0.30)]
    df = compile_schema_to_dataframe(schema, n_rows=4000, seed=7)
    r = df["device_risk_score"].astype(float).corr(df["is_fraud"].astype(float))
    assert r <= -0.20, "negatif isaretli kural pozitif korelasyon uretti: r=%.3f" % r


def test_zero_one_int_label_is_treated_as_binary():
    """Etiket bool degil de 0/1 int tasiyorsa da ayni yol calismali.

    Fraud enjeksiyonu ve bazi semalar etiketi int olarak veriyor; bool sarti
    koysaydik bu kolonlar sessizce sayisal harmanlamaya duser ve etiket
    0/1 olmaktan cikardi.
    """
    rng = np.random.default_rng(11)
    n = 4000
    df = pd.DataFrame({
        "device_risk_score": rng.uniform(0, 100, n),
        "is_fraud": (rng.random(n) < 0.05).astype(int),
    })
    rule = CorrelationRule(columns=["device_risk_score", "is_fraud"],
                           expected_sign="positive", min_r=0.30)

    out = ParametricEngine(seed=11)._apply_correlations(df.copy(), [rule], rng)

    values = set(pd.unique(out["is_fraud"].astype(float)))
    assert values.issubset({0.0, 1.0}), "etiket 0/1 olmaktan cikti: %s" % values
    assert abs(out["is_fraud"].mean() - 0.05) < 0.01
    r = out["device_risk_score"].corr(out["is_fraud"].astype(float))
    assert r >= 0.24, "int etikette korelasyon kurulmadi: r=%.3f" % r


def test_numeric_correlation_still_applies():
    """Sayisal-sayisal yol degismemeli."""
    schema = SchemaContract(
        domain="income", description="test", row_count_target=2000, random_seed=3,
        columns=[
            ColumnSpec(name="monthly_income", type="float", min=1000, max=40000,
                       distribution="lognormal", mean=8000),
            ColumnSpec(name="credit_limit", type="float", min=1000, max=50000,
                       distribution="uniform"),
        ],
        correlations=[CorrelationRule(columns=["monthly_income", "credit_limit"],
                                      expected_sign="positive", min_r=0.45)],
    )
    df = compile_schema_to_dataframe(schema, n_rows=2000, seed=3)
    assert df["monthly_income"].corr(df["credit_limit"]) >= 0.40
