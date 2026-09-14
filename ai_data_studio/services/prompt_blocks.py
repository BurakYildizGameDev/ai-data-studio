"""Tek tablolu ve iliskisel kod istemlerinin PAYLASTIGI ogretme bloklari.

Neden ayri bir modul: iliskisel istem bu bloklari kopyalamak yerine buradan aliyor.
Canli kosuda olculen uc kusurun ucu de ayni kokten geliyordu - *iliskisel istem, tek
tablolu istemin soyledigi kisiti tekrarlamiyordu*. Metni tek yerde tutmak o sinif
hatayi kaynaginda bitirir: bir blok guncellenince iki istem birden guncellenir.

Bloklar numarasiz saklanir ve devam satirlari girintisizdir; :func:`numbered` hem
numarayi hem hizalamayi ekler, boylece ayni blok iki istemde farkli sira numarasiyla
gorunebilir.
"""
from __future__ import annotations

__all__ = [
    "numbered",
    "escape_braces",
    "CORRELATION_SHAPE",
    "MONOTONICITY_SHAPE",
    "CONTRACT_RULES_BLOCK",
    "DATASET_SHAPE",
    "COLUMN_SHAPE",
    "BUSINESS_RULES_BLOCK",
    "COPULA_BLOCK",
    "RUNTIME_LITERALS_BLOCK",
    "MONOTONICITY_BLOCK",
    "HEAVY_TAIL_BLOCK",
    "DATETIME_BLOCK",
    "FAKER_BLOCK",
]


def numbered(index: int, block: str) -> str:
    """Blogu ``"<index>. BASLIK"`` olarak numaralandirir, devam satirlarini hizalar.

    >>> numbered(9, "TITLE:\\nbody")
    '9. TITLE:\\n   body'
    """
    prefix = "%d. " % index
    pad = " " * len(prefix)
    lines = block.rstrip("\n").split("\n")
    return "\n".join([prefix + lines[0]] + [pad + line for line in lines[1:]])


BUSINESS_RULES_BLOCK = """BUSINESS RULES & LOGICAL CONSTRAINTS:
Enforce relational rules directly in code generation! For rules specifying bounds or ordering
between columns (e.g. `col_a <= col_b`, `duration >= watch_time`, `end_date >= start_date`),
do not generate the two columns in isolation. Derive or bound the dependent column directly
(e.g. `watch_time = np.minimum(ad_duration, candidate_watch_time)` or `end = start + positive_delta`).
Aim for 90-95% natural compliance so the downstream discriminator cleans up subtle edge cases
without discarding large swaths of valid data."""


# Canli kosu (2026-09-14, qwen2.5-coder:1.5b): model `scipy.special.ndtr(...)` ornegini
# `ndtr(z_corr)` diye kisaltti ve import etmedi -> NameError. Import satiri artik ornekte.
COPULA_BLOCK = """CORRELATIONS & GAUSSIAN COPULA:
Build the requested correlations into the data structurally. For multi-variable rank correlations or
dependent variables with non-normal marginals, use a Gaussian Copula:
- Generate independent normals: `z = rng.standard_normal((n_rows, k))`
- Correlate via Cholesky decomposition: `z_corr = z @ np.linalg.cholesky(corr_matrix).T`
- Map to uniform margins [0, 1]: put `from scipy.special import ndtr` at the top of the file,
  then `u = ndtr(z_corr)` (or use empirical ranks)
- Invert $u$ to target marginal distributions using quantile functions."""


# Canli kosu (2026-09-14, qwen2.5-coder:1.5b): model kodun icinde sozlesmeyi sozluk olarak
# yeniden yazip `schema["churned"]["min"]` gibi okudu; bool kolonda min olmadigi icin
# iki denemede KeyError ile dustu.
RUNTIME_LITERALS_BLOCK = """THE CONTRACT IS NOT AVAILABLE AT RUNTIME:
The function receives only `n_rows` and `seed` - the contract is shown to you, never to the
code. Write every bound, category list and ratio as a literal inside the numpy call, e.g.
`rng.integers(18, 61, n_rows)`. Do not rebuild the contract as a dict and look values up:
`schema["churned"]["min"]` raises KeyError because a bool column has no min."""


