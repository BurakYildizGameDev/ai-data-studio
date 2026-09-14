# Engines

The generation engine and the enrichment engines are switches on the same pipeline —
CLI flags, `generate()` keywords, and checkboxes in the desktop studio all set the same
`PipelineConfig` fields.

- [Choosing a generation engine](#choosing-a-generation-engine)
- [Enrichment engines](#enrichment-engines)
- [Two ordering rules](#two-ordering-rules-the-pipeline-enforces)
- [Small local models](#small-local-models)
- [What the parametric engine does with the contract](#what-the-parametric-engine-does-with-the-contract)

## Choosing a generation engine

| Flag | Engine | What it does |
| --- | --- | --- |
| `--engine llm` (default) | — | The LLM writes a `generate_data()` program, a subprocess runs it, and failures are fed back to the model for up to three repair rounds |
| `--engine parametric` | `ParametricEngine` | Compiles the contract directly into NumPy/pandas vectors. No code generation and no subprocess. Works for single-table and relational contracts |
| `--engine auto` | both | Tries the LLM first; if code generation exhausts its retries, falls back to parametric instead of failing the run |

With `parametric`, the only LLM call is the one that writes the contract. Generation
itself takes milliseconds to seconds depending on size — measured on an Intel
i9-13900HX (Python 3.11, NumPy 2.4, pandas 3.0), with two correlations and one
monotonicity rule in the contract:

| Rows × columns | Generate | Validate |
| --- | --- | --- |
| 20,000 × 4 | ~20 ms | — |
| 100,000 × 10 | 0.13 s | 0.40 s |
| 1,000,000 × 10 | 1.6 s | 5.1 s |

The `llm` engine is slower because the program runs in a fresh subprocess, and it depends
on the model writing working code. It is still useful when a column needs logic the
contract cannot express.

```bash
# One LLM call (the contract), then vectorised generation. Deterministic for a given seed.
python -m ai_data_studio.core.orchestrator \
    --domain "credit card transactions with fraud labels" \
    --rows 50000 --engine parametric --formats csv
```

## Enrichment engines

| Flag | Engine | What it does |
| --- | --- | --- |
| `--time-series` | `TimeSeriesEngine` | Chronological ordering per entity, circadian activity curve, `seconds_since_last_tx`, burst-velocity anomalies. Needs an entity column that **repeats** — set it with `--ts-entity-col`; the pipeline warns when the column is near-unique, because velocity means nothing at one row per entity |
| `--expand-features` | `FeatureExpander` | Deterministic derived columns: financial ratios, age/credit bands, hour/day/weekend/night flags |
| `--dirty-rate 0.05` | `DirtyDataEngine` | MCAR missingness, QWERTY-adjacency typos, casing/whitespace jitter, outlier spikes, plus `is_corrupted` / `corruption_details` audit columns |
| `--hardware` | `HardwareProfiler` | Prints CPU/RAM/GPU tier and the local Ollama model that fits it, then exits |

In relational runs each of them applies to the root table unless you pick another one with
`--ts-table`, `--expand-table` or `--dirty-table`.

```bash
# Everything on: parametric generation + temporal dynamics + derived features + noise.
python -m ai_data_studio.core.orchestrator \
    --domain "credit card transactions with fraud labels" \
    --rows 50000 \
    --engine parametric \
    --time-series \
    --expand-features \
    --dirty-rate 0.05
```

```python
from ai_data_studio import generate

result = generate("credit card transactions with fraud labels",
                  rows=50_000,
                  provider="ollama", model="qwen2.5-coder:1.5b",
                  engine="parametric",     # "llm" (default) | "parametric" | "auto"
                  time_series=True,
                  expand_features=True,
                  dirty_rate=0.05)

result.report["engines"]["generation"]        # 'parametric'
result.report["engines"]["dirty_data"]        # corrupted_rows, breakdown, ordering note
result.dataframe["is_corrupted"].sum()        # the noise survived validation, on purpose
```

## Two ordering rules the pipeline enforces

1. **Time series and feature expansion run *before* validation.** They only add columns,
   and the validator normalizes column order as "schema columns, then extras" — so the
   new columns pass through untouched while the schema columns still get checked.
2. **Controlled noise runs *after* validation.** Injected before it, the schema-bounds
   check would delete the outlier spikes, the category check would delete the typos, and
   the null check would delete the missing values — the corruption would vanish silently.
   The report records this: `engines.dirty_data.column_stats_precede_corruption`.

## Small local models

Measured on `qwen2.5-coder:1.5b` (about 1 GB, runs on CPU-only machines), 20,000 rows,
three prompts (e-commerce orders, loan applications, mobile game players), repeated three
times each:

| Engine | Runs finished | Correlations met | Monotonicity met | Lowest rows kept | Avg. time |
| --- | --- | --- | --- | --- | --- |
| `parametric` | 9 / 9 | 25 / 26 | 19 / 20 | 99.2% | 14 s |
| `auto` | 3 / 3 (all fell back to parametric) | 8 / 8 | 3 / 4 | 99.1% | 30–240 s |
| `llm` | 0 / 3 | — | — | — | ~30 s |

A 1.5B model writes a usable contract but not a working generator: every `llm` run failed,
each time with a different class of error. Pick `parametric` for small models — `auto` gets
the same data but first spends three code-generation rounds that cannot succeed. The desktop
studio switches to `parametric` when you pick a small Ollama model (you can switch back), and
the CLI warns when `--engine llm` or `--engine auto` is used with one.

"Correlations met" means the data matches the contract. It does not mean the contract is
sensible: a small model can declare a relationship that runs the wrong way for the domain.
Read the schema file before relying on the data.

Reasoning models such as `deepseek-r1` spend most of their output budget thinking; the
client gives them a larger budget and retries once when the answer is cut off.

## What the parametric engine does with the contract

- **Distributions.** Each column is drawn from its declared distribution (`normal`,
  `uniform`, `lognormal`, `exponential`, `poisson`, `gamma`, `tweedie`, `zip`, `pareto`,
  `gpd`, `categorical`) and kept inside `min`/`max`; `int` columns stay integers and `bool`
  columns follow `target_ratio`.
- **Correlations and monotonicity** are solved together in one Gaussian copula that only
  reorders already-generated values, so every column keeps its distribution, bounds and type
  even when it takes part in several correlations. Declared correlations are enforced for
  numeric pairs, for a binary target driven by a numeric column (`is_fraud`, `churned`) via a
  latent-normal threshold that preserves the class ratio, and for binary-to-binary pairs.
  Pairs the contract says nothing about are filled with the value their chain implies
  (`a~b`, `b~c` ⇒ `a~c`) instead of zero; a zero there made the target matrix inconsistent
  and the repair step weakened the whole chain (measured: a four-column chain with targets
  of 0.88 came out at 0.61–0.73; now every link lands on target). A monotonicity rule
  becomes a 0.80 rank-correlation target (0.35 for a binary column), which clears the
  validator's binned and pairwise compliance checks: 25 of 25 rules across five seeds.
- **Business rules** are repaired while generating instead of being left to the validator:
  bounds tighter than the column range (`sessions_per_week <= 7`), scaled or summed sides
  (`loan_amount <= annual_income * 0.5`, `total >= basket + shipping`), `and`-joined bounds
  and derived columns (`ratio == loan / income`). A violating value is mirrored across the
  bound, so the column does not pile up at the limit. Rules with `or`/`not` are left to the
  validator. Repair runs once *before* the copula — a constant bound survives reordering, and
  repairing it afterwards mirrored half the rows and erased the correlation (measured: target
  0.5, result −0.008) — and once after it for column-to-column rules. Datetime columns take
  their range from the column `description`, and ordering rules between dates are repaired
  the same way.
- **The validator flags a suspicious rule.** When a single rule removes more than half of
  the rows on its own, it is still applied, but the console and the report
  (`business_rules[].suspicious`) say that it probably contradicts the column ranges. A rule
  that *no* row satisfies is skipped instead of emptying the dataset.

### Known limits

- Several numeric drivers correlated with the same rare `bool` column are each checked
  against that column's correlation ceiling on their own, not jointly; with four drivers on a
  5% class the targets can land a few hundredths short.
- Repairing a column-to-column rule after the copula can weaken the repaired column's own
  correlation target (measured: 0.30 → 0.255).
- On a rare `bool` target (≈5–8%), the validator's binned monotonicity check can fail on a
  single-row uptick in the last bins even when the rank correlation is strong.
