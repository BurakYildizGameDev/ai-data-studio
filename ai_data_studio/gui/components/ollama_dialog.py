"""Ollama model yöneticisi - kurulu modeller + indirilebilecekler tek listede.

Kullanıcı hangi modellerin indirilmiş olduğunu, hangilerinin indirilebileceğini ve
her birinin boyutunu tek ekranda görür; indirme ilerlemesi canlı akar.
"""
from __future__ import annotations

import threading
import webbrowser
from typing import Callable, Dict, List, Optional

import customtkinter as ctk

from ... import config
from ...i18n import t

from ...services import ollama_service
from ..thread_bridge import post_to_ui

OK_COLOR = "#81c784"
WARN_COLOR = "#ffb74d"
ERR_COLOR = "#e57373"
INFO_COLOR = "#4fc3f7"
MUTED = "#8a8a8a"

DOWNLOAD_URL = "https://ollama.com/download"
# Kurulumdan sonra cekilecek ilk model. 7B varsayilan ama ilk adim icin 1.5B
# oneriliyor: olculdu, dusuk donanimda calisan ve ise yarayan en kucuk model bu.
FIRST_MODEL = "qwen2.5-coder:1.5b"


class OllamaDialog(ctk.CTkToplevel):
    """Model listesi, indirme ve silme."""

    def __init__(self, master, on_done: Optional[Callable[[], None]] = None,
                 preselect: Optional[str] = None):
        super().__init__(master)
        self.on_done = on_done
        self.preselect = preselect
        self._cancel = threading.Event()
        self._busy = False

        self.title("Ollama modelleri")
        # Sunucu adresi satiri baslikta ~60px yer tutuyor; liste alani ayni
        # kalsin diye pencere o kadar buyutuldu.
        self.geometry("720x640")
        self.minsize(640, 560)
        self.transient(master)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 4))
        header.grid_columnconfigure(0, weight=1)
        self.daemon_label = ctk.CTkLabel(header, text="", anchor="w",
                                         font=ctk.CTkFont(size=12))
        self.daemon_label.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(header, text=t("history.refresh"), width=80, command=self.refresh).grid(
            row=0, column=1)

        # --- sunucu adresi ------------------------------------------------ #
        # Ollama baska bir makinede kosuyor olabilir (tek GPU'lu makineyi
        # paylasmanin en ucuz yolu). Adres ONCEDEN yalnizca OLLAMA_HOST ortam
        # degiskeniyle verilebiliyordu; exe'ye cift tiklayan kullanicinin
        # ulasamayacagi bir yer.
        host_row = ctk.CTkFrame(header, fg_color="transparent")
        host_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        host_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(host_row, text=t("ollama.host.label"), anchor="w",
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=(0, 8))
        self.host_entry = ctk.CTkEntry(
            host_row, placeholder_text=config.OLLAMA_HOST_DEFAULT)
        self.host_entry.insert(0, config.ollama_host())
        self.host_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.host_entry.bind("<Return>", lambda _event: self._save_host())
        ctk.CTkButton(host_row, text=t("ollama.host.save"), width=90,
                      command=self._save_host).grid(row=0, column=2)
        ctk.CTkLabel(host_row, text=t("ollama.host.remote_hint"), anchor="w",
                     font=ctk.CTkFont(size=10), text_color=MUTED,
                     wraplength=640, justify="left").grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))

        ctk.CTkLabel(self, text=t("ollama.legend"),
                     font=ctk.CTkFont(size=11), text_color=MUTED, anchor="w").grid(
            row=1, column=0, sticky="ew", padx=16, pady=(0, 6))

        self.list_frame = ctk.CTkScrollableFrame(self, label_text=t("model.manage"))
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.list_frame.grid_columnconfigure(0, weight=1)

        # --- elle indirme ------------------------------------------------ #
        manual = ctk.CTkFrame(self)
        manual.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))
        manual.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(manual, text=t("ollama.other_model")).grid(row=0, column=0, sticky="w",
                                                       padx=(12, 8), pady=10)
        self.manual_entry = ctk.CTkEntry(
            manual, placeholder_text=t("ollama.manual_placeholder"))
        self.manual_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=10)
        self.manual_button = ctk.CTkButton(manual, text=t("settings.ollama.pull"), width=90,
                                           command=self._pull_manual)
        self.manual_button.grid(row=0, column=2, padx=(0, 12), pady=10)

        # --- ilerleme ----------------------------------------------------- #
        self.progress = ctk.CTkProgressBar(self)
        self.progress.grid(row=4, column=0, sticky="ew", padx=16)
        self.progress.set(0)
        self.status = ctk.CTkLabel(self, text="", anchor="w", font=ctk.CTkFont(size=11),
                                   text_color=MUTED)
        self.status.grid(row=5, column=0, sticky="ew", padx=16, pady=(4, 4))

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=6, column=0, sticky="ew", padx=16, pady=(0, 14))
        footer.grid_columnconfigure(0, weight=1)
        self.cancel_button = ctk.CTkButton(footer, text=t("ollama.cancel_pull"), width=150,
                                           fg_color="#8b3a3a", hover_color="#a04545",
                                           state="disabled", command=self._cancel_pull)
        self.cancel_button.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(footer, text=t("ollama.close"), width=100, command=self._close).grid(
            row=0, column=1, sticky="e")

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.refresh()
        self.after(120, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        for widget in self.list_frame.winfo_children():
            widget.destroy()
        self.daemon_label.configure(text="Kontrol ediliyor...", text_color=MUTED)
        threading.Thread(target=self._load_worker, daemon=True,
                         name="ollama-catalog").start()

    def _load_worker(self) -> None:
        available = ollama_service.is_available()
        version = ollama_service.get_version() if available else None
        entries = ollama_service.catalog() if available else []
        post_to_ui(self, lambda: self._render(available, version, entries))

    def _render(self, available: bool, version, entries: List[Dict]) -> None:
        if not available:
            self.daemon_label.configure(
                text=t("settings.ollama.down_host", host=config.ollama_host()),
                text_color=ERR_COLOR)
            ctk.CTkLabel(self.list_frame, text=t("ollama.list_unavailable"),
                         text_color=MUTED).grid(row=0, column=0, pady=(24, 4))
            self._render_install_help(row=1)
            return

        installed = [e for e in entries if e["installed"]]
        self.daemon_label.configure(
            text=t("ollama.daemon_running", version=version or "?", count=len(installed)),
            text_color=OK_COLOR)

        row = 0
        for section, want_installed in ((t("ollama.section.installed"), True),
                                        (t("ollama.section.available"), False)):
            subset = [e for e in entries if e["installed"] is want_installed]
            if not subset:
                continue
            ctk.CTkLabel(self.list_frame, text=section, anchor="w",
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=MUTED).grid(row=row, column=0, sticky="ew",
                                                padx=6, pady=(10, 2))
            row += 1
            for entry in subset:
                row = self._render_entry(entry, row)

    def _render_install_help(self, row: int) -> int:
        """Daemon yoksa: indirme baglantisi + ilk modeli ceken komut.

        "Ollama calismiyor" demek, kurulu olmayan kullaniciya hicbir sey
        soylemiyordu. Burada ne indirecegi ve kurduktan sonra hangi komutu
        yazacagi tek ekranda duruyor.
        """
        help_card = ctk.CTkFrame(self.list_frame)
        help_card.grid(row=row, column=0, sticky="ew", padx=4, pady=6)
        help_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(help_card, text=t("ollama.install.hint"), anchor="w",
                     wraplength=600, justify="left",
                     font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 8))

        ctk.CTkButton(help_card, text=t("ollama.install.download"), width=160,
                      command=self._open_download).grid(
            row=1, column=0, sticky="w", padx=12, pady=(0, 10))

        command_row = ctk.CTkFrame(help_card)
        command_row.grid(row=2, column=0, columnspan=2, sticky="ew",
                         padx=12, pady=(0, 12))
        command_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(command_row, text="ollama pull " + FIRST_MODEL, anchor="w",
                     font=ctk.CTkFont(size=12, family="Consolas")).grid(
            row=0, column=0, sticky="ew", padx=(10, 8), pady=8)
        ctk.CTkButton(command_row, text=t("ollama.copy"), width=90,
                      command=self._copy_pull_command).grid(
            row=0, column=1, padx=(0, 10), pady=8)
        return row + 1

    def _open_download(self) -> None:
        try:
            webbrowser.open(DOWNLOAD_URL)
        except Exception as exc:  # pragma: no cover - tarayici yoksa
            self.status.configure(text=str(exc), text_color=ERR_COLOR)

    def _copy_pull_command(self) -> None:
        command = "ollama pull " + FIRST_MODEL
        try:
            self.clipboard_clear()
            self.clipboard_append(command)
            self.update_idletasks()
            self.status.configure(text=t("ollama.copied", text=command),
                                  text_color=OK_COLOR)
        except Exception as exc:  # pragma: no cover - pano yoksa
            self.status.configure(text=str(exc), text_color=ERR_COLOR)

    def _save_host(self) -> None:
        """Adresi ayarlara yazar ve baglantiyi yeniden dener.

        Bos birakmak "ayarlanmadi" demektir: OLLAMA_HOST ortam degiskeni ya da
        varsayilan localhost yeniden gecerli olur.
        """
        raw = self.host_entry.get().strip()
        normalised = config.normalise_ollama_host(raw)
        if raw and not normalised:
            self.status.configure(text=t("ollama.host.invalid", value=raw),
                                  text_color=ERR_COLOR)
            return

        try:
            config.save_settings({"ollama_host": normalised})
        except Exception as exc:
            self.status.configure(text=str(exc), text_color=ERR_COLOR)
            return

        self.host_entry.delete(0, "end")
        self.host_entry.insert(0, config.ollama_host())
        self.status.configure(text=t("ollama.host.saved", host=config.ollama_host()),
                              text_color=OK_COLOR)
        self.refresh()

    def _render_entry(self, entry: Dict, row: int) -> int:
        card = ctk.CTkFrame(self.list_frame)
        card.grid(row=row, column=0, sticky="ew", padx=4, pady=3)
        card.grid_columnconfigure(1, weight=1)

        dot = "●" if entry["installed"] else "○"
        color = OK_COLOR if entry["installed"] else MUTED
        ctk.CTkLabel(card, text=dot, text_color=color, width=20).grid(
            row=0, column=0, rowspan=2, padx=(10, 4))
        ctk.CTkLabel(card, text=entry["name"], anchor="w",
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=1, sticky="ew", padx=(0, 8), pady=(8, 0))
        subtitle = " · ".join(x for x in (entry["size"], entry["detail"]) if x)
        ctk.CTkLabel(card, text=subtitle, anchor="w", font=ctk.CTkFont(size=11),
                     text_color=MUTED).grid(row=1, column=1, sticky="ew",
                                            padx=(0, 8), pady=(0, 8))

        if entry["installed"]:
            ctk.CTkButton(card, text=t("ollama.choose"), width=110,
                          command=lambda n=entry["name"]: self._choose(n)).grid(
                row=0, column=2, rowspan=2, padx=4)
            ctk.CTkButton(card, text=t("ollama.delete"), width=60, fg_color="#8b3a3a",
                          hover_color="#a04545",
                          command=lambda n=entry["name"]: self._delete(n)).grid(
                row=0, column=3, rowspan=2, padx=(0, 10))
        else:
            ctk.CTkButton(card, text=t("settings.ollama.pull"), width=110,
                          command=lambda n=entry["name"]: self._pull(n)).grid(
                row=0, column=2, rowspan=2, padx=(4, 10))
        return row + 1

    # ------------------------------------------------------------------ #
    def _choose(self, name: str) -> None:
        self.preselect = name
        self._close()

    def _delete(self, name: str) -> None:
        try:
            ollama_service.delete_model(name)
            self._set_status(t("ollama.deleted", name=name), MUTED)
        except Exception as exc:
            self._set_status(t("ollama.delete_failed", error=exc), ERR_COLOR)
        self.refresh()

    def _pull_manual(self) -> None:
        name = self.manual_entry.get().strip()
        if not name:
            self._set_status(t("ollama.need_name"), WARN_COLOR)
            return
        self._pull(name)

    def _pull(self, name: str) -> None:
        if self._busy:
            self._set_status(t("ollama.already_pulling"), WARN_COLOR)
            return
        self._busy = True
        self._cancel = threading.Event()
        self.progress.set(0)
        self.manual_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self._set_status(t("ollama.pulling", name=name), INFO_COLOR)
        threading.Thread(target=self._pull_worker, args=(name,), daemon=True,
                         name="ollama-pull").start()

    def _pull_worker(self, name: str) -> None:
        def on_progress(event: Dict) -> None:
            percent = event.get("percent")
            label = event.get("status", "")
            post_to_ui(self, lambda: self._update_progress(percent, label, name))

        try:
            ok = ollama_service.pull_model(name, on_progress=on_progress,
                                           cancel_event=self._cancel)
            if self._cancel.is_set():
                message, color = t("ollama.pull_cancelled"), WARN_COLOR
            elif ok:
                message, color = t("ollama.pulled", name=name), OK_COLOR
            else:
                message, color = t("ollama.pull_failed", name=name), ERR_COLOR
        except Exception as exc:
            message, color = t("app.error.prefix", message=exc), ERR_COLOR
        post_to_ui(self, lambda: self._finish_pull(message, color, name))

    def _update_progress(self, percent, label: str, name: str) -> None:
        if percent is not None:
            self.progress.set(percent / 100.0)
            self._set_status("%s - %s  %s" % (name, label,
                                               t("common.percent", value="%.1f" % percent)),
                             INFO_COLOR)
        else:
            self._set_status("%s - %s" % (name, label), INFO_COLOR)

    def _finish_pull(self, message: str, color: str, name: str) -> None:
        self._busy = False
        self.manual_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.progress.set(1.0 if color == OK_COLOR else 0)
        self._set_status(message, color)
        if color == OK_COLOR:
            self.preselect = name
        self.refresh()

    def _cancel_pull(self) -> None:
        self._cancel.set()
        self._set_status(t("ollama.cancelling"), WARN_COLOR)

    def _set_status(self, message: str, color: str = MUTED) -> None:
        self.status.configure(text=message, text_color=color)

    def _close(self) -> None:
        self._cancel.set()
        if self.on_done is not None:
            try:
                self.on_done(self.preselect)
            except TypeError:
                self.on_done()
            except Exception:
                pass
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
