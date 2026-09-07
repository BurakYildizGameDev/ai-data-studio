"""LLM istemcileri için ortak taban sinifi ve prompt sablonlari.

Ollama ve bulut saglayicilari aynı sozlesmeyi (BaseLLMClient) uygular; böylece
orchestrator ve generator hangi sağlayıcının kullanildigini bilmek zorunda kalmaz.
Prompt sablonlari tek yerde tutulur - kod üretimi, şema üretimi ve dataset card
üretimi tüm saglayicilarda aynı davranir.
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

from .. import config
from ..i18n import t
from .prompt_blocks import (
    BUSINESS_RULES_BLOCK,
    COPULA_BLOCK,
    DATETIME_BLOCK,
    FAKER_BLOCK,
    HEAVY_TAIL_BLOCK,
    MONOTONICITY_BLOCK,
    numbered,
)
from ..core.schema_contract import (
    SchemaContract,
    SchemaValidationError,
    extract_json_block,
)

# Sema uretimi kac kez denenir (self-healing)
SCHEMA_MAX_RETRIES = 3

from .relational_prompts import (
    DATASET_CODE_SYSTEM_PROMPT,
    DATASET_CODE_USER_TEMPLATE,
    DATASET_SCHEMA_SYSTEM_PROMPT,
    DATASET_SCHEMA_USER_TEMPLATE,
)

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM çağrısı başarısız oldu (ag, kimlik doğrulama, kota vb.)."""


class LLMNotConfiguredError(LLMError):
    """API key eksik veya servis erisilemiyor."""


# --------------------------------------------------------------------------- #
# Prompt sablonlari
# --------------------------------------------------------------------------- #
SCHEMA_SYSTEM_PROMPT = """You are a senior data engineer who designs synthetic dataset schemas.

You will be given a domain description. Research the domain from your own knowledge and
produce a STRICT JSON "Schema Contract" that downstream code generation and statistical
validation will both consume. Realism matters: pick column names, ranges, distributions and
business rules that a real practitioner in this domain would recognise.

Return ONLY a single JSON object. No prose, no markdown fences, no explanation.

The JSON object MUST have exactly this shape:

{
  "domain": "<short_snake_case_domain_id>",
  "description": "<one sentence describing the dataset>",
  "row_count_target": <int>,
  "random_seed": <int>,
  "columns": [
    {
      "name": "<snake_case identifier: letters, digits, underscore only; must not start with a digit>",
      "type": "int" | "float" | "bool" | "str" | "category" | "datetime",
      "min": <number, optional - numeric columns only>,
      "max": <number, optional - numeric columns only>,
      "distribution": "normal" | "uniform" | "lognormal" | "exponential" | "poisson" | "gamma" | "tweedie" | "zip" | "gpd" | "pareto" | "categorical",
      "mean": <number, REQUIRED when distribution is "normal">,
      "std": <number, optional>,
      "target_ratio": <0..1, bool columns only - share of True values>,
      "categories": [<values>],
      "shape": <number, optional - for gamma/pareto/gpd distributions>,
      "scale": <number, optional - for gamma/pareto/gpd distributions>,
      "zero_prob": <0..1, optional - for zero-inflated poisson>,
      "p_index": <1..2, optional - for compound poisson-gamma tweedie>,
      "nullable": <bool, optional>,
      "description": "<short column description>"
    }
  ],
  "business_rules": [
    "<pandas df.eval() compatible boolean expression that every VALID row satisfies>"
  ],
  "correlations": [
    {"columns": ["<col_a>", "<col_b>"], "expected_sign": "positive" | "negative", "min_r": <0..1>, "method": "pearson" | "spearman"}
  ],
  "monotonicity_rules": [
    {"column_x": "<feature_col>", "column_y": "<target_or_outcome_col>", "direction": "increasing" | "decreasing", "min_compliance_ratio": 0.90}
  ]
}

Hard constraints:
- 12 to 20 columns. Include at least one target/outcome column when the domain implies one.
- Provide a rich, enterprise-grade schema covering: identifiers, user demographics, financial balances/limits, transaction specifics, device/network telemetries, and outcome/risk labels.
- Every name in business_rules, correlations, and monotonicity_rules MUST be a column defined in "columns".
- business_rules are expressions that hold TRUE for valid rows (e.g. "watch_time_s <= ad_duration_s").
  Use only column names, numeric literals, comparison operators and `and` / `or` / `not`.
  Do NOT use Python function calls, method calls, or string methods.
- `correlations.columns` must list EXACTLY TWO column names - never one, never three.
- correlations may only reference int, float or bool columns
  (a bool target vs. a numeric driver is a valid point-biserial correlation).
- "category" columns MUST provide a non-empty "categories" list.
- Distributions must be plausible for the domain, not arbitrary. In actuarial/insurance domains, prefer
  gamma (claim severity), zero-inflated poisson (claim counts), tweedie (pure premium), or pareto/gpd (heavy tails).
- In credit risk / scorecard domains, specify monotonicity_rules for rank-order consistency."""

