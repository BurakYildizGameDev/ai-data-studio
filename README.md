# AI Synthetic Data Studio & Validator

<p align="center">
  <img src="ai_data_studio/assets/logo.png" width="96" height="96" alt="AI Synthetic Data Studio logo">
</p>

<p align="center">
  <strong>High-performance, privacy-first synthetic data generation and multi-stage statistical validation studio.</strong>
</p>

<p align="center">
  <a href="https://github.com/BurakYildizGameDev/ai-data-studio/actions/workflows/tests.yml"><img src="https://github.com/BurakYildizGameDev/ai-data-studio/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg" alt="Platform">
  <img src="https://img.shields.io/badge/Architecture-Generator--Discriminator-orange.svg" alt="Architecture">
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
  - **Anthropic Claude:** Claude 3.5 Sonnet, Haiku, and Opus via official API.
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
- **Self-Healing Code Loop:** If generated code fails execution or violates structural schema bounds, tracebacks and AST hints are fed back to the LLM to auto-correct the code (up to 3 retries).
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
[6] Validation Pipeline   ──> Deduplication ──> Bounds ──> Rules ──> Z-Score (symmetric cols only)
                          ──> Isolation Forest (opt-in) ──> Correlation Guard (rollback on regression)
[7] Output & Checkpoint   ──> CSV / Parquet export + SQLite state checkpoint + Dataset Card
```

---

## Quickstart

### 1. Installation

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

`import ai_data_studio` stays cheap (~1 ms) — pandas and the provider SDKs load lazily on first use.

### 4. Launch Desktop Studio (GUI)

```bash
python -m ai_data_studio.main
```

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
cardinalities in the contract. Fraud injection, the privacy audit, the HuggingFace
dataset card, and the GUI chart panel apply to the root table in relational mode.
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

---

## Sandbox Execution

Generated code runs in a separate process with several layers of containment:

1. **AST static import allowlist** — parses the generated module before it runs and rejects
   imports outside the allowlist plus hazardous builtins (`eval`, `exec`, `open`,
   `__import__`, `__subclasses__`).
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

Run the automated test suite (360+ tests, 100% offline using mock LLM harnesses):

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
└── tests/                      # Full test suite (360+ unit & integration tests)
```

---

## License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.
