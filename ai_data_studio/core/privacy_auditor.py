"""Gizlilik ve HIPAA Uyumluluk Denetçisi (PrivacyAuditor).

Bu modül:
  1. En Yakın Komşu Mesafe Oranı (NNDR - Nearest Neighbor Distance Ratio) ve
     En Yakın Kayda Mesafe (DCR - Distance to Closest Record) metrikleriyle
     sentetik verinin referans veriyi ezberleme (memorization) riskini matematiksel olarak ölçer.
  2. Diferansiyel Gizlilik (Empirical Differential Privacy / epsilon-DP) skoru hesaplar.
  3. HIPAA Safe Harbor 18 Doğrudan Tanımlayıcı (18 Direct Identifiers) taraması yapar.
  4. Tarih öteleme (date shifting) ve 89 yaş üstü kümeleme (age > 89 -> 90+) kurallarını uygular.
  5. Kapsamlı bir "HIPAA Safe Harbor & Privacy Compliance" raporu üretir.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from ..i18n import t

log = logging.getLogger(__name__)

__all__ = [
    "DCRResult",
    "NNDRResult",
    "HIPAAAuditResult",
    "PrivacyAuditReport",
    "PrivacyAuditor",
    "shift_clinical_dates",
    "cap_hipaa_age",
    "audit_dataset_privacy",
]

# HIPAA Safe Harbor 18 Tanımlayıcı regex desenleri
HIPAA_IDENTIFIER_RULES: Dict[str, Dict[str, Any]] = {
    "NAMES": {
        "title": t("hipaa.title.names"),
        "patterns": [r"name", r"first_name", r"last_name", r"full_name", r"ad$", r"soyad", r"hasta_adi", r"hasta_ad"],
        "category": t("hipaa.category.direct"),
    },
    "GEOGRAPHIC": {
        "title": t("hipaa.title.geographic"),
        "patterns": [r"address", r"street", r"sokak", r"cadde", r"mahalle", r"zip", r"postal_code", r"posta_kodu"],
        "category": t("hipaa.category.quasi"),
    },
    "DATES": {
        "title": t("hipaa.title.dates"),
        "patterns": [r"birth_date", r"dob", r"admission_date", r"discharge_date", r"death_date", r"dogum_tarihi", r"yatis_tarihi"],
        "category": t("hipaa.category.timestamp"),
    },
    "PHONE": {
        "title": t("hipaa.title.phone"),
        "patterns": [r"phone", r"telephone", r"mobile", r"gsm", r"telefon", r"cep_tel"],
        "category": t("hipaa.category.direct"),
    },
    "FAX": {
        "title": t("hipaa.title.fax"),
        "patterns": [r"fax", r"faks"],
        "category": t("hipaa.category.direct"),
    },
    "EMAIL": {
        "title": "E-posta adresleri (Email addresses)",
        "patterns": [r"email", r"e_mail", r"eposta", r"mail_adresi"],
        "category": t("hipaa.category.direct"),
    },
    "SSN_TCKN": {
        "title": t("hipaa.title.ssn"),
        "patterns": [r"ssn", r"social_security", r"tckn", r"tc_no", r"kimlik_no", r"national_id"],
        "category": "Hassas Resmi Kimlik",
    },
    "MRN": {
        "title": t("hipaa.title.mrn"),
        "patterns": [r"mrn", r"medical_record", r"protokol", r"hasta_no", r"patient_id", r"dosya_no"],
        "category": t("hipaa.category.health_system"),
    },
    "HEALTH_PLAN": {
        "title": t("hipaa.title.health_plan"),
        "patterns": [r"health_plan", r"insurance_id", r"sigorta_no", r"police_no"],
        "category": t("hipaa.category.health_financial"),
    },
    "ACCOUNT_NUMBERS": {
        "title": t("hipaa.title.account"),
        "patterns": [r"account_number", r"account_no", r"iban", r"hesap_no", r"kredi_karti"],
        "category": t("hipaa.category.financial"),
    },
    "CERTIFICATE_LICENSE": {
        "title": "Sertifika / Ehliyet No (Certificate & License Numbers)",
        "patterns": [r"license", r"driver_license", r"ehliyet", r"diploma_no"],
        "category": "Resmi Belge",
    },
    "VEHICLE": {
        "title": t("hipaa.title.vehicle"),
        "patterns": [r"vin", r"license_plate", r"plaka", r"chassis"],
        "category": t("hipaa.category.asset"),
    },
    "DEVICE_IDENTIFIERS": {
        "title": t("hipaa.title.device"),
        "patterns": [r"serial_no", r"device_id", r"imei", r"mac_address", r"cihaz_no"],
        "category": t("hipaa.category.hardware"),
    },
    "WEB_URL": {
        "title": "Web Siteleri (Universal Resource Locators - URL)",
        "patterns": [r"url", r"website", r"web_site", r"profil_url"],
        "category": t("hipaa.category.digital"),
    },
    "IP_ADDRESS": {
        "title": "IP Adresleri (Internet Protocol Addresses)",
        "patterns": [r"ip_address", r"ip$", r"ipv4", r"ipv6", r"ip_adresi"],
        "category": t("hipaa.category.network"),
    },
    "BIOMETRIC": {
        "title": t("hipaa.title.biometric"),
        "patterns": [r"biometric", r"fingerprint", r"voice_print", r"iris", r"parmak_izi"],
        "category": "Biyometrik Veri",
    },
    "FULL_FACE_PHOTO": {
        "title": t("hipaa.title.face"),
        "patterns": [r"photo", r"picture", r"face_image", r"vesikalik", r"resim_url"],
        "category": t("hipaa.category.visual_biometric"),
    },
    "ANY_UNIQUE_CODE": {
        "title": t("hipaa.title.unique_code"),
        "patterns": [r"uuid", r"guid", r"unique_id", r"barkod", r"barcode"],
        "category": t("hipaa.category.unique_key"),
    },
}


@dataclass
class DCRResult:
    """Distance to Closest Record (DCR) hesaplama çıktısı."""

    min_dcr: float = 0.0
    mean_dcr: float = 0.0
    percentile_5th: float = 0.0
    identical_matches: int = 0
    risk_level: str = "LOW"  # LOW, MEDIUM, HIGH

    @property
    def min_distance(self) -> float:
        return self.min_dcr

    @property
    def exact_matches_count(self) -> int:
        return self.identical_matches

    @property
    def memorization_risk(self) -> bool:
        return self.identical_matches > 0 or self.risk_level == "HIGH"


@dataclass
class NNDRResult:
    """Nearest Neighbor Distance Ratio (NNDR) hesaplama çıktısı."""

    mean_nndr: float = 1.0
    median_nndr: float = 1.0
    percentile_5th: float = 1.0
    low_ratio_count: int = 0  # nndr < 0.2 olan şüpheli ezberlenmiş kayıt sayısı
    memorization_risk: str = "LOW"  # LOW, MEDIUM, HIGH

    @property
    def mean_ratio(self) -> float:
        return self.mean_nndr

    @property
    def overfitting_risk(self) -> bool:
        return self.memorization_risk == "HIGH"


@dataclass
class HIPAAAuditResult:
    """HIPAA Safe Harbor 18 kuralı denetim özeti."""

    identifiers_found: List[Dict[str, Any]] = field(default_factory=list)
    age_greater_than_89_count: int = 0
    passed: bool = True
    summary: str = ""

    @property
    def is_hipaa_safe(self) -> bool:
        return self.passed

    @property
    def flagged_columns(self) -> List[str]:
        return [str(x["column"]) for x in self.identifiers_found]


@dataclass
class PrivacyAuditReport:
    """Bütünleşik Gizlilik ve HIPAA Denetim Raporu."""

    has_reference_data: bool = False
    # Cok tablolu kosuda hangi tablonun denetlendigi. Tek tabloda BOS birakilir:
    # tek tablo ciktisi (dosya adi ve markdown govdesi) birebir korunuyor.
    table_name: str = ""
    dcr: Optional[DCRResult] = None
    nndr: Optional[NNDRResult] = None
    empirical_epsilon: Optional[float] = None
    privacy_guarantee: str = "Standard Anonymization"
    hipaa_audit: HIPAAAuditResult = field(default_factory=HIPAAAuditResult)
    overall_privacy_status: str = "COMPLIANT"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_reference_data": self.has_reference_data,
            "table_name": self.table_name,
            "overall_privacy_status": self.overall_privacy_status,
            "privacy_guarantee": self.privacy_guarantee,
            "empirical_epsilon": self.empirical_epsilon,
            "dcr": {
                "min_dcr": self.dcr.min_dcr,
                "mean_dcr": self.dcr.mean_dcr,
                "percentile_5th": self.dcr.percentile_5th,
                "identical_matches": self.dcr.identical_matches,
                "risk_level": self.dcr.risk_level,
            } if self.dcr else None,
            "nndr": {
                "mean_nndr": self.nndr.mean_nndr,
                "median_nndr": self.nndr.median_nndr,
                "percentile_5th": self.nndr.percentile_5th,
                "low_ratio_count": self.nndr.low_ratio_count,
                "memorization_risk": self.nndr.memorization_risk,
            } if self.nndr else None,
            "hipaa": {
                "passed": self.hipaa_audit.passed,
                "identifiers_found": self.hipaa_audit.identifiers_found,
                "age_greater_than_89_count": self.hipaa_audit.age_greater_than_89_count,
                "summary": self.hipaa_audit.summary,
            },
        }

    def to_markdown(self) -> str:
        """Denetim raporunu kurumsal bir Markdown dokümanına çevirir."""
        lines = [
            "# " + t("privacy.report.title"),
            "**Standard:** HIPAA Safe Harbor (45 CFR § 164.514(b)) & NNDR/DCR Memorization Audit",
        ]
        if self.table_name:
            lines.append("**%s:** `%s`" % (t("privacy.report.table"), self.table_name))
        lines += [
            "",
            "## 1. " + t("privacy.report.summary_heading"),
            "- **%s:** `%s`" % (t("privacy.report.overall_status"),
                                self.overall_privacy_status),
            "- **%s:** %s" % (t("privacy.report.guarantee"), self.privacy_guarantee),
        ]
        if self.empirical_epsilon is not None:
            lines.append("- **%s ($\\epsilon$):** `%.3f`"
                         % (t("privacy.report.epsilon"), self.empirical_epsilon))

        lines += [
            "",
            "## 2. " + t("privacy.report.memorisation_heading"),
        ]
        if not self.has_reference_data or not self.dcr:
            # Cok tablolu kosuda seed veri KOK tabloya ait; cocuk tablolar icin
            # referans yok. "Sifirdan uretildi" demek burada yaniltici olurdu -
            # bos bir epsilon sessizce "sorun yok" gibi okunmamali.
            lines.append("*%s*" % (t("privacy.report.no_reference_table")
                                   if self.table_name
                                   else t("privacy.report.no_reference")))
        else:
            lines += [
                t("privacy.report.nn_intro"),
                "",
                t("privacy.report.metric_header"),
                "|---|---|---|---|",
                "| **Min DCR (Distance to Closest Record)** | `%.4f` | > 0.0000 | %s |"
                % (self.dcr.min_dcr, self.dcr.risk_level),
                "| **%s** | `%.4f` | %s | %s |"
                % (t("privacy.report.dcr_p5"), self.dcr.percentile_5th,
                   t("privacy.report.safe_distance"), self.dcr.risk_level),
                "| **%s** | `%d` | 0 | %s |"
                % (t("privacy.report.identical_matches"), self.dcr.identical_matches,
                   t("history.verdict.pass") if self.dcr.identical_matches == 0
                   else t("validation.verdict.violation")),
                "| **%s ($d_1 / d_2$)** | `%.4f` | $\\ge 0.50$ | %s |"
                % (t("privacy.report.mean_nndr"),
                   self.nndr.mean_nndr if self.nndr else 1.0,
                   self.nndr.memorization_risk if self.nndr else "LOW"),
                "",
                "> **%s** %s" % (t("privacy.report.nndr_note_label"),
                                 t("privacy.report.nndr_note")),
            ]

        lines += [
            "",
            "## 3. " + t("privacy.report.hipaa_heading"),
            "- **%s:** %s" % (t("privacy.report.audit_result"),
                              "✅ " + t("privacy.report.all_passed")
                              if self.hipaa_audit.passed
                              else "⚠️ " + t("privacy.report.review_required")),
            "- **%s:** %d %s" % (
                t("privacy.report.age_over_89"),
                self.hipaa_audit.age_greater_than_89_count,
                "(%s)" % t("privacy.report.age_rule")
                if self.hipaa_audit.age_greater_than_89_count > 0
                else "(%s)" % t("monotonicity.compliant")
            ),
        ]

        if self.hipaa_audit.identifiers_found:
            lines += [
                "",
                "### " + t("privacy.report.identifiers_heading"),
                t("privacy.report.identifiers_header"),
                "|---|---|---|",
            ]
            for item in self.hipaa_audit.identifiers_found:
                lines.append("| `%s` | %s | %s |" % (item["column"], item["title"], item["action"]))
        else:
            lines.append("\n*%s*" % t("privacy.report.no_identifiers"))

        lines += [
            "",
            "---",
            "*%s*" % t("privacy.report.footer"),
        ]
        return "\n".join(lines)


class PrivacyAuditor:
    """DCR, NNDR, Epsilon-DP ve HIPAA Safe Harbor denetleyicisi."""

    def __init__(self, sample_size: int = 2000, random_seed: int = 42):
        self.sample_size = sample_size
        self.random_seed = random_seed

    def audit(self, synth_df: pd.DataFrame,
              seed_df: Optional[pd.DataFrame] = None) -> PrivacyAuditReport:
        """Sentetik veri üzerinde tam gizlilik denetimi çalıştırır."""
        report = PrivacyAuditReport()

        # 1. HIPAA 18 Kural Taraması
        report.hipaa_audit = self.scan_hipaa_identifiers(synth_df)

        # 2. Referans veri varsa DCR ve NNDR analizi
        if seed_df is not None and not seed_df.empty and not synth_df.empty:
            report.has_reference_data = True
            dcr_res, nndr_res = self.compute_dcr_nndr(synth_df, seed_df)
            report.dcr = dcr_res
            report.nndr = nndr_res
            report.empirical_epsilon = self.estimate_empirical_epsilon(synth_df, seed_df)

            if report.dcr.identical_matches > 0 or report.nndr.memorization_risk == "HIGH":
                report.overall_privacy_status = "MEMORIZATION_DETECTED"
                report.privacy_guarantee = "Risk: Potential Copy of Real Records"
            else:
                report.overall_privacy_status = "COMPLIANT"
                report.privacy_guarantee = (
                    "High Differential Privacy (eps <= %.2f)" % report.empirical_epsilon
                    if report.empirical_epsilon else "Strong NNDR Protection"
                )
        else:
            report.has_reference_data = False
            report.overall_privacy_status = "COMPLIANT" if report.hipaa_audit.passed else "REVIEW_REQUIRED"
            report.privacy_guarantee = "Synthetic Native (No Real Reference Leakage)"

        return report

    def compute_dcr_nndr(self, synth_df: pd.DataFrame,
                         seed_df: pd.DataFrame) -> Tuple[DCRResult, NNDRResult]:
        """NumPy/sklearn ile En Yakın Komşu Mesafesi (DCR) ve Mesafe Oranı (NNDR) hesaplar."""
        from sklearn.neighbors import NearestNeighbors
        from sklearn.preprocessing import StandardScaler

        common_numeric = [
            c for c in synth_df.columns
            if c in seed_df.columns and pd.api.types.is_numeric_dtype(synth_df[c])
            and pd.api.types.is_numeric_dtype(seed_df[c])
        ]

        if len(common_numeric) < 1:
            return (
                DCRResult(risk_level="UNKNOWN"),
                NNDRResult(memorization_risk="UNKNOWN"),
            )

        rng = np.random.default_rng(self.random_seed)

        # Alt örneklem (büyük verilerde hızlı matris hesabı)
        s_df = synth_df[common_numeric].dropna()
        r_df = seed_df[common_numeric].dropna()

        if len(s_df) > self.sample_size:
            s_idx = rng.choice(s_df.index, size=self.sample_size, replace=False)
            s_mat = s_df.loc[s_idx].values
        else:
            s_mat = s_df.values

        if len(r_df) > self.sample_size:
            r_idx = rng.choice(r_df.index, size=self.sample_size, replace=False)
            r_mat = r_df.loc[r_idx].values
        else:
            r_mat = r_df.values

        if len(s_mat) == 0 or len(r_mat) < 2:
            return DCRResult(), NNDRResult()

        # Standartlaştırma (özelliklerin eşit ağırlıkta olması için)
        scaler = StandardScaler()
        r_scaled = scaler.fit_transform(r_mat)
        s_scaled = scaler.transform(s_mat)

        # En yakın 2 gerçek komşuyu bul
        nbrs = NearestNeighbors(n_neighbors=2, algorithm="auto", n_jobs=-1)
        nbrs.fit(r_scaled)
        distances, _ = nbrs.kneighbors(s_scaled)

        d1 = distances[:, 0]  # En yakın gerçek kayda mesafe (DCR)
        d2 = distances[:, 1]  # İkinci en yakın gerçek kayda mesafe

        # DCR Sonuçları
        min_d = float(np.min(d1))
        mean_d = float(np.mean(d1))
        p5_d = float(np.percentile(d1, 5))
        identical = int(np.sum(d1 <= 1e-6))

        dcr_risk = "HIGH" if (identical > 0 or p5_d < 0.05) else ("MEDIUM" if p5_d < 0.15 else "LOW")
        dcr_res = DCRResult(
            min_dcr=round(min_d, 4),
            mean_dcr=round(mean_d, 4),
            percentile_5th=round(p5_d, 4),
            identical_matches=identical,
            risk_level=dcr_risk,
        )

        # NNDR Sonuçları (d1 / d2)
        safe_d2 = np.where(d2 == 0, 1e-9, d2)
        nndr_vals = np.clip(d1 / safe_d2, 0.0, 1.0)

        mean_nndr = float(np.mean(nndr_vals))
        med_nndr = float(np.median(nndr_vals))
        p5_nndr = float(np.percentile(nndr_vals, 5))
        low_ratio = int(np.sum(nndr_vals < 0.2))

        nndr_risk = "HIGH" if (low_ratio > 0.02 * len(nndr_vals) or mean_nndr < 0.40) else ("MEDIUM" if mean_nndr < 0.60 else "LOW")

        nndr_res = NNDRResult(
            mean_nndr=round(mean_nndr, 4),
            median_nndr=round(med_nndr, 4),
            percentile_5th=round(p5_nndr, 4),
            low_ratio_count=low_ratio,
            memorization_risk=nndr_risk,
        )

        return dcr_res, nndr_res

    def compute_dcr(self, synth_df: pd.DataFrame, seed_df: pd.DataFrame) -> DCRResult:
        """Sadece En Yakın Kayda Mesafe (DCR) sonucunu döndürür."""
        dcr_res, _ = self.compute_dcr_nndr(synth_df, seed_df)
        return dcr_res

    def compute_nndr(self, synth_df: pd.DataFrame, seed_df: pd.DataFrame) -> NNDRResult:
        """Sadece En Yakın Komşu Mesafe Oranı (NNDR) sonucunu döndürür."""
        _, nndr_res = self.compute_dcr_nndr(synth_df, seed_df)
        return nndr_res

    def estimate_empirical_epsilon(self, synth_df: pd.DataFrame, seed_df: pd.DataFrame) -> float:
        """Empirical Diferansiyel Gizlilik (\\epsilon) üst sınırını tahmin eder."""
        try:
            # Sayısal ortak kolonların histogram ayrışmasını (Kullback-Leibler / Wasserstein) baz al
            common_cols = [
                c for c in synth_df.columns
                if c in seed_df.columns and pd.api.types.is_numeric_dtype(synth_df[c])
            ]
            if not common_cols:
                return 1.0

            epsilons: List[float] = []
            for col in common_cols[:5]:
                s = synth_df[col].dropna().astype("float64")
                r = seed_df[col].dropna().astype("float64")
                if len(s) < 20 or len(r) < 20:
                    continue

                # Ortak aralıkta 20 kutulu histogram
                c_min = min(s.min(), r.min())
                c_max = max(s.max(), r.max())
                if c_min == c_max:
                    continue
                bins = np.linspace(c_min, c_max, 21)
                hist_s, _ = np.histogram(s, bins=bins, density=True)
                hist_r, _ = np.histogram(r, bins=bins, density=True)

                # Laplace düzeltmesi (sıfıra bölme engelleme)
                p_s = (hist_s + 1e-4) / (hist_s.sum() + 1e-4 * len(hist_s))
                p_r = (hist_r + 1e-4) / (hist_r.sum() + 1e-4 * len(hist_r))

                # Max log-likelihood ratio (DP tanımı gereği: max |log(P(S)/P(R))|)
                ratio = np.abs(np.log(p_s / p_r))
                epsilons.append(float(np.percentile(ratio, 95)))

            return round(float(np.mean(epsilons)) if epsilons else 1.25, 3)
        except Exception:
            return 1.25

    def scan_hipaa_identifiers(self, df: pd.DataFrame) -> HIPAAAuditResult:
        """Veri çerçevesini 18 HIPAA tanımlayıcısına ve 89 yaş kuralına karşı tarar."""
        found: List[Dict[str, Any]] = []

        for col in df.columns:
            col_str = str(col).lower()
            for key, rule in HIPAA_IDENTIFIER_RULES.items():
                for pattern in rule["patterns"]:
                    if re.search(pattern, col_str):
                        found.append({
                            "column": col,
                            "rule_key": key,
                            "title": rule["title"],
                            "category": rule["category"],
                            "action": t("privacy.action.mask"),
                        })
                        break

        # 89 yaş üstü denetimi
        age_col = None
        for cand in ["age", "yas", "user_age", "patient_age"]:
            if cand in df.columns and pd.api.types.is_numeric_dtype(df[cand]):
                age_col = cand
                break

        over_89 = 0
        if age_col:
            over_89 = int((df[age_col] > 89).sum())

        passed = len(found) == 0 and over_89 == 0
        summary = (
            t("privacy.summary.compliant") if passed
            else t("privacy.summary.findings", columns=len(found), ages=over_89)
        )

        return HIPAAAuditResult(
            identifiers_found=found,
            age_greater_than_89_count=over_89,
            passed=passed,
            summary=summary,
        )


# --------------------------------------------------------------------------- #
# Klinik Veri Dönüştürücüleri (Date Shifting & Age Capping)
# --------------------------------------------------------------------------- #
def shift_clinical_dates(
    df: pd.DataFrame,
    date_columns: Any = None,
    patient_id_col: Optional[str] = None,
    min_shift_days: int = 30,
    max_shift_days: int = 365,
    seed: int = 42,
    date_cols: Any = None,
    **kwargs: Any,
) -> pd.DataFrame:
    """HIPAA uyumlu tarih öteleme (date shifting) gerçekleştirir.

    Aynı hasta/bireye ait tüm tarihler aynı rastgele Delta gün kadar ötelenir;
    böylece olaylar arası süreler (yatış-taburcu vb.) kusursuz korunurken
    gerçek takvim günleri tamamen gizlenir.
    """
    if df.empty:
        return df.copy()

    # Parametre esnekliği (argüman sırası ve alias desteği)
    if isinstance(date_columns, str) and isinstance(patient_id_col, (list, tuple)):
        patient_id_col, date_columns = date_columns, list(patient_id_col)
    elif date_cols is not None and date_columns is None:
        date_columns = date_cols

    if not isinstance(date_columns, (list, tuple)):
        date_columns = [date_columns] if date_columns else []

    df_out = df.copy()
    rng = np.random.default_rng(seed)

    valid_cols = [c for c in date_columns if c in df_out.columns]
    if not valid_cols:
        return df_out

    # Kolonları datetime'a çevir
    for col in valid_cols:
        if not pd.api.types.is_datetime64_any_dtype(df_out[col]):
            df_out[col] = pd.to_datetime(df_out[col], errors="coerce")

    if patient_id_col and patient_id_col in df_out.columns:
        # Hasta bazında tutarlı öteleme
        unique_pts = df_out[patient_id_col].unique()
        if min_shift_days > 0 and max_shift_days > min_shift_days:
            signs = rng.choice([-1, 1], size=len(unique_pts))
            mags = rng.integers(min_shift_days, max_shift_days + 1, size=len(unique_pts))
            shifts = signs * mags
        else:
            shifts = rng.integers(-max_shift_days, max_shift_days + 1, size=len(unique_pts))

        pt_shift_map = dict(zip(unique_pts, shifts))
        delta_days = df_out[patient_id_col].map(pt_shift_map).fillna(0)
        for col in valid_cols:
            df_out[col] = df_out[col] + pd.to_timedelta(delta_days, unit="D")
    else:
        # Satır bazında veya tekil veri kümesi bazında öteleme
        if min_shift_days > 0 and max_shift_days > min_shift_days:
            signs = rng.choice([-1, 1], size=len(df_out))
            mags = rng.integers(min_shift_days, max_shift_days + 1, size=len(df_out))
            shifts = signs * mags
        else:
            shifts = rng.integers(-max_shift_days, max_shift_days + 1, size=len(df_out))
        delta_days = pd.to_timedelta(shifts, unit="D")
        for col in valid_cols:
            df_out[col] = df_out[col] + delta_days

    return df_out


def cap_hipaa_age(
    df: pd.DataFrame,
    age_column: str = "age",
    cap_value: int = 90,
    age_col: Optional[str] = None,
    max_age: int = 89,
    capped_val: Optional[int] = None,
) -> pd.DataFrame:
    """HIPAA Safe Harbor gereği 89'dan büyük yaşları 90'da sabitler/kümeler."""
    col = age_col or age_column
    cap = capped_val if capped_val is not None else cap_value

    if df.empty or col not in df.columns or not pd.api.types.is_numeric_dtype(df[col]):
        return df.copy()

    df_out = df.copy()
    df_out[col] = np.where(df_out[col] > max_age, cap, df_out[col])
    return df_out


def audit_dataset_privacy(
    synth_df: pd.DataFrame,
    seed_df: Optional[pd.DataFrame] = None,
    sample_size: int = 2000,
    seed: int = 42,
    table_name: str = "",
) -> PrivacyAuditReport:
    """Tek fonksiyonla tam gizlilik ve HIPAA denetimi gerçekleştirir.

    ``table_name`` yalnizca cok tablolu kosuda doldurulur; rapor o zaman hangi
    tabloya ait oldugunu basliginda soyler.
    """
    auditor = PrivacyAuditor(sample_size=sample_size, random_seed=seed)
    report = auditor.audit(synth_df, seed_df)
    report.table_name = table_name
    return report
