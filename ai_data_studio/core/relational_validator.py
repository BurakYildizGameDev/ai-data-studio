"""Iliskisel butunluk dogrulayicisi (cok tablolu Discriminator eki).

``validator.run_validation`` tek bir tabloyu kendi icinde denetler. Bu modul
tablolar ARASINDAKI sozlesmeyi denetler:

  1. Birincil anahtar tekilligi ve bosluk denetimi
  2. Yetim yabanci anahtar orani (child.fk, parent.pk kumesinde var mi)
  3. Kardinalite uyumu (ebeveyn basina cocuk sayisi sozlesmeye uyuyor mu)
  4. Yetim satirlarin ayiklanmasi

ONEMLI SIRA NOTU: Tek tablo temizligi (duplicate/sinir/kural/outlier) satir
siler; silinen bir EBEVEYN satiri, cocuklarini yetim birakir. Bu yuzden
iliskisel onarim, tek tablo dogrulamasindan SONRA calismalidir.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from .. import config
from ..i18n import t
from .dataset_contract import DatasetContract, Relationship

log = logging.getLogger(__name__)

__all__ = [
    "check_primary_keys",
    "check_foreign_keys",
    "check_cardinality",
    "repair_orphans",
    "validate_relationships",
]

# Kardinalite sapma toleransi: gozlenen ortalama, sozlesmedekinin bu kadar
# katindan uzaklasirsa uyari verilir. Uretim stokastik oldugu icin genis.
CARDINALITY_TOLERANCE = 0.5


def check_primary_keys(tables: Dict[str, pd.DataFrame],
                       contract: DatasetContract) -> List[Dict[str, Any]]:
    """Her tablonun primary_key'i tekil ve dolu mu."""
    results: List[Dict[str, Any]] = []
    for schema in contract.tables:
        pk = schema.primary_key
        name = schema.table_name
        if not pk:
            continue
        df = tables.get(name)
        if df is None or pk not in df.columns:
            results.append({"table": name, "primary_key": pk, "pass": False,
                            "reason": t("relational.reason.no_table_or_column")})
            continue
        col = df[pk]
        duplicates = int(col.duplicated().sum())
        nulls = int(col.isna().sum())
        results.append({
            "table": name,
            "primary_key": pk,
            "duplicates": duplicates,
            "nulls": nulls,
            "pass": duplicates == 0 and nulls == 0,
        })
    return results


def check_foreign_keys(tables: Dict[str, pd.DataFrame],
                       contract: DatasetContract) -> List[Dict[str, Any]]:
    """Her iliski icin yetim yabanci anahtar oranini olcer."""
    results: List[Dict[str, Any]] = []
    for rel in contract.relationships:
        parent = tables.get(rel.parent_table)
        child = tables.get(rel.child_table)
        if parent is None or child is None:
            results.append({"relationship": rel.label(), "pass": False,
                            "reason": t("relational.reason.no_table"), "orphan_rows": 0})
            continue
        if rel.parent_key not in parent.columns or rel.child_key not in child.columns:
            results.append({"relationship": rel.label(), "pass": False,
                            "reason": t("relational.reason.no_key_column"), "orphan_rows": 0})
            continue

        fk = child[rel.child_key]
        known = pd.Index(parent[rel.parent_key].dropna().unique())
        missing = ~fk.isin(known)
        if rel.nullable:
            missing &= fk.notna()          # bos FK opsiyonel iliskide serbest
        else:
            missing |= fk.isna()

        orphan_rows = int(missing.sum())
        total = int(len(child))
        results.append({
            "relationship": rel.label(),
            "parent_table": rel.parent_table,
            "child_table": rel.child_table,
            "child_key": rel.child_key,
            "orphan_rows": orphan_rows,
            "orphan_pct": round(orphan_rows / total * 100, 3) if total else 0.0,
            "pass": orphan_rows == 0,
        })
    return results


