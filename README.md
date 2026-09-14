# AI Synthetic Data Studio & Validator

<p align="center">
  <img src="ai_data_studio/assets/logo.png" width="96" height="96" alt="AI Synthetic Data Studio logo">
</p>

<p align="center">
  <strong>Describe a dataset in plain language. A small local model writes the contract, the engine generates the rows, and a validator checks that the data keeps the contract — no API key required.</strong>
</p>

<p align="center">
  <a href="https://github.com/BurakYildizGameDev/ai-data-studio/actions/workflows/ci.yml"><img src="https://github.com/BurakYildizGameDev/ai-data-studio/actions/workflows/ci.yml/badge.svg" alt="CI Status"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg" alt="Python 3.10 | 3.11 | 3.12"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/code%20style-ruff-000000.svg" alt="Code Style: Ruff"></a>
</p>

<p align="center">
  <img src="docs/media/demo.gif" width="900" alt="Desktop studio demo: describing an e-commerce dataset, running the 7-step pipeline and reviewing the result, validation charts and job history">
  <br>
  <sub>15-second tour of the desktop studio — local Ollama <code>qwen2.5-coder:14b</code>, parametric engine, 20,000 rows.
  Only the LLM's schema step is sped up; everything else plays in real time. A run on the 1.5B model is
  <a href="#first-dataset-in-two-minutes">measured below</a>. (<a href="docs/media/demo.mp4">MP4</a>)</sub>
</p>

---

## How it works

Asking an LLM to write rows one token at a time is slow, costs more with every row, and gives
you nothing to check the result against. This project asks the model for something much
smaller: a **Schema Contract** — a JSON description of the columns, distributions, business
rules, correlations and monotonic relationships the data should have.

```
description ──LLM──> Schema Contract ──engine──> raw rows ──validator──> clean rows + report
                          (JSON)        parametric compiler, or an
                                        LLM-written generator program
```

1. **Contract.** One LLM call — local Ollama, Google Gemini or Anthropic Claude — turns your
   description into a contract. Formatting mistakes whose meaning is clear are repaired;
   ambiguous ones are sent back to the model.
2. **Generate.** The parametric engine compiles the contract into NumPy/pandas vectors: the
   declared distributions, a Gaussian copula for correlations and monotonic trends, and
   business rules repaired during generation. Alternatively (`--engine llm`) the model writes
   a generator program that runs in a separate process.
3. **Validate.** The validator removes duplicates, out-of-range values and rule violations,
   filters outliers without cutting heavy tails, and then *measures* whether each declared
   correlation and monotonic trend actually holds.
4. **Export.** CSV, Parquet or JSON, plus the contract, a JSON report, a script that
   regenerates the data offline and, optionally, a Hugging Face dataset card.

Because the model only writes the contract, a 1.5B model on an ordinary laptop is enough, and
the number of rows does not change the number of LLM calls.

> **The validator checks the data against the contract, not against the real world.** A small
> model can declare a relationship that runs the wrong way for your domain. Read the generated
> `*_schema.json` before you rely on the data.

---

## First dataset in two minutes

### With a small local model

