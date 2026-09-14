"""Proje planlayici - proje tarifinden egitime hazir bir veri sozlesmesi cikarir.

Bu modul, kullaniciyi "bana su kolonlari uret" demekten kurtarir: projesini anlatir,
plan hangi verinin gerektigine karar verir. Ciktisi bir ``DatasetContract`` **ve** onu
kullanilabilir kilan makine ogrenmesi kararlaridir.

Neden yalnizca kolon listesi yetmez: bir veri seti, hedef degiskeni belirsizse, sinif
dengesi soylenmemisse, sizinti (leakage) yaratan kolonlar ayiklanmamissa ya da train/test
ayriminin ne anlama geldigi yazilmamissa "egitime hazir" degildir. Plan bu dordunu
acikca tasir.

**Dogrulama felsefesi:** Planin *kendisi* bir yargidir, karsilastirilacak bir dogru cevap
yoktur. Ama **ic tutarliligi** dogrulanabilir ve dogrulanir:

* hedef kolon sozlesmede gercekten var mi,
* sizintili ilan edilen kolonlar sozlesmeden gercekten CIKARILMIS mi
  (aksi halde "ayikladim" demek anlamsizdir),
* siniflandirmada sinif dengesi verilmis ve makul bir aralikta mi,
* bolme stratejisinin dayandigi kolon var mi ve dogru turde mi,
* planin sinif dengesi ile semanin ``target_ratio``'su birbiriyle celisiyor mu.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .dataset_contract import DatasetContract
from ..i18n import t
from .schema_contract import SchemaValidationError, extract_json_block

__all__ = [
    "TASK_TYPES",
    "SPLIT_KINDS",
    "LeakageExclusion",
    "SplitStrategy",
    "TargetSpec",
    "ProjectPlan",
]

# Planin hedefleyebilecegi gorev turleri. Siniflandirma turleri sinif dengesi ister.
TASK_TYPES = {
    "binary_classification",
    "multiclass_classification",
    "regression",
    "forecasting",
    "unsupervised",
}
_CLASSIFICATION = {"binary_classification", "multiclass_classification"}

# Train/test ayriminin anlami. "random" her zaman dogru cevap degildir: zamana bagli
# bir problemde rastgele bolme gelecekten gecmise bilgi sizdirir, iliskisel veride ayni
# musterinin satirlari iki tarafa dagilirsa model kimligi ezberler.
SPLIT_KINDS = {"random", "temporal", "group"}

# Cok dengesiz bir hedef anlamli bir plan degildir; bu araligin disi uyari uretir.
_RATIO_WARN_LOW = 0.005
_RATIO_WARN_HIGH = 0.95


def _require_str(data: Dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(
            t("contract.error.field_required", where=where, field=key)
        )
    return value.strip()


@dataclass
class LeakageExclusion:
    """Sozlesmeye BILEREK konmamis, sizinti yaratacak bir kolon.

    Bunlar uretilmeyecek kolonlardir: hedef olay gerceklestikten sonra bilinen,
    dolayisiyla egitimde kullanilirsa modeli gelecege baktiran alanlar.
    """

    column: str
    reason: str

    @classmethod
    def from_dict(cls, data: Any, index: int) -> "LeakageExclusion":
        where = "excluded_leakage[%d]" % index
        if not isinstance(data, dict):
            raise SchemaValidationError(
                t("schema.error.must_be_object", where=where,
                  got=type(data).__name__)
            )
        return cls(column=_require_str(data, "column", where),
                   reason=_require_str(data, "reason", where))

    def to_dict(self) -> Dict[str, str]:
        return {"column": self.column, "reason": self.reason}


@dataclass
class SplitStrategy:
    """Train/test ayriminin nasil yapilmasi gerektigi ve nedeni."""

    kind: str
    reason: str
    column: str = ""          # temporal -> zaman kolonu, group -> gruplama anahtari
    table: str = ""           # kolonun ait oldugu tablo (iliskisel planlarda gerekli)

    @classmethod
    def from_dict(cls, data: Any) -> "SplitStrategy":
        where = "split"
        if not isinstance(data, dict):
            raise SchemaValidationError(
                t("schema.error.must_be_object", where=where,
                  got=type(data).__name__)
            )
        kind = _require_str(data, "kind", where).lower()
        if kind not in SPLIT_KINDS:
            raise SchemaValidationError(
                t("plan.error.split_kind", where=where, valid=sorted(SPLIT_KINDS))
            )
        return cls(
            kind=kind,
            reason=_require_str(data, "reason", where),
            column=str(data.get("column") or "").strip(),
            table=str(data.get("table") or "").strip(),
        )

    def to_dict(self) -> Dict[str, str]:
        out = {"kind": self.kind, "reason": self.reason}
        if self.column:
            out["column"] = self.column
        if self.table:
            out["table"] = self.table
        return out


@dataclass
class TargetSpec:
    """Modelin tahmin edecegi degisken."""

    table: str
    column: str

    @classmethod
    def from_dict(cls, data: Any) -> "TargetSpec":
        where = "target"
        if not isinstance(data, dict):
            raise SchemaValidationError(
                t("schema.error.must_be_object", where=where,
                  got=type(data).__name__)
            )
        return cls(table=_require_str(data, "table", where),
                   column=_require_str(data, "column", where))

    def to_dict(self) -> Dict[str, str]:
        return {"table": self.table, "column": self.column}

    def label(self) -> str:
        return "%s.%s" % (self.table, self.column)


@dataclass
class ProjectPlan:
    """Bir proje tarifinden cikarilmis veri plani."""

    project: str
    contract: DatasetContract
    task_type: str
    rationale: str
    target: Optional[TargetSpec] = None
    positive_class_ratio: Optional[float] = None
    excluded_leakage: List[LeakageExclusion] = field(default_factory=list)
    split: Optional[SplitStrategy] = None
    warnings: List[str] = field(default_factory=list)

    # -- kurulum ---------------------------------------------------------- #
    @classmethod
    def from_dict(cls, data: Any, project: str = "") -> "ProjectPlan":
        if not isinstance(data, dict):
            raise SchemaValidationError(
                t("plan.error.plan_object", got=type(data).__name__)
            )

        raw_dataset = data.get("dataset")
        if raw_dataset is None:
            raise SchemaValidationError(t("plan.error.dataset_required"))
        contract = DatasetContract.from_dict(raw_dataset)

        task_type = _require_str(data, "task_type", "plan").lower()
        if task_type not in TASK_TYPES:
            raise SchemaValidationError(
                t("plan.error.task_type", valid=sorted(TASK_TYPES))
            )

        target = None
        if data.get("target") is not None:
            target = TargetSpec.from_dict(data["target"])

        raw_leakage = data.get("excluded_leakage")
        if raw_leakage is None:
            raise SchemaValidationError(t("plan.error.leakage_required"))
        if not isinstance(raw_leakage, list):
            raise SchemaValidationError(t("plan.error.leakage_list"))
        exclusions = [LeakageExclusion.from_dict(item, i)
                      for i, item in enumerate(raw_leakage)]

        split = SplitStrategy.from_dict(data["split"]) if data.get("split") else None

        ratio = data.get("positive_class_ratio")
        if ratio is not None:
            try:
                ratio = float(ratio)
            except (TypeError, ValueError):
                raise SchemaValidationError(
                    t("plan.error.class_ratio_number", value=repr(ratio))
                ) from None

        plan = cls(
            project=(project or str(data.get("project") or "")).strip(),
            contract=contract,
            task_type=task_type,
            rationale=str(data.get("rationale") or "").strip(),
            target=target,
            positive_class_ratio=ratio,
            excluded_leakage=exclusions,
            split=split,
        )
        plan._validate()
        return plan

    @classmethod
    def from_json(cls, text: str, project: str = "") -> "ProjectPlan":
        return cls.from_dict(extract_json_block(text), project=project)

    # -- ic tutarlilik ----------------------------------------------------- #
    def _validate(self) -> None:
        supervised = self.task_type != "unsupervised"

        # 1) Hedef degisken: gozetimli bir gorevde zorunlu ve sozlesmede var olmali.
        if supervised:
            if self.target is None:
                raise SchemaValidationError(
                    t("plan.error.target_required", task=self.task_type)
                )
            table = self._table_or_raise(self.target.table, "target")
            if self.target.column not in table.column_names:
                raise SchemaValidationError(
                    t("plan.error.target_column_missing", column=self.target.column,
                      table=self.target.table, columns=sorted(table.column_names))
                )
        elif self.target is not None:
            self.warnings.append(
                t("plan.warning.unsupervised_target", target=self.target.label())
            )
            self.target = None

        # 2) Sizinti: ayiklandigi soylenen kolon sozlesmede DURUYORSA plan kendiyle
        #    celisir. Bu, planlayicinin en kolay kandirdigi yer.
        contract_columns = {
            (t.table_name, c.name) for t in self.contract.tables for c in t.columns
        }
        bare_names = {name for _, name in contract_columns}
        still_present = sorted(
            excl.column for excl in self.excluded_leakage if excl.column in bare_names
        )
        if still_present:
            raise SchemaValidationError(
                t("plan.error.leakage_still_present", columns=still_present)
            )
        if supervised and not self.excluded_leakage:
            self.warnings.append(
                t("plan.warning.no_leakage")
            )

        # 3) Hedef kolonun kendisi sizinti listesinde olamaz.
        if self.target is not None:
            leaked = [e.column for e in self.excluded_leakage
                      if e.column == self.target.column]
            if leaked:
                raise SchemaValidationError(
                    t("plan.error.target_is_leakage", column=self.target.column)
                )

        # 4) Sinif dengesi: siniflandirmada zorunlu, regresyonda anlamsiz.
        if self.task_type in _CLASSIFICATION:
            if self.positive_class_ratio is None:
                raise SchemaValidationError(
                    t("plan.error.class_ratio_required", task=self.task_type)
                )
            if not 0.0 < self.positive_class_ratio < 1.0:
                raise SchemaValidationError(
                    t("plan.error.class_ratio_range",
                      value=self.positive_class_ratio)
                )
            if not _RATIO_WARN_LOW <= self.positive_class_ratio <= _RATIO_WARN_HIGH:
                self.warnings.append(
                    t("plan.warning.class_ratio_extreme",
                      ratio="%.3f" % self.positive_class_ratio)
                )
        elif self.positive_class_ratio is not None:
            self.warnings.append(
                t("plan.warning.class_ratio_ignored", task=self.task_type)
            )
            self.positive_class_ratio = None

        # 5) Bolme stratejisi: dayandigi kolon gercekten var mi ve dogru turde mi.
        if self.split is not None:
            self._validate_split()
        elif supervised:
            self.warnings.append(t("plan.warning.no_split"))

        # 6) Plan ile semanin sinif dengesi celismemeli.
        self._check_target_ratio_agreement()

    def _table_or_raise(self, name: str, where: str):
        try:
            return self.contract.table(name)
        except KeyError:
            raise SchemaValidationError(
                t("plan.error.table_missing", where=where, table=name,
                  tables=self.contract.table_names)
            ) from None

    def _validate_split(self) -> None:
        split = self.split
        if split.kind == "random":
            return

        if not split.column:
            raise SchemaValidationError(
                t("plan.error.split_column_required", kind=split.kind)
            )
        table_name = split.table or (self.target.table if self.target
                                     else self.contract.root_table)
        table = self._table_or_raise(table_name, "split")
        column = next((c for c in table.columns if c.name == split.column), None)
        if column is None:
            raise SchemaValidationError(
                t("plan.error.split_column_missing", column=split.column,
                  table=table_name)
            )
        split.table = table_name

        if split.kind == "temporal" and column.type != "datetime":
            raise SchemaValidationError(
                t("plan.error.split_not_datetime", column=column.name,
                  got=column.type)
            )

    def _check_target_ratio_agreement(self) -> None:
        """Bool hedefte plan orani ile semadaki ``target_ratio`` ayni seyi soylemeli."""
        column = self.target_column_spec()
        if column is None or self.positive_class_ratio is None:
            return
        if column.type != "bool":
            return
        if column.target_ratio is None:
            # Plan uretimi yonlendirsin: karar plandaysa sema onu tasimali.
            column.target_ratio = self.positive_class_ratio
        elif abs(column.target_ratio - self.positive_class_ratio) > 0.02:
            raise SchemaValidationError(
                t("plan.error.ratio_disagreement",
                  plan_ratio="%.3f" % self.positive_class_ratio,
                  target=self.target.label(),
                  column_ratio="%.3f" % column.target_ratio)
            )

    # -- erisim ------------------------------------------------------------ #
    def target_column_spec(self):
        """Hedef kolonun :class:`ColumnSpec`'i; hedef yoksa None."""
        if self.target is None:
            return None
        table = self.contract.table(self.target.table)
        return next((c for c in table.columns if c.name == self.target.column), None)

    @property
    def is_supervised(self) -> bool:
        return self.task_type != "unsupervised"

    def summary(self) -> str:
        """Konsola basmak icin tek satirlik ozet."""
        parts = [t("plan.summary.task", task=self.task_type)]
        if self.target is not None:
            parts.append(t("plan.summary.target", target=self.target.label()))
        if self.positive_class_ratio is not None:
            parts.append(t("plan.summary.positive_class", ratio=t(
                "common.percent", value="%.1f" % (self.positive_class_ratio * 100))))
        parts.append(t("plan.summary.tables", count=len(self.contract.tables)))
        if self.excluded_leakage:
            parts.append(t("plan.summary.leakage", count=len(self.excluded_leakage)))
        if self.split is not None:
            parts.append(t("plan.summary.split", kind=self.split.kind))
        return " | ".join(parts)

    # -- serilestirme ------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "project": self.project,
            "task_type": self.task_type,
            "rationale": self.rationale,
            "excluded_leakage": [e.to_dict() for e in self.excluded_leakage],
            "dataset": self.contract.to_dict(),
        }
        if self.target is not None:
            out["target"] = self.target.to_dict()
        if self.positive_class_ratio is not None:
            out["positive_class_ratio"] = self.positive_class_ratio
        if self.split is not None:
            out["split"] = self.split.to_dict()
        if self.warnings:
            out["warnings"] = list(self.warnings)
        return out

    def to_json(self, indent: int = 2) -> str:
        import json

        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
