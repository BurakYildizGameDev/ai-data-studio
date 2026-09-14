# AI Synthetic Data Studio & Validator

<p align="center">
  <img src="ai_data_studio/assets/logo.png" width="96" height="96" alt="AI Synthetic Data Studio logo">
</p>

<p align="center">
  <strong>High-performance, privacy-first synthetic data generation and multi-stage statistical validation studio.</strong>
</p>

<p align="center">
  <a href="https://github.com/BurakYildizGameDev/ai-data-studio/actions/workflows/ci.yml"><img src="https://github.com/BurakYildizGameDev/ai-data-studio/actions/workflows/ci.yml/badge.svg" alt="CI Status"></a>
  <img src="https://img.shields.io/badge/tests-680%20passed-brightgreen.svg" alt="Tests: 680 Passed">
  <a href="https://pypi.org/project/ai-data-studio/"><img src="https://img.shields.io/badge/pypi-v2.0.0-blue.svg" alt="PyPI Version"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg" alt="Python 3.10 | 3.11 | 3.12"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-000000.svg" alt="Code Style: Ruff"></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg" alt="Platform">
  <img src="https://img.shields.io/badge/LLMs-Ollama%20%7C%20Claude%20CLI%20%7C%20Gemini-purple.svg" alt="LLM Engines">
  <img src="https://img.shields.io/badge/architecture-Parametric%20Vector%20%2B%20Discriminator-orange.svg" alt="Architecture">
</p>

<p align="center">
  <img src="docs/media/demo.gif" width="900" alt="Desktop studio demo: describing an e-commerce dataset, running the 7-step pipeline and reviewing the result, validation charts and job history">
  <br>
  <sub>15-second tour of the desktop studio — local Ollama <code>qwen2.5-coder:14b</code>, parametric engine, 20,000 rows.
  Only the LLM's schema step is sped up; everything else plays in real time. (<a href="docs/media/demo.mp4">MP4</a>)</sub>
</p>

---

## Overview

Most synthetic data tools prompt an LLM to generate raw CSV rows token-by-token. For 50,000+ rows, this approach costs hundreds of dollars in API tokens, takes hours, and suffers from context fatigue and repetitive outputs.

**AI Synthetic Data Studio** adopts a **Generator–Discriminator** architecture:
1. **The Generator (LLM):** The model analyzes your domain description and generates clean, vectorized **NumPy / Pandas code** (rather than raw rows).
2. **The Sandbox:** The code runs in an isolated, AST-monitored Python sandbox with strict memory and execution timeouts, generating **100,000+ rows in under 2 seconds**.
3. **The Discriminator (Statistical & ML Validator):** A multi-stage hygiene pipeline purges duplicate rows, bounds violations, business rule anomalies and univariate outliers, then verifies Pearson/Spearman correlations and Kolmogorov-Smirnov distributions. Filtering is **tail-preserving by design**: statistical outlier removal is never applied where it would flatten a heavy-tailed distribution or break a target correlation.

The result is mathematically consistent, highly authentic synthetic data ready for model training, analytics, and software testing — at **$0.00 cost** when using local Ollama or Antigravity CLI.

---

## Key Features

- **Blazing Fast Vectorized Generation:** Capable of synthesizing millions of rows locally in seconds using NumPy vectorization and Copula ranking methods.
- **Multi-Provider LLM Support:**
  - **Local (Ollama):** 100% offline, private, and free (`qwen2.5-coder`, `llama3.1`, etc.).
  - **Google Gemini:** Direct Google AI Studio API or Antigravity CLI (zero API key overhead).
  - **Anthropic Claude:** Claude Opus 5, Sonnet 5 and Haiku 4.5 via the official API or an existing Claude Code session.
- **Real-Time Web Intelligence (Web Seed Collector):** Built-in DuckDuckGo / URL scraper extracts domain distributions and realistic category values from live web sources without requiring paid search APIs.
- **Multi-Stage Validation Pipeline (Discriminator):**
  - Deduplication
  - Strict Bounds and Data Type Enforcement
  - Pandas `df.eval()` Business Rules
  - Distribution-Aware Univariate Z-Score Filtering ($|Z| > 3.0$) — applied **only** to approximately symmetric columns. Heavy-tailed and zero-inflated columns (`gamma`, `lognormal`, `pareto`, `zip`, `poisson`, …) are skipped automatically, because a fixed $|Z|$ cut on such a column decapitates the tail that carries the signal. Detection uses the schema `distribution` first, then a robust quantile (Bowley) fallback.
  - Multivariate Isolation Forest Anomaly Detection — **opt-in** (`--contamination 0.05`). Off by default: a fixed contamination rate asserts "x% of my data is bad" and deletes that share even from clean data.
  - **Correlation Guard** — target correlations are measured before and after outlier removal. If cleaning breaks a correlation that previously held, the outlier stages are rolled back automatically and the regression is reported (disable with `--no-correlation-guard`).
  - Target Correlation Verification ($r \ge \text{threshold}$)
  - Kolmogorov-Smirnov (KS) Distribution Conformance
