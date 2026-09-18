# -*- coding: utf-8 -*-
"""Licensing engine unit & integration tests.

Tests:
  - Ed25519 signature verification
  - Offline validation
  - Expiration detection
  - Tamper resistance
  - Feature gating (is_pro, is_enterprise, require_pro)
  - Webhook verification (LemonSqueezy, Polar.sh)
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_data_studio.licensing import manager
from ai_data_studio.licensing.manager import (
    LicenseManager,
    LicenseStatus,
    LicenseTier,
    ProFeatureRequiredError,
    generate_signed_license,
    get_license_manager,
    is_enterprise,
    is_pro,
    verify_lemonsqueezy_webhook,
    verify_polar_webhook,
)
from ai_data_studio.tests.license_keys import ephemeral_keypair, ephemeral_manager


class TestLicensingEngine(unittest.TestCase):
    def setUp(self):
        # A fresh key pair per test: the suite no longer carries the production
        # private key, so a checkout of this repository cannot mint licenses.
        self.mgr, self.private_key = ephemeral_manager()

    def test_default_community_status(self):
        """Default unactivated state is Community edition."""
        info = self.mgr.verify_token("")
        self.assertEqual(info.status, LicenseStatus.MISSING)
        self.assertFalse(info.is_active)
        self.assertFalse(info.is_pro)
        self.assertFalse(info.is_enterprise)

    def test_valid_pro_license(self):
        """Valid Ed25519 signed Pro license verification."""
        tomorrow = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)).isoformat()
        payload = {
            "key": "ADS-PRO-12345",
            "email": "customer@company.com",
            "tier": "pro",
            "features": ["audit_pdf", "unlimited_rows"],
            "issued_at": "2026-01-01T00:00:00Z",
            "expires_at": tomorrow,
            "seats": 5,
        }
        token = generate_signed_license(payload, self.private_key)
        self.assertTrue(token.startswith("ADS-"))

        info = self.mgr.verify_token(token)
        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertTrue(info.is_active)
        self.assertTrue(info.is_pro)
        self.assertFalse(info.is_enterprise)
        self.assertEqual(info.tier, LicenseTier.PRO)
        self.assertEqual(info.email, "customer@company.com")
        self.assertTrue(info.has_feature("audit_pdf"))
        self.assertTrue(info.has_feature("unlimited_rows"))
        self.assertFalse(info.has_feature("custom_models"))
        self.assertIsNotNone(info.days_remaining)
        self.assertGreater(info.days_remaining, 300)

    def test_valid_enterprise_license(self):
        """Enterprise tier has access to all features automatically."""
        payload = {
            "key": "ADS-ENT-99999",
            "email": "enterprise@bank.com",
            "tier": "enterprise",
            "features": ["*"],
            "expires_at": "lifetime",
            "seats": 100,
        }
        token = generate_signed_license(payload, self.private_key)
        info = self.mgr.verify_token(token)
        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertTrue(info.is_active)
        self.assertTrue(info.is_pro)
        self.assertTrue(info.is_enterprise)
        self.assertIsNone(info.days_remaining)  # lifetime
        self.assertTrue(info.has_feature("any_unlisted_feature"))

    def test_expired_license(self):
        """Expired licenses are identified and deactivated."""
        yesterday = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).isoformat()
        payload = {
            "key": "ADS-PRO-OLD",
            "email": "old@company.com",
            "tier": "pro",
            "expires_at": yesterday,
        }
        token = generate_signed_license(payload, self.private_key)
        info = self.mgr.verify_token(token)
        self.assertEqual(info.status, LicenseStatus.EXPIRED)
        self.assertFalse(info.is_active)
        self.assertFalse(info.is_pro)

    def test_tampered_payload_rejected(self):
        """Modifying payload bytes invalidates the Ed25519 signature."""
        payload = {
            "key": "ADS-PRO-ORIG",
            "tier": "pro",
            "email": "user@test.com",
        }
        token = generate_signed_license(payload, self.private_key)
        parts = token[4:].split(".")
        # Tamper with the payload portion
        tampered_token = "ADS-eyJ0aWVyIjogImVudGVycHJpc2UifQ." + parts[1]
        info = self.mgr.verify_token(tampered_token)
        self.assertEqual(info.status, LicenseStatus.INVALID)
        self.assertFalse(info.is_active)

    def test_corrupted_token_format(self):
        """Malformed strings fail gracefully without crashing."""
        self.assertEqual(self.mgr.verify_token("invalid").status, LicenseStatus.INVALID)
        self.assertEqual(self.mgr.verify_token("ADS-abc.def.ghi").status, LicenseStatus.INVALID)
        self.assertEqual(self.mgr.verify_token("ADS-!not_b64!.!sig!").status, LicenseStatus.INVALID)

    def test_require_pro_guard(self):
        """require_pro raises ProFeatureRequiredError when inactive."""
        with mock.patch.object(self.mgr, "get_active_license") as mock_lic:
            mock_lic.return_value.is_active = False
            with self.assertRaises(ProFeatureRequiredError):
                self.mgr.require_pro("Audit PDF")

            mock_lic.return_value.is_active = True
            # Should not raise
            self.mgr.require_pro("Audit PDF")

    def test_public_key_cannot_be_overridden_by_environment(self):
        """An attacker-supplied public key in the environment is ignored.

        The manager used to read AI_DATA_STUDIO_LICENSE_PUBKEY, so generating a
        key pair and exporting one variable was enough to have a self-signed
        Enterprise token accepted. The trust anchor is now compiled in.
        """
        attacker_private, attacker_public = ephemeral_keypair()
        forged = generate_signed_license(
            {
                "key": "FORGED-0001",
                "email": "attacker@example.invalid",
                "tier": "enterprise",
                "features": ["*"],
                "expires_at": "lifetime",
                "seats": 9999,
            },
            attacker_private,
        )

        for var in ("AI_DATA_STUDIO_LICENSE_PUBKEY",
                    "AI_DATA_STUDIO_LICENSE_PUBKEY_TEST"):
            with mock.patch.dict(os.environ, {var: attacker_public}):
                info = LicenseManager().verify_token(forged)
                self.assertEqual(info.status, LicenseStatus.INVALID)
                self.assertFalse(info.is_active)
                self.assertFalse(info.is_enterprise)

    def test_license_installation_and_removal(self):
        """Persisting and removing license via settings / keyring."""
        payload = {
            "key": "ADS-PRO-SAVE",
            "tier": "pro",
            "expires_at": "lifetime",
        }
        token = generate_signed_license(payload, self.private_key)

        with mock.patch("ai_data_studio.config._keyring", return_value=None):
            # Using local settings fallback
            info = self.mgr.install_license(token)
            self.assertEqual(info.status, LicenseStatus.VALID)

            loaded = self.mgr.get_active_license(force_reload=True)
            self.assertEqual(loaded.status, LicenseStatus.VALID)
            self.assertEqual(loaded.key, "ADS-PRO-SAVE")

            self.mgr.remove_license()
            removed = self.mgr.get_active_license(force_reload=True)
            self.assertEqual(removed.status, LicenseStatus.MISSING)



class TestExpiryAndClock(unittest.TestCase):
    """Sure denetiminin fail-closed oldugunu ve saatin geri alinamadigini dogrular."""

    def setUp(self):
        self.mgr, self.private_key = ephemeral_manager()
        self.tmp = tempfile.TemporaryDirectory()
        # Saat damgasini teste ozel bir yola al: gercek kullanici damgasina
        # dokunmadan ve testler arasi sizinti olmadan calissin.
        self._old_seen = manager.LICENSE_SEEN_PATH
        manager.LICENSE_SEEN_PATH = Path(self.tmp.name) / ".license_seen"
        self.now = datetime.datetime.now(datetime.timezone.utc)

    def tearDown(self):
        manager.LICENSE_SEEN_PATH = self._old_seen
        self.tmp.cleanup()

    def _token(self, expires_at):
        return generate_signed_license(
            {"key": "K", "email": "e@x", "tier": "pro", "features": ["pdf"],
             "seats": 1, "expires_at": expires_at},
            self.private_key)

    def _at(self, when):
        """Sistem saatini *when* gosterecek sekilde sahteler."""
        patcher = mock.patch.object(manager.datetime, "datetime",
                                    wraps=datetime.datetime)
        fake = patcher.start()
        fake.now.return_value = when
        self.addCleanup(patcher.stop)
        return fake

    def test_unparseable_expiry_fails_closed(self):
        """Ayrıştırılamayan bir sure omurluk lisans anlamina gelmemeli."""
        for bad in ("tomorrow-ish", "2027-13-45", 1, 3.5, []):
            with self.subTest(expires_at=bad):
                info = self.mgr.verify_token(self._token(bad))
                self.assertEqual(info.status, LicenseStatus.INVALID)
                self.assertFalse(info.is_active)

    def test_valid_and_expired_dates_still_work(self):
        future = (self.now + datetime.timedelta(days=30)).isoformat()
        self.assertEqual(self.mgr.verify_token(self._token(future)).status,
                         LicenseStatus.VALID)
        past = (self.now - datetime.timedelta(days=1)).isoformat()
        self.assertEqual(self.mgr.verify_token(self._token(past)).status,
                         LicenseStatus.EXPIRED)

    def test_lifetime_licence_skips_the_clock_check(self):
        info = self.mgr.verify_token(self._token("lifetime"))
        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertFalse(manager.LICENSE_SEEN_PATH.exists())

    def test_non_numeric_seats_does_not_escape(self):
        """Sayisal olmayan seats eskiden verify_token'dan disari kaciyordu."""
        token = generate_signed_license(
            {"key": "K", "tier": "pro", "expires_at": "lifetime", "seats": "many"},
            self.private_key)
        info = self.mgr.verify_token(token)
        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertEqual(info.seats, 1)

    def test_rolling_the_clock_back_invalidates_the_licence(self):
        token = self._token((self.now + datetime.timedelta(days=30)).isoformat())
        self.assertEqual(self.mgr.verify_token(token).status, LicenseStatus.VALID)
        self.assertTrue(manager.LICENSE_SEEN_PATH.exists())

        self._at(self.now - datetime.timedelta(days=500))
        rolled = self.mgr.verify_token(token)
        self.assertEqual(rolled.status, LicenseStatus.INVALID)
        self.assertFalse(rolled.is_active)

    def test_small_clock_skew_is_tolerated(self):
        """NTP duzeltmesi ya da seyahat mesru lisansi dusurmemeli."""
        token = self._token((self.now + datetime.timedelta(days=30)).isoformat())
        self.assertEqual(self.mgr.verify_token(token).status, LicenseStatus.VALID)

        self._at(self.now - datetime.timedelta(hours=2))
        self.assertEqual(self.mgr.verify_token(token).status, LicenseStatus.VALID)

    def test_cached_licence_is_revalidated_after_ttl(self):
        """Calisirken dolan bir lisans sonsuza kadar gecerli kalmamali."""
        soon = self.now + datetime.timedelta(minutes=5)
        token = self._token(soon.isoformat())
        with mock.patch("ai_data_studio.config._keyring", return_value=None):
            self.assertEqual(self.mgr.install_license(token).status,
                             LicenseStatus.VALID)
            self.assertTrue(self.mgr.get_active_license().is_active)

            # TTL'in otesine, lisansin bitisinden sonrasina sic
            self._at(self.now + manager.CACHE_TTL + datetime.timedelta(minutes=10))
            self.assertFalse(self.mgr.get_active_license().is_active)
            self.mgr.remove_license()



