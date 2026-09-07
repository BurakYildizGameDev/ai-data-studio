"""Discriminator - İş kuralları, istatistiksel ayıklama ve dağılım testleri.

Ham sentetik veri bu pipeline'dan geçirilerek gürültü, aykırı değerler ve
iş kuralı ihlalleri ayıklanır; geriye yüksek kaliteli, arıtılmış bir veri seti kalır.

Aşamalar:
  1. Duplicate temizleme          -> df.drop_duplicates()
  2. Şema sınırları               -> min/max ihlalleri ve not-null kontrolleri
  3. İş kuralları                 -> Güvenli df.eval() boolean filtreleri
  4. Z-Score aykırı değer         -> Tek değişkenli aşırı uç temizliği (|Z| > threshold),
                                     yalnızca yaklaşık simetrik kolonlarda
  5. IsolationForest              -> Çok değişkenli anomali tespiti (opt-in, varsayılan kapalı)
  5b. Korelasyon koruma           -> Temizlik hedef korelasyonu bozduysa geri alma
  6. Raporlama                    -> Korelasyon doğrulaması ve KS dağılım testleri

Kuyruk koruma ilkesi: 4. ve 5. aşama, dağılımın kuyruğunu kesip semanın
hedeflediği korelasyonu taşıyan satırları silebiliyordu. Artık Z-Score ağır
kuyruklu/sıfır-şişirilmiş kolonlarda hiç çalışmıyor, IsolationForest açıkça
istenmedikçe devrede değil ve 5b aşaması ikisinin de zararını geri alabiliyor.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .. import config
from ..i18n import t
from .schema_contract import SchemaContract

log = logging.getLogger(__name__)

__all__ = [
    "ValidationCancelled",
    "apply_business_rules",
    "remove_z_score_outliers",
    "remove_isolation_forest_outliers",
    "zscore_eligible_columns",
    "validate_correlations",
    "validate_distributions",
    "run_validation",
]

DEFAULT_Z_THRESHOLD = 3.0
# IsolationForest varsayilan olarak KAPALI (0.0). Sabit bir contamination orani
# "verimin %x'i bozuk" varsayimi demektir; saglam veride bile o orani korfezden
# atar ve agir kuyruklu kolonlarda hep en uc - yani bilgi tasiyan - satirlari
# secer. Acmak icin --contamination 0.05 gibi acik bir deger verin.
DEFAULT_CONTAMINATION = 0.0
MAX_ISOLATION_FOREST_SAMPLE = 50_000   # fit icin alt orneklem - 100k+ satirda hiz icin

# Z-Score yalnizca yaklasik simetrik dagilimlar icin anlamlidir. Agir kuyruklu
# ve sifir-sisirilmis sayim dagilimlarinda ortalama+std tahmini kuyruk tarafindan
# yanli hale gelir; |Z|>3 esigi kuyrugu tamamen kesip korelasyonu tasiyan
# satirlari siler (bkz. HEAVY_TAIL_DISTRIBUTIONS testleri).
HEAVY_TAIL_DISTRIBUTIONS = {
    "lognormal", "exponential", "poisson", "gamma", "tweedie",
    "zip", "zero_inflated_poisson", "gpd", "pareto",
}
# Sema dagilim bilgisi vermediginde ampirik olarak karar veririz. Moment
# carpikligi burada kullanilamaz: birkac uc deger carpikligi sisirir ve tam da
# onlari temizleyecek filtreyi kapatir (maskeleme). Bunun yerine ceyreklere
# dayali, uc degerlere duyarsiz Bowley carpikligini kullaniyoruz.
SKEW_SKIP_THRESHOLD = 0.30           # |Bowley carpikligi| bu esigin ustundeyse Z-Score atlanir
ZERO_FRACTION_SKIP_THRESHOLD = 0.30  # sifir orani bu esigin ustundeyse Z-Score atlanir


class ValidationCancelled(RuntimeError):
    """Kullanıcı validasyonu iptal etti."""


def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ValidationCancelled(t("validation.cancelled"))


# --------------------------------------------------------------------------- #
# 1. Sema sinirlari
# --------------------------------------------------------------------------- #
def apply_schema_bounds(df: pd.DataFrame, schema: SchemaContract) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """min/max disindaki ve nullable olmayan kolonlarda boş olan satirlari eler."""
    mask = pd.Series(True, index=df.index)
    removed: Dict[str, int] = {}

    for col in schema.columns:
        if col.name not in df.columns:
            continue
        series = df[col.name]
        col_mask = pd.Series(True, index=df.index)

        if not col.nullable:
            col_mask &= series.notna()

        if col.is_numeric and pd.api.types.is_numeric_dtype(series):
            if col.min is not None:
                col_mask &= (series >= col.min) | series.isna()
            if col.max is not None:
                col_mask &= (series <= col.max) | series.isna()

        if col.type == "category" and col.categories:
            col_mask &= series.isin(col.categories) | (series.isna() & col.nullable)

        dropped = int((~col_mask).sum())
        if dropped:
            removed[col.name] = dropped
        mask &= col_mask

    return df[mask], removed


# --------------------------------------------------------------------------- #
# 2. Is kurallari - guvenli degerlendirme (eval() degil, df.eval())
# --------------------------------------------------------------------------- #
def apply_business_rules(df: pd.DataFrame, rules: List[str]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Her kuralın TRUE olması gereken satırları tutar.

    Parse edilemeyen veya geçersiz kurallar güvenle atlanır ve raporlanır;
    hatalı tek bir kural tüm pipeline'ı durdurmaz.
    """
    mask = pd.Series(True, index=df.index)
    details: List[Dict[str, Any]] = []

    for rule in rules:
        try:
            result = df.eval(rule)
        except Exception as exc:
            log.warning("Kural parse edilemedi, atlaniyor: '%s' -> %s", rule, exc)
            details.append({"rule": rule, "status": "skipped", "reason": str(exc), "violations": 0})
            continue

        if not isinstance(result, pd.Series):
            details.append({
                "rule": rule, "status": "skipped",
                "reason": "İfade satır bazli bir boolean seri döndürmedi",
                "violations": 0,
            })
            continue

        rule_mask = result.fillna(False).astype(bool)
        violations = int((~rule_mask).sum())
        details.append({
            "rule": rule,
            "status": "applied",
            "violations": violations,
            "violation_pct": round(violations / len(df) * 100, 2) if len(df) else 0.0,
        })
        mask &= rule_mask

    return df[mask], {"rules": details, "removed": int((~mask).sum())}