SCHEMA_USER_TEMPLATE = """Domain / task: {domain_prompt}

row_count_target: {row_count}
random_seed: {seed}
Locale for any localised values: {locale}
{seed_block}
Produce the Schema Contract JSON now."""

SEED_DATA_BLOCK = """
A real reference dataset was found on HuggingFace. Use it to ground your column choices,
ranges and distributions (do not copy the rows, only the structure and realistic ranges):

Columns and dtypes:
{dtypes}

Descriptive statistics:
{describe}

Sample rows:
{sample}
"""

SCHEMA_FIX_TEMPLATE = """{original}

Your previous answer was REJECTED by the schema validator.

Previous answer:
{previous}

Validator error:
{error}

Fix exactly that problem and return the corrected Schema Contract JSON only.
Reminders that cause most rejections:
- `correlations.columns` must list EXACTLY TWO column names - never one, never three
- correlations may only reference int, float or bool columns defined in "columns"
- every name used in business_rules and correlations must be a defined column
- "category" columns require a non-empty "categories" list
- "normal" distribution requires "mean"
- column names: letters, digits and underscore only, never starting with a digit"""

CODE_SYSTEM_PROMPT = ("""You write Python that GENERATES synthetic data. You never output data rows,
only code. The code runs in a locked-down sandbox subprocess.

Output ONLY Python source code. No markdown fences, no commentary before or after.

Your code MUST define exactly this entry point:

    def generate_data(n_rows: int, seed: int) -> pd.DataFrame:

Hard requirements:
1. ALLOWED IMPORTS ONLY: {allowed_imports}
   Any other import is rejected before execution and your code will never run.
2. FORBIDDEN anywhere in the file: open(), eval(), exec(), compile(), __import__(), input(),
   file I/O, network access, printing, and dunder attribute tricks
   (__class__, __subclasses__, __globals__, ...).
3. NO file writing and NO `if __name__ == "__main__":` block. The harness imports your module,
   seeds every RNG, and calls generate_data() itself.
4. PERFORMANCE: n_rows can be 100000+ and the sandbox kills the process after {timeout} seconds
   and above {memory_mb} MB. Use fully vectorised numpy/pandas operations.
   Never loop row by row in Python. `numpy.random.default_rng(seed)` is the preferred RNG.
5. REPRODUCIBILITY: derive all randomness from the `seed` argument.
6. The returned DataFrame must have EXACTLY the schema columns, in schema order, with matching
   dtypes: "int" -> integer dtype, "float" -> float dtype, "bool" -> bool dtype,
   "category"/"str" -> object/string dtype, "datetime" -> datetime64.
   DTYPE RULE: do all arithmetic in float64 and cast to int ONCE at the end
   (`col = col.round().astype(int)`). Never use in-place operators (+=, -=, *=) on an
   integer array with a float operand - numpy raises UFuncOutputCastingError.
7. Respect every min/max bound, every requested distribution, and every bool target_ratio
   (within a couple of percent).
"""
 + numbered(8, BUSINESS_RULES_BLOCK) + """
"""
 + numbered(9, COPULA_BLOCK) + """
"""
 + numbered(10, MONOTONICITY_BLOCK) + """
"""
 + numbered(11, HEAVY_TAIL_BLOCK) + """
"""
 + numbered(12, FAKER_BLOCK) + """
"""
 + numbered(13, DATETIME_BLOCK))


CODE_USER_TEMPLATE = """Schema Contract:

{schema_json}

Write generate_data(n_rows, seed) for this contract now. Output Python source only."""

