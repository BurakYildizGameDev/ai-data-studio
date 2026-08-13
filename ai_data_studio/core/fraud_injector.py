"""Fraud & Anomali Senaryo Enjektörü (FraudScenarioInjector).

Gerçek dünya dolandırıcılık (fraud), siber saldırı ve finansal anomali veri setlerinde,
dolandırıcılık oranları tipik olarak %0.01 ile %1.0 arasında son derece dengesizdir (imbalanced).

Bu modül:
  1. Sentetik veri setlerine gerçekçi, çok değişkenli ve parametrik dolandırıcılık senaryoları enjekte eder.
  2. Yüksek tutar patlaması (high amount burst), olağandışı saatler (odd hours), imkansız hız (impossible velocity)
     ve çoklu başarısız deneme gibi bilinen tipolojileri simüle eder.
  3. Discriminator aşamasında bu satırların Z-Score veya IsolationForest tarafından "aykırı değer" sanılıp
     silinmesini engellemek için `preserve_anomaly_column` bayrağı ile uyumlu çalışır.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

__all__ = [
    "FraudScenarioConfig",
    "FraudScenarioInjector",
    "inject_fraud_scenarios",
]

# Kolon tanıma regex desenleri
_AMOUNT_PATTERNS = [
    r"amount", r"tutar", r"fiyat", r"price", r"income", r"balance", r"spend",
    r"cost", r"fee", r"bakiye", r"harcama", r"gelir", r"payment", r"odeme"
]
_ATTEMPTS_PATTERNS = [
    r"attempt", r"deneme", r"failed", r"retry", r"count", r"error_count", r"hata"
]
_DISTANCE_PATTERNS = [
    r"distance", r"mesafe", r"km", r"speed", r"hiz", r"velocity", r"location_dist"
]
_HOUR_PATTERNS = [
    r"hour", r"saat", r"time", r"zaman", r"transaction_hour"
]
_RISK_BOOL_PATTERNS = [
    r"is_international", r"international", r"is_vpn", r"is_proxy", r"foreign",
    r"yurt_disi", r"is_risk", r"is_suspicious"
]


@dataclass
class FraudScenarioConfig:
    """Fraud enjeksiyon yapılandırması."""

    fraud_rate: float = 0.005              # Varsayılan: %0.5 (0.005)
    target_column: str = "is_fraud"        # Anomali etiket kolonu
    scenarios: List[str] = field(default_factory=lambda: [
        "high_amount_burst",
        "impossible_velocity",
        "off_hours_activity",
        "credential_stuffing",
    ])
    random_seed: int = 42
    amount_multiplier_min: float = 5.0
    amount_multiplier_max: float = 20.0


class FraudScenarioInjector:
    """Sentetik veri setlerine gerçekçi dolandırıcılık senaryoları enjekte eder."""

    def __init__(self, config: Optional[FraudScenarioConfig] = None):
        self.config = config or FraudScenarioConfig()

    def inject(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Verilen DataFrame'e dolandırıcılık desenleri enjekte eder.

        Args:
            df: Ham sentetik DataFrame.

        Returns:
            Tuple[pd.DataFrame, Dict[str, Any]]: Enjekte edilmiş DataFrame ve özet rapor.
        """
        if df.empty:
            return df.copy(), {
                "injected_fraud_count": 0,
                "fraud_rate": 0.0,
                "target_column": self.config.target_column,
                "scenarios_applied": [],
                "modified_columns": [],
            }

        df_out = df.copy()
        n_rows = len(df_out)
        target_col = self.config.target_column
        rng = np.random.default_rng(self.config.random_seed)

        # Hedef kolon yoksa 0 / False olarak başlat
        if target_col not in df_out.columns:
            df_out[target_col] = 0
        else:
            # Mevcut kolonu sıfırla veya koru (sayısal türe zorla)
            if not pd.api.types.is_numeric_dtype(df_out[target_col]) and not pd.api.types.is_bool_dtype(df_out[target_col]):
                df_out[target_col] = 0

        # Enjekte edilecek satır sayısını hesapla
        fraud_rate = max(0.0, min(1.0, float(self.config.fraud_rate)))
        n_fraud = max(1, int(round(n_rows * fraud_rate))) if fraud_rate > 0 else 0

        if n_fraud == 0:
            return df_out, {
                "injected_fraud_count": 0,
                "fraud_rate": 0.0,
                "target_column": target_col,
                "scenarios_applied": [],
                "modified_columns": [],
            }

        # Rastgele anomali satır indekslerini seç
        fraud_indices = rng.choice(df_out.index, size=n_fraud, replace=False)
        df_out.loc[fraud_indices, target_col] = 1

        modified_columns: List[str] = [target_col]
        scenarios_applied: List[str] = []

        # İlgili kolonları tespit et
        amount_cols = self._find_matching_columns(df_out, _AMOUNT_PATTERNS, numeric_only=True)
        attempt_cols = self._find_matching_columns(df_out, _ATTEMPTS_PATTERNS, numeric_only=True)
        distance_cols = self._find_matching_columns(df_out, _DISTANCE_PATTERNS, numeric_only=True)
        hour_cols = self._find_matching_columns(df_out, _HOUR_PATTERNS, numeric_only=True)
        risk_bool_cols = self._find_matching_columns(df_out, _RISK_BOOL_PATTERNS)

        scenarios = self.config.scenarios

        # 1. Senaryo: High Amount Burst (Hesap ele geçirme / aşırı harcama)
        if "high_amount_burst" in scenarios and amount_cols:
            col = amount_cols[0]
            col_series = df_out[col].astype("float64")
            col_mean = col_series.mean()
            col_std = col_series.std()
            base_val = col_mean if np.isfinite(col_mean) and col_mean > 0 else 100.0

            # Normal dağılımın 5-20 katı veya mean + (4 ila 8)*std
            multipliers = rng.uniform(
                self.config.amount_multiplier_min,
                self.config.amount_multiplier_max,
                size=len(fraud_indices)
            )
            if col_std > 0:
                spikes = col_mean + rng.uniform(4.5, 9.0, size=len(fraud_indices)) * col_std
            else:
                spikes = base_val * multipliers

            # Değerleri yaz
            df_out.loc[fraud_indices, col] = np.round(spikes, 2)
            if col not in modified_columns:
                modified_columns.append(col)
            scenarios_applied.append("high_amount_burst")

        # 2. Senaryo: Impossible Velocity / Geographic Anomaly
        if "impossible_velocity" in scenarios and distance_cols:
            col = distance_cols[0]
            extreme_dist = rng.uniform(2500.0, 9500.0, size=len(fraud_indices))
            df_out.loc[fraud_indices, col] = np.round(extreme_dist, 1)
            if col not in modified_columns:
                modified_columns.append(col)
            scenarios_applied.append("impossible_velocity")

        # 3. Senaryo: Credential Stuffing / Başarısız Denemeler
        if "credential_stuffing" in scenarios and attempt_cols:
            col = attempt_cols[0]
            high_attempts = rng.integers(4, 15, size=len(fraud_indices))
            df_out.loc[fraud_indices, col] = high_attempts
            if col not in modified_columns:
                modified_columns.append(col)
            scenarios_applied.append("credential_stuffing")

        # 4. Senaryo: Gece Yarısı / Olağandışı Saatler (02:00 - 05:00)
        if "off_hours_activity" in scenarios and hour_cols:
            col = hour_cols[0]
            off_hours = rng.choice([2, 3, 4, 5], size=len(fraud_indices))
            df_out.loc[fraud_indices, col] = off_hours
            if col not in modified_columns:
                modified_columns.append(col)
            scenarios_applied.append("off_hours_activity")

        # 5. Ek Risk Bayrakları
        for bcol in risk_bool_cols:
            df_out.loc[fraud_indices, bcol] = True
            if bcol not in modified_columns:
                modified_columns.append(bcol)

        actual_fraud_rate = float(len(fraud_indices) / n_rows) if n_rows else 0.0

        report = {
            "total_rows": n_rows,
            "injected_fraud_count": int(len(fraud_indices)),
            "fraud_rate": round(actual_fraud_rate, 4),
            "target_column": target_col,
            "scenarios_applied": scenarios_applied,
            "modified_columns": modified_columns,
        }

        log.info(
            "Fraud enjeksiyonu tamamlandı: %d satır (%s=1, oran: %%%.2f), senaryolar: %s",
            len(fraud_indices), target_col, actual_fraud_rate * 100, scenarios_applied
        )

        return df_out, report

    def _find_matching_columns(self, df: pd.DataFrame, patterns: List[str],
                               numeric_only: bool = False) -> List[str]:
        """İsmi regex desenlerinden biriyle eşleşen kolonları bulur."""
        matches: List[str] = []
        for col in df.columns:
            if col == self.config.target_column:
                continue
            if numeric_only and not pd.api.types.is_numeric_dtype(df[col]):
                continue
            col_lower = str(col).lower()
            for pattern in patterns:
                if re.search(pattern, col_lower):
                    matches.append(col)
                    break
        return matches


def inject_fraud_scenarios(df: pd.DataFrame,
                           fraud_rate: float = 0.005,
                           target_column: str = "is_fraud",
                           seed: int = 42,
                           scenarios: Optional[List[str]] = None) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Tek fonksiyon ile dolandırıcılık senaryoları enjekte eder."""
    cfg = FraudScenarioConfig(
        fraud_rate=fraud_rate,
        target_column=target_column,
        random_seed=seed,
    )
    if scenarios:
        cfg.scenarios = scenarios
    injector = FraudScenarioInjector(cfg)
    return injector.inject(df)
