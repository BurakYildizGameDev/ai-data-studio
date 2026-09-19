# -*- coding: utf-8 -*-
"""LemonSqueezy test modundan gelen bir siparişin uçtan uca karşılanması.

Zincir, gerçek akışın birebir aynısı:

    webhook gövdesi -> X-Signature doğrulaması -> sipariş->payload eşlemesi
    -> Ed25519 token -> LicenseManager -> Pro özellikleri açık

Ana anahtar her testte tek kullanımlık üretilir; üretim anahtarı bu dosyaya
hiçbir zaman girmez.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_data_studio.licensing import manager as license_manager
from ai_data_studio.licensing.manager import (
    LicenseStatus,
    LicenseTier,
    ProFeatureRequiredError,
)
from tools import license_admin as admin

WEBHOOK_SECRET = "test_mode_webhook_secret_0123456789"

# LemonSqueezy'nin test modunda gerçekten gönderdiği order_created gövdesinin
# alan yapısı. Tutarlar ve adlar örnek; şekil gerçek.
TEST_ORDER = {
    "meta": {
        "test_mode": True,
        "event_name": "order_created",
        "custom_data": {},
    },
    "data": {
        "type": "orders",
        "id": "1",
        "attributes": {
            "store_id": 42,
            "identifier": "8f1a0d52-3a12-4d0f-9a1e-6f1b2c3d4e5f",
            "order_number": 42,
            "user_name": "Test Buyer",
            "user_email": "buyer@example.com",
            "currency": "USD",
            "subtotal": 4900,
            "total": 4900,
            "status": "paid",
            "refunded": False,
            "first_order_item": {
                "id": 1,
                "product_name": "AI Data Studio",
                "variant_name": "Pro",
                "price": 4900,
                "quantity": 1,
            },
        },
    },
}


def _sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    """LemonSqueezy X-Signature: gövdenin HMAC-SHA256 hex özeti."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _body(order: dict) -> bytes:
    """Gövde ham baytlardır; imza JSON'un YENİDEN biçimlenmiş hâline değil buna bağlıdır."""
    return json.dumps(order, separators=(",", ":")).encode("utf-8")


class TestWebhookSignature(unittest.TestCase):
    """İmza doğrulaması: test modundan gelen gövde de aynı yoldan geçer."""

    def test_a_signed_test_order_verifies(self):
        body = _body(TEST_ORDER)

        self.assertTrue(admin.verify_lemonsqueezy_webhook(
            body, _sign(body), WEBHOOK_SECRET))

    def test_a_body_changed_after_signing_is_refused(self):
        body = _body(TEST_ORDER)
        signature = _sign(body)
        tampered = body.replace(b'"total":4900', b'"total":1')

        self.assertFalse(admin.verify_lemonsqueezy_webhook(
            tampered, signature, WEBHOOK_SECRET))

    def test_another_stores_secret_does_not_verify(self):
        body = _body(TEST_ORDER)

        self.assertFalse(admin.verify_lemonsqueezy_webhook(
            body, _sign(body, "someone-elses-secret"), WEBHOOK_SECRET))

    def test_reformatted_json_no_longer_matches(self):
        """Gövde ham tutulmalı: json.dumps ile yeniden yazmak imzayı bozar."""
        body = _body(TEST_ORDER)
        reformatted = json.dumps(json.loads(body), indent=2).encode("utf-8")

        self.assertFalse(admin.verify_lemonsqueezy_webhook(
            reformatted, _sign(body), WEBHOOK_SECRET))


