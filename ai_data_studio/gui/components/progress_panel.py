"""İlerleme paneli - 7 adımlı pipeline'ın görsel durumu ve işlem kontrol butonları."""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from ...core.orchestrator import STEP_NAMES, TOTAL_STEPS

IDLE_COLOR = "#3a3a3a"
ACTIVE_COLOR = "#1f6aa5"
DONE_COLOR = "#2e7d32"
ERROR_COLOR = "#c62828"


class ProgressPanel(ctk.CTkFrame):
    """Adım rozetleri + ilerleme çubuğu + başlat/iptal butonları."""

    def __init__(self, master, on_start: Callable[[], None],
                 on_cancel: Callable[[], None], **kwargs):
        super().__init__(master, **kwargs)
        self.on_start = on_start
        self.on_cancel = on_cancel
        self.grid_columnconfigure(0, weight=1)

        # --- adim rozetleri --------------------------------------------- #
        steps_frame = ctk.CTkFrame(self, fg_color="transparent")
        steps_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        for i in range(TOTAL_STEPS):
            steps_frame.grid_columnconfigure(i, weight=1)

        self.step_badges = {}
        for step in range(1, TOTAL_STEPS + 1):
            badge = ctk.CTkLabel(
                steps_frame, text=str(step), width=26, height=26, corner_radius=13,
                fg_color=IDLE_COLOR, font=ctk.CTkFont(size=12, weight="bold"),
            )
            badge.grid(row=0, column=step - 1, pady=(0, 2))
            label = ctk.CTkLabel(steps_frame, text=STEP_NAMES[step].split(" ")[0],
                                 font=ctk.CTkFont(size=10), text_color="#8a8a8a")
            label.grid(row=1, column=step - 1)
            self.step_badges[step] = badge

        # --- ilerleme cubugu -------------------------------------------- #
        self.progress_bar = ctk.CTkProgressBar(self, height=14)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(8, 4))
        self.progress_bar.set(0)

        self.status_label = ctk.CTkLabel(self, text="Hazır", anchor="w",
                                         font=ctk.CTkFont(size=12))
        self.status_label.grid(row=2, column=0, sticky="ew", padx=10)

        # --- butonlar ---------------------------------------------------- #
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew", padx=10, pady=(8, 10))
        buttons.grid_columnconfigure(0, weight=1)
        buttons.grid_columnconfigure(1, weight=1)

        self.start_button = ctk.CTkButton(buttons, text="Pipeline'i Başlat", height=36,
                                          command=self.on_start,
                                          font=ctk.CTkFont(size=13, weight="bold"))
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.cancel_button = ctk.CTkButton(buttons, text="İptal", height=36,
                                           command=self.on_cancel, state="disabled",
                                           fg_color="#8b3a3a", hover_color="#a04545")
        self.cancel_button.grid(row=0, column=1, sticky="ew", padx=(5, 0))

    # ------------------------------------------------------------------ #
    def set_running(self, running: bool) -> None:
        self.start_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")

    def update_progress(self, step: int, percent: float, message: str) -> None:
        self.progress_bar.set(max(0.0, min(percent / 100.0, 1.0)))
        self.status_label.configure(text="[%d/%d] %s" % (step, TOTAL_STEPS, message))
        for number, badge in self.step_badges.items():
            if number < step:
                badge.configure(fg_color=DONE_COLOR)
            elif number == step:
                badge.configure(fg_color=ACTIVE_COLOR)
            else:
                badge.configure(fg_color=IDLE_COLOR)

    def set_finished(self, message: str = "Tamamlandı") -> None:
        self.progress_bar.set(1.0)
        self.status_label.configure(text=message)
        for badge in self.step_badges.values():
            badge.configure(fg_color=DONE_COLOR)
        self.set_running(False)

    def set_error(self, message: str, step: Optional[int] = None) -> None:
        self.status_label.configure(text=message)
        if step and step in self.step_badges:
            self.step_badges[step].configure(fg_color=ERROR_COLOR)
        self.set_running(False)

    def reset(self) -> None:
        self.progress_bar.set(0)
        self.status_label.configure(text="Hazır")
        for badge in self.step_badges.values():
            badge.configure(fg_color=IDLE_COLOR)
        self.set_running(False)
