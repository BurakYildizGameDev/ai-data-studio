# -*- coding: utf-8 -*-
"""Offline provenance signing and verification (M-1).

The chain under test:

    master key -> licence payload -> report_public_key
               -> declaration signature -> dataset digest

Every link is checked here, and so is every way an attacker could try to
reuse, forge or strip one of them. The tests swap in a throwaway master key,
so nothing depends on the real signing key.
"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import ai_data_studio.licensing.provenance as provenance_module
from ai_data_studio.licensing import manager as license_manager
from ai_data_studio.licensing.provenance import (sign_provenance,
                                                 verify_provenance)
from tools import license_admin as admin


class _SignedLicenceCase(unittest.TestCase):
    """Tek kullanimlik bir ana anahtar kurup istemciye onu tanitir."""

    def setUp(self):
        self.master = admin.generate_master_keypair()
        self._patches = [
            mock.patch.object(license_manager, "DEFAULT_PUBLIC_KEY",
                              self.master["public_key"]),
            mock.patch.object(provenance_module, "DEFAULT_PUBLIC_KEY",
                              self.master["public_key"]),
        ]
        for patch in self._patches:
            patch.start()
            self.addCleanup(patch.stop)

        self.token = admin.generate_signed_license(
            admin.build_payload("ADS-PRO-00042", "customer@example.com",
                                "pro", days=365, seats=3),
            self.master["private_key"])
        self.mgr = license_manager.LicenseManager(
            public_key_b64=self.master["public_key"])
        self.info = self.mgr.verify_token(self.token)
        self.fields = {"notice": "synthetic", "rows": "100",
                       "content_sha256": "abc123",
                       "privacy_audit": "not_performed"}


class TestChainOfTrust(_SignedLicenceCase):
    def test_signed_declaration_verifies_end_to_end(self):
        signed = sign_provenance(self.fields, self.info)
        result = verify_provenance(signed, actual_digest="abc123")

        self.assertTrue(result.ok)
        self.assertTrue(result.license_valid)
        self.assertTrue(result.signature_valid)
        self.assertIs(result.content_matches, True)
        self.assertEqual(result.license_key, "ADS-PRO-00042")
        self.assertEqual(result.email, "customer@example.com")

    def test_the_private_report_key_never_reaches_the_declaration(self):
        """Imzali bir raporu denetciye vermek lisansi vermek olmamali."""
        signed = sign_provenance(self.fields, self.info)
        blob = json.dumps(signed)

        self.assertTrue(self.info.report_private_key)
        self.assertNotIn(self.info.report_private_key, blob)
        self.assertNotIn(self.token.split(".")[-1], blob)
        self.assertEqual(len(signed["license_token"].split(".")), 2)

    def test_unlicensed_run_produces_an_unsigned_declaration(self):
        """Lisans yoksa sahte imza uretmeyiz; alanlar dokunulmadan doner."""
        from ai_data_studio.licensing import LicenseInfo

        unsigned = sign_provenance(self.fields, LicenseInfo())
        self.assertNotIn("signature", unsigned)
        self.assertEqual(unsigned, self.fields)

        result = verify_provenance(unsigned, actual_digest="abc123")
        self.assertFalse(result.signed)
        self.assertFalse(result.ok)

    def test_v1_licence_cannot_sign_but_still_works(self):
        v1 = admin.generate_signed_license(
            admin.build_payload("ADS-PRO-OLD", "old@example.com", "pro",
                                lifetime=True),
            self.master["private_key"], with_report_key=False)
        info = self.mgr.verify_token(v1)

        self.assertTrue(info.is_active)
        self.assertFalse(info.can_sign_reports)
        self.assertNotIn("signature", sign_provenance(self.fields, info))


class TestForgeryIsRejected(_SignedLicenceCase):
    def test_changed_data_is_caught(self):
        signed = sign_provenance(self.fields, self.info)
        result = verify_provenance(signed, actual_digest="a-different-digest")

        self.assertFalse(result.ok)
        self.assertIs(result.content_matches, False)
        # İmza hâlâ geçerli: hangi denetimin düştüğü ayrı ayrı raporlanır.
        self.assertTrue(result.signature_valid)

    def test_edited_declaration_breaks_the_signature(self):
        signed = sign_provenance(self.fields, self.info)
        signed["rows"] = "999999"

        result = verify_provenance(signed, actual_digest="abc123")
        self.assertFalse(result.signature_valid)
        self.assertFalse(result.ok)

    def test_a_self_issued_licence_is_rejected(self):
        """Saldirgan kendi ana anahtarini uretirse istemci kabul etmemeli."""
        evil = admin.generate_master_keypair()
        evil_token = admin.generate_signed_license(
            admin.build_payload("ADS-ENT-FAKE", "attacker@evil.invalid",
                                "enterprise", lifetime=True),
            evil["private_key"])
        evil_info = license_manager.LicenseManager(
            public_key_b64=evil["public_key"]).verify_token(evil_token)

        result = verify_provenance(sign_provenance(self.fields, evil_info),
                                   actual_digest="abc123")
        self.assertFalse(result.license_valid)
        self.assertFalse(result.ok)

    def test_a_borrowed_licence_token_does_not_validate_someone_elses_signature(self):
        """Mesru bir token'i baska bir rapora yapistirmak ise yaramamali."""
        evil = admin.generate_master_keypair()
        evil_info = license_manager.LicenseManager(
            public_key_b64=evil["public_key"]).verify_token(
                admin.generate_signed_license(
                    admin.build_payload("ADS-X", "x@evil.invalid", "pro",
                                        lifetime=True),
                    evil["private_key"]))

        legitimate = sign_provenance(self.fields, self.info)
        forged = dict(self.fields)
        forged["license_token"] = legitimate["license_token"]
        forged["signature"] = sign_provenance(
            dict(self.fields), evil_info)["signature"]

        result = verify_provenance(forged, actual_digest="abc123")
        self.assertTrue(result.license_valid)      # token gerçek
        self.assertFalse(result.signature_valid)   # ama imza o lisansın değil
        self.assertFalse(result.ok)