MONOTONICITY_BLOCK = """MONOTONICITY (CREDIT RISK & SCORECARDS):
When monotonicity is specified between $X$ and $Y$ ($X_1 > X_2 \\implies Y_1 \\ge Y_2$), guarantee that
$Y$ is derived monotonically from $X$ (e.g. rank-aligned mapping, monotonic trend $f(X)$ with small bounded noise)
so that decile/bin averages remain monotonically ordered across the feature space."""


# Lognormal satiri canli kosudan geldi: sozlesmedeki mean/std GERCEK olceklidir
# (parametric_engine de boyle yorumlar), numpy ise log olcekli parametre bekler. Model
# `rng.lognormal(mean=50000, scale=10000)` yazdi; `sigma` ile bile exp(50000) = inf olur.
HEAVY_TAIL_BLOCK = """ACTUARIAL & HEAVY-TAIL DISTRIBUTIONS:
- Lognormal: the contract's `mean`/`std` are the column's REAL-scale mean and standard deviation,
  but `rng.lognormal(mean, sigma, size)` takes the parameters of the underlying normal (LOG scale)
  and its keyword is `sigma`, never `scale`. Convert first - passing `mean=50000` overflows to inf:
  `sigma = np.sqrt(np.log1p((std / mean) ** 2)); mu = np.log(mean) - sigma ** 2 / 2`, then
  `rng.lognormal(mu, sigma, n_rows)` (no `std` in the contract: use `sigma = 0.8`)
- Zero-Inflated Poisson (`zip`): `np.where(rng.uniform(0, 1, n_rows) < zero_prob, 0, rng.poisson(lam, n_rows))`
- Tweedie ($1 < p < 2$ Compound Poisson-Gamma): `k = rng.poisson(lam, n_rows); np.where(k > 0, rng.gamma(shape * k, scale), 0.0)`
- Gamma: `rng.gamma(shape, scale, n_rows)`
- Generalized Pareto / Pareto: `rng.pareto(shape, n_rows) * scale`"""


# Sema sozlesmesinde datetime kolonlarinin min/max alani YOKTUR (ikisi de sayisaldir),
# bu yuzden aralik `description` icinde duz metin olarak gelir. Kod istemi bunu bilmezse
# model tarihleri rastgele bir araliktan uretir.
DATETIME_BLOCK = """DATETIME COLUMNS:
A "datetime" column carries no min/max in the contract - those fields are numeric only.
Read its intended range from the column `description` (e.g. "signup timestamp between
2020-01-01 and 2024-12-31") and generate within it, defaulting to a sensible recent
window when the description says nothing. Build them by adding an integer offset to a
base timestamp, e.g.
`pd.Timestamp("2020-01-01") + pd.to_timedelta(rng.integers(0, 1826, n_rows), unit="D")`.
Return real datetime64 values, never strings."""


FAKER_BLOCK = """Faker is available with `from faker import Faker`, `fake = Faker("{locale}")` and `Faker.seed(seed)`, but PREFER numpy.
Faker is slow at 100k rows - if you use it, generate a small pool (<=500 values) and
sample it with numpy.
ONLY use simple no-argument providers: name(), first_name(), last_name(), email(),
city(), country(), company(), user_agent(), uuid4().
NEVER use Faker's template/format APIs - pystr_format(), bothify(), lexify(),
numerify(), parse(). They take formatter templates, not str.format() placeholders,
and are a frequent source of "Unknown formatter" errors.
For patterned strings like version numbers or IDs, build them with numpy instead, e.g.
`np.char.add("v1.", rng.integers(0, 20, n_rows).astype(str))`."""


