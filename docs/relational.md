# Relational (Multi-Table) Datasets

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
    --engine parametric \
    --provider anthropic \
    --formats csv
```

```python
from ai_data_studio import generate

result = generate("SaaS billing: customers, subscriptions, invoices", rows=5_000,
                  relational=True, engine="parametric", provider="anthropic")

sorted(result.tables)                     # e.g. ['customers', 'invoices', 'subscriptions']
result.tables["invoices"].head()          # any table by name
result.dataframe                          # still the ROOT table - existing code keeps working
result.contract.relationships             # the FK graph the LLM designed
result.report["relational"]["pass"]       # did integrity hold?
```

You can also compile a Dataset Contract you wrote yourself, without any model — see
[`compile_dataset`](../README.md#python) in the README and the field reference in
[schema-contract.md](schema-contract.md#dataset-contract-multi-table).

## What is guaranteed

Generation walks the contract in topological order, so a child table draws its
foreign keys from the parent's **actual** key array rather than inventing an ID
range. After generation, three checks run and are recorded in
`report["relational"]`:

| Check | Meaning | On failure |
|---|---|---|
| **Primary keys** | Every `primary_key` is unique and non-null | Reported |
| **Foreign keys** | Every child FK resolves to a live parent row | Orphans removed (or reported with `--no-repair-orphans`) |
| **Cardinality** | Children per parent match the contract's `mean_per_parent` (±50%) | Reported as a deviation |

## Order matters

Per-table cleaning runs **first**, relational repair **second** — and never the
other way around. The validator removes rows table by table; when it drops a
parent row, that parent's children become orphans. Repairing relationships before
single-table cleaning would therefore leave dangling keys behind. The pipeline
enforces this order, and `--no-repair-orphans` turns the check into a **CI gate**:
orphaned foreign keys or duplicate primary keys make the process exit with code
`3` instead of silently deleting rows.

## Output layout

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

## Choosing a provider

The relational contract prompt is long, so this path asks more of the model than
single-table generation — and with `--engine llm` the generated program has to build every
table in one pass.

- **`--engine parametric` skips code generation**: the model only has to write the
  contract, and the tables are compiled from it.
- **API-key backends** (Anthropic, or Gemini via an AI Studio key with
  `--gemini-backend aistudio`) are the recommended choice for four or more tables. Runs of
  that size have not been measured with a small local model.
- **A capable local model works for small schemas.** A two-table contract generated and
  validated cleanly on a local `qwen2.5-coder:14b` with `--engine llm` (zero orphan keys,
  cardinality 2.93 against a contracted 3.0), taking one self-healing round on the code step.
  Larger schemas exceeded it.
- **The Antigravity CLI backend (`--gemini-backend cli`) is not practical here.** It
  reloads its agent context on every call and **timed out at 900 s** on the
  code-generation step of a four-table run. It remains usable for single-table work.
  The cost is startup, not inference: on a measured call the total was **204 s while
  the model step itself took 3.6 s**, and a 40-character prompt still billed ~13.4k
  input tokens for the agent's own context. Picking a smaller model does not help.
  The console reports the wait (a start notice plus a heartbeat every 30 s) so a long
  call does not look frozen.

## Scope

`--rows` applies to the **root table** only; child table sizes follow from the
cardinalities in the contract.

The modules around the pipeline take a table of their own:

| Flag | Default | What it does |
| --- | --- | --- |
| `--audit-table <name\|all>` | root table | Runs the privacy checks per table and writes one `job_<id>_<table>_privacy_report.md` for each. A child table has no reference data, so its report says the memorisation risk was **not measured** rather than leaving an empty score to read as "fine". An unknown table name is rejected instead of silently checking nothing |
| `--fraud-table <name>` | root table | Injects the fraud scenario into that table. The anomaly-preservation exemption follows the injection, so injected rows survive cleaning wherever they were put — measured with a custom label column: 0 survivors before, 69 after |
| `--ts-table <name>` | root table | Table that receives the time-series enrichment |
| `--expand-table <name>` | root table | Table that receives the derived feature columns |
| `--dirty-table <name>` | root table | Table that receives the controlled noise |

The Hugging Face dataset card lists every table with its primary key and row count plus
the relationship schema, and states which table the repository actually holds. The
desktop chart panel gets a table selector.

Single-table runs are untouched: same flat report shape, same file names, same
behaviour as before.
