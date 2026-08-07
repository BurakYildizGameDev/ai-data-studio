"""Iliskisel (cok tablolu) uretim icin prompt sablonlari.

Tek tablolu sablonlar ``llm_base`` icinde durur. Iliskisel olanlar ayri tutulur
cunku hem uzundurlar hem de en kritik ogretme yuku buradadir: modelin yabanci
anahtarlari EBEVEYNIN GERCEK anahtar dizisinden turetmesi gerekir. Uydurulmus
FK araliklari (ornegin ``rng.integers(1, n_rows)``) yetim satir uretir ve
iliskisel dogrulayici tarafindan reddedilir.
"""
from __future__ import annotations

from ..core.schema_contract import VALID_DISTRIBUTIONS
from .prompt_blocks import (
    CONTRACT_RULES_BLOCK,
    COPULA_BLOCK,
    DATASET_SHAPE,
    DATETIME_BLOCK,
    FAKER_BLOCK,
    HEAVY_TAIL_BLOCK,
    MONOTONICITY_BLOCK,
    escape_braces,
    numbered,
)

# Izin verilen dagilimlar dogrulayicidan turetilir. Sabit bir liste yazmak, canli
# kosuda somut bir hataya yol acmisti: istem dagilim adlarini hic saymadigi icin
# model bounded bir skor kolonu icin "beta" uydurdu ve sozlesme dogrulamasi dustu.
_ALLOWED_DISTRIBUTIONS = " | ".join('"%s"' % d for d in sorted(VALID_DISTRIBUTIONS))

__all__ = [
    "DATASET_SCHEMA_SYSTEM_PROMPT",
    "DATASET_SCHEMA_USER_TEMPLATE",
    "DATASET_CODE_SYSTEM_PROMPT",
    "DATASET_CODE_USER_TEMPLATE",
]


DATASET_SCHEMA_SYSTEM_PROMPT = ("""You are a senior data architect. You design NORMALISED RELATIONAL
schemas for synthetic datasets - not one wide denormalised table.

Output ONLY a single JSON object. No markdown fences, no commentary.

Shape:

DATASET_SHAPE

Design rules:
1. NORMALISE. Model the entities the problem actually has. A churn problem is usually
   customers + subscriptions/orders + events - not one table with pre-aggregated features
   like `total_purchases_90d`. Pre-aggregated columns are FEATURES, not data; do not invent them.
2. Between {min_tables} and {max_tables} tables. Prefer the smallest set that honestly
   represents the domain. Do not add tables for the sake of it.
3. Every table needs a `primary_key` naming a column that exists in that table and is an
   "int" column. Every child table lists its foreign key columns in `foreign_keys`, and those
   columns must exist in that table too.
4. Relationships must form a DAG - no cycles, no self-references. `root_table` must be the
   table that no relationship points to as a child.
5. `row_count_target` for the root table is exactly {row_count}. For child tables set it to a
   realistic multiple implied by `mean_per_parent` (it is a hint, the generator derives the
   true count from the cardinality).
6. `mean_per_parent` must be a realistic average for the domain. Use `min_per_parent: 0` when
   a parent may legitimately have no children.
7. Column objects follow the single-table Schema Contract exactly: name, type
   (int/float/bool/category/str/datetime), min, max, distribution, mean, std, target_ratio,
   categories, nullable, description.
   `min` and `max` are NUMBERS and apply to "int"/"float" columns only. A "datetime"
   column carries no min/max - state its range in `description` instead
   (e.g. "signup timestamp between 2020-01-01 and 2024-12-31"). Passing a date string
   as `min` is rejected.
   `distribution`, when present, MUST be exactly one of:
   """ + _ALLOWED_DISTRIBUTIONS + """
   There is no other accepted value - do not invent one (no "beta", no "binomial",
   no "weibull"). A column whose shape is not on this list simply OMITS `distribution`
   and relies on min/max. "normal" additionally requires "mean".
8. Put business rules, correlations and monotonicity rules on the table whose columns they
   reference. They may only reference columns WITHIN that same table - a rule can never
   span two tables, even through a foreign key.
   `business_rules` are pandas `df.eval()` expressions that are TRUE for every valid row
   (e.g. "shipping_cost <= basket_value"). Use only column names, numeric literals,
   comparison operators and `and` / `or` / `not`. This is NOT SQL: `AND`, `OR`, `NOT`,
   `IS NULL`, `IS NOT NULL` and quoted SQL string comparisons are all rejected. Express
   "may be missing" with `nullable` on the column instead of a null-check rule, and drop
   any rule you cannot write in that form.
   `correlations` may only reference int, float or bool columns of the same table.
9. Column and table names: lowercase snake_case, ASCII letters/digits/underscore, never
   starting with a digit.

Reminders that cause most rejections:
CONTRACT_RULES

Think about what the stated PROBLEM needs - the target variable, the entities that carry
signal, and how they relate - then emit the schema."""
).replace("DATASET_SHAPE", escape_braces(DATASET_SHAPE)
).replace("CONTRACT_RULES", CONTRACT_RULES_BLOCK)


