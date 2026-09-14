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


def _shared_column_schema():
    """Canli demo sozlesmesinin (qwen2.5-coder:14b) ozu: basket_value uc kuralda."""
    return SchemaContract(
        domain="ecommerce_orders", description="test", row_count_target=20000, random_seed=42,
        columns=[
            ColumnSpec(name="basket_value", type="float", min=0, max=1000,
                       distribution="lognormal", mean=100, std=20),
            ColumnSpec(name="item_count", type="int", min=1, max=100,
                       distribution="poisson", mean=5),
            ColumnSpec(name="shipping_cost", type="float", min=0, max=200,
                       distribution="normal", mean=10, std=5),
            ColumnSpec(name="is_returned", type="bool", target_ratio=0.05),
        ],
        correlations=[
            CorrelationRule(columns=["basket_value", "item_count"], expected_sign="positive", min_r=0.70),
            CorrelationRule(columns=["shipping_cost", "basket_value"], expected_sign="positive", min_r=0.50),
            CorrelationRule(columns=["is_returned", "basket_value"], expected_sign="positive", min_r=0.40),
        ],
    )


def test_column_shared_by_several_rules_keeps_every_correlation():
    """Eski blend yolunda son kural ilkini eziyordu: hedef 0.70, olculen r=-0.004."""
    df = compile_schema_to_dataframe(_shared_column_schema(), n_rows=20000, seed=42)
    assert df["basket_value"].corr(df["item_count"].astype(float)) >= 0.70
    assert df["shipping_cost"].corr(df["basket_value"]) >= 0.50
    assert df["basket_value"].corr(df["is_returned"].astype(float)) >= 0.40


def test_correlation_keeps_marginals_bounds_and_dtypes():
    """Eski blend yolu lognormal kolonu negatife, int kolonu ondaliga ceviriyordu."""
    schema = _shared_column_schema()
    rng_free = ParametricEngine(seed=42)
    import copy
    independent = copy.deepcopy(schema)
    independent.correlations = []
    before = rng_free.compile(independent, n_rows=20000, seed=42)
    after = compile_schema_to_dataframe(schema, n_rows=20000, seed=42)

    for name in ("basket_value", "item_count", "shipping_cost"):
        # Kopula yalnizca satir eslesmesini degistirir: deger kumesi birebir ayni.
        assert np.array_equal(np.sort(before[name].to_numpy()), np.sort(after[name].to_numpy())), name
    assert after["basket_value"].between(0, 1000).all()
    assert after["item_count"].between(1, 100).all()
    assert pd.api.types.is_integer_dtype(after["item_count"])
    assert abs(after["is_returned"].mean() - 0.05) < 0.01


def test_contradictory_numeric_targets_do_not_crash():
    """Pozitif tanimli olmayan hedef matris en yakin gecerli matrise cekilmeli."""
    schema = SchemaContract(
        domain="contradiction", description="test", row_count_target=3000, random_seed=1,
        columns=[ColumnSpec(name=n, type="float", min=0, max=1, distribution="uniform")
                 for n in ("a", "b", "c")],
        correlations=[
            CorrelationRule(columns=["a", "b"], expected_sign="positive", min_r=0.9),
            CorrelationRule(columns=["b", "c"], expected_sign="positive", min_r=0.9),
            CorrelationRule(columns=["a", "c"], expected_sign="negative", min_r=0.9),
        ],
    )
    df = compile_schema_to_dataframe(schema, n_rows=3000, seed=1)
    assert len(df) == 3000 and df[["a", "b", "c"]].notna().all().all()


def test_correlation_chain_is_not_weakened_by_unstated_pairs():
    """a~b ve b~c guclu iken belirtilmemis a~c=0 sayilinca ozdeger kirpmasi zinciri eziyordu.

    Olcum (yas->kidem->gelir->kredi, hedef 0.88): gerceklesen 0.61-0.73.
    """
    names = ("a", "b", "c", "d")
    schema = SchemaContract(
        domain="chain", description="test", row_count_target=10000, random_seed=5,
        columns=[ColumnSpec(name=n, type="float", min=0, max=1, distribution="uniform")
                 for n in names],
        correlations=[CorrelationRule(columns=[x, y], expected_sign="positive", min_r=0.8,
                                      method="spearman")
                      for x, y in zip(names, names[1:])],
    )
    df = compile_schema_to_dataframe(schema, n_rows=10000, seed=5)
    for x, y in zip(names, names[1:]):
        assert df[x].corr(df[y], method="spearman") >= 0.80, (x, y)


