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

import ast
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .correlation import latent_from_target, pair_correlation
from .dataset_contract import DatasetContract
from .schema_contract import ColumnSpec, SchemaContract

log = logging.getLogger(__name__)

__all__ = [
    "ParametricEngine",
    "compile_schema_to_dataframe",
    "compile_relational",
    "compile_dataset_to_dataframes",
]


DEFAULT_DATETIME_WINDOW = ("2026-01-01", "2026-09-01")
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_UNTIL_RE = re.compile(r"\b(until|before|up to|through|to)\s+\d{4}-\d{2}-\d{2}", re.IGNORECASE)


def _datetime_window(description: str) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """Tarih kolonunun aralığı - sözleşme onu ``description`` içinde taşır.

    ``min``/``max`` yalnızca sayısal olduğu için tarih aralığı açıklamaya yazılır;
    sözleşme normalizasyonu da modelin tarih ``min``'ini oraya "between X and Y" /
    "from X" / "until Y" diye taşır. Motor bunu okumuyor, her tarihi sabit bir 2026
    penceresinden üretiyordu: 14b'nin ``order_date <= '2023-12-31'`` kuralı her satırda
    ihlal edildi. Tek tarih verilmişse pencere bir yıl kabul edilir.
    """
    found = []
    for text in _ISO_DATE_RE.findall(description or ""):
        try:
            found.append(pd.Timestamp(text))
        except ValueError:
            continue
    default = (pd.Timestamp(DEFAULT_DATETIME_WINDOW[0]), pd.Timestamp(DEFAULT_DATETIME_WINDOW[1]))
    if not found:
        return default
    if len(found) >= 2:
        start, end = min(found), max(found)
        return (start, end) if end > start else default
    one_year = pd.Timedelta(days=365)
    if _UNTIL_RE.search(description):
        return found[0] - one_year, found[0]
    return found[0], found[0] + one_year


_COMPARE_OPS = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "=="}
_FLIPPED = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "==": "=="}


def _comparisons(node: ast.expr) -> List[Tuple[str, str, ast.expr]]:
    """Karşılaştırmayı ``(kolon, işlem, öbür_taraf)`` üçlülerine çevirir.

    Zincirli karşılaştırma (``18 <= age <= 60``) ikili parçalara bölünür. Onarılacak
    taraf çıplak bir addır; iki taraf da çıplak adsa SOL taraf bağımlı kabul edilir
    (``discount <= basket`` -> discount düzeltilir). Sol taraf ifadeyse ve sağ taraf
    çıplak adsa işlem ters çevrilir (``item_count * 10 <= basket`` -> basket >= ...).
    """
    if not isinstance(node, ast.Compare):
        return []
    out = []
    left = node.left
    for op, right in zip(node.ops, node.comparators):
        symbol = _COMPARE_OPS.get(type(op))
        if symbol is not None:
            if isinstance(left, ast.Name):
                out.append((left.id, symbol, right))
            elif isinstance(right, ast.Name):
                out.append((right.id, _FLIPPED[symbol], left))
        left = right
    return out