Install from source ([below](#installation)) and [Ollama](https://ollama.com/), then:

```bash
ollama pull qwen2.5-coder:1.5b      # about 1 GB; runs without a GPU

python -m ai_data_studio.core.orchestrator \
    --domain "loan applications with income, credit score and default flag" \
    --provider ollama --model qwen2.5-coder:1.5b \
    --engine parametric --rows 20000 --formats csv
```

On the development machine (Intel i9-13900HX, RTX 5070 Ti) this run took 16 seconds end to
end: one LLM call of 1,814 tokens, 19,636 of 20,000 rows kept, 3 of 3 declared correlations
and 1 of 1 monotonicity rule met. On a machine without a GPU the LLM call takes longer;
generation and validation do not use the GPU.

That run is also a good example of the warning above: the model declared that defaults
*rise* with income. The data honours the contract; the contract is wrong for the domain.

Over nine runs on three different prompts, `qwen2.5-coder:1.5b` with the parametric engine
finished every run and met 25 of 26 declared correlations — see
[small local models](docs/engines.md#small-local-models).

### Without any model

If you already know what the data should look like, write the contract yourself. No model is
involved and nothing leaves your machine:

```python
from ai_data_studio import compile_schema, validate

contract = {
    "domain": "loan_applications",
    "columns": [
        {"name": "age", "type": "int", "min": 18, "max": 75,
         "distribution": "normal", "mean": 40, "std": 12},
        {"name": "income", "type": "float", "min": 8000, "max": 250000,
         "distribution": "lognormal", "mean": 52000},
        {"name": "loan_amount", "type": "float", "min": 1000, "max": 100000,
         "distribution": "lognormal", "mean": 15000},
        {"name": "credit_score", "type": "int", "min": 300, "max": 850,
         "distribution": "normal", "mean": 680, "std": 60},
        {"name": "defaulted", "type": "bool", "target_ratio": 0.15},
    ],
    "business_rules": ["loan_amount <= income * 0.5"],
    "correlations": [
        {"columns": ["age", "income"], "expected_sign": "positive", "min_r": 0.4},
    ],
    "monotonicity_rules": [
        {"column_x": "credit_score", "column_y": "defaulted", "direction": "decreasing"},
    ],
}

df = compile_schema(contract, rows=100_000, seed=42)
clean, report = validate(df, contract)

report["retention_pct"]                                         # 99.85 - share of rows kept
[(c["pair"], c["actual_r"], c["pass"]) for c in report["correlations"]]
                                                                # [(['age', 'income'], 0.45, True)]
report["monotonicity"]["passed_rules"]                          # 1 (of 1)
```

The whole script, imports included, runs in about a second.

---

## Installation

The package is not on PyPI yet, so install it from source. Python 3.10, 3.11 or 3.12.

```bash
git clone https://github.com/BurakYildizGameDev/ai-data-studio.git
cd ai-data-studio

python -m venv .venv
# Windows:        .venv\Scripts\activate
# Linux / macOS:  source .venv/bin/activate

pip install -e .            # library, command line and desktop studio
pip install -e ".[dev]"     # adds pytest, ruff and PyInstaller for development
```

## LLM providers

| Provider | Authentication | Notes |
| --- | --- | --- |
| **Ollama** (local) | none | Runs offline. `--hardware` suggests a model size for your machine |
| **Google Gemini** | AI Studio key (`GEMINI_API_KEY`), or an Antigravity CLI login | The CLI login needs no key, but every call spends about 3–4 minutes starting the CLI; use a key for anything beyond a small single-table run |
| **Anthropic Claude** | API key (`ANTHROPIC_API_KEY`), or an existing Claude Code login | The Claude Code login runs on your subscription and expires after a few hours; `claude setup-token` creates a long-lived token |

Keys can also be saved to the operating system's credential store from the desktop studio's
Settings tab. `python -m ai_data_studio.core.orchestrator --check-auth` prints which
credentials each provider can use.

---

## Three ways in

### Python

```python
from ai_data_studio import generate

result = generate("e-commerce orders with churn", rows=50_000,
                  provider="ollama", model="qwen2.5-coder:1.5b", engine="parametric")

result.dataframe.head()            # pandas DataFrame, already validated
result.report["retention_pct"]     # share of rows the validator kept
result.schema                      # the contract the model wrote
result.code                        # a script that regenerates the data offline
```

Nothing is written to disk unless you ask for it:

```python
result = generate(
    "credit card transactions with fraud patterns",
    rows=200_000,
    provider="gemini",
    engine="parametric",
    output_dir="./out",
    formats=["csv", "parquet"],
    preserve_anomaly_column="is_fraud",   # rare positives are exempt from outlier filters
    audit_privacy=True,
)
print(result.output_paths)
```

Follow progress, or run only the validator on data you already have:

```python
from ai_data_studio import generate, validate

generate("clinical vitals", rows=10_000,
         provider="ollama", model="qwen2.5-coder:1.5b", engine="parametric",
         on_progress=lambda e: print(f"[{e['step']}/{e['total_steps']}] {e['message']}"))

clean_df, report = validate(my_dataframe, my_contract_dict)
```

Multi-table data without a model: `compile_dataset` draws every child foreign key from the
keys it generated for the parent table.

```python
from ai_data_studio import compile_dataset

spec = {
    "root_table": "customers",
    "tables": [
        {"name": "customers", "primary_key": "customer_id", "columns": [
            {"name": "customer_id", "type": "int"},
            {"name": "country", "type": "category", "categories": ["US", "DE", "TR", "GB"]},
            {"name": "age", "type": "int", "min": 18, "max": 80,
             "distribution": "normal", "mean": 38, "std": 12},
        ]},
        {"name": "orders", "primary_key": "order_id", "foreign_keys": ["customer_id"], "columns": [
            {"name": "order_id", "type": "int"},
            {"name": "customer_id", "type": "int"},
            {"name": "amount", "type": "float", "min": 1, "max": 5000,
             "distribution": "lognormal", "mean": 60},
            {"name": "is_fraud", "type": "bool", "target_ratio": 0.02},
        ]},
    ],
    "relationships": [
        {"parent_table": "customers", "parent_key": "customer_id",
         "child_table": "orders", "child_key": "customer_id", "mean_per_parent": 4},
    ],
}

tables = compile_dataset(spec, rows=10_000, seed=42)   # rows = size of the root table
tables["customers"], tables["orders"]                  # 10,000 customers, ~40,000 orders, 0 orphan keys
```

`import ai_data_studio` takes under a millisecond; pandas and the provider SDKs load on first
use. The package ships type information (`py.typed`).

### Desktop studio

```bash
python -m ai_data_studio.main      # or, after installing: ai-data-studio
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

The studio switches to the parametric engine when you pick an Ollama model of 3B parameters or
less (you can switch back), and preselects the model `--hardware` recommends when it is
installed.

### Command line

```bash
python -m ai_data_studio.core.orchestrator \
    --domain "mobile game advertising engagement and in-app purchases" \
    --rows 50000 --seed 42 \
    --provider gemini --engine parametric \
    --formats csv,parquet
```

Frequently used flags (`--help` lists all of them):

| Flag | What it does |
| --- | --- |
| `--provider`, `--model` | `anthropic` (default), `gemini` or `ollama`, and a provider-specific model name |
| `--engine` | `llm` (default), `parametric` or `auto` — see [Engines](#engines) |
| `--relational`, `--max-tables` | Multi-table dataset with foreign keys — see [docs/relational.md](docs/relational.md) |
| `--project` | Describe the machine-learning problem instead of the data — see [docs/project-planner.md](docs/project-planner.md) |
| `--time-series`, `--expand-features`, `--dirty-rate` | Temporal dynamics, derived columns, controlled noise (applied after validation) |
| `--inject-fraud`, `--fraud-rate`, `--preserve-anomaly-col` | Fraud scenarios, and keeping rare positives through the outlier filters |
| `--contamination` | Turns on Isolation Forest filtering at that rate (off by default) |
| `--audit-privacy`, `--audit-table` | Heuristic privacy checks — see [Privacy checks](#privacy-checks) |
| `--web-seed`, `--web-query`, `--hf-seed` | Reference data from a web search or URL, or from a Hugging Face dataset |
| `--push-to-hub` | Uploads the clean data to a Hugging Face repository |
| `--no-repair-orphans` | CI gate for relational runs: exit code 3 instead of deleting orphan foreign keys |
| `--agentic` | Experimental: four LLM roles (domain analyst, statistician, critic, schema engineer) design the contract over several rounds. More LLM calls; not benchmarked yet |
| `--hardware`, `--check-auth` | Print the hardware tier or the credential status, then exit |

---

## Engines

| Engine | When to use it |
| --- | --- |
| `parametric` | The choice for small local models. One LLM call for the contract, then vectorised generation — 100,000 rows × 10 columns in 0.13 s, 1,000,000 rows × 10 columns in 1.6 s on the development machine |
| `llm` | When a column needs logic a contract cannot express. The model writes a generator program; failures are fed back for up to three repair rounds. Needs a capable model — `qwen2.5-coder:1.5b` failed all of its runs |
| `auto` | Tries `llm` and falls back to `parametric` when code generation runs out of attempts |

The command line and the Python API default to `llm`. Enrichment engines, the ordering rules
between them, the small-model measurements and known limits are in
[docs/engines.md](docs/engines.md).

## Validation

Every run passes through the same stages, and the report records what each one removed:

1. **Duplicates** are removed.
2. **Schema bounds** — `min`/`max` and non-null constraints.
3. **Business rules** — pandas `eval` expressions. A rule that removes more than half of the
   rows on its own is flagged as suspicious; a rule that no row satisfies is skipped instead
   of emptying the dataset.
4. **Z-score outliers** (`|z| > 3`) — only on roughly symmetric columns. Heavy-tailed and
   zero-inflated columns (`gamma`, `lognormal`, `pareto`, `zip`, `poisson`, …) are skipped,
   because a fixed cut would remove the tail that carries the signal.
5. **Isolation Forest** — opt-in with `--contamination`. Off by default: a fixed contamination
   rate deletes that share of rows even from clean data.
6. **Correlation guard** — declared correlations are measured before and after outlier
   removal. If cleaning broke one that held before, the outlier stages are rolled back and the
   regression is reported (`--no-correlation-guard` turns this off).
7. **Checks** — every declared correlation against its `min_r`; every monotonicity rule with
   binned means, sampled row pairs and the Spearman direction (plus Weight of Evidence and
   Information Value for binary outcomes); and Kolmogorov–Smirnov tests when reference data is
   supplied.

A check that fails is reported as failed. The validator does not alter values to make a check
pass.

## Privacy checks

`--audit-privacy` writes a `*_privacy_report.md` next to the data. It runs three **heuristic**
checks that can point you at problems. They are not a differential-privacy guarantee and not a
HIPAA or GDPR compliance certification.

| Check | What it does | Limits |
| --- | --- | --- |
| **Memorisation (DCR / NNDR)** | Needs reference data (`--web-seed`, `--hf-seed`). On a sample of up to 2,000 rows, using the standardised numeric columns both datasets share, it measures each synthetic row's distance to the closest reference row (DCR) and the ratio of the closest to the second-closest distance (NNDR). Identical rows or low ratios are reported as possible copies | Numeric columns only. The thresholds are fixed: with one or two numeric columns even independent data is flagged — in two dimensions about 4% of rows fall below the NNDR cut-off by chance |
| **Distribution divergence score** | The 95th percentile of the absolute log ratio between synthetic and reference histogram bins (20 bins, up to five shared numeric columns) | A similarity heuristic. The report field is still called `empirical_epsilon`; it is not a differential-privacy ε |
| **Identifier column-name scan** | Matches column **names** against patterns for the 18 HIPAA Safe Harbor identifier categories and counts ages over 89 | Cell values are never inspected: an identifier stored under an unrelated name is missed, and a harmless name that contains a pattern (`mobile_sessions`) is flagged |

Without reference data the memorisation check is reported as **not measured**. The helpers
`shift_clinical_dates` (moves all dates of one patient by the same random offset) and
`cap_hipaa_age` (groups ages over 89 as 90) are available in
`ai_data_studio.core.privacy_auditor` for your own preprocessing; the pipeline does not call
them.

## Domain features

- **Rare positives survive cleaning.** `--preserve-anomaly-col is_fraud` exempts those rows
  from the Z-score and Isolation Forest filters.
- **Fraud scenarios.** `--inject-fraud` applies high-amount bursts, impossible velocity,
  off-hours activity and credential stuffing at `--fraud-rate`, each where the matching
  columns exist.
- **Heavy-tailed and actuarial distributions.** Tweedie (compound Poisson–Gamma,
  `1 < p < 2`), zero-inflated Poisson, Gamma, Pareto and generalised Pareto.
- **Credit-risk monotonicity.** Rules such as "default rate falls as credit score rises" are
  built into generation and verified afterwards.
- **Reference data.** `--web-seed` extracts categories and value ranges from a DuckDuckGo
  search or a URL; `--hf-seed` samples a Hugging Face dataset. Reference data also enables the
  KS tests and the memorisation check.

## Sandbox (`--engine llm` only)

Generated code runs in a separate process with several layers of containment:

1. **AST static import allowlist** — parses the generated module before it runs and rejects
   imports outside the allowlist plus hazardous builtins (`eval`, `exec`, `open`,
   `__import__`, `__subclasses__`). A rejection is fed back to the self-healing loop like any
   other failure: the code never ran, so asking the model to rewrite it is safe.
2. **Isolated subprocess** — generated code never executes in the host process or the UI thread.
3. **Execution timeout** — 90 seconds by default; runaway processes are terminated.
4. **Memory watchdog (`psutil`)** — samples the process tree's memory and kills it past the
   limit (2 GB by default).

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
the whole application inside a container or VM — or use `--engine parametric`, which executes
no generated code at all.

---

## Languages

The desktop studio and command-line messages are available in English, Turkish, German,
French, Russian, Simplified Chinese and Japanese (*Settings → Defaults → Language*). English
and Turkish are maintained with the code; the other five started as machine translations and
have only been partly reviewed. Corrections are welcome — `test_i18n.py` catches missing keys
and mismatched placeholders.

```python
from ai_data_studio import i18n

i18n.set_language("de")
i18n.t("settings.keys.title")   # "API-Schlüssel"
```

You can describe datasets in any language; the prompts require column names and contract keys
to be ASCII snake_case identifiers, so the data works the same in pandas and databases
everywhere. Two things are deliberately **not** translated:

- **LLM prompts and the self-healing feedback.** The data a model generates must not change
  because a user switched the interface language. A test asserts the prompt modules never
  call `t()`.
- **Log records.** A fixed log language keeps the same failure searchable.

---

## Development

```bash
pip install -e ".[dev]"                   # or: pip install -r requirements-dev.txt
pytest ai_data_studio/tests               # offline, with mock LLM clients; about two minutes
ruff check . --select=E9,F63,F7,F82       # the lint gate CI runs
```

CI runs the suite on Ubuntu and Windows with Python 3.10, 3.11 and 3.12.

`build_exe.py` packages the desktop studio with PyInstaller (`--onedir` for a folder bundle,
`--console` to keep a console window). The Windows build is not part of CI and has not been
re-verified against the current code.

## Project layout

```
ai_data_studio/
├── __init__.py                 # Lazy public API (PEP 562) + __init__.pyi stub
├── api.py                      # generate() / validate() / compile_schema() / compile_dataset()
├── main.py                     # Desktop studio entry point
├── config.py                   # Configuration, keyring, paths, UTF-8 I/O
├── i18n.py                     # t(), language selection; catalogs in locales/
├── core/
│   ├── schema_contract.py      # Schema Contract model and tolerant parser (one table)
│   ├── dataset_contract.py     # Dataset Contract: tables + foreign keys + topological order
│   ├── project_planner.py      # Project description -> target, class balance, leakage, split
│   ├── parametric_engine.py    # --engine parametric: contract -> vectors, no generated code
│   ├── generator.py            # --engine llm: sandboxed execution and self-healing loop
│   ├── time_series_engine.py   # --time-series
│   ├── feature_expander.py     # --expand-features
│   ├── dirty_data_engine.py    # --dirty-rate
│   ├── hardware_profiler.py    # --hardware
│   ├── validator.py            # Cleaning stages, correlation guard, checks
│   ├── monotonicity_validator.py  # Binned / pairwise monotonicity, WoE / IV
│   ├── relational_validator.py # Primary / foreign keys, cardinality, orphan repair
│   ├── privacy_auditor.py      # Heuristic privacy checks (DCR / NNDR, identifier-name scan)
│   ├── fraud_injector.py       # Fraud and rare-event scenarios
│   ├── state_manager.py        # SQLite checkpoints and job history
│   └── orchestrator.py         # 7-step pipeline and command line
├── agents/                     # --agentic: experimental multi-role contract design
├── services/                   # Ollama, Gemini (AI Studio / Antigravity CLI), Claude,
│                               # web and Hugging Face clients, shared prompt blocks
├── gui/                        # CustomTkinter desktop studio
├── locales/                    # Message catalogs (en, tr, de, fr, ru, zh, ja)
└── tests/                      # Offline test suite with mock LLM clients
```

## Documentation

- [docs/engines.md](docs/engines.md) — generation and enrichment engines, measurements, known limits
- [docs/schema-contract.md](docs/schema-contract.md) — contract fields, multi-table contracts, tolerant parsing
- [docs/relational.md](docs/relational.md) — multi-table datasets, integrity checks, output layout
- [docs/project-planner.md](docs/project-planner.md) — generating data from a project description
- [docs/ENGINEERING_REPORT_TR.md](docs/ENGINEERING_REPORT_TR.md) — long-form engineering report in Turkish

## License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.