- **Privacy & HIPAA Safe Harbor Auditor:**
  - Mathematical memorization risk detection via **Distance to Closest Record (DCR)** and **Nearest Neighbor Distance Ratio (NNDR)** against real reference seeds.
  - Empirical Differential Privacy ($\epsilon$-DP) score estimation.
  - HIPAA Safe Harbor 18 Direct Identifiers Scanner (45 CFR § 164.514(b)).
  - Clinical date shifting (`shift_clinical_dates`) preserving intra-patient intervals and age-89+ capping (`cap_hipaa_age`).
  - Automated Markdown compliance auditing report (`_privacy_report.md`).
- **Imbalanced Class & Anomaly Preservation (Fraud & Risk):**
  - Anomaly protection flag (`--preserve-anomaly-col`) ensuring rare ground-truth events (e.g., `is_fraud=1`) are not purged by Z-Score or Isolation Forest.
  - Built-in `FraudScenarioInjector` with parameterized attack models (burst amounts, velocity checks, off-hours activity, credential stuffing).
- **Credit Risk & Monotonicity Validator (Basel III / Scorecards):**
  - Enforces and validates monotonic rank-ordering between risk drivers and outcomes ($X_1 > X_2 \implies Y_1 \ge Y_2$) across binned quantiles and pairwise samples.
  - Automated Weight of Evidence (WoE) and Information Value (IV) analysis with monotonic trend verification.
  - Non-linear rank correlations (**Spearman** / **Kendall**) and multivariate **Gaussian Copula** (Cholesky decomposition) generation templates.
- **Actuarial & Heavy-Tailed Distributions (Insurance & Claims):**
  - Compound Poisson-Gamma **Tweedie** ($1 < p < 2$) for pure premium modeling.
  - **Zero-Inflated Poisson (ZIP)** for high-zero claim counts.
  - **Gamma** distribution for positive claim severity.
  - **Generalized Pareto Distribution (GPD / Pareto)** for extreme tail catastrophe modeling.
- **Parametric Vector Compiler (`ParametricEngine`):** Instant C-level vector compilation of `SchemaContract` directly into Pandas/NumPy distributions (Normal, Lognormal, Exponential, Gamma, Tweedie, ZIP, Pareto, GPD) in **~2ms**, bypassing code-generation latency for lightweight models. Target correlations are induced all at once with a Gaussian copula that only reorders the already-generated values, so every column keeps its distribution, bounds and integer type even when one column takes part in several correlations. Enable with `--engine parametric` (or `--engine auto` to fall back to it only when code generation fails).
- **Time Series & Velocity Engine (`TimeSeriesEngine`):** Chronological entity ordering, bimodal circadian activity cycles, inter-arrival time deltas (`seconds_since_last_tx`), and burst fraud simulation. Enable with `--time-series`.
- **Controlled Noise & Data Corruption (`DirtyDataEngine`):** Real-world benchmark noise simulation including MCAR missingness, physical QWERTY distance matrix typos, casing/whitespace jitter, outlier spikes, and audit tracking columns (`is_corrupted`, `corruption_details`). Enable with `--dirty-rate 0.05`; it runs *after* validation so the noise actually survives into the output.
- **Hardware-Aware Model Recommender (`HardwareProfiler`):** Automatically scans CPU cores, system RAM, and NVIDIA GPU VRAM to classify hardware tier and recommend the optimal local Ollama model. Print it with `--hardware`; the desktop model picker preselects the recommended model when it is installed.
- **Deterministic Feature Expander (`FeatureExpander`):** Enriches compact schemas generated by lightweight 1.5B/3B models with financial ratios, credit ratings, and behavioral flags to scale datasets to 20+ enterprise columns. Enable with `--expand-features`.
- **Self-Healing Code Loop:** If generated code fails execution or violates structural schema bounds, tracebacks and AST hints are fed back to the LLM to auto-correct the code (up to 3 retries). A missing import of a known name (`Faker`, `np`, `ndtr`, …) is added directly and the code re-runs without spending an LLM round or a retry.
- **Three Ways In — Python API, CLI, GUI:** A three-line Python API (`from ai_data_studio import generate`) for notebooks and pipelines, a full headless CLI for CI/CD, and a CustomTkinter desktop studio with real-time colored console logging and distribution/correlation charts. The package is `py.typed`, and `import ai_data_studio` stays lazy so nothing heavy loads until you call it.
- **Multi-Format Export & HuggingFace Hub:** Exports to CSV, Parquet, JSON, plus auto-generated HuggingFace Dataset Cards (`README.md`).

---

## Pipeline Workflow

```
[1] Service & Auth Check  ──> Verify API credentials / local Ollama daemon
[2] Research & Schema     ──> LLM synthesizes strict JSON Schema Contract
[3] Seed Data Lookup      ──> Web scraping or HuggingFace reference sample (Optional)
[4] Code Generation       ──> LLM authors vectorized generate_data(n_rows, seed)
[5] Sandbox Execution     ──> Subprocess execution + memory watchdog + import allowlist
     └ --engine parametric skips [4] and [5]: the contract compiles straight to vectors
[5.5] Enrichment          ──> Time series & velocity (--time-series), feature expansion
                              (--expand-features) — both add columns, remove no rows
[6] Validation Pipeline   ──> Deduplication ──> Bounds ──> Rules ──> Z-Score (symmetric cols only)
                          ──> Isolation Forest (opt-in) ──> Correlation Guard (rollback on regression)
[6.5] Controlled Noise    ──> --dirty-rate injects missingness/typos/spikes AFTER validation,
                              because validation would otherwise delete exactly those rows
[7] Output & Checkpoint   ──> CSV / Parquet export + SQLite state checkpoint + Dataset Card
```