class TestRevocation(_SignedLicenceCase):
    def test_a_revoked_key_is_refused_even_though_it_verifies(self):
        signed = sign_provenance(self.fields, self.info)
        revoked = {"ADS-PRO-00042"}

        with mock.patch.object(provenance_module, "load_revoked_keys",
                               return_value=revoked):
            result = verify_provenance(signed, actual_digest="abc123")
        self.assertTrue(result.signature_valid)
        self.assertTrue(result.revoked)
        self.assertFalse(result.ok)

        with mock.patch.object(license_manager, "load_revoked_keys",
                               return_value=revoked):
            self.assertFalse(self.mgr.verify_token(self.token).is_active)

    def test_a_broken_revocation_file_does_not_lock_everyone_out(self):
        """Bozuk liste yuzunden butun lisanslari kilitlemek daha kotu bir ariza."""
        with mock.patch.object(license_manager.config, "read_text",
                               side_effect=OSError("gone")):
            self.assertEqual(license_manager.load_revoked_keys(), set())


class TestVerifyOutputFiles(_SignedLicenceCase):
    """Uretilen dosyalar dort formatta da dogrulanabilmeli."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _run_pipeline(self, formats, export_pdf=False):
        from ai_data_studio.core import orchestrator
        from ai_data_studio.core.state_manager import StateManager
        from ai_data_studio.tests import fake_llm

        self.state = StateManager(self.tmp / "state.db")
        self.addCleanup(self.state.close)
        cfg = orchestrator.PipelineConfig(
            domain_prompt="x", provider="fake", row_count=300,
            output_dir=self.tmp / "out", write_outputs=True,
            export_formats=formats, provenance_header=True,
            export_pdf=export_pdf)
        iterator = orchestrator.run_pipeline(
            cfg, threading.Event(), self.state,
            llm_client=fake_llm.FakeLLMClient())
        while True:
            try:
                next(iterator)
            except StopIteration as stop:
                return stop.value

    def test_every_format_round_trips_its_digest(self):
        """Float degerler CSV/JSON uzerinden tam gidip gelmeli.

        pandas'in varsayilan CSV ayristiricisi ve to_json float64'u kayipli
        isliyordu; bu, imza dogru olsa bile icerik ozetini dogrulanamaz
        kiliyordu.
        """
        from ai_data_studio.core.orchestrator import verify_output_file

        with mock.patch.object(license_manager, "_GLOBAL_MANAGER", self.mgr), \
             mock.patch.object(self.mgr, "get_active_license",
                               return_value=self.info):
            result = self._run_pipeline(["csv", "json", "parquet"],
                                        export_pdf=True)

            for kind in ("csv", "json", "parquet", "pdf"):
                with self.subTest(format=kind):
                    path = result.output_paths.get(kind)
                    self.assertIsNotNone(path, "%s ciktisi yok" % kind)
                    verified = verify_output_file(Path(path))
                    self.assertTrue(verified.ok,
                                    "; ".join(verified.problems))

    def test_editing_a_row_is_detected(self):
        from ai_data_studio.core.orchestrator import verify_output_file

        with mock.patch.object(license_manager, "_GLOBAL_MANAGER", self.mgr), \
             mock.patch.object(self.mgr, "get_active_license",
                               return_value=self.info):
            result = self._run_pipeline(["csv"])

        csv_path = Path(result.output_paths["csv"])
        lines = csv_path.read_text(encoding="utf-8").splitlines()
        header = [line for line in lines if line.startswith("#")]
        body = [line for line in lines if not line.startswith("#")]
        body[1] = "999999," + body[1].split(",", 1)[1]

        tampered = self.tmp / "tampered.csv"
        tampered.write_text("\n".join(header + body) + "\n", encoding="utf-8")

        verified = verify_output_file(tampered)
        self.assertTrue(verified.signature_valid)
        self.assertIs(verified.content_matches, False)
        self.assertFalse(verified.ok)


if __name__ == "__main__":
    unittest.main()