@dataclass
class _RankTarget:
    """Monotonluk kuralından türetilen, korelasyon kuralı biçiminde sıra hedefi."""

    columns: List[str]
    expected_sign: str
    min_r: float
    method: str = "spearman"


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

        protected = set(schema.foreign_keys)
        if schema.primary_key:
            protected.add(schema.primary_key)

        # İş kuralları İKİ kez onarılır. Önce kopuladan ÖNCE: sabit sınırlı bir kural
        # (`sessions_per_week >= 10`) kopuladan sonra onarılınca satırların yarısını
        # aynalayıp sıralamayı tersine çeviriyor ve kurulan korelasyonu siliyordu
        # (canlı 1.5b: hedef 0.5 -> ölçülen -0.008). Kopula yalnızca değerleri yeniden
        # sıraladığı için burada sağlanan sabit sınır korunur.
        if schema.business_rules:
            df = self._enforce_business_rules(df, schema, rng, protected)

        # Korelasyonları uygula (Basit Gauss Copula yaklaşımı). Monotonluk kuralları
        # aynı kopulaya sıra hedefi olarak katılır.
        correlations = self._with_monotonicity_targets(schema)
        if correlations:
            df = self._apply_correlations(
                df, correlations, rng,
                exclude={schema.primary_key} if schema.primary_key else None)

        # Sonra kopuladan SONRA: kolonlar arası kurallar (`a <= b`) satır eşleşmesine
        # bağlıdır ve yeniden sıralama onları bozar; sabit sınırlar burada zaten sağlanmış.
        if schema.business_rules and correlations:
            df = self._enforce_business_rules(df, schema, rng, protected)

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
            start, end = _datetime_window(col.description)
            offset_seconds = rng.uniform(0, (end - start).total_seconds(), size=n_rows)
            return start + pd.to_timedelta(offset_seconds, unit="s")

        # 5. DÜZ METİN (Fallback)
        pool = [f"{col.name.upper()}_{i:04d}" for i in range(min(500, max(10, n_rows // 2)))]
        return rng.choice(pool, size=n_rows)

    # Monotonluk kuralini karsilayan sira korelasyonu. Validator'in kabul kosulu (10
    # dilimin 9 adiminin da monoton olmasi + ikili uyum >= %76.5) Kendall tau >= ~0.53'e,
    # yani gerceklesen Spearman ~0.72'ye karsilik geliyor; 0.80 (+ CORRELATION_MARGIN)
    # temizlik kaybina ragmen pay birakir.
    MONOTONIC_RANK_R = 0.80
    # Ikili (bool) hedefte dilim ortalamasi = dilimdeki oran; nokta-cift serili 0.35 ile
    # 20.000 satirda on dilimin orani kararli bicimde siralaniyor.
    MONOTONIC_BINARY_R = 0.35

    @classmethod
    def _with_monotonicity_targets(cls, schema: SchemaContract) -> List[Any]:
        """Korelasyon kurallarına monotonluk kurallarını sıra hedefi olarak ekler.

        Eskiden parametrik motor ``monotonicity_rules``'u hiç okumuyordu; canlı
        koşularda (2026-09-14, qwen2.5-coder:1.5b) konsol ``monotonluk 0/1`` bastı.
        ``X`` arttıkça ``Y`` artıyorsa (azalıyorsa) iki kolon arasında güçlü pozitif
        (negatif) bir Spearman korelasyonu gerekir - kopula bunu marjinalleri
        bozmadan kurabiliyor.

        Aynı çift için korelasyon kuralı zaten varsa ve yönü aynıysa hedefi yalnızca
        yükseltilir; yönler çelişiyorsa korelasyon kuralı kazanır (açıkça ölçülen bir
        hedef, sözleşmedeki bir sıralama beyanından önce gelir) ve log'a yazılır.
        """
        rules: List[Any] = list(schema.correlations)
        by_pair = {frozenset(rule.columns): index for index, rule in enumerate(rules)}
        for mono in schema.monotonicity_rules:
            if mono.column_x == mono.column_y:
                continue
            try:
                binary = any(schema.column(name).type == "bool"
                             for name in (mono.column_x, mono.column_y))
            except KeyError:
                continue
            sign = "positive" if mono.direction == "increasing" else "negative"
            strength = cls.MONOTONIC_BINARY_R if binary else cls.MONOTONIC_RANK_R
            target = _RankTarget([mono.column_x, mono.column_y], sign, strength)
            index = by_pair.get(frozenset(target.columns))
            if index is None:
                by_pair[frozenset(target.columns)] = len(rules)
                rules.append(target)
                continue
            existing = rules[index]
            if getattr(existing, "expected_sign", "positive") != sign:
                log.info("Monotonluk kuralı %s -> %s aynı çiftteki zıt yönlü korelasyonla "
                         "çelişiyor; korelasyon kuralı uygulanıyor",
                         mono.column_x, mono.column_y)
                continue
            if abs(cls._target_corr(existing)) < strength:
                rules[index] = _RankTarget(list(existing.columns), sign, strength)
        return rules

    @staticmethod
    def _target_corr(rule: Any) -> float:
        """Kuraldan hedef korelasyon katsayısını (işaretiyle) çıkarır."""
        target = rule.min_r if getattr(rule, "min_r", None) is not None else 0.7
        if getattr(rule, "expected_sign", "") == "negative":
            return -abs(target)
        return abs(target)

    def _apply_correlations(self, df: pd.DataFrame, correlations: List[Any],
                            rng: np.random.Generator,
                            exclude: Optional[set] = None) -> pd.DataFrame:
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

        Sayısal çiftler tek bir Gauss kopulasıyla birlikte kurulur
        (bkz. :meth:`_apply_numeric_correlations`); ``exclude`` birincil anahtar gibi
        yeniden sıralanmaması gereken kolonlardır.
        """
        exclude = exclude or set()
        bool_rules: Dict[str, List[Any]] = {}
        numeric_rules: List[Tuple[str, str, float, str]] = []

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
            if not (n1 and n2) or c1 in exclude or c2 in exclude or c1 == c2:
                continue
            numeric_rules.append((c1, c2, self._target_corr(rule),
                                  getattr(rule, "method", "pearson") or "pearson"))

        if numeric_rules:
            df = self._apply_numeric_correlations(df, numeric_rules, rng)

        for column, drivers in bool_rules.items():
            df[column] = self._correlated_binary(df, column, drivers, rng)
        return df

    # Temizlik (sinir/Z-score) korelasyonu bir miktar dusuruyor; min_r bir ALT sinir
    # oldugu icin hedefin biraz ustune nisan alinir.
    CORRELATION_MARGIN = 0.05

    def _apply_numeric_correlations(self, df: pd.DataFrame,
                                    rules: List[Tuple[str, str, float, str]],
                                    rng: np.random.Generator) -> pd.DataFrame:
        """Sayısal kolon çiftlerini Gauss kopulasıyla, marjinalleri bozmadan ilişkilendirir.

        Eski yol her kural için hedef kolonu ``r*X + sqrt(1-r^2)*Z`` normal harmanı
        olarak BAŞTAN üretiyordu. Üç sonucu vardı (canlı demo, qwen2.5-coder:14b):
        lognormal ``basket_value`` -271'e kadar negatif değer aldı, int ``item_count``
        ondalıklı/negatif oldu ve ``basket_value`` üç kuralda geçtiği için son kural
        ilkini ezdi (hedef 0.70, ölçülen r=-0.004).

        Burada tüm çiftlerden tek bir latent korelasyon matrisi kurulur, çok değişkenli
        normal örneklenir ve her kolonun ZATEN ÜRETİLMİŞ değerleri latent sıraya göre
        yeniden dizilir. Değerler (dağılım, min/max, dtype) birebir korunur; yalnızca
        satırlar arası eşleşme değişir. Tutarsız hedefler (pozitif tanımlı olmayan
        matris) özdeğer kırpmasıyla en yakın geçerli matrise çekilir.
        """
        columns: List[str] = []
        for c1, c2, _, _ in rules:
            for name in (c1, c2):
                if name not in columns:
                    columns.append(name)
        index = {name: i for i, name in enumerate(columns)}
        n, k = len(df), len(columns)
        if n < 3:
            return df

        desired: Dict[Tuple[int, int], Tuple[float, str]] = {}
        for c1, c2, target, method in rules:
            i, j = sorted((index[c1], index[c2]))
            boosted = float(np.sign(target)) * min(0.95, abs(target) + self.CORRELATION_MARGIN)
            desired[(i, j)] = (boosted, method)

        sorted_values = {name: np.sort(df[name].to_numpy()) for name in columns}
        base = rng.standard_normal((n, k))

        def nearest_correlation(latent: Dict[Tuple[int, int], float]) -> np.ndarray:
            matrix = np.eye(k)
            known = np.eye(k, dtype=bool)
            for (i, j), rho in latent.items():
                matrix[i, j] = matrix[j, i] = rho
                known[i, j] = known[j, i] = True
            # Kural verilmemis ciftler 0 DEGIL, zincirin ima ettigi degerdir: a~b ve b~c
            # guclu iken a~c=0 tutarsiz bir matris verir ve ozdeger kirpmasi butun zinciri
            # zayiflatiyordu (olcum: yas->kidem->gelir->kredi zincirinde hedef 0.88,
            # gerceklesen 0.61-0.73). En guclu yolun carpimi - Gauss agacinin yapisi -
            # agac bicimli kural kumelerinde matrisi kendiliginden pozitif tanimli yapar.
            implied = known.copy()
            for m in range(k):
                for i in range(k):
                    for j in range(i + 1, k):
                        if known[i, j] or m in (i, j) or not (implied[i, m] and implied[m, j]):
                            continue
                        candidate = matrix[i, m] * matrix[m, j]
                        if not implied[i, j] or abs(candidate) > abs(matrix[i, j]):
                            matrix[i, j] = matrix[j, i] = candidate
                            implied[i, j] = implied[j, i] = True
            eigval, eigvec = np.linalg.eigh(matrix)
            matrix = eigvec @ np.diag(np.clip(eigval, 1e-4, None)) @ eigvec.T
            scale = np.sqrt(np.diag(matrix))
            return matrix / np.outer(scale, scale)

        def build(latent: Dict[Tuple[int, int], float]) -> Dict[str, np.ndarray]:
            latent_z = base @ np.linalg.cholesky(nearest_correlation(latent)).T
            return {name: sorted_values[name][np.argsort(np.argsort(latent_z[:, index[name]],
                                                                   kind="stable"),
                                                         kind="stable")]
                    for name in columns}

        def measure(values: Dict[str, np.ndarray]) -> Dict[Tuple[int, int], float]:
            out = {}
            for (i, j), (_, method) in desired.items():
                # Doğrulayıcıyla aynı ölçü (bkz. core/correlation.py).
                r = pair_correlation(values[columns[i]], values[columns[j]], method)
                out[(i, j)] = 0.0 if np.isnan(r) else r
            return out

        def error(observed: Dict[Tuple[int, int], float]) -> float:
            return sum(abs(observed[key] - target) for key, (target, _) in desired.items())

        # Normal latent -> sira korelasyonu: rho_s = (6/pi) asin(rho/2), Kendall icin
        # tau = (2/pi) asin(rho). Hedefi sira olcegine gore cevirerek baslanir, sonra
        # olculen sapmayla kalibre edilir (lognormal kuyruk / Poisson basamaklari
        # Pearson'u latentin altina ceker).
        latent = {key: latent_from_target(target, method)
                  for key, (target, method) in desired.items()}
        best = build(latent)
        best_obs = measure(best)
        for _ in range(2):
            corrected = {}
            for key, rho in latent.items():
                target, observed = desired[key][0], best_obs[key]
                if abs(observed) < 1e-3 or np.sign(observed) != np.sign(target):
                    corrected[key] = rho
                else:
                    corrected[key] = float(np.clip(rho * target / observed, -0.99, 0.99))
            candidate = build(corrected)
            candidate_obs = measure(candidate)
            if error(candidate_obs) >= error(best_obs):
                break
            latent, best, best_obs = corrected, candidate, candidate_obs

        for name in columns:
            df[name] = best[name]
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
        # min_r bir alt sinir: temizlik sonrasi da tutmasi icin biraz ustune nisan al.
        targets = np.array([np.sign(target) * min(0.95, abs(target) + self.CORRELATION_MARGIN)
                            for _, target in drivers], dtype=float)
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

        def measure(candidate: np.ndarray) -> np.ndarray:
            return np.array([self._point_biserial(df[driver], candidate)
                             for driver, _ in drivers])

        flags = build(weights)
        observed = measure(flags)

        # Kalibrasyon: formul normallik varsayiyor, gercek surucular (lognormal kuyruk,
        # Poisson basamaklari) hedefin altinda kaliyor. Olculen sapma agirliklara geri
        # beslenir. Tek tur yetmiyordu: kopula artik suruculerin gercek (egik)
        # dagilimini korudugu icin lognormal surucude r 0.40 hedefinde 0.32'de kaldi.
        for _ in range(4):
            safe = np.where(np.abs(observed) < 1e-3, np.sign(targets) * 1e-3, observed)
            corrected = np.clip(weights * (targets / safe), -0.95, 0.95)
            if not np.all(np.isfinite(corrected)):
                break
            retry = build(corrected)
            retry_obs = measure(retry)
            # Yalnizca gercekten yaklastiysa kabul et - kalibrasyon geri tepmesin.
            if np.sum(np.abs(retry_obs - targets)) >= np.sum(np.abs(observed - targets)):
                break
            weights, flags, observed = corrected, retry, retry_obs

        if pd.api.types.is_bool_dtype(original):
            return flags
        return flags.astype(original.dtype if original.dtype != object else int)

    @staticmethod
    def _point_biserial(driver: pd.Series, flags: np.ndarray) -> float:
        values = pd.to_numeric(driver, errors="coerce").astype(float)
        r = values.corr(pd.Series(flags.astype(float), index=values.index))
        return 0.0 if pd.isna(r) else float(r)

    # Bir kuralin onarimi baska bir kuralin kolonunu degistirebilir (a <= b, b <= c);
    # ikinci tur zinciri oturtur.
    RULE_REPAIR_PASSES = 2

    def _enforce_business_rules(self, df: pd.DataFrame, schema: SchemaContract,
                                rng: np.random.Generator,
                                protected: Optional[set] = None) -> pd.DataFrame:
        """İş kurallarını üretim sırasında sağlar; validator'a yalnızca kenar vakalar kalır.

        Eskiden yalnızca iki çıplak kolonlu ``a <= b`` / ``a >= b`` biçimi onarılıyordu.
        Canlı şemalardaki kuralların çoğu başka biçimdeydi ve validator bunlarda
        satırların büyük kısmını sildi: kolon sınırından sıkı bir sabit
        (``sessions_per_week <= 7`` iken max 200), ölçekli ya da toplamlı taraf
        (``loan_amount <= annual_income * 0.5``, ``total >= basket + shipping``),
        ``and`` ile birleşik sınırlar ve türetilmiş kolon eşitlikleri
        (``ratio == loan / income``). Burada kural AST'ye çevrilir, üst düzey ``and``
        parçalanır ve her karşılaştırmada bir tarafı çıplak kolon olan parça onarılır
        (:meth:`_repair_comparison`). ``or``/``not`` gibi seçenekli biçimlere dokunulmaz;
        onları validator eler.
        """
        from .schema_contract import conjuncts, normalize_rule

        protected = protected or set()
        comparisons = []
        for rule in schema.business_rules:
            try:
                tree = ast.parse(normalize_rule(rule).strip(), mode="eval").body
            except SyntaxError:
                continue
            for clause in conjuncts(tree):
                comparisons.extend(_comparisons(clause))

        for _ in range(self.RULE_REPAIR_PASSES):
            for column, op, other in comparisons:
                if column in protected or column not in df.columns:
                    continue
                try:
                    self._repair_comparison(df, schema, column, op, other, rng)
                except Exception as exc:  # onarim hicbir zaman uretimi dusurmemeli
                    log.debug("Kural onarımı atlandı: %s %s %s (%s)", column, op, other, exc)
        return df

    @staticmethod
    def _repair_comparison(df: pd.DataFrame, schema: SchemaContract, column: str,
                           op: str, other: ast.expr, rng: np.random.Generator) -> None:
        """``column <op> other`` karşılaştırmasını ihlal eden satırlarda ``column``'u düzeltir.

        * ``==``: diğer taraf başka kolonlara dayanıyorsa kolon ondan türetilir.
        * ``<``, ``<=``, ``>``, ``>=``: ihlal eden değer sınırın öbür yanına aynalanır
          (ihlalin büyüklüğü korunur, sınırda yığılma olmaz); aynalanan değer kolonun
          kendi alt/üst sınırını aşarsa sınırla o uç arasında düzgün çekilir.

        Kolonun min/max'ı kuralla çelişiyorsa (``x <= 5`` iken ``min=10``) onarım
        değeri sınıra kırpılır ve satır ihlalde kalır - ikisini birden sağlamak
        mümkün değildir, karar validator'ındır.
        """
        try:
            spec = schema.column(column)
        except KeyError:
            return
        # Tarih kolonlari nanosaniye cinsinden sayi olarak onarilir. Canli kosu (13.09,
        # deepseek-r1:8b): `last_session_date >= signup_date` iki bagimsiz tarih kolonunda
        # satirlarin yarisini sildirdi.
        is_datetime = (spec.type == "datetime"
                       and pd.api.types.is_datetime64_any_dtype(df[column]))
        if not is_datetime and (spec.type not in ("int", "float")
                                or not pd.api.types.is_numeric_dtype(df[column])):
            return
        references = {node.id for node in ast.walk(other) if isinstance(node, ast.Name)}
        if not references <= set(df.columns):
            return
        bound = df.eval(ast.unparse(other))
        if is_datetime:
            if op == "==":
                return
            # Birim acikca ns: pandas metinden cevirdigi tarihi saniye cozunurlugunde
            # (datetime64[s]) tutabiliyor; ham int64'ler karistirilinca tarihler 1970'e dustu.
            stamps = pd.to_datetime(pd.Series(bound, index=df.index) if np.ndim(bound) == 0
                                    else bound, errors="coerce").astype("datetime64[ns]")
            bound = stamps.astype("int64").astype(float).where(stamps.notna())
            current = df[column].astype("datetime64[ns]").astype("int64").astype(float)
        else:
            if np.ndim(bound) == 0:
                bound = pd.Series(float(bound), index=df.index)
            bound = pd.to_numeric(bound, errors="coerce").astype(float)
            current = df[column].astype(float)
        # Nanosaniye degerleri (~1.7e18) float64'te zaten tamsayidir; `ceil(x) - 1` bu
        # buyuklukte kaybolur, o yuzden tarihler tamsayi yuvarlamasina sokulmaz.
        is_int = spec.type == "int"

        if op == "==":
            if not references:
                return          # sabit esitlik tum kolonu tek degere cevirirdi
            values = bound.round() if is_int else bound
            usable = np.isfinite(values)
            if spec.min is not None:
                usable &= values >= spec.min
            if spec.max is not None:
                usable &= values <= spec.max
            if usable.any():
                target_dtype = df[column].dtype if is_int else float
                df.loc[usable, column] = values[usable].astype(target_dtype)
            return

        checks = {"<": np.less, "<=": np.less_equal, ">": np.greater, ">=": np.greater_equal}
        violating = np.isfinite(bound) & ~checks[op](current, bound)
        if not violating.any():
            return
        b = bound[violating].to_numpy()
        v = current[violating].to_numpy()
        holding = current[~violating]
        mirrored = 2.0 * b - v

        if op in ("<", "<="):
            if spec.min is not None:
                far = float(spec.min)
            elif len(holding):
                far = float(holding.min())
            else:
                far = float(np.min(b)) - abs(float(np.min(b))) - 1.0
            far = np.minimum(far, b)
            new = np.where(mirrored < far, rng.uniform(far, b), mirrored)
            if op == "<":
                new = np.minimum(new, np.nextafter(b, -np.inf))
            if is_int:
                new = np.floor(new) if op == "<=" else np.ceil(new) - 1.0
        else:
            if spec.max is not None:
                far = float(spec.max)
            elif len(holding):
                far = float(holding.max())
            else:
                far = float(np.max(b)) + abs(float(np.max(b))) + 1.0
            far = np.maximum(far, b)
            new = np.where(mirrored > far, rng.uniform(b, far), mirrored)
            if op == ">":
                new = np.maximum(new, np.nextafter(b, np.inf))
            if is_int:
                new = np.ceil(new) if op == ">=" else np.floor(new) + 1.0

        if spec.min is not None or spec.max is not None:
            new = np.clip(new, spec.min if spec.min is not None else -np.inf,
                          spec.max if spec.max is not None else np.inf)
        # Kolon araligi kuralla celisiyorsa kirpilan deger kurali yine saglamaz; o satira
        # dokunulmaz. Canli kosu (14.09, 1.5b): `loan_amount <= credit_score` iken
        # loan_amount min=2000, credit_score max=850 - onarim her satiri 2000'e kirpip
        # kolonu sabite ceviriyordu ve korelasyon olculemez oldu.
        fixed = checks[op](new, b)
        if not fixed.any():
            return
        rows = violating[violating].index[fixed]
        if is_datetime:
            repaired = pd.to_datetime(new[fixed].astype("int64"), unit="ns")
            df.loc[rows, column] = repaired.astype(df[column].dtype)
        elif is_int:
            df.loc[rows, column] = new[fixed].astype(df[column].dtype)
        else:
            if not pd.api.types.is_float_dtype(df[column]):
                df[column] = df[column].astype(float)
            df.loc[rows, column] = new[fixed]


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

