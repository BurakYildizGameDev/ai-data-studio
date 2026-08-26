"""Konsol log bileşeni - pipeline mesajlarını renkli olarak gösterir.

Yalnızca ana thread'den çağrılır (app_window.poll_queue içinden); worker thread
buraya asla dokunmaz.
"""
from __future__ import annotations

import time
from typing import Optional

import customtkinter as ctk

LEVEL_COLORS = {
    "info": "#d4d4d4",
    "step": "#4fc3f7",
    "success": "#81c784",
    "warning": "#ffb74d",
    "error": "#e57373",
    "muted": "#8a8a8a",
    "substep": "#80deea",
    "detail": "#90caf9",
}


class ConsoleLog(ctk.CTkFrame):
    """Otomatik kaydırmalı, salt okunur log paneli."""

    MAX_LINES = 2000

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Konsol", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, sticky="w"
        )
        ctk.CTkButton(header, text="Temizle", width=70, height=24,
                      command=self.clear).grid(row=0, column=1, sticky="e")

        self.textbox = ctk.CTkTextbox(self, wrap="word", font=ctk.CTkFont(family="Consolas", size=12))
        self.textbox.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.textbox.configure(state="disabled")

        for level, color in LEVEL_COLORS.items():
            self.textbox.tag_config(level, foreground=color)

        self._line_count = 0

    def write(self, message: str, level: str = "info", timestamp: bool = True) -> None:
        """Log satırı ekler ve en alta kaydırır."""
        level = level if level in LEVEL_COLORS else "info"
        prefix = time.strftime("%H:%M:%S  ") if timestamp else ""
        self.textbox.configure(state="normal")
        self.textbox.insert("end", prefix + message + "\n", level)
        self._line_count += 1
        if self._line_count > self.MAX_LINES:
            self.textbox.delete("1.0", "%d.0" % (self.MAX_LINES // 4))
            self._line_count = self.textbox.index("end-1c").split(".")[0]
            self._line_count = int(self._line_count)
        self.textbox.see("end")
        self.textbox.configure(state="disabled")

    def write_separator(self, title: Optional[str] = None) -> None:
        line = "-" * 68 if not title else ("--- %s " % title).ljust(68, "-")
        self.write(line, "muted", timestamp=False)

    def clear(self) -> None:
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")
        self._line_count = 0

    def get_text(self) -> str:
        return self.textbox.get("1.0", "end-1c")
