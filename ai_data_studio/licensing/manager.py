# -*- coding: utf-8 -*-
"""Asymmetric Ed25519 offline-tolerant licensing engine.

Supports offline verification, enterprise air-gapped environments, and
LemonSqueezy / Polar.sh webhook integrations.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from .. import config
from ..i18n import t

log = logging.getLogger(__name__)

# Master Ed25519 public key (embedded into client for offline verification).
# Rotated 2026-09-18: the previous key pair's private half had been committed
# alongside the test-suite, so any holder of the repository could mint valid
# licenses. The matching private key now lives only in the release secret store
# and must never appear in this repository or its tests.
DEFAULT_PUBLIC_KEY = "o66ER5nGBFNT7Ks12CLne1sViJHwH+P2O6jKwFkbimE="
# Uygulamanin geri kalani config.KEYRING_SERVICE ("AIDataStudio") kullaniyor.
# Lisans modulu kendi adini tasiyordu, yani kullanicinin kimlik deposunda
# iki ayri giris olusuyordu ve bir "tum verileri sil" akisi birini kaciriyordu.
KEYRING_SERVICE = config.KEYRING_SERVICE
# 2.0.0 oncesi surumlerin yazdigi ad; okurken hala denenir ve tasinir.
LEGACY_KEYRING_SERVICE = "ai_data_studio"
KEYRING_LICENSE_KEY = "license_token"
SETTINGS_LICENSE_KEY = "license_token"


class LicenseTier(str, Enum):
    COMMUNITY = "community"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class LicenseStatus(str, Enum):
    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"
    MISSING = "missing"


class ProFeatureRequiredError(RuntimeError):
    """Raised when an operation requires an active Pro or Enterprise license."""
    def __init__(self, feature: str = "Pro"):
        self.feature = feature
        super().__init__(t("license.error.pro_required", feature=feature))


@dataclass
class LicenseInfo:
    """Decoded and verified license information."""
    key: str = ""
    email: str = ""
    tier: LicenseTier = LicenseTier.COMMUNITY
    features: List[str] = field(default_factory=list)
    issued_at: Optional[str] = None
    expires_at: Optional[str] = None
    status: LicenseStatus = LicenseStatus.MISSING
    status_message: str = ""
    seats: int = 1
    # M-2: bagli makine parmak izi. Varsayilan "*" = bagsiz. Katı bir
    # engelleme degil; manifest ve denetim icin beyan edilir.
    machine_id: str = "*"
    # M-1: musteriye ozel rapor imzalama anahtari. Public yarisi ana
    # anahtarla imzalanmis payload'in icinde, private yarisi token'in
    # ucuncu parcasinda ve ASLA rapora gomulmez.
    report_public_key: str = ""
    report_private_key: str = ""
    # Rapora gomulebilen kisim: payload + ana imza. Ozel anahtar icermez.
    public_token: str = ""

    @property
    def is_active(self) -> bool:
        return self.status == LicenseStatus.VALID and self.tier in (LicenseTier.PRO, LicenseTier.ENTERPRISE)

    @property
    def is_pro(self) -> bool:
        return self.is_active and self.tier in (LicenseTier.PRO, LicenseTier.ENTERPRISE)

    @property
    def is_enterprise(self) -> bool:
        return self.is_active and self.tier == LicenseTier.ENTERPRISE

    @property
    def days_remaining(self) -> Optional[int]:
        if not self.expires_at or self.expires_at == "lifetime":
            return None
        try:
            exp = datetime.datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            now = datetime.datetime.now(datetime.timezone.utc)
            delta = exp - now
            return max(0, delta.days)
        except Exception:
            return None

    @property
    def can_sign_reports(self) -> bool:
        """Bu lisans dogrulanabilir rapor imzalayabilir mi?

        Token v1 (tek imzali, rapor anahtari olmayan) lisanslar hala
        gecerlidir; yalnizca imzasiz serh uretirler.
        """
        return bool(self.is_active and self.report_private_key
                    and self.report_public_key)

    def has_feature(self, feature_name: str) -> bool:
        if not self.is_active:
            return False
        if self.tier == LicenseTier.ENTERPRISE:
            return True
        return feature_name in self.features or "*" in self.features


# Iptal listesi paketle birlikte gelir: 7/24 sunucu tutmadan calisan
# offline-first bir CRL. Sizan bir anahtar sonraki surumde buraya girer.
REVOCATION_LIST_PATH = Path(__file__).resolve().parent / "revoked_keys.json"


def load_revoked_keys() -> Set[str]:
    """Paketle gelen iptal listesini okur.

    Liste okunamazsa BOS kume doner: bozuk bir dosya yuzunden butun
    lisanslari kilitlemek, iptal edilmis tek bir anahtari kabul etmekten
    daha kotu bir arizadir.
    """
    try:
        data = json.loads(config.read_text(REVOCATION_LIST_PATH))
    except Exception:
        return set()
    entries = data.get("revoked") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return set()
    keys = set()
    for entry in entries:
        if isinstance(entry, str):
            keys.add(entry)
        elif isinstance(entry, dict) and entry.get("key"):
            keys.add(str(entry["key"]))
    return keys


LICENSE_FILE_PATH = Path(config.APP_DATA_DIR) / ".license"
# Gordugumuz en ileri tarih. Sadece ileri gider; saat bunun gerisine dusmusse
# expires_at denetimi guvenilmez demektir.
LICENSE_SEEN_PATH = Path(config.APP_DATA_DIR) / ".license_seen"

# Mesru saat sapmasi (seyahat, NTP duzeltmesi, sanal makine uykusu) icin pay.
CLOCK_SKEW_TOLERANCE = datetime.timedelta(hours=24)
# Onbellek omru: calisirken dolan bir lisans sonsuza kadar gecerli kalmasin.
CACHE_TTL = datetime.timedelta(minutes=15)


def _migrate_legacy_keyring_entry(kr: Any) -> Optional[str]:
    """Eski servis adi altinda duran lisansi yeni ada tasir.

    2.0.0 oncesinde lisans "ai_data_studio" altinda saklaniyordu; adi
    config.KEYRING_SERVICE ile birlestirirken mevcut kullanicilarin
    lisansini kaybetmemesi icin eski giris okunur ve tasinir.
    """
    try:
        token = kr.get_password(LEGACY_KEYRING_SERVICE, KEYRING_LICENSE_KEY)
    except Exception:
        return None
    if not token:
        return None
    try:
        kr.set_password(KEYRING_SERVICE, KEYRING_LICENSE_KEY, token)
        kr.delete_password(LEGACY_KEYRING_SERVICE, KEYRING_LICENSE_KEY)
        log.info("Migrated license from legacy keyring entry")
    except Exception as exc:  # pragma: no cover - keyring arka ucuna bagli
        log.warning("Could not migrate legacy keyring entry: %s", exc)
    return token


def _write_private(path: Path, content: str) -> None:
    """Lisans token'ini yalnizca sahibin okuyabilecegi izinlerle yazar.

    config.write_text() umask'a tabidir ve POSIX'te 0644 uretir; APP_DATA_DIR
    de 0755 aciliyordu. Keyring'in bulunmadigi ortamlarda (headless Linux,
    Docker, air-gapped sunucu - yani tam da Enterprise hedef kitlesi) ayni
    makinedeki baska bir kullanici token'i okuyup kopyalayabiliyordu.

    Windows'ta os.open'in mod parametresi yok sayilir; koruma oradaki
    %LOCALAPPDATA% ACL kalitimindan gelir.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path.parent, 0o700)
        except OSError as exc:  # pragma: no cover - dosya sistemine bagli
            log.warning("Could not tighten license directory permissions: %s", exc)

    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)

    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError as exc:  # pragma: no cover - dosya sistemine bagli
            log.warning("Could not tighten license file permissions: %s", exc)


