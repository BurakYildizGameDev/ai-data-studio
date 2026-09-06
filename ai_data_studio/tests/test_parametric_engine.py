# -*- coding: utf-8 -*-
"""Test suite for ParametricEngine."""
import numpy as np
import pandas as pd
import pytest
from ai_data_studio.core.schema_contract import ColumnSpec, SchemaContract
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
