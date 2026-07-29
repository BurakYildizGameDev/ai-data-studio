"""Schema Contract - Sentetik veri üretim ve doğrulama kontratı.

Adım 2'de LLM'in ürettiği çıktı katı bir JSON şemadır. Kod üretimi (generator),
validasyon (validator) ve iş kuralları bu sözleşmeyi referans alır.
Bu modül şemayı dataclass modellerine çevirir ve eksik/tutarsız alanları doğrular.

Ayrıca LLM yanıtlarından JSON bloğu ayıklayan extract_json_block() burada tanımlıdır;
hem şema üretiminde hem self-healing geri besleme döngüsünde kullanılır.
"""
from __future__ import annotations

import json
import re
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
        raise SchemaValidationError("LLM yaniti boş - JSON blogu bulunamadı")

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
            continue
        if isinstance(parsed, dict):
            return parsed

    raise SchemaValidationError(
        "LLM yanitinda geçerli JSON blogu bulunamadı"
        + (" (%s)" % last_error if last_error else "")
    )


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

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# df.eval icinde kullanilan operator/anahtar kelimeler - kolon adi sanilmasinlar.
_RULE_KEYWORDS = {
    "and", "or", "not", "in", "True", "False", "None", "abs", "true", "false",
}


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
    def from_dict(cls, data: Any, index: int) -> "ColumnSpec":
        where = "columns[%d]" % index
        if not isinstance(data, dict):
            raise SchemaValidationError("%s bir nesne olmalı, %s geldi" % (where, type(data).__name__))

        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SchemaValidationError("%s: 'name' zorunlu ve boş olmayan bir metin olmalı" % where)
        name = name.strip()
        if not _IDENTIFIER_RE.fullmatch(name):
            raise SchemaValidationError(
                "%s: kolon adı '%s' geçersiz - df.eval ile kullanilabilmesi için "
                "sadece harf/rakam/alt cizgi icermeli ve rakamla baslamamali" % (where, name)
            )

        ctype = data.get("type")
        if not isinstance(ctype, str) or ctype.lower() not in VALID_TYPES:
            raise SchemaValidationError(
                "%s ('%s'): 'type' su degerlerden biri olmalı: %s"
                % (where, name, sorted(VALID_TYPES))
            )
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
                "%s ('%s'): bilinmeyen distribution '%s' - geçerli: %s"
                % (where, self.name, self.distribution, sorted(VALID_DISTRIBUTIONS))
            )
        if self.distribution:
            self.distribution = self.distribution.lower()
        if self.min is not None and self.max is not None and self.min > self.max:
            raise SchemaValidationError(
                "%s ('%s'): min (%s) max'tan (%s) büyük olamaz"
                % (where, self.name, self.min, self.max)
            )
        if self.target_ratio is not None and not 0.0 <= self.target_ratio <= 1.0:
            raise SchemaValidationError(
                "%s ('%s'): target_ratio 0..1 araliginda olmalı, %s geldi"
                % (where, self.name, self.target_ratio)
            )
        if self.zero_prob is not None and not 0.0 <= self.zero_prob <= 1.0:
            raise SchemaValidationError(
                "%s ('%s'): zero_prob 0..1 araliginda olmalı, %s geldi"
                % (where, self.name, self.zero_prob)
            )
        if self.p_index is not None and not 1.0 < self.p_index < 2.0:
            raise SchemaValidationError(
                "%s ('%s'): tweedie p_index 1..2 araliginda olmalı (Compound Poisson-Gamma), %s geldi"
                % (where, self.name, self.p_index)
            )
        if self.std is not None and self.std < 0:
            raise SchemaValidationError("%s ('%s'): std negatif olamaz" % (where, self.name))
        if self.shape is not None and self.shape <= 0:
            raise SchemaValidationError("%s ('%s'): shape pozitif olmalı" % (where, self.name))
        if self.scale is not None and self.scale <= 0:
            raise SchemaValidationError("%s ('%s'): scale pozitif olmalı" % (where, self.name))
        if self.type == "category" and not self.categories:
            raise SchemaValidationError(
                "%s ('%s'): type 'category' ise 'categories' listesi zorunlu" % (where, self.name)
            )
        if self.distribution == "normal" and self.mean is None:
            raise SchemaValidationError(
                "%s ('%s'): distribution 'normal' ise 'mean' zorunlu" % (where, self.name)
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
            raise SchemaValidationError("%s bir nesne olmalı" % where)
        cols = data.get("columns")
        if not isinstance(cols, (list, tuple)) or len(cols) != 2:
            raise SchemaValidationError("%s: 'columns' tam olarak 2 kolon adı icermeli" % where)
        sign = str(data.get("expected_sign", "positive")).lower()
        if sign not in VALID_SIGNS:
            raise SchemaValidationError(
                "%s: expected_sign 'positive' veya 'negative' olmalı, '%s' geldi" % (where, sign)
            )
        min_r = _as_number(data.get("min_r", 0.0), where, "min_r") or 0.0
        if not 0.0 <= abs(min_r) <= 1.0:
            raise SchemaValidationError("%s: min_r -1..1 araliginda olmalı" % where)

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
            raise SchemaValidationError("%s bir nesne olmalı" % where)

        col_x = data.get("column_x") or data.get("x")
        col_y = data.get("column_y") or data.get("y")
        if not col_x or not col_y:
            cols = data.get("columns")
            if isinstance(cols, (list, tuple)) and len(cols) == 2:
                col_x, col_y = cols[0], cols[1]

        if not col_x or not col_y:
            raise SchemaValidationError(
                "%s: 'column_x' ve 'column_y' (veya 2 elemanlı 'columns') zorunlu" % where
            )

        direction = str(data.get("direction", "increasing")).lower().strip()
        if direction in {"positive", "inc", "artik", "artisi"}:
            direction = "increasing"
        elif direction in {"negative", "dec", "azalis", "azalan"}:
            direction = "decreasing"

        if direction not in {"increasing", "decreasing"}:
            raise SchemaValidationError(
                "%s: direction 'increasing' veya 'decreasing' olmalı, '%s' geldi" % (where, direction)
            )

        min_ratio = _as_number(data.get("min_compliance_ratio", 0.90), where, "min_compliance_ratio") or 0.90
        if not 0.0 < min_ratio <= 1.0:
            raise SchemaValidationError("%s: min_compliance_ratio 0..1 aralığında olmalı" % where)

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
                "Schema Contract bir JSON nesnesi olmalı, %s geldi" % type(data).__name__
            )

        missing = [k for k in ("domain", "columns") if k not in data]
        if missing:
            raise SchemaValidationError("Schema Contract'ta zorunlu alan(lar) eksik: %s" % missing)

        domain = data.get("domain")
        if not isinstance(domain, str) or not domain.strip():
            raise SchemaValidationError("'domain' boş olmayan bir metin olmalı")

        raw_columns = data.get("columns")
        if not isinstance(raw_columns, list) or not raw_columns:
            raise SchemaValidationError("'columns' en az bir kolon iceren bir liste olmalı")

        columns = [ColumnSpec.from_dict(c, i) for i, c in enumerate(raw_columns)]
        names = [c.name for c in columns]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise SchemaValidationError("Tekrarlanan kolon adları: %s" % duplicates)

        row_count_target = data.get("row_count_target", 100_000)
        try:
            row_count_target = int(row_count_target)
        except (TypeError, ValueError):
            raise SchemaValidationError(
                "'row_count_target' tam sayı olmalı, %r geldi" % (row_count_target,)
            ) from None
        if row_count_target <= 0:
            raise SchemaValidationError("'row_count_target' pozitif olmalı")

        try:
            random_seed = int(data.get("random_seed", 42))
        except (TypeError, ValueError):
            raise SchemaValidationError("'random_seed' tam sayı olmalı") from None

        raw_rules = data.get("business_rules", []) or []
        if not isinstance(raw_rules, list):
            raise SchemaValidationError("'business_rules' bir liste olmalı")
        business_rules = [str(r).strip() for r in raw_rules if str(r).strip()]

        raw_corr = data.get("correlations", []) or []
        if not isinstance(raw_corr, list):
            raise SchemaValidationError("'correlations' bir liste olmalı")
        correlations = [CorrelationRule.from_dict(c, i) for i, c in enumerate(raw_corr)]

        raw_mono = data.get("monotonicity_rules", []) or []
        if not isinstance(raw_mono, list):
            raise SchemaValidationError("'monotonicity_rules' bir liste olmalı")
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
                "'%s' tablosunda primary_key '%s' kolonlar arasinda yok"
                % (self.table_name, self.primary_key)
            )
        missing = [k for k in self.foreign_keys if k not in known]
        if missing:
            raise SchemaValidationError(
                "'%s' tablosunda foreign_keys kolonlar arasinda yok: %s"
                % (self.table_name, missing)
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
                    "Korelasyon kuralı dusuruldu - bilinmeyen kolon(lar) %s (tanımlı: %s)"
                    % (unknown, sorted(known))
                )
                continue
            bad = [c for c in rule.columns if not self.column(c).is_correlatable]
            if bad:
                self.warnings.append(
                    "Korelasyon kuralı dusuruldu - %s sayısal/bool değil, korelasyon "
                    "hesaplanamaz" % bad
                )
                continue
            valid_correlations.append(rule)
        self.correlations = valid_correlations

        # Monotonluk kuralları doğrulaması
        valid_monotonic = []
        for m_rule in self.monotonicity_rules:
            if m_rule.column_x not in known or m_rule.column_y not in known:
                self.warnings.append(
                    "Monotonluk kuralı düşürüldü - bilinmeyen kolon(lar) [%s, %s] (tanımlı: %s)"
                    % (m_rule.column_x, m_rule.column_y, sorted(known))
                )
                continue
            if not self.column(m_rule.column_x).is_correlatable or not self.column(m_rule.column_y).is_correlatable:
                self.warnings.append(
                    "Monotonluk kuralı düşürüldü - [%s, %s] sayısal/bool değil"
                    % (m_rule.column_x, m_rule.column_y)
                )
                continue
            valid_monotonic.append(m_rule)
        self.monotonicity_rules = valid_monotonic

        # Is kurallari serbest ifade oldugu icin sert hata yerine uyari uretilir;
        # validator zaten parse edilemeyen kurali atlar (Bolum 6.4).
        for rule in self.business_rules:
            referenced = {
                token for token in _IDENTIFIER_RE.findall(rule)
                if token not in _RULE_KEYWORDS
            }
            unknown = sorted(referenced - known)
            if unknown:
                self.warnings.append(
                    "İş kuralı '%s' tanımlı olmayan ad(lar) iceriyor: %s" % (rule, unknown)
                )

        if self.preserve_anomaly_column and self.preserve_anomaly_column not in known:
            self.warnings.append(
                "preserve_anomaly_column '%s' tanımlı kolonlar arasında bulunamadı: %s"
                % (self.preserve_anomaly_column, sorted(known))
            )

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
        """Konsola/loga basmak için tek satirlik ozet."""
        anom_str = (" | anomali koruma: %s" % self.preserve_anomaly_column) if self.preserve_anomaly_column else ""
        mono_str = (" | %d monotonluk" % len(self.monotonicity_rules)) if self.monotonicity_rules else ""
        return ("%s | %d kolon | hedef %s satır | seed %d | %d kural | %d korelasyon%s%s"
                % (self.domain, len(self.columns), format(self.row_count_target, ","),
                   self.random_seed, len(self.business_rules), len(self.correlations), mono_str, anom_str))


def _as_number(value: Any, where: str, key: str) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise SchemaValidationError("%s: '%s' sayısal olmalı, boolean geldi" % (where, key))
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SchemaValidationError(
            "%s: '%s' sayısal olmalı, %r geldi" % (where, key, value)
        ) from None
