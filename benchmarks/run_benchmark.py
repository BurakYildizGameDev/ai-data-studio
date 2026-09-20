#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Parametrik motorun yeniden üretilebilir üretim ölçümü (benchmark).

README "100.000 satır x 10 kolon 0,13 saniyede" diyor; bu betik o iddiayı okuyanın
kendi makinesinde tek komutla doğrulayabilmesi için var. Ölçülen tek şey **üretim**:
sabit bir Schema Contract'ın parametrik motorla DataFrame'e derlenmesi. LLM çağrısı,
doğrulama ve dosyaya yazma dışarıda - hiçbiri ağa çıkmaz, hiçbiri model gerektirmez.

Bağımlılık eklenmez: yalnızca projenin zaten kullandığı ``numpy``/``pandas`` ve
standart kütüphanedeki ``time``/``tracemalloc``. Harici bir benchmark kütüphanesi
(pytest-benchmark vb.) bilerek kullanılmıyor.

Kullanım:
    python benchmarks/run_benchmark.py            # terminale metin tablosu
    python benchmarks/run_benchmark.py --json     # benchmarks/results/dev_machine.json
    python benchmarks/run_benchmark.py --rows 10000 --repeat 1   # hızlı deneme
"""
from __future__ import annotations

import argparse
import gc
import json
import platform
import statistics
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # depo kökünden `python benchmarks/...` ile çalışsın
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402  (yol yukarıda ayarlanmalı)
import pandas as pd  # noqa: E402

from ai_data_studio.core.parametric_engine import ParametricEngine  # noqa: E402
from ai_data_studio.core.schema_contract import SchemaContract  # noqa: E402

DEFAULT_ROW_COUNTS = (10_000, 100_000, 1_000_000)
DEFAULT_REPEAT = 3
SEED = 42
DEFAULT_RESULT_PATH = REPO_ROOT / "benchmarks" / "results" / "dev_machine.json"
RESULT_SCHEMA_VERSION = 1

# Ölçümün sabiti: 10 kolonluk standart sözleşme. Bir modelin yazdığı sözleşmeyle
# aynı biçimde - JSON dict olarak - duruyor ve `SchemaContract.from_dict` ile aynı
# doğrulamadan geçiyor; böylece ölçülen yol gerçek koşudaki yolun ta kendisi.
# Kolon karışımı kasten çeşitli: sürekli dağılımlar, tam sayı, ikili etiket,
# kategori ve tarih; üstüne kopulanın çalışması için iki korelasyon ve motorun
# üretim sırasında onardığı iki iş kuralı.
STANDARD_CONTRACT: Dict[str, Any] = {
    "domain": "benchmark_loan_applications",
    "description": "Fixed 10-column contract used by the reproducible benchmark.",
    "row_count_target": 100_000,
    "random_seed": SEED,
    "columns": [
        {"name": "application_id", "type": "int", "min": 1, "max": 2_000_000_000,
         "distribution": "uniform"},
        {"name": "applicant_age", "type": "int", "min": 18, "max": 90,
         "distribution": "normal", "mean": 42, "std": 12},
        {"name": "annual_income", "type": "float", "min": 12_000, "max": 400_000,
         "distribution": "lognormal", "mean": 55_000},
        {"name": "credit_score", "type": "int", "min": 300, "max": 850,
         "distribution": "normal", "mean": 680, "std": 60},
        {"name": "loan_amount", "type": "float", "min": 1_000, "max": 250_000,
         "distribution": "gamma", "shape": 2.0, "scale": 18_000},
        {"name": "months_employed", "type": "int", "min": 0, "max": 480,
         "distribution": "exponential", "mean": 54},
        {"name": "prior_defaults", "type": "int", "min": 0, "max": 12,
         "distribution": "poisson", "mean": 0.4},
        {"name": "is_approved", "type": "bool", "target_ratio": 0.62},
        {"name": "product", "type": "category",
         "categories": ["mortgage", "auto", "personal", "student", "business"]},
        {"name": "applied_at", "type": "datetime",
         "description": "between 2024-01-01 and 2026-01-01"},
    ],
    "business_rules": [
        "loan_amount <= annual_income * 5",
        "months_employed >= 0",
    ],
    "correlations": [
        {"columns": ["annual_income", "credit_score"],
         "expected_sign": "positive", "min_r": 0.35},
        {"columns": ["credit_score", "is_approved"],
         "expected_sign": "positive", "min_r": 0.25},
    ],
}

TABLE_HEADER = "%12s %10s %14s %14s %14s" % (
    "Rows", "Time (s)", "Rows/s", "Peak mem (MB)", "DataFrame (MB)")


def build_schema() -> SchemaContract:
    """Standart sözleşmeyi her koşuda sıfırdan kurar (ölçümün dışında tutulur)."""
    return SchemaContract.from_dict(STANDARD_CONTRACT)


def _dataframe_megabytes(df: pd.DataFrame) -> float:
    """DataFrame'in kendi taşıdığı bayt - tracemalloc'un tepe değeriyle kıyas için."""
    return float(df.memory_usage(deep=True).sum()) / (1024 * 1024)


def warm_up() -> float:
    """İlk derlemeyi ısınma olarak koşar ve süresini döndürür.

    Sürecin ilk ``compile`` çağrısı tembel içe aktarmaları (scipy, pandas'ın
    kendi alt modülleri) da ödüyor: ölçülen makinede 10.000 satır ilk koşuda
    3,6 saniye, ikinci koşuda 0,02 saniye sürdü. Bu tek seferlik maliyet üretim
    hızı değil, süreç açılışıdır; ölçümün dışında tutulur ama raporda
    ``cold_start_seconds`` olarak görünür - CLI'yi bir kez çalıştıran kullanıcı
    onu da ödüyor.
    """
    schema = build_schema()
    engine = ParametricEngine(seed=SEED)
    start = time.perf_counter()
    engine.compile(schema, n_rows=1_000, seed=SEED)
    duration = time.perf_counter() - start
    gc.collect()
    return duration


def measure(rows: int, repeat: int) -> Dict[str, Any]:
    """Tek satır sayısı için süre ve tepe belleği ölçer.

    Süre ile bellek ayrı geçişlerde ölçülür: ``tracemalloc`` açıkken her ayırma
    izlendiği için üretim gözle görülür biçimde yavaşlar, süreyi onun altında
    ölçmek makineyi olduğundan yavaş gösterirdi.
    """
    schema = build_schema()
    engine = ParametricEngine(seed=SEED)

    # 1) Süre: `repeat` kez koş, en iyisini ve ortancasını sakla. En iyi değer
    #    makinenin yapabildiğini, ortanca tipik koşuyu gösterir.
    durations: List[float] = []
    df: Optional[pd.DataFrame] = None
    for _ in range(repeat):
        df = None
        gc.collect()
        start = time.perf_counter()
        df = engine.compile(schema, n_rows=rows, seed=SEED)
        durations.append(time.perf_counter() - start)

    assert df is not None  # repeat >= 1, argparse bunu garanti ediyor
    dataframe_mb = _dataframe_megabytes(df)
    columns = len(df.columns)
    df = None
    gc.collect()

    # 2) Bellek: ayrı bir geçiş, yalnızca tepe değer için.
    tracemalloc.start()
    tracemalloc.reset_peak()
    df = engine.compile(schema, n_rows=rows, seed=SEED)
    _current, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    df = None
    gc.collect()

    best = min(durations)
    return {
        "rows": rows,
        "columns": columns,
        "repeat": repeat,
        "best_seconds": round(best, 4),
        "median_seconds": round(statistics.median(durations), 4),
        "all_seconds": [round(value, 4) for value in durations],
        "rows_per_second": int(rows / best) if best > 0 else None,
        "peak_memory_mb": round(peak_bytes / (1024 * 1024), 2),
        "dataframe_mb": round(dataframe_mb, 2),
    }


def machine_info() -> Dict[str, str]:
    """Sayıların hangi makineye ait olduğu - onsuz ölçüm karşılaştırılamaz."""
    return {
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "machine": platform.machine(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
    }


def run(row_counts: Sequence[int], repeat: int) -> Dict[str, Any]:
    """Verilen satır sayılarını ölçer ve tek bir rapor sözlüğü döndürür."""
    schema = build_schema()
    type_counts: Dict[str, int] = {}
    for column in schema.columns:
        type_counts[column.type] = type_counts.get(column.type, 0) + 1

    cold_start = warm_up()
    results = [measure(rows, repeat) for rows in row_counts]
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "machine": machine_info(),
        "cold_start_seconds": round(cold_start, 4),
        "settings": {
            "engine": "parametric",
            "seed": SEED,
            "repeat": repeat,
            "columns": len(schema.columns),
            "column_types": dict(sorted(type_counts.items())),
            "business_rules": len(schema.business_rules),
            "correlations": len(schema.correlations),
            "measures": "generation only - no LLM call, no validation, no file export",
        },
        "results": results,
        "contract": STANDARD_CONTRACT,
    }


def format_table(report: Dict[str, Any]) -> str:
    """Terminale basılan metin tablosu."""
    machine = report["machine"]
    settings = report["settings"]
    types = ", ".join("%d %s" % (count, name)
                      for name, count in settings["column_types"].items())
    lines = [
        "AI Synthetic Data Studio - parametric generation benchmark",
        "",
        "Machine : %s | %s" % (machine["platform"], machine["processor"]),
        "Runtime : Python %s, numpy %s, pandas %s"
        % (machine["python"], machine["numpy"], machine["pandas"]),
        "Contract: %d columns (%s), %d business rules, %d correlations"
        % (settings["columns"], types, settings["business_rules"],
           settings["correlations"]),
        "Method  : best of %d runs, seed %d, %s"
        % (settings["repeat"], settings["seed"], settings["measures"]),
        "",
        TABLE_HEADER,
        "-" * len(TABLE_HEADER),
    ]
    for entry in report["results"]:
        lines.append("%12s %10.3f %14s %14.1f %14.1f" % (
            "{:,}".format(entry["rows"]),
            entry["best_seconds"],
            "{:,}".format(entry["rows_per_second"] or 0),
            entry["peak_memory_mb"],
            entry["dataframe_mb"],
        ))
    lines.extend([
        "",
        "Peak memory is what tracemalloc traced in this process during one generation:",
        "the finished DataFrame plus the engine's intermediate arrays.",
        "The first compile in a process also pays a one-time import cost, measured here",
        "as %.2f s and excluded from the times above." % report["cold_start_seconds"],
    ])
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproducible parametric-engine generation benchmark.")
    parser.add_argument("--json", action="store_true",
                        help="write the results to %s instead of printing a table"
                             % DEFAULT_RESULT_PATH.relative_to(REPO_ROOT).as_posix())
    parser.add_argument("--out", type=Path, default=DEFAULT_RESULT_PATH,
                        help="where --json writes (default: %(default)s)")
    parser.add_argument("--rows", type=int, nargs="+", default=list(DEFAULT_ROW_COUNTS),
                        metavar="N",
                        help="row counts to measure (default: 10000 100000 1000000)")
    parser.add_argument("--repeat", type=int, default=DEFAULT_REPEAT, metavar="N",
                        help="timed runs per row count, the best is reported "
                             "(default: %(default)s)")
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    if any(rows < 1 for rows in args.rows):
        parser.error("--rows must be positive")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = run(args.rows, args.repeat)

    if args.json:
        out_path: Path = args.out
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("Wrote %s" % out_path)
    else:
        print(format_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
