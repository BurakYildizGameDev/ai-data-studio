# -*- coding: utf-8 -*-
"""Lemon Squeezy lisans anahtari (UUID) yolu.

Magazanin "License keys" ozelligi acikken musteriye imzali bir ADS token'i
degil duz bir UUID gidiyor. Bu dosya o anahtarin yolunu bastan sona kurar:
bicim tanima, magazaya sorma, kapsam denetimi, saklama, yeniden dogrulama.

Ag ERISIMI YOK: butun testler ``requests.post``i degistiriyor. Bir test
gercekten api.lemonsqueezy.com'a ciktiysa bu bir kusurdur, testin gecmesi
saticinin sebekesine bagli olamaz.
"""
from __future__ import annotations

import datetime
import json
import time
import unittest
from unittest import mock

from ai_data_studio.licensing import lemonsqueezy as ls
from ai_data_studio.licensing import manager as manager_module
from ai_data_studio.licensing.manager import LicenseStatus, LicenseTier
from ai_data_studio.tests.license_keys import ephemeral_manager

# Magazanin gercekten dondurdugu govde; musteri e-postasi disinda
# 2026-09-19'da /v1/licenses/validate ne verdiyse o.
LIVE_KEY = "296B8F04-E41C-4228-8B42-3FC9D762E417"


def _response(body: dict, status_code: int = 200):
    reply = mock.Mock()
    reply.status_code = status_code
    reply.json.return_value = body
    return reply


def _store_body(*, flag: str = "valid", test_mode: bool = False,
                store_id: int = ls.STORE_ID, product_id: int = 1372277,
                status: str = "active", expires_at=None, error=None,
                variant_name: str = "Default", instance_id: str = "inst-1",
                activation_limit: int = 2, activation_usage: int = 1) -> dict:
    return {
        flag: error is None,
        "error": error,
        "license_key": {
            "id": 1620824,
            "status": status,
            "key": LIVE_KEY,
            "activation_limit": activation_limit,
            "activation_usage": activation_usage,
            "created_at": "2026-09-19T18:59:44.000000Z",
            "expires_at": expires_at,
            "test_mode": test_mode,
        },
        "instance": {"id": instance_id, "name": "test-machine"},
        "meta": {
            "store_id": store_id,
            "order_id": 9520047,
            "variant_id": 2144223,
            "variant_name": variant_name,
            "product_id": product_id,
            "product_name": "AI Synthetic Data Studio",
            "customer_email": "buyer@example.com",
        },
    }


class TestKeyFormat(unittest.TestCase):
    """Hangi metin hangi yola gider."""

    def test_a_lemonsqueezy_uuid_is_recognised_in_either_case(self):
        self.assertTrue(ls.looks_like_license_key(LIVE_KEY))
        self.assertTrue(ls.looks_like_license_key(LIVE_KEY.lower()))
        self.assertTrue(ls.looks_like_license_key("  " + LIVE_KEY + "  "))

    def test_an_ads_token_is_not_mistaken_for_a_store_key(self):
        self.assertFalse(ls.looks_like_license_key("ADS-eyJrZXkiOiAiQSJ9.c2ln"))
        self.assertFalse(ls.looks_like_license_key(""))
        self.assertFalse(ls.looks_like_license_key("296B8F04E41C42288B423FC9D762E417"))
        # Bir eksik hane: UUID'ye benziyor, UUID degil.
        self.assertFalse(ls.looks_like_license_key("296B8F04-E41C-4228-8B42-3FC9D762E41"))

    def test_the_raw_key_is_never_shown_in_full(self):
        self.assertEqual(ls.mask(LIVE_KEY), "296B8F04-...-E417")