def escape_braces(text: str) -> str:
    """``str.format`` uygulanacak bir sablona duz metin gomerken suslu parantezleri kacirir.

    Iliskisel sema istemi ``.format(min_tables=..., ...)`` ile isleniyor; icine
    kacirilmamis bir JSON ornegi konursa format() onu yer tutucu sanip patlar.
    """
    return text.replace("{", "{{").replace("}", "}}")


# Sozlesme nesnelerinin SEKLI. Tek tablolu istem bunlari zaten gosteriyordu, iliskisel
# istem yalnizca "[...]" yaziyordu - model sekli tahmin etmek zorunda kaliyordu ve canli
# kosuda ayni hatayi uc denemede de tekrarladi ('columns' tek elemanli geldi).
CORRELATION_SHAPE = (
    '{"columns": ["<col_a>", "<col_b>"], "expected_sign": "positive" | "negative", '
    '"min_r": <0..1>, "method": "pearson" | "spearman"}'
)

MONOTONICITY_SHAPE = (
    '{"column_x": "<feature_col>", "column_y": "<target_or_outcome_col>", '
    '"direction": "increasing" | "decreasing", "min_compliance_ratio": 0.90}'
)

# En sik redde yol acan kisitlar. Iki sema istemi de bunlari aynen gostermeli.
CONTRACT_RULES_BLOCK = """- `correlations.columns` must list EXACTLY TWO column names - never one, never three.
- correlations may only reference int, float or bool columns
  (a bool target vs. a numeric driver is a valid point-biserial correlation).
- "category" columns MUST provide a non-empty "categories" list.
- "normal" distribution requires "mean".
- column names: ALL column names MUST be pure ASCII snake_case English identifiers (e.g. "transaction_amount", "customer_age", "is_fraud"), regardless of what language the prompt or domain description is written in (letters, digits, underscore only; never start with a digit; no accented or non-ASCII characters)."""


# Bir kolon nesnesinin alanlari. Uc istem de ayni listeyi gostermeli - kisaltilan her
# alan modelin tahmin etmesi gereken bir alandir ve canli kosuda dusen bir sozlesmedir.
COLUMN_SHAPE = """{
        "name": "<snake_case identifier>",
        "type": "int" | "float" | "bool" | "str" | "category" | "datetime",
        "min": <number, int/float columns only>,
        "max": <number, int/float columns only>,
        "distribution": <see the allowed list below>,
        "mean": <number, REQUIRED when distribution is "normal">,
        "std": <number, optional>,
        "target_ratio": <0..1, bool columns only - share of True values>,
        "categories": [<values>, ...],
        "nullable": <bool, optional>,
        "description": "<short description; a datetime column states its range here>"
      }"""

# Cok tablolu sozlesmenin tam sekli. `domain` her tabloda ZORUNLUDUR - kisaltildiginda
# yerel model bu alani atladi ve sozlesme dogrulamasi dustu.
DATASET_SHAPE = """{
  "domain": "snake_case_dataset_name",
  "description": "one sentence",
  "root_table": "<name of the table the requested row count applies to>",
  "tables": [
    {
      "name": "customers",
      "domain": "customers",
      "row_count_target": <int>,
      "primary_key": "customer_id",
      "foreign_keys": [],
      "columns": [COLUMN_SHAPE],
      "business_rules": ["<pandas df.eval() expression true for every valid row>"],
      "correlations": [CORR_SHAPE],
      "monotonicity_rules": [MONO_SHAPE]
    }
  ],
  "relationships": [
    {
      "parent_table": "customers", "parent_key": "customer_id",
      "child_table": "orders",     "child_key": "customer_id",
      "mean_per_parent": 3.0, "min_per_parent": 0, "max_per_parent": 50,
      "nullable": false
    }
  ]
}""".replace("COLUMN_SHAPE", COLUMN_SHAPE).replace(
    "CORR_SHAPE", CORRELATION_SHAPE).replace("MONO_SHAPE", MONOTONICITY_SHAPE)
