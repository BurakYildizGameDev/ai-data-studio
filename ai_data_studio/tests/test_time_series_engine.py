# -*- coding: utf-8 -*-
"""Test suite for TimeSeriesEngine."""
import pandas as pd
import pytest
from ai_data_studio.core.time_series_engine import TimeSeriesConfig, TimeSeriesEngine, apply_time_series_dynamics

def test_time_series_engine_basic():
    df = pd.DataFrame({
        "customer_id": ["USR_1", "USR_1", "USR_1", "USR_2", "USR_2", "USR_3"],
        "amount": [10.0, 25.0, 50.0, 100.0, 15.0, 80.0],
        "is_fraud": [False, False, False, False, False, False]
    })
    
    cfg = TimeSeriesConfig(
        timestamp_column="tx_time",
        entity_id_column="customer_id",
        start_date="2026-08-01 00:00:00",
        end_date="2026-08-10 00:00:00",
        add_velocity_columns=True,
        burst_anomalies=True,
        burst_rate=0.3,
        random_seed=42
    )
    engine = TimeSeriesEngine(cfg)
    df_ts, meta = engine.apply(df)
    
    assert len(df_ts) == 6
    assert "tx_time" in df_ts.columns
    assert "seconds_since_last_tx" in df_ts.columns
    assert "is_high_velocity" in df_ts.columns
    
    # Check that df_ts is sorted chronologically
    assert df_ts["tx_time"].is_monotonic_increasing
    assert meta["unique_entities"] == 3
