# -*- coding: utf-8 -*-
"""Offline-verifiable provenance signing.

A generated dataset carries a declaration: how many rows, which seed, whether
a privacy audit ran, and a SHA-256 of the data itself. On its own that
declaration proves nothing — anyone can retype it.

This module gives it a chain of trust that needs no server:

    master key (ours, offline)
        signs the licence payload, which contains report_public_key
            report_public_key verifies the report signature
                the report signature covers the declaration, including
                the dataset digest

An auditor runs ``ai-data-studio verify-report <file>`` and checks all of it
locally: the licence really was issued by us, the declaration really was
signed by that licence, and the data really is the data described. No network
call, which is the point for air-gapped deployments.

What the customer's private report key never touches is the report itself.
Only ``public_token`` (payload + master signature) is embedded, so handing a
signed report to an auditor does not hand them the licence.
"""
from __future__ import annotations

import base64
import datetime
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from ..i18n import t
from .manager import (
    DEFAULT_PUBLIC_KEY,
    LicenseInfo,
    LicenseStatus,
    LicenseTier,
    load_revoked_keys,
)

log = logging.getLogger(__name__)

__all__ = [
    "ProvenanceVerification",
    "SIGNATURE_FIELD",
    "canonical_bytes",
    "sign_provenance",
    "verify_provenance",
]

# İmzanın kendisi imzalanan gövdeye dahil edilemez; bu alan hariç tutulur.
SIGNATURE_FIELD = "signature"
# İmza şeması sürümü: ileride algoritma değişirse doğrulayıcı ayırt edebilsin.
SIGNATURE_SCHEME = "ads-ed25519-v1"


def canonical_bytes(fields: Dict[str, Any]) -> bytes:
    """İmzalanacak gövdeyi belirlenimci bir bayt dizisine çevirir.

    ``sort_keys`` ve ayraçların sabitlenmesi şart: aynı sözlük farklı
    sıralamayla farklı baytlara çevrilirse imza bir makinede doğrulanıp
    diğerinde doğrulanmaz.
    """
    body = {k: v for k, v in fields.items() if k != SIGNATURE_FIELD}
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sign_provenance(fields: Dict[str, Any],
                    info: Optional[LicenseInfo]) -> Dict[str, Any]:
    """Serh alanlarına lisans kimliğini ve rapor imzasını ekler.

    Lisans yoksa, süresi dolmuşsa ya da eski (v1) bir token'sa alanlar
    **değiştirilmeden** döner: imzasız bir serh, sahte imzalı bir serhten
    iyidir. Çağıran ``signature`` alanının varlığına bakarak ayırt edebilir.
    """
    if info is None or not info.can_sign_reports:
        return dict(fields)

    signed = dict(fields)
    signed["license_key"] = info.key
    signed["license_tier"] = info.tier.value
    signed["license_token"] = info.public_token
    signed["signature_scheme"] = SIGNATURE_SCHEME
    if info.machine_id and info.machine_id != "*":
        signed["machine_id"] = info.machine_id

    try:
        private = ed25519.Ed25519PrivateKey.from_private_bytes(
            base64.b64decode(info.report_private_key))
        signature = private.sign(canonical_bytes(signed))
    except Exception as exc:  # pragma: no cover - bozuk anahtar
        log.warning("Could not sign provenance: %s", exc)
        return dict(fields)

    signed[SIGNATURE_FIELD] = base64.b64encode(signature).decode("ascii")
    return signed