def _clock_is_sane(now: datetime.datetime) -> bool:
    """Sistem saatinin geriye alinmadigini dogrular.

    ``expires_at`` denetimi yalnizca duvar saatine bakiyordu, dolayisiyla
    saati geri almak suresi dolmus bir lisansi yeniden gecerli kiliyordu.
    Burada gordugumuz en ileri tarihi saklayip saatin belirgin sekilde
    gerisine dusup dusmedigine bakiyoruz.

    Damga dosyasi kullanicinin yazabildigi bir konumda durur; bu, atlatmayi
    imkansiz KILMAZ, yalnizca maliyetini yukseltir. Kesin cozum sunucu
    tarafinda periyodik dogrulamadir.
    """
    seen: Optional[datetime.datetime] = None
    try:
        seen = datetime.datetime.fromisoformat(
            config.read_text(LICENSE_SEEN_PATH).strip())
    except Exception:
        seen = None

    if seen is not None and seen.tzinfo is None:
        seen = seen.replace(tzinfo=datetime.timezone.utc)

    if seen is not None and now < seen - CLOCK_SKEW_TOLERANCE:
        return False

    if seen is None or now > seen:
        try:
            _write_private(LICENSE_SEEN_PATH, now.isoformat())
        except Exception as exc:  # pragma: no cover - salt okunur disk
            log.warning("Could not update license clock stamp: %s", exc)
    return True



