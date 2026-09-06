# -*- coding: utf-8 -*-
"""Otomatik Özellik Genişletici (Automated Derived Feature Expander).

Küçük modeller (1.5B/3B) 6-10 temel kolon ürettiğinde bile, bu motor
mevcut değişkenlerden deterministik finansal, demografik ve zamansal oranlar
türeterek kolon sayısını anında 18-25+ kurumsal seviyeye çıkarır.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def expand_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
    """DataFrame içindeki temel değişkenlerden otomatik türetilmiş kurumsal özellikler ekler.

    Döner:
        (df_expanded, metadata)
    """
    df_out = df.copy()
    added_cols: List[str] = []

    col_map = {c.lower(): c for c in df_out.columns}

    # 1. Finansal Oranlar: Harcama / Gelir Oranı
    amt_col = None
    for k in ["transaction_amount", "amount", "order_amount"]:
        if k in col_map:
            amt_col = col_map[k]
            break

    inc_col = None
    for k in ["income", "customer_income", "annual_income"]:
        if k in col_map:
            inc_col = col_map[k]
            break

    if amt_col and inc_col and "amount_to_income_ratio" not in df_out.columns:
        monthly_inc = df_out[inc_col].replace(0, np.nan) / 12.0
        df_out["amount_to_income_ratio"] = (df_out[amt_col] / monthly_inc).round(4).fillna(0.0)
        added_cols.append("amount_to_income_ratio")

    # Kredi Kartı Limit Kullanım Oranı
    limit_col = None
    for k in ["credit_limit", "credit_limit_usd", "card_limit"]:
        if k in col_map:
            limit_col = col_map[k]
            break

    if amt_col and limit_col and "credit_utilization_ratio" not in df_out.columns:
        valid_lim = df_out[limit_col].replace(0, np.nan)
        df_out["credit_utilization_ratio"] = (df_out[amt_col] / valid_lim).round(4).fillna(0.0)
        added_cols.append("credit_utilization_ratio")

    # 2. Demografik Gruplama: Yaş Grupları
    age_col = None
    for k in ["customer_age", "age"]:
        if k in col_map:
            age_col = col_map[k]
            break

    if age_col and "age_group" not in df_out.columns:
        def _categorize_age(v):
            if pd.isna(v): return "UNKNOWN"
            if v < 30: return "YOUNG"
            if v < 50: return "ADULT"
            if v < 65: return "MATURE"
            return "SENIOR"
        df_out["age_group"] = df_out[age_col].apply(_categorize_age).astype("category")
        added_cols.append("age_group")

    # Kredi Skoru Sınıflandırması
    score_col = None
    for k in ["credit_score", "customer_credit_score", "score"]:
        if k in col_map:
            score_col = col_map[k]
            break

    if score_col and "credit_rating" not in df_out.columns:
        def _categorize_score(v):
            if pd.isna(v): return "UNKNOWN"
            if v < 580: return "POOR"
            if v < 670: return "FAIR"
            if v < 740: return "GOOD"
            if v < 800: return "VERY_GOOD"
            return "EXCELLENT"
        df_out["credit_rating"] = df_out[score_col].apply(_categorize_score).astype("category")
        added_cols.append("credit_rating")

    # 3. Zamansal Türetimler
    ts_col = None
    for k in ["transaction_timestamp", "timestamp", "order_timestamp", "date"]:
        if k in col_map:
            ts_col = col_map[k]
            break

    if ts_col:
        try:
            ts_series = pd.to_datetime(df_out[ts_col], errors="coerce")
            if "hour_of_day" not in df_out.columns:
                df_out["hour_of_day"] = ts_series.dt.hour.fillna(-1).astype(int)
                added_cols.append("hour_of_day")
            if "day_of_week" not in df_out.columns:
                df_out["day_of_week"] = ts_series.dt.day_name().fillna("Unknown").astype("category")
                added_cols.append("day_of_week")
            if "is_weekend" not in df_out.columns:
                df_out["is_weekend"] = ts_series.dt.dayofweek.isin([5, 6]).fillna(False)
                added_cols.append("is_weekend")
            if "is_night_transaction" not in df_out.columns:
                df_out["is_night_transaction"] = ts_series.dt.hour.isin([0, 1, 2, 3, 4, 5]).fillna(False)
                added_cols.append("is_night_transaction")
        except Exception as exc:
            log.debug("Zaman türetimi atlandı: %s", exc)

    # 4. Davranışsal Risk Kompozit Bayrağı
    fail_col = None
    for k in ["failed_attempts", "failed_attempts_24h", "failed_attempts_last_24h"]:
        if k in col_map:
            fail_col = col_map[k]
            break

    if fail_col and amt_col and "is_high_risk_combo" not in df_out.columns:
        med_amt = df_out[amt_col].median() if len(df_out) > 0 else 100.0
        df_out["is_high_risk_combo"] = (
            (df_out[fail_col] >= 2) & (df_out[amt_col] > med_amt * 2.0)
        ).fillna(False)
        added_cols.append("is_high_risk_combo")

    meta = {
        "added_columns_count": len(added_cols),
        "added_columns": added_cols,
        "total_columns": len(df_out.columns),
    }
    return df_out, meta
