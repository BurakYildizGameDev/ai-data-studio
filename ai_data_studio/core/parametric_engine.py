# -*- coding: utf-8 -*-
"""Parametrik ve Deterministik Veri Derleme Motoru (ParametricEngine).

Düşük donanımlı (düşük VRAM, CPU-only, 8 GB RAM) sistemlerde çalışan küçük yerel
modeller (1.5B, 3B, 7B) için "Nöro-Sembolik / Hibrit" veri üretim motoru.

Mimari Felsefesi:
  - Küçük model sadece alan uzmanlığı ve semantik kararları verir -> JSON Schema Contract üretir.
  - Python kod yazma ameleliği, girinti (indentation), sözdizimi ve kütüphane hataları
    tamamen ortadan kaldırılır.
  - Şema doğrudan bu motor tarafından C hızındaki `numpy` ve `pandas` vektörlerine derlenir.
  - 100.000 satır veri 0.1 saniye içinde, %100 deterministik ve hatasız üretilir.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .dataset_contract import DatasetContract
from .schema_contract import ColumnSpec, SchemaContract

log = logging.getLogger(__name__)

__all__ = [
    "ParametricEngine",
    "compile_schema_to_dataframe",
    "compile_relational",
    "compile_dataset_to_dataframes",
]


def _is_binary(series: pd.Series) -> bool:
    """Kolon ikili (bool ya da yalnızca 0/1) mi?

    Dolandırıcılık / churn etiketleri bazen bool, bazen 0-1 int gelir; korelasyon
    kurma yolu ikisinde de aynı olmalı.
    """
    if pd.api.types.is_bool_dtype(series):
        return True
    if not pd.api.types.is_numeric_dtype(series):
        return False
    values = pd.unique(pd.to_numeric(series, errors="coerce").dropna())
    return len(values) <= 2 and set(np.asarray(values).astype(float)).issubset({0.0, 1.0})


class ParametricEngine:
    """SchemaContract ve DatasetContract nesnelerini doğrudan yüksek hızlı
    DataFrame'lere derleyen deterministik motor.
    """

    def __init__(self, seed: Optional[int] = None):
        self.default_seed = seed or 42

    def compile(self, schema: SchemaContract, n_rows: Optional[int] = None,
                seed: Optional[int] = None) -> pd.DataFrame:
        """Şemayı doğrular ve doğrudan vektörize sentetik veri üretir."""
        rows = n_rows or schema.row_count_target or 1000
        rng_seed = seed or schema.random_seed or self.default_seed
        rng = np.random.default_rng(rng_seed)

        data: Dict[str, Any] = {}

        for col in schema.columns:
            data[col.name] = self._generate_column(col, rows, rng, schema.faker_locale)

        df = pd.DataFrame(data)

        # Birincil anahtar tekilliğini garanti et
        if schema.primary_key and schema.primary_key in df.columns:
            pk_col = schema.column(schema.primary_key)
            if pk_col and pk_col.type.lower() in ("str", "string", "text", "varchar"):
                prefix = (schema.table_name or schema.domain or pk_col.name or "ID")[:3].upper()
                df[schema.primary_key] = [f"{prefix}_{i:06d}" for i in range(1, rows + 1)]
            else:
                df[schema.primary_key] = np.arange(1, rows + 1, dtype=int)

        # Korelasyonları uygula (Basit Gauss Copula yaklaşımı)
        if schema.correlations:
            df = self._apply_correlations(df, schema.correlations, rng)

        # İş kurallarını uygula / düzelt
        if schema.business_rules:
            df = self._enforce_business_rules(df, schema.business_rules)

        return df

    def compile_relational(self, contract: DatasetContract,
                           root_rows: Optional[int] = None,
                           seed: Optional[int] = None) -> Dict[str, pd.DataFrame]:
        """DatasetContract nesnesindeki tüm tabloları yabancı anahtar ve kardinalite
        tutarlılığıyla doğrudan vektörize sentetik veri setine derler.
        """
        rng_seed = seed or contract.random_seed or self.default_seed
        rng = np.random.default_rng(rng_seed)

        tables: Dict[str, pd.DataFrame] = {}
        order = contract.generation_order()

        for table_name in order:
            schema = contract.table(table_name)
            parents = contract.parents_of(table_name)

            if not parents:
                # Kök tablo veya ebeveyni olmayan bağımsız tablo
                if table_name == contract.root_table:
                    n_rows = root_rows or schema.row_count_target or 1000
                else:
                    n_rows = schema.row_count_target or root_rows or 1000
                table_seed = int(rng.integers(0, 2**31 - 1))
                df = self.compile(schema, n_rows=n_rows, seed=table_seed)
                tables[table_name] = df
            else:
                # Çocuk tablo: satır sayısı birincil ebeveynin kardinalitesinden türer
                primary_rel = parents[0]
                parent_df = tables[primary_rel.parent_table]
                n_parents = len(parent_df)

                mean_c = primary_rel.mean_per_parent
                min_c = primary_rel.min_per_parent
                max_c = primary_rel.max_per_parent

                # Poisson tabanlı kardinalite dağılımı
                counts = rng.poisson(lam=mean_c, size=n_parents)
                if min_c > 0 or max_c is not None:
                    counts = np.clip(counts, min_c, max_c if max_c is not None else 1000000)

                # Eğer toplam 0 satır çıkarsa en az bir satır garanti et
                if int(np.sum(counts)) == 0:
                    counts[0] = max(1, min_c)

                parent_pks = parent_df[primary_rel.parent_key].to_numpy()
                primary_fks = np.repeat(parent_pks, counts)
                n_rows = len(primary_fks)

                table_seed = int(rng.integers(0, 2**31 - 1))
                df = self.compile(schema, n_rows=n_rows, seed=table_seed)
                df[primary_rel.child_key] = primary_fks

                # Varsa diğer ebeveyn ilişkilerini de bağla (örn. order_items -> products)
                for other_rel in parents[1:]:
                    other_parent_df = tables.get(other_rel.parent_table)
                    if other_parent_df is not None and other_rel.parent_key in other_parent_df.columns:
                        other_pks = other_parent_df[other_rel.parent_key].to_numpy()
                        if len(other_pks) > 0:
                            sampled_fks = rng.choice(other_pks, size=n_rows, replace=True)
                            df[other_rel.child_key] = sampled_fks

                tables[table_name] = df

        return tables

    def _generate_column(self, col: ColumnSpec, n_rows: int, rng: np.random.Generator,
                         locale: str) -> np.ndarray:
        """Tek bir kolon için dağılıma uygun vektörize veri üretir."""
        col_type = col.type.lower()
        dist = (col.distribution or "uniform").lower()

        # 1. SAYISAL ALANLAR (int, float)
        if col_type in ("int", "float"):
            min_val = col.min if col.min is not None else 0.0
            max_val = col.max if col.max is not None else 1000.0
            mean_val = col.mean if col.mean is not None else (min_val + max_val) / 2.0
            std_val = col.std if col.std is not None else max(1.0, (max_val - min_val) / 6.0)

            if dist == "normal":
                vals = rng.normal(loc=mean_val, scale=std_val, size=n_rows)
            elif dist == "lognormal":
                # Lognormal parametre tahmini
                sigma = 0.8
                mu = np.log(max(mean_val, 1.0)) - (sigma ** 2) / 2.0
                vals = rng.lognormal(mean=mu, sigma=sigma, size=n_rows)
            elif dist == "exponential":
                scale = max(mean_val, 1.0)
                vals = rng.exponential(scale=scale, size=n_rows)
            elif dist == "poisson":
                lam = max(0.1, mean_val)
                vals = rng.poisson(lam=lam, size=n_rows).astype(float)
            elif dist == "gamma":
                shape = col.shape if col.shape is not None else 2.0
                scale = col.scale if col.scale is not None else 1.0
                vals = rng.gamma(shape=shape, scale=scale, size=n_rows)
            elif dist in ("pareto", "gpd"):
                shape = col.shape if col.shape is not None else 3.0
                vals = (rng.pareto(a=shape, size=n_rows) + 1.0) * (min_val or 1.0)
            else: # uniform varsayılan
                vals = rng.uniform(low=min_val, high=max_val, size=n_rows)

            # Sınır kırpma (clipping)
            if col.min is not None or col.max is not None:
                vals = np.clip(vals, col.min if col.min is not None else -1e9,
                                     col.max if col.max is not None else 1e9)

            if col_type == "int":
                return np.round(vals).astype(int)
            return np.round(vals, 2)

        # 2. BOOLEAN ALANLAR
        if col_type == "bool":
            ratio = col.target_ratio if col.target_ratio is not None else 0.5
            return rng.random(size=n_rows) < ratio

        # 3. KATEGORİK ALANLAR
        if col_type in ("category", "str") and col.categories:
            cats = list(col.categories)
            # Rastgele doğal ağırlık dağılımı
            weights = rng.dirichlet(np.ones(len(cats)))
            return rng.choice(cats, p=weights, size=n_rows)

        # 4. ZAMAN / TARİH ALANLARI
        if col_type == "datetime":
            start = pd.to_datetime("2026-01-01")
            end = pd.to_datetime("2026-09-01")
            offset_seconds = rng.uniform(0, (end - start).total_seconds(), size=n_rows)
            return start + pd.to_timedelta(offset_seconds, unit="s")

        # 5. DÜZ METİN (Fallback)
        pool = [f"{col.name.upper()}_{i:04d}" for i in range(min(500, max(10, n_rows // 2)))]
        return rng.choice(pool, size=n_rows)

    @staticmethod
    def _target_corr(rule: Any) -> float:
        """Kuraldan hedef korelasyon katsayısını (işaretiyle) çıkarır."""
        target = rule.min_r if getattr(rule, "min_r", None) is not None else 0.7
        if getattr(rule, "expected_sign", "") == "negative":
            return -abs(target)
        return abs(target)

    @staticmethod
    def _standardize(series: pd.Series) -> np.ndarray:
        values = pd.to_numeric(series, errors="coerce").astype(float).to_numpy()
        std = np.nanstd(values)
        return (values - np.nanmean(values)) / (std if std else 1.0)

    def _apply_correlations(self, df: pd.DataFrame, correlations: List[Any],
                            rng: np.random.Generator) -> pd.DataFrame:
        """Belirtilen kolon çiftleri arasında doğrusal/sıralı korelasyon oluşturur.

        İki ayrı yol var:

        * **Sayısal - sayısal:** hedef kolon, sürücünün standartlaştırılmış hâli ile
          gürültünün ``r * X + sqrt(1 - r^2) * Z`` harmanı olarak yeniden üretilir.
        * **Sayısal - boolean:** boolean kolon doğrudan harmanlanamaz (0/1'e blend
          uygulamak oranı da dağılımı da bozar). Bunun yerine gizli (latent) bir
          normal değişken kurulur ve hedef orana karşılık gelen kuantilden eşiklenir;
          böylece hem ``target_ratio`` korunur hem de nokta-çift serili korelasyon
          gerçekleşir. Eşikleme korelasyonu zayıflattığı için latent katsayı
          ``phi(z) / sqrt(p(1-p))`` çarpanıyla önceden büyütülür.

        Boolean yolu olmadan dolandırıcılık/churn gibi ikili hedefli sözleşmelerde
        beklenen korelasyonlar sıfıra yakın çıkıyordu (ölçüm: Job #17, r=0.0035).
        """
        bool_rules: Dict[str, List[Any]] = {}

        for rule in correlations:
            c1, c2 = rule.columns[0], rule.columns[1]
            if c1 not in df.columns or c2 not in df.columns:
                continue

            b1, b2 = _is_binary(df[c1]), _is_binary(df[c2])
            n1 = pd.api.types.is_numeric_dtype(df[c1]) and not b1
            n2 = pd.api.types.is_numeric_dtype(df[c2]) and not b2

            # Boolean hedefli kurallar toplanip TEK seferde uygulanir: ayni bool
            # kolona bakan birden fazla kural sirayla uygulansaydi her biri
            # oncekini ezerdi (canli kosuda uc kural da is_fraud'a bakiyordu).
            if b1 and n2:
                bool_rules.setdefault(c1, []).append((c2, self._target_corr(rule)))
                continue
            if b2 and n1:
                bool_rules.setdefault(c2, []).append((c1, self._target_corr(rule)))
                continue
            if b1 and b2:
                # İkisi de boolean ise: önceden hedef olan kolona sürücü ekle,
                # aksi halde c1'i c2'ye sürücü yap (örn. card_present -> is_fraud).
                if c1 in bool_rules and c2 not in bool_rules:
                    bool_rules[c1].append((c2, self._target_corr(rule)))
                else:
                    bool_rules.setdefault(c2, []).append((c1, self._target_corr(rule)))
                continue
            if not (n1 and n2):
                continue

            target_corr = self._target_corr(rule)
            norm_c1 = self._standardize(df[c1])
            noise = rng.normal(0, 1, size=len(df))

            # Blend: r * X + sqrt(1 - r^2) * Z
            blended = target_corr * norm_c1 + np.sqrt(max(0.01, 1 - target_corr ** 2)) * noise

            # Hedef c2'nin orijinal ölçeğine geri dönüştür
            df[c2] = (blended * (df[c2].std() or 1.0) + df[c2].mean()).round(2)

        for column, drivers in bool_rules.items():
            df[column] = self._correlated_binary(df, column, drivers, rng)
        return df

    @staticmethod
    def _normal_scores(series: pd.Series) -> np.ndarray:
        """Kolonu sıra (rank) üzerinden normal skorlara çevirir - van der Waerden.

        Standartlaştırma tek başına yetmiyor: eşikleme formülü iki değişkenli
        normallik varsayar, sürücüler ise lognormal / Poisson / uniform olabiliyor.
        Sıra dönüşümü dağılımdan bağımsız bir latent kurmayı sağlıyor.
        """
        from scipy import stats

        values = pd.to_numeric(series, errors="coerce")
        n = len(values)
        if n == 0:
            return np.zeros(0)
        ranks = values.rank(method="average", na_option="keep").to_numpy(dtype=float)
        return np.nan_to_num(stats.norm.ppf((ranks - 0.5) / n), nan=0.0)

    def _correlated_binary(self, df: pd.DataFrame, column: str,
                           drivers: List[Tuple[str, float]],
                           rng: np.random.Generator) -> np.ndarray:
        """Boolean kolonu, sürücüleriyle korelasyonlu ve oranı korunmuş üretir."""
        from scipy import stats

        original = df[column]
        ratio = float(pd.to_numeric(original, errors="coerce").mean())
        if not 0.0 < ratio < 1.0:
            return original.to_numpy()

        # Eşikleme zayıflatmasi: dikotomize edilmis iki degiskenli normalde
        # r_gozlenen = r_latent * phi(z) / sqrt(p(1-p)). Latent katsayiyi bu
        # carpanla bolerek istenen GOZLENEN korelasyonu hedefliyoruz.
        z = stats.norm.ppf(1.0 - ratio)
        attenuation = stats.norm.pdf(z) / np.sqrt(ratio * (1.0 - ratio))
        if attenuation <= 0:
            return original.to_numpy()

        scores = [self._normal_scores(df[driver]) for driver, _ in drivers]
        targets = np.array([target for _, target in drivers], dtype=float)
        raw_weights = []
        for driver, target in drivers:
            atten = attenuation
            if _is_binary(df[driver]):
                d_p = float(pd.to_numeric(df[driver], errors="coerce").mean())
                if 0.0 < d_p < 1.0:
                    dz = stats.norm.ppf(1.0 - d_p)
                    d_atten = stats.norm.pdf(dz) / np.sqrt(d_p * (1.0 - d_p))
                    if d_atten > 0:
                        atten *= d_atten
            raw_weights.append(np.clip(target / atten, -0.95, 0.95))
        weights = np.array(raw_weights, dtype=float)
        noise = rng.normal(0, 1, size=len(df))

        def build(ws: np.ndarray) -> np.ndarray:
            combined = np.zeros(len(df), dtype=float)
            for weight, score in zip(ws, scores):
                combined += weight * score
            # Toplam varyans 1'i asarsa gurultuye yer kalmaz; katsayilari birlikte
            # olcekle - butun korelasyonlar orantili zayiflar ama tutarli kalir.
            explained = float(np.var(combined))
            if explained > 0.98:
                combined *= np.sqrt(0.98 / explained)
                explained = 0.98
            combined += np.sqrt(max(0.02, 1.0 - explained)) * noise
            return combined >= np.quantile(combined, 1.0 - ratio)

        flags = build(weights)

        # Tek adim kalibrasyon: formul normallik varsayiyor, gercek surucular
        # (lognormal kuyruk, Poisson basamaklari) hedefin altinda kaliyor. Olculen
        # sapmayi agirliklara geri besleyip bir kez daha kuruyoruz.
        observed = np.array([
            self._point_biserial(df[driver], flags) for driver, _ in drivers
        ])
        safe = np.where(np.abs(observed) < 1e-3, np.sign(targets) * 1e-3, observed)
        corrected = np.clip(weights * (targets / safe), -0.95, 0.95)
        if np.all(np.isfinite(corrected)):
            retry = build(corrected)
            retry_obs = np.array([
                self._point_biserial(df[driver], retry) for driver, _ in drivers
            ])
            # Yalnizca gercekten yaklastiysa kabul et - kalibrasyon geri tepmesin.
            if np.sum(np.abs(retry_obs - targets)) < np.sum(np.abs(observed - targets)):
                flags = retry

        if pd.api.types.is_bool_dtype(original):
            return flags
        return flags.astype(original.dtype if original.dtype != object else int)

    @staticmethod
    def _point_biserial(driver: pd.Series, flags: np.ndarray) -> float:
        values = pd.to_numeric(driver, errors="coerce").astype(float)
        r = values.corr(pd.Series(flags.astype(float), index=values.index))
        return 0.0 if pd.isna(r) else float(r)

    def _enforce_business_rules(self, df: pd.DataFrame, rules: List[str]) -> pd.DataFrame:
        """df.eval ile kuralları filtreler veya sınırları düzeltir."""
        for rule in rules:
            try:
                # Kolonlar arası karşılaştırma: col_a <= col_b
                if "<=" in rule:
                    parts = rule.split("<=")
                    left, right = parts[0].strip(), parts[1].strip()
                    if left in df.columns and right in df.columns:
                        df[left] = np.minimum(df[left], df[right])
                elif ">=" in rule:
                    parts = rule.split(">=")
                    left, right = parts[0].strip(), parts[1].strip()
                    if left in df.columns and right in df.columns:
                        df[left] = np.maximum(df[left], df[right])
            except Exception as exc:
                log.debug("Kural düzeltme atlandı: %s (%s)", rule, exc)
        return df


def compile_schema_to_dataframe(schema: SchemaContract, n_rows: Optional[int] = None,
                                seed: Optional[int] = None) -> pd.DataFrame:
    """Tek fonksiyonla şemadan deterministik DataFrame üretir."""
    engine = ParametricEngine(seed=seed)
    return engine.compile(schema, n_rows=n_rows, seed=seed)


def compile_dataset_to_dataframes(contract: DatasetContract,
                                  root_rows: Optional[int] = None,
                                  seed: Optional[int] = None) -> Dict[str, pd.DataFrame]:
    """Tek fonksiyonla DatasetContract'tan deterministik ilişkisel DataFrame sözlüğü üretir."""
    engine = ParametricEngine(seed=seed)
    return engine.compile_relational(contract, root_rows=root_rows, seed=seed)


def compile_relational(contract: DatasetContract,
                       root_rows: Optional[int] = None,
                       seed: Optional[int] = None) -> Dict[str, pd.DataFrame]:
    """compile_dataset_to_dataframes için pratik takma ad (alias)."""
    return compile_dataset_to_dataframes(contract, root_rows=root_rows, seed=seed)