class LicenseManager:
    """Manages offline license validation, storage, and feature gating."""

    def __init__(self, public_key_b64: Optional[str] = None):
        # The trust anchor is the compiled-in key and nothing else. Reading it
        # from the environment made the signature check decorative: setting one
        # variable to a self-generated public key was enough to have the client
        # accept self-signed Enterprise tokens, with no patching involved.
        # public_key_b64 exists for tests, which pass an ephemeral key.
        self._pubkey_b64 = public_key_b64 or DEFAULT_PUBLIC_KEY
        self._public_key = self._load_public_key(self._pubkey_b64)
        self._cached_license: Optional[LicenseInfo] = None
        self._cached_at: Optional[datetime.datetime] = None

    @staticmethod
    def _load_public_key(key_b64: str) -> ed25519.Ed25519PublicKey:
        key_bytes = base64.b64decode(key_b64)
        return ed25519.Ed25519PublicKey.from_public_bytes(key_bytes)

    def verify_token(self, token: str) -> LicenseInfo:
        """Verify and decode a license token offline.

        Format: ``ADS-<base64_json_payload>.<base64_signature>``
        """
        token = token.strip()
        if not token:
            return LicenseInfo(
                status=LicenseStatus.MISSING,
                status_message=t("license.status.missing"),
            )

        # Strip prefix if present
        raw_token = token
        if raw_token.startswith("ADS-"):
            raw_token = raw_token[4:]

        # v1: <payload>.<master_sig>
        # v2: <payload>.<master_sig>.<report_private_key>
        parts = raw_token.split(".")
        if len(parts) not in (2, 3):
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                status_message=t("license.status.invalid_format"),
            )

        payload_b64, sig_b64 = parts[0], parts[1]
        report_private_key = parts[2] if len(parts) == 3 else ""
        try:
            payload_bytes = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
            sig_bytes = base64.urlsafe_b64decode(sig_b64.encode("ascii"))
        except Exception:
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                status_message=t("license.status.invalid_encoding"),
            )

        # Cryptographic Ed25519 signature verification
        try:
            self._public_key.verify(sig_bytes, payload_bytes)
        except InvalidSignature:
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                status_message=t("license.status.signature_failed"),
            )
        except Exception as exc:
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                status_message=str(exc),
            )

        # Parse JSON payload
        try:
            data = json.loads(payload_bytes.decode("utf-8"))
        except Exception:
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                status_message=t("license.status.invalid_payload"),
            )

        key = str(data.get("key", ""))
        email = str(data.get("email", ""))
        tier_str = str(data.get("tier", "community")).lower()
        tier = LicenseTier.ENTERPRISE if tier_str == "enterprise" else (
            LicenseTier.PRO if tier_str == "pro" else LicenseTier.COMMUNITY
        )
        features = list(data.get("features", []))
        machine_id = str(data.get("machine_id", "*") or "*")
        report_public_key = str(data.get("report_public_key", "") or "")
        public_token = "%s.%s" % (payload_b64, sig_b64)
        issued_at = data.get("issued_at")
        expires_at = data.get("expires_at")
        try:
            seats = int(data.get("seats", 1))
        except (TypeError, ValueError):
            # Sayisal olmayan seats eskiden verify_token'dan disari kacip
            # acilista GUI'yi dusuruyordu.
            seats = 1

        def _fail(status: LicenseStatus, message: str) -> LicenseInfo:
            return LicenseInfo(
                key=key,
                email=email,
                tier=tier,
                features=features,
                issued_at=issued_at,
                expires_at=expires_at,
                status=status,
                status_message=message,
                seats=seats,
                machine_id=machine_id,
                report_public_key=report_public_key,
                public_token=public_token,
            )

        # Iptal denetimi imzadan SONRA: iptal edilmis bir anahtar
        # kriptografik olarak gecerli olsa da kabul edilmez.
        if key and key in load_revoked_keys():
            return _fail(LicenseStatus.INVALID,
                         t("license.status.revoked", license_key=key))

        # Sadece ACIK "suresiz" gosterimleri sonsuz sayilir. Onceki kosul
        # falsy olan her seyi (bos liste, 0, False) suresiz kabul ediyordu;
        # bunlar bozuk veridir, sonsuz lisans degil.
        perpetual = (
            expires_at is None
            or (isinstance(expires_at, str)
                and expires_at.strip().lower() in ("", "lifetime"))
        )
        if not perpetual:
            now = datetime.datetime.now(datetime.timezone.utc)

            if not _clock_is_sane(now):
                return _fail(LicenseStatus.INVALID,
                             t("license.status.clock_tampered"))

            try:
                exp = datetime.datetime.fromisoformat(
                    str(expires_at).replace("Z", "+00:00"))
            except (TypeError, ValueError, AttributeError):
                # Ayrıştırılamayan bir sure gecerli SAYILMAZ. Eskiden buradaki
                # `except: pass` bozuk her expires_at'i omurluk yapiyordu.
                return _fail(LicenseStatus.INVALID,
                             t("license.status.bad_expiry"))

            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=datetime.timezone.utc)
            if now > exp:
                return _fail(LicenseStatus.EXPIRED,
                             t("license.status.expired", date=expires_at))

        return LicenseInfo(
            key=key,
            email=email,
            tier=tier,
            features=features,
            issued_at=issued_at,
            expires_at=expires_at,
            status=LicenseStatus.VALID,
            status_message=t("license.status.valid"),
            seats=seats,
            machine_id=machine_id,
            report_public_key=report_public_key,
            report_private_key=report_private_key,
            public_token=public_token,
        )

    def install_license(self, token: str) -> LicenseInfo:
        """Verify and persist license token in OS keyring or dedicated file."""
        info = self.verify_token(token)
        if info.status != LicenseStatus.VALID:
            return info

        token = token.strip()
        kr = config._keyring()
        stored = False
        if kr is not None:
            try:
                kr.set_password(KEYRING_SERVICE, KEYRING_LICENSE_KEY, token)
                stored = True
            except Exception as exc:
                log.warning("Could not store license in OS keyring: %s", exc)

        if not stored:
            try:
                _write_private(LICENSE_FILE_PATH, token)
                stored = True
            except Exception as exc:
                log.warning("Could not write license file: %s", exc)

        if not stored:
            # Dogrulama gecti ama hicbir yere yazilamadi: kullanici "aktif"
            # gorur, uygulamayi kapatinca lisans kaybolurdu.
            info.status_message = t("license.status.not_persisted")

        self._cached_license = info
        self._cached_at = datetime.datetime.now(datetime.timezone.utc)
        return info

    def remove_license(self) -> None:
        """Remove persisted license."""
        kr = config._keyring()
        if kr is not None:
            try:
                kr.delete_password(KEYRING_SERVICE, KEYRING_LICENSE_KEY)
            except Exception:
                pass

            try:
                kr.delete_password(LEGACY_KEYRING_SERVICE, KEYRING_LICENSE_KEY)
            except Exception:
                pass

        try:
            if LICENSE_FILE_PATH.exists():
                LICENSE_FILE_PATH.unlink()
        except Exception:
            pass

        self._cached_license = None
        self._cached_at = None

    def get_active_license(self, force_reload: bool = False) -> LicenseInfo:
        """Retrieve and verify currently stored license."""
        now = datetime.datetime.now(datetime.timezone.utc)
        fresh = (self._cached_at is not None
                 and datetime.timedelta(0) <= now - self._cached_at < CACHE_TTL)
        if self._cached_license is not None and fresh and not force_reload:
            return self._cached_license
        self._cached_at = now

        token = None
        kr = config._keyring()
        if kr is not None:
            try:
                token = kr.get_password(KEYRING_SERVICE, KEYRING_LICENSE_KEY)
            except Exception:
                pass
            if not token:
                token = _migrate_legacy_keyring_entry(kr)

        if not token and LICENSE_FILE_PATH.exists():
            try:
                token = config.read_text(LICENSE_FILE_PATH).strip()
            except Exception:
                pass

        if not token:
            self._cached_license = LicenseInfo(
                status=LicenseStatus.MISSING,
                status_message=t("license.status.missing"),
            )
            return self._cached_license

        self._cached_license = self.verify_token(token)
        return self._cached_license

    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check whether a specific enterprise feature is enabled."""
        info = self.get_active_license()
        return info.has_feature(feature_name)

    def require_pro(self, feature_name: str = "Pro") -> None:
        """Raise ProFeatureRequiredError if pro/enterprise license is not active."""
        info = self.get_active_license()
        if not info.is_active:
            raise ProFeatureRequiredError(feature_name)


# --------------------------------------------------------------------------- #
# Helper / Server utilities (for LemonSqueezy / Polar.sh / Test key generation)
# --------------------------------------------------------------------------- #

# Lisans URETIMI ve webhook dogrulama artik bu pakette DEGIL.
#
# generate_signed_license() ve webhook dogrulayicilari tools/license_admin.py
# altina tasindi: satici tarafina ait kod, musteriye giden pakette durmamali.
# Ozel anahtar zaten burada degildi, yani bir sizinti yoktu; ama test edilmis,
# hazir bir token uretme araci dagitmak, bir sekilde anahtari ele geciren
# saldirgana ihtiyaci olan son parcayi veriyordu.
#
# Istemci yalnizca DOGRULAR: verify_token() ve licensing.provenance.


# Singleton instance
_GLOBAL_MANAGER: Optional[LicenseManager] = None


def get_license_manager() -> LicenseManager:
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is None:
        _GLOBAL_MANAGER = LicenseManager()
    return _GLOBAL_MANAGER


def is_pro() -> bool:
    return get_license_manager().get_active_license().is_pro


def is_enterprise() -> bool:
    return get_license_manager().get_active_license().is_enterprise