def _monotonic_schema():
    """Canli 1.5b kosularinda parametrik motor monotonluk kurallarini hic uygulamiyordu (0/N)."""
    return SchemaContract.from_dict({
        "domain": "loans", "row_count_target": 20000, "random_seed": 42,
        "columns": [
            {"name": "age", "type": "int", "min": 18, "max": 75, "distribution": "normal",
             "mean": 40, "std": 12},
            {"name": "income", "type": "float", "min": 5000, "max": 400000,
             "distribution": "lognormal", "mean": 60000, "std": 30000},
            {"name": "credit_score", "type": "int", "min": 300, "max": 850,
             "distribution": "normal", "mean": 650, "std": 80},
            {"name": "loan_amount", "type": "float", "min": 1000, "max": 200000,
             "distribution": "gamma", "shape": 2, "scale": 15000},
            {"name": "years_employed", "type": "int", "min": 0, "max": 40,
             "distribution": "poisson", "mean": 6},
            {"name": "late_payments", "type": "int", "min": 0, "max": 20, "distribution": "zip",
             "mean": 2, "zero_prob": 0.6},
            {"name": "defaulted", "type": "bool", "target_ratio": 0.1},
        ],
        "correlations": [
            {"columns": ["income", "loan_amount"], "expected_sign": "positive", "min_r": 0.4},
        ],
        "monotonicity_rules": [
            {"column_x": "credit_score", "column_y": "defaulted", "direction": "decreasing"},
            {"column_x": "income", "column_y": "loan_amount", "direction": "increasing"},
            {"column_x": "years_employed", "column_y": "income", "direction": "increasing"},
            {"column_x": "late_payments", "column_y": "credit_score", "direction": "decreasing"},
            {"column_x": "age", "column_y": "years_employed", "direction": "increasing"},
        ],
    })


def test_monotonicity_rules_pass_the_validator():
    from ai_data_studio.core.monotonicity_validator import MonotonicityValidator

    schema = _monotonic_schema()
    df = compile_schema_to_dataframe(schema, n_rows=20000, seed=42)
    report = MonotonicityValidator().validate_all(df, schema.monotonicity_rules)
    failed = [(r.column_x, r.column_y, r.reason) for r in report.results if not r.passed]
    assert report.passed_rules == report.total_rules, failed
    # Siralama marjinalleri bozmaz, sinif orani korunur.
    assert df["income"].between(5000, 400000).all()
    assert abs(df["defaulted"].mean() - 0.10) < 0.01


def _rules_schema(rules):
    """Canli sema yanitlarindaki kural bicimleri (14b, 1.5b, deepseek-r1, Claude, agy)."""
    return SchemaContract.from_dict({
        "domain": "rules", "row_count_target": 20000, "random_seed": 7,
        "columns": [
            {"name": "sessions_per_week", "type": "int", "min": 0, "max": 200,
             "distribution": "uniform"},
            {"name": "customer_age", "type": "int", "min": 18, "max": 80,
             "distribution": "normal", "mean": 40, "std": 12},
            {"name": "annual_income", "type": "float", "min": 10000, "max": 300000,
             "distribution": "lognormal", "mean": 60000, "std": 25000},
            {"name": "loan_amount", "type": "float", "min": 1000, "max": 250000,
             "distribution": "uniform"},
            {"name": "loan_to_income", "type": "float", "min": 0, "max": 25,
             "distribution": "uniform"},
            {"name": "basket_value", "type": "float", "min": 0, "max": 1000,
             "distribution": "gamma", "shape": 2, "scale": 60},
            {"name": "shipping_cost", "type": "float", "min": 0, "max": 50,
             "distribution": "uniform"},
            {"name": "total_order_value", "type": "float", "min": 0, "max": 1200,
             "distribution": "uniform"},
            {"name": "item_count", "type": "int", "min": 1, "max": 30, "distribution": "poisson",
             "mean": 4},
            {"name": "signup_date", "type": "datetime"},
        ],
        "business_rules": rules,
    })


