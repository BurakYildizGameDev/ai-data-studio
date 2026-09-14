"""Schema Contract - Sentetik veri üretim ve doğrulama kontratı.

Adım 2'de LLM'in ürettiği çıktı katı bir JSON şemadır. Kod üretimi (generator),
validasyon (validator) ve iş kuralları bu sözleşmeyi referans alır.
Bu modül şemayı dataclass modellerine çevirir ve eksik/tutarsız alanları doğrular.

Ayrıca LLM yanıtlarından JSON bloğu ayıklayan extract_json_block() burada tanımlıdır;
hem şema üretiminde hem self-healing geri besleme döngüsünde kullanılır.
"""
from __future__ import annotations

import ast
import json
import math
import re
from statistics import NormalDist

from ..i18n import t
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    "SchemaValidationError",
    "ColumnSpec",
    "CorrelationRule",
    "MonotonicityRule",
    "SchemaContract",
    "extract_json_block",
]


class SchemaValidationError(ValueError):
    """Schema Contract dogrulanamadiginda firlatilir."""


# --------------------------------------------------------------------------- #
# Bolum 10.6 - LLM "JSON only" zorlamasi
# --------------------------------------------------------------------------- #
_FENCE_RE = re.compile(r"```(?:json|python)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json_block(text: str) -> Dict[str, Any]:
    """LLM yanitindan en distaki JSON nesnesini ayiklar ve parse eder.

    LLM'ler bazen JSON'un basina/sonuna açıklama ekler ("Here is your JSON: {...}")
    veya markdown fence icine sarar. Önce dogrudan parse denenir, sonra fence,
    en son da dengeli parantez taramasi yapılır.
    """
    if not isinstance(text, str) or not text.strip():
        raise SchemaValidationError(t("schema.error.empty_response"))

    candidates: List[str] = [text.strip()]
    for match in _FENCE_RE.finditer(text):
        candidates.append(match.group(1).strip())

    balanced = _find_balanced_object(text)
    if balanced:
        candidates.append(balanced)

    last_error: Optional[Exception] = None
    for candidate in candidates:
        if not candidate.startswith("{"):
            inner = _find_balanced_object(candidate)
            if not inner:
                continue
            candidate = inner
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            # Yerel modeller gecerli bir sozlesmeyi siklikla JSON disi kucuk
            # kusurlarla dondurur (// yorum, sondaki virgul, Python True/None).
            # Sozlesmeyi bu yuzden reddetmek bir tam LLM turuna mal oluyordu.
            try:
                parsed = json.loads(repair_json(candidate))
            except json.JSONDecodeError:
                continue
        if isinstance(parsed, dict):
            return parsed

    raise SchemaValidationError(
        t("schema.error.no_json")
        + (" (%s)" % last_error if last_error else "")
    )


_PY_LITERALS = {"True": "true", "False": "false", "None": "null"}


def repair_json(text: str) -> str:
    """LLM'lerin JSON'a kattigi sik kusurlari string-farkindalikli olarak temizler.

    * ``//`` ve ``#`` satir yorumlari, ``/* ... */`` blok yorumlari
    * ``}`` / ``]`` oncesindeki sondaki virgul
    * Python sabitleri ``True`` / ``False`` / ``None``

    String iceriklerine asla dokunmaz; gecerli JSON'u degistirmez.
    """
    out: List[str] = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
        elif text.startswith("//", i) or ch == "#":
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        elif ch.isalpha() or ch == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            word = text[i:j]
            out.append(_PY_LITERALS.get(word, word))
            i = j
        else:
            out.append(ch)
            i += 1
    return _strip_trailing_commas("".join(out))


def _strip_trailing_commas(text: str) -> str:
    """String disindaki, ardindan yalnizca bosluk ve ``}``/``]`` gelen virgulleri siler."""
    out: List[str] = []
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == ",":
            j = i + 1
            while j < len(text) and text[j].isspace():
                j += 1
            if j < len(text) and text[j] in "}]":
                continue
        out.append(ch)
    return "".join(out)


def _find_balanced_object(text: str) -> Optional[str]:
    """Metindeki ilk dengeli {...} blogunu string-farkindalikli olarak dondurur."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


# --------------------------------------------------------------------------- #
# Sozlesme modeli
# --------------------------------------------------------------------------- #
VALID_TYPES = {"int", "float", "bool", "str", "category", "datetime"}
NUMERIC_TYPES = {"int", "float"}
# bool da korelasyona girer - pandas onu sayisal kabul eder (point-biserial).
CORRELATABLE_TYPES = {"int", "float", "bool"}
VALID_DISTRIBUTIONS = {
    "normal", "uniform", "lognormal", "exponential", "poisson", "categorical", "custom",
    "gamma", "tweedie", "zip", "zero_inflated_poisson", "gpd", "pareto",
}
VALID_SIGNS = {"positive", "negative"}

# Modellerin gecerli dagilimlar icin kullandigi es anlamli adlar.
_DISTRIBUTION_ALIASES = {
    "gaussian": "normal", "norm": "normal",
    "log_normal": "lognormal", "lognorm": "lognormal",
    "exp": "exponential", "expon": "exponential",
    "zeroinflated_poisson": "zip", "zip_poisson": "zip",
    "generalized_pareto": "gpd", "generalised_pareto": "gpd", "genpareto": "gpd",
    "compound_poisson_gamma": "tweedie",
    "discrete_uniform": "uniform", "uniform_int": "uniform", "randint": "uniform",
    "integer_uniform": "uniform",
    "category": "categorical", "multinomial": "categorical", "choice": "categorical",
}
# bool kolonun dagilimi zaten target_ratio'lu Bernoulli'dir; bu adlar bilgi tasimaz.
_BOOL_DISTRIBUTIONS = {"bernoulli", "binomial", "binary"}

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# df.eval icinde ad gibi gorunen ama kolon olmayan sozcukler - kolon adi sanilmasinlar.
_RULE_KEYWORDS = {"abs", "true", "false"}

_SQL_IS_NOT_NULL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s+is\s+not\s+null\b", re.I)
_SQL_IS_NULL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s+is\s+null\b", re.I)
# IN: canli kosu (14.09, 1.5b) `return_status IN (True, False)` yazdi.
_SQL_KEYWORDS = re.compile(r"\b(AND|OR|NOT|IN)\b")
_SQL_SINGLE_EQUALS = re.compile(r"(?<![<>=!])=(?!=)")


def normalize_rule(rule: str) -> str:
    """SQL aliskanligiyla yazilmis bir kurali ``df.eval`` diline cevirir.

    Istemler SQL'i acikca yasakliyor, ama canli kosuda model yine
    ``not is_returned and return_date is null`` yazdi ve kural sessizce atlandi.
    Anlami tartismasiz donusumler: ``x IS NULL`` -> ``x != x`` (NaN kendine esit
    degildir), ``x IS NOT NULL`` -> ``x == x``, ``AND/OR/NOT`` -> kucuk harf,
    tek ``=`` -> ``==``.

    Sozlesme dogrulamasi ve validator ayni donusumu kullanir; ayri kalsalardi
    sozlesme, validator'in sorunsuz uyguladigi bir kural icin uyari basardi.
    """
    text = _SQL_IS_NOT_NULL.sub(r"(\1 == \1)", rule)
    text = _SQL_IS_NULL.sub(r"(\1 != \1)", text)
    text = _SQL_KEYWORDS.sub(lambda m: m.group(1).lower(), text)
    return _SQL_SINGLE_EQUALS.sub("==", text)


def _parse_rule(rule: str) -> Optional[ast.Expression]:
    try:
        return ast.parse(normalize_rule(rule).strip(), mode="eval")
    except (SyntaxError, ValueError):
        return None


def rule_names(rule: str) -> Optional[set]:
    """Kuralin atif yaptigi adlar; ifade olarak parse edilemiyorsa ``None``.

    Duzenli ifadeyle ad toplamak tirnak icindeki degerleri de ad sayiyordu
    (``status == 'active'`` -> ``active`` "tanimsiz ad"). AST yalnizca gercek
    ad dugumlerini verir.
    """
    tree = _parse_rule(rule)
    if tree is None:
        return None
    return {node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name)} - _RULE_KEYWORDS


def conjuncts(node: ast.expr) -> List[ast.expr]:
    """Üst düzey ``and`` zincirini parçalarına ayırır (``or`` bütün kalır)."""
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        parts: List[ast.expr] = []
        for value in node.values:
            parts.extend(conjuncts(value))
        return parts
    return [node]


def _pinned_bool_column(node: ast.expr, bool_columns: set) -> Optional[str]:
    """Parça bir bool kolonu tek değere sabitliyorsa o kolonun adı.

    ``col``, ``not col``, ``col == False``, ``col != 1``, ``col is True`` biçimleri.
    """
    if isinstance(node, ast.Name) and node.id in bool_columns:
        return node.id
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)
            and isinstance(node.operand, ast.Name) and node.operand.id in bool_columns):
        return node.operand.id
    if (isinstance(node, ast.Compare) and len(node.ops) == 1
            and isinstance(node.ops[0], (ast.Eq, ast.NotEq, ast.Is, ast.IsNot))):
        sides = (node.left, node.comparators[0])
        for name, other in (sides, sides[::-1]):
            if (isinstance(name, ast.Name) and name.id in bool_columns
                    and isinstance(other, ast.Constant)
                    and other.value in (True, False, 0, 1)):
                return name.id
    return None


def _is_text_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return bool(node.elts) and all(_is_text_literal(e) for e in node.elts)
    return False


def rule_text_compared_columns(rule: str, non_text_columns: set) -> List[str]:
    """Kuralda metin sabitiyle karsilastirilan sayisal/bool kolonlar.

    Canli kosu (14.09, qwen2.5-coder:1.5b): ``churned in ['True', 'False']`` - bool
    kolon hicbir zaman bir metne esit olmaz, kural her satirda yanlis ve validator
    verinin %100'unu sildi.
    """
    tree = _parse_rule(rule)
    if tree is None:
        return []
    found: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left] + list(node.comparators)
        if any(_is_text_literal(o) for o in operands):
            found.extend(o.id for o in operands
                         if isinstance(o, ast.Name) and o.id in non_text_columns)
    return sorted(set(found))


@dataclass
class ColumnSpec:
    """Tek bir kolonun sozlesmesi."""

    name: str
    type: str
    min: Optional[float] = None
    max: Optional[float] = None
    distribution: Optional[str] = None
    mean: Optional[float] = None
    std: Optional[float] = None
    target_ratio: Optional[float] = None   # bool kolonlar icin True orani
    categories: Optional[List[Any]] = None  # category kolonlar icin
    nullable: bool = False
    description: str = ""
    # Aktüeryal ve kuyruk dağılım parametreleri
    shape: Optional[float] = None          # Gamma/Pareto/GPD şekil parametresi
    scale: Optional[float] = None          # Gamma/Pareto/GPD ölçek parametresi
    zero_prob: Optional[float] = None      # Zero-Inflated Poisson (ZIP) sıfır hasar olasılığı (0..1)
    p_index: Optional[float] = None        # Tweedie güç parametresi (1 < p < 2, Compound Poisson-Gamma)

    @classmethod
    def from_dict(cls, data: Any, index: int,
                  notes: Optional[List[str]] = None) -> "ColumnSpec":
        """Ham kolon nesnesini dogrular.

        Args:
            notes: verilirse, reddetmek yerine duzeltilen kusurlarin uyarilari
                buraya eklenir (bkz. :func:`_normalize_column`).
        """
        where = "columns[%d]" % index
        if not isinstance(data, dict):
            raise SchemaValidationError(
                t("schema.error.must_be_object", where=where,
                  got=type(data).__name__))
        data = _normalize_column(data, notes if notes is not None else [])

        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SchemaValidationError(t("schema.error.name_required", where=where))
        name = name.strip()
        if not _IDENTIFIER_RE.fullmatch(name):
            raise SchemaValidationError(
                t("schema.error.bad_identifier", where=where, name=name))

        ctype = data.get("type")
        if not isinstance(ctype, str) or ctype.lower() not in VALID_TYPES:
            raise SchemaValidationError(
                t("schema.error.bad_type", where=where, name=name,
                  valid=sorted(VALID_TYPES)))
        ctype = ctype.lower()

        spec = cls(
            name=name,
            type=ctype,
            min=_as_number(data.get("min"), where, "min"),
            max=_as_number(data.get("max"), where, "max"),
            distribution=(data.get("distribution") or None),
            mean=_as_number(data.get("mean"), where, "mean"),
            std=_as_number(data.get("std"), where, "std"),
            target_ratio=_as_number(data.get("target_ratio"), where, "target_ratio"),
            categories=list(data["categories"]) if isinstance(data.get("categories"), list) else None,
            nullable=bool(data.get("nullable", False)),
            description=str(data.get("description") or ""),
            shape=_as_number(data.get("shape"), where, "shape"),
            scale=_as_number(data.get("scale"), where, "scale"),
            zero_prob=_as_number(data.get("zero_prob"), where, "zero_prob"),
            p_index=_as_number(data.get("p_index"), where, "p_index"),
        )
        spec._validate(where)
        return spec

    def _validate(self, where: str) -> None:
        if self.distribution and self.distribution.lower() not in VALID_DISTRIBUTIONS:
            raise SchemaValidationError(
                t("schema.error.bad_distribution", where=where, name=self.name,
                  distribution=self.distribution,
                  valid=sorted(VALID_DISTRIBUTIONS))
            )
        if self.distribution:
            self.distribution = self.distribution.lower()
        if self.min is not None and self.max is not None and self.min > self.max:
            raise SchemaValidationError(
                t("schema.error.min_gt_max", where=where, name=self.name,
                  low=self.min, high=self.max)
            )
        if self.target_ratio is not None and not 0.0 <= self.target_ratio <= 1.0:
            raise SchemaValidationError(
                t("schema.error.target_ratio_range", where=where, name=self.name,
                  value=self.target_ratio)
            )
        if self.zero_prob is not None and not 0.0 <= self.zero_prob <= 1.0:
            raise SchemaValidationError(
                t("schema.error.zero_prob_range", where=where, name=self.name,
                  value=self.zero_prob)
            )
        if self.p_index is not None and not 1.0 < self.p_index < 2.0:
            raise SchemaValidationError(
                t("schema.error.p_index_range", where=where, name=self.name,
                  value=self.p_index)
            )
        if self.std is not None and self.std < 0:
            raise SchemaValidationError(
                t("schema.error.std_negative", where=where, name=self.name))
        if self.shape is not None and self.shape <= 0:
            raise SchemaValidationError(
                t("schema.error.shape_positive", where=where, name=self.name))
        if self.scale is not None and self.scale <= 0:
            raise SchemaValidationError(
                t("schema.error.scale_positive", where=where, name=self.name))
        if self.type == "category" and not self.categories:
            raise SchemaValidationError(
                t("schema.error.categories_required", where=where, name=self.name)
            )
        if self.distribution == "normal" and self.mean is None:
            raise SchemaValidationError(
                t("schema.error.mean_required", where=where, name=self.name)
            )

    @property
    def is_numeric(self) -> bool:
        return self.type in NUMERIC_TYPES

    @property
    def is_correlatable(self) -> bool:
        """Korelasyon hesabina girebilir mi?

        bool dahildir: pandas bool'u sayısal kabul eder ve sayısal bir kolonla
        arasindaki korelasyon geçerli bir point-biserial katsayidir
        (or. izleme süresi <-> tiklandi mi).
        """
        return self.type in CORRELATABLE_TYPES

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"name": self.name, "type": self.type}
        for key in ("min", "max", "distribution", "mean", "std", "target_ratio",
                    "categories", "description", "shape", "scale", "zero_prob", "p_index"):
            value = getattr(self, key)
            if value not in (None, ""):
                out[key] = value
        if self.nullable:
            out["nullable"] = True
        return out


@dataclass
class CorrelationRule:
    """İki kolon arasında hedeflenen korelasyon kuralı."""

    columns: List[str]
    expected_sign: str = "positive"
    min_r: float = 0.0
    method: str = "pearson"  # pearson, spearman, kendall

    @classmethod
    def from_dict(cls, data: Any, index: int) -> "CorrelationRule":
        where = "correlations[%d]" % index
        if not isinstance(data, dict):
            raise SchemaValidationError(
                t("schema.error.must_be_object", where=where, got=type(data).__name__))
        cols = data.get("columns")
        if not isinstance(cols, (list, tuple)) or len(cols) != 2:
            raise SchemaValidationError(t("schema.error.correlation_pair", where=where))
        sign = str(data.get("expected_sign", "positive")).lower()
        if sign not in VALID_SIGNS:
            raise SchemaValidationError(
                t("schema.error.expected_sign", where=where, sign=sign)
            )
        min_r = _as_number(data.get("min_r", 0.0), where, "min_r") or 0.0
        if not 0.0 <= abs(min_r) <= 1.0:
            raise SchemaValidationError(t("schema.error.min_r_range", where=where))

        method = str(data.get("method", "pearson")).lower().strip()
        if method not in {"pearson", "spearman", "kendall"}:
            method = "pearson"

        return cls(
            columns=[str(c) for c in cols],
            expected_sign=sign,
            min_r=abs(float(min_r)),
            method=method,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "columns": list(self.columns),
            "expected_sign": self.expected_sign,
            "min_r": self.min_r,
            "method": self.method,
        }


@dataclass
class MonotonicityRule:
    """İki kolon arasında beklenen monotonluk (monotonicity) kuralı.

    Özellikle kredi skor kartları (Basel III / Scorecards) ve risk modellerinde
    X1 > X2 ==> Y1 >= Y2 monotonic trendini veya WoE (Weight of Evidence) yönünü denetler.
    """

    column_x: str
    column_y: str
    direction: str = "increasing"  # "increasing" (positive) veya "decreasing" (negative)
    min_compliance_ratio: float = 0.90  # Binned / quantile bazında en az %90 monotonluk uyumu

    @classmethod
    def from_dict(cls, data: Any, index: int) -> "MonotonicityRule":
        where = "monotonicity_rules[%d]" % index
        if not isinstance(data, dict):
            raise SchemaValidationError(
                t("schema.error.must_be_object", where=where, got=type(data).__name__))

        col_x = data.get("column_x") or data.get("x")
        col_y = data.get("column_y") or data.get("y")
        if not col_x or not col_y:
            cols = data.get("columns")
            if isinstance(cols, (list, tuple)) and len(cols) == 2:
                col_x, col_y = cols[0], cols[1]

        if not col_x or not col_y:
            raise SchemaValidationError(
                t("schema.error.monotonicity_columns", where=where)
            )

        direction = str(data.get("direction", "increasing")).lower().strip()
        if direction in {"positive", "inc", "artik", "artisi"}:
            direction = "increasing"
        elif direction in {"negative", "dec", "azalis", "azalan"}:
            direction = "decreasing"

        if direction not in {"increasing", "decreasing"}:
            raise SchemaValidationError(
                t("schema.error.direction", where=where, direction=direction)
            )

        min_ratio = _as_number(data.get("min_compliance_ratio", 0.90), where, "min_compliance_ratio") or 0.90
        if not 0.0 < min_ratio <= 1.0:
            raise SchemaValidationError(
                t("schema.error.min_compliance_range", where=where))

        return cls(
            column_x=str(col_x).strip(),
            column_y=str(col_y).strip(),
            direction=direction,
            min_compliance_ratio=float(min_ratio),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "column_x": self.column_x,
            "column_y": self.column_y,
            "direction": self.direction,
            "min_compliance_ratio": self.min_compliance_ratio,
        }


@dataclass
class SchemaContract:
    """Pipeline'in tüm adimlarinin okudugu merkezi veri sozlesmesi."""

    domain: str
    row_count_target: int
    columns: List[ColumnSpec]
    random_seed: int = 42
    business_rules: List[str] = field(default_factory=list)
    correlations: List[CorrelationRule] = field(default_factory=list)
    monotonicity_rules: List[MonotonicityRule] = field(default_factory=list)
    faker_locale: str = "en_US"
    description: str = ""
    warnings: List[str] = field(default_factory=list)
    preserve_anomaly_column: Optional[str] = None
    preserve_anomaly_value: Any = None
    # -- iliskisel (cok tablolu) alanlar --------------------------------- #
    # Tek tablolu kullanimda bos kalirlar; DatasetContract icinde anlam
    # kazanirlar. name verilmezse domain'e duser.
    name: str = ""
    primary_key: Optional[str] = None
    foreign_keys: List[str] = field(default_factory=list)

    # -- kurulum ---------------------------------------------------------- #
    @classmethod
    def from_dict(cls, data: Any) -> "SchemaContract":
        """Ham dict'i doğrular ve sozlesmeye çevirir. Hatada SchemaValidationError."""
        if not isinstance(data, dict):
            raise SchemaValidationError(
                t("schema.error.contract_object", got=type(data).__name__)
            )

        missing = [k for k in ("domain", "columns") if k not in data]
        if missing:
            raise SchemaValidationError(t("schema.error.missing_fields", fields=missing))

        domain = data.get("domain")
        if not isinstance(domain, str) or not domain.strip():
            raise SchemaValidationError(t("schema.error.domain_required"))

        raw_columns = data.get("columns")
        if not isinstance(raw_columns, list) or not raw_columns:
            raise SchemaValidationError(t("schema.error.columns_required"))

        notes: List[str] = []
        columns = [ColumnSpec.from_dict(c, i, notes) for i, c in enumerate(raw_columns)]
        names = [c.name for c in columns]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise SchemaValidationError(t("schema.error.duplicate_columns",
                                          columns=duplicates))

        row_count_target = data.get("row_count_target", 100_000)
        try:
            row_count_target = int(row_count_target)
        except (TypeError, ValueError):
            raise SchemaValidationError(
                t("schema.error.row_count_int", value=row_count_target)
            ) from None
        if row_count_target <= 0:
            raise SchemaValidationError(t("schema.error.row_count_positive"))

        try:
            random_seed = int(data.get("random_seed", 42))
        except (TypeError, ValueError):
            raise SchemaValidationError(t("schema.error.seed_int")) from None

        raw_rules = data.get("business_rules", []) or []
        if not isinstance(raw_rules, list):
            raise SchemaValidationError(t("schema.error.rules_list"))
        business_rules = [str(r).strip() for r in raw_rules if str(r).strip()]

        raw_corr = data.get("correlations", []) or []
        if not isinstance(raw_corr, list):
            raise SchemaValidationError(t("schema.error.correlations_list"))
        correlations = [CorrelationRule.from_dict(c, i) for i, c in enumerate(raw_corr)]

        raw_mono = data.get("monotonicity_rules", []) or []
        if not isinstance(raw_mono, list):
            raise SchemaValidationError(t("schema.error.monotonicity_list"))
        monotonicity_rules = [MonotonicityRule.from_dict(m, i) for i, m in enumerate(raw_mono)]

        preserve_anomaly_column = data.get("preserve_anomaly_column")
        preserve_anomaly_value = data.get("preserve_anomaly_value")

        contract = cls(
            domain=domain.strip(),
            row_count_target=row_count_target,
            columns=columns,
            random_seed=random_seed,
            business_rules=business_rules,
            correlations=correlations,
            monotonicity_rules=monotonicity_rules,
            faker_locale=str(data.get("faker_locale") or "en_US"),
            description=str(data.get("description") or ""),
            preserve_anomaly_column=str(preserve_anomaly_column).strip() if preserve_anomaly_column else None,
            preserve_anomaly_value=preserve_anomaly_value,
            name=str(data.get("name") or "").strip(),
            primary_key=(str(data.get("primary_key")).strip()
                         if data.get("primary_key") else None),
            foreign_keys=[str(k).strip() for k in (data.get("foreign_keys") or [])
                          if str(k).strip()],
            warnings=notes,
        )
        contract._validate_keys()
        contract._cross_validate()
        return contract

    @classmethod
    def from_json(cls, text: str) -> "SchemaContract":
        """Ham LLM yanitindan (açıklama metni sarilmis olabilir) sozlesme üretir."""
        return cls.from_dict(extract_json_block(text))

    @property
    def table_name(self) -> str:
        """Iliskisel baglamda tablo adi; verilmemisse domain'e duser."""
        return self.name or self.domain

    def _validate_keys(self) -> None:
        """primary_key / foreign_keys gercekten var olan kolonlara isaret etmeli."""
        known = self.column_names
        if self.primary_key and self.primary_key not in known:
            raise SchemaValidationError(
                t("schema.error.primary_key_missing", table=self.table_name,
                  pk=self.primary_key)
            )
        missing = [k for k in self.foreign_keys if k not in known]
        if missing:
            raise SchemaValidationError(
                t("schema.error.foreign_keys_missing", table=self.table_name, keys=missing)
            )

    def _cross_validate(self) -> None:
        """Kurallarin/korelasyonlarin var olmayan kolonlara atif yapmadigini denetler."""
        known = self.column_names

        # Korelasyon kurallari SEMA URETIMININ yan urunudur; hatali bir kural
        # yuzunden tum pipeline'i dusurmek yerine o kurali dusurup uyari veriyoruz.
        # (Sema uretimi ayrica llm_base icinde yeniden denenir.)
        valid_correlations = []
        for rule in self.correlations:
            unknown = [c for c in rule.columns if c not in known]
            if unknown:
                self.warnings.append(
                    t("schema.warning.correlation_unknown_columns",
                      columns=unknown, known=sorted(known))
                )
                continue
            bad = [c for c in rule.columns if not self.column(c).is_correlatable]
            if bad:
                self.warnings.append(
                    t("schema.warning.correlation_not_numeric", columns=bad)
                )
                continue
            ceiling = self._binary_correlation_ceiling(rule)
            if ceiling is not None and rule.min_r > ceiling:
                # Tavanin %80'i: parametrik motor tek surucuyle tavanin ~%84'une
                # ulasabiliyor (latent katsayi 0.95'te kirpiliyor, gurultu payi kaliyor;
                # olcum: p=0.10, tavan 0.585, gerceklesen 0.494). %90 hedef kil payi kaciyordu.
                lowered = math.floor(ceiling * 0.8 * 100) / 100
                self.warnings.append(t("schema.warning.correlation_above_ceiling",
                                       columns=rule.columns, requested="%g" % rule.min_r,
                                       ceiling="%.2f" % ceiling, lowered="%.2f" % lowered))
                rule.min_r = lowered
            valid_correlations.append(rule)
        self.correlations = valid_correlations

        # Monotonluk kuralları doğrulaması
        valid_monotonic = []
        for m_rule in self.monotonicity_rules:
            if m_rule.column_x not in known or m_rule.column_y not in known:
                self.warnings.append(
                    t("schema.warning.monotonicity_unknown_columns",
                      x=m_rule.column_x, y=m_rule.column_y, known=sorted(known))
                )
                continue
            if not self.column(m_rule.column_x).is_correlatable or not self.column(m_rule.column_y).is_correlatable:
                self.warnings.append(
                    t("schema.warning.monotonicity_not_numeric",
                      x=m_rule.column_x, y=m_rule.column_y)
                )
                continue
            valid_monotonic.append(m_rule)
        self.monotonicity_rules = valid_monotonic

        # Is kurallari serbest ifade oldugu icin sert hata yerine uyariyla DUSURULUR.
        # Eskiden uyari basilip kural tutuluyordu: validator onu zaten atliyordu ama
        # kod istemi modele var olmayan kolonlari "uygula" diyordu. Kucuk modeller
        # istemdeki ornek kurali (`watch_time_s <= ad_duration_s`) baska bir domaine
        # kopyaliyor, ya da `defaulted is boolean` gibi ifade olmayan bir cumle yaziyor.
        valid_rules = []
        non_text = {c.name for c in self.columns if c.type in ("int", "float", "bool")}
        # Orani iki sinif da iceren bool kolonlar (target_ratio verilmemisse motor %50 kullanir).
        two_class = {c.name for c in self.columns if c.type == "bool"
                     and (c.target_ratio is None or 0.0 < c.target_ratio < 1.0)}
        for rule in self.business_rules:
            mismatched = rule_text_compared_columns(rule, non_text)
            if mismatched:
                self.warnings.append(t("schema.warning.rule_type_mismatch", rule=rule,
                                       columns=mismatched))
                continue
            rule = self._without_pinned_bools(rule, two_class)
            if rule is None:
                continue
            referenced = rule_names(rule)
            if referenced is None:
                self.warnings.append(t("schema.warning.rule_unparseable", rule=rule))
                continue
            unknown = sorted(referenced - known)
            if unknown:
                self.warnings.append(
                    t("schema.warning.rule_unknown_names", rule=rule, names=unknown)
                )
                continue
            if not referenced:
                self.warnings.append(t("schema.warning.rule_unparseable", rule=rule))
                continue
            valid_rules.append(rule)
        self.business_rules = valid_rules

        if self.preserve_anomaly_column and self.preserve_anomaly_column not in known:
            self.warnings.append(
                t("schema.warning.preserve_column_missing",
                  column=self.preserve_anomaly_column, known=sorted(known))
            )

    def _binary_correlation_ceiling(self, rule: "CorrelationRule") -> Optional[float]:
        """Bir bool kolonun bu kuralda ulaşabileceği en yüksek |r|; bool yoksa ``None``.

        True oranı ``p`` olan ikili bir kolonun normal bir sürücüyle nokta-çift serili
        korelasyonu en fazla ``phi(z) / sqrt(p(1-p))`` olabilir (``z = Phi^-1(1-p)``);
        iki ikili kolon arasındaki phi katsayısı en fazla
        ``sqrt(p1(1-p2) / (p2(1-p1)))`` (``p1 <= p2``). Canlı 1.5b şemalarında oranı %5-10
        olan hedeflere 0.6-0.9 istendi (tavan ~0.47-0.58): hiçbir veri bunu sağlayamaz,
        doğrulama her koşuda "geçmedi" diyordu.
        """
        ratios = []
        for name in rule.columns:
            col = self.column(name)
            if col.type == "bool":
                ratios.append(0.5 if col.target_ratio is None else col.target_ratio)
        if not ratios:
            return None
        if any(not 0.0 < p < 1.0 for p in ratios):
            return None     # tek sinifli kolonun korelasyonu zaten tanimsiz
        if len(ratios) == 2:
            low, high = sorted(ratios)
            return math.sqrt(low * (1 - high) / (high * (1 - low)))
        p = ratios[0]
        z = NormalDist().inv_cdf(1 - p)
        return NormalDist().pdf(z) / math.sqrt(p * (1 - p))

    def _without_pinned_bools(self, rule: str, two_class: set) -> Optional[str]:
        """İki sınıflı bir bool kolonu tek değere sabitleyen ``and`` parçalarını çıkarır.

        Canlı koşular (2026-09-14, qwen2.5-coder:1.5b): ``loan_default == False`` ve
        ``order_return_status = 0``. Validator bu kuralla pozitif sınıfın TAMAMINI
        siliyordu (satırların %4,9 / %9,8'i) - veri seti etiketini kaybediyor ama
        tutulan satır oranı iyi göründüğü için kimse fark etmiyordu. Kural geri kalan
        parçalarıyla korunur; hiçbir parça kalmazsa ``None`` döner.
        """
        tree = _parse_rule(rule)
        if tree is None or not two_class:
            return rule
        parts = conjuncts(tree.body)
        pinned = [_pinned_bool_column(part, two_class) for part in parts]
        if not any(pinned):
            return rule
        columns = sorted({name for name in pinned if name})
        kept = [part for part, name in zip(parts, pinned) if not name]
        self.warnings.append(t("schema.warning.rule_pins_bool", rule=rule, columns=columns))
        if not kept:
            return None
        return " and ".join(ast.unparse(part) for part in kept)

    # -- erisim ----------------------------------------------------------- #
    @property
    def column_names(self) -> set:
        return {c.name for c in self.columns}

    @property
    def numeric_columns(self) -> List[str]:
        return [c.name for c in self.columns if c.is_numeric]

    def column(self, name: str) -> ColumnSpec:
        for col in self.columns:
            if col.name == name:
                return col
        raise KeyError(name)

    # -- serilestirme ----------------------------------------------------- #
    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "domain": self.domain,
            "row_count_target": self.row_count_target,
            "random_seed": self.random_seed,
            "faker_locale": self.faker_locale,
            "columns": [c.to_dict() for c in self.columns],
            "business_rules": list(self.business_rules),
            "correlations": [c.to_dict() for c in self.correlations],
            "monotonicity_rules": [m.to_dict() for m in self.monotonicity_rules],
        }
        if self.description:
            out["description"] = self.description
        if self.name:
            out["name"] = self.name
        if self.primary_key:
            out["primary_key"] = self.primary_key
        if self.foreign_keys:
            out["foreign_keys"] = list(self.foreign_keys)
        if self.preserve_anomaly_column:
            out["preserve_anomaly_column"] = self.preserve_anomaly_column
        if self.preserve_anomaly_value is not None:
            out["preserve_anomaly_value"] = self.preserve_anomaly_value
        return out

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def summary(self) -> str:
        """Konsola basmak için tek satirlik ozet (arayuz dilinde)."""
        text = t("schema.summary", domain=self.domain, columns=len(self.columns),
                 rows=format(self.row_count_target, ","), seed=self.random_seed,
                 rules=len(self.business_rules), correlations=len(self.correlations))
        if self.monotonicity_rules:
            text += t("schema.summary.monotonicity", count=len(self.monotonicity_rules))
        if self.preserve_anomaly_column:
            text += t("schema.summary.anomaly", column=self.preserve_anomaly_column)
        return text