class TestLicenseFilePermissions(unittest.TestCase):
    """Keyring yokken token'in dosyaya nasil yazildigini dogrular."""

    def setUp(self):
        self.mgr, self.private_key = ephemeral_manager()
        self.tmp = tempfile.TemporaryDirectory()
        self._old_file = manager.LICENSE_FILE_PATH
        manager.LICENSE_FILE_PATH = Path(self.tmp.name) / "store" / ".license"

    def tearDown(self):
        manager.LICENSE_FILE_PATH = self._old_file
        self.tmp.cleanup()

    def _token(self):
        return generate_signed_license(
            {"key": "K", "tier": "pro", "expires_at": "lifetime"}, self.private_key)

    def test_license_file_is_owner_only_on_posix(self):
        """POSIX'te 0600 olmali: eskiden umask'a tabi 0644 yaziliyordu."""
        with mock.patch("ai_data_studio.config._keyring", return_value=None):
            info = self.mgr.install_license(self._token())
            self.assertEqual(info.status, LicenseStatus.VALID)

        path = manager.LICENSE_FILE_PATH
        self.assertTrue(path.exists())
        if os.name == "nt":
            self.skipTest("POSIX izin bitleri Windows'ta uygulanmaz")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_written_token_round_trips(self):
        with mock.patch("ai_data_studio.config._keyring", return_value=None):
            self.mgr.install_license(self._token())
            loaded = self.mgr.get_active_license(force_reload=True)
            self.assertEqual(loaded.status, LicenseStatus.VALID)
            self.assertEqual(loaded.key, "K")

    def test_unstorable_license_is_reported_not_silently_lost(self):
        """Hicbir yere yazilamiyorsa kullanici bunu gormeli."""
        with mock.patch("ai_data_studio.config._keyring", return_value=None),              mock.patch.object(manager, "_write_private",
                               side_effect=OSError("read-only")):
            info = self.mgr.install_license(self._token())
            self.assertEqual(info.status, LicenseStatus.VALID)
            self.assertIn("restart", info.status_message.lower())


