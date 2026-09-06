# -*- coding: utf-8 -*-
"""Kirli Veri ve Gürültü Enjeksiyon Motoru (DirtyDataEngine).

Gerçek dünya veritabanlarında veriler asla %100 steril ve pürüzsüz değildir.
Makine öğrenmesi modellerinin gerçek dünyada aşırı öğrenme (overfitting) yapmasını
engellemek ve veri temizleme (data cleaning / imputation) boru hatlarını test
edebilmek için kontrollü, parametrik ve etiketli gürültü enjeksiyonu gereklidir.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

__all__ = [
    "DirtyDataConfig",
    "DirtyDataEngine",
    "inject_dirty_data",
]

_KEYBOARD_NEIGHBORS = {
    'a': 'qwsz', 'b': 'vghn', 'c': 'xdfv', 'd': 'ersfxc', 'e': 'wsdr',
    'f': 'rtgvcd', 'g': 'tyhbvf', 'h': 'yujnbg', 'i': 'ujko', 'j': 'uikmnh',
    'k': 'ijlm', 'l': 'okp', 'm': 'njk', 'n': 'bhjm', 'o': 'iklp',
    'p': 'ol', 'q': 'wa', 'r': 'edft', 's': 'wedxza', 't': 'rfgy',
    'u': 'yhji', 'v': 'cfgb', 'w': 'qase', 'x': 'zsdc', 'y': 'tghu', 'z': 'asx'
}


@dataclass
class DirtyDataConfig:
    """Kirli veri üretim yapılandırması."""

    dirty_rate: float = 0.05                  # Bozulacak toplam satır oranı (%5)
    missing_rate: float = 0.03                # Null/NaN yapılma ihtimali
    typo_rate: float = 0.03                   # Yazım hatası eklenme ihtimali
    outlier_spike_rate: float = 0.02          # Mantıksız uç değer üretilme ihtimali
    casing_noise_rate: float = 0.03           # Büyük/küçük harf bozulması ihtimali
    
    exclude_columns: Set[str] = field(default_factory=lambda: {
        "id", "is_fraud", "target", "label", "timestamp", "date"
    })
    add_audit_columns: bool = True            # is_corrupted ve corruption_details eklensin mi?
    random_seed: int = 42


class DirtyDataEngine:
    """DataFrame üzerinde kontrollü gürültü ve veri kirliliği simülatörü."""

    def __init__(self, config: Optional[DirtyDataConfig] = None):
        self.config = config or DirtyDataConfig()

    def corrupt(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Verilen DataFrame'e yapılandırılmış gürültü enjekte eder."""
        if df.empty:
            return df.copy(), {"corrupted_rows": 0, "corrupted_rate": 0.0}

        df_out = df.copy()
        n_rows = len(df_out)
        rng = np.random.default_rng(self.config.random_seed)

        target_corrupt_count = max(1, int(round(n_rows * self.config.dirty_rate)))
        corrupted_indices = set(rng.choice(df_out.index, size=target_corrupt_count, replace=False))

        reasons: Dict[int, List[str]] = {idx: [] for idx in corrupted_indices}

        eligible_cols = [c for c in df_out.columns if c.lower() not in self.config.exclude_columns]

        # Convert Categorical columns to object dtype to prevent pandas category assignment errors
        for c in eligible_cols:
            if isinstance(df_out[c].dtype, pd.CategoricalDtype) or df_out[c].dtype.name == "category":
                df_out[c] = df_out[c].astype(object)

        numeric_cols = [c for c in eligible_cols if pd.api.types.is_numeric_dtype(df_out[c])]
        string_cols = [c for c in eligible_cols if pd.api.types.is_string_dtype(df_out[c]) or pd.api.types.is_object_dtype(df_out[c])]

        for idx in corrupted_indices:
            # 1. Eksik Değer (Missingness / NaN)
            if rng.random() < self.config.missing_rate and eligible_cols:
                col = rng.choice(eligible_cols)
                if df_out[col].dtype == bool:
                    df_out[col] = df_out[col].astype(object)
                df_out.at[idx, col] = np.nan
                reasons[idx].append(f"missing_value:{col}")

            # 2. Yazım Hatası (Typo)
            if rng.random() < self.config.typo_rate and string_cols:
                col = rng.choice(string_cols)
                val = str(df_out.at[idx, col]) if pd.notna(df_out.at[idx, col]) else ""
                if len(val) >= 3:
                    corrupted_str = self._inject_typo(val, rng)
                    df_out.at[idx, col] = corrupted_str
                    reasons[idx].append(f"typo:{col}")

            # 3. Mantıksal Sınır Taşması (Outlier Spike)
            if rng.random() < self.config.outlier_spike_rate and numeric_cols:
                col = rng.choice(numeric_cols)
                curr_val = df_out.at[idx, col]
                if pd.notna(curr_val):
                    spike_val = self._generate_spike(curr_val, col, rng)
                    df_out.at[idx, col] = spike_val
                    reasons[idx].append(f"outlier_spike:{col}")

            # 4. Büyük/Küçük Harf ve Boşluk Karmaşası
            if rng.random() < self.config.casing_noise_rate and string_cols:
                col = rng.choice(string_cols)
                val = str(df_out.at[idx, col]) if pd.notna(df_out.at[idx, col]) else ""
                if val:
                    noisy_str = self._inject_casing_whitespace(val, rng)
                    df_out.at[idx, col] = noisy_str
                    reasons[idx].append(f"casing_whitespace:{col}")

            if not reasons[idx] and eligible_cols:
                col = rng.choice(eligible_cols)
                if df_out[col].dtype == bool:
                    df_out[col] = df_out[col].astype(object)
                df_out.at[idx, col] = np.nan
                reasons[idx].append(f"fallback_missing:{col}")

        if self.config.add_audit_columns:
            df_out["is_corrupted"] = [idx in corrupted_indices for idx in df_out.index]
            df_out["corruption_details"] = [
                ", ".join(reasons[idx]) if idx in reasons and reasons[idx] else "clean"
                for idx in df_out.index
            ]

        meta = {
            "total_rows": n_rows,
            "corrupted_rows": len(corrupted_indices),
            "corrupted_rate": round(len(corrupted_indices) / n_rows, 4),
            "corruption_breakdown": {
                "missing": sum(1 for r in reasons.values() if any("missing" in x for x in r)),
                "typo": sum(1 for r in reasons.values() if any("typo" in x for x in r)),
                "outlier_spike": sum(1 for r in reasons.values() if any("outlier_spike" in x for x in r)),
                "casing": sum(1 for r in reasons.values() if any("casing" in x for x in r)),
            }
        }
        return df_out, meta

    def _inject_typo(self, text: str, rng) -> str:
        if len(text) < 2:
            return text
        pos = rng.integers(0, len(text))
        char = text[pos].lower()
        action = rng.choice(["swap", "delete", "repeat", "replace"])

        chars = list(text)
        if action == "swap" and pos < len(chars) - 1:
            chars[pos], chars[pos + 1] = chars[pos + 1], chars[pos]
        elif action == "delete" and len(chars) > 2:
            chars.pop(pos)
        elif action == "repeat":
            chars.insert(pos, chars[pos])
        elif action == "replace" and char in _KEYBOARD_NEIGHBORS:
            neighbor = rng.choice(list(_KEYBOARD_NEIGHBORS[char]))
            chars[pos] = neighbor.upper() if text[pos].isupper() else neighbor
        return "".join(chars)

    def _generate_spike(self, val: float, col_name: str, rng) -> float:
        col_lower = col_name.lower()
        if "age" in col_lower or "yas" in col_lower:
            return float(rng.choice([999, -1, 150, 0]))
        if "price" in col_lower or "amount" in col_lower or "tutar" in col_lower:
            return float(rng.choice([-99.0, 999999.0, 0.0001]))
        if "score" in col_lower or "oran" in col_lower or "ratio" in col_lower:
            return float(rng.choice([-1.0, 99.9, 1000.0]))
        factor = float(rng.choice([100.0, -10.0, 0.0]))
        return round(float(val) * factor, 2)

    def _inject_casing_whitespace(self, text: str, rng) -> str:
        noise_type = rng.choice(["upper", "lower", "spaces", "mixed"])
        if noise_type == "upper":
            return text.upper()
        if noise_type == "lower":
            return text.lower()
        if noise_type == "spaces":
            return f"  {text}   "
        return "".join(c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(text))


def inject_dirty_data(
    df: pd.DataFrame,
    dirty_rate: float = 0.05,
    missing_rate: float = 0.03,
    typo_rate: float = 0.03,
    outlier_spike_rate: float = 0.02,
    seed: int = 42,
    add_audit_columns: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    cfg = DirtyDataConfig(
        dirty_rate=dirty_rate,
        missing_rate=missing_rate,
        typo_rate=typo_rate,
        outlier_spike_rate=outlier_spike_rate,
        random_seed=seed,
        add_audit_columns=add_audit_columns,
    )
    engine = DirtyDataEngine(cfg)
    return engine.corrupt(df)
