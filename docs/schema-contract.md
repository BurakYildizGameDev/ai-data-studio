# Schema Contract

The Schema Contract is the single source of truth between generation and validation: the
LLM writes it (or you do), the engine generates data from it, and the validator checks the
data against it.

- [Example](#example)
- [Field reference](#field-reference)
- [Dataset Contract (multi-table)](#dataset-contract-multi-table)
- [Tolerant parsing](#tolerant-parsing)

## Example

```json
{
  "domain": "mobile_game_ad_engagement",
  "row_count_target": 50000,
  "random_seed": 42,
  "columns": [
    {"name": "user_age", "type": "int", "min": 13, "max": 65,
     "distribution": "normal", "mean": 28, "std": 8},
    {"name": "ad_duration_s", "type": "int", "min": 5, "max": 60, "distribution": "uniform"},
    {"name": "watch_time_s", "type": "float", "min": 0.0, "max": 60.0},
    {"name": "is_clicked", "type": "bool", "target_ratio": 0.12}
  ],
  "business_rules": [
    "watch_time_s <= ad_duration_s",
    "watch_time_s >= 0.0"
  ],
  "correlations": [
    {"columns": ["ad_duration_s", "watch_time_s"], "expected_sign": "positive", "min_r": 0.35}
  ],
  "monotonicity_rules": [
    {"column_x": "watch_time_s", "column_y": "is_clicked", "direction": "increasing"}
  ]
}
```

## Field reference

### Top level

| Field | Type | Notes |
| --- | --- | --- |
| `domain` | string | Short snake_case name; used in file names. `compile_schema` fills in a default |
| `columns` | list | Required, at least one column |
| `row_count_target` | int | Rows to generate when no explicit count is passed (default 100,000) |
| `random_seed` | int | Default `42` |
| `business_rules` | list of strings | pandas `DataFrame.eval` expressions every row must satisfy |
| `correlations` | list | See below |
| `monotonicity_rules` | list | See below |
| `preserve_anomaly_column` / `preserve_anomaly_value` | string / any | Rows with this value are exempt from outlier filters (e.g. `is_fraud` / `1`) |
| `faker_locale` | string | Locale for generated text values, e.g. `tr_TR` |
| `description` | string | Free text |

### Columns

| Field | Applies to | Notes |
| --- | --- | --- |
| `name` | all | ASCII snake_case identifier, unique |
| `type` | all | `int`, `float`, `bool`, `str`, `category`, `datetime` |
| `min`, `max` | `int`, `float` | Hard bounds; the validator removes rows outside them |
| `distribution` | numeric | `normal`, `uniform`, `lognormal`, `exponential`, `poisson`, `gamma`, `tweedie`, `zip` (zero-inflated Poisson), `pareto`, `gpd`, `categorical`, `custom` |
| `mean`, `std` | numeric | Distribution parameters |
| `shape`, `scale` | `gamma`, `pareto`, `gpd` | Shape / scale parameters |
| `zero_prob` | `zip` | Probability of a structural zero (0–1) |
| `p_index` | `tweedie` | Power parameter, strictly between 1 and 2 |
| `target_ratio` | `bool` | Share of `True` values |
| `categories` | `category` | Allowed values |
| `nullable` | all | Default `false` |
| `description` | all | Free text; for `datetime` columns the date range is read from here |

### Correlations

| Field | Notes |
| --- | --- |
| `columns` | Exactly two column names of type `int`, `float` or `bool` |
| `expected_sign` | `positive` or `negative` |
| `min_r` | Minimum correlation strength in the expected direction (`r >= min_r`, or `r <= -min_r` for `negative`) |
| `method` | `pearson` (default) or `spearman`. `kendall` is accepted by the parser but is currently checked with Pearson |

### Monotonicity rules

| Field | Notes |
| --- | --- |
| `column_x`, `column_y` | Driver and outcome (`x`/`y` or a two-item `columns` list are accepted too) |
| `direction` | `increasing` or `decreasing` |
| `min_compliance_ratio` | Default `0.90`. Adjacent-bin means must follow the direction at least this often, sampled row pairs at least 85% of it, and the Spearman correlation must not point the other way |

## Dataset Contract (multi-table)

A Dataset Contract wraps several Schema Contracts. Each table accepts every field above plus
`name`, `primary_key` and `foreign_keys`; relationships live at the top level.

```python
from ai_data_studio import compile_dataset

spec = {
    "root_table": "customers",
    "tables": [
        {"name": "customers", "primary_key": "customer_id", "columns": [
            {"name": "customer_id", "type": "int"},
            {"name": "country", "type": "category", "categories": ["US", "DE", "TR", "GB"]},
        ]},
        {"name": "orders", "primary_key": "order_id", "foreign_keys": ["customer_id"], "columns": [
            {"name": "order_id", "type": "int"},
            {"name": "customer_id", "type": "int"},
            {"name": "amount", "type": "float", "min": 1, "max": 5000,
             "distribution": "lognormal", "mean": 60},
        ]},
    ],
    "relationships": [
        {"parent_table": "customers", "parent_key": "customer_id",
         "child_table": "orders", "child_key": "customer_id", "mean_per_parent": 4},
    ],
}

tables = compile_dataset(spec, rows=10_000, seed=42)   # rows = root table size
```

| Relationship field | Notes |
| --- | --- |
| `parent_table`, `parent_key` | Required |
| `child_table`, `child_key` | Required |
| `mean_per_parent` | Average children per parent; default `3.0` |
| `min_per_parent`, `max_per_parent` | Optional bounds on children per parent |
| `nullable` | Whether the child key may be empty |

## Tolerant parsing

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
