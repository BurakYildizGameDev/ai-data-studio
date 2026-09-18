"""Heuristic Sanity Checker — LLM-generated schema contracts sanity guard.

Small local models (1.5B–3B parameters) frequently produce semantically
inverted correlations and monotonicity rules.  For example:
  * income ↑ → default_rate ↑  (should be negative)
  * credit_score ↑ → is_fraud ↑  (should be negative)
  * Transitivity violation: A~B (+), B~C (−), but A~C (+)
  * A monetary column ("transaction_amount") left without a lower bound,
    which lets the generator emit negative amounts

This module runs AFTER SchemaContract.from_dict() and BEFORE the pipeline
starts generating data.  It is purely deterministic — no LLM calls — and
works by matching column names against a domain-knowledge dictionary of
risk / asset / quality semantic groups.

Design rules:
  * Never silently drop a rule — warn the user and auto-correct if enabled.
  * The heuristic dictionary is intentionally conservative: only high-confidence
    semantic pairs are flagged.  Unknown column names pass through unchecked.
  * All user-facing messages go through i18n (`t()`).
  * Log messages stay in English (project convention).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..i18n import t
from .schema_contract import CorrelationRule, MonotonicityRule, SchemaContract

log = logging.getLogger(__name__)

__all__ = [
    "SanityFinding",
    "SanityReport",
    "check_schema_sanity",
]

# --------------------------------------------------------------------------- #
# Semantic domain knowledge dictionary
# --------------------------------------------------------------------------- #
# Column names (or substrings) are grouped into semantic categories.
# When a RISK column is paired with an ASSET column, the expected correlation
# sign is NEGATIVE and the expected monotonicity direction is DECREASING.
#
# The matching is case-insensitive and uses substring containment so that
# "default_rate", "is_defaulted", "has_defaulted" all match "default".

# Risk / negative-outcome indicators: higher value = worse outcome
RISK_INDICATORS: Set[str] = {
    "default", "fraud", "churn", "late_payment", "delinquent",
    "overdue", "loss", "claim", "complaint", "risk",
    "bankrupt", "attrition", "dropout", "failure", "error",
    "reject", "denied", "cancel", "refund", "return",
    "mortality", "death", "readmission",
}

# Asset / positive-quality indicators: higher value = better outcome
ASSET_INDICATORS: Set[str] = {
    "income", "salary", "revenue", "profit", "credit_score",
    "fico", "tenure", "experience", "loyalty", "satisfaction",
    "balance", "savings", "investment", "education", "gpa",
    "rating", "score", "quality", "reliability", "health",
    "net_worth", "equity", "coverage", "premium_paid",
}

# Explicitly positive pairs: both columns moving in the same direction
# makes domain sense (e.g. income ↑ → credit_score ↑).
POSITIVE_PAIRS: Set[frozenset] = {
    frozenset({"income", "credit_score"}),
    frozenset({"salary", "credit_score"}),
    frozenset({"experience", "salary"}),
    frozenset({"tenure", "loyalty"}),
    frozenset({"satisfaction", "loyalty"}),
    frozenset({"education", "income"}),
}


# Ayni koke sahip ama ters anlamli kolonlar. Substring eslesmesi bunlari
# yanlis siniflandiriyordu: "annual_return" bir getiri (asset) ama "return"
# iade (risk) listesinde; "default_currency" bir ayar ama "default" temerrut.
# Olculdu: bu dordu de mesru korelasyonlari ters cevirtiyordu.
_CONTEXT_OVERRIDES: Dict[str, Optional[str]] = {
    "annual_return": "asset",
    "total_return": "asset",
    "rate_of_return": "asset",
    "expected_return": "asset",
    "return_on": "asset",           # return_on_equity, return_on_assets
    "default_currency": None,
    "default_value": None,
    "default_language": None,
    "default_locale": None,
}

# Risk <-> asset ciftinin NEGATIF olmasi beklentisinin gecerli olmadigi,
# bilinen alan istisnalari. Burada uyari verilir ama otomatik duzeltme
# YAPILMAZ: sigortacilikta yuksek riskli musteri yuksek prim oder, yani
# premium ile claim arasindaki pozitif iliski dogrudur.
AMBIGUOUS_PAIRS: Set[frozenset] = {
    frozenset({"premium", "claim"}),
    frozenset({"premium_paid", "claim"}),
    frozenset({"coverage", "claim"}),
    frozenset({"balance", "loss"}),
    frozenset({"revenue", "refund"}),
    frozenset({"revenue", "return"}),
}


# Negatif degeri olamayacak buyuklukler. Kucuk modeller bu kolonlara alt sinir
# koymayi unutuyor: olculdu, Qwen2.5-Coder 1.5B'nin urettigi 1000 satirin 66'si
# "transaction_amount" icin negatifti (en dusuk -538.62). Sozlesmede min yoksa
# validator'un eleyecegi bir sey de yok - veri oldugu gibi cikiyor.
NON_NEGATIVE_INDICATORS: Set[str] = {
    "amount", "price", "salary", "salaries", "income", "fee", "cost",
}

# Ayni kelimeleri tasiyip negatifi MESRU olan kolonlar. Bunlara dokunulmaz:
# net tutar eksiye duser, duzeltme kaydi eksi yazilir, kar/zarar zaten
# isaretlidir. Asiri duzeltme bu modulun bilinen kusuru (bkz. O-6), o yuzden
# sinir dar tutuldu.
NEGATIVE_ALLOWED_TOKENS: Set[str] = {
    "net", "adjustment", "adjust", "delta", "change", "difference", "diff",
    "profit", "loss", "pnl", "margin", "variance", "growth", "balance",
}


# Basit cekim ekleri: "default" gostergesi "defaulted"i, "claim" "claims"i,
# "return" "returned"i de yakalasin. Tam kok eslesmesi bunlari kaciriyordu.
_SUFFIXES = ("", "s", "es", "d", "ed", "ing")


def _normalise(name: str) -> str:
    """Kolon adini snake_case'e indirger.

    camelCase bolmesi ORIJINAL ad uzerinde yapilmalidir; once kucultmek
    "totalReturn"u tek parcaya indirip bağlam istisnalarini kacirtiyordu.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return re.sub(r"[^a-z0-9]+", "_", spaced.lower()).strip("_")


