"""
Quickstart Demo: End-to-End Vectorized Synthetic Pipeline
-------------------------------------------------------
Demonstrates:
1. Hardware detection & optimal LLM recommendation
2. Instant (~2ms) Parametric Vector Compilation
3. Enterprise Time Series & Circadian velocity simulation
4. Realistic noise and QWERTY typo injection
5. Feature expansion (scaling to 20+ columns)
"""

import sys
import time
from pathlib import Path

# Add repository root to path for direct execution
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ai_data_studio.core.hardware_profiler import profile_hardware
from ai_data_studio.core.parametric_engine import compile_schema_to_dataframe
from ai_data_studio.core.time_series_engine import apply_time_series_dynamics
from ai_data_studio.core.dirty_data_engine import inject_dirty_data
from ai_data_studio.core.feature_expander import expand_features
from ai_data_studio.core.schema_contract import SchemaContract

def main():
    print("=" * 70)
    print(">>> AI Synthetic Data Studio - Quickstart Showcase")
    print("=" * 70)

    # 1. Hardware Profiling
    print("\n[1] Scanning Hardware Profile...")
    hw = profile_hardware()
    print(f"    CPU Cores: {hw.cpu_physical_cores} Physical / {hw.cpu_logical_cores} Logical ({hw.cpu_name})")
    print(f"    RAM: {hw.ram_total_gb:.1f} GB Total ({hw.ram_available_gb:.1f} GB Available)")
    print(f"    GPU: {hw.gpu_name} ({hw.vram_total_gb:.1f} GB VRAM)" if hw.has_gpu else "    GPU: None (CPU Only)")
    print(f"    Hardware Tier: {hw.hardware_tier}")
    print(f"    Recommended Local Model: {hw.recommended_model}")

    # 2. Parametric Vector Compilation (Instant Generation)
    print("\n[2] Compiling Vectorized Synthetic Schema (1,000 rows)...")
    contract = SchemaContract.from_dict({
        "domain": "financial_banking",
        "description": "High-velocity banking transactions",
        "columns": [
            {"name": "customer_id", "type": "int", "distribution": "uniform", "min": 1000, "max": 9999},
            {"name": "amount", "type": "float", "distribution": "lognormal", "mean": 4.5, "std": 1.2, "min": 1.0, "max": 50000.0},
            {"name": "account_age_months", "type": "int", "distribution": "normal", "mean": 36, "std": 18, "min": 1, "max": 120},
            {"name": "monthly_income", "type": "float", "distribution": "lognormal", "mean": 8.5, "std": 0.6, "min": 1000, "max": 40000},
            {"name": "credit_limit", "type": "float", "distribution": "uniform", "min": 1000, "max": 50000},
            {"name": "merchant_category", "type": "category", "categories": ["grocery", "tech", "travel", "dining", "crypto"]},
            {"name": "is_international", "type": "bool"},
            {"name": "channel", "type": "category", "categories": ["web", "mobile", "pos", "atm"]},
        ]
    })

    t0 = time.perf_counter()
    df_raw = compile_schema_to_dataframe(contract, n_rows=1000, seed=42)
    compile_time_ms = (time.perf_counter() - t0) * 1000.0
    print(f"    Generated {len(df_raw)} rows in {compile_time_ms:.2f} ms ({len(df_raw.columns)} columns)")

    # 3. Time Series Dynamics (Bimodal circadian cycle + velocity deltas)
    print("\n[3] Injecting Time Series Dynamics & Circadian Velocity...")
    t0 = time.perf_counter()
    df_ts, ts_meta = apply_time_series_dynamics(
        df_raw,
        entity_id_column="customer_id",
        start_date="2026-09-01 00:00:00",
        end_date="2026-09-07 23:59:59",
        burst_anomalies=True,
        seed=42
    )
    ts_time_ms = (time.perf_counter() - t0) * 1000.0
    print(f"    Applied circadian rhythm in {ts_time_ms:.2f} ms")
    print(f"    New temporal columns: transaction_timestamp, delta_seconds, velocity_1h, is_burst_fraud")

    # 4. Feature Expansion (Enriching to 20+ columns)
    print("\n[4] Expanding Engineered Features...")
    t0 = time.perf_counter()
    df_expanded, exp_meta = expand_features(df_ts)
    exp_time_ms = (time.perf_counter() - t0) * 1000.0
    print(f"    Expanded in {exp_time_ms:.2f} ms (Added {len(exp_meta['added_columns'])} features)")
    print(f"    Total columns now: {len(df_expanded.columns)}")

    # 5. Controlled Real-World Noise Injection
    print("\n[5] Injecting Controlled Real-World Noise (QWERTY Typos, Missingness, Casing)...")
    t0 = time.perf_counter()
    df_dirty, dirty_meta = inject_dirty_data(df_expanded, dirty_rate=0.08, seed=42)
    noise_time_ms = (time.perf_counter() - t0) * 1000.0
    print(f"    Injected noise in {noise_time_ms:.2f} ms")
    print(f"    Corrupted rows: {dirty_meta['corrupted_rows']} ({dirty_meta['corrupted_rate']*100:.1f}%)")
    print(f"    Audit Breakdown: {dirty_meta['corruption_breakdown']}")

    print("\n" + "=" * 70)
    print("[SUCCESS] Pipeline Completed Successfully!")
    print(f"    Final Shape: {df_dirty.shape[0]} rows x {df_dirty.shape[1]} columns")
    print(f"    Columns preview: {list(df_dirty.columns[:10])} ...")
    print("=" * 70)

    # The same engines are switches on the full pipeline, where an LLM writes the
    # schema for you first instead of it being hard-coded as above.
    print()
    print("Same engines, driven by the full pipeline:")
    print()
    print("  python -m ai_data_studio.core.orchestrator \\")
    print('      --domain "credit card transactions with fraud labels" --rows 50000 \\')
    print("      --engine parametric --time-series --expand-features --dirty-rate 0.05")
    print()
    print("  from ai_data_studio import generate")
    print('  generate("...", engine="parametric", time_series=True, dirty_rate=0.05)')


if __name__ == "__main__":
    main()