class TestOrderToPayload(unittest.TestCase):
    """Sipariş -> lisans payload eşlemesi."""

    def test_a_test_mode_order_is_refused_by_default(self):
        """Ödenmemiş bir test siparişinden sessizce lisans basılmamalı."""
        with self.assertRaises(ValueError) as ctx:
            admin.payload_from_lemonsqueezy_order(TEST_ORDER)

        self.assertIn("test-mode", str(ctx.exception))

    def test_the_test_order_mints_when_explicitly_allowed(self):
        payload = admin.payload_from_lemonsqueezy_order(
            TEST_ORDER, allow_test_mode=True)

        self.assertEqual(payload["email"], "buyer@example.com")
        self.assertEqual(payload["tier"], "pro")
        self.assertEqual(payload["key"], "ADS-PRO-00042")
        self.assertEqual(payload["seats"], 1)
        self.assertIn("audit_pdf", payload["features"])

    def test_a_live_order_needs_no_flag(self):
        live = copy.deepcopy(TEST_ORDER)
        live["meta"]["test_mode"] = False

        payload = admin.payload_from_lemonsqueezy_order(live)

        self.assertEqual(payload["tier"], "pro")

    def test_the_enterprise_variant_maps_to_the_enterprise_tier(self):
        order = copy.deepcopy(TEST_ORDER)
        order["data"]["attributes"]["first_order_item"]["variant_name"] = "Enterprise"
        order["data"]["attributes"]["first_order_item"]["quantity"] = 25

        payload = admin.payload_from_lemonsqueezy_order(order, allow_test_mode=True)

        self.assertEqual(payload["tier"], "enterprise")
        self.assertEqual(payload["seats"], 25)
        self.assertEqual(payload["features"], ["*"])
        self.assertEqual(payload["key"], "ADS-ENTERPRISE-00042")

    def test_checkout_custom_data_overrides_the_product_name(self):
        order = copy.deepcopy(TEST_ORDER)
        order["meta"]["custom_data"] = {"tier": "enterprise"}

        payload = admin.payload_from_lemonsqueezy_order(order, allow_test_mode=True)

        self.assertEqual(payload["tier"], "enterprise")

    def test_a_non_numeric_identifier_still_produces_a_key(self):
        order = copy.deepcopy(TEST_ORDER)
        order["data"]["attributes"].pop("order_number")

        payload = admin.payload_from_lemonsqueezy_order(order, allow_test_mode=True)

        self.assertTrue(payload["key"].startswith("ADS-PRO-"))
        self.assertNotIn("-", payload["key"][len("ADS-PRO-"):])

    def test_another_event_type_is_refused(self):
        order = copy.deepcopy(TEST_ORDER)
        order["meta"]["event_name"] = "subscription_updated"

        with self.assertRaises(ValueError):
            admin.payload_from_lemonsqueezy_order(order, allow_test_mode=True)

    def test_an_order_without_an_email_is_refused(self):
        order = copy.deepcopy(TEST_ORDER)
        order["data"]["attributes"]["user_email"] = ""

        with self.assertRaises(ValueError):
            admin.payload_from_lemonsqueezy_order(order, allow_test_mode=True)


