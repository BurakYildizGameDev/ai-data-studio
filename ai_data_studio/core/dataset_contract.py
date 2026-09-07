"""Iliskisel (cok tablolu) veri sozlesmesi.

``SchemaContract`` tek bir tabloyu tarif eder. ``DatasetContract`` birden fazla
tabloyu ve aralarindaki yabanci anahtar iliskilerini tarif eder; tek tablolu
kullanim bunun ``N=1`` ozel durumudur, ayri bir kod yolu degildir.

Tasarim notlari:

* Iliskiler bir DAG olmak zorunda. ``generation_order()`` topolojik sirayi
  dondurur; sandbox once ebeveyn tablolari uretip cocuklarin yabanci anahtarlarini
  ebeveynin GERCEK anahtar dizisinden cekebilsin diye bu sira zorunlu.
* ``root_table`` ``--rows`` sayisinin hangi tabloya ait oldugunu sabitler.
  Cocuk tablolarin buyuklugu kardinaliteden turer, kullanicidan alinmaz.
* Dogrulama katmani degismeden calisir: her tabloya mevcut ``run_validation``
  uygulanir, iliskiler ayrica denetlenir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from ..i18n import t

from .schema_contract import (
    SchemaContract,
    SchemaValidationError,
    extract_json_block,
)

__all__ = ["Relationship", "DatasetContract", "MAX_TABLES"]

MAX_TABLES = 12           # LLM'in kontrolsuz sema uretmesine karsi sert ust sinir


@dataclass
class Relationship:
    """Bir ebeveyn-cocuk yabanci anahtar iliskisi ve kardinalitesi."""

    parent_table: str
    parent_key: str
    child_table: str
    child_key: str
    # Ebeveyn basina cocuk satir sayisi dagilimi.
    mean_per_parent: float = 3.0
    min_per_parent: int = 0
    max_per_parent: Optional[int] = None
    # Cocuk tarafinda yabanci anahtar bos birakilabilir mi (opsiyonel iliski).
    nullable: bool = False
    description: str = ""

    @classmethod
    def from_dict(cls, data: Any, index: int) -> "Relationship":
        where = "relationships[%d]" % index
        if not isinstance(data, dict):
            raise SchemaValidationError(
                t("schema.error.must_be_object", where=where, got=type(data).__name__)
            )

        def _req(key: str) -> str:
            value = data.get(key)
            if not isinstance(value, str) or not value.strip():
                raise SchemaValidationError(
                    t("contract.error.field_required", where=where, field=key)
                )
            return value.strip()

        try:
            mean_per_parent = float(data.get("mean_per_parent", 3.0))
        except (TypeError, ValueError):
            raise SchemaValidationError(t("contract.error.mean_per_parent_number", where=where)) from None
        if mean_per_parent <= 0:
            raise SchemaValidationError(t("contract.error.mean_per_parent_positive", where=where))

        try:
            min_per_parent = int(data.get("min_per_parent", 0))
        except (TypeError, ValueError):
            raise SchemaValidationError(t("contract.error.min_per_parent_int", where=where)) from None
        if min_per_parent < 0:
            raise SchemaValidationError("%s: 'min_per_parent' negatif olamaz" % where)

        raw_max = data.get("max_per_parent")
        max_per_parent: Optional[int] = None
        if raw_max is not None:
            try:
                max_per_parent = int(raw_max)
            except (TypeError, ValueError):
                raise SchemaValidationError(
                    t("contract.error.max_per_parent_int", where=where)
                ) from None
            if max_per_parent < min_per_parent:
                raise SchemaValidationError(
                    t("contract.error.max_lt_min", where=where,
                      high=max_per_parent, low=min_per_parent)
                )

        return cls(
            parent_table=_req("parent_table"),
            parent_key=_req("parent_key"),
            child_table=_req("child_table"),
            child_key=_req("child_key"),
            mean_per_parent=mean_per_parent,
            min_per_parent=min_per_parent,
            max_per_parent=max_per_parent,
            nullable=bool(data.get("nullable", False)),
            description=str(data.get("description") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "parent_table": self.parent_table,
            "parent_key": self.parent_key,
            "child_table": self.child_table,
            "child_key": self.child_key,
            "mean_per_parent": self.mean_per_parent,
            "min_per_parent": self.min_per_parent,
        }
        if self.max_per_parent is not None:
            out["max_per_parent"] = self.max_per_parent
        if self.nullable:
            out["nullable"] = True
        if self.description:
            out["description"] = self.description
        return out

    def label(self) -> str:
        return "%s.%s -> %s.%s" % (self.parent_table, self.parent_key,
                                   self.child_table, self.child_key)


@dataclass
class DatasetContract:
    """Bir veya daha fazla iliskili tablonun sozlesmesi."""

    domain: str
    tables: List[SchemaContract]
    root_table: str = ""
    relationships: List[Relationship] = field(default_factory=list)
    random_seed: int = 42
    description: str = ""
    warnings: List[str] = field(default_factory=list)

    # -- kurulum ---------------------------------------------------------- #
    @classmethod
    def from_dict(cls, data: Any) -> "DatasetContract":
        if not isinstance(data, dict):
            raise SchemaValidationError(
                t("contract.error.contract_object", got=type(data).__name__)
            )

        # Tek tablolu bir Schema Contract da kabul edilir: N=1 olarak sarilir.
        if "tables" not in data and "columns" in data:
            return cls.from_schema(SchemaContract.from_dict(data))

        domain = data.get("domain")
        if not isinstance(domain, str) or not domain.strip():
            raise SchemaValidationError(t("schema.error.domain_required"))

        raw_tables = data.get("tables")
        if not isinstance(raw_tables, list) or not raw_tables:
            raise SchemaValidationError(t("contract.error.tables_required"))
        if len(raw_tables) > MAX_TABLES:
            raise SchemaValidationError(
                "'tables' en fazla %d tablo icerebilir, %d geldi"
                % (MAX_TABLES, len(raw_tables))
            )

        tables = [SchemaContract.from_dict(t) for t in raw_tables]

        names = [t.table_name for t in tables]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise SchemaValidationError(t("contract.error.duplicate_tables",
                                          tables=duplicates))

        raw_rel = data.get("relationships", []) or []
        if not isinstance(raw_rel, list):
            raise SchemaValidationError(t("contract.error.relationships_list"))
        relationships = [Relationship.from_dict(r, i) for i, r in enumerate(raw_rel)]

        try:
            random_seed = int(data.get("random_seed", tables[0].random_seed))
        except (TypeError, ValueError):
            raise SchemaValidationError(t("schema.error.seed_int")) from None

        contract = cls(
            domain=domain.strip(),
            tables=tables,
            root_table=str(data.get("root_table") or "").strip(),
            relationships=relationships,
            random_seed=random_seed,
            description=str(data.get("description") or ""),
        )
        contract._cross_validate()
        return contract

    @classmethod
    def from_json(cls, text: str) -> "DatasetContract":
        return cls.from_dict(extract_json_block(text))

    @classmethod
    def from_schema(cls, schema: SchemaContract) -> "DatasetContract":
        """Tek tablolu bir sozlesmeyi N=1 dataset olarak sarar."""
        return cls(
            domain=schema.domain,
            tables=[schema],
            root_table=schema.table_name,
            relationships=[],
            random_seed=schema.random_seed,
            description=schema.description,
        )

    # -- dogrulama -------------------------------------------------------- #
    def _cross_validate(self) -> None:
        by_name = {t.table_name: t for t in self.tables}

        if not self.root_table:
            self.root_table = self._infer_root(by_name)
        if self.root_table not in by_name:
            raise SchemaValidationError(
                "root_table '%s' tablolar arasinda yok: %s"
                % (self.root_table, sorted(by_name))
            )

        for rel in self.relationships:
            for role, table_name, key in (
                ("parent", rel.parent_table, rel.parent_key),
                ("child", rel.child_table, rel.child_key),
            ):
                table = by_name.get(table_name)
                if table is None:
                    raise SchemaValidationError(
                        t("contract.error.relationship_table_missing",
                          label=rel.label(), side=role, table=table_name)
                    )
                if key not in table.column_names:
                    raise SchemaValidationError(
                        t("contract.error.relationship_column_missing",
                          label=rel.label(), column=key, table=table_name)
                    )
            if rel.parent_table == rel.child_table:
                raise SchemaValidationError(
                    t("contract.error.self_parent", label=rel.label())
                )

        # Uretim sirasi cikarilabiliyor mu (dongu var mi)?
        self.generation_order()

    def _infer_root(self, by_name: Dict[str, SchemaContract]) -> str:
        """Hicbir iliskide cocuk olmayan tabloyu kok kabul eder."""
        children = {r.child_table for r in self.relationships}
        roots = [name for name in by_name if name not in children]
        if not roots:
            raise SchemaValidationError(
                t("contract.error.no_root_table")
            )
        return roots[0]

    # -- erisim ----------------------------------------------------------- #
    @property
    def table_names(self) -> List[str]:
        return [t.table_name for t in self.tables]

    def table(self, name: str) -> SchemaContract:
        for t in self.tables:
            if t.table_name == name:
                return t
        raise KeyError(name)

    def parents_of(self, table_name: str) -> List[Relationship]:
        return [r for r in self.relationships if r.child_table == table_name]

    def children_of(self, table_name: str) -> List[Relationship]:
        return [r for r in self.relationships if r.parent_table == table_name]

    def generation_order(self) -> List[str]:
        """Ebeveynler cocuklardan once gelecek sekilde topolojik sira.

        Raises:
            SchemaValidationError: Iliskilerde dongu varsa.
        """
        names = self.table_names
        pending = {n: {r.parent_table for r in self.parents_of(n)} for n in names}
        ordered: List[str] = []

        while pending:
            ready = sorted(n for n, deps in pending.items() if not (deps - set(ordered)))
            if not ready:
                raise SchemaValidationError(
                    t("contract.error.cycle", tables=sorted(pending))
                )
            for name in ready:
                ordered.append(name)
                pending.pop(name)
        return ordered

    @property
    def is_relational(self) -> bool:
        return len(self.tables) > 1

    # -- serilestirme ----------------------------------------------------- #
    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "domain": self.domain,
            "root_table": self.root_table,
            "random_seed": self.random_seed,
            "tables": [t.to_dict() for t in self.tables],
        }
        if self.relationships:
            out["relationships"] = [r.to_dict() for r in self.relationships]
        if self.description:
            out["description"] = self.description
        if self.warnings:
            out["warnings"] = list(self.warnings)
        return out

    def to_json(self, indent: int = 2) -> str:
        import json

        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