def _tokens(name: str) -> Set[str]:
    """Kolon adini kelime parcalarina ayirir (snake_case ve camelCase)."""
    return {tok for tok in _normalise(name).split("_") if tok}


def _matches(indicators: Set[str], lower: str, toks: Set[str]) -> bool:
    """Cok kelimeli gosterge icin tam ifade, tek kelimelik icin token eslesmesi.

    Substring yerine kelime siniri kullanilir: aksi halde "default" ->
    "default_currency_rate" ve "return" -> "annual_return" gibi yanlis
    pozitifler olusuyordu.
    """
    for indicator in indicators:
        if "_" in indicator:
            if indicator in lower:
                return True
            continue
        for tok in toks:
            if any(tok == indicator + suffix for suffix in _SUFFIXES):
                return True
    return False


def _classify_column(name: str) -> Optional[str]:
    """Kolonu 'risk', 'asset' ya da None olarak siniflar."""
    lower = _normalise(name)
    for phrase, override in _CONTEXT_OVERRIDES.items():
        if phrase in lower:
            return override

    toks = _tokens(name)
    if _matches(RISK_INDICATORS, lower, toks):
        return "risk"
    if _matches(ASSET_INDICATORS, lower, toks):
        return "asset"
    return None


def _is_ambiguous_pair(col_a: str, col_b: str) -> bool:
    """Risk<->asset beklentisinin alan bilgisiyle celistigi bilinen ciftler."""
    a, b = _normalise(col_a), _normalise(col_b)
    for pair in AMBIGUOUS_PAIRS:
        x, y = tuple(pair)
        if (x in a and y in b) or (y in a and x in b):
            return True
    return False


def _is_positive_pair(col_a: str, col_b: str) -> bool:
    """Check if two columns are a known positive-correlation pair."""
    a_lower = _normalise(col_a)
    b_lower = _normalise(col_b)
    for pair in POSITIVE_PAIRS:
        items = list(pair)
        if (items[0] in a_lower and items[1] in b_lower) or \
           (items[1] in a_lower and items[0] in b_lower):
            return True
    return False


# --------------------------------------------------------------------------- #
# Finding data structures
# --------------------------------------------------------------------------- #