def _is_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None or value == "":
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _normalize_column(data: Dict[str, Any], notes: List[str]) -> Dict[str, Any]:
    """Modelin sik yaptigi, anlami belli kusurlari reddetmek yerine duzeltir.

    Canli olcum (qwen2.5-coder:14b, 6 sema yaniti): altisi de ilk denemede reddedildi -
    dordu datetime kolonuna ``min: "2022-01-01"`` yazdi, biri ``beta``, biri bool icin
    ``bernoulli`` kullandi. Her ret 50-90 sn'lik bir LLM turuydu ve model duzeltme
    turunda ayni hatayi tekrarladi. Anlami tartismasiz olan bu durumlarda sozlesme
    duzeltilir ve uyari ``notes``'a yazilir; belirsiz olanlar yine reddedilir.
    """
    data = dict(data)
    name = str(data.get("name") or "?")
    ctype = str(data.get("type") or "").strip().lower()

    raw = data.get("distribution")
    if raw not in (None, ""):
        key = re.sub(r"[\s\-]+", "_", raw.strip().lower()) if isinstance(raw, str) else ""
        key = _DISTRIBUTION_ALIASES.get(key, key)
        if key in VALID_DISTRIBUTIONS:
            data["distribution"] = key
        else:
            data["distribution"] = None
            if not (ctype == "bool" and key in _BOOL_DISTRIBUTIONS):
                notes.append(t("schema.warning.distribution_dropped",
                               column=name, distribution=raw))

    if ctype == "datetime":
        textual = {k: data[k] for k in ("min", "max")
                   if data.get(k) not in (None, "") and not _is_number(data[k])}
        if textual:
            for k in textual:
                data.pop(k)
            low, high = textual.get("min"), textual.get("max")
            if low is not None and high is not None:
                span = "between %s and %s" % (low, high)
            elif low is not None:
                span = "from %s" % low
            else:
                span = "until %s" % high
            # Aralik aciklamaya tasinir: kod istemi datetime araligini oradan okur
            # (bkz. prompt_blocks.DATETIME_BLOCK). LLM'e gidecegi icin Ingilizce.
            description = str(data.get("description") or "").strip()
            data["description"] = ("%s (%s)" % (description, span)).strip()
            notes.append(t("schema.warning.datetime_bounds_moved", column=name, range=span))

    # Bool kolonun ortalamasi True oranidir. Canli kosu (14.09, qwen2.5-coder:1.5b):
    # `"churned": {"type": "bool", "mean": 0.1}` yazdi; target_ratio bos kaldigi icin
    # parametrik motor %50 churn uretti.
    if (ctype == "bool" and data.get("target_ratio") in (None, "")
            and _is_number(data.get("mean")) and 0.0 <= float(data["mean"]) <= 1.0):
        data["target_ratio"] = float(data.pop("mean"))
        notes.append(t("schema.warning.bool_mean_as_ratio", column=name,
                       ratio="%g" % data["target_ratio"]))

    # Istem eskiden `"p_index": <1..2>` diyordu, dogrulayici ise 1 < p < 2 istiyor.
    # Canli kosu (14.09, qwen2.5-coder:1.5b): `p_index: 1.0` uc denemede de reddedildi ve
    # pipeline FAILED oldu. Sinirin kendisi istemin davet ettigi deger - parametre
    # dusurulur (motor kullanmiyor, kod istemi varsayilana doner). Sinir disi
    # degerler (2.5 gibi) hala reddedilir.
    if _is_number(data.get("p_index")) and float(data["p_index"]) in (1.0, 2.0):
        notes.append(t("schema.warning.p_index_boundary_dropped", column=name,
                       value="%g" % float(data.pop("p_index"))))

    if data.get("distribution") == "normal" and not _is_number(data.get("mean")):
        low, high = data.get("min"), data.get("max")
        if _is_number(low) and _is_number(high):
            data["mean"] = (float(low) + float(high)) / 2.0
            notes.append(t("schema.warning.normal_mean_filled", column=name,
                           mean="%g" % data["mean"]))
        else:
            data["distribution"] = None
            notes.append(t("schema.warning.distribution_dropped",
                           column=name, distribution="normal"))
    return data


def _as_number(value: Any, where: str, key: str) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise SchemaValidationError(
            t("schema.error.numeric_bool", where=where, field=key))
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SchemaValidationError(
            t("schema.error.numeric_expected", where=where, field=key, value=value)
        ) from None
