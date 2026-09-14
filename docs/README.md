# Documentation

| Document | What it covers |
| --- | --- |
| [engines.md](engines.md) | Generation engines (`llm`, `parametric`, `auto`), enrichment engines, ordering rules, small-model and speed measurements, known limits |
| [schema-contract.md](schema-contract.md) | Every contract field, multi-table Dataset Contracts, and the mistakes the tolerant parser repairs |
| [relational.md](relational.md) | Multi-table datasets: integrity checks, repair order, output layout, provider advice |
| [project-planner.md](project-planner.md) | Generating data from a project description: target, class balance, leakage, split |
| [ENGINEERING_REPORT_TR.md](ENGINEERING_REPORT_TR.md) | Long-form engineering report in Turkish (see below) |

## `ENGINEERING_REPORT_TR.md`

A long **technical engineering report written in Turkish**, kept as a development record:

- Architecture deep-dives for the ParametricEngine, TimeSeriesEngine and DirtyDataEngine
- Forensic write-ups of notable bug investigations and fixes
- A head-to-head comparison of Gemini, local Ollama (`qwen2.5-coder`) and Claude on the same fraud-detection dataset
- Design rationale for the Generator–Discriminator pipeline, the Correlation Guard and relational integrity repair

It describes the project at the time each section was written; test counts, defaults and some
wording (for example the privacy report's former "differential privacy" and "HIPAA compliant"
labels) have changed since. The documents above and the README reflect the current code.
Machine-translation tools handle the prose well; the tables and code listings are largely
self-explanatory.