@dataclass
class SanityFinding:
    """A single sanity check finding."""
    severity: str  # "WARNING" or "INFO"
    category: str  # "semantic_inversion", "transitivity_violation", "monotonicity_inversion"
    message: str   # Human-readable, i18n'd message
    auto_corrected: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SanityReport:
    """Aggregated sanity check results."""
    findings: List[SanityFinding] = field(default_factory=list)
    corrections_applied: int = 0

    @property
    def has_warnings(self) -> bool:
        return any(f.severity == "WARNING" for f in self.findings)

    @property
    def clean(self) -> bool:
        return len(self.findings) == 0

    def summary_lines(self) -> List[str]:
        """Short summary for progress callback / console."""
        if self.clean:
            return [t("sanity.report.clean")]
        lines = []
        for f in self.findings:
            prefix = "⚠️" if f.severity == "WARNING" else "ℹ️"
            corrected = " ✅" if f.auto_corrected else ""
            lines.append(f"{prefix} {f.message}{corrected}")
        return lines


# --------------------------------------------------------------------------- #
# Core check functions
# --------------------------------------------------------------------------- #

def _check_correlation_semantics(
    schema: SchemaContract,
    auto_correct: bool,
) -> Tuple[List[SanityFinding], int]:
    """Check correlation rules for semantic inversions."""
    findings: List[SanityFinding] = []
    corrections = 0

    for rule in schema.correlations:
        if len(rule.columns) != 2:
            continue
        col_a, col_b = rule.columns
        cat_a = _classify_column(col_a)
        cat_b = _classify_column(col_b)

        if cat_a is None or cat_b is None:
            continue

        # Alan bilgisinin risk<->asset beklentisiyle celistigi bilinen ciftler:
        # uyari verilir, otomatik duzeltme yapilmaz. Sigortacilikta yuksek
        # riskli musteri yuksek prim oder; premium <-> claim pozitif olmalidir.
        if _is_ambiguous_pair(col_a, col_b):
            findings.append(SanityFinding(
                severity="INFO",
                category="ambiguous_pair",
                message=t("sanity.correlation.ambiguous_pair",
                          col_a=col_a, col_b=col_b),
                auto_corrected=False,
                details={"columns": [col_a, col_b],
                         "expected_sign": rule.expected_sign},
            ))
            continue

        # Pozitif-cift kisayolu, kolonlardan biri RISK siniflandirmasi aldiysa
        # UYGULANMAZ: "satisfaction" <-> "loyalty_churn_rate" eskiden dogru
        # negatif korelasyonu pozitife ceviriyordu, cunku "loyalty" pozitif
        # ciftle eslesip risk mantigini atliyordu.
        if _is_positive_pair(col_a, col_b) and "risk" not in (cat_a, cat_b):
            if rule.expected_sign == "negative":
                msg = t("sanity.correlation.positive_pair_inverted",
                        col_a=col_a, col_b=col_b)
                if auto_correct:
                    rule.expected_sign = "positive"
                    corrections += 1
                findings.append(SanityFinding(
                    severity="WARNING",
                    category="semantic_inversion",
                    message=msg,
                    auto_corrected=auto_correct,
                    details={"columns": [col_a, col_b],
                             "was": "negative", "corrected_to": "positive"},
                ))
            continue

        # Risk ↔ Asset: expected sign is NEGATIVE
        if (cat_a == "risk" and cat_b == "asset") or \
           (cat_a == "asset" and cat_b == "risk"):
            if rule.expected_sign == "positive":
                msg = t("sanity.correlation.risk_asset_inverted",
                        col_a=col_a, col_b=col_b,
                        cat_a=cat_a, cat_b=cat_b)
                if auto_correct:
                    rule.expected_sign = "negative"
                    corrections += 1
                findings.append(SanityFinding(
                    severity="WARNING",
                    category="semantic_inversion",
                    message=msg,
                    auto_corrected=auto_correct,
                    details={"columns": [col_a, col_b],
                             "was": "positive", "corrected_to": "negative"},
                ))

    return findings, corrections