LIVE_RULE_FORMS = [
    "sessions_per_week <= 7",                                   # sinirdan siki sabit
    "customer_age > 18",                                        # kesin esitsizlik, int
    "loan_amount <= annual_income * 0.5",                       # olcekli taraf
    "loan_to_income == loan_amount / annual_income",            # turetilmis kolon
    "total_order_value >= basket_value + shipping_cost",        # toplamli taraf
    "shipping_cost >= 0 and shipping_cost <= 25",               # and ile birlesik
    "item_count * 10 <= basket_value",                          # ifade solda, kolon sagda
]


def test_parametric_engine_repairs_live_rule_forms():
    """Eskiden yalniz `a <= b` onariliyordu; bu kurallar veriyi validator'da eritiyordu."""
    from ai_data_studio.core.validator import apply_business_rules

    schema = _rules_schema(LIVE_RULE_FORMS)
    assert schema.business_rules == LIVE_RULE_FORMS
    df = compile_schema_to_dataframe(schema, n_rows=20000, seed=7)

    kept, detail = apply_business_rules(df, schema.business_rules)
    per_rule = {d["rule"]: d.get("violation_pct") for d in detail["rules"]}
    assert all(d["status"] == "applied" for d in detail["rules"]), detail
    assert len(kept) / len(df) >= 0.99, per_rule

    # Onarim sinirlari, tipleri ve dagilimin genisligini korur (sinirda yigilma yok).
    assert df["sessions_per_week"].between(0, 7).all()
    assert pd.api.types.is_integer_dtype(df["sessions_per_week"])
    assert df["sessions_per_week"].nunique() == 8
    assert df["loan_amount"].between(1000, 250000).all()
    assert (df["shipping_cost"] == 25).mean() < 0.01


def test_rule_that_contradicts_column_bounds_does_not_crash():
    """`x <= 5` iken min=18: ikisi birden saglanamaz, satir validator'a birakilir."""
    schema = _rules_schema(["customer_age <= 5", "signup_date >= '2020-01-01'",
                            "customer_age > 30 or basket_value > 0"])
    df = compile_schema_to_dataframe(schema, n_rows=2000, seed=7)
    assert len(df) == 2000
    assert df["customer_age"].between(18, 80).all()
    # Canli 1.5b: `loan_amount <= credit_score` (loan min 2000 > score max 850) onarimi
    # her satiri alt sinira kirpip kolonu sabite ceviriyordu.
    assert df["customer_age"].nunique() > 30


def test_datetime_column_uses_the_range_in_its_description():
    """Sozlesme tarih araligini aciklamada tasir; motor sabit 2026 penceresi kullaniyordu."""
    from ai_data_studio.core.parametric_engine import _datetime_window

    assert _datetime_window("signup timestamp (between 2020-01-01 and 2023-12-31)") == (
        pd.Timestamp("2020-01-01"), pd.Timestamp("2023-12-31"))
    assert _datetime_window("orders until 2022-06-30")[1] == pd.Timestamp("2022-06-30")
    assert _datetime_window("orders from 2021-03-01")[0] == pd.Timestamp("2021-03-01")
    assert _datetime_window("no range here")[0] == pd.Timestamp("2026-01-01")

    schema = SchemaContract.from_dict({
        "domain": "orders", "row_count_target": 5000,
        "columns": [{"name": "order_date", "type": "datetime",
                     "min": "2020-01-01", "max": "2023-12-31"}],    # normalizasyon aciklamaya tasir
        "business_rules": ["order_date <= '2023-12-31'"],
    })
    df = compile_schema_to_dataframe(schema, n_rows=5000, seed=3)
    assert df["order_date"].between("2020-01-01", "2023-12-31").all()


def test_datetime_ordering_rule_is_repaired():
    """Canli deepseek-r1: `last_session_date >= signup_date` satirlarin yarisini sildirdi."""
    from ai_data_studio.core.validator import apply_business_rules

    schema = SchemaContract.from_dict({
        "domain": "players", "row_count_target": 10000,
        "columns": [
            {"name": "signup_date", "type": "datetime",
             "description": "between 2022-01-01 and 2024-12-31"},
            {"name": "last_session_date", "type": "datetime",
             "description": "between 2022-01-01 and 2024-12-31"},
        ],
        "business_rules": ["last_session_date >= signup_date",
                           "signup_date < '2024-06-30'"],
    })
    df = compile_schema_to_dataframe(schema, n_rows=10000, seed=11)
    kept, detail = apply_business_rules(df, schema.business_rules)
    assert len(kept) / len(df) >= 0.99, detail
    assert pd.api.types.is_datetime64_any_dtype(df["signup_date"])
    assert df["signup_date"].dt.date.nunique() > 300           # sinirda yigilma yok


