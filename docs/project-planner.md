# From a Project, Not a Schema

Every other mode asks you to describe the **data** you want. This one asks you to
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

result = generate(project="predict which subscribers churn next month", rows=5_000,
                  provider="anthropic")

result.plan.target.label()                        # e.g. 'customers.churned'
result.plan.positive_class_ratio                  # e.g. 0.18
[e.column for e in result.plan.excluded_leakage]  # e.g. ['cancellation_reason', ...]
result.plan.split.kind                            # e.g. 'temporal'
result.tables["customers"].head()
```

## Four decisions that make data trainable

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

## What you can check

The plan itself is a judgement — there is no ground truth to compare it against. What can
be verified is whether it is self-consistent and whether the data honours it, and both are:
the run prints every decision to the console, writes the plan next to the data as
`job_<id>_<domain>_plan.json`, and stores it in the report under `project_plan`.

```
Plan ready: task: binary_classification | target: customers.churned | positive class: 18.0% | 2 tables | 2 leakage columns removed | split: temporal
  -> Target variable: customers.churned
  -> Class balance: positive class 18.0%
  -> Columns dropped because they would leak (2):
  • cancellation_reason - only filled in after the customer has churned
  • refund_issued_at - a post-churn event; it gives the target away
  -> Train/test split: temporal (customers.signup_at) - we are predicting the future
```

How well the planner spots leakage depends on the model. In a local test with
`qwen2.5-coder:14b` the planner returned an empty leakage list; larger API models have not
been measured systematically yet.

`--project` replaces `--domain`; the two cannot be combined. The planner decides how many
tables the problem needs (`--max-tables` caps it), so `--relational` does not apply here —
a one-table plan is a legitimate answer when the problem has one entity.
