"""Sezgisel gizlilik kontrolleri (PrivacyAuditor).

Bu modül:
  1. En Yakın Komşu Mesafe Oranı (NNDR - Nearest Neighbor Distance Ratio) ve
     En Yakın Kayda Mesafe (DCR - Distance to Closest Record) metrikleriyle
     sentetik satırların referans kayıtların kopyası olup olmadığını örneklem üzerinde ölçer.
  2. Ortak sayısal kolonların histogramları arasındaki Jensen-Shannon mesafesini
     hesaplar (``distribution_divergence``). Bir gizlilik garantisi DEĞİLDİR.
  3. Kolon ADLARINI 18 HIPAA Safe Harbor tanımlayıcı kategorisinin desenleriyle eşleştirir.
     Hücre değerlerine bakmaz; bir uyumluluk sertifikası değildir.
  4. Tarih öteleme (date shifting) ve 89 yaş üstü kümeleme (age > 89 -> 90+) yardımcıları sunar.
  5. Bulguları, kapsamını açıkça yazan bir Markdown raporuna döker.
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

# HIPAA Safe Harbor'un 18 tanımlayıcı kategorisi için kolon ADI desenleri.
# Başlık ve kategori katalog ANAHTARI olarak tutulur ve tarama anında çevrilir:
# modül yüklenirken t() çağırmak metni o anki dile dondurur, sonradan dil
# değişse de rapor eski dilde kalırdı.
HIPAA_IDENTIFIER_RULES: Dict[str, Dict[str, Any]] = {
    "NAMES": {
        "title_key": "hipaa.title.names",
        "patterns": [r"name", r"first_name", r"last_name", r"full_name", r"ad$", r"soyad", r"hasta_adi", r"hasta_ad"],
        "category_key": "hipaa.category.direct",
    },
    "GEOGRAPHIC": {
        "title_key": "hipaa.title.geographic",
        "patterns": [r"address", r"street", r"sokak", r"cadde", r"mahalle", r"zip", r"postal_code", r"posta_kodu"],
        "category_key": "hipaa.category.quasi",
    },
    "DATES": {
        "title_key": "hipaa.title.dates",
        "patterns": [r"birth_date", r"dob", r"admission_date", r"discharge_date", r"death_date", r"dogum_tarihi", r"yatis_tarihi"],
        "category_key": "hipaa.category.timestamp",
    },
    "PHONE": {
        "title_key": "hipaa.title.phone",
        "patterns": [r"phone", r"telephone", r"mobile", r"gsm", r"telefon", r"cep_tel"],
        "category_key": "hipaa.category.direct",
    },
    "FAX": {
        "title_key": "hipaa.title.fax",
        "patterns": [r"fax", r"faks"],
        "category_key": "hipaa.category.direct",
    },
    "EMAIL": {
        "title_key": "hipaa.title.email",
        "patterns": [r"email", r"e_mail", r"eposta", r"mail_adresi"],
        "category_key": "hipaa.category.direct",
    },
    "SSN_TCKN": {
        "title_key": "hipaa.title.ssn",
        "patterns": [r"ssn", r"social_security", r"tckn", r"tc_no", r"kimlik_no", r"national_id"],
        "category_key": "hipaa.category.government_id",
    },
    "MRN": {
        "title_key": "hipaa.title.mrn",
        "patterns": [r"mrn", r"medical_record", r"protokol", r"hasta_no", r"patient_id", r"dosya_no"],
        "category_key": "hipaa.category.health_system",
    },
    "HEALTH_PLAN": {
        "title_key": "hipaa.title.health_plan",
        "patterns": [r"health_plan", r"insurance_id", r"sigorta_no", r"police_no"],
        "category_key": "hipaa.category.health_financial",
    },
    "ACCOUNT_NUMBERS": {
        "title_key": "hipaa.title.account",
        "patterns": [r"account_number", r"account_no", r"iban", r"hesap_no", r"kredi_karti"],
        "category_key": "hipaa.category.financial",
    },
    "CERTIFICATE_LICENSE": {
        "title_key": "hipaa.title.certificate",
        "patterns": [r"license", r"driver_license", r"ehliyet", r"diploma_no"],
        "category_key": "hipaa.category.official_document",
    },
    "VEHICLE": {
        "title_key": "hipaa.title.vehicle",
        "patterns": [r"vin", r"license_plate", r"plaka", r"chassis"],
        "category_key": "hipaa.category.asset",
    },
    "DEVICE_IDENTIFIERS": {
        "title_key": "hipaa.title.device",
        "patterns": [r"serial_no", r"device_id", r"imei", r"mac_address", r"cihaz_no"],
        "category_key": "hipaa.category.hardware",
    },
    "WEB_URL": {
        "title_key": "hipaa.title.url",
        "patterns": [r"url", r"website", r"web_site", r"profil_url"],
        "category_key": "hipaa.category.digital",
    },
    "IP_ADDRESS": {
        "title_key": "hipaa.title.ip",
        "patterns": [r"ip_address", r"ip$", r"ipv4", r"ipv6", r"ip_adresi"],
        "category_key": "hipaa.category.network",
    },
    "BIOMETRIC": {
        "title_key": "hipaa.title.biometric",
        "patterns": [r"biometric", r"fingerprint", r"voice_print", r"iris", r"parmak_izi"],
        "category_key": "hipaa.category.biometric",
    },
    "FULL_FACE_PHOTO": {
        "title_key": "hipaa.title.face",
        "patterns": [r"photo", r"picture", r"face_image", r"vesikalik", r"resim_url"],
        "category_key": "hipaa.category.visual_biometric",
    },
    "ANY_UNIQUE_CODE": {
        "title_key": "hipaa.title.unique_code",
        "patterns": [r"uuid", r"guid", r"unique_id", r"barkod", r"barcode"],
        "category_key": "hipaa.category.unique_key",
    },
}


def _fmt(value: Optional[float], pattern: str, scale: float = 1.0) -> str:
    """Rapor hücresi; taban çizgisi olmayan eski kayıtlarda "-" yazar."""
    return "-" if value is None else pattern % (value * scale)


_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _worst(*levels: str) -> str:
    return max(levels, key=lambda level: _RISK_ORDER.get(level, 0))


def _rate_excess_level(rate: float, baseline: float, n: int, n_baseline: int,
                       high_floor: float, medium_floor: float) -> str:
    """Bir oranın taban çizgisini örnekleme hatasının ötesinde aşıp aşmadığı.

    İki oran farkının standart hatasıyla (havuzlanmış binom) karşılaştırılır;
    küçük örneklemde gürültüyü kopya sanmamak için sabit bir alt eşik de vardır.
    """
    pooled = (rate * n + baseline * n_baseline) / float(n + n_baseline)
    pooled = min(max(pooled, 1.0 / (n + n_baseline)), 1.0 - 1e-9)
    se = float(np.sqrt(pooled * (1.0 - pooled) * (1.0 / n + 1.0 / n_baseline)))
    excess = rate - baseline
    if excess > max(high_floor, 3.0 * se):
        return "HIGH"
    if excess > max(medium_floor, 2.0 * se):
        return "MEDIUM"
    return "LOW"


@dataclass
class DCRResult:
    """Distance to Closest Record (DCR) hesaplama çıktısı.

    ``baseline_*`` alanları referans->referans (satırın kendisi hariç) ölçümüdür:
    aynı dağılımdan gelen, KOPYA OLMAYAN verinin nasıl göründüğü. Eski kayıtlarda
    bulunmaz (None).
    """

    min_dcr: float = 0.0
    mean_dcr: float = 0.0
    percentile_5th: float = 0.0
    identical_matches: int = 0
    risk_level: str = "LOW"  # LOW, MEDIUM, HIGH, UNKNOWN
    identical_rate: float = 0.0
    baseline_min_dcr: Optional[float] = None
    baseline_percentile_5th: Optional[float] = None
    baseline_identical_rate: Optional[float] = None

    @property
    def min_distance(self) -> float:
        return self.min_dcr

    @property
    def exact_matches_count(self) -> int:
        return self.identical_matches

    @property
    def memorization_risk(self) -> bool:
        # Kesikli veride birebir eşleşme doğal olarak olur; karar taban çizgisine göre
        # verilen risk seviyesindedir.
        return self.risk_level == "HIGH"


@dataclass
class NNDRResult:
    """Nearest Neighbor Distance Ratio (NNDR) hesaplama çıktısı."""

    mean_nndr: float = 1.0
    median_nndr: float = 1.0
    percentile_5th: float = 1.0
    low_ratio_count: int = 0  # nndr < 0.2 olan satır sayısı
    memorization_risk: str = "LOW"  # LOW, MEDIUM, HIGH, UNKNOWN
    low_ratio_rate: float = 0.0
    baseline_mean_nndr: Optional[float] = None
    baseline_low_ratio_rate: Optional[float] = None

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
    # Ortak sayısal kolonların histogramları arasındaki ortalama Jensen-Shannon
    # mesafesi (0 = aynı, 1 = hiç örtüşme yok). Bir gizlilik garantisi DEĞİL.
    distribution_divergence: Optional[float] = None
    distribution_divergence_columns: Dict[str, float] = field(default_factory=dict)
    # Ezberleme kontrolünün okunur özeti (çevrilmiş metin); adı tarihsel.
    privacy_guarantee: str = ""
    hipaa_audit: HIPAAAuditResult = field(default_factory=HIPAAAuditResult)
    overall_privacy_status: str = "NO_ISSUES_FOUND"

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict

        return {
            "has_reference_data": self.has_reference_data,
            "table_name": self.table_name,
            "overall_privacy_status": self.overall_privacy_status,
            "privacy_guarantee": self.privacy_guarantee,
            "distribution_divergence": self.distribution_divergence,
            "distribution_divergence_columns": dict(self.distribution_divergence_columns),
            "dcr": asdict(self.dcr) if self.dcr else None,
            "nndr": asdict(self.nndr) if self.nndr else None,
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
            t("privacy.report.scope"),
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
        if self.distribution_divergence is not None:
            lines.append("- **%s:** `%.3f` - %s"
                         % (t("privacy.report.divergence"), self.distribution_divergence,
                            t("privacy.report.divergence_note")))

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
            nndr = self.nndr or NNDRResult()
            lines += [
                t("privacy.report.nn_intro"),
                "",
                t("privacy.report.metric_header"),
                "|---|---|---|---|",
                "| **Min DCR (Distance to Closest Record)** | `%.4f` | %s | %s |"
                % (self.dcr.min_dcr, _fmt(self.dcr.baseline_min_dcr, "`%.4f`"),
                   self.dcr.risk_level),
                "| **%s** | `%.4f` | %s | %s |"
                % (t("privacy.report.dcr_p5"), self.dcr.percentile_5th,
                   _fmt(self.dcr.baseline_percentile_5th, "`%.4f`"), self.dcr.risk_level),
                "| **%s** | `%d` (%.1f%%) | %s | %s |"
                % (t("privacy.report.identical_matches"), self.dcr.identical_matches,
                   self.dcr.identical_rate * 100,
                   _fmt(self.dcr.baseline_identical_rate, "%.1f%%", 100), self.dcr.risk_level),
                "| **%s ($d_1 / d_2$)** | `%.4f` | %s | %s |"
                % (t("privacy.report.mean_nndr"), nndr.mean_nndr,
                   _fmt(nndr.baseline_mean_nndr, "`%.4f`"), nndr.memorization_risk),
                "| **%s** | %.1f%% | %s | %s |"
                % (t("privacy.report.low_nndr_share"), nndr.low_ratio_rate * 100,
                   _fmt(nndr.baseline_low_ratio_rate, "%.1f%%", 100),
                   nndr.memorization_risk),
                "",
                "> **%s** %s" % (t("privacy.report.nndr_note_label"),
                                 t("privacy.report.nndr_note")),
            ]

        lines += [
            "",
            "## 3. " + t("privacy.report.hipaa_heading"),
            t("privacy.report.hipaa_scope"),
            "",
            "- **%s:** %s" % (t("privacy.report.audit_result"),
                              "✅ " + t("privacy.report.all_passed")
                              if self.hipaa_audit.passed
                              else "⚠️ " + t("privacy.report.review_required")),
            "- **%s:** %d%s" % (
                t("privacy.report.age_over_89"),
                self.hipaa_audit.age_greater_than_89_count,
                " (%s)" % t("privacy.report.age_rule")
                if self.hipaa_audit.age_greater_than_89_count > 0 else ""
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
    """DCR/NNDR ezberleme testi, dağılım farkı skoru ve tanımlayıcı kolon adı taraması."""

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
            (report.distribution_divergence,
             report.distribution_divergence_columns) = self.estimate_distribution_divergence(
                synth_df, seed_df)

            if report.dcr.risk_level == "HIGH" or report.nndr.memorization_risk == "HIGH":
                report.overall_privacy_status = "MEMORIZATION_DETECTED"
                report.privacy_guarantee = t("privacy.assessment.copies_found")
            else:
                report.overall_privacy_status = (
                    "NO_ISSUES_FOUND" if report.hipaa_audit.passed else "REVIEW_REQUIRED")
                # Ortak sayısal kolon ya da yeterli referans satırı yoksa ölçülemedi.
                report.privacy_guarantee = t(
                    "privacy.assessment.not_measured"
                    if report.dcr.risk_level == "UNKNOWN" else "privacy.assessment.no_copies")
        else:
            # Referans yoksa ezberleme ölçülemez; "sızıntı yok" demek ölçülmemiş
            # bir şeyi garanti etmek olurdu.
            report.has_reference_data = False
            report.overall_privacy_status = (
                "NO_ISSUES_FOUND" if report.hipaa_audit.passed else "REVIEW_REQUIRED")
            report.privacy_guarantee = t("privacy.assessment.not_measured")

        return report

    def compute_dcr_nndr(self, synth_df: pd.DataFrame,
                         seed_df: pd.DataFrame) -> Tuple[DCRResult, NNDRResult]:
        """DCR ve NNDR'yi referans->referans taban çizgisine göre değerlendirir.

        Sabit eşikler boyuttan ve yoğunluktan bağımsız değildi: yerel olarak düzgün
        yoğunlukta P(d1/d2 < 0.2) ~ 0.2^d olduğundan 1-2 sayısal kolonda hiç
        kopyalanmamış veri de "HIGH" çıkıyordu (ölçüm: d=2, n=2000 -> %3,8 > %2).
        Artık aynı metrikler referansın her satırı için, kendisi hariç, diğer
        referans satırlarına karşı da ölçülür; bu, aynı dağılımdan gelen kopya
        OLMAYAN verinin görünümüdür ve karar ona göre verilir:

        * birebir eşleşme oranı ve NNDR < 0.2 payı taban çizgisini örnekleme
          hatasının ötesinde aşarsa MEDIUM/HIGH; referansta hiç birebir tekrar
          yoksa tek bir birebir kopya bile HIGH;
        * DCR 5. yüzdeliği taban çizgisinin altına düşerse en fazla MEDIUM -
          sentetik veri yoğun bölgelerde toplandığında kopya olmadan da düşer.
        """
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

        if len(s_mat) == 0 or len(r_mat) < 3:
            # Taban çizgisi için referansta en az 3 satır gerekir (kendisi + 2 komşu).
            return DCRResult(risk_level="UNKNOWN"), NNDRResult(memorization_risk="UNKNOWN")

        # Standartlaştırma (özelliklerin eşit ağırlıkta olması için)
        scaler = StandardScaler()
        r_scaled = scaler.fit_transform(r_mat)
        s_scaled = scaler.transform(s_mat)

        nbrs = NearestNeighbors(n_neighbors=3, algorithm="auto", n_jobs=-1)
        nbrs.fit(r_scaled)
        synth_d, _ = nbrs.kneighbors(s_scaled, n_neighbors=2)
        # Referans satırının ilk komşusu kendisidir (mesafe 0) - atlanır. Referansta
        # birebir tekrar varsa kalan ilk komşu da 0 olur: bu doğal bir eşleşmedir ve
        # taban çizgisine öyle girer.
        ref_d, _ = nbrs.kneighbors(r_scaled, n_neighbors=3)
        ref_d = ref_d[:, 1:]

        def summarise(d: np.ndarray) -> Dict[str, Any]:
            d1, d2 = d[:, 0], d[:, 1]
            ratio = np.clip(d1 / np.where(d2 == 0, 1e-9, d2), 0.0, 1.0)
            return {
                "d1": d1, "ratio": ratio,
                "min": float(np.min(d1)), "p5": float(np.percentile(d1, 5)),
                "identical": int(np.sum(d1 <= 1e-6)),
                "identical_rate": float(np.mean(d1 <= 1e-6)),
                "low_count": int(np.sum(ratio < 0.2)),
                "low_rate": float(np.mean(ratio < 0.2)),
            }

        syn, ref = summarise(synth_d), summarise(ref_d)
        n_syn, n_ref = len(s_mat), len(r_mat)

        # Birebir eşleşme: referansın kendi içinde hiç tekrarı yoksa (sürekli veri)
        # tek bir birebir kopya bile gerçek bir kaydın sızmasıdır.
        if ref["identical"] == 0:
            identical_level = "HIGH" if syn["identical"] > 0 else "LOW"
        else:
            identical_level = _rate_excess_level(syn["identical_rate"], ref["identical_rate"],
                                                 n_syn, n_ref, high_floor=0.01,
                                                 medium_floor=0.005)
        if ref["p5"] > 0:
            p5_level = ("MEDIUM" if syn["p5"] < 0.8 * ref["p5"] else "LOW")
        else:
            p5_level = "LOW"
        dcr_res = DCRResult(
            min_dcr=round(syn["min"], 4),
            mean_dcr=round(float(np.mean(syn["d1"])), 4),
            percentile_5th=round(syn["p5"], 4),
            identical_matches=syn["identical"],
            risk_level=_worst(identical_level, p5_level),
            identical_rate=round(syn["identical_rate"], 4),
            baseline_min_dcr=round(ref["min"], 4),
            baseline_percentile_5th=round(ref["p5"], 4),
            baseline_identical_rate=round(ref["identical_rate"], 4),
        )

        nndr_res = NNDRResult(
            mean_nndr=round(float(np.mean(syn["ratio"])), 4),
            median_nndr=round(float(np.median(syn["ratio"])), 4),
            percentile_5th=round(float(np.percentile(syn["ratio"], 5)), 4),
            low_ratio_count=syn["low_count"],
            memorization_risk=_rate_excess_level(syn["low_rate"], ref["low_rate"], n_syn, n_ref,
                                                 high_floor=0.02, medium_floor=0.01),
            low_ratio_rate=round(syn["low_rate"], 4),
            baseline_mean_nndr=round(float(np.mean(ref["ratio"])), 4),
            baseline_low_ratio_rate=round(ref["low_rate"], 4),
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

    def estimate_distribution_divergence(
            self, synth_df: pd.DataFrame, seed_df: pd.DataFrame,
    ) -> Tuple[Optional[float], Dict[str, float]]:
        """Ortak sayısal kolonlarda sentetik ve referans histogramlarının benzerliği.

        Kolon başına Jensen-Shannon mesafesi (log2 tabanı; 0 = aynı histogram,
        1 = hiç örtüşme yok) ve bunların ortalaması döner. Kutular referansın
        20'lik yüzdelik sınırlarıdır, uçlar iki verinin min/max'ına genişletilir.

        Yerini aldığı "empirical epsilon" boş kutularda 1e-4 düzeltmesiyle log
        oranını şişiriyordu (aynı dağılımdan 300'er satır -> 3,19) ve bir
        diferansiyel gizlilik ölçümü gibi adlandırılmıştı. Bu da bir gizlilik
        garantisi değildir; küçük örneklemde aynı dağılım için bile sıfırdan büyüktür.
        """
        from scipy.spatial.distance import jensenshannon

        per_column: Dict[str, float] = {}
        for col in synth_df.columns:
            if col not in seed_df.columns:
                continue
            if not (pd.api.types.is_numeric_dtype(synth_df[col])
                    and pd.api.types.is_numeric_dtype(seed_df[col])):
                continue
            s = synth_df[col].dropna().to_numpy(dtype="float64")
            r = seed_df[col].dropna().to_numpy(dtype="float64")
            if len(s) < 20 or len(r) < 20:
                continue
            low, high = min(s.min(), r.min()), max(s.max(), r.max())
            if low == high:
                per_column[str(col)] = 0.0
                continue
            edges = np.unique(np.quantile(r, np.linspace(0.0, 1.0, 21)))
            edges = np.unique(np.concatenate(([low], edges[1:-1], [high])))
            hist_s, _ = np.histogram(s, bins=edges)
            hist_r, _ = np.histogram(r, bins=edges)
            distance = float(jensenshannon(hist_s, hist_r, base=2))
            per_column[str(col)] = round(0.0 if np.isnan(distance) else distance, 4)

        if not per_column:
            return None, {}
        return round(float(np.mean(list(per_column.values()))), 4), per_column

    def scan_hipaa_identifiers(self, df: pd.DataFrame) -> HIPAAAuditResult:
        """Kolon ADLARINI 18 HIPAA tanımlayıcı desenine, yaş kolonunu 89 kuralına karşı tarar.

        Hücre değerlerine bakılmaz: ilgisiz bir adla saklanan tanımlayıcı
        kaçar, adında desen geçen zararsız bir kolon (``mobile_sessions``)
        işaretlenir.
        """
        found: List[Dict[str, Any]] = []

        for col in df.columns:
            col_str = str(col).lower()
            for key, rule in HIPAA_IDENTIFIER_RULES.items():
                for pattern in rule["patterns"]:
                    if re.search(pattern, col_str):
                        found.append({
                            "column": col,
                            "rule_key": key,
                            "title": t(rule["title_key"]),
                            "category": t(rule["category_key"]),
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