def test_constant_bound_repair_does_not_erase_correlations():
    """Canli 1.5b: `sessions_per_week >= 10` (ortalama 10) kopuladan SONRA onarilinca
    satirlarin yarisini aynaladi; hedef 0.5 olan korelasyon -0.008 olculdu."""
    from ai_data_studio.core.validator import apply_business_rules

    schema = SchemaContract.from_dict({
        "domain": "players", "row_count_target": 20000,
        "columns": [
            {"name": "age", "type": "int", "min": 18, "max": 60},
            {"name": "sessions_per_week", "type": "float", "min": 0, "max": 30,
             "distribution": "normal", "mean": 10, "std": 2},
            {"name": "average_session_minutes", "type": "float", "min": 0, "max": 300,
             "distribution": "normal", "mean": 15, "std": 5},
        ],
        "business_rules": ["sessions_per_week >= 10", "average_session_minutes >= 15"],
        "correlations": [
            {"columns": ["age", "sessions_per_week"], "expected_sign": "positive", "min_r": 0.5},
            {"columns": ["sessions_per_week", "average_session_minutes"],
             "expected_sign": "positive", "min_r": 0.5},
        ],
    })
    df = compile_schema_to_dataframe(schema, n_rows=20000, seed=42)
    kept, _ = apply_business_rules(df, schema.business_rules)
    assert len(kept) == len(df)
    assert df["age"].corr(df["sessions_per_week"]) >= 0.5
    assert df["sessions_per_week"].corr(df["average_session_minutes"]) >= 0.5


def test_contradicting_two_column_rule_leaves_the_column_intact():
    schema = _rules_schema(["loan_amount <= customer_age"])      # 1000+ vs <= 80
    independent = _rules_schema([])
    before = compile_schema_to_dataframe(independent, n_rows=3000, seed=7)
    after = compile_schema_to_dataframe(schema, n_rows=3000, seed=7)
    assert np.array_equal(before["loan_amount"].to_numpy(), after["loan_amount"].to_numpy())


def test_monotonicity_never_overrides_an_opposite_correlation():
    """Ayni ciftte zit yonlu acik korelasyon kurali varsa o kazanir."""
    engine = ParametricEngine()
    schema = _monotonic_schema()
    schema.monotonicity_rules[1].direction = "decreasing"     # income -> loan_amount
    targets = engine._with_monotonicity_targets(schema)
    pair = [t for t in targets if set(t.columns) == {"income", "loan_amount"}]
    assert len(pair) == 1 and pair[0].expected_sign == "positive"


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


def test_kendall_rules_are_generated_and_validated_as_kendall():
    """Motor ve doğrulayıcı `kendall` kuralını sessizce Pearson ile ölçüyordu.

    Gauss kopulasında tau = (2/pi) asin(r) < r: Pearson'a kalibre edilmiş veri gerçek
    Kendall ölçümünde kuralı düşürürdü. İkisi artık aynı ölçüyü kullanıyor.
    """
    from scipy.stats import kendalltau

    from ai_data_studio.core import validator

    schema = SchemaContract(
        domain="kendall_check",
        description="test",
        row_count_target=20000,
        random_seed=3,
        columns=[
            ColumnSpec(name="tenure", type="float", min=0, max=100, distribution="normal", mean=50, std=15),
            ColumnSpec(name="spend", type="float", min=1, max=10000, distribution="lognormal", mean=300),
        ],
        correlations=[
            CorrelationRule(columns=["tenure", "spend"], expected_sign="positive", min_r=0.5,
                            method="kendall"),
        ],
    )
    df = compile_schema_to_dataframe(schema, n_rows=20000, seed=3)
    tau = kendalltau(df["tenure"], df["spend"])[0]
    assert tau >= 0.5, tau
    # Pearson'a kalibre edilseydi tau ~0.33 kalırdı; sıra ölçüsünü gerçekten hedefliyor.
    assert tau - 0.5 < 0.1, tau

    result = validator.validate_correlations(df, schema)[0]
    assert result["method"] == "kendall"
    assert result["pass"] is True
    assert abs(result["actual_r"] - tau) < 0.01