class TestActivation(unittest.TestCase):
    """Anahtarin magazada karsiligi var mi, ve neyin karsiligi."""

    def setUp(self):
        self.mgr, _ = ephemeral_manager()

    def test_a_paid_key_activates_and_unlocks_pro(self):
        with mock.patch("requests.post",
                        return_value=_response(_store_body(flag="activated"))) as post:
            record = ls.activate(LIVE_KEY, "test-machine")

        self.assertEqual(post.call_args.args[0],
                         "https://api.lemonsqueezy.com/v1/licenses/activate")
        self.assertEqual(record["tier"], "pro")
        self.assertEqual(record["instance_id"], "inst-1")
        self.assertEqual(record["expires_at"], "lifetime")

        info = self.mgr._verify_lemonsqueezy_record(record, allow_network=False)
        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertTrue(info.is_pro)
        self.assertEqual(info.tier, LicenseTier.PRO)
        self.assertEqual(info.email, "buyer@example.com")

    def test_an_enterprise_variant_unlocks_enterprise(self):
        body = _store_body(flag="activated", variant_name="Enterprise")
        with mock.patch("requests.post", return_value=_response(body)):
            record = ls.activate(LIVE_KEY, "test-machine")
        info = self.mgr._verify_lemonsqueezy_record(record, allow_network=False)
        self.assertTrue(info.is_enterprise)

    def test_a_key_from_another_store_is_refused(self):
        """/validate BUTUN magazalara bakar.

        Bu denetim olmadan baska bir saticinin bir dolarlik anahtari burada
        Pro acardi - anahtar kendi magazasinda kusursuz gecerli oldugu icin
        imza denetimine de takilmazdi.
        """
        body = _store_body(flag="activated", store_id=ls.STORE_ID + 1)
        with mock.patch("requests.post", return_value=_response(body)):
            with self.assertRaises(ls.LemonSqueezyError) as caught:
                ls.activate(LIVE_KEY, "test-machine")
        self.assertEqual(caught.exception.message_key, "license.status.ls_wrong_store")

    def test_a_key_for_another_product_in_our_own_store_is_refused(self):
        body = _store_body(flag="activated", product_id=999999)
        with mock.patch("requests.post", return_value=_response(body)):
            with self.assertRaises(ls.LemonSqueezyError) as caught:
                ls.activate(LIVE_KEY, "test-machine")
        self.assertEqual(caught.exception.message_key, "license.status.ls_wrong_store")

    def test_a_test_mode_key_does_not_unlock_a_paid_edition(self):
        """Test modundaki siparis odenmez.

        Satici tarafi bunu zaten reddediyor (payload_from_lemonsqueezy_order);
        istemci reddetmezse magaza test modundayken Pro bedavaya dagitilir.
        """
        body = _store_body(flag="activated", test_mode=True)
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop(ls.TEST_MODE_ENV, None)
            with mock.patch("requests.post", return_value=_response(body)):
                with self.assertRaises(ls.LemonSqueezyError) as caught:
                    ls.activate(LIVE_KEY, "test-machine")
        self.assertEqual(caught.exception.message_key, "license.status.ls_test_mode")

    def test_test_mode_can_be_opened_deliberately_and_says_so(self):
        """Saticinin kendi magazasini denemesi icin kapi; acikken gorunur."""
        body = _store_body(flag="activated", test_mode=True)
        with mock.patch.dict("os.environ", {ls.TEST_MODE_ENV: "1"}):
            with mock.patch("requests.post", return_value=_response(body)):
                record = ls.activate(LIVE_KEY, "test-machine")
            info = self.mgr._verify_lemonsqueezy_record(record, allow_network=False)

        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertIn("TEST", info.status_message.upper())

    def test_a_refused_key_carries_the_store_reason(self):
        body = _store_body(flag="activated", error="license_key not found")
        with mock.patch("requests.post", return_value=_response(body, 400)):
            with self.assertRaises(ls.LemonSqueezyError) as caught:
                ls.activate(LIVE_KEY, "test-machine")
        self.assertEqual(caught.exception.message_key, "license.status.ls_rejected")
        self.assertIn("not found", caught.exception.localized())

    def test_an_exhausted_key_says_so_instead_of_invalid(self):
        body = _store_body(flag="activated",
                           error="License key activation limit reached.",
                           activation_usage=2)
        with mock.patch("requests.post", return_value=_response(body, 400)):
            with self.assertRaises(ls.LemonSqueezyError) as caught:
                ls.activate(LIVE_KEY, "test-machine")
        self.assertEqual(caught.exception.message_key, "license.status.ls_limit_reached")
        self.assertIn("2/2", caught.exception.localized())

    def test_a_store_outage_is_transient_not_a_verdict(self):
        with mock.patch("requests.post", return_value=_response({}, 503)):
            with self.assertRaises(ls.LemonSqueezyError) as caught:
                ls.validate(LIVE_KEY)
        self.assertTrue(caught.exception.transient)

    def test_a_dead_connection_is_transient_too(self):
        with mock.patch("requests.post", side_effect=OSError("no route to host")):
            with self.assertRaises(ls.LemonSqueezyError) as caught:
                ls.validate(LIVE_KEY)
        self.assertTrue(caught.exception.transient)