class TestKeyringServiceName(unittest.TestCase):
    """Lisans, uygulamanin geri kalaniyla ayni keyring servisini kullanmali.

    Lisans modulu kendi adini ("ai_data_studio") tasiyordu; kullanicinin
    kimlik deposunda iki ayri giris olusuyor ve bir "tum verileri sil" akisi
    birini kaciriyordu.
    """

    class FakeKeyring:
        def __init__(self):
            self.store = {}

        def get_password(self, service, account):
            return self.store.get((service, account))

        def set_password(self, service, account, value):
            self.store[(service, account)] = value

        def delete_password(self, service, account):
            self.store.pop((service, account), None)

    def setUp(self):
        self.mgr, self.private_key = ephemeral_manager()
        self.kr = self.FakeKeyring()
        self.token = generate_signed_license(
            {"key": "OLD", "tier": "pro", "expires_at": "lifetime"},
            self.private_key)

    def test_service_name_matches_the_rest_of_the_app(self):
        from ai_data_studio import config

        self.assertEqual(manager.KEYRING_SERVICE, config.KEYRING_SERVICE)

    def test_legacy_entry_is_read_and_migrated(self):
        self.kr.store[(manager.LEGACY_KEYRING_SERVICE,
                       manager.KEYRING_LICENSE_KEY)] = self.token

        with mock.patch("ai_data_studio.config._keyring", return_value=self.kr):
            info = self.mgr.get_active_license(force_reload=True)

        self.assertEqual(info.key, "OLD")
        self.assertEqual(
            self.kr.store.get((manager.KEYRING_SERVICE,
                               manager.KEYRING_LICENSE_KEY)), self.token)
        self.assertNotIn((manager.LEGACY_KEYRING_SERVICE,
                          manager.KEYRING_LICENSE_KEY), self.kr.store)

    def test_remove_license_clears_both_names(self):
        self.kr.store[(manager.KEYRING_SERVICE,
                       manager.KEYRING_LICENSE_KEY)] = self.token
        self.kr.store[(manager.LEGACY_KEYRING_SERVICE,
                       manager.KEYRING_LICENSE_KEY)] = self.token

        with mock.patch("ai_data_studio.config._keyring", return_value=self.kr):
            self.mgr.remove_license()

        self.assertEqual(self.kr.store, {})


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

        self.assertTrue(verify_lemonsqueezy_webhook(payload, sig, secret))
        self.assertFalse(verify_lemonsqueezy_webhook(payload, "bad_sig", secret))
        self.assertFalse(verify_lemonsqueezy_webhook(payload, sig, "wrong_secret"))
        self.assertFalse(verify_lemonsqueezy_webhook(payload, "", secret))

    def test_lemonsqueezy_rejects_a_stale_timestamp(self):
        secret = "secret_ls_12345"
        payload = b'{"event_name":"order_created"}'
        sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

        self.assertTrue(verify_lemonsqueezy_webhook(
            payload, sig, secret, timestamp=self._now()))
        self.assertFalse(verify_lemonsqueezy_webhook(
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
        self.assertTrue(verify_polar_webhook(
            self.payload, "v1," + sig, self.secret,
            msg_id=self.msg_id, timestamp=ts))

    def test_polar_accepts_the_secret_without_the_whsec_prefix(self):
        ts = self._now()
        sig = self._svix(self.secret_raw, self.msg_id, ts, self.payload)
        self.assertTrue(verify_polar_webhook(
            self.payload, "v1," + sig, self.secret_raw,
            msg_id=self.msg_id, timestamp=ts))

    def test_polar_accepts_one_of_several_rotated_signatures(self):
        """Svix anahtar rotasyonunda baslik bosluk ayracli birden cok imza tasir."""
        ts = self._now()
        good = self._svix(self.secret_raw, self.msg_id, ts, self.payload)
        other = base64.b64encode(b"x" * 32).decode("ascii")
        header = "v1,%s v1,%s" % (other, good)
        self.assertTrue(verify_polar_webhook(
            self.payload, header, self.secret,
            msg_id=self.msg_id, timestamp=ts))

    def test_polar_rejects_a_tampered_body(self):
        ts = self._now()
        sig = self._svix(self.secret_raw, self.msg_id, ts, self.payload)
        self.assertFalse(verify_polar_webhook(
            b'{"type":"subscription.deleted"}', "v1," + sig, self.secret,
            msg_id=self.msg_id, timestamp=ts))

    def test_polar_rejects_a_signature_bound_to_another_message(self):
        """Imza msg_id ve timestamp'e baglidir; baska bir olaya tasinamaz."""
        ts = self._now()
        sig = self._svix(self.secret_raw, self.msg_id, ts, self.payload)
        self.assertFalse(verify_polar_webhook(
            self.payload, "v1," + sig, self.secret,
            msg_id="msg_other", timestamp=ts))

    def test_polar_rejects_a_replayed_request(self):
        """Yakalanan bir istek sonsuza kadar yeniden gonderilememeli."""
        stale = self._now() - 3600
        sig = self._svix(self.secret_raw, self.msg_id, stale, self.payload)
        self.assertFalse(verify_polar_webhook(
            self.payload, "v1," + sig, self.secret,
            msg_id=self.msg_id, timestamp=stale))

    def test_polar_rejects_malformed_input(self):
        ts = self._now()
        sig = self._svix(self.secret_raw, self.msg_id, ts, self.payload)
        for header in ("", "invalid_sig", sig, "v2," + sig):
            with self.subTest(header=header):
                self.assertFalse(verify_polar_webhook(
                    self.payload, header, self.secret,
                    msg_id=self.msg_id, timestamp=ts))
        self.assertFalse(verify_polar_webhook(
            self.payload, "v1," + sig, self.secret,
            msg_id="", timestamp=ts))
        self.assertFalse(verify_polar_webhook(
            self.payload, "v1," + sig, self.secret,
            msg_id=self.msg_id, timestamp="not-a-number"))


if __name__ == "__main__":
    unittest.main()
