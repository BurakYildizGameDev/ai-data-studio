# -*- coding: utf-8 -*-
"""License activation & management dialog.

Allows users to inspect their current edition (Community, Pro, Enterprise),
activate a new offline Ed25519 license key, deactivate an active license,
or visit the checkout/pricing portal.
"""
from __future__ import annotations

import webbrowser
from typing import Callable, Optional

import customtkinter as ctk

from ...i18n import t
from ...licensing import (
    LicenseInfo,
    LicenseStatus,
    LicenseTier,
    get_license_manager,
)

OK_COLOR = "#81c784"
WARN_COLOR = "#ffb74d"
ERR_COLOR = "#e57373"
INFO_COLOR = "#4fc3f7"
MUTED = "#8a8a8a"
CHECKOUT_URL = "https://syntheticdatastudio.com/pricing"


class LicenseDialog(ctk.CTkToplevel):
    """License and edition management dialog window."""

    def __init__(
        self,
        master,
        on_done: Optional[Callable[[], None]] = None,
        highlight_feature: Optional[str] = None,
    ):
        super().__init__(master)
        self.on_done = on_done
        self.highlight_feature = highlight_feature
        self._manager = get_license_manager()

        self.title(t("license.dialog.title"))
        self.geometry("640x540")
        self.minsize(580, 480)
        self.transient(master)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_content()
        self._build_footer()

        self.refresh()
        self.after(120, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 6))
        header.grid_columnconfigure(0, weight=1)

        title_lbl = ctk.CTkLabel(
            header,
            text=t("license.dialog.heading"),
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        )
        title_lbl.grid(row=0, column=0, sticky="w")

        subtitle_lbl = ctk.CTkLabel(
            header,
            text=t("license.dialog.subheading"),
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
            anchor="w",
            wraplength=580,
            justify="left",
        )
        subtitle_lbl.grid(row=1, column=0, sticky="w", pady=(2, 0))

        if self.highlight_feature:
            req_frame = ctk.CTkFrame(self, fg_color="#2b2010", corner_radius=6)
            req_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 8))
            ctk.CTkLabel(
                req_frame,
                text=t("license.error.pro_required", feature=self.highlight_feature),
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=WARN_COLOR,
                anchor="w",
                padx=12,
                pady=8,
            ).pack(fill="x")

    def _build_content(self) -> None:
        self.content_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.content_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=4)
        self.content_frame.grid_columnconfigure(0, weight=1)

        # --- Current Status Card ---
        self.status_card = ctk.CTkFrame(self.content_frame)
        self.status_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.status_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self.status_card,
            text=t("settings.license.title"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 4))

        self.current_tier_label = ctk.CTkLabel(
            self.status_card,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        self.current_tier_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 4))

        self.current_details_label = ctk.CTkLabel(
            self.status_card,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=540,
        )
        self.current_details_label.grid(row=2, column=0, sticky="w", padx=14, pady=(0, 12))

        self.deactivate_button = ctk.CTkButton(
            self.status_card,
            text=t("settings.license.deactivate"),
            width=90,
            fg_color="#8b2525",
            hover_color="#a83232",
            command=self._on_deactivate,
        )
        self.deactivate_button.grid(row=2, column=1, sticky="e", padx=(0, 14), pady=(0, 12))

        # --- License Key Input Card ---
        self.input_card = ctk.CTkFrame(self.content_frame)
        self.input_card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.input_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.input_card,
            text=t("license.dialog.enter_key"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 4))

        ctk.CTkLabel(
            self.input_card,
            text=t("settings.license.note"),
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
            wraplength=540,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 8))

        self.key_entry = ctk.CTkEntry(
            self.input_card,
            height=36,
            placeholder_text=t("settings.license.key_placeholder"),
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.key_entry.grid(row=2, column=0, sticky="ew", padx=(14, 8), pady=4)

        self.activate_button = ctk.CTkButton(
            self.input_card,
            text=t("license.dialog.activate_btn"),
            width=120,
            height=36,
            fg_color="#2e7d32",
            hover_color="#388e3c",
            command=self._on_activate,
        )
        self.activate_button.grid(row=2, column=1, padx=(0, 14), pady=4)

        self.action_status = ctk.CTkLabel(
            self.input_card,
            text="",
            font=ctk.CTkFont(size=11),
            anchor="w",
            wraplength=540,
            justify="left",
        )
        self.action_status.grid(row=3, column=0, columnspan=2, sticky="w", padx=14, pady=(4, 12))

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=20, pady=(4, 16))
        footer.grid_columnconfigure(0, weight=1)

        self.buy_button = ctk.CTkButton(
            footer,
            text=t("license.dialog.buy_btn") + " ↗",
            width=140,
            fg_color="#3a5a78",
            hover_color="#46698a",
            command=self._on_buy,
        )
        self.buy_button.grid(row=0, column=0, sticky="w")

        close_btn = ctk.CTkButton(footer, text="Close", width=100, command=self._close)
        close_btn.grid(row=0, column=1, sticky="e")

    def refresh(self) -> None:
        info = self._manager.get_active_license(force_reload=True)
        if info.is_active:
            tier_name = (
                t("license.tier.enterprise")
                if info.tier == LicenseTier.ENTERPRISE
                else t("license.tier.pro")
            )
            color = "#ba68c8" if info.tier == LicenseTier.ENTERPRISE else OK_COLOR
            self.current_tier_label.configure(
                text="● " + t("settings.license.tier", tier=tier_name),
                text_color=color,
            )
            expiry_str = info.expires_at or "Lifetime"
            details = t(
                "license.dialog.activated_details",
                email=info.email or "Licensed User",
                tier=info.tier.value.upper(),
                expiry=expiry_str,
            )
            if info.features:
                details += f" • Features: {', '.join(info.features)}"
            self.current_details_label.configure(text=details)
            self.deactivate_button.grid()
        else:
            self.current_tier_label.configure(
                text="○ " + t("settings.license.tier", tier=t("license.tier.community")),
                text_color=MUTED,
            )
            msg = info.status_message or t("license.status.missing")
            self.current_details_label.configure(text=msg)
            self.deactivate_button.grid_remove()

    def _on_activate(self) -> None:
        key = self.key_entry.get().strip()
        if not key:
            self.action_status.configure(
                text=t("license.status.invalid_format"),
                text_color=ERR_COLOR,
            )
            return

        info = self._manager.install_license(key)
        if info.status == LicenseStatus.VALID:
            tier_name = info.tier.value.upper()
            self.action_status.configure(
                text=t("license.dialog.success", tier=tier_name),
                text_color=OK_COLOR,
            )
            self.key_entry.delete(0, "end")
            self.refresh()
            if self.on_done is not None:
                try:
                    self.on_done()
                except Exception:
                    pass
        else:
            self.action_status.configure(
                text=info.status_message or t("license.status.signature_failed"),
                text_color=ERR_COLOR,
            )

    def _on_deactivate(self) -> None:
        self._manager.remove_license()
        self.action_status.configure(
            text="License deactivated. Reverted to Community Edition.",
            text_color=INFO_COLOR,
        )
        self.refresh()
        if self.on_done is not None:
            try:
                self.on_done()
            except Exception:
                pass

    def _on_buy(self) -> None:
        webbrowser.open(CHECKOUT_URL)

    def _close(self) -> None:
        if self.on_done is not None:
            try:
                self.on_done()
            except Exception:
                pass
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
