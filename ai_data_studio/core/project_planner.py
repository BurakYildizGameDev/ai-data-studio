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
            "%s: '%s' bos olmayan bir metin olmali" % (where, key)
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
                "%s bir nesne olmali, %s geldi" % (where, type(data).__name__)
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
                "%s bir nesne olmali, %s geldi" % (where, type(data).__name__)
            )
        kind = _require_str(data, "kind", where).lower()
        if kind not in SPLIT_KINDS:
            raise SchemaValidationError(
                "%s: 'kind' su degerlerden biri olmali: %s" % (where, sorted(SPLIT_KINDS))
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
                "%s bir nesne olmali, %s geldi" % (where, type(data).__name__)
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
                "Proje plani bir JSON nesnesi olmali, %s geldi" % type(data).__name__
            )

        raw_dataset = data.get("dataset")
        if raw_dataset is None:
            raise SchemaValidationError("'dataset' alani zorunlu (Dataset Contract)")
        contract = DatasetContract.from_dict(raw_dataset)

        task_type = _require_str(data, "task_type", "plan").lower()
        if task_type not in TASK_TYPES:
            raise SchemaValidationError(
                "'task_type' su degerlerden biri olmali: %s" % sorted(TASK_TYPES)
            )

        target = None
        if data.get("target") is not None:
            target = TargetSpec.from_dict(data["target"])

        raw_leakage = data.get("excluded_leakage")
        if raw_leakage is None:
            raise SchemaValidationError(
                "'excluded_leakage' alani zorunlu - sizinti yaratacak kolonlari "
                "dusundugunu gostermelisin (hicbiri yoksa bos liste ver)"
            )
        if not isinstance(raw_leakage, list):
            raise SchemaValidationError("'excluded_leakage' bir liste olmali")
        exclusions = [LeakageExclusion.from_dict(item, i)
                      for i, item in enumerate(raw_leakage)]

        split = SplitStrategy.from_dict(data["split"]) if data.get("split") else None

        ratio = data.get("positive_class_ratio")
        if ratio is not None:
            try:
                ratio = float(ratio)
            except (TypeError, ValueError):
                raise SchemaValidationError(
                    "'positive_class_ratio' sayi olmali, %r geldi" % (ratio,)
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
                    "'%s' gorevinde 'target' zorunlu - hedef degiskeni olmayan bir "
                    "veri seti egitime hazir degildir" % self.task_type
                )
            table = self._table_or_raise(self.target.table, "target")
            if self.target.column not in table.column_names:
                raise SchemaValidationError(
                    "Hedef kolon '%s' '%s' tablosunda yok. Tanimli kolonlar: %s"
                    % (self.target.column, self.target.table, sorted(table.column_names))
                )
        elif self.target is not None:
            self.warnings.append(
                "Gorev 'unsupervised' ama bir hedef degisken verilmis (%s) - yok sayildi."
                % self.target.label()
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
                "Sizintili ilan edilen kolon(lar) sozlesmede hala duruyor: %s. "
                "Ayiklanan kolonlar uretilmemeli - ya sozlesmeden cikar ya da "
                "sizinti listesinden." % still_present
            )
        if supervised and not self.excluded_leakage:
            self.warnings.append(
                "Hicbir sizinti kolonu ayiklanmamis. Cogu gercek problemde hedef olay "
                "sonrasi bilinen en az bir alan vardir; plan bunu dusunmemis olabilir."
            )

        # 3) Hedef kolonun kendisi sizinti listesinde olamaz.
        if self.target is not None:
            leaked = [e.column for e in self.excluded_leakage
                      if e.column == self.target.column]
            if leaked:
                raise SchemaValidationError(
                    "Hedef kolon '%s' ayni zamanda sizinti olarak isaretlenmis"
                    % self.target.column
                )

        # 4) Sinif dengesi: siniflandirmada zorunlu, regresyonda anlamsiz.
        if self.task_type in _CLASSIFICATION:
            if self.positive_class_ratio is None:
                raise SchemaValidationError(
                    "'%s' gorevinde 'positive_class_ratio' zorunlu - sinif dengesi "
                    "belirtilmemis bir siniflandirma veri seti kullanisli degildir"
                    % self.task_type
                )
            if not 0.0 < self.positive_class_ratio < 1.0:
                raise SchemaValidationError(
                    "'positive_class_ratio' 0 ile 1 arasinda olmali, %r geldi"
                    % (self.positive_class_ratio,)
                )
            if not _RATIO_WARN_LOW <= self.positive_class_ratio <= _RATIO_WARN_HIGH:
                self.warnings.append(
                    "Sinif dengesi asiri (%.3f): bu orandaki bir hedef, uretilen satir "
                    "sayisinda anlamli sayida ornek vermeyebilir."
                    % self.positive_class_ratio
                )
        elif self.positive_class_ratio is not None:
            self.warnings.append(
                "'%s' gorevinde sinif dengesi anlamsiz - yok sayildi." % self.task_type
            )
            self.positive_class_ratio = None

        # 5) Bolme stratejisi: dayandigi kolon gercekten var mi ve dogru turde mi.
        if self.split is not None:
            self._validate_split()
        elif supervised:
            self.warnings.append(
                "Train/test ayrimi belirtilmemis - varsayilan rastgele bolme dogru "
                "olmayabilir (zamana bagli ya da ayni varliga ait satirlar varsa)."
            )

        # 6) Plan ile semanin sinif dengesi celismemeli.
        self._check_target_ratio_agreement()

    def _table_or_raise(self, name: str, where: str):
        try:
            return self.contract.table(name)
        except KeyError:
            raise SchemaValidationError(
                "%s: '%s' tablosu sozlesmede yok. Tanimli tablolar: %s"
                % (where, name, self.contract.table_names)
            ) from None

    def _validate_split(self) -> None:
        split = self.split
        if split.kind == "random":
            return

        if not split.column:
            raise SchemaValidationError(
                "split: '%s' bolme icin 'column' zorunlu" % split.kind
            )
        table_name = split.table or (self.target.table if self.target
                                     else self.contract.root_table)
        table = self._table_or_raise(table_name, "split")
        column = next((c for c in table.columns if c.name == split.column), None)
        if column is None:
            raise SchemaValidationError(
                "split: '%s' kolonu '%s' tablosunda yok" % (split.column, table_name)
            )
        split.table = table_name

        if split.kind == "temporal" and column.type != "datetime":
            raise SchemaValidationError(
                "split: zamana gore bolme icin '%s' bir 'datetime' kolonu olmali, "
                "'%s' turunde" % (column.name, column.type)
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
                "Plan sinif dengesini %.3f diyor ama '%s' kolonunun target_ratio'su "
                "%.3f. Ikisi ayni sayiyi soylemeli."
                % (self.positive_class_ratio, self.target.label(), column.target_ratio)
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
        parts = ["gorev: %s" % self.task_type]
        if self.target is not None:
            parts.append("hedef: %s" % self.target.label())
        if self.positive_class_ratio is not None:
            parts.append("pozitif sinif: %%%.1f" % (self.positive_class_ratio * 100))
        parts.append("%d tablo" % len(self.contract.tables))
        if self.excluded_leakage:
            parts.append("%d sizinti kolonu ayiklandi" % len(self.excluded_leakage))
        if self.split is not None:
            parts.append("bolme: %s" % self.split.kind)
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