def _check_monotonicity_semantics(
    schema: SchemaContract,
    auto_correct: bool,
) -> Tuple[List[SanityFinding], int]:
    """Check monotonicity rules for semantic inversions."""
    findings: List[SanityFinding] = []
    corrections = 0

    for rule in schema.monotonicity_rules:
        cat_x = _classify_column(rule.column_x)
        cat_y = _classify_column(rule.column_y)

        if cat_x is None or cat_y is None:
            continue

        # Asset ↑ → Risk ↑ should be DECREASING (asset goes up, risk goes down)
        if cat_x == "asset" and cat_y == "risk":
            if rule.direction == "increasing":
                msg = t("sanity.monotonicity.asset_risk_inverted",
                        col_x=rule.column_x, col_y=rule.column_y)
                if auto_correct:
                    rule.direction = "decreasing"
                    corrections += 1
                findings.append(SanityFinding(
                    severity="WARNING",
                    category="monotonicity_inversion",
                    message=msg,
                    auto_corrected=auto_correct,
                    details={"column_x": rule.column_x,
                             "column_y": rule.column_y,
                             "was": "increasing",
                             "corrected_to": "decreasing"},
                ))

        # Risk ↑ → Asset ↑ should be DECREASING too
        elif cat_x == "risk" and cat_y == "asset":
            if rule.direction == "increasing":
                msg = t("sanity.monotonicity.risk_asset_inverted",
                        col_x=rule.column_x, col_y=rule.column_y)
                if auto_correct:
                    rule.direction = "decreasing"
                    corrections += 1
                findings.append(SanityFinding(
                    severity="WARNING",
                    category="monotonicity_inversion",
                    message=msg,
                    auto_corrected=auto_correct,
                    details={"column_x": rule.column_x,
                             "column_y": rule.column_y,
                             "was": "increasing",
                             "corrected_to": "decreasing"},
                ))

    return findings, corrections


def _check_correlation_transitivity(
    schema: SchemaContract,
) -> List[SanityFinding]:
    """Detect transitivity violations in correlation rules.

    If Sign(A,B) × Sign(B,C) ≠ Sign(A,C) and all three |min_r| > 0.3,
    the rules are mutually contradictory.
    """
    findings: List[SanityFinding] = []
    SIGN_MAP = {"positive": 1, "negative": -1}
    MIN_R_THRESHOLD = 0.3  # Only flag strong correlations

    # Build an edge map: (col_a, col_b) -> sign
    edges: Dict[frozenset, Tuple[int, float, CorrelationRule]] = {}
    for rule in schema.correlations:
        if len(rule.columns) != 2:
            continue
        key = frozenset(rule.columns)
        sign = SIGN_MAP.get(rule.expected_sign, 0)
        if sign != 0:
            edges[key] = (sign, rule.min_r, rule)

    # Check all triples
    columns_in_rules = set()
    for rule in schema.correlations:
        columns_in_rules.update(rule.columns)

    # sorted() bir kez: eskiden ic ice donguler her yinelemede listeyi
    # yeniden siraliyordu (200 kolonda ~40.000 sıralama).
    ordered = sorted(columns_in_rules)
    for i, col_a in enumerate(ordered):
        for j in range(i + 1, len(ordered)):
            col_b = ordered[j]
            edge_ab = edges.get(frozenset({col_a, col_b}))
            if not edge_ab:
                continue
            for k in range(j + 1, len(ordered)):
                col_c = ordered[k]
                # a < b < c siralamasi her ucluyu zaten bir kez uretir,
                # ayrica "checked" kumesine gerek yok.

                edge_ac = edges.get(frozenset({col_a, col_c}))
                edge_bc = edges.get(frozenset({col_b, col_c}))
                if not edge_ac or not edge_bc:
                    continue

                sign_ab, r_ab, _ = edge_ab
                sign_ac, r_ac, _ = edge_ac
                sign_bc, r_bc, _ = edge_bc

                # Only flag if all correlations are strong enough
                if min(r_ab, r_ac, r_bc) < MIN_R_THRESHOLD:
                    continue

                # Transitivity: sign(A,B) * sign(B,C) should equal sign(A,C)
                expected_ac = sign_ab * sign_bc
                if expected_ac != sign_ac:
                    msg = t("sanity.transitivity.violation",
                            col_a=col_a, col_b=col_b, col_c=col_c,
                            sign_ab="+" if sign_ab > 0 else "−",
                            sign_bc="+" if sign_bc > 0 else "−",
                            sign_ac="+" if sign_ac > 0 else "−")
                    findings.append(SanityFinding(
                        severity="WARNING",
                        category="transitivity_violation",
                        message=msg,
                        auto_corrected=False,
                        details={"columns": [col_a, col_b, col_c],
                                 "signs": {"ab": sign_ab, "bc": sign_bc,
                                           "ac": sign_ac,
                                           "expected_ac": expected_ac}},
                    ))

    return findings


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def _check_non_negative_amounts(
    schema: SchemaContract,
    auto_correct: bool,
) -> Tuple[List[SanityFinding], int]:
    """Parasal kolonlarin alt sinirini 0'a cekerek negatif tutari engeller.

    Diger denetimlerin aksine bu, kurallara degil KOLON SINIRLARINA bakar:
    ``min`` hic verilmemisse ya da negatifse tutar kolonu negatif deger
    uretebilir ve validator'un elemesi icin bir sinir yoktur. ``min = 0``
    hem uretim istemini hem de dogrulamayi ayni anda duzeltir.

    Adi negatifi mesru kilan kolonlar (net_amount, adjustment_amount,
    profit_amount...) ELENIR; ayrica ``auto_correct=False`` ise yalnizca
    rapor edilir, sozlesme degistirilmez.
    """
    findings: List[SanityFinding] = []
    corrections = 0

    for column in schema.columns:
        if not column.is_numeric:
            continue
        lower = _normalise(column.name)
        toks = _tokens(column.name)
        if not _matches(NON_NEGATIVE_INDICATORS, lower, toks):
            continue
        if _matches(NEGATIVE_ALLOWED_TOKENS, lower, toks):
            continue
        if column.min is not None and column.min >= 0:
            continue

        declared = column.min
        if auto_correct:
            column.min = 0
            corrections += 1

        if declared is None:
            message = t("sanity.bounds.amount_missing_min", column=column.name)
        else:
            message = t("sanity.bounds.amount_negative_min",
                        column=column.name, declared=declared)

        findings.append(SanityFinding(
            severity="WARNING",
            category="non_negative_amount",
            message=message,
            auto_corrected=auto_correct,
            details={"column": column.name, "declared_min": declared,
                     "applied_min": 0 if auto_correct else None},
        ))

    return findings, corrections


