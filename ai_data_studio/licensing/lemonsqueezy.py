# -*- coding: utf-8 -*-
"""Lemon Squeezy license-key activation - the second, ONLINE licence path.

With the store's "License keys" feature switched on, the buyer receives a bare
UUID (``296B8F04-E41C-4228-8B42-3FC9D762E417``) instead of the signed ADS token
this application was built around. There is nothing inside such a key to check:
no payload, no signature, nothing but 32 hex digits. The only party that knows
whether it was ever paid for is Lemon Squeezy, so verifying it REQUIRES a call
to their API.

That is why this module exists instead of a wider regular expression in
:mod:`.manager`. Treating "looks like a UUID" as "is licensed" would not fix
the format check, it would delete the licence: any user could type 32 hex
digits and unlock Pro.

ADS tokens keep working exactly as before - verified offline against the
compiled-in Ed25519 key, which is what air-gapped Enterprise installs rely on.
The two paths live side by side; only the shape of the pasted string decides
which one runs.
"""
from __future__ import annotations

import datetime
import logging
import os
import re
from typing import Any, Dict, Optional

from ..i18n import t

log = logging.getLogger(__name__)

PROVIDER = "lemonsqueezy"
API_BASE = "https://api.lemonsqueezy.com/v1/licenses"

# Kisa tutuldu: bayatlamis bir kaydin yeniden dogrulanmasi acilis yolunda
# calisiyor, paketleri sessizce yutan bir sebeke arayuzu kilitlememeli.
HTTP_TIMEOUT = (5, 10)

# Bu kurulumun kabul ettigi magaza ve urun.
#
# GOMULU ve ayarlanabilir DEGIL. /v1/licenses/validate butun Lemon Squeezy
# magazalarindaki anahtarlara bakar; bu denetim olmadan baska bir magazadan
# alinmis bir dolarlik herhangi bir anahtar burada Pro aciyor olurdu. Gerekce
# DEFAULT_PUBLIC_KEY'inkiyle ayni: ortam degiskeninden okunan bir guven capasi
# guven capasi degildir.
STORE_ID = 477942
PRODUCT_IDS = frozenset({1372277})

# Test modundaki siparisler odenmez. Satici tarafi bunlari zaten reddediyor
# (bkz. tools/license_admin.py, payload_from_lemonsqueezy_order); istemci de
# reddetmezse magaza test modundayken ucretsiz Pro dagitilmis olur. Kendi
# magazanizi denerken GECICI olarak acilir, dagitilan yapida asla acik
# birakilmaz.
TEST_MODE_ENV = "ADS_LICENSE_ALLOW_TEST_MODE"

# tools/license_admin.py ayni listeyi tasiyor. Kasitli kopya: o arac satici
# tarafinda, bu paket kurulu olmadan bir webhook sunucusunda calisabilmeli.
ENTERPRISE_MARKERS = ("enterprise", "business", "team")

# 8-4-4-4-12 onaltilik, buyuk/kucuk harf duyarsiz.
LICENSE_KEY_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class LemonSqueezyError(RuntimeError):
    """A key the store refused, or a store we could not reach.

    ``transient`` separates those two: a refusal is an answer and must
    invalidate the licence, a timeout is not an answer and must not.
    Conflating them either locks out paying customers on a flaky connection
    or keeps refunded keys alive forever.
    """

    def __init__(self, message_key: str, *, transient: bool = False, **fmt: Any):
        self.message_key = message_key
        self.transient = transient
        self.fmt = fmt
        super().__init__(message_key)

    def localized(self) -> str:
        return t(self.message_key, **self.fmt)


def looks_like_license_key(text: str) -> bool:
    """Is this a Lemon Squeezy license key rather than an ADS token?"""
    return bool(LICENSE_KEY_RE.match((text or "").strip()))


def test_mode_allowed() -> bool:
    allowed = str(os.getenv(TEST_MODE_ENV, "")).strip().lower() in (
        "1", "true", "yes", "on")
    if allowed:
        log.warning(
            "%s is set: Lemon Squeezy TEST-mode licence keys will be accepted. "
            "Unset it before shipping a build.", TEST_MODE_ENV)
    return allowed


def mask(license_key: str) -> str:
    """``296B8F04-...-E417`` - safe to show in a window or write to a log."""
    key = (license_key or "").strip()
    if len(key) < 12:
        return "?"
    return "%s-...-%s" % (key[:8], key[-4:])


