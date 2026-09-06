# -*- coding: utf-8 -*-
"""Zaman Serisi ve Hız Dinamiği Motoru (TimeSeriesEngine).

Gerçek dünyada işlemler, sağlık kayıtları, IoT olayları ve kullanıcı davranışları
anlık tekil fotoğraflar değildir; zaman ekseni üzerinde ardışık (sequential) akar.

Bu modül:
  1. Varlık / Kullanıcı bazlı kronolojik olay zaman damgaları (`timestamp`) üretir.
  2. Sirkadiyen Ritim (Circadian Rhythm): Günün saatlerine göre doğal insan aktivitesi
     (gece 03:00'te düşük işlem, öğlen 14:00'te zirve) simüle eder.
  3. Hız Dinamiği (Velocity Metrics): İşlemler arası geçen süre (`delta_seconds`),
     son 1 saatteki işlem sayısı (`tx_count_1h`) gibi kritik anomali sinyalleri üretir.
  4. Dolandırıcılık Patlamaları (Burst Attack): Dolandırıcılık vakalarında kart deneme
     (10 saniye arayla 5 ardışık işlem) gibi yüksek hızlı anomali kümeleri oluşturur.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

__all__ = [
    "TimeSeriesConfig",
    "TimeSeriesEngine",
    "apply_time_series_dynamics",
]


@dataclass
class TimeSeriesConfig:
    """Zaman serisi ve hız dinamiği yapılandırması."""

    timestamp_column: str = "transaction_timestamp"
    entity_id_column: Optional[str] = "customer_id"  # Varlık kimliği (kullanıcı/kart)
    start_date: str = "2026-08-01 00:00:00"
    end_date: str = "2026-09-01 23:59:59"
    
    # Hız ve anomali ayarları
    add_velocity_columns: bool = True               # delta_seconds, velocity_1h eklensin mi?
    circadian_pattern: bool = True                 # Gece/gündüz aktivite eğrisi
    burst_anomalies: bool = True                   # Dolandırıcılık patlamaları
    burst_rate: float = 0.02                       # Patlama anomali oranı
    random_seed: int = 42


class TimeSeriesEngine:
    """Sentetik verilere zamansal derinlik ve hız dinamiği kazandıran motor."""

    def __init__(self, config: Optional[TimeSeriesConfig] = None):
        self.config = config or TimeSeriesConfig()

    def apply(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Verilen DataFrame'e kronolojik sıralama, zaman damgaları ve hız kolonları ekler."""
        if df.empty:
            return df.copy(), {"total_rows": 0}

        df_out = df.copy()
        n_rows = len(df_out)
        rng = np.random.default_rng(self.config.random_seed)

        start_dt = pd.to_datetime(self.config.start_date)
        end_dt = pd.to_datetime(self.config.end_date)
        total_seconds = max(1.0, (end_dt - start_dt).total_seconds())

        # Varlık kolonunu kontrol et / oluştur
        entity_col = self.config.entity_id_column
        if entity_col not in df_out.columns:
            # 1.000 satır için ~100-200 tekil kullanıcı
            n_entities = max(10, n_rows // 8)
            entity_pool = [f"USR_{1000 + i}" for i in range(n_entities)]
            df_out[entity_col or "entity_id"] = rng.choice(entity_pool, size=n_rows)
            entity_col = entity_col or "entity_id"

        # Sirkadiyen ritim ağırlıkları (24 saat için olasılık dağılımı)
        # Gece 02-05 dip (0.01), öğlen 12-18 zirve (0.08)
        hour_weights = np.array([
            0.015, 0.010, 0.005, 0.005, 0.010, 0.020,  # 00 - 05
            0.035, 0.050, 0.065, 0.070, 0.075, 0.080,  # 06 - 11
            0.085, 0.080, 0.075, 0.070, 0.065, 0.060,  # 12 - 17
            0.055, 0.050, 0.045, 0.035, 0.025, 0.020   # 18 - 23
        ])
        hour_weights = hour_weights / hour_weights.sum()

        timestamps = []
        is_burst = np.zeros(n_rows, dtype=bool)

        # Temel zaman damgalarını üret
        base_offsets = rng.uniform(0, total_seconds, size=n_rows)
        base_dts = start_dt + pd.to_timedelta(base_offsets, unit="s")

        if self.config.circadian_pattern:
            # Saatleri sirkadiyen dağılıma göre kaydır
            sampled_hours = rng.choice(np.arange(24), p=hour_weights, size=n_rows)
            sampled_minutes = rng.integers(0, 60, size=n_rows)
            sampled_seconds = rng.integers(0, 60, size=n_rows)
            
            dts_adjusted = []
            for dt, h, m, s in zip(base_dts, sampled_hours, sampled_minutes, sampled_seconds):
                dts_adjusted.append(dt.replace(hour=h, minute=m, second=s))
            base_dts = pd.Series(dts_adjusted)

        df_out[self.config.timestamp_column] = base_dts

        # Varlık bazında kronolojik sırala
        df_out = df_out.sort_values(by=[entity_col, self.config.timestamp_column]).reset_index(drop=True)

        # Hız (Velocity) ve Zaman Farkı Metrikleri
        if self.config.add_velocity_columns:
            # delta_seconds: Aynı kullanıcının bir önceki işlemiyle arasındaki saniye
            time_deltas = df_out.groupby(entity_col)[self.config.timestamp_column].diff().dt.total_seconds()
            df_out["seconds_since_last_tx"] = time_deltas.fillna(86400.0).clip(lower=0.0).round(1)

            # Patlama (Burst) Senaryosu Enjeksiyonu
            if self.config.burst_anomalies:
                n_bursts = max(1, int(round(n_rows * self.config.burst_rate)))
                burst_indices = rng.choice(df_out.index[1:], size=n_bursts, replace=False)
                
                for b_idx in burst_indices:
                    # Bir önceki işlemin hemen peşinden (5 - 30 saniye sonra) yapılmış gibi ayarla
                    prev_time = df_out.at[b_idx - 1, self.config.timestamp_column]
                    fast_delta = rng.uniform(4.0, 25.0)
                    df_out.at[b_idx, self.config.timestamp_column] = prev_time + pd.to_timedelta(fast_delta, unit="s")
                    df_out.at[b_idx, "seconds_since_last_tx"] = round(fast_delta, 1)
                    is_burst[b_idx] = True
                    
                    # Eğer is_fraud varsa patlama işlemlerini fraud işaretle
                    if "is_fraud" in df_out.columns:
                        if pd.api.types.is_bool_dtype(df_out["is_fraud"]):
                            df_out.at[b_idx, "is_fraud"] = True
                        elif pd.api.types.is_float_dtype(df_out["is_fraud"]):
                            df_out.at[b_idx, "is_fraud"] = 1.0
                        else:
                            df_out.at[b_idx, "is_fraud"] = 1

                df_out["is_burst_velocity"] = is_burst

            # tx_velocity_1h: Son 1 saat içinde yapılan kümülatif işlem göstergesi
            # Hızlı vektörize proxy: delta < 3600 ise hız yüksek
            is_fast = df_out["seconds_since_last_tx"] < 3600.0
            df_out["is_high_velocity"] = is_fast

        # Tüm veri setini genel zamana göre yeniden sırala
        df_out = df_out.sort_values(by=self.config.timestamp_column).reset_index(drop=True)

        meta = {
            "total_rows": n_rows,
            "unique_entities": df_out[entity_col].nunique(),
            "time_range": f"{df_out[self.config.timestamp_column].min()} to {df_out[self.config.timestamp_column].max()}",
            "burst_anomalies_count": int(is_burst.sum()),
            "median_delta_seconds": float(df_out["seconds_since_last_tx"].median()) if "seconds_since_last_tx" in df_out.columns else 0.0,
        }
        log.info("Zaman serisi dinamiği uygulandı: %d satır, %d varlık",
                 meta["total_rows"], meta["unique_entities"])
        return df_out, meta


def apply_time_series_dynamics(
    df: pd.DataFrame,
    timestamp_column: str = "transaction_timestamp",
    entity_id_column: Optional[str] = "customer_id",
    start_date: str = "2026-08-01 00:00:00",
    end_date: str = "2026-09-01 23:59:59",
    add_velocity_columns: bool = True,
    circadian_pattern: bool = True,
    burst_anomalies: bool = True,
    seed: int = 42,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    cfg = TimeSeriesConfig(
        timestamp_column=timestamp_column,
        entity_id_column=entity_id_column,
        start_date=start_date,
        end_date=end_date,
        add_velocity_columns=add_velocity_columns,
        circadian_pattern=circadian_pattern,
        burst_anomalies=burst_anomalies,
        random_seed=seed,
    )
    engine = TimeSeriesEngine(cfg)
    return engine.apply(df)