FIX_SYSTEM_PROMPT = """You are debugging Python data-generation code that failed inside a sandbox.

Output ONLY the complete corrected Python source file. No markdown fences, no commentary,
no diff - the full file, ready to run.

All original constraints still apply:
- entry point `def generate_data(n_rows: int, seed: int) -> pd.DataFrame:`
- allowed imports only: {allowed_imports}
- no open/eval/exec/__import__/file I/O/network/print, no `if __name__ == "__main__":` block
- fully vectorised, must finish within {timeout} seconds and {memory_mb} MB
- must match the Schema Contract exactly

Fix the ROOT CAUSE of the reported problem. Do not merely suppress the symptom, and do not
silently drop columns or shrink the row count to make the error go away."""

FIX_USER_TEMPLATE = """Schema Contract:

{schema_json}

Previous code:

{previous_code}

Problem reported by the sandbox / validator:

{error_feedback}
{history_block}{escalation_block}
Return the corrected full Python file now."""

HISTORY_BLOCK = """
Earlier failed attempts in this session (do not repeat these mistakes):
{history}
"""

ESCALATION_BLOCK = """
STOP. You have now failed with the SAME error more than once, so patching your previous
code is not working. Discard it and rewrite generate_data from scratch, as simply as you
can:
- use ONLY numpy and pandas; do not import Faker (build string columns from small
  hard-coded value pools sampled with numpy)
- build every numeric column as float64 first, apply all arithmetic, and cast to int only
  once at the very end
- never use in-place operators (+=, *=) on integer arrays
- create each column with a single vectorised expression of length n_rows
Correctness first: a simple generator that runs beats a clever one that crashes.
"""

CARD_SYSTEM_PROMPT = """You write HuggingFace dataset cards. Output ONLY GitHub-flavoured Markdown
starting with a YAML front matter block. No commentary outside the card.

The card must contain:
- YAML front matter with `license: mit`, `language`, `tags`, `size_categories`
- an H1 title
- a "Dataset Summary" section stating clearly that the data is SYNTHETIC and machine-generated
- a "Columns" markdown table: name, type, description
- a "Generation Method" section (LLM-authored generator code + statistical validation pipeline)
- a "Validation" section quoting the given statistics
- a "Limitations and Intended Use" section warning that synthetic data must not be treated as
  real observations and should not be used for safety-critical decisions"""

CARD_USER_TEMPLATE = """Schema Contract:

{schema_json}

Validation statistics:

{stats_json}

Write the dataset card now."""

_FENCE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def strip_code_fences(text: str) -> str:
    """LLM ciktisindaki markdown fence'lerini temizler, çıplak Python birakir."""
    if not text:
        return ""
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    return cleaned.strip()


