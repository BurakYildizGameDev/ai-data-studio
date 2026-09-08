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


def test_compile_relational_generates_tables_with_zero_orphans():
    """compile_relational multi-tablolu semalarda sifir yetim yabanci anahtar garantisi vermelidir."""
    from ai_data_studio.core.dataset_contract import DatasetContract
    from ai_data_studio.core.parametric_engine import compile_relational, compile_dataset_to_dataframes

    dataset_dict = {
        "domain": "ecommerce",
        "root_table": "customers",
        "random_seed": 42,
        "tables": [
            {
                "name": "customers",
                "domain": "customers",
                "row_count_target": 50,
                "primary_key": "customer_id",
                "columns": [
                    {"name": "customer_id", "type": "int", "min": 1, "max": 100000},
                    {"name": "age", "type": "int", "min": 18, "max": 80},
                ],
            },
            {
                "name": "orders",
                "domain": "orders",
                "row_count_target": 150,
                "primary_key": "order_id",
                "foreign_keys": ["customer_id"],
                "columns": [
                    {"name": "order_id", "type": "int", "min": 1, "max": 100000},
                    {"name": "customer_id", "type": "int"},
                    {"name": "amount", "type": "float", "min": 10.0, "max": 1000.0},
                ],
            },
            {
                "name": "order_items",
                "domain": "order_items",
                "row_count_target": 300,
                "primary_key": "item_id",
                "foreign_keys": ["order_id"],
                "columns": [
                    {"name": "item_id", "type": "int", "min": 1, "max": 100000},
                    {"name": "order_id", "type": "int"},
                    {"name": "quantity", "type": "int", "min": 1, "max": 10},
                ],
            },
        ],
        "relationships": [
            {
                "parent_table": "customers",
                "parent_key": "customer_id",
                "child_table": "orders",
                "child_key": "customer_id",
                "min_per_parent": 1,
                "max_per_parent": 5,
                "mean_per_parent": 2.5,
            },
            {
                "parent_table": "orders",
                "parent_key": "order_id",
                "child_table": "order_items",
                "child_key": "order_id",
                "min_per_parent": 1,
                "max_per_parent": 4,
                "mean_per_parent": 2.0,
            },
        ],
    }
    contract = DatasetContract.from_dict(dataset_dict)
    tables = compile_relational(contract, root_rows=50, seed=42)

    assert set(tables.keys()) == {"customers", "orders", "order_items"}
    cust_df = tables["customers"]
    ord_df = tables["orders"]
    item_df = tables["order_items"]

    assert len(cust_df) == 50
    # Primary key tekilligi
    assert len(cust_df["customer_id"].unique()) == len(cust_df)
    assert len(ord_df["order_id"].unique()) == len(ord_df)
    assert len(item_df["item_id"].unique()) == len(item_df)

    # Sifir yetim foreign key
    assert ord_df["customer_id"].isin(cust_df["customer_id"]).all()
    assert item_df["order_id"].isin(ord_df["order_id"]).all()

    # Kardinalite sinirlari
    order_counts = ord_df.groupby("customer_id").size()
    assert order_counts.min() >= 1
    assert order_counts.max() <= 5

    # compile_dataset_to_dataframes sarmalayicisinin uyumlulugu
    wrapped = compile_dataset_to_dataframes(contract, root_rows=50, seed=42)
    assert set(wrapped.keys()) == set(tables.keys())
    assert len(wrapped["customers"]) == 50


def test_primary_key_uniqueness_string_prefix():
    """String tipi birincil anahtarlar tekil onekli formatta uretilmeli."""
    from ai_data_studio.core.parametric_engine import compile_schema_to_dataframe
    schema = SchemaContract(
        domain="products",
        description="test",
        row_count_target=100,
        random_seed=12,
        primary_key="sku",
        columns=[
            ColumnSpec(name="sku", type="string"),
            ColumnSpec(name="price", type="float", min=10.0, max=100.0),
        ]
    )
    df = compile_schema_to_dataframe(schema, n_rows=100)
    assert len(df) == 100
    assert len(df["sku"].unique()) == 100
    assert df["sku"].iloc[0].startswith("PRO_") and df["sku"].iloc[0].endswith("_000001")


def test_pure_binary_binary_correlation():
    """Iki boolean kolon arasinda dogrudan korelasyon kurulabilmeli."""
    schema = SchemaContract(
        domain="membership_conversion",
        description="test",
        row_count_target=5000,
        random_seed=42,
        columns=[
            ColumnSpec(name="is_member", type="bool", target_ratio=0.30),
            ColumnSpec(name="purchased", type="bool", target_ratio=0.10),
        ],
        correlations=[
            CorrelationRule(columns=["is_member", "purchased"], expected_sign="positive", min_r=0.25),
        ],
    )
    df = compile_schema_to_dataframe(schema, n_rows=5000, seed=42)
    assert abs(df["is_member"].mean() - 0.30) < 0.02
    assert abs(df["purchased"].mean() - 0.10) < 0.02

    r = df["is_member"].astype(float).corr(df["purchased"].astype(float))
    assert r >= 0.20, f"Beklenen r>=0.20 (hedef 0.25), gerceklesen r={r:.4f}"


def test_mixed_numeric_and_binary_drivers_for_binary_target():
    """Boolean hedef hem sayisal hem de boolean suruculeri ayni anda alabilmeli (Job #18 senaryosu)."""
    schema = SchemaContract(
        domain="card_fraud_complete",
        description="test",
        row_count_target=5000,
        random_seed=7,
        columns=[
            ColumnSpec(name="device_risk_score", type="float", min=0, max=100, distribution="uniform"),
            ColumnSpec(name="failed_attempts", type="int", min=0, max=10, distribution="poisson", mean=1),
            ColumnSpec(name="amount", type="float", min=1, max=5000, distribution="lognormal", mean=200),
            ColumnSpec(name="card_present", type="bool", target_ratio=0.20),
            ColumnSpec(name="is_fraud", type="bool", target_ratio=0.05),
        ],
        correlations=[
            CorrelationRule(columns=["device_risk_score", "is_fraud"], expected_sign="positive", min_r=0.30),
            CorrelationRule(columns=["failed_attempts", "is_fraud"], expected_sign="positive", min_r=0.25),
            CorrelationRule(columns=["amount", "is_fraud"], expected_sign="positive", min_r=0.15),
            CorrelationRule(columns=["card_present", "is_fraud"], expected_sign="negative", min_r=0.15),
        ],
    )
    df = compile_schema_to_dataframe(schema, n_rows=5000, seed=7)
    labels = df["is_fraud"].astype(float)

    assert abs(labels.mean() - 0.05) < 0.01
    assert abs(df["card_present"].astype(float).mean() - 0.20) < 0.02

    # Sayisal suruculer
    assert df["device_risk_score"].corr(labels) >= 0.24
    assert df["failed_attempts"].astype(float).corr(labels) >= 0.20
    assert df["amount"].corr(labels) >= 0.10
    # Boolean surucu (negatif isaret ve anlamli korelasyon)
    r_card = df["card_present"].astype(float).corr(labels)
    assert r_card <= -0.08, f"card_present korelasyonu zayif veya isaretsiz: r={r_card:.4f}"