# --------------------------------------------------------------------------- #
# 3. Istatistiksel aykiri deger ayiklama
# --------------------------------------------------------------------------- #
def zscore_eligible_columns(
    df: pd.DataFrame,
    columns: List[str],
    schema: Optional[SchemaContract] = None,
) -> Tuple[List[str], Dict[str, str]]:
    """Z-Score uygulanabilir kolonlari secer.

    Once semadaki ``distribution`` bilgisine bakar; sema yoksa veya dagilim
    belirtilmemisse veriden ampirik karar verir (sifir orani / carpiklik).

    Returns:
        (uygun_kolonlar, {atlanan_kolon: sebep})
    """
    eligible: List[str] = []
    skipped: Dict[str, str] = {}

    for col in columns:
        if col not in df.columns or not pd.api.types.is_numeric_dtype(df[col]):
            continue

        dist = None
        if schema is not None:
            try:
                dist = (schema.column(col).distribution or "").lower() or None
            except KeyError:
                dist = None

        if dist in HEAVY_TAIL_DISTRIBUTIONS:
            skipped[col] = "dağılım '%s' ağır kuyruklu/sayım tipi" % dist
            continue

        series = df[col].astype("float64")
        finite = series[np.isfinite(series)]
        if finite.empty:
            continue

        # Sema "normal"/"uniform" dediyse ampirik kontrole gerek yok.
        if dist in ("normal", "uniform"):
            eligible.append(col)
            continue

        zero_fraction = float((finite == 0).mean())
        if zero_fraction > ZERO_FRACTION_SKIP_THRESHOLD:
            skipped[col] = "sıfır oranı %%%.0f (sıfır-şişirilmiş)" % (zero_fraction * 100)
            continue

        q1, q2, q3 = (float(finite.quantile(q)) for q in (0.25, 0.5, 0.75))
        spread = q3 - q1
        if spread <= 0:
            # Orta %50 tek bir degere yigilmis: ortalama/std tabanli Z-Score
            # bu kolonda anlamsiz, her farkli deger "aykiri" cikar.
            skipped[col] = "değerlerin yarısı tek noktada yığılı (IQR=0)"
            continue

        bowley = ((q3 - q2) - (q2 - q1)) / spread
        if abs(bowley) > SKEW_SKIP_THRESHOLD:
            skipped[col] = "Bowley çarpıklığı %.2f (simetrik değil)" % bowley
            continue

        eligible.append(col)

    return eligible, skipped