---

## Quickstart

### 1. Installation

**Install from PyPI (Recommended for Data Science & Pipelines):**
```bash
pip install ai-data-studio
```

*Or install from source for local development:*
```bash
# Clone the repository
git clone https://github.com/BurakYildizGameDev/ai-data-studio.git
cd ai-data-studio

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

### 2. Configure API Keys (Optional)

API keys can be saved securely in your operating system credential store (Keyring) directly via the GUI Settings tab, or set as environment variables:

```bash
# Windows PowerShell
$env:GEMINI_API_KEY = "AIzaSy..."
# or:
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# Linux / macOS
export GEMINI_API_KEY="AIzaSy..."
```

*Note: If you run [Ollama](https://ollama.com/) locally (`ollama serve`), no API keys or internet connection are required.*

> **If you have Claude Code installed**, the Anthropic provider will fall back to the OAuth
> session in `~/.claude/.credentials.json` when no API key is set — it runs on **your Claude
> Code subscription**, and heavy use can hit rate limits in the Claude Code CLI itself.
> That session also expires after a few hours. For anything beyond a quick trial, run
> `claude setup-token` for a long-lived token or set `ANTHROPIC_API_KEY` explicitly.

### 3. Use it from Python

```python
from ai_data_studio import generate

result = generate("e-commerce orders with churn", rows=50_000, provider="ollama")

result.dataframe.head()            # pandas DataFrame - validated, ready to use
result.report["retention_pct"]     # how much survived the Discriminator
result.schema                      # the SchemaContract the LLM designed
result.code                        # the generator source, reproducible offline
```

Nothing is written to disk unless you ask for it:

```python
result = generate(
    "credit card transactions with fraud patterns",
    rows=200_000,
    provider="gemini",
    output_dir="./out",
    formats=["csv", "parquet"],
    preserve_anomaly_column="is_fraud",   # keep rare ground-truth events
    audit_privacy=True,
)
print(result.output_paths)
```

Track progress, or run the Discriminator on data you already have:

```python
from ai_data_studio import generate, validate

generate("clinical vitals", rows=10_000, provider="ollama",
         on_progress=lambda e: print(f"[{e['step']}/{e['total_steps']}] {e['message']}"))

clean_df, report = validate(my_dataframe, my_schema_dict)
```

#### Zero-Token Parametric Generation (Instant in Jupyter Notebooks)

If you already have a schema or contract definition, compile 100,000+ rows in milliseconds with **zero LLM tokens, 100% offline**:

```python
from ai_data_studio import compile_dataset

# Relational multi-table generation with 0 orphan foreign keys:
spec = {
    "tables": [
        {
            "name": "users",
            "columns": [
                {"name": "user_id", "type": "int", "distribution": "uniform", "min": 1, "max": 10000},
                {"name": "country", "type": "str", "distribution": "categorical", "categories": ["US", "DE", "TR", "GB"]},
            ]
        },
        {
            "name": "transactions",
            "columns": [
                {"name": "tx_id", "type": "int"},
                {"name": "user_id", "type": "int"},
                {"name": "amount", "type": "float", "distribution": "lognormal", "mean": 4.0, "std": 0.8},
                {"name": "is_fraud", "type": "bool"},
            ],
            "relationships": [
                {"parent_table": "users", "parent_key": "user_id", "foreign_key": "user_id"}
            ]
        }
    ]
}

# Returns Dict[str, pd.DataFrame]
tables = compile_dataset(spec, rows=50_000, seed=42)
users_df = tables["users"]
tx_df = tables["transactions"]
```

Or for a single table:
```python
from ai_data_studio import compile_schema

df = compile_schema({
    "columns": [
        {"name": "age", "type": "int", "min": 18, "max": 75},
        {"name": "income", "type": "float", "distribution": "gamma", "mean": 55000, "std": 15000},
        {"name": "credit_score", "type": "int", "distribution": "normal", "mean": 680, "std": 50},
    ],
    "correlations": [
        {"col_a": "age", "col_b": "income", "target_r": 0.55}
    ]
}, rows=10_000, seed=42)
```

`import ai_data_studio` stays cheap (~1 ms) — pandas and the provider SDKs load lazily on first use.

### 4. Launch Desktop Studio (GUI)

```bash
python -m ai_data_studio.main
```

<table>
  <tr>
    <td width="33%"><img src="docs/media/screenshot-pipeline-console.png" alt="Pipeline tab: domain description, model picker and the live colored console log of a finished run"></td>
    <td width="33%"><img src="docs/media/screenshot-validation-charts.png" alt="Charts tab: rows removed per validation stage and the correlation matrix of the clean data"></td>
    <td width="33%"><img src="docs/media/screenshot-job-history.png" alt="History tab: a stored job with its schema, business rules and validation summary"></td>
  </tr>
  <tr>
    <td align="center"><sub><b>Pipeline</b> — describe the data, pick a model, follow all 7 steps in the live console</sub></td>
    <td align="center"><sub><b>Charts</b> — rows removed per validation stage and the correlation matrix</sub></td>
    <td align="center"><sub><b>History</b> — every job keeps its schema, rules and validation summary</sub></td>
  </tr>
</table>

### 5. Run Headless via CLI

Generate 50,000 rows directly from your terminal:

```bash
python -m ai_data_studio.core.orchestrator \
    --domain "mobile game advertising engagement and in-app purchases" \
    --rows 50000 \
    --seed 42 \
    --provider gemini \
    --formats csv,parquet
