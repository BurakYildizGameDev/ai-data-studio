# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/).

## [2.0.0] - 2026-09-14

First public release.

### Generation
- An LLM writes a **Schema Contract** (columns, distributions, business rules, correlations,
  monotonicity rules) instead of rows; one call covers any row count.
- Providers: local **Ollama** (no key), **Google Gemini** (AI Studio key or Antigravity CLI
  login) and **Anthropic Claude** (API key or an existing Claude Code login).
- **Parametric engine** compiles the contract into NumPy/pandas vectors: declared distributions
  (including Tweedie, zero-inflated Poisson, Gamma, Pareto, GPD), a Gaussian copula for
  correlations and monotonic trends, and business rules repaired during generation.
  100,000 rows × 10 columns in 0.13 s on the development machine.
- **LLM engine** runs a model-written generator program in a separate process with an import
  allowlist, timeout and memory watchdog, and feeds failures back for up to three repairs;
  `auto` falls back to the parametric engine.
- Small local models: `qwen2.5-coder:1.5b` with the parametric engine finished 9 of 9 measured
  runs and met 25 of 26 declared correlations. The desktop studio switches small models to the
  parametric engine automatically.
- Tolerant contract parsing for small-model mistakes (comments, aliases, SQL-style rules,
  impossible correlation targets) with warnings; ambiguous errors are sent back to the model.
- **Relational datasets**: Dataset Contracts with primary/foreign keys and cardinalities,
  topological generation, orphan repair or a CI gate (`--no-repair-orphans`).
- **Project planner** (`--project`): target variable, class balance, leakage exclusions and a
  train/test split, checked for consistency before generation.
- Enrichment: time series and velocity (`--time-series`), derived features
  (`--expand-features`), controlled noise applied after validation (`--dirty-rate`), fraud
  scenarios (`--inject-fraud`).
- Experimental multi-role contract design (`--agentic`).

### Validation
- Duplicates, schema bounds, business rules, distribution-aware Z-score filtering that skips
  heavy-tailed columns, opt-in Isolation Forest, and a correlation guard that rolls back outlier
  removal when it breaks a declared correlation.
- Checks for every declared correlation (Pearson, Spearman or Kendall), monotonicity rules
  (binned, pairwise, Spearman direction, WoE/IV) and Kolmogorov–Smirnov tests against
  reference data.
- Heuristic privacy checks (`--audit-privacy`): nearest-neighbour memorisation test compared
  with a reference-to-reference baseline, Jensen–Shannon distribution divergence and an
  identifier column-name scan. Not a differential-privacy guarantee or a compliance
  certification.

### Interfaces
- Python API: `generate`, `validate`, `compile_schema`, `compile_dataset` (lazy import, typed).
- Command line: `python -m ai_data_studio.core.orchestrator`.
- CustomTkinter desktop studio (`ai-data-studio`) with a live console, charts and job history.
- Messages in English and Turkish, plus machine-translated German, French, Russian,
  Simplified Chinese and Japanese.
- Exports to CSV, Parquet and JSON, with the contract, a JSON report, a regeneration script and
  an optional Hugging Face dataset card.

[2.0.0]: https://github.com/BurakYildizGameDev/ai-data-studio/releases/tag/v2.0.0