class TestInstallation(unittest.TestCase):
    """Anahtarin kutuya yapistirilmasindan sonrasi."""

    def setUp(self):
        self.mgr, _ = ephemeral_manager()
        self.stored = {}
        patcher = mock.patch.object(
            manager_module.LicenseManager, "_persist_token",
            side_effect=lambda token: self.stored.setdefault("token", token) or True)
        self.persist = patcher.start()
        self.addCleanup(patcher.stop)

    def test_pasting_the_key_activates_it_and_stores_a_record(self):
        """Kullanicinin yaptigi sey: anahtari yapistir, Etkinlestir'e bas."""
        with mock.patch("requests.post",
                        return_value=_response(_store_body(flag="activated"))):
            info = self.mgr.install_license("  " + LIVE_KEY.lower() + "  ")

        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertTrue(info.is_pro)

        record = json.loads(self.stored["token"])
        self.assertEqual(record["provider"], "lemonsqueezy")
        self.assertEqual(record["key"], LIVE_KEY)
        self.assertEqual(record["instance_id"], "inst-1")

    def test_the_raw_key_never_reaches_the_provenance_record(self):
        """LicenseInfo.key paylasilan denetim raporlarina giriyor.

        ADS token'larinda o alan bir siparis numarasi; magaza anahtarinda ise
        paroladir. Raporu alan herkes urunu etkinlestirebilseydi lisansin
        anlami kalmazdi.
        """
        with mock.patch("requests.post",
                        return_value=_response(_store_body(flag="activated"))):
            info = self.mgr.install_license(LIVE_KEY)

        self.assertNotIn(LIVE_KEY, info.key)
        self.assertNotIn(LIVE_KEY, info.status_message)
        self.assertEqual(info.key, "ADS-LS-1620824")

    def test_a_refusal_is_reported_and_nothing_is_stored(self):
        body = _store_body(flag="activated", error="license_key not found")
        with mock.patch("requests.post", return_value=_response(body, 400)):
            info = self.mgr.install_license(LIVE_KEY)

        self.assertEqual(info.status, LicenseStatus.INVALID)
        self.assertFalse(info.is_pro)
        self.assertEqual(self.stored, {})

    def test_an_unactivated_key_read_back_from_storage_is_not_a_licence(self):
        info = self.mgr.verify_token(LIVE_KEY)
        self.assertEqual(info.status, LicenseStatus.INVALID)
        self.assertNotIn(LIVE_KEY, info.key)

    def test_removing_the_licence_hands_the_seat_back(self):
        """Yoksa her yeniden kurulum bir etkinlestirme hakki yakar."""
        record = _store_body(flag="activated")
        with mock.patch("requests.post", return_value=_response(record)):
            self.mgr.install_license(LIVE_KEY)

        with mock.patch.object(manager_module.LicenseManager, "_read_stored_token",
                               return_value=self.stored["token"]):
            with mock.patch.object(ls, "deactivate") as released:
                self.mgr.remove_license()

        released.assert_called_once_with(LIVE_KEY, "inst-1")

    def test_removing_an_ads_token_licence_calls_no_store(self):
        with mock.patch.object(manager_module.LicenseManager, "_read_stored_token",
                               return_value="ADS-eyJrZXkiOiAiQSJ9.c2ln"):
            with mock.patch("requests.post") as post:
                self.mgr.remove_license()
        post.assert_not_called()


class TestRevalidation(unittest.TestCase):
    """Kurulu bir kayit ne zaman magazaya yeniden sorulur, ne zaman dusürulur."""

    def setUp(self):
        self.mgr, _ = ephemeral_manager()
        patcher = mock.patch.object(manager_module.LicenseManager,
                                    "_persist_token", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _record(self, age_days: float) -> dict:
        stamp = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(days=age_days))
        record = ls._record_from(_store_body(flag="activated"), flag="activated")
        record["last_validated"] = stamp.isoformat()
        return record

    def test_a_fresh_record_is_trusted_without_touching_the_network(self):
        """Her ozellik denetiminde magazaya sormak kabul edilemez."""
        with mock.patch("requests.post") as post:
            info = self.mgr._verify_lemonsqueezy_record(self._record(1))
        post.assert_not_called()
        self.assertEqual(info.status, LicenseStatus.VALID)

    def test_a_stale_record_is_re_checked_with_the_store(self):
        with mock.patch("requests.post",
                        return_value=_response(_store_body())) as post:
            info = self.mgr._verify_lemonsqueezy_record(self._record(9))
        self.assertEqual(post.call_args.args[0],
                         "https://api.lemonsqueezy.com/v1/licenses/validate")
        self.assertEqual(info.status, LicenseStatus.VALID)

    def test_a_refund_revokes_the_licence_at_the_next_check(self):
        body = _store_body(error="license_key has been disabled")
        with mock.patch("requests.post", return_value=_response(body, 400)):
            info = self.mgr._verify_lemonsqueezy_record(self._record(9))
        self.assertEqual(info.status, LicenseStatus.INVALID)

    def test_a_stale_record_survives_an_unreachable_store(self):
        """Ucakta, otelde, kesintide: lisans dusmez."""
        with mock.patch("requests.post", side_effect=OSError("offline")):
            info = self.mgr._verify_lemonsqueezy_record(self._record(9))
        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertTrue(info.is_pro)

    def test_but_not_forever(self):
        days = manager_module.LS_OFFLINE_GRACE.days + 1
        with mock.patch("requests.post", side_effect=OSError("offline")):
            info = self.mgr._verify_lemonsqueezy_record(self._record(days))
        self.assertEqual(info.status, LicenseStatus.INVALID)

    def test_an_expired_key_is_expired_without_asking_anyone(self):
        yesterday = (datetime.datetime.now(datetime.timezone.utc)
                     - datetime.timedelta(days=1)).isoformat()
        record = self._record(1)
        record["expires_at"] = yesterday
        with mock.patch("requests.post") as post:
            info = self.mgr._verify_lemonsqueezy_record(record)
        post.assert_not_called()
        self.assertEqual(info.status, LicenseStatus.EXPIRED)

    def test_a_revoked_key_is_refused_from_the_bundled_list(self):
        record = self._record(1)
        with mock.patch.object(manager_module, "load_revoked_keys",
                               return_value={record["public_key_id"]}):
            info = self.mgr._verify_lemonsqueezy_record(record)
        self.assertEqual(info.status, LicenseStatus.INVALID)

    def test_the_raw_key_can_also_be_revoked(self):
        record = self._record(1)
        with mock.patch.object(manager_module, "load_revoked_keys",
                               return_value={LIVE_KEY}):
            info = self.mgr._verify_lemonsqueezy_record(record)
        self.assertEqual(info.status, LicenseStatus.INVALID)

    def test_a_stored_record_round_trips_through_verify_token(self):
        record = self._record(1)
        info = self.mgr.verify_token(json.dumps(record))
        self.assertEqual(info.status, LicenseStatus.VALID)
        self.assertTrue(info.is_pro)

    def test_rolling_the_clock_back_forces_a_re_check(self):
        """Saat geri alinirsa 'ne kadar zaman gecti' sorusu anlamsizdir."""
        with mock.patch.object(manager_module, "_clock_is_sane", return_value=False):
            with mock.patch("requests.post",
                            return_value=_response(_store_body())) as post:
                self.mgr._verify_lemonsqueezy_record(self._record(0))
        post.assert_called_once()