DATASET_SCHEMA_USER_TEMPLATE = """Project / domain description:

{domain_prompt}

Root table row count: {row_count}
Random seed: {seed}
Faker locale: {locale}
{seed_block}
Design the relational Dataset Contract now. Output JSON only."""


_CROSS_TABLE_NOTE = """
Cross-table signal should flow through the foreign key: compute a per-parent propensity,
then use `np.repeat` to apply it to that parent's children."""


DATASET_CODE_SYSTEM_PROMPT = ("""You write Python that GENERATES a synthetic RELATIONAL dataset.
You never output data rows, only code. The code runs in a locked-down sandbox subprocess.

Output ONLY Python source code. No markdown fences, no commentary before or after.

Your code MUST define exactly this entry point:

    def generate_dataset(n_rows: int, seed: int) -> dict:

It returns a dict mapping table name -> pandas.DataFrame, containing EVERY table in the
contract, keyed by the exact table names.

`n_rows` is the row count of the ROOT table only. Child table sizes follow from the
cardinality of each relationship - never force a child table to n_rows.

=== THE FOREIGN KEY RULE (most important) ===

A child's foreign key column MUST be drawn from the parent's ACTUAL primary key array.
Never invent a range. This is wrong and produces orphan rows:

    orders["customer_id"] = rng.integers(1, n_rows, n_orders)   # WRONG

Generate parents first, then expand. The canonical pattern:

    # parent
    customer_id = np.arange(1, n_rows + 1)
    customers = pd.DataFrame({{"customer_id": customer_id, ...}})

    # how many children each parent gets (respect min/max_per_parent)
    per_parent = rng.poisson(mean_per_parent, n_rows).clip(min_per_parent, max_per_parent)

    # expand parent keys into the child's foreign key column
    order_customer_id = np.repeat(customer_id, per_parent)
    n_orders = order_customer_id.size

    orders = pd.DataFrame({{
        "order_id": np.arange(1, n_orders + 1),          # child's own primary key
        "customer_id": order_customer_id,                 # foreign key - always valid
        ...
    }})

Apply the same pattern down the chain (customers -> orders -> order_items), always using the
already-generated parent's key array. Follow the contract's table order: parents before children.

Hard requirements:
1. ALLOWED IMPORTS ONLY: {allowed_imports}
   Any other import is rejected before execution and your code will never run.
2. FORBIDDEN anywhere in the file: open(), eval(), exec(), compile(), __import__(), input(),
   file I/O, network access, printing, and dunder attribute tricks
   (__class__, __subclasses__, __globals__, ...).
3. NO file writing and NO `if __name__ == "__main__":` block. The harness imports your module,
   seeds every RNG, and calls generate_dataset() itself.
4. PERFORMANCE: the total row count across tables can exceed 1,000,000 and the sandbox kills
   the process after {timeout} seconds and above {memory_mb} MB. Use fully vectorised
   numpy/pandas operations - `np.repeat`, `np.arange`, boolean masks. Never loop row by row.
   `numpy.random.default_rng(seed)` is the preferred RNG.
5. REPRODUCIBILITY: derive all randomness from the `seed` argument.
6. Every primary key must be UNIQUE and non-null within its table.
7. Each DataFrame must have EXACTLY that table's schema columns, in schema order, with matching
   dtypes: "int" -> integer, "float" -> float, "bool" -> bool, "category"/"str" -> object/string,
   "datetime" -> datetime64.
   DTYPE RULE: do all arithmetic in float64 and cast to int ONCE at the end
   (`col = col.round().astype(int)`). Never use in-place operators (+=, -=, *=) on an integer
   array with a float operand - numpy raises UFuncOutputCastingError.
8. Respect every min/max bound, every requested distribution, and every bool target_ratio
   (within a couple of percent), per table.
9. BUSINESS RULES: enforce each table's rules structurally while generating that table
   (e.g. `end = start + positive_delta`, `child_amount = np.minimum(cap, candidate)`).
   Aim for 90-95% natural compliance so the downstream discriminator only trims edge cases.
"""
 + numbered(10, COPULA_BLOCK + _CROSS_TABLE_NOTE) + """
11. Deliberately leave a small amount of realistic noise (a few percent of outliers or rule
    violations). The discriminator cleans it. Do NOT emit perfectly sanitised data.
"""
 + numbered(12, MONOTONICITY_BLOCK) + """
"""
 + numbered(13, HEAVY_TAIL_BLOCK) + """
"""
 + numbered(14, DATETIME_BLOCK) + """
"""
 + numbered(15, FAKER_BLOCK))


DATASET_CODE_USER_TEMPLATE = """Dataset Contract:

{contract_json}

Generation order (parents first): {generation_order}
Root table: {root_table}

Write generate_dataset(n_rows, seed) for this contract now. Output Python source only."""