```

```bash
# Healthcare / Clinical Trials with HIPAA Safe Harbor & NNDR Privacy Audit:
python -m ai_data_studio.core.orchestrator \
    --domain "clinical cardiology patient admission vitals and lab results" \
    --rows 10000 \
    --audit-privacy \
    --provider gemini

# Multi-table run: audit every table, inject fraud into a child table.
python -m ai_data_studio.core.orchestrator \
    --domain "retail banking customers, accounts and card transactions" \
    --relational --rows 20000 \
    --audit-privacy --audit-table all \
    --inject-fraud --fraud-table transactions

# Fraud Detection with preserved extreme anomalies:
python -m ai_data_studio.core.orchestrator \
    --domain "credit card transactions with e-commerce fraud patterns" \
    --rows 20000 \
    --inject-fraud \
    --fraud-rate 0.005 \
    --preserve-anomaly-col is_fraud
```

Use `--help` to inspect all flags (e.g. `--audit-privacy`, `--preserve-anomaly-col`, `--inject-fraud`, `--web-seed`, `--web-query`, `--hf-seed`).

---

## Engines: Skip the Code, Add the Dynamics

The generation engine and the enrichment engines are switches on the same pipeline —
CLI flags, `generate()` keywords, and checkboxes in the desktop studio all set the same
`PipelineConfig` fields.

```bash
# No LLM code generation at all: the schema compiles straight to numpy/pandas vectors.
# One LLM call (the schema), then ~2 ms of generation. Deterministic and reproducible.
python -m ai_data_studio.core.orchestrator \
    --domain "credit card transactions with fraud labels" \
    --rows 50000 --engine parametric --formats csv

# Everything on: parametric generation + temporal dynamics + derived features + noise.
python -m ai_data_studio.core.orchestrator \
    --domain "credit card transactions with fraud labels" \
    --rows 50000 \
    --engine parametric \
    --time-series \
    --expand-features \
    --dirty-rate 0.05

# What can this machine run locally?
python -m ai_data_studio.core.orchestrator --hardware
```

```python
from ai_data_studio import generate

result = generate("credit card transactions with fraud labels",
                  rows=50_000,
                  engine="parametric",     # "llm" (default) | "parametric" | "auto"
                  time_series=True,
                  expand_features=True,
                  dirty_rate=0.05)