def check_schema_sanity(
    schema: SchemaContract,
    *,
    auto_correct: bool = True,
) -> SanityReport:
    """Run all heuristic sanity checks on a schema contract.

    Parameters
    ----------
    schema : SchemaContract
        The contract to check.  If *auto_correct* is True the contract's
        correlation and monotonicity rules are modified **in place**.
    auto_correct : bool
        When True, detected inversions are automatically fixed and a warning
        is added to the schema's warnings list.  When False, findings are
        reported but the schema is not modified.

    Returns
    -------
    SanityReport
        Aggregated findings and correction count.
    """
    report = SanityReport()

    # 1. Correlation semantic inversions
    corr_findings, corr_corrections = _check_correlation_semantics(
        schema, auto_correct)
    report.findings.extend(corr_findings)
    report.corrections_applied += corr_corrections

    # 2. Monotonicity semantic inversions
    mono_findings, mono_corrections = _check_monotonicity_semantics(
        schema, auto_correct)
    report.findings.extend(mono_findings)
    report.corrections_applied += mono_corrections

    # 3. Correlation transitivity violations (informational, no auto-correct)
    trans_findings = _check_correlation_transitivity(schema)
    report.findings.extend(trans_findings)

    # 4. Negatif olamayacak parasal kolonlarin alt siniri
    bound_findings, bound_corrections = _check_non_negative_amounts(
        schema, auto_correct)
    report.findings.extend(bound_findings)
    report.corrections_applied += bound_corrections

    # Push findings to schema warnings so they appear in the UI
    for finding in report.findings:
        if finding.message not in schema.warnings:
            schema.warnings.append(finding.message)

    if report.findings:
        log.info("Schema sanity check: %d finding(s), %d auto-corrected",
                 len(report.findings), report.corrections_applied)
    else:
        log.debug("Schema sanity check: clean")

    return report
