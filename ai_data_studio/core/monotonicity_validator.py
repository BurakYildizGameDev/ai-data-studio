"""Monotonluk ve Kredi Riski / Skor Kartı Doğrulayıcısı (MonotonicityValidator).

Bu modül:
  1. X ve Y değişkenleri arasındaki monotonluk ilişkisini (X1 > X2 ==> Y1 >= Y2 veya Y1 <= Y2)
     hem quantile/binned hem pairwise hem de Spearman rank korelasyonuyla doğrular.
  2. Kredi risk modelleme (Basel III, FICO, PD scorecards) standartlarında kritik olan
     Weight of Evidence (WoE) ve Information Value (IV) hesaplar; WoE trendinin monotonluğunu test eder.
  3. Çok değişkenli bağımlılıkların ve skor kartı özelliklerinin tutarlılığını temin eder.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..i18n import t

from .schema_contract import MonotonicityRule

log = logging.getLogger(__name__)

__all__ = [
    "MonotonicityCheckResult",
    "WoEResult",
    "MonotonicityReport",
    "MonotonicityValidator",
    "validate_monotonicity",
    "compute_woe_iv",
]


@dataclass
class WoEResult:
    """Weight of Evidence (WoE) ve Information Value (IV) analiz sonucu."""

    feature: str
    target: str
    bins: List[Dict[str, Any]] = field(default_factory=list)
    total_iv: float = 0.0
    is_monotonic_woe: bool = True
    predictive_power: str = "Medium"  # Weak (<0.02), Medium (0.02-0.1), Strong (0.1-0.3), Very Strong (>0.3)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature": self.feature,
            "target": self.target,
            "total_iv": round(self.total_iv, 4),
            "is_monotonic_woe": self.is_monotonic_woe,
            "predictive_power": self.predictive_power,
            "bins_count": len(self.bins),
            "bins": self.bins,
        }


@dataclass
class MonotonicityCheckResult:
    """Tek bir kural için monotonluk denetim sonucu."""

    column_x: str
    column_y: str
    direction: str
    passed: bool
    binned_compliance_ratio: float
    spearman_r: float
    pairwise_compliance_ratio: float
    min_compliance_ratio: float
    bin_means: List[float] = field(default_factory=list)
    bin_edges: List[float] = field(default_factory=list)
    woe_result: Optional[Dict[str, Any]] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "column_x": self.column_x,
            "column_y": self.column_y,
            "direction": self.direction,
            "passed": self.passed,
            "binned_compliance_ratio": round(self.binned_compliance_ratio, 3),
            "spearman_r": round(self.spearman_r, 3),
            "pairwise_compliance_ratio": round(self.pairwise_compliance_ratio, 3),
            "min_compliance_ratio": self.min_compliance_ratio,
            "bin_means": [round(m, 4) for m in self.bin_means],
            "bin_edges": [round(e, 4) for e in self.bin_edges],
            "woe_result": self.woe_result,
            "reason": self.reason,
        }


@dataclass
class MonotonicityReport:
    """Tüm monotonluk kurallarının toplu raporu."""

    results: List[MonotonicityCheckResult] = field(default_factory=list)
    all_passed: bool = True
    total_rules: int = 0
    passed_rules: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "all_passed": self.all_passed,
            "total_rules": self.total_rules,
            "passed_rules": self.passed_rules,
            "results": [r.to_dict() for r in self.results],
        }

    def to_markdown(self) -> str:
        if not self.results:
            return "*%s*" % t("monotonicity.no_rules")

        lines = [
            "### " + t("monotonicity.report_title"),
            t("monotonicity.table_header"),
            "|---|---|---|---|---|---|---|",
        ]
        for r in self.results:
            status = ("✅ " + t("history.verdict.pass") if r.passed
                      else "❌ " + t("validation.verdict.violation"))
            lines.append(
                "| `%s` | `%s` | %s | `%.3f` | %%%.1f | %%%.1f | %s |"
                % (
                    r.column_x,
                    r.column_y,
                    r.direction,
                    r.spearman_r,
                    r.binned_compliance_ratio * 100,
                    r.pairwise_compliance_ratio * 100,
                    status,
                )
            )
        return "\n".join(lines)


class MonotonicityValidator:
    """Monotonluk ve WoE kurallarını denetleyen motor."""

    def __init__(self, n_bins: int = 10, max_pairs_sample: int = 2000, random_seed: int = 42):
        self.n_bins = n_bins
        self.max_pairs_sample = max_pairs_sample
        self.random_seed = random_seed

    def validate_rule(self, df: pd.DataFrame, rule: MonotonicityRule) -> MonotonicityCheckResult:
        """Belirtilen MonotonicityRule kuralını DataFrame üzerinde test eder."""
        cx, cy = rule.column_x, rule.column_y
        if df.empty or cx not in df.columns or cy not in df.columns:
            return MonotonicityCheckResult(
                column_x=cx,
                column_y=cy,
                direction=rule.direction,
                passed=False,
                binned_compliance_ratio=0.0,
                spearman_r=0.0,
                pairwise_compliance_ratio=0.0,
                min_compliance_ratio=rule.min_compliance_ratio,
                reason=t("monotonicity.column_missing"),
            )

        # Sayısala çevir ve geçerli satırları al
        sub = df[[cx, cy]].dropna()
        x_vals = pd.to_numeric(sub[cx], errors="coerce")
        y_vals = pd.to_numeric(sub[cy], errors="coerce")
        valid_mask = ~(x_vals.isna() | y_vals.isna())
        # bool kolonlar (orn. is_churned) to_numeric sonrasi bool kalir; numpy
        # bool dizilerde cikarma islemini desteklemedigi icin float'a zorluyoruz.
        x_clean = x_vals[valid_mask].to_numpy(dtype="float64")
        y_clean = y_vals[valid_mask].to_numpy(dtype="float64")

        if len(x_clean) < 10:
            return MonotonicityCheckResult(
                column_x=cx,
                column_y=cy,
                direction=rule.direction,
                passed=False,
                binned_compliance_ratio=0.0,
                spearman_r=0.0,
                pairwise_compliance_ratio=0.0,
                min_compliance_ratio=rule.min_compliance_ratio,
                reason=t("monotonicity.not_enough_rows"),
            )

        # 1. Spearman Rank Korelasyonu
        corr_matrix = pd.DataFrame({"x": x_clean, "y": y_clean}).corr(method="spearman")
        spearman_val = float(corr_matrix.loc["x", "y"])
        if np.isnan(spearman_val):
            spearman_val = 0.0

        # 2. Binned / Quantile Monotonluğu (Scorecard / Basel standardı)
        binned_ratio, bin_means, bin_edges = self._compute_binned_monotonicity(
            x_clean, y_clean, rule.direction, self.n_bins
        )

        # 3. Pairwise concordance ratio (Örneklem üzerinde ikili monotonluk uyumu)
        pairwise_ratio = self._compute_pairwise_monotonicity(
            x_clean, y_clean, rule.direction, self.max_pairs_sample
        )

        # 4. Binary hedef ise Weight of Evidence (WoE) testi
        woe_dict: Optional[Dict[str, Any]] = None
        unique_y = np.unique(y_clean)
        if len(unique_y) == 2 and set(unique_y).issubset({0, 1, 0.0, 1.0}):
            woe_res = compute_woe_iv(sub, feature_col=cx, target_col=cy, n_bins=self.n_bins)
            woe_dict = woe_res.to_dict()

        # Genel kabul: Binned uyum ve ikili uyumun min_compliance_ratio eşiğini sağlaması
        # Spearman yönü de beklenen yöne uygun olmalı
        expected_increasing = rule.direction == "increasing"
        direction_ok = (spearman_val >= -0.05) if expected_increasing else (spearman_val <= 0.05)

        passed = (
            binned_ratio >= rule.min_compliance_ratio
            and pairwise_ratio >= (rule.min_compliance_ratio * 0.85)
            and direction_ok
        )

        reason = t("monotonicity.compliant") if passed else t(
            "monotonicity.below_threshold",
            binned="%.1f" % (binned_ratio * 100),
            pairwise="%.1f" % (pairwise_ratio * 100),
            threshold="%.1f" % (rule.min_compliance_ratio * 100))

        return MonotonicityCheckResult(
            column_x=cx,
            column_y=cy,
            direction=rule.direction,
            passed=bool(passed),
            binned_compliance_ratio=binned_ratio,
            spearman_r=spearman_val,
            pairwise_compliance_ratio=pairwise_ratio,
            min_compliance_ratio=rule.min_compliance_ratio,
            bin_means=bin_means,
            bin_edges=bin_edges,
            woe_result=woe_dict,
            reason=reason,
        )

    def validate_all(self, df: pd.DataFrame, rules: List[MonotonicityRule]) -> MonotonicityReport:
        """Tüm kuralları çalıştırır ve MonotonicityReport döndürür."""
        if not rules:
            return MonotonicityReport(results=[], all_passed=True, total_rules=0, passed_rules=0)

        results = [self.validate_rule(df, r) for r in rules]
        passed_count = sum(1 for r in results if r.passed)
        all_passed = (passed_count == len(results))

        return MonotonicityReport(
            results=results,
            all_passed=all_passed,
            total_rules=len(results),
            passed_rules=passed_count,
        )

    def _compute_binned_monotonicity(
        self, x: np.ndarray, y: np.ndarray, direction: str, n_bins: int
    ) -> Tuple[float, List[float], List[float]]:
        """Veriyi K quantiledilime bölerek ardışık dilim ortalamalarının monotonluğunu ölçer."""
        try:
            # Eşit frekanslı (quantile) kutulama
            quantiles = np.linspace(0, 1, n_bins + 1)
            raw_edges = np.percentile(x, quantiles * 100)
            edges = np.unique(raw_edges)
            if len(edges) < 3:
                # Eşit aralıklı kutulama (tekrar eden değerler çoksa)
                edges = np.linspace(np.min(x), np.max(x), n_bins + 1)
                edges = np.unique(edges)

            if len(edges) < 2:
                return 1.0, [float(np.mean(y))], [float(e) for e in edges]

            bin_indices = np.digitize(x, edges[1:-1])  # 0 to len(edges)-1
            bin_means: List[float] = []

            for b in range(len(edges) - 1):
                mask = (bin_indices == b)
                if np.any(mask):
                    bin_means.append(float(np.mean(y[mask])))

            if len(bin_means) <= 1:
                return 1.0, bin_means, [float(e) for e in edges]

            # Ardışık dilim farkları
            diffs = np.diff(bin_means)
            expected_increasing = direction == "increasing"

            if expected_increasing:
                valid_steps = np.sum(diffs >= -1e-6)
            else:
                valid_steps = np.sum(diffs <= 1e-6)

            ratio = float(valid_steps / len(diffs))
            return ratio, bin_means, [float(e) for e in edges]
        except Exception as exc:
            log.warning("Dilimli monotonluk hesaplanamadı: %s", exc)
            return 0.0, [], []

    def _compute_pairwise_monotonicity(
        self, x: np.ndarray, y: np.ndarray, direction: str, max_pairs: int
    ) -> float:
        """Rastgele ikililer (pairs) çekerek X_i > X_j iken Y_i >= Y_j uyum oranını hesaplar."""
        n = len(x)
        if n < 2:
            return 1.0

        rng = np.random.default_rng(self.random_seed)
        sample_size = min(n, max_pairs)

        idx1 = rng.integers(0, n, size=sample_size)
        idx2 = rng.integers(0, n, size=sample_size)

        # Farklı indeks çiftleri
        diff_mask = (idx1 != idx2)
        i1, i2 = idx1[diff_mask], idx2[diff_mask]

        dx = x[i1] - x[i2]
        dy = y[i1] - y[i2]

        # X'in eşit olmadığı çiftleri baz al
        valid = (dx != 0)
        if not np.any(valid):
            return 1.0

        dx_v = dx[valid]
        dy_v = dy[valid]

        expected_increasing = direction == "increasing"
        if expected_increasing:
            # dx > 0 ise dy >= 0, dx < 0 ise dy <= 0  ==>  dx * dy >= 0
            concordant = np.sum(dx_v * dy_v >= -1e-7)
        else:
            # dx > 0 ise dy <= 0, dx < 0 ise dy >= 0  ==>  dx * dy <= 0
            concordant = np.sum(dx_v * dy_v <= 1e-7)

        return float(concordant / len(dx_v))


# --------------------------------------------------------------------------- #
# Weight of Evidence (WoE) & Information Value (IV) Hesaplayıcısı
# --------------------------------------------------------------------------- #
def compute_woe_iv(
    df: pd.DataFrame,
    feature_col: str,
    target_col: str,
    n_bins: int = 10,
) -> WoEResult:
    """Kredi riski / skor kartı için WoE ve IV hesaplar."""
    sub = df[[feature_col, target_col]].dropna()
    x = pd.to_numeric(sub[feature_col], errors="coerce")
    y = pd.to_numeric(sub[target_col], errors="coerce")
    mask = ~(x.isna() | y.isna())
    sub = sub[mask]

    total_good = int(np.sum(y == 0))
    total_bad = int(np.sum(y == 1))

    if total_good == 0 or total_bad == 0 or len(sub) < 10:
        return WoEResult(
            feature=feature_col,
            target=target_col,
            bins=[],
            total_iv=0.0,
            is_monotonic_woe=True,
            predictive_power="Undetermined",
        )

    # Binning
    try:
        sub["bin"] = pd.qcut(sub[feature_col], q=n_bins, duplicates="drop")
    except Exception:
        sub["bin"] = pd.cut(sub[feature_col], bins=min(n_bins, 5))

    grouped = sub.groupby("bin", observed=False).agg(
        total=(target_col, "count"),
        bad=(target_col, lambda v: int(np.sum(v == 1))),
    ).reset_index()

    grouped["good"] = grouped["total"] - grouped["bad"]

    bins_data: List[Dict[str, Any]] = []
    total_iv = 0.0
    woe_values: List[float] = []

    for _, row in grouped.iterrows():
        b_cnt = int(row["bad"])
        g_cnt = int(row["good"])
        t_cnt = int(row["total"])

        # Laplace düzeltmesi (sıfır frekans engelleme)
        dist_good = max(g_cnt, 0.5) / total_good
        dist_bad = max(b_cnt, 0.5) / total_bad

        woe = float(np.log(dist_good / dist_bad))
        iv_bin = float((dist_good - dist_bad) * woe)
        total_iv += iv_bin
        woe_values.append(woe)

        bins_data.append({
            "bin": str(row["bin"]),
            "count": t_cnt,
            "good": g_cnt,
            "bad": b_cnt,
            "bad_rate": round(b_cnt / t_cnt if t_cnt else 0.0, 4),
            "woe": round(woe, 4),
            "iv": round(iv_bin, 4),
        })

    # WoE trendinin monotonluğu
    diffs = np.diff(woe_values) if len(woe_values) > 1 else np.array([])
    is_inc = bool(np.all(diffs >= -0.05))
    is_dec = bool(np.all(diffs <= 0.05))
    is_monotonic = bool(is_inc or is_dec) if len(diffs) > 0 else True

    # Predictive power (FICO / Basel standardı)
    if total_iv < 0.02:
        power = "Weak / Unpredictive (<0.02)"
    elif total_iv < 0.10:
        power = "Medium (0.02 - 0.10)"
    elif total_iv < 0.30:
        power = "Strong (0.10 - 0.30)"
    else:
        power = "Very Strong (>0.30)"

    return WoEResult(
        feature=feature_col,
        target=target_col,
        bins=bins_data,
        total_iv=total_iv,
        is_monotonic_woe=is_monotonic,
        predictive_power=power,
    )


def validate_monotonicity(
    df: pd.DataFrame,
    rules: List[MonotonicityRule],
    n_bins: int = 10,
    seed: int = 42,
) -> MonotonicityReport:
    """Yardımcı fonksiyon: Verilen kurallar için monotonluk doğrulaması yapar."""
    validator = MonotonicityValidator(n_bins=n_bins, random_seed=seed)
    return validator.validate_all(df, rules)
