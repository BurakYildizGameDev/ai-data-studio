# Generation benchmark

Every performance number in the README comes from this benchmark. It measures one thing:
**generation** — compiling a fixed Schema Contract into a pandas DataFrame with the
`parametric` engine. No LLM call, no validation pass, no file export, no network.

The script uses only what the project already depends on (`numpy`, `pandas`) plus `time` and
`tracemalloc` from the standard library. There is no benchmark framework to install.

## Running it

```bash
python benchmarks/run_benchmark.py
```

That prints the table below for your machine. Two other forms:

```bash
python benchmarks/run_benchmark.py --json                  # writes benchmarks/results/dev_machine.json
python benchmarks/run_benchmark.py --rows 10000 --repeat 1 # quick check on a slow machine
```

| Flag | What it does |
| --- | --- |
| *(none)* | Prints a formatted text table |
| `--json` | Writes the full report to `benchmarks/results/dev_machine.json` |
| `--out PATH` | Sends `--json` somewhere else — use it to keep a second machine's numbers |
| `--rows N [N ...]` | Row counts to measure (default `10000 100000 1000000`) |
| `--repeat N` | Timed runs per row count; the best one is reported (default `3`) |

The full run takes about 25 seconds and peaks near 300 MB. `--rows 10000 100000` is enough on
a machine with 8 GB of RAM.

## What is measured

- **The contract is fixed.** 10 columns — 5 `int`, 2 `float`, 1 `bool`, 1 `category`,
  1 `datetime` — with two business rules and two correlations, so the run exercises the
  Gaussian copula and the rule repair rather than plain `rng` draws. It lives in
  `STANDARD_CONTRACT` inside the script and is copied into the JSON report, so a result file
  says exactly what produced it.
- **The seed is fixed** (42). Same machine, same numbers.
- **Time** is `time.perf_counter()` around `ParametricEngine.compile()`, repeated three times;
  the table reports the best run and the JSON keeps all three.
- **Peak memory** is `tracemalloc`'s peak over a separate, untimed generation — timing under
  `tracemalloc` would make the machine look slower than it is. It covers the finished
  DataFrame plus the engine's intermediate arrays, and NumPy's buffers are traced too.
- **Cold start** is measured once and excluded from the times: the first `compile()` in a
  process also pays for lazy imports (~0.5 s on the machine below). A user who runs the CLI
  once pays it; a service that generates repeatedly does not.

## Reference measurements — development machine

Intel Core i9-13900HX, 32 GB RAM, Windows 11, Python 3.11.9, numpy 2.4.6, pandas 3.0.5.
Generation is CPU-only; the GPU in this machine is idle throughout.

Raw report: [`results/dev_machine.json`](results/dev_machine.json) — measured 2026-09-20.

| Rows | Time (s) | Rows/s | Peak memory (MB) | DataFrame (MB) |
| ---: | ---: | ---: | ---: | ---: |
| 10,000 | 0.022 | 462,830 | 2.8 | 0.8 |
| 100,000 | 0.156 | 640,314 | 27.1 | 7.7 |
| 1,000,000 | 1.898 | 526,996 | 270.9 | 77.1 |

Cold start (one-time, excluded above): 0.50 s.

Reading it: throughput is flat from 100,000 rows on — roughly half a million rows per second
for this contract — and memory grows linearly at about **0.27 MB per 1,000 rows** for
10 columns. At 10,000 rows the fixed per-call overhead still dominates, which is why the
rows/s figure is lower there. Budget peak memory at roughly 3.5× the size of the finished
DataFrame.

## Your machine

Run the script and paste your row into a copy of this table. The three columns that make a
result comparable are the CPU, the row count and the peak memory.

| Machine | CPU | Python / numpy / pandas | 100,000 rows | 1,000,000 rows | Peak (1M) |
| --- | --- | --- | ---: | ---: | ---: |
| Development machine | i9-13900HX | 3.11.9 / 2.4.6 / 3.0.5 | 0.156 s | 1.898 s | 270.9 MB |
| *your machine* | | | | | |

## What this does not measure

- **The LLM call.** One call per run, independent of row count, and it dominates a small run:
  a 20,000-row run with `qwen2.5-coder:1.5b` takes about 16 seconds end to end, nearly all of
  it the model writing the contract. See [docs/engines.md](../docs/engines.md).
- **Validation and export.** The validator's cleaning passes and writing CSV/Parquet are real
  costs in a full pipeline run; neither is included here.
- **The `llm` engine.** It runs a model-written program in a separate process, so its speed is
  a property of the model and the generated code, not of this engine.