result.report["engines"]["generation"]        # 'parametric'
result.report["engines"]["dirty_data"]        # corrupted_rows, breakdown, ordering note
result.dataframe["is_corrupted"].sum()        # the noise survived validation, on purpose
```

| Flag | Engine | What it does |
| --- | --- | --- |
| `--engine llm` (default) | — | LLM writes `generate_data()`, sandbox runs it, self-healing on failure |
| `--engine parametric` | `ParametricEngine` | Compiles the contract directly into vectors. No code generation, no sandbox, ~2 ms. Declared correlations are enforced for numeric pairs, for a binary target driven by a numeric column (`is_fraud`, `churned`) via a latent-normal threshold that preserves the class ratio, and for binary-to-binary pairs. Monotonicity rules join the same copula as rank targets, and business rules are repaired while generating (see below). Works for single-table and relational contracts |
| `--engine auto` | both | Tries the LLM first; if code generation exhausts its retries, falls back to parametric instead of failing the run |
| `--time-series` | `TimeSeriesEngine` | Chronological ordering per entity, circadian activity curve, `seconds_since_last_tx`, burst-velocity anomalies. Needs an entity column that **repeats** — set it with `--ts-entity-col`; the pipeline warns when the column is near-unique, because velocity means nothing at one row per entity |
| `--expand-features` | `FeatureExpander` | Deterministic derived columns: financial ratios, age/credit bands, hour/day/weekend/night flags |
| `--dirty-rate 0.05` | `DirtyDataEngine` | MCAR missingness, QWERTY-adjacency typos, casing/whitespace jitter, outlier spikes, plus `is_corrupted` / `corruption_details` audit columns |
| `--hardware` | `HardwareProfiler` | Prints CPU/RAM/GPU tier and the local Ollama model that fits it, then exits |

**Two ordering rules the pipeline enforces, and why:**

1. **Time series and feature expansion run *before* validation.** They only add columns,
   and the validator normalizes column order as "schema columns, then extras" — so the
   new columns pass through untouched while the schema columns still get checked.
2. **Controlled noise runs *after* validation.** Injected before it, the schema-bounds
   check would delete the outlier spikes, the category check would delete the typos, and
   the null check would delete the missing values — the corruption would vanish silently.
   The report records this: `engines.dirty_data.column_stats_precede_corruption`.

Enrichment applies to the **root table** in relational runs unless you pick another one
with `--ts-table`, `--expand-table` or `--dirty-table`. `--engine parametric` also handles
`--relational`: tables are compiled in topological order, child foreign keys are drawn from
the parent's generated primary keys with the declared cardinality, so no orphans are emitted.

**Small local models.** Measured on `qwen2.5-coder:1.5b` (about 1 GB, runs on CPU-only
machines), 20,000 rows, three prompts (e-commerce orders, loan applications, mobile game
players), repeated three times each:

| Engine | Runs finished | Correlations met | Monotonicity met | Lowest rows kept | Avg. time |
| --- | --- | --- | --- | --- | --- |
| `parametric` | 9 / 9 | 25 / 26 | 19 / 20 | 99.2% | 14 s |
| `auto` | 3 / 3 (all fell back to parametric) | 8 / 8 | 3 / 4 | 99.1% | 30–240 s |
| `llm` | 0 / 3 | — | — | — | ~30 s |

A 1.5B model writes a usable schema but not a working generator: every `llm` run failed, each
time with a different class of error. Pick `parametric` for small models — `auto` gets the same
data but first spends three code-generation rounds that cannot succeed. The desktop studio
switches to `parametric` when you pick a small Ollama model (you can switch back), and the CLI
warns when `--engine llm` or `--engine auto` is used with one. Reasoning models such as `deepseek-r1` spend most of their output budget thinking;
the client gives them a larger budget and retries once when the answer is cut off.

**What the parametric engine does with the contract's rules:**

- **Correlations and monotonicity** are solved together in one Gaussian copula that only
  reorders already-generated values. Pairs the contract says nothing about are filled with
  the value their chain implies (`a~b`, `b~c` ⇒ `a~c`) instead of zero; a zero there made the
  target matrix inconsistent and the repair step weakened the whole chain (measured: a
  four-column chain with targets of 0.88 came out at 0.61–0.73; now every link lands on target).
  A monotonicity rule becomes a 0.80 rank-correlation target (0.35 for a binary column), which
  clears the validator's binned and pairwise compliance checks: 25 of 25 rules across five seeds.
- **Business rules** are repaired while generating instead of being left to the validator:
  bounds tighter than the column range (`sessions_per_week <= 7`), scaled or summed sides
  (`loan_amount <= annual_income * 0.5`, `total >= basket + shipping`), `and`-joined bounds and
  derived columns (`ratio == loan / income`). A violating value is mirrored across the bound, so
  the column does not pile up at the limit. Rules with `or`/`not` are left to the validator.
  Repair runs once *before* the copula — a constant bound survives reordering, and repairing it
  afterwards mirrored half the rows and erased the correlation (measured: target 0.5, result
  −0.008) — and once after it for column-to-column rules. Datetime columns take their range
  from the column `description` and ordering rules between dates are repaired the same way.
- **The validator flags a suspicious rule.** When a single rule removes more than half of the
  rows on its own, it is still applied, but the console and the report
  (`business_rules[].suspicious`) say that it probably contradicts the column ranges. A rule
  that *no* row satisfies is skipped instead of emptying the dataset.

---

## From a Project, Not a Schema

Every other mode here asks you to describe the **data** you want. This one asks you to
describe the **problem**. The planner decides what data that problem needs — then designs
it, generates it, and validates it in the same run.

```bash
python -m ai_data_studio.core.orchestrator \
    --project "predict which customers stop buying in the next 90 days, so the
               retention team can target them with offers" \
    --rows 5000 --provider anthropic --formats csv
```

```python
from ai_data_studio import generate

result = generate(project="predict which subscribers churn next month", rows=5_000)

result.plan.target.label()                        # 'customers.churned'
result.plan.positive_class_ratio                  # 0.18
[e.column for e in result.plan.excluded_leakage]  # ['cancellation_reason', ...]
result.plan.split.kind                            # 'temporal'
result.tables["customers"].head()
```

### Four decisions that make data trainable

A column list is not a training set. The plan commits to all four, and each one is
checked for internal consistency before a single row is generated:

| Decision | What the plan produces | What is enforced |
|---|---|---|
| **Target variable** | The column a model would predict | Must exist as a real column in the contract |
| **Class balance** | A realistic positive-class rate — fraud ~0.1–2%, churn ~5–30%, not a convenient 50/50 | Drives the bool column's `target_ratio`, so the generated data actually has that rate; a plan that contradicts the schema is rejected |
| **Leakage** | Columns deliberately left **out**, each with a reason | A column cannot be both "excluded as leakage" and defined in the contract — that contradiction fails the run |
| **Train/test split** | `temporal`, `group`, or `random`, with the column it hinges on | A temporal split must name a real `datetime` column; a group split must name a column that exists |

Leakage is the one most designs get wrong, so it is a required field rather than an
optional nicety: the planner must state what it considered and left out
(`cancellation_reason` is only filled in *after* a customer churns), or explicitly return
an empty list.

### What you can check

The plan itself is a judgement — there is no ground truth to compare it against. What can
be verified is whether it is self-consistent and whether the data honours it, and both are:
the run prints every decision to the console, writes the plan next to the data as
`job_<id>_<domain>_plan.json`, and stores it in the report under `project_plan`.

```
Plan hazır: gorev: binary_classification | hedef: customers.churned | pozitif sinif: %18.0
  -> Hedef değişken: customers.churned
  -> Sınıf dengesi: pozitif sınıf %18.0
  -> Sızıntı yaratacağı için ayıklanan kolonlar (2 adet):
  • cancellation_reason - yalnızca müşteri ayrıldıktan sonra doldurulur
  • refund_issued_at - churn sonrası olay; hedefi doğrudan ele verir
  -> Train/test ayrımı: temporal (customers.signup_at) - geleceği tahmin ediyoruz