class BaseLLMClient(ABC):
    """Tüm LLM saglayicilarinin uyguladigi sozlesme.

    Alt siniflar yalnızca _complete() metodunu yazar; prompt kurgusu ve çıktı
    ayıklama burada ortaktir.
    """

    provider: str = "base"

    def __init__(self, model: str, state_manager=None, job_id: Optional[int] = None,
                 temperature: float = 0.4,
                 progress_cb: Optional[Callable[[str], None]] = None):
        self.model = model
        self.state_manager = state_manager
        self.job_id = job_id
        self.temperature = temperature
        # health_check() basarisiz olursa nedeni buraya yazilir (GUI/CLI gosterir).
        self.last_health_error: str = ""
        # Hangi kimlik kaynagi kullanildi (config.Credential); Ollama'da anlamsizdir.
        self.credential = None
        # Uzun suren bir cagri sirasinda ara durum bildirmek icin (bkz.
        # _report_progress). Yalnizca akis destekleyen istemciler kullanir;
        # digerlerinde None kalir ve hicbir sey degismez.
        self.progress_cb: Optional[Callable[[str], None]] = progress_cb

    # -- alt siniflarin uygulayacagi tek metot ---------------------------- #
    @abstractmethod
    def _complete(self, system: str, user: str, max_tokens: int = 16000,
                  temperature: Optional[float] = None) -> str:
        """Tek turlu tamamlama yapar, düz metin dondurur.

        Token kullanimini _log_usage() ile kaydetmelidir.
        """

    @abstractmethod
    def health_check(self) -> bool:
        """Servis erisilebilir ve kimlik bilgileri geçerli mi?"""

    # -- ortak yardimcilar ------------------------------------------------ #
    def _report_progress(self, message: str) -> None:
        """Cagri suruyorken ara durum bildirir; alici yoksa hicbir sey yapmaz.

        Geri cagirma UI thread'ine kuyruk uzerinden yaziyor olabilir; oradan gelen
        bir hata pipeline'i dusurmemeli - ilerleme bildirimi hicbir zaman kritik yol
        degildir.
        """
        if self.progress_cb is None:
            return
        try:
            self.progress_cb(message)
        except Exception as exc:  # pragma: no cover - savunma amacli
            log.warning("İlerleme bildirimi başarısız: %s", exc)

    def _log_usage(self, input_tokens: int, output_tokens: int, purpose: str) -> None:
        if self.state_manager is None:
            return
        try:
            self.state_manager.log_llm_call(
                self.job_id, self.provider, self.model,
                input_tokens=input_tokens, output_tokens=output_tokens, purpose=purpose,
            )
        except Exception as exc:  # pragma: no cover - loglama hicbir zaman pipeline'i kirmasin
            log.warning("Token kullanimi loglanamadi: %s", exc)

    def _sandbox_prompt_vars(self) -> Dict[str, Any]:
        return {
            "allowed_imports": ", ".join(sorted(config.ALLOWED_IMPORTS)),
            "timeout": config.SANDBOX_TIMEOUT_S,
            "memory_mb": config.SANDBOX_MEMORY_LIMIT_MB,
        }

    # -- pipeline adimlari ------------------------------------------------ #
    def generate_schema(self, domain_prompt: str,
                        row_count: int = config.DEFAULT_ROW_TARGET,
                        seed: int = config.DEFAULT_RANDOM_SEED,
                        locale: str = "en_US",
                        seed_dataframe=None) -> SchemaContract:
        """Adım 2: domain analizi -> Schema Contract JSON üretimi."""
        seed_block = ""
        if seed_dataframe is not None and len(seed_dataframe) > 0:
            seed_block = _build_seed_block(seed_dataframe)

        user = SCHEMA_USER_TEMPLATE.format(
            domain_prompt=domain_prompt.strip(),
            row_count=row_count,
            seed=seed,
            locale=locale,
            seed_block=seed_block,
        )

        # Kod uretimindeki gibi self-healing: sema dogrulamasi patlarsa hatayi
        # LLM'e geri besleyip duzelttiririz. Yerel/kucuk modeller ilk denemede
        # siklikla sozlesmeyi tam tutturamaz; tek atista pes etmek pipeline'i
        # gereksiz yere dusurur.
        last_error: Optional[Exception] = None
        last_raw = ""
        for attempt in range(1, SCHEMA_MAX_RETRIES + 1):
            prompt = user if attempt == 1 else SCHEMA_FIX_TEMPLATE.format(
                original=user, previous=last_raw, error=str(last_error)
            )
            raw = self._complete(SCHEMA_SYSTEM_PROMPT, prompt,
                                 max_tokens=8000, temperature=0.5)
            last_raw = raw
            try:
                # Bolum 10.6: LLM JSON'u aciklamaya sarmis olabilir.
                data = extract_json_block(raw)
                # Kullanicinin GUI'de sectigi degerler LLM'in tahminini ezer.
                data["row_count_target"] = row_count
                data["random_seed"] = seed
                data["faker_locale"] = locale
                contract = SchemaContract.from_dict(data)
            except SchemaValidationError as exc:
                last_error = exc
                log.warning("Şema doğrulanamadı (deneme %d/%d): %s",
                            attempt, SCHEMA_MAX_RETRIES, exc)
                continue
            if attempt > 1:
                log.info("Şema %d. denemede duzeltildi", attempt)
            return contract

        raise SchemaValidationError(
            t("service.error.schema_retries", attempts=SCHEMA_MAX_RETRIES,
              error=last_error)
        )

    def generate_dataset_schema(self, domain_prompt: str,
                                row_count: int = config.DEFAULT_ROW_TARGET,
                                seed: int = config.DEFAULT_RANDOM_SEED,
                                locale: str = "en_US",
                                seed_dataframe=None,
                                min_tables: int = 2,
                                max_tables: int = 6):
        """Adım 2 (iliskisel): domain analizi -> Dataset Contract JSON.

        Tek tablolu :meth:`generate_schema` ile ayni self-healing dongusunu
        kullanir; dogrulama hatasi LLM'e geri beslenir.
        """
        from ..core.dataset_contract import DatasetContract

        seed_block = ""
        if seed_dataframe is not None and len(seed_dataframe) > 0:
            seed_block = _build_seed_block(seed_dataframe)

        system = DATASET_SCHEMA_SYSTEM_PROMPT.format(
            min_tables=min_tables, max_tables=max_tables, row_count=row_count
        )
        user = DATASET_SCHEMA_USER_TEMPLATE.format(
            domain_prompt=domain_prompt.strip(),
            row_count=row_count,
            seed=seed,
            locale=locale,
            seed_block=seed_block,
        )

        last_error = None
        last_raw = ""
        for attempt in range(1, SCHEMA_MAX_RETRIES + 1):
            prompt = user if attempt == 1 else SCHEMA_FIX_TEMPLATE.format(
                original=user, previous=last_raw, error=str(last_error)
            )
            raw = self._complete(system, prompt, max_tokens=12000, temperature=0.5)
            last_raw = raw
            try:
                data = extract_json_block(raw)
                data["random_seed"] = seed
                contract = DatasetContract.from_dict(data)
                # Kullanicinin sectigi satir sayisi KOK tabloya uygulanir;
                # cocuk tablolar kardinaliteden turer.
                root = contract.table(contract.root_table)
                root.row_count_target = row_count
                for table in contract.tables:
                    table.faker_locale = locale
                    table.random_seed = seed
            except SchemaValidationError as exc:
                last_error = exc
                log.warning("Dataset Contract doğrulanamadı (deneme %d/%d): %s",
                            attempt, SCHEMA_MAX_RETRIES, exc)
                continue
            if attempt > 1:
                log.info("Dataset Contract %d. denemede duzeltildi", attempt)
            return contract

        raise SchemaValidationError(
            t("service.error.contract_retries", attempts=SCHEMA_MAX_RETRIES,
              error=last_error)
        )

    def generate_project_plan(self, project_prompt: str,
                             row_count: int = config.DEFAULT_ROW_TARGET,
                             seed: int = config.DEFAULT_RANDOM_SEED,
                             locale: str = "en_US",
                             seed_dataframe=None,
                             max_tables: int = 6):
        """Adım 2 (planlayici): proje tarifi -> :class:`ProjectPlan`.

        Sema uretimiyle ayni self-healing dongusu; fark, dogrulamanin yalnizca
        sozlesmeyi degil planin **ic tutarliligini** da denetlemesi (hedef degisken
        var mi, sizintili kolon gercekten disarida mi, sinif dengesi verilmis mi).
        """
        from ..core.project_planner import ProjectPlan
        from .planner_prompts import (
            PROJECT_PLAN_SYSTEM_PROMPT,
            PROJECT_PLAN_USER_TEMPLATE,
        )

        seed_block = ""
        if seed_dataframe is not None and len(seed_dataframe) > 0:
            seed_block = _build_seed_block(seed_dataframe)

        user = PROJECT_PLAN_USER_TEMPLATE.format(
            project_prompt=project_prompt.strip(),
            row_count=row_count,
            seed=seed,
            locale=locale,
            max_tables=max_tables,
            seed_block=seed_block,
        )

        last_error = None
        last_raw = ""
        for attempt in range(1, SCHEMA_MAX_RETRIES + 1):
            prompt = user if attempt == 1 else SCHEMA_FIX_TEMPLATE.format(
                original=user, previous=last_raw, error=str(last_error)
            )
            raw = self._complete(PROJECT_PLAN_SYSTEM_PROMPT, prompt,
                                 max_tokens=12000, temperature=0.5)
            last_raw = raw
            try:
                data = extract_json_block(raw)
                dataset = data.get("dataset")
                if isinstance(dataset, dict):
                    dataset["random_seed"] = seed
                plan = ProjectPlan.from_dict(data, project=project_prompt)
                # Satir sayisi KOK tabloya uygulanir; cocuklar kardinaliteden turer.
                root = plan.contract.table(plan.contract.root_table)
                root.row_count_target = row_count
                for table in plan.contract.tables:
                    table.faker_locale = locale
                    table.random_seed = seed
            except SchemaValidationError as exc:
                last_error = exc
                log.warning("Proje planı doğrulanamadı (deneme %d/%d): %s",
                            attempt, SCHEMA_MAX_RETRIES, exc)
                continue
            if attempt > 1:
                log.info("Proje planı %d. denemede duzeltildi", attempt)
            return plan

        raise SchemaValidationError(
            t("service.error.plan_retries", attempts=SCHEMA_MAX_RETRIES,
              error=last_error)
        )

    def generate_dataset_code(self, contract) -> str:
        """Adım 4 (iliskisel): Dataset Contract -> generate_dataset() kaynagi."""
        locale = contract.tables[0].faker_locale if contract.tables else "en_US"
        system = DATASET_CODE_SYSTEM_PROMPT.format(
            locale=locale, **self._sandbox_prompt_vars()
        )
        user = DATASET_CODE_USER_TEMPLATE.format(
            contract_json=contract.to_json(),
            generation_order=" -> ".join(contract.generation_order()),
            root_table=contract.root_table,
        )
        return strip_code_fences(
            self._complete(system, user, max_tokens=16000, temperature=0.3)
        )

    def generate_code(self, schema: SchemaContract) -> str:
        """Adım 4: Schema Contract -> generate_data() iceren Python kaynagi."""
        system = CODE_SYSTEM_PROMPT.format(
            locale=schema.faker_locale, **self._sandbox_prompt_vars()
        )
        user = CODE_USER_TEMPLATE.format(schema_json=schema.to_json())
        return strip_code_fences(self._complete(system, user, max_tokens=16000, temperature=0.3))

    def fix_code(self, previous_code: str, error_feedback: str,
                 schema: SchemaContract, history=None, escalate: bool = False) -> str:
        """Self-healing dongusu: hatayi geri besleyip duzeltilmis kaynagi al.

        Args:
            history: önceki denemelerin hata ozetleri - model aynı hatayi
                tekrarlamasin diye iletilir.
            escalate: aynı hata tekrar edildi; modelden yaklasimini komple
                degistirmesi istenir (kucuk yerel Modeller aynı tuzaga
                defalarca dusebiliyor).
        """
        system = FIX_SYSTEM_PROMPT.format(**self._sandbox_prompt_vars())
        history_block = ""
        if history:
            lines = ["- deneme %d: %s" % (i + 1, h) for i, h in enumerate(history)]
            history_block = HISTORY_BLOCK.format(history="\n".join(lines)[:2000])
        user = FIX_USER_TEMPLATE.format(
            schema_json=schema.to_json(),
            previous_code=previous_code,
            error_feedback=error_feedback[:6000],
            history_block=history_block,
            escalation_block=ESCALATION_BLOCK if escalate else "",
        )
        # Tekrar eden hatada sicakligi yukselt - ayni cikti yeniden uretilmesin.
        temperature = 0.6 if escalate else 0.2
        return strip_code_fences(
            self._complete(system, user, max_tokens=16000, temperature=temperature))

    def generate_dataset_card(self, schema: SchemaContract,
                              stats: Dict[str, Any]) -> str:
        """HuggingFace Hub için doğrulanmış dataset card (README.md) üretir."""
        import json
        user = CARD_USER_TEMPLATE.format(
            schema_json=schema.to_json(),
            stats_json=json.dumps(stats, ensure_ascii=False, indent=2, default=str)[:6000],
        )
        return strip_code_fences(
            self._complete(CARD_SYSTEM_PROMPT, user, max_tokens=4000, temperature=0.4)
        )


def _build_seed_block(seed_df, max_rows: int = 8) -> str:
    """HF seed veri setinin yapisini prompt'a sigacak sekilde özetler."""
    try:
        dtypes = "\n".join("- %s: %s" % (c, seed_df[c].dtype) for c in seed_df.columns[:40])
        try:
            describe = seed_df.describe(include="all").to_string(max_cols=15)[:2500]
        except Exception:
            describe = "(hesaplanamadi)"
        sample = seed_df.head(max_rows).to_string(max_cols=15)[:2500]
        return SEED_DATA_BLOCK.format(dtypes=dtypes, describe=describe, sample=sample)
    except Exception as exc:  # pragma: no cover
        log.warning("Seed veri özeti olusturulamadi: %s", exc)
        return ""