def tier_for(*names: Any) -> str:
    blob = " ".join(str(name or "") for name in names).lower()
    return "enterprise" if any(m in blob for m in ENTERPRISE_MARKERS) else "pro"


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _post(endpoint: str, payload: Dict[str, str]) -> Dict[str, Any]:
    try:
        import requests  # gec import: lisans paketi acilista requests'i cekmesin
    except ImportError as exc:  # pragma: no cover - requirements.txt'te var
        raise LemonSqueezyError("license.status.ls_offline", transient=True) from exc

    try:
        response = requests.post(
            "%s/%s" % (API_BASE, endpoint),
            data=payload,
            headers={"Accept": "application/json"},
            timeout=HTTP_TIMEOUT,
        )
    except Exception as exc:
        log.warning("Lemon Squeezy %s call failed: %s", endpoint, exc)
        raise LemonSqueezyError("license.status.ls_offline", transient=True) from exc

    # 5xx bir hukum degil, bir ariza. Magazanin cokmesi musterinin lisansini
    # dusurmemeli, bu yuzden gecici sayilir.
    if response.status_code >= 500:
        raise LemonSqueezyError("license.status.ls_offline", transient=True)

    try:
        body = response.json()
    except ValueError as exc:
        raise LemonSqueezyError("license.status.ls_unreadable") from exc
    if not isinstance(body, dict):
        raise LemonSqueezyError("license.status.ls_unreadable")
    return body


def _record_from(body: Dict[str, Any], *, flag: str) -> Dict[str, Any]:
    """Turn an activate/validate response into the record we persist.

    Every refusal reason is raised as :class:`LemonSqueezyError`, so the caller
    has one thing to catch and the dialog gets a sentence worth reading.
    """
    error = body.get("error")
    if error or not body.get(flag):
        raise LemonSqueezyError(
            "license.status.ls_rejected",
            reason=str(error).strip() if error else t("license.status.ls_no_reason"))

    key_obj = body.get("license_key") or {}
    meta = body.get("meta") or {}
    instance = body.get("instance") or {}

    # Kapsam denetimi her seyden once: baska bir magazanin anahtari burada
    # gecerli degildir, kendi magazasinda ne kadar gecerli olursa olsun.
    store_id = _as_int(meta.get("store_id"))
    product_id = _as_int(meta.get("product_id"))
    if store_id != STORE_ID or product_id not in PRODUCT_IDS:
        log.warning("Licence key from a foreign store/product: store=%s product=%s",
                    store_id, product_id)
        raise LemonSqueezyError("license.status.ls_wrong_store")

    if bool(key_obj.get("test_mode")) and not test_mode_allowed():
        raise LemonSqueezyError("license.status.ls_test_mode")

    status = str(key_obj.get("status") or "").strip().lower()
    if status in ("expired", "disabled"):
        raise LemonSqueezyError("license.status.ls_rejected", reason=status)

    key_id = _as_int(key_obj.get("id")) or 0
    expires_at = key_obj.get("expires_at")
    return {
        "v": 1,
        "provider": PROVIDER,
        "key": str(key_obj.get("key") or ""),
        # Rapora ve saglamaya gecen kimlik BU: ham anahtar bir paroladir,
        # paylasilan bir denetim raporunda isi yok (bkz. provenance.py).
        "key_id": key_id,
        "public_key_id": "ADS-LS-%05d" % key_id,
        "instance_id": str(instance.get("id") or ""),
        "tier": tier_for(meta.get("variant_name"), meta.get("product_name")),
        "email": str(meta.get("customer_email") or ""),
        "issued_at": key_obj.get("created_at"),
        # LS'te null "suresiz" demek; manager.py bu gosterimi zaten biliyor.
        "expires_at": expires_at if expires_at else "lifetime",
        "seats": max(1, _as_int(key_obj.get("activation_limit")) or 1),
        "store_id": store_id,
        "product_id": product_id,
        "test_mode": bool(key_obj.get("test_mode")),
        "last_validated": _now_iso(),
    }


def _limit_reached(body: Dict[str, Any]) -> bool:
    return "activation limit" in str(body.get("error") or "").lower()


def activate(license_key: str, instance_name: str) -> Dict[str, Any]:
    """Bind the key to this machine and return the record to persist.

    Activation, not validation, is what enforces the seat count: ``/validate``
    alone would let one key run on every machine that pasted it.
    """
    body = _post("activate", {"license_key": license_key.strip(),
                              "instance_name": instance_name})
    if _limit_reached(body):
        key_obj = body.get("license_key") or {}
        raise LemonSqueezyError(
            "license.status.ls_limit_reached",
            used=_as_int(key_obj.get("activation_usage")) or 0,
            limit=_as_int(key_obj.get("activation_limit")) or 0)
    return _record_from(body, flag="activated")


def validate(license_key: str, instance_id: str = "") -> Dict[str, Any]:
    """Re-check a key that is already installed."""
    payload = {"license_key": license_key.strip()}
    if instance_id:
        payload["instance_id"] = instance_id
    return _record_from(_post("validate", payload), flag="valid")


def deactivate(license_key: str, instance_id: str) -> bool:
    """Release this machine's slot. Best effort: never blocks removal.

    Without it, uninstalling and reinstalling burns activations until the
    customer is locked out of a licence they paid for.
    """
    if not instance_id:
        return False
    try:
        body = _post("deactivate", {"license_key": license_key.strip(),
                                    "instance_id": instance_id})
    except LemonSqueezyError as exc:
        log.info("Could not release the licence activation: %s", exc.message_key)
        return False
    return bool(body.get("deactivated"))
