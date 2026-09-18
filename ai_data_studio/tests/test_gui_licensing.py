# -*- coding: utf-8 -*-
"""GUI License integration tests: LicenseDialog, AppWindow badge, SettingsView, and PDF export gating."""
from __future__ import annotations

import datetime
import gc
import sys
import time
import tkinter
import unittest
from pathlib import Path
from unittest import mock

from ai_data_studio.licensing.manager import get_license_manager
from tools.license_admin import generate_signed_license
from ai_data_studio.tests.license_keys import (
    install_ephemeral_global_manager,
    restore_global_manager,
)

_TCL_BOOTSTRAP_MARKERS = ("init.tcl", "auto.tcl", "tcl_findlibrary", "tcl8.6")
_TK_CREATE_ATTEMPTS = 4


def make_tk(factory):
    last: Exception | None = None
    for attempt in range(_TK_CREATE_ATTEMPTS):
        try:
            return factory()
        except tkinter.TclError as exc:
            message = str(exc).lower()
            if not any(marker in message for marker in _TCL_BOOTSTRAP_MARKERS):
                raise
            last = exc
            gc.collect()
            time.sleep(0.05 * (attempt + 1))
    raise last  # type: ignore[misc]


try:
    import customtkinter as ctk
    _root = make_tk(ctk.CTk)
    _root.withdraw()
    _root.destroy()
    GUI_AVAILABLE = True
except Exception:
    GUI_AVAILABLE = False


def _create_test_pro_token(private_key: str, email="user@example.com",
                           tier="pro", features=None) -> str:
    """Sign a fixture token with the caller's ephemeral key.

    The key used to be a module-level constant holding the production private
    key; it is now supplied per test so no secret lives in this file.
    """
    tomorrow = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)).isoformat()
    payload = {
        "key": f"ADS-{tier.upper()}-TEST",
        "email": email,
        "tier": tier,
        "features": features or ["audit_pdf", "unlimited_rows"],
        "issued_at": "2026-01-01T00:00:00Z",
        "expires_at": tomorrow,
        "seats": 1,
    }
    return generate_signed_license(payload, private_key)


@unittest.skipUnless(GUI_AVAILABLE, "Headless CI environment without Tkinter")
class TestLicenseDialog(unittest.TestCase):
    def setUp(self):
        self.private_key = install_ephemeral_global_manager()
        self.root = make_tk(ctk.CTk)
        self.root.withdraw()
        self.mgr = get_license_manager()
        self.mgr.remove_license()

    def tearDown(self):
        self.mgr.remove_license()
        restore_global_manager()
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_license_dialog_opens_and_shows_community(self):
        from ai_data_studio.gui.components.license_dialog import LicenseDialog

        dialog = make_tk(lambda: LicenseDialog(self.root))
        try:
            self.assertIn("Community", dialog.current_tier_label.cget("text"))
            self.assertTrue(dialog.activate_button.winfo_exists())
            self.assertTrue(dialog.key_entry.winfo_exists())
        finally:
            dialog.destroy()

    def test_license_dialog_rejects_empty_or_invalid_key(self):
        from ai_data_studio.gui.components.license_dialog import LicenseDialog

        dialog = make_tk(lambda: LicenseDialog(self.root))
        try:
            # Empty key
            dialog._on_activate()
            self.assertIn("Invalid", dialog.action_status.cget("text"))

            # Corrupted key
            dialog.key_entry.delete(0, "end")
            dialog.key_entry.insert(0, "ADS-invalid.key")
            dialog._on_activate()
            self.assertTrue(dialog.action_status.cget("text"))
        finally:
            dialog.destroy()

    def test_license_dialog_activates_pro_token_and_calls_callback(self):
        from ai_data_studio.gui.components.license_dialog import LicenseDialog

        called = []
        dialog = make_tk(lambda: LicenseDialog(self.root, on_done=lambda: called.append(True)))
        try:
            token = _create_test_pro_token(self.private_key, email="alice@company.com", tier="pro")
            dialog.key_entry.insert(0, token)
            dialog._on_activate()

            self.assertTrue(called)
            self.assertIn("Pro", dialog.current_tier_label.cget("text"))
            self.assertTrue(self.mgr.get_active_license().is_pro)

            # Test deactivation
            dialog._on_deactivate()
            self.assertFalse(self.mgr.get_active_license().is_active)
            self.assertIn("Community", dialog.current_tier_label.cget("text"))
        finally:
            dialog.destroy()

    def test_license_dialog_buy_button_opens_browser(self):
        from ai_data_studio.gui.components.license_dialog import LicenseDialog

        dialog = make_tk(lambda: LicenseDialog(self.root))
        try:
            with mock.patch("webbrowser.open") as mock_open:
                dialog._on_buy()
                mock_open.assert_called_once()
        finally:
            dialog.destroy()