```

`--project` replaces `--domain`; the two cannot be combined. The planner decides how many
tables the problem needs (`--max-tables` caps it), so `--relational` does not apply here —
a one-table plan is a legitimate answer when the problem has one entity.


---

## Relational (Multi-Table) Datasets

Most synthetic data tools hand you one wide, denormalised table. Real systems are
normalised: customers own subscriptions, subscriptions raise invoices, invoices
receive payments. Pass `--relational` (CLI) or `relational=True` (Python) and the
LLM designs a **Dataset Contract** instead of a single Schema Contract: several
tables plus the foreign keys and cardinalities that connect them.

```bash
python -m ai_data_studio.core.orchestrator \
    --relational \
    --domain "SaaS billing: customers, subscription plans, invoices, payments" \
    --rows 5000 \
    --max-tables 5 \
    --provider anthropic \
    --formats csv
```

```python
from ai_data_studio import generate

result = generate("SaaS billing: customers, subscriptions, invoices", rows=5_000,
                  relational=True, provider="anthropic")

sorted(result.tables)                     # ['customers', 'invoices', 'subscriptions']
result.tables["invoices"].head()          # any table by name
result.dataframe                          # still the ROOT table - existing code keeps working
result.contract.relationships             # the FK graph the LLM designed
result.report["relational"]["pass"]       # did integrity hold?
```

### What is guaranteed

Generation walks the contract in topological order, so a child table draws its
foreign keys from the parent's **actual** key array rather than inventing an ID
range. After generation, three checks run and are recorded in
`report["relational"]`:

| Check | Meaning | On failure |
|---|---|---|
| **Primary keys** | Every `primary_key` is unique and non-null | Reported |
| **Foreign keys** | Every child FK resolves to a live parent row | Orphans removed (or reported with `--no-repair-orphans`) |
| **Cardinality** | Children per parent match the contract's `mean_per_parent` (±50%) | Reported as a deviation |

### Order matters

Per-table cleaning runs **first**, relational repair **second** — and never the
other way around. The Discriminator removes rows table by table; when it drops a
parent row, that parent's children become orphans. Repairing relationships before
single-table cleaning would therefore leave dangling keys behind. The pipeline
enforces this order, and `--no-repair-orphans` turns the check into a **CI gate**:
orphaned foreign keys or duplicate primary keys make the process exit with code
`3` instead of silently deleting rows.

### Output layout

Each table is written separately, alongside a `manifest.json` that records which
file holds which table, the relationship graph, and the integrity results:

```
job_42_saas_billing_customers.csv
job_42_saas_billing_invoices.csv
job_42_saas_billing_schema.json      # the full Dataset Contract
job_42_saas_billing_manifest.json    # table -> file map, relationships, integrity
```

`result.output_paths` keys are namespaced per table in relational mode
(`csv:customers`, `csv:invoices`, …) plus `manifest`, `schema`, `code`, `report`.

### Choosing a provider

The relational schema prompt is long and the generated program has to build every table in
one pass, so this path asks more of the model than single-table generation.

- **API-key backends** (Anthropic, or Gemini via an AI Studio key with
  `--gemini-backend aistudio`) are the recommended choice, and the only ones that reliably
  handle four or more tables.
- **A capable local model works for small schemas.** A two-table contract generated and
  validated cleanly on a local `qwen2.5-coder:14b` (zero orphan keys, cardinality 2.93
  against a contracted 3.0), taking one self-healing round on the code step. Larger
  schemas exceeded it.
- **The Antigravity CLI backend (`--gemini-backend cli`) is not practical here.** It
  reloads its agent context on every call and **timed out at 900 s** on the
  code-generation step of a four-table run. It remains fine for single-table work.
  The cost is startup, not inference: on a measured call the total was **204 s while
  the model step itself took 3.6 s**, and a 40-character prompt still billed ~13.4k
  input tokens for the agent's own context. Picking a smaller model does not help.
  The console reports the wait (a start notice plus a heartbeat every 30 s) so a long
  call does not look frozen.

### Scope

`--rows` applies to the **root table** only; child table sizes follow from the
cardinalities in the contract.

The modules around the pipeline now take a table of their own:

| Flag | Default | What it does |
| --- | --- | --- |
| `--audit-table <name\|all>` | root table | Runs the privacy / HIPAA audit per table and writes one `job_<id>_<table>_privacy_report.md` for each. A child table has no reference data, so its report says the memorisation risk was **not measured** rather than leaving an empty epsilon to read as "fine". An unknown table name is rejected instead of silently auditing nothing |
| `--fraud-table <name>` | root table | Injects the fraud scenario into that table. The anomaly-preservation exemption follows the injection, so injected rows survive cleaning wherever they were put — measured with a custom label column: 0 survivors before, 69 after |

The HuggingFace dataset card lists every table with its primary key and row count plus
the relationship schema, and states which table the repository actually holds. The
desktop chart panel gets a table selector. Enrichment engines (`--time-series`,
`--expand-features`, `--dirty-rate`) still apply to the root table.

Single-table runs are untouched: same flat report shape, same file names, same
behaviour as before.


---

## Schema Contract Specification

The Schema Contract is the single source of truth connecting code generation and validation:

```json
{
  "domain": "mobile_game_ad_engagement",
  "row_count_target": 50000,
  "random_seed": 42,
  "columns": [
    {
      "name": "user_age",
      "type": "int",
      "min": 13,
      "max": 65,
      "distribution": "normal",
      "mean": 28,
      "std": 8
    },
    {
      "name": "ad_duration_s",
      "type": "int",
      "min": 5,
      "max": 60,
      "distribution": "uniform"
    },
    {
      "name": "watch_time_s",
      "type": "float",
      "min": 0.0,
      "max": 60.0
    },
    {
      "name": "is_clicked",
      "type": "bool",
      "target_ratio": 0.12
    }
  ],
  "business_rules": [
    "watch_time_s <= ad_duration_s",
    "watch_time_s >= 0.0"
  ],
  "correlations": [
    {
      "columns": ["ad_duration_s", "watch_time_s"],
      "expected_sign": "positive",
      "min_r": 0.35
    }
  ]
}
```

### Tolerant parsing

Local models often return a contract that is right in substance but wrong in form, and every
rejection costs a full LLM round. Measured on `qwen2.5-coder:14b`, nine schema answers out of
nine were rejected on the first try before this was added. The parser now fixes mistakes whose
meaning is unambiguous and records a warning that shows up in the console; anything ambiguous
is still rejected and fed back to the model:

| The model returned | Accepted as |
|---|---|
| `// comments`, `# comments`, trailing commas, `True` / `None` | strict JSON |
| a date string as `min` / `max` of a `datetime` column | the range moved into `description` |
| an invented distribution such as `beta` or `weibull` | `distribution` dropped, values stay within `min`/`max` |
| `bernoulli` / `binomial` on a `bool` column | dropped silently (`target_ratio` already defines it) |
| aliases such as `gaussian`, `log-normal` | `normal`, `lognormal` |
| `normal` without `mean` | midpoint of `min`/`max` |
| SQL-style rules: `x IS NULL`, `AND`, `a = b` | `x != x`, `and`, `a == b` |
| a rule naming a column that is not in the contract (small models copy the prompt's example) | rule dropped with a warning |
| a rule that is not an expression (`defaulted is boolean`, `a -> b`) | rule dropped with a warning |
| a numeric or bool column compared with text (`churned in ['True', 'False']`) | rule dropped — it never matches and would delete every row |
| a condition that pins a two-class bool column (`loan_default == False`) | that condition removed — it would delete the whole positive class |
| `mean` on a `bool` column | used as `target_ratio` |
| tweedie `p_index` of exactly `1` or `2` | dropped (it must lie strictly between them) |
| `min_r` above what a bool column with that True ratio can reach (≈0.47 at a 5% ratio) | lowered to 80% of that ceiling, with a warning |

---

## Sandbox Execution

Generated code runs in a separate process with several layers of containment:

1. **AST static import allowlist** — parses the generated module before it runs and rejects
   imports outside the allowlist plus hazardous builtins (`eval`, `exec`, `open`,
   `__import__`, `__subclasses__`). A rejection is fed back to the self-healing loop like any
   other failure: the code never ran, so asking the model to rewrite it is safe.
2. **Isolated subprocess** — generated code never executes in the host process or the UI thread.
3. **Execution timeout** — 90 seconds by default; runaway processes are terminated.
4. **Memory watchdog (`psutil`)** — samples the process tree's RSS and kills it past the limit
   (2 GB by default).

### What this is not

**These layers are a guardrail against runaway or accidental code, not a security boundary.**
Do not treat them as a sandbox for untrusted input. The static allowlist checks import
statements, so it cannot stop a module reached through an allowed one — for example
`pd.io.common.os.system(...)` passes the check today. The watchdog samples memory rather than
capping it, so a fast-allocating program can overshoot the limit between samples before it is
killed.

That matters most with `--web-seed`, where the chain is *web page → LLM prompt → executed
code*: content you do not control influences code that then runs on your machine. Treat every
run as executing code you would be willing to run yourself. If you need a real boundary, run
the whole application inside a container or VM.

---

## Testing

Run the automated test suite (680 tests, 100% offline using mock LLM harnesses):

```bash
# Run all unit and integration tests
python -m unittest discover -s ai_data_studio/tests -t .

# Run static architecture rules test (AST validation)
python -m unittest ai_data_studio.tests.test_gui.TestArchitectureRules
```

---

## Building Standalone Windows Executable (.exe)

Package the entire studio into a standalone portable `.exe`:

```bash
# Build standalone single-file binary
python build_exe.py

# Build directory bundle (faster launch time)
python build_exe.py --onedir

# Build with debug console
python build_exe.py --console
```

The compiled binary will be placed in the `dist/` directory.

---

## Directory Structure

```
ai_data_studio/
├── __init__.py                 # Lazy public API surface (PEP 562) + __init__.pyi stub
├── api.py                      # generate() / validate() - the Python library entry point
├── main.py                     # Desktop app entry point
├── config.py                   # Centralized configuration, keyring, paths, UTF-8 I/O
├── core/
│   ├── schema_contract.py      # Strict Schema Contract model & parser (one table)
│   ├── dataset_contract.py     # Dataset Contract: tables + foreign keys + topological order
│   ├── project_planner.py      # Project description -> target, class balance, leakage, split
│   ├── generator.py            # AST sandbox execution & self-healing engine
│   ├── parametric_engine.py    # --engine parametric: contract -> vectors, no LLM code
│   ├── time_series_engine.py   # --time-series: chronology, circadian curve, velocity
│   ├── dirty_data_engine.py    # --dirty-rate: controlled noise + audit trail columns
│   ├── feature_expander.py     # --expand-features: deterministic derived columns
│   ├── hardware_profiler.py    # --hardware: CPU/RAM/GPU tier -> local model advice
│   ├── validator.py            # Multi-stage statistical & ML discriminator
│   ├── relational_validator.py # Primary/foreign key, cardinality & orphan repair
│   ├── privacy_auditor.py      # DCR / NNDR / HIPAA Safe Harbor audit
│   ├── monotonicity_validator.py  # Actuarial monotonicity rules
│   ├── fraud_injector.py       # Parametric fraud / rare-event injection
│   ├── state_manager.py        # SQLite checkpoints & job persistence
│   └── orchestrator.py         # 7-step pipeline controller & CLI
├── services/
│   ├── llm_base.py             # Base LLM client interface & prompt engineering
│   ├── relational_prompts.py   # Multi-table schema & code prompt templates
│   ├── planner_prompts.py      # Project-to-dataset planning prompt
│   ├── prompt_blocks.py        # Teaching blocks shared by every prompt (no drift)
│   ├── cloud_llm_service.py    # Anthropic (Claude) & Google (Gemini AI Studio)
│   ├── agy_service.py          # Antigravity CLI session integration
│   ├── ollama_service.py       # REST-based local Ollama client
│   ├── web_collector.py        # DuckDuckGo & URL web extraction
│   └── hf_service.py           # HuggingFace datasets & push-to-hub
├── gui/
│   ├── app_window.py           # Main window, event queue loop & thread bridge
│   ├── components/             # Console, charts, progress badges, auth dialogs
│   └── views/                  # Pipeline, settings, and job history views
└── tests/                      # Full test suite (512 unit & integration tests)
```

---

---

## Language

The desktop studio and CLI ship with full support for **7 languages**:
- 🇬🇧 **English (`en`)** — Default
- 🇹🇷 **Türkçe (`tr`)**
- 🇩🇪 **Deutsch (`de`)**
- 🇫🇷 **Français (`fr`)**
- 🇷🇺 **Русский (`ru`)**
- 🇨🇳 **简体中文 (`zh`)**
- 🇯🇵 **日本語 (`ja`)**

Pick your preferred language in *Settings → Defaults → Language*; the choice is saved to `settings.json` and applies on launch.

```python
from ai_data_studio import i18n

i18n.set_language("de")
i18n.t("settings.keys.title")   # "API-Schlüssel"
```

### Multilingual Prompts & ASCII Normalization

You can write your dataset domains or problem descriptions in **any language** (Turkish, Chinese, German, Japanese, Russian, etc.). The prompt compiler enforces a strict constraint:
> **All generated column names and contract keys MUST be pure ASCII snake_case English identifiers** (e.g. `transaction_amount`, `user_age`, `is_fraud`), regardless of the user's input language.

This prevents Unicode encoding bugs in pandas / database engines while letting users express complex business domains in their native tongue.

Two things are deliberately **not** translated:

- **LLM prompts** (`services/prompt_blocks.py`, `planner_prompts.py`,
  `relational_prompts.py`, `llm_base.py`) and the self-healing feedback built in
  `core/generator.py` (schema mismatches, repair hints). They stay in English: the data a
  model generates must not change because a user switched the interface language. A test
  asserts the prompt modules never call `t()`.
- **Log records.** A fixed log language keeps the same failure searchable; otherwise
  one error produces two different lines depending on who ran it.

## Further Reading

- [`docs/ENGINEERING_REPORT_TR.md`](docs/ENGINEERING_REPORT_TR.md) — a long-form
  engineering report (in Turkish) covering the architecture of the three data engines,
  the forensic bug write-ups behind several fixes, and a head-to-head benchmark of
  Gemini, local Ollama and Claude on the same fraud-detection dataset.

---

## License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.