def remove_z_score_outliers(df: pd.DataFrame, columns: List[str],
                            threshold: float = DEFAULT_Z_THRESHOLD,
                            preserve_anomaly_column: Optional[str] = None,
                            preserve_anomaly_value: Any = None,
                            schema: Optional[SchemaContract] = None
                            ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """|Z| > threshold olan satirlari eler.

    Yalnizca yaklasik simetrik dagilimli kolonlara uygulanir: agir kuyruklu
    (gamma, lognormal, pareto...) ve sifir-sisirilmis sayim (zip, poisson)
    kolonlarinda Z-Score kuyrugu kesip korelasyonu tasiyan satirlari sildigi
    icin atlanir. Hangi kolonun neden atlandigi ``skipped_columns`` icinde
    dondurulur. Kolon secimi icin bkz. :func:`zscore_eligible_columns`.

    Eğer preserve_anomaly_column verilmişse, o kolonda anomali değeri (örn. is_fraud=1)
    taşıyan satırlar Z-score eşiğini aşsa dahi silinmez, korunur.
    """
    if df.empty:
        return df, {"columns": [], "removed": 0, "per_column": {},
                    "skipped_columns": {}, "preserved_anomalies": 0}

    usable, skipped_columns = zscore_eligible_columns(df, columns, schema)
    if not usable:
        return df, {"columns": [], "removed": 0, "per_column": {},
                    "skipped_columns": skipped_columns, "preserved_anomalies": 0}

    mask = pd.Series(True, index=df.index)
    per_column: Dict[str, int] = {}
    for col in usable:
        series = df[col].astype("float64")
        std = series.std(ddof=0)
        if not np.isfinite(std) or std == 0:
            continue
        z = (series - series.mean()).abs() / std
        col_mask = (z <= threshold) | z.isna()
        flagged = int((~col_mask).sum())
        if flagged:
            per_column[col] = flagged
        mask &= col_mask

    preserved_count = 0
    if preserve_anomaly_column and preserve_anomaly_column in df.columns:
        p_col = df[preserve_anomaly_column]
        if preserve_anomaly_value is not None:
            protect_mask = p_col == preserve_anomaly_value
        else:
            protect_mask = (p_col == 1) | (p_col == True) | (p_col.astype(str).str.lower().isin(["1", "true", "fraud", "anomaly"]))
        preserved_count = int((~mask & protect_mask).sum())
        mask = mask | protect_mask

    return df[mask], {
        "columns": usable,
        "threshold": threshold,
        "removed": int((~mask).sum()),
        "per_column": per_column,
        "skipped_columns": skipped_columns,
        "preserved_anomalies": preserved_count,
    }


def remove_isolation_forest_outliers(df: pd.DataFrame, columns: List[str],
                                     contamination: float = DEFAULT_CONTAMINATION,
                                     random_state: int = 42,
                                     preserve_anomaly_column: Optional[str] = None,
                                     preserve_anomaly_value: Any = None
                                     ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Çok degiskenli anomali ayıklama (sklearn IsolationForest).

    ``contamination`` 0 veya daha kucukse asama tamamen atlanir (varsayilan).
    Sabit bir oran vermek "verinin su kadari bozuk" demektir; saglam veride bile
    o orani siler ve agir kuyruklu kolonlarda en uc satirlari secer.

    Eğer preserve_anomaly_column verilmişse, o kolonda anomali değeri taşıyan satırlar
    Isolation Forest tarafından outlier (-1) olarak tespit edilse bile silinmez.
    """
    if not isinstance(contamination, str) and contamination <= 0:
        return df, {"skipped": True, "reason": "devre disi (contamination=0)",
                    "removed": 0, "preserved_anomalies": 0}

    usable = [c for c in columns if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]
    if len(usable) < 2 or len(df) < 50:
        return df, {"skipped": True, "reason": "yetersiz sayısal kolon veya satır", "removed": 0, "preserved_anomalies": 0}

    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:  # pragma: no cover
        return df, {"skipped": True, "reason": "scikit-learn kurulu değil", "removed": 0, "preserved_anomalies": 0}

    features = df[usable].astype("float64")
    finite = features.replace([np.inf, -np.inf], np.nan).dropna()
    if len(finite) < 50:
        return df, {"skipped": True, "reason": "yetersiz tam satır", "removed": 0, "preserved_anomalies": 0}

    model = IsolationForest(
        contamination=contamination,
        random_state=random_state,
        n_estimators=100,
        max_samples=min(MAX_ISOLATION_FOREST_SAMPLE, len(finite)),
        n_jobs=-1,
    )
    fit_sample = (finite.sample(MAX_ISOLATION_FOREST_SAMPLE, random_state=random_state)
                  if len(finite) > MAX_ISOLATION_FOREST_SAMPLE else finite)
    model.fit(fit_sample)
    predictions = model.predict(finite)

    keep_mask = pd.Series(predictions == 1, index=finite.index)

    preserved_count = 0
    if preserve_anomaly_column and preserve_anomaly_column in df.columns:
        p_col = df.loc[finite.index, preserve_anomaly_column]
        if preserve_anomaly_value is not None:
            protect_mask = p_col == preserve_anomaly_value
        else:
            protect_mask = (p_col == 1) | (p_col == True) | (p_col.astype(str).str.lower().isin(["1", "true", "fraud", "anomaly"]))
        preserved_count = int((~keep_mask & protect_mask).sum())
        keep_mask = keep_mask | protect_mask

    keep_index = finite.index[keep_mask]
    # Sayisal kolonlarinda NaN/inf olan satirlar model tarafindan puanlanamaz;
    # onlari sema sinirlari asamasi zaten elemis olmali, kalanlari tutuyoruz.
    unscored = df.index.difference(finite.index)
    result = df.loc[df.index.isin(keep_index) | df.index.isin(unscored)]

    return result, {
        "skipped": False,
        "columns": usable,
        "contamination": contamination,
        "removed": int(len(df) - len(result)),
        "unscored_rows": int(len(unscored)),
        "preserved_anomalies": preserved_count,
    }


# --------------------------------------------------------------------------- #
# 4. Korelasyon & dagilim dogrulamasi (Bolum 6.4)
# --------------------------------------------------------------------------- #
def validate_correlations(df: pd.DataFrame, schema: SchemaContract) -> List[Dict[str, Any]]:
    """Semada beklenen korelasyonlarin (Pearson veya Spearman rank) veride gercekten olusup olusmadigini olcer."""
    rules = schema.correlations
    if not rules or df.empty:
        return []

    corr_pearson = df.corr(method="pearson", numeric_only=True)
    corr_spearman = df.corr(method="spearman", numeric_only=True)
    results: List[Dict[str, Any]] = []
    for rule in rules:
        c1, c2 = rule.columns
        method = getattr(rule, "method", "pearson") or "pearson"
        corr_matrix = corr_spearman if method == "spearman" else corr_pearson

        if c1 not in corr_matrix.columns or c2 not in corr_matrix.columns:
            results.append({
                "pair": [c1, c2], "expected_sign": rule.expected_sign, "min_r": rule.min_r,
                "method": method, "actual_r": None, "pass": False, "reason": "kolon sayısal değil veya yok",
            })
            continue
        r = corr_matrix.loc[c1, c2]
        if pd.isna(r):
            results.append({
                "pair": [c1, c2], "expected_sign": rule.expected_sign, "min_r": rule.min_r,
                "method": method, "actual_r": None, "pass": False, "reason": "korelasyon hesaplanamadi (sabit kolon?)",
            })
            continue
        r = float(r)
        ok = r >= rule.min_r if rule.expected_sign == "positive" else r <= -rule.min_r
        results.append({
            "pair": [c1, c2],
            "expected_sign": rule.expected_sign,
            "min_r": rule.min_r,
            "method": method,
            "actual_r": round(r, 3),
            "pass": bool(ok),
        })
    return results


def validate_distributions(synth_df: pd.DataFrame, seed_df: Optional[pd.DataFrame],
                           schema: SchemaContract) -> Dict[str, Any]:
    """Seed data varsa KS testiyle dağılım kiyasi; yoksa atlanir."""
    if seed_df is None or len(seed_df) == 0:
        return {"skipped": True, "reason": "seed_data_yok"}

    try:
        from scipy.stats import ks_2samp
    except ImportError:  # pragma: no cover
        return {"skipped": True, "reason": "scipy kurulu değil"}

    report: Dict[str, Any] = {"skipped": False, "columns": {}}
    for col in schema.columns:
        name = col.name
        if name not in synth_df.columns or name not in seed_df.columns:
            continue
        a = pd.to_numeric(synth_df[name], errors="coerce").dropna()
        b = pd.to_numeric(seed_df[name], errors="coerce").dropna()
        if len(a) < 20 or len(b) < 20:
            continue
        stat, p_value = ks_2samp(a, b)
        report["columns"][name] = {
            "ks_stat": round(float(stat), 3),
            "p_value": round(float(p_value), 4),
            "pass": bool(p_value > 0.05),
        }
    if not report["columns"]:
        return {"skipped": True, "reason": "ortak sayısal kolon bulunamadı"}
    passed = sum(1 for v in report["columns"].values() if v["pass"])
    report["passed"] = passed
    report["total"] = len(report["columns"])
    return report


# --------------------------------------------------------------------------- #
# 5. Tam validasyon pipeline'i
# --------------------------------------------------------------------------- #
def run_validation(
    df: pd.DataFrame,
    schema: SchemaContract,
    seed_df: Optional[pd.DataFrame] = None,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
    contamination: float = DEFAULT_CONTAMINATION,
    preserve_anomaly_column: Optional[str] = None,
    preserve_anomaly_value: Any = None,
    audit_privacy: bool = False,
    # Cok tablolu kosuda denetlenen tablonun adi; gizlilik raporunun basligina
    # girer. Tek tabloda bos kalir ve rapor metni birebir eskisi gibi uretilir.
    audit_table_name: str = "",
    cancel_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    reference_df: Optional[pd.DataFrame] = None,
    correlation_guard: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Ham veriyi tam Discriminator pipeline'indan gecirir.

    Returns:
        (temiz_dataframe, rapor)
    """
    if seed_df is None and reference_df is not None:
        seed_df = reference_df

    def emit(message: str, level: str = config.PROGRESS_INFO) -> None:
        """Alt adım mesajını dışarı verir.

        ``level`` konsol rengini belirler; çağıran taraf uyarıyı METİNDEN değil
        buradan bildirir, aksi hâlde çeviri yapıldığında renklendirme bozulur.
        """
        log.info(message)
        if on_progress is not None:
            on_progress(message, level)

    rows_in = len(df)
    report: Dict[str, Any] = {
        "rows_in": rows_in,
        "stages": [],
        "warnings": list(schema.warnings),
    }

    target_preserve_col = preserve_anomaly_column or getattr(schema, "preserve_anomaly_column", None)
    target_preserve_val = preserve_anomaly_value if preserve_anomaly_value is not None else getattr(schema, "preserve_anomaly_value", None)

    # Otomatik anomali kolonu algılama (eğer açıkça belirtilmemişse):
    if not target_preserve_col:
        for candidate in ("is_fraud", "is_anomaly", "fraud_label", "is_attack", "fraud"):
            if candidate in df.columns:
                target_preserve_col = candidate
                break

    def record(stage: str, before: int, after: int, extra: Optional[Dict[str, Any]] = None) -> None:
        entry = {
            "stage": stage,
            "rows_before": before,
            "rows_after": after,
            "removed": before - after,
            "removed_pct": round((before - after) / before * 100, 2) if before else 0.0,
        }
        if extra:
            entry.update(extra)
        report["stages"].append(entry)
        pct_str = " (%%%.1f)" % entry["removed_pct"] if before else ""
        emit("  %-24s %s -> %s (-%s%s)" % (stage, format(before, ","), format(after, ","),
                                           format(before - after, ","), pct_str))

    # -- kolon sirasini semaya gore normalize et -------------------------- #
    ordered = [c.name for c in schema.columns if c.name in df.columns]
    extras = [c for c in df.columns if c not in set(ordered)]
    df = df[ordered + extras]

    # -- 1. Duplicate temizleme ------------------------------------------ #
    _check_cancel(cancel_event)
    emit(t("validation.started", rows=format(rows_in, ",")))
    before = len(df)
    df = df.drop_duplicates()
    record(t("validation.stage.duplicates"), before, len(df))

    # -- 2. Sema sinirlari ------------------------------------------------ #
    _check_cancel(cancel_event)
    before = len(df)
    df, bounds_detail = apply_schema_bounds(df, schema)
    record(t("validation.stage.bounds"), before, len(df), {"per_column": bounds_detail})
    if bounds_detail:
        top_bounds = sorted(bounds_detail.items(), key=lambda x: x[1], reverse=True)[:3]
        emit("    -> " + t("validation.top_dropped_columns",
                            columns=", ".join("%s: -%s" % (c, format(n, ","))
                                              for c, n in top_bounds)))

    # -- 3. Is kurallari -------------------------------------------------- #
    _check_cancel(cancel_event)
    before = len(df)
    df, rules_detail = apply_business_rules(df, schema.business_rules)
    record(t("validation.stage.rules"), before, len(df), {"detail": rules_detail["rules"]})
    report["business_rules"] = rules_detail["rules"]
    for r_info in rules_detail.get("rules", []):
        if r_info.get("violations", 0) > 0:
            emit("    -> " + t("validation.rule_violation",
                                rule=r_info["rule"],
                                rows=format(r_info["violations"], ","),
                                pct="%.1f" % r_info.get("violation_pct", 0.0)))

    # -- 4. Z-Score ------------------------------------------------------- #
    _check_cancel(cancel_event)
    before = len(df)
    # Kuyruk koruma: outlier asamalari korelasyonu bozarsa geri donebilmek icin
    # filtrelenmemis kareyi ve o andaki korelasyon durumunu sakla.
    df_before_outliers = df
    corr_before_outliers = validate_correlations(df, schema) if correlation_guard else []

    df, z_detail = remove_z_score_outliers(
        df, schema.numeric_columns, z_threshold,
        preserve_anomaly_column=target_preserve_col,
        preserve_anomaly_value=target_preserve_val,
        schema=schema,
    )
    record(t("validation.stage.z_score"), before, len(df), {"detail": z_detail})
    z_skipped = z_detail.get("skipped_columns", {})
    if z_skipped:
        emit("    -> " + t("validation.z_skipped",
                            columns=", ".join("%s (%s)" % (c, why)
                                              for c, why in list(z_skipped.items())[:4])))
    z_per_col = z_detail.get("per_column", {})
    if z_per_col:
        top_z = sorted(z_per_col.items(), key=lambda x: x[1], reverse=True)[:3]
        emit("    -> " + t("validation.z_outliers",
                            columns=", ".join("%s: -%s" % (c, format(n, ","))
                                              for c, n in top_z)))
    z_preserved = z_detail.get("preserved_anomalies", 0)
    if z_preserved > 0:
        emit("    -> " + t("validation.z_preserved",
                            column=target_preserve_col, rows=z_preserved))

    # -- 5. IsolationForest ----------------------------------------------- #
    _check_cancel(cancel_event)
    before = len(df)
    df, iso_detail = remove_isolation_forest_outliers(
        df, schema.numeric_columns, contamination, random_state=schema.random_seed,
        preserve_anomaly_column=target_preserve_col,
        preserve_anomaly_value=target_preserve_val
    )
    record("IsolationForest", before, len(df), {"detail": iso_detail})
    iso_preserved = iso_detail.get("preserved_anomalies", 0)
    if iso_preserved > 0:
        emit("    -> " + t("validation.iso_preserved",
                            column=target_preserve_col, rows=iso_preserved))

    # -- 5b. Korelasyon koruma (kuyruk kesme emniyeti) --------------------- #
    # Outlier asamalari, semanin hedefledigi korelasyonu tasiyan uc satirlari
    # silebiliyor. Filtreleme oncesi saglanan bir hedef sonrasinda bozulduysa
    # temizligi geri alip filtrelenmemis kareye donuyoruz.
    _check_cancel(cancel_event)
    guard_info: Dict[str, Any] = {"enabled": bool(correlation_guard), "reverted": False, "regressions": []}
    if correlation_guard and len(df) != len(df_before_outliers):
        corr_after = validate_correlations(df, schema)
        before_map = {tuple(c["pair"]): c for c in corr_before_outliers}
        regressions = []
        for entry in corr_after:
            prev = before_map.get(tuple(entry["pair"]))
            if prev is not None and prev.get("pass") and not entry.get("pass"):
                regressions.append({
                    "pair": entry["pair"],
                    "r_before": prev.get("actual_r"),
                    "r_after": entry.get("actual_r"),
                    "min_r": entry.get("min_r"),
                })
        guard_info["regressions"] = regressions
        if regressions:
            restored = int(len(df_before_outliers) - len(df))
            for reg in regressions:
                emit("    -> " + t("validation.correlation_regressed",
                                    left=reg["pair"][0], right=reg["pair"][1],
                                    before=reg["r_before"], after=reg["r_after"],
                                    threshold=reg["min_r"]),
                     level=config.PROGRESS_WARNING)
            emit("    -> " + t("validation.correlation_guard_reverted",
                                rows=format(restored, ",")))
            before_revert = len(df)
            df = df_before_outliers
            guard_info["reverted"] = True
            guard_info["rows_restored"] = restored
            # Asama tablosu toplamda tutarli kalsin. record() silinen satir
            # sayisini yazdirdigi icin burada dogrudan ekliyoruz: bu asama
            # satir silmiyor, geri getiriyor.
            report["stages"].append({
                "stage": "Korelasyon koruma (geri alma)",
                "rows_before": before_revert,
                "rows_after": len(df),
                "removed": 0,
                "removed_pct": 0.0,
                "restored": restored,
                "detail": {"reverted": True, "regressions": regressions},
            })
    report["correlation_guard"] = guard_info

    # -- 6. Raporlama ----------------------------------------------------- #
    _check_cancel(cancel_event)
    df = df.reset_index(drop=True)
    tot_preserved = z_preserved + iso_preserved
    report["rows_out"] = len(df)
    report["retention_pct"] = round(len(df) / rows_in * 100, 2) if rows_in else 0.0
    report["removed_total"] = rows_in - len(df)
    report["correlations"] = validate_correlations(df, schema)
    report["distributions"] = validate_distributions(df, seed_df, schema)
    report["column_stats"] = _column_stats(df, schema)
    report["schema_conformance"] = _schema_conformance(df, schema)
    report["preserved_anomalies"] = {
        "column": target_preserve_col,
        "value": target_preserve_val if target_preserve_val is not None else 1,
        "z_score_preserved": z_preserved,
        "isolation_forest_preserved": iso_preserved,
        "total_preserved": tot_preserved,
    }

    emit(t("validation.finished", rows_in=format(rows_in, ","),
             rows_out=format(len(df), ","),
             retention="%.1f" % report["retention_pct"]))
    if target_preserve_col and tot_preserved > 0:
        emit("  -> " + t("validation.preserved_summary",
                          rows=tot_preserved, column=target_preserve_col))

    for c in report["correlations"]:
        corr_status = (t("validation.verdict.ok") if c["pass"]
                       else t("validation.verdict.below"))
        emit("  -> " + t("validation.correlation_line",
                         pair=" - ".join(c["pair"]), r="%.3f" % c["actual_r"],
                         sign=c["expected_sign"], min_r="%.2f" % c["min_r"],
                         verdict=corr_status))

    dist_rep = report.get("distributions", {})
    if not dist_rep.get("skipped"):
        emit("  -> " + t("validation.ks_summary",
                          passed=dist_rep.get("passed", 0),
                          total=dist_rep.get("total", 0)))

    failed_corr = [c for c in report["correlations"] if not c["pass"]]
    if failed_corr:
        emit(t("validation.correlations_unmet",
               count=len(failed_corr),
               pairs=", ".join("-".join(c["pair"]) for c in failed_corr)),
             level=config.PROGRESS_WARNING)

    # -- 6b. Monotonluk ve Kredi Riski Skor Kartı Doğrulaması -------------- #
    if schema.monotonicity_rules:
        try:
            from .monotonicity_validator import validate_monotonicity
            mono_report = validate_monotonicity(df, schema.monotonicity_rules, seed=schema.random_seed)
            report["monotonicity"] = mono_report.to_dict()
            emit("  -> " + t("validation.monotonicity_summary",
                              passed=mono_report.passed_rules,
                              total=mono_report.total_rules))
            for mr in mono_report.results:
                st = (t("validation.verdict.ok") if mr.passed
                      else t("validation.verdict.violation"))
                emit("     * " + t("validation.monotonicity_line",
                                   x=mr.column_x, y=mr.column_y,
                                   direction=mr.direction,
                                   r="%.3f" % mr.spearman_r,
                                   compliance="%.1f" % (mr.binned_compliance_ratio * 100),
                                   verdict=st))
        except Exception as exc:
            log.warning("Monotonluk denetimi hatası: %s", exc)

    # -- 7. Gizlilik ve HIPAA Safe Harbor Denetimi ----------------------- #
    if audit_privacy or seed_df is not None:
        try:
            from .privacy_auditor import audit_dataset_privacy
            priv_rep = audit_dataset_privacy(df, seed_df=seed_df, seed=schema.random_seed,
                                             table_name=audit_table_name)
            report["privacy_audit"] = priv_rep.to_dict()
            if priv_rep.dcr and priv_rep.nndr and priv_rep.has_reference_data:
                emit("  -> " + t("validation.privacy_nndr",
                                  dcr="%.4f" % priv_rep.dcr.mean_dcr,
                                  nndr="%.4f" % priv_rep.nndr.mean_nndr,
                                  risk=priv_rep.nndr.memorization_risk))
            if not priv_rep.hipaa_audit.passed:
                emit("  -> " + t("validation.hipaa_warning",
                                  summary=priv_rep.hipaa_audit.summary),
                     level=config.PROGRESS_WARNING)
            else:
                emit("  -> " + t("validation.hipaa_ok"))
        except Exception as exc:
            log.warning("Gizlilik denetimi çalıştırılamadı: %s", exc)

    return df, report


def _column_stats(df: pd.DataFrame, schema: SchemaContract) -> Dict[str, Any]:
    """Rapor ve dataset card için kolon bazli ozet istatistikler."""
    stats: Dict[str, Any] = {}
    for col in schema.columns:
        if col.name not in df.columns:
            continue
        series = df[col.name]
        entry: Dict[str, Any] = {
            "dtype": str(series.dtype),
            "null_count": int(series.isna().sum()),
            "unique": int(series.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            clean = series.dropna().astype("float64")
            if len(clean):
                entry.update({
                    "min": round(float(clean.min()), 4),
                    "max": round(float(clean.max()), 4),
                    "mean": round(float(clean.mean()), 4),
                    "std": round(float(clean.std()), 4),
                    "median": round(float(clean.median()), 4),
                })
        elif pd.api.types.is_bool_dtype(series):
            entry["true_ratio"] = round(float(series.astype(bool).mean()), 4)
        else:
            top = series.value_counts(dropna=True).head(5)
            entry["top_values"] = {str(k): int(v) for k, v in top.items()}
        stats[col.name] = entry
    return stats


def _schema_conformance(df: pd.DataFrame, schema: SchemaContract) -> Dict[str, Any]:
    """Temiz verinin sozlesmeye uyum özeti."""
    expected = schema.column_names
    return {
        "missing_columns": sorted(expected - set(df.columns)),
        "extra_columns": sorted(set(df.columns) - expected),
        "column_order_matches": [c.name for c in schema.columns if c.name in df.columns]
                                == [c for c in df.columns if c in expected],
    }