@unittest.skipUnless(GUI_AVAILABLE, "Headless CI environment without Tkinter")
class TestAppWindowLicenseIntegration(unittest.TestCase):
    def setUp(self):
        self.private_key = install_ephemeral_global_manager()
        self.mgr = get_license_manager()
        self.mgr.remove_license()
        from ai_data_studio.gui.app_window import AppWindow
        self.app = make_tk(AppWindow)
        self.app.withdraw()

    def tearDown(self):
        self.mgr.remove_license()
        restore_global_manager()
        try:
            self.app.destroy()
        except Exception:
            pass

    def test_header_badge_reflects_community_by_default(self):
        badge_text = self.app.license_badge.cget("text")
        self.assertIn("Community", badge_text)

    def test_header_badge_updates_when_license_changes(self):
        token = _create_test_pro_token(self.private_key, tier="pro")
        self.mgr.install_license(token)
        self.app.refresh_license_badge()
        self.assertIn("PRO", self.app.license_badge.cget("text"))

        ent_token = _create_test_pro_token(self.private_key, tier="enterprise")
        self.mgr.install_license(ent_token)
        self.app.refresh_license_badge()
        self.assertIn("ENTERPRISE", self.app.license_badge.cget("text"))

    def test_settings_view_displays_license_status(self):
        view = self.app.settings_view
        self.assertIn("Community", view.license_tier_label.cget("text"))

        token = _create_test_pro_token(self.private_key, email="dev@enterprise.org", tier="pro")
        self.mgr.install_license(token)
        view.refresh_license_status()
        self.assertIn("Pro", view.license_tier_label.cget("text"))
        self.assertIn("dev@enterprise.org", view.license_details_label.cget("text"))


@unittest.skipUnless(GUI_AVAILABLE, "Headless CI environment without Tkinter")
class TestPipelineViewPDFGating(unittest.TestCase):
    def setUp(self):
        self.private_key = install_ephemeral_global_manager()
        self.mgr = get_license_manager()
        self.mgr.remove_license()
        from ai_data_studio.gui.app_window import AppWindow
        self.app = make_tk(AppWindow)
        self.app.withdraw()
        self.view = self.app.pipeline_view

    def tearDown(self):
        self.mgr.remove_license()
        restore_global_manager()
        try:
            self.app.destroy()
        except Exception:
            pass

    def test_collect_inputs_reflects_pdf_var(self):
        selector = self.view.model_selector
        with mock.patch.object(type(selector), "is_ready", return_value=True):
            self.view.pdf_var.set(False)
            inputs = self.view.collect_inputs()
            self.assertFalse(inputs["export_pdf"])

            self.view.pdf_var.set(True)
            inputs2 = self.view.collect_inputs()
            self.assertTrue(inputs2["export_pdf"])

    def test_pdf_checkbox_toggle_triggers_license_dialog_when_unlicensed(self):
        with mock.patch("ai_data_studio.gui.components.license_dialog.LicenseDialog") as mock_dialog:
            self.view.pdf_var.set(True)
            self.view._on_pdf_check_toggled()
            mock_dialog.assert_called_once()

    def test_export_pdf_button_triggers_dialog_when_unlicensed(self):
        with mock.patch("ai_data_studio.gui.components.license_dialog.LicenseDialog") as mock_dialog:
            self.view._on_export_pdf_click()
            mock_dialog.assert_called_once()

    def test_export_pdf_button_generates_pdf_when_licensed(self):
        import pandas as pd
        import types
        from ai_data_studio.core.schema_contract import SchemaContract

        token = _create_test_pro_token(self.private_key, tier="pro")
        self.mgr.install_license(token)

        schema = SchemaContract.from_dict({
            "domain": "finance",
            "columns": [{"name": "amount", "type": "float", "distribution": "normal", "mean": 100, "std": 10}],
        })
        import tempfile
        tmp_csv = str(Path(tempfile.gettempdir()) / "job_42.csv")
        fake_result = types.SimpleNamespace(
            job_id=42,
            schema=schema,
            dataframe=pd.DataFrame({"amount": [50.0, 100.0, 150.0]}),
            report={"rows_in": 3, "rows_out": 3, "retention_pct": 100.0, "stages": []},
            output_paths={"csv": tmp_csv},
            generation_meta={"attempts": 1, "duration_s": 1.0},
            cost={"cost_usd": 0.0, "calls": 1},
            hub_url="",
        )
        self.view.show_result(fake_result)
        self.assertEqual(self.view.export_pdf_button.cget("state"), "normal")

        with mock.patch("ai_data_studio.reporting.generate_pdf_report") as mock_gen, \
             mock.patch.object(self.view, "_open_file") as mock_open:
            self.view._on_export_pdf_click()
            mock_gen.assert_called_once()
            mock_open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
