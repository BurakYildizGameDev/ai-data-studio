# -*- coding: utf-8 -*-
"""Licence issuing and webhook verification — SELLER SIDE ONLY.

This module is deliberately outside the ``ai_data_studio`` package. It is not
imported by the application, not bundled by ``build_exe.py`` and not shipped
to customers. It belongs wherever fulfilment runs: a laptop, a CI job, a
LemonSqueezy/Polar webhook handler.

Why the split: ``generate_signed_license`` used to sit next to the verifier in
the client package. The private key was never there, so nothing leaked, but
shipping a tested, ready-made minting tool to every customer hands an attacker
the exact function they need the moment they get a key from anywhere else.

The signing key lives only in your secret store. Pass it through
``ADS_LICENSE_PRIVATE_KEY`` or ``--private-key``; never commit it, never put
it in a test.

Usage
-----
    # A one-year Pro licence
    python tools/license_admin.py issue \\
        --key ADS-PRO-00042 --email customer@example.com \\
        --tier pro --days 365

    # A perpetual Enterprise licence, declared against one machine
    python tools/license_admin.py issue \\
        --key ADS-ENT-00007 --email ops@bank.example --tier enterprise \\
        --lifetime --seats 25 --machine-id 3f8c...

    # Revoke a leaked key (writes the list that ships with the client)
    python tools/license_admin.py revoke --key ADS-PRO-00042 \\
        --reason "refunded"
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

ENV_PRIVATE_KEY = "ADS_LICENSE_PRIVATE_KEY"
REVOCATION_LIST_PATH = (Path(__file__).resolve().parent.parent
                        / "ai_data_studio" / "licensing" / "revoked_keys.json")

WEBHOOK_TOLERANCE_S = 300


# --------------------------------------------------------------------------- #
# Key material
# --------------------------------------------------------------------------- #

def generate_master_keypair() -> Dict[str, str]:
    """Create a fresh master keypair.

    The public half is compiled into the client as DEFAULT_PUBLIC_KEY; the
    private half goes to the secret store and nowhere else.
    """
    private = ed25519.Ed25519PrivateKey.generate()
    return {
        "private_key": base64.b64encode(private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption())).decode("ascii"),
        "public_key": base64.b64encode(private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw)).decode("ascii"),
    }


def _report_keypair() -> Dict[str, str]:
    """Per-customer keypair used to sign that customer's reports.

    The public half is embedded in the signed payload, so a verifier can trust
    it. The private half travels in the token's third segment and is never
    written into a report.
    """
    return generate_master_keypair()


# --------------------------------------------------------------------------- #
# Licence issuing
# --------------------------------------------------------------------------- #

def generate_signed_license(payload: Dict[str, Any],
                            private_key_b64: str,
                            *,
                            with_report_key: bool = True) -> str:
    """Sign a licence payload with Ed25519 and return an ADS token.

    Format
    ------
    v1 ``ADS-<payload>.<signature>``
        Legacy; the client still accepts it but such a licence cannot sign
        reports.
    v2 ``ADS-<payload>.<signature>.<report_private_key>``
        The payload carries ``report_public_key``; the third segment carries
        its private half. Only the first two segments are ever embedded in a
        report, so sharing a signed report does not share the licence.
    """
    payload = dict(payload)
    report_private = ""
    if with_report_key:
        keys = _report_keypair()
        payload["report_public_key"] = keys["public_key"]
        report_private = keys["private_key"]

    private = ed25519.Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(private_key_b64))
    payload_bytes = json.dumps(payload, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")
    signature = private.sign(payload_bytes)

    token = "ADS-%s.%s" % (
        base64.urlsafe_b64encode(payload_bytes).decode("ascii"),
        base64.urlsafe_b64encode(signature).decode("ascii"),
    )
    if report_private:
        token += "." + report_private
    return token


def build_payload(key: str, email: str, tier: str, *,
                  days: Optional[int] = None,
                  lifetime: bool = False,
                  seats: int = 1,
                  features: Optional[list] = None,
                  machine_id: str = "*") -> Dict[str, Any]:
    """Assemble a licence payload.

    ``machine_id`` defaults to ``"*"`` (unbound). A fingerprint here is a
    declaration that lands in the manifest and in audits — the client does not
    refuse to run on another machine, because a developer moving between a
    laptop and a desktop is a customer, not an attacker.
    """
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    if lifetime:
        expires_at: Any = "lifetime"
    elif days:
        expires_at = (now + datetime.timedelta(days=days)).isoformat()
    else:
        raise SystemExit("either --days or --lifetime is required")

    return {
        "key": key,
        "email": email,
        "tier": tier,
        "features": features or (["*"] if tier == "enterprise" else ["audit_pdf"]),
        "issued_at": now.isoformat(),
        "expires_at": expires_at,
        "seats": int(seats),
        "machine_id": machine_id,
    }


# --------------------------------------------------------------------------- #
# Webhook verification (LemonSqueezy / Polar)
# --------------------------------------------------------------------------- #

def _within_replay_window(timestamp: Any, tolerance_s: int) -> bool:
    try:
        sent = int(timestamp)
    except (TypeError, ValueError):
        return False
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    return abs(now - sent) <= tolerance_s


ENTERPRISE_MARKERS = ("enterprise", "business", "team")


def payload_from_lemonsqueezy_order(event: Dict[str, Any], *,
                                    days: Optional[int] = 365,
                                    lifetime: bool = False,
                                    allow_test_mode: bool = False) -> Dict[str, Any]:
    """Turn an ``order_created`` webhook into a licence payload.

    This is the fulfilment step: webhook arrives -> signature verified ->
    payload built here -> :func:`generate_signed_license` mints the token ->
    the token is emailed to the buyer.

    Test-mode orders are REFUSED unless *allow_test_mode* is passed. LemonSqueezy
    sends real-looking ``order_created`` events from its test mode, and a
    fulfilment handler that cannot tell them apart mints perfectly valid
    lifetime licences for orders that were never paid.

    The tier comes from ``meta.custom_data.tier`` when the checkout sets it, and
    otherwise from the product/variant name, so a store that only renames its
    products keeps working.
    """
    meta = event.get("meta") or {}
    if str(meta.get("event_name") or "") != "order_created":
        raise ValueError("not an order_created event: %r" % meta.get("event_name"))
    if bool(meta.get("test_mode")) and not allow_test_mode:
        raise ValueError(
            "test-mode order refused; pass allow_test_mode=True to mint from it")

    data = event.get("data") or {}
    attributes = data.get("attributes") or {}
    email = str(attributes.get("user_email") or "").strip()
    if not email:
        raise ValueError("the order carries no user_email")

    first_item = attributes.get("first_order_item") or {}
    custom = meta.get("custom_data") or {}
    named = " ".join(str(x) for x in (
        custom.get("tier", ""), first_item.get("product_name", ""),
        first_item.get("variant_name", ""),
    )).lower()
    tier = "enterprise" if any(m in named for m in ENTERPRISE_MARKERS) else "pro"

    order_number = attributes.get("order_number") or attributes.get("identifier") or "0"
    try:
        suffix = "%05d" % int(order_number)
    except (TypeError, ValueError):
        # UUID gibi sayisal olmayan tanimlayicilar: ilk 8 karakter yeter.
        suffix = str(order_number).replace("-", "")[:8].upper()

    try:
        seats = max(1, int(first_item.get("quantity") or 1))
    except (TypeError, ValueError):
        seats = 1

    return build_payload(
        "ADS-%s-%s" % (tier.upper(), suffix),
        email,
        tier,
        days=None if lifetime else days,
        lifetime=lifetime,
        seats=seats,
    )


def verify_lemonsqueezy_webhook(payload_bytes: bytes, signature_header: str,
                                webhook_secret: str, *,
                                timestamp: Optional[Any] = None,
                                tolerance_s: int = WEBHOOK_TOLERANCE_S) -> bool:
    """Verify a LemonSqueezy HMAC-SHA256 signature (hex digest of the body)."""
    if not signature_header or not webhook_secret:
        return False
    if timestamp is not None and not _within_replay_window(timestamp, tolerance_s):
        return False
    mac = hmac.new(webhook_secret.encode("utf-8"), msg=payload_bytes,
                   digestmod=hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), signature_header)


def verify_polar_webhook(payload_bytes: bytes, signature_header: str,
                         webhook_secret: str, *, msg_id: str, timestamp: Any,
                         tolerance_s: int = WEBHOOK_TOLERANCE_S) -> bool:
    """Verify a Polar.sh (Svix) signature.

    Svix signs ``{id}.{timestamp}.{body}``, returns base64, and may send
    several space-separated signatures during key rotation.
    """
    if not signature_header or not webhook_secret or not msg_id:
        return False
    if not _within_replay_window(timestamp, tolerance_s):
        return False

    secret = webhook_secret
    if secret.startswith("whsec_"):
        secret = secret[len("whsec_"):]
    try:
        key = base64.b64decode(secret)
    except Exception:
        return False
    if not key:
        return False

    signed = b".".join((str(msg_id).encode("utf-8"),
                        str(timestamp).encode("utf-8"), payload_bytes))
    expected = base64.b64encode(
        hmac.new(key, msg=signed, digestmod=hashlib.sha256).digest()
    ).decode("ascii")

    matched = False
    for candidate in signature_header.split():
        version, _, value = candidate.partition(",")
        if version == "v1" and hmac.compare_digest(expected, value):
            matched = True     # no break: keep the comparison constant time
    return matched


# --------------------------------------------------------------------------- #
# Revocation list
# --------------------------------------------------------------------------- #

def revoke_key(key: str, reason: str = "") -> Path:
    """Add a key to the revocation list that ships with the client."""
    try:
        data = json.loads(REVOCATION_LIST_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {"revoked": []}

    entries = data.setdefault("revoked", [])
    if any(isinstance(e, dict) and e.get("key") == key or e == key
           for e in entries):
        print("%s is already revoked" % key)
        return REVOCATION_LIST_PATH

    entries.append({
        "key": key,
        "reason": reason,
        "revoked_at": datetime.datetime.now(
            datetime.timezone.utc).replace(microsecond=0).isoformat(),
    })
    data["updated_at"] = datetime.date.today().isoformat()
    REVOCATION_LIST_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return REVOCATION_LIST_PATH


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _resolve_private_key(explicit: Optional[str]) -> str:
    key = explicit or os.getenv(ENV_PRIVATE_KEY, "")
    if not key:
        raise SystemExit(
            "No signing key. Set %s or pass --private-key. The key belongs in "
            "your secret store, never in this repository." % ENV_PRIVATE_KEY)
    return key


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="license_admin",
        description="Issue and revoke AI Synthetic Data Studio licences (seller side).")
    sub = parser.add_subparsers(dest="command", required=True)

    issue = sub.add_parser("issue", help="issue a signed licence token")
    issue.add_argument("--key", required=True, help="licence key, e.g. ADS-PRO-00042")
    issue.add_argument("--email", required=True)
    issue.add_argument("--tier", choices=("pro", "enterprise"), default="pro")
    issue.add_argument("--days", type=int, help="validity in days")
    issue.add_argument("--lifetime", action="store_true")
    issue.add_argument("--seats", type=int, default=1)
    issue.add_argument("--machine-id", default="*",
                       help='machine fingerprint to declare; "*" (default) is unbound')
    issue.add_argument("--private-key", help="base64 signing key (prefer the env var)")
    issue.add_argument("--no-report-key", action="store_true",
                       help="issue a v1 token that cannot sign reports")

    fulfil = sub.add_parser(
        "fulfil", help="verify a LemonSqueezy webhook body and mint the licence")
    fulfil.add_argument("--body", required=True,
                        help="file holding the RAW webhook body (bytes as received)")
    fulfil.add_argument("--signature", required=True,
                        help="the X-Signature header value")
    fulfil.add_argument("--webhook-secret", default=os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", ""),
                        help="store webhook secret (or LEMONSQUEEZY_WEBHOOK_SECRET)")
    fulfil.add_argument("--days", type=int, default=365)
    fulfil.add_argument("--lifetime", action="store_true")
    fulfil.add_argument("--allow-test-mode", action="store_true",
                        help="mint from a LemonSqueezy TEST-mode order (dry runs only)")
    fulfil.add_argument("--private-key", default="")

    keygen = sub.add_parser("keygen", help="generate a new master keypair")
    keygen.add_argument("--out", help="write the private key to this file")

    revoke = sub.add_parser("revoke", help="add a key to the revocation list")
    revoke.add_argument("--key", required=True)
    revoke.add_argument("--reason", default="")

    args = parser.parse_args(argv)

    if args.command == "keygen":
        keys = generate_master_keypair()
        print("public  (embed as DEFAULT_PUBLIC_KEY): %s" % keys["public_key"])
        if args.out:
            target = Path(args.out)
            target.write_text(keys["private_key"] + "\n", encoding="utf-8")
            if os.name != "nt":
                os.chmod(target, 0o600)
            print("private (keep secret) written to: %s" % target)
        else:
            print("private (keep secret): %s" % keys["private_key"])
        return 0

    if args.command == "revoke":
        path = revoke_key(args.key, args.reason)
        print("Revoked %s. Ship %s with the next release." % (args.key, path))
        return 0

    if args.command == "fulfil":
        # Govde HAM okunur: imza baytlarin uzerinde hesaplandi, JSON'i yeniden
        # bicimlendirmek imzayi bozar.
        body = Path(args.body).read_bytes()
        if not args.webhook_secret:
            raise SystemExit(
                "No webhook secret. Pass --webhook-secret or set "
                "LEMONSQUEEZY_WEBHOOK_SECRET.")
        if not verify_lemonsqueezy_webhook(body, args.signature, args.webhook_secret):
            print("Signature does NOT match; nothing was minted.", file=sys.stderr)
            return 1
        try:
            payload = payload_from_lemonsqueezy_order(
                json.loads(body.decode("utf-8")),
                days=args.days, lifetime=args.lifetime,
                allow_test_mode=args.allow_test_mode)
        except ValueError as exc:
            # Kullanicinin gorecegi sey bir traceback degil, ne yapmasi
            # gerektigi olmali: bu komut satici tarafinda elle kosuluyor.
            print("Refused: %s" % exc, file=sys.stderr)
            return 2
        token = generate_signed_license(payload, _resolve_private_key(args.private_key))
        print("# %s  %s  seats=%s" % (payload["key"], payload["email"], payload["seats"]))
        print(token)
        return 0

    payload = build_payload(
        args.key, args.email, args.tier,
        days=args.days, lifetime=args.lifetime, seats=args.seats,
        machine_id=args.machine_id)
    token = generate_signed_license(
        payload, _resolve_private_key(args.private_key),
        with_report_key=not args.no_report_key)
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