class TestDeferredRevalidation(unittest.TestCase):
    """Acilis yolu magazayi beklemez.

    app_window bayragi ana thread'de tazeliyor; paketleri yutan bir aginda
    senkron bir dogrulama pencereyi zaman asimi boyunca dondururdu.
    """

    def setUp(self):
        self.mgr, _ = ephemeral_manager()
        patcher = mock.patch.object(manager_module.LicenseManager,
                                    "_persist_token", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _record(self, age_days):
        stamp = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(days=age_days))
        record = ls._record_from(_store_body(flag="activated"), flag="activated")
        record["last_validated"] = stamp.isoformat()
        return record

    def test_a_stale_record_is_refreshed_off_the_calling_thread(self):
        with mock.patch.object(manager_module.LicenseManager,
                               "_refresh_record_in_background") as background:
            with mock.patch("requests.post") as post:
                info = self.mgr._verify_lemonsqueezy_record(self._record(9), defer=True)

        post.assert_not_called()
        background.assert_called_once()
        self.assertEqual(info.status, LicenseStatus.VALID)

    def test_past_the_grace_period_it_is_worth_waiting_for(self):
        """Lisans zaten dusmek uzere: tek bekleyecek an burasi."""
        days = manager_module.LS_OFFLINE_GRACE.days + 1
        with mock.patch("requests.post", side_effect=OSError("offline")) as post:
            info = self.mgr._verify_lemonsqueezy_record(self._record(days), defer=True)
        post.assert_called_once()
        self.assertEqual(info.status, LicenseStatus.INVALID)

    def test_a_refusal_seen_in_the_background_is_written_down(self):
        """Yoksa reddedilen anahtar her seferinde arka plana ertelenir ve
        lisans pay suresi dolana kadar yasamaya devam ederdi."""
        stored = {}
        record = self._record(9)
        body = _store_body(error="license_key has been disabled")

        with mock.patch.object(manager_module.LicenseManager, "_persist_token",
                               side_effect=lambda token: stored.setdefault("t", token) or True):
            with mock.patch("requests.post", return_value=_response(body, 400)):
                self.mgr._refresh_record_in_background(record)
                for _ in range(200):
                    if "t" in stored:
                        break
                    time.sleep(0.02)

        self.assertIn("t", stored)
        written = json.loads(stored["t"])
        self.assertIn("disabled", written["refused_reason"])

        info = self.mgr._verify_lemonsqueezy_record(written, allow_network=False)
        self.assertEqual(info.status, LicenseStatus.INVALID)

    def test_only_one_background_check_runs_at_a_time(self):
        self.mgr._revalidating = True
        with mock.patch("threading.Thread") as thread:
            self.mgr._refresh_record_in_background(self._record(9))
        thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