def check_cardinality(tables: Dict[str, pd.DataFrame],
                      contract: DatasetContract) -> List[Dict[str, Any]]:
    """Ebeveyn basina cocuk sayisi sozlesmedeki dagilima uyuyor mu."""
    results: List[Dict[str, Any]] = []
    for rel in contract.relationships:
        parent = tables.get(rel.parent_table)
        child = tables.get(rel.child_table)
        if parent is None or child is None:
            continue
        if rel.parent_key not in parent.columns or rel.child_key not in child.columns:
            continue

        n_parents = int(parent[rel.parent_key].nunique())
        if n_parents == 0:
            continue

        counts = child[rel.child_key].value_counts()
        # Hic cocugu olmayan ebeveynler de ortalamaya girmeli.
        observed_mean = float(len(child)) / n_parents
        observed_max = int(counts.max()) if len(counts) else 0

        expected = rel.mean_per_parent
        low = expected * (1 - CARDINALITY_TOLERANCE)
        high = expected * (1 + CARDINALITY_TOLERANCE)
        within = low <= observed_mean <= high

        violations: List[str] = []
        if not within:
            violations.append("ortalama %.2f, beklenen %.2f (+/-%%%d)"
                              % (observed_mean, expected, CARDINALITY_TOLERANCE * 100))
        if rel.max_per_parent is not None and observed_max > rel.max_per_parent:
            violations.append("en yuksek %d, ust sinir %d" % (observed_max, rel.max_per_parent))

        results.append({
            "relationship": rel.label(),
            "expected_mean": expected,
            "observed_mean": round(observed_mean, 3),
            "observed_max": observed_max,
            "min_per_parent": rel.min_per_parent,
            "max_per_parent": rel.max_per_parent,
            "pass": not violations,
            "violations": violations,
        })
    return results


def repair_orphans(tables: Dict[str, pd.DataFrame],
                   contract: DatasetContract,
                   emit: Optional[Callable[[str], None]] = None
                   ) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    """Yetim cocuk satirlarini eler.

    Tek tablo temizligi ebeveyn satirlari sildiginde cocuklar yetim kalir.
    Uretim sirasinda (ebeveynden cocuga) ilerleyerek zincirleme yetimleri de
    temizler: once orders'in yetimleri, sonra order_items'in.
    """
    repaired = dict(tables)
    detail: Dict[str, Any] = {"removed_per_relationship": {}, "removed_total": 0}

    order = contract.generation_order()
    for rel in sorted(contract.relationships,
                      key=lambda r: order.index(r.child_table)):
        parent = repaired.get(rel.parent_table)
        child = repaired.get(rel.child_table)
        if parent is None or child is None:
            continue
        if rel.parent_key not in parent.columns or rel.child_key not in child.columns:
            continue

        known = pd.Index(parent[rel.parent_key].dropna().unique())
        fk = child[rel.child_key]
        keep = fk.isin(known)
        if rel.nullable:
            keep |= fk.isna()

        removed = int((~keep).sum())
        if removed:
            repaired[rel.child_table] = child[keep].reset_index(drop=True)
            detail["removed_per_relationship"][rel.label()] = removed
            detail["removed_total"] += removed
            if emit is not None:
                emit("    -> " + t("relational.orphans_removed",
                                   relationship=rel.label(),
                                   rows=format(removed, ",")))
    return repaired, detail


def validate_relationships(tables: Dict[str, pd.DataFrame],
                           contract: DatasetContract,
                           repair: bool = True,
                           emit: Optional[Callable[[str], None]] = None
                           ) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    """Iliskisel butunlugu denetler, istenirse yetimleri ayiklar.

    Returns:
        (tablolar, rapor). Rapor ``primary_keys``, ``foreign_keys``,
        ``cardinality``, ``repair`` ve ``pass`` anahtarlarini tasir.
    """
    report: Dict[str, Any] = {"relational": contract.is_relational}

    if repair:
        tables, repair_detail = repair_orphans(tables, contract, emit)
        report["repair"] = repair_detail

    pk = check_primary_keys(tables, contract)
    fk = check_foreign_keys(tables, contract)
    card = check_cardinality(tables, contract)

    report["primary_keys"] = pk
    report["foreign_keys"] = fk
    report["cardinality"] = card
    report["row_counts"] = {name: int(len(df)) for name, df in tables.items()}
    report["pass"] = (all(r["pass"] for r in pk)
                      and all(r["pass"] for r in fk)
                      and all(r["pass"] for r in card))

    if emit is not None:
        for r in pk:
            if not r["pass"]:
                emit("    -> " + t("relational.pk_not_unique",
                                   table=r["table"], pk=r["primary_key"],
                                   duplicates=format(r.get("duplicates", 0), ","),
                                   nulls=format(r.get("nulls", 0), ",")),
                     level=config.PROGRESS_WARNING)
        for r in fk:
            status = (t("validation.verdict.ok") if r["pass"]
                      else t("relational.verdict.orphans"))
            emit("    -> " + t("relational.fk_line",
                               relationship=r["relationship"],
                               orphans=format(r.get("orphan_rows", 0), ","),
                               pct="%.2f" % r.get("orphan_pct", 0.0),
                               verdict=status))
        for r in card:
            status = (t("validation.verdict.ok") if r["pass"]
                      else t("result.relational.deviation"))
            emit("    -> " + t("relational.cardinality_line",
                               relationship=r["relationship"],
                               observed="%.2f" % r["observed_mean"],
                               expected="%.2f" % r["expected_mean"],
                               verdict=status))
            for v in r.get("violations", []):
                emit("       * %s" % v)

    return tables, report