@dataclass
class ProvenanceVerification:
    """``verify_provenance`` sonucu; her denetim ayrı ayrı raporlanır."""

    signed: bool = False
    license_valid: bool = False
    signature_valid: bool = False
    content_matches: Optional[bool] = None   # None = veri dosyası verilmedi
    revoked: bool = False
    license_key: str = ""
    license_tier: str = ""
    email: str = ""
    expires_at: Optional[str] = None
    declared_digest: str = ""
    actual_digest: str = ""
    machine_id: str = "*"
    problems: List[str] = field(default_factory=list)
    fields: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Yalnızca denetlenen her şey geçtiyse True."""
        return (self.signed and self.license_valid and self.signature_valid
                and not self.revoked and self.content_matches is not False)

    def summary_lines(self) -> List[str]:
        """İnsan tarafından okunacak özet."""
        mark = lambda ok: "PASS" if ok else "FAIL"  # noqa: E731
        lines = []
        if not self.signed:
            lines.append("%s  %s" % (mark(False), t("verify.result.unsigned")))
            return lines
        lines.append("%s  %s" % (mark(self.license_valid),
                                 t("verify.result.license", license_key=self.license_key,
                                   tier=self.license_tier.upper())))
        if self.revoked:
            lines.append("%s  %s" % (mark(False), t("verify.result.revoked")))
        lines.append("%s  %s" % (mark(self.signature_valid),
                                 t("verify.result.signature")))
        if self.content_matches is None:
            lines.append("      %s" % t("verify.result.content_unchecked",
                                        digest=self.declared_digest[:16]))
        else:
            lines.append("%s  %s" % (mark(self.content_matches),
                                     t("verify.result.content")))
        for problem in self.problems:
            lines.append("      %s" % problem)
        return lines


def _decode_public_token(token: str):
    """``<payload>.<master_sig>`` çiftini çözer ve ana anahtarla doğrular."""
    parts = str(token or "").split(".")
    if len(parts) < 2:
        raise ValueError(t("verify.error.token_format"))
    payload = base64.urlsafe_b64decode(parts[0].encode("ascii"))
    signature = base64.urlsafe_b64decode(parts[1].encode("ascii"))

    master = ed25519.Ed25519PublicKey.from_public_bytes(
        base64.b64decode(DEFAULT_PUBLIC_KEY))
    master.verify(signature, payload)     # InvalidSignature fırlatabilir
    return json.loads(payload.decode("utf-8"))


def verify_provenance(fields: Dict[str, Any],
                      actual_digest: Optional[str] = None,
                      ) -> ProvenanceVerification:
    """Bir serh bloğunu tamamen çevrimdışı doğrular.

    Parameters
    ----------
    fields : dict
        Dosyadan okunan ``_provenance`` bloğu.
    actual_digest : str, optional
        Veri dosyasından yeniden hesaplanan SHA-256. Verilmezse içerik
        denetimi atlanır ve ``content_matches`` None kalır.
    """
    result = ProvenanceVerification(fields=dict(fields))
    result.declared_digest = str(fields.get("content_sha256", "") or "")
    result.actual_digest = actual_digest or ""

    if not fields.get(SIGNATURE_FIELD) or not fields.get("license_token"):
        result.problems.append(t("verify.error.unsigned"))
        return result
    result.signed = True

    # 1. Lisans gerçekten bizim ana anahtarımızla mı imzalanmış?
    try:
        payload = _decode_public_token(str(fields["license_token"]))
        result.license_valid = True
    except InvalidSignature:
        result.problems.append(t("verify.error.license_signature"))
        return result
    except Exception as exc:
        result.problems.append(t("verify.error.license_unreadable", error=exc))
        return result

    result.license_key = str(payload.get("key", ""))
    result.license_tier = str(payload.get("tier", ""))
    result.email = str(payload.get("email", ""))
    result.expires_at = payload.get("expires_at")
    result.machine_id = str(payload.get("machine_id", "*") or "*")

    # 2. Anahtar iptal edilmiş mi? (İmza geçerli olsa bile reddedilir.)
    if result.license_key and result.license_key in load_revoked_keys():
        result.revoked = True
        result.problems.append(t("verify.error.revoked", license_key=result.license_key))

    # 3. Serh, o lisansın rapor anahtarıyla mı imzalanmış?
    report_pubkey = str(payload.get("report_public_key", "") or "")
    if not report_pubkey:
        result.problems.append(t("verify.error.no_report_key"))
        return result
    try:
        public = ed25519.Ed25519PublicKey.from_public_bytes(
            base64.b64decode(report_pubkey))
        public.verify(base64.b64decode(str(fields[SIGNATURE_FIELD])),
                      canonical_bytes(fields))
        result.signature_valid = True
    except InvalidSignature:
        result.problems.append(t("verify.error.report_signature"))
        return result
    except Exception as exc:
        result.problems.append(t("verify.error.report_unreadable", error=exc))
        return result

    # 4. Beyan edilen özet gerçekten bu veriye mi ait?
    if actual_digest is not None:
        result.content_matches = (result.declared_digest == actual_digest)
        if not result.content_matches:
            result.problems.append(t("verify.error.content_mismatch"))

    return result