class TestEndToEndFulfilment(unittest.TestCase):
    """Webhook'tan uygulamada aktif Pro lisansa kadar."""

    def setUp(self):
        self.master = admin.generate_master_keypair()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self._old_file = license_manager.LICENSE_FILE_PATH
        license_manager.LICENSE_FILE_PATH = Path(self.temp_dir.name) / ".license"
        self.addCleanup(
            lambda: setattr(license_manager, "LICENSE_FILE_PATH", self._old_file))

        self.manager = license_manager.LicenseManager(
            public_key_b64=self.master["public_key"])

    def _mint(self, order=TEST_ORDER, **kwargs):
        """Gerçek sıradaki üç adım: imzayı doğrula, payload üret, token bas."""
        body = _body(order)
        self.assertTrue(admin.verify_lemonsqueezy_webhook(
            body, _sign(body), WEBHOOK_SECRET))
        payload = admin.payload_from_lemonsqueezy_order(
            json.loads(body.decode("utf-8")), allow_test_mode=True, **kwargs)
        return admin.generate_signed_license(payload, self.master["private_key"])

    def test_the_minted_token_verifies_as_an_active_pro_licence(self):
        info = self.manager.verify_token(self._mint())

        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertEqual(info.tier, LicenseTier.PRO)
        self.assertTrue(info.is_active)
        self.assertEqual(info.email, "buyer@example.com")
        self.assertEqual(info.key, "ADS-PRO-00042")

    def test_activating_it_unlocks_the_pro_gate(self):
        """require_pro, PDF denetim raporunun kapısı; aktivasyondan sonra açılmalı."""
        with mock.patch("ai_data_studio.config._keyring", return_value=None):
            installed = self.manager.install_license(self._mint())
            self.assertEqual(installed.status, LicenseStatus.VALID)

            active = self.manager.get_active_license(force_reload=True)
            self.assertTrue(active.is_active)
            self.assertTrue(active.is_pro)
            self.manager.require_pro("Enterprise PDF Audit Report")

    def test_the_licence_survives_a_restart(self):
        """Uygulamanin yeniden acilisi: yeni yonetici, ayni depolanan token."""
        with mock.patch("ai_data_studio.config._keyring", return_value=None):
            self.manager.install_license(self._mint())

            fresh = license_manager.LicenseManager(
                public_key_b64=self.master["public_key"])
            info = fresh.get_active_license(force_reload=True)

        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertEqual(info.key, "ADS-PRO-00042")

    def test_an_enterprise_order_unlocks_every_feature(self):
        order = copy.deepcopy(TEST_ORDER)
        order["data"]["attributes"]["first_order_item"]["variant_name"] = "Enterprise"

        info = self.manager.verify_token(self._mint(order))

        self.assertEqual(info.tier, LicenseTier.ENTERPRISE)
        self.assertTrue(info.has_feature("anything_at_all"))

    def test_a_token_from_another_master_key_is_refused(self):
        """Kendi anahtar ciftini uretip lisans basan biri gecemez."""
        attacker = admin.generate_master_keypair()
        payload = admin.payload_from_lemonsqueezy_order(
            TEST_ORDER, allow_test_mode=True)
        forged = admin.generate_signed_license(payload, attacker["private_key"])

        info = self.manager.verify_token(forged)

        self.assertEqual(info.status, LicenseStatus.INVALID)
        self.assertFalse(info.is_active)

    def test_a_revoked_key_is_refused_even_though_it_is_signed(self):
        token = self._mint()

        with mock.patch.object(license_manager, "load_revoked_keys",
                               return_value={"ADS-PRO-00042"}):
            info = self.manager.verify_token(token)

        self.assertNotEqual(info.status, LicenseStatus.VALID)
        self.assertFalse(info.is_active)

    def test_without_a_licence_the_pro_gate_stays_closed(self):
        """Karsilastirma noktasi: aktivasyon oncesi ayni cagri reddedilmeli."""
        with mock.patch("ai_data_studio.config._keyring", return_value=None):
            fresh = license_manager.LicenseManager(
                public_key_b64=self.master["public_key"])
            with self.assertRaises(ProFeatureRequiredError):
                fresh.require_pro("Enterprise PDF Audit Report")

    def test_the_signed_report_key_is_minted_with_the_licence(self):
        """M-1 zinciri: lisans, serh imzalamak icin kendi anahtarini tasimali."""
        info = self.manager.verify_token(self._mint())

        self.assertTrue(info.report_private_key)
        self.assertTrue(info.public_token)


class TestFulfilCommand(unittest.TestCase):
    """``python tools/license_admin.py fulfil`` — satıcı tarafındaki tek komut."""

    def setUp(self):
        self.master = admin.generate_master_keypair()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.body_path = Path(self.temp_dir.name) / "webhook.json"
        self.body = _body(TEST_ORDER)
        self.body_path.write_bytes(self.body)

    def _run(self, *extra):
        return admin.main([
            "fulfil", "--body", str(self.body_path),
            "--signature", _sign(self.body),
            "--webhook-secret", WEBHOOK_SECRET,
            "--private-key", self.master["private_key"],
            *extra,
        ])

    def test_a_test_mode_order_needs_the_explicit_flag(self):
        """Komut satirinda traceback degil, ne yapmasi gerektigi gorunmeli."""
        printed = []
        with mock.patch("builtins.print",
                        side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
            code = self._run()

        self.assertEqual(code, 2)
        self.assertIn("test-mode", " ".join(printed))

    def test_the_command_prints_a_token_the_client_accepts(self):
        printed = []
        with mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
            code = self._run("--allow-test-mode")

        self.assertEqual(code, 0)
        token = printed[-1]
        info = license_manager.LicenseManager(
            public_key_b64=self.master["public_key"]).verify_token(token)
        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertEqual(info.tier, LicenseTier.PRO)
        self.assertIn("ADS-PRO-00042", printed[-2])

    def test_a_bad_signature_mints_nothing(self):
        code = admin.main([
            "fulfil", "--body", str(self.body_path),
            "--signature", "0" * 64,
            "--webhook-secret", WEBHOOK_SECRET,
            "--private-key", self.master["private_key"],
            "--allow-test-mode",
        ])

        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
