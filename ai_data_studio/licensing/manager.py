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
ENV_PUBLIC_KEY = "AI_DATA_STUDIO_LICENSE_PUBKEY"
KEYRING_SERVICE = "ai_data_studio"
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

    def has_feature(self, feature_name: str) -> bool:
        if not self.is_active:
            return False
        if self.tier == LicenseTier.ENTERPRISE:
            return True
        return feature_name in self.features or "*" in self.features


LICENSE_FILE_PATH = Path(config.APP_DATA_DIR) / ".license"


class LicenseManager:
    """Manages offline license validation, storage, and feature gating."""

    def __init__(self, public_key_b64: Optional[str] = None):
        self._pubkey_b64 = (
            public_key_b64
            or os.getenv(ENV_PUBLIC_KEY)
            or DEFAULT_PUBLIC_KEY
        )
        self._public_key = self._load_public_key(self._pubkey_b64)
        self._cached_license: Optional[LicenseInfo] = None

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

        parts = raw_token.split(".")
        if len(parts) != 2:
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                status_message=t("license.status.invalid_format"),
            )

        payload_b64, sig_b64 = parts
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
        issued_at = data.get("issued_at")
        expires_at = data.get("expires_at")
        seats = int(data.get("seats", 1))

        # Check expiration date
        if expires_at and expires_at != "lifetime":
            try:
                exp = datetime.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                now = datetime.datetime.now(datetime.timezone.utc)
                if now > exp:
                    return LicenseInfo(
                        key=key,
                        email=email,
                        tier=tier,
                        features=features,
                        issued_at=issued_at,
                        expires_at=expires_at,
                        status=LicenseStatus.EXPIRED,
                        status_message=t("license.status.expired", date=expires_at),
                        seats=seats,
                    )
            except Exception:
                pass

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
                config.write_text(LICENSE_FILE_PATH, token)
            except Exception as exc:
                log.warning("Could not write license file: %s", exc)

        self._cached_license = info
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
            if LICENSE_FILE_PATH.exists():
                LICENSE_FILE_PATH.unlink()
        except Exception:
            pass

        self._cached_license = None

    def get_active_license(self, force_reload: bool = False) -> LicenseInfo:
        """Retrieve and verify currently stored license."""
        if self._cached_license is not None and not force_reload:
            return self._cached_license

        token = None
        kr = config._keyring()
        if kr is not None:
            try:
                token = kr.get_password(KEYRING_SERVICE, KEYRING_LICENSE_KEY)
            except Exception:
                pass

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

def generate_signed_license(payload: Dict[str, Any], private_key_b64: str) -> str:
    """Generate a cryptographically signed ADS license token using Ed25519.

    Used by LemonSqueezy / Polar.sh webhook handlers or CLI admin scripts.
    """
    priv_bytes = base64.b64decode(private_key_b64)
    priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)

    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload_bytes = payload_json.encode("utf-8")

    signature = priv_key.sign(payload_bytes)

    p_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii")
    s_b64 = base64.urlsafe_b64encode(signature).decode("ascii")
    return f"ADS-{p_b64}.{s_b64}"


def verify_lemonsqueezy_webhook(payload_bytes: bytes, signature_header: str, webhook_secret: str) -> bool:
    """Verify LemonSqueezy webhook HMAC-SHA256 signature."""
    if not signature_header or not webhook_secret:
        return False
    mac = hmac.new(webhook_secret.encode("utf-8"), msg=payload_bytes, digestmod=hashlib.sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature_header)


def verify_polar_webhook(payload_bytes: bytes, signature_header: str, webhook_secret: str) -> bool:
    """Verify Polar.sh webhook signature (Svix/HMAC-SHA256 style)."""
    if not signature_header or not webhook_secret:
        return False
    # Standard HMAC-SHA256 check
    mac = hmac.new(webhook_secret.encode("utf-8"), msg=payload_bytes, digestmod=hashlib.sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(expected, signature_header.replace("v1,", ""))


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
