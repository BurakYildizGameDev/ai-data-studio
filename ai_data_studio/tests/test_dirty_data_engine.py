# -*- coding: utf-8 -*-
"""Test suite for DirtyDataEngine."""
import numpy as np
import pandas as pd
import pytest
from ai_data_studio.core.dirty_data_engine import DirtyDataConfig, DirtyDataEngine, inject_dirty_data

def test_dirty_data_engine_basic():
    df = pd.DataFrame({
        "customer_id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "city": ["Istanbul", "Ankara", "Izmir", "Bursa", "Antalya", "Adana", "Konya", "Trabzon", "Samsun", "Eskisehir"],
        "age": [25, 30, 35, 40, 45, 50, 55, 60, 65, 70],
        "spend": [100.5, 200.0, 150.75, 80.0, 500.0, 45.0, 310.0, 95.5, 600.0, 120.0]
    })
    
    cfg = DirtyDataConfig(dirty_rate=0.4, missing_rate=0.5, typo_rate=0.5, outlier_spike_rate=0.5, random_seed=42)
    engine = DirtyDataEngine(cfg)
    df_corrupt, meta = engine.corrupt(df)
    
    assert len(df_corrupt) == 10
    assert meta["corrupted_rows"] == 4
    assert "is_corrupted" in df_corrupt.columns
    assert "corruption_details" in df_corrupt.columns
    assert df_corrupt["is_corrupted"].sum() == 4
    
    # Check that at least some corruption took place
    corrupted_subset = df_corrupt[df_corrupt["is_corrupted"]]
    assert len(corrupted_subset) == 4
    for idx, row in corrupted_subset.iterrows():
        assert row["corruption_details"] != "clean"

def test_inject_dirty_data_helper():
    df = pd.DataFrame({"val": [10, 20, 30, 40, 50]})
    df_out, meta = inject_dirty_data(df, dirty_rate=0.4, seed=42)
    assert len(df_out) == 5
    assert meta["corrupted_rows"] >= 1
