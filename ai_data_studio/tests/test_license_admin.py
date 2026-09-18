# -*- coding: utf-8 -*-
"""Seller-side licence tooling tests (tools/license_admin.py).

This tool is deliberately outside the shipped package: it mints licences and
verifies payment webhooks, neither of which belongs on a customer machine.
The first test pins that separation.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import unittest

from ai_data_studio.licensing import LicenseManager, LicenseStatus
from tools import license_admin as admin


class TestSellerClientSeparation(unittest.TestCase):
    """Uretici kod musteriye giden pakette olmamali."""

    def test_client_package_cannot_mint_licences(self):
        from ai_data_studio.licensing import manager

        for name in ("generate_signed_license", "verify_polar_webhook",
                     "verify_lemonsqueezy_webhook"):
            with self.subTest(symbol=name):
                self.assertFalse(
                    hasattr(manager, name),
                    "%s hala istemci paketinde" % name)

    def test_client_package_still_verifies(self):
        from ai_data_studio import licensing

        for name in ("verify_provenance", "get_license_manager",
                     "load_revoked_keys"):
            with self.subTest(symbol=name):
                self.assertTrue(hasattr(licensing, name))


class TestLicenceIssuing(unittest.TestCase):
    def setUp(self):
        self.master = admin.generate_master_keypair()
        self.mgr = LicenseManager(public_key_b64=self.master["public_key"])

    def test_v2_token_carries_a_report_key(self):
        token = admin.generate_signed_license(
            admin.build_payload("ADS-PRO-1", "a@b.test", "pro", days=30),
            self.master["private_key"])
        self.assertEqual(len(token[4:].split(".")), 3)

        info = self.mgr.verify_token(token)
        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertTrue(info.can_sign_reports)
        # Paylasilabilen kisim ozel anahtari ICERMEMELI.
        self.assertEqual(len(info.public_token.split(".")), 2)
        self.assertNotIn(info.report_private_key, info.public_token)

    def test_v1_token_still_verifies_but_cannot_sign(self):
        token = admin.generate_signed_license(
            admin.build_payload("ADS-PRO-2", "a@b.test", "pro", lifetime=True),
            self.master["private_key"], with_report_key=False)
        self.assertEqual(len(token[4:].split(".")), 2)

        info = self.mgr.verify_token(token)
        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertFalse(info.can_sign_reports)

    def test_machine_id_defaults_to_unbound(self):
        """Katı DRM yok: varsayilan bagsiz, deger yalnizca beyan edilir."""
        payload = admin.build_payload("ADS-PRO-3", "a@b.test", "pro", days=30)
        self.assertEqual(payload["machine_id"], "*")

        bound = admin.build_payload("ADS-ENT-1", "a@b.test", "enterprise",
                                    lifetime=True, seats=25,
                                    machine_id="abc123")
        info = self.mgr.verify_token(admin.generate_signed_license(
            bound, self.master["private_key"]))
        self.assertEqual(info.machine_id, "abc123")
        self.assertEqual(info.seats, 25)
        # Beyan edilmis olmasi calismayi engellemez.
        self.assertTrue(info.is_active)

    def test_expiry_is_required(self):
        with self.assertRaises(SystemExit):
            admin.build_payload("ADS-PRO-4", "a@b.test", "pro")


class TestWebhooks(unittest.TestCase):
    """LemonSqueezy ve Polar.sh webhook imza dogrulama testleri."""

    @staticmethod
    def _now() -> int:
        return int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    # -- LemonSqueezy: govdenin ham HMAC-SHA256 hexdigest'i ----------------- #

    def test_lemonsqueezy_accepts_a_correct_signature(self):
        secret = "secret_ls_12345"
        payload = b'{"event_name":"order_created","data":{"id":"1"}}'
        sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

        self.assertTrue(admin.verify_lemonsqueezy_webhook(payload, sig, secret))
        self.assertFalse(admin.verify_lemonsqueezy_webhook(payload, "bad_sig", secret))
        self.assertFalse(admin.verify_lemonsqueezy_webhook(payload, sig, "wrong_secret"))
        self.assertFalse(admin.verify_lemonsqueezy_webhook(payload, "", secret))

    def test_lemonsqueezy_rejects_a_stale_timestamp(self):
        secret = "secret_ls_12345"
        payload = b'{"event_name":"order_created"}'
        sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

        self.assertTrue(admin.verify_lemonsqueezy_webhook(
            payload, sig, secret, timestamp=self._now()))
        self.assertFalse(admin.verify_lemonsqueezy_webhook(
            payload, sig, secret, timestamp=self._now() - 3600))

    # -- Polar / Svix: base64 HMAC over "{id}.{timestamp}.{body}" ----------- #

    @staticmethod
    def _svix(secret_b64: str, msg_id: str, timestamp: int, payload: bytes) -> str:
        key = base64.b64decode(secret_b64)
        signed = b".".join((msg_id.encode(), str(timestamp).encode(), payload))
        digest = hmac.new(key, signed, hashlib.sha256).digest()
        return base64.b64encode(digest).decode("ascii")

    def setUp(self):
        self.secret_raw = base64.b64encode(b"polar-signing-key-0123456789").decode()
        self.secret = "whsec_" + self.secret_raw
        self.msg_id = "msg_2abc"
        self.payload = b'{"type":"subscription.created"}'

    def test_polar_accepts_a_real_svix_signature(self):
        ts = self._now()
        sig = self._svix(self.secret_raw, self.msg_id, ts, self.payload)
        self.assertTrue(admin.verify_polar_webhook(
            self.payload, "v1," + sig, self.secret,
            msg_id=self.msg_id, timestamp=ts))

    def test_polar_accepts_the_secret_without_the_whsec_prefix(self):
        ts = self._now()
        sig = self._svix(self.secret_raw, self.msg_id, ts, self.payload)
        self.assertTrue(admin.verify_polar_webhook(
            self.payload, "v1," + sig, self.secret_raw,
            msg_id=self.msg_id, timestamp=ts))

    def test_polar_accepts_one_of_several_rotated_signatures(self):
        """Svix anahtar rotasyonunda baslik bosluk ayracli birden cok imza tasir."""
        ts = self._now()
        good = self._svix(self.secret_raw, self.msg_id, ts, self.payload)
        other = base64.b64encode(b"x" * 32).decode("ascii")
        header = "v1,%s v1,%s" % (other, good)
        self.assertTrue(admin.verify_polar_webhook(
            self.payload, header, self.secret,
            msg_id=self.msg_id, timestamp=ts))

    def test_polar_rejects_a_tampered_body(self):
        ts = self._now()
        sig = self._svix(self.secret_raw, self.msg_id, ts, self.payload)
        self.assertFalse(admin.verify_polar_webhook(
            b'{"type":"subscription.deleted"}', "v1," + sig, self.secret,
            msg_id=self.msg_id, timestamp=ts))

    def test_polar_rejects_a_signature_bound_to_another_message(self):
        """Imza msg_id ve timestamp'e baglidir; baska bir olaya tasinamaz."""
        ts = self._now()
        sig = self._svix(self.secret_raw, self.msg_id, ts, self.payload)
        self.assertFalse(admin.verify_polar_webhook(
            self.payload, "v1," + sig, self.secret,
            msg_id="msg_other", timestamp=ts))

    def test_polar_rejects_a_replayed_request(self):
        """Yakalanan bir istek sonsuza kadar yeniden gonderilememeli."""
        stale = self._now() - 3600
        sig = self._svix(self.secret_raw, self.msg_id, stale, self.payload)
        self.assertFalse(admin.verify_polar_webhook(
            self.payload, "v1," + sig, self.secret,
            msg_id=self.msg_id, timestamp=stale))

    def test_polar_rejects_malformed_input(self):
        ts = self._now()
        sig = self._svix(self.secret_raw, self.msg_id, ts, self.payload)
        for header in ("", "invalid_sig", sig, "v2," + sig):
            with self.subTest(header=header):
                self.assertFalse(admin.verify_polar_webhook(
                    self.payload, header, self.secret,
                    msg_id=self.msg_id, timestamp=ts))
        self.assertFalse(admin.verify_polar_webhook(
            self.payload, "v1," + sig, self.secret,
            msg_id="", timestamp=ts))
        self.assertFalse(admin.verify_polar_webhook(
            self.payload, "v1," + sig, self.secret,
            msg_id=self.msg_id, timestamp="not-a-number"))


if __name__ == "__main__":
    unittest.main()
