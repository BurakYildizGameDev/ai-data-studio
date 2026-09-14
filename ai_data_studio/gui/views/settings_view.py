"""Ayarlar ekranı - API anahtarları (keyring), Ollama yönetimi ve varsayılanlar.

API anahtarları düz metin dosyaya yazılmaz; işletim sistemi credential store
(keyring) üzerinde güvenli şekilde saklanır.
"""
from __future__ import annotations

import subprocess
import threading
from typing import Any, Dict

import customtkinter as ctk

from ... import config
from ...i18n import LANGUAGE_NAMES, get_language, t
from ...services import ollama_service
from ..thread_bridge import post_to_ui

KEY_FIELDS = [
    (config.PROVIDER_ANTHROPIC, "Anthropic API Key", "ANTHROPIC_API_KEY"),
    (config.PROVIDER_GEMINI, "Google Gemini API Key", "GEMINI_API_KEY"),
    ("huggingface", "HuggingFace Token", "HF_TOKEN"),
]


class SettingsView(ctk.CTkScrollableFrame):
    def __init__(self, master, on_settings_changed=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_settings_changed = on_settings_changed
        self.grid_columnconfigure(0, weight=1)
        self.settings = config.load_settings()
        row = 0

        # ================= API key'ler ================================== #
        keys_frame = ctk.CTkFrame(self)
        keys_frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(6, 10))
        keys_frame.grid_columnconfigure(1, weight=1)
        row += 1

        ctk.CTkLabel(keys_frame, text=t("settings.keys.title"),
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 2))
        ctk.CTkLabel(keys_frame,
                     text=t("settings.keys.storage_note"),
                     font=ctk.CTkFont(size=11), text_color="#8a8a8a",
                     wraplength=560, justify="left").grid(
            row=1, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 8))

        self.key_entries: Dict[str, ctk.CTkEntry] = {}
        self.key_status: Dict[str, ctk.CTkLabel] = {}
        for i, (provider, label, env_var) in enumerate(KEY_FIELDS):
            grid_row = 2 + i * 2
            ctk.CTkLabel(keys_frame, text=label).grid(
                row=grid_row, column=0, sticky="w", padx=(12, 8), pady=(6, 0))
            entry = ctk.CTkEntry(keys_frame, show="*",
                                 placeholder_text=t("settings.keys.placeholder", env_var=env_var))
            entry.grid(row=grid_row, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))
            button_row = ctk.CTkFrame(keys_frame, fg_color="transparent")
            button_row.grid(row=grid_row, column=2, padx=(0, 12), pady=(6, 0))
            ctk.CTkButton(button_row, text=t("settings.keys.save"), width=64,
                          command=lambda p=provider: self._save_key(p)).pack(side="left")
            ctk.CTkButton(button_row, text=t("settings.keys.test"), width=64, fg_color="#3a5a78",
                          hover_color="#46698a",
                          command=lambda p=provider: self._test_credential(p)).pack(
                side="left", padx=(6, 0))
            ctk.CTkButton(button_row, text="OAuth...", width=70, fg_color="#3a5a78",
                          hover_color="#46698a",
                          command=lambda p=provider: self._open_auth_dialog(p)).pack(
                side="left", padx=(6, 0))
            status = ctk.CTkLabel(keys_frame, text="", font=ctk.CTkFont(size=11), anchor="w")
            status.grid(row=grid_row + 1, column=1, columnspan=2, sticky="w", padx=(0, 12))
            self.key_entries[provider] = entry
            self.key_status[provider] = status
        self._refresh_key_status()

        # ================= OAuth / CLI girisi ============================ #
        oauth_frame = ctk.CTkFrame(self)
        oauth_frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 10))
        oauth_frame.grid_columnconfigure(1, weight=1)
        row += 1

        ctk.CTkLabel(oauth_frame, text=t("settings.oauth.title"),
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 2))
        ctk.CTkLabel(oauth_frame,
                     text=t("settings.oauth.note"),
                     font=ctk.CTkFont(size=11), text_color="#8a8a8a",
                     wraplength=560, justify="left").grid(
            row=1, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 8))

        self.oauth_status_labels = {}
        # Yalnizca gercekten OAuth/CLI girisi olan saglayicilar listelenir.
        # (Gemini yalnizca AI Studio API anahtariyla calisir - calismayan bir
        # "Giris yap" dugmesi gostermek kullaniciyi cikmaza sokuyordu.)
        oauth_fields = [f for f in KEY_FIELDS
                        if config.oauth_status(f[0]).get("supported")]
        for i, (provider, label, _) in enumerate(oauth_fields):
            grid_row = 2 + i * 2
            ctk.CTkLabel(oauth_frame, text=label.replace(" API Key", "").replace(" Token", "")).grid(
                row=grid_row, column=0, sticky="w", padx=(12, 8), pady=(4, 0))
            status = ctk.CTkLabel(oauth_frame, text="", font=ctk.CTkFont(size=11), anchor="w")
            status.grid(row=grid_row, column=1, sticky="ew", padx=(0, 8), pady=(4, 0))
            ctk.CTkButton(oauth_frame, text=t("settings.oauth.login"), width=90,
                          command=lambda p=provider: self._oauth_login(p)).grid(
                row=grid_row, column=2, padx=(0, 12), pady=(4, 0))
            hint = ctk.CTkLabel(oauth_frame, text="", font=ctk.CTkFont(family="Consolas", size=10),
                                text_color="#8a8a8a", anchor="w")
            hint.grid(row=grid_row + 1, column=1, columnspan=2, sticky="ew", padx=(0, 12))
            self.oauth_status_labels[provider] = (status, hint)

        ctk.CTkButton(oauth_frame, text=t("settings.oauth.rescan"), width=110,
                      fg_color="#3a5a78", hover_color="#46698a",
                      command=self._refresh_oauth_status).grid(
            row=2 + len(oauth_fields) * 2, column=2, padx=(0, 12), pady=(8, 12))


        # ================= Ollama ======================================= #
        ollama_frame = ctk.CTkFrame(self)
        ollama_frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 10))
        ollama_frame.grid_columnconfigure(1, weight=1)
        row += 1

        ctk.CTkLabel(ollama_frame, text=t("settings.ollama.title"),
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 6))

        self.ollama_status = ctk.CTkLabel(ollama_frame, text=t("settings.ollama.checking"),
                                          font=ctk.CTkFont(size=11), anchor="w")
        self.ollama_status.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12)
        ctk.CTkButton(ollama_frame, text=t("settings.ollama.refresh"), width=70,
                      command=self.refresh_ollama).grid(row=1, column=2, padx=(0, 12))

        ctk.CTkButton(ollama_frame, text=t("settings.ollama.open_manager"), width=180,
                      command=self._open_ollama_dialog).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 0))
        ctk.CTkLabel(ollama_frame, text=t("settings.ollama.quick_pull")).grid(
            row=3, column=0, sticky="w", padx=(12, 8), pady=(10, 12))
        self.pull_entry = ctk.CTkEntry(ollama_frame, placeholder_text="or: qwen2.5-coder:7b")
        self.pull_entry.grid(row=3, column=1, sticky="ew", padx=(0, 8), pady=(10, 12))
        self.pull_button = ctk.CTkButton(ollama_frame, text=t("settings.ollama.pull"), width=70,
                                         command=self._pull_model)
        self.pull_button.grid(row=3, column=2, padx=(0, 12), pady=(10, 12))

        self.pull_progress = ctk.CTkProgressBar(ollama_frame)
        self.pull_progress.grid(row=4, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 6))
        self.pull_progress.set(0)
        self.pull_status = ctk.CTkLabel(ollama_frame, text="", font=ctk.CTkFont(size=11),
                                        text_color="#8a8a8a", anchor="w")
        self.pull_status.grid(row=5, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 12))

        # ================= Varsayilanlar ================================ #
        defaults_frame = ctk.CTkFrame(self)
        defaults_frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 10))
        defaults_frame.grid_columnconfigure(1, weight=1)
        row += 1

        ctk.CTkLabel(defaults_frame, text=t("settings.defaults.title"),
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(12, 6))

        ctk.CTkLabel(defaults_frame, text=t("settings.defaults.theme")).grid(row=1, column=0, sticky="w",
                                                       padx=(12, 8), pady=6)
        self.appearance_menu = ctk.CTkOptionMenu(
            defaults_frame, values=["dark", "light", "system"], command=self._change_appearance)
        self.appearance_menu.set(self.settings.get("appearance", "dark"))
        self.appearance_menu.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=6)

        ctk.CTkLabel(defaults_frame, text=t("settings.defaults.language")).grid(
            row=2, column=0, sticky="w", padx=(12, 8), pady=6)
        self.language_menu = ctk.CTkOptionMenu(
            defaults_frame, values=list(LANGUAGE_NAMES.values()),
            command=self._change_language)
        self.language_menu.set(LANGUAGE_NAMES.get(get_language(),
                                                  LANGUAGE_NAMES["en"]))
        self.language_menu.grid(row=2, column=1, sticky="w", padx=(0, 12), pady=6)
        self.language_hint = ctk.CTkLabel(
            defaults_frame, text="", font=ctk.CTkFont(size=11), text_color="#4fc3f7",
            anchor="w", wraplength=420, justify="left")
        self.language_hint.grid(row=3, column=1, sticky="ew", padx=(0, 12), pady=(0, 6))
        self.language_hint.grid_remove()

        ctk.CTkLabel(defaults_frame, text=t("settings.defaults.data_dir")).grid(
            row=4, column=0, sticky="w", padx=(12, 8), pady=6)
        path_label = ctk.CTkLabel(defaults_frame, text=str(config.APP_DATA_DIR),
                                  font=ctk.CTkFont(size=11), text_color="#8a8a8a", anchor="w")
        path_label.grid(row=4, column=1, sticky="ew", padx=(0, 12), pady=(6, 12))

        # ================= Maliyet ====================================== #
        cost_frame = ctk.CTkFrame(self)
        cost_frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 10))
        cost_frame.grid_columnconfigure(0, weight=1)
        row += 1
        ctk.CTkLabel(cost_frame, text=t("settings.cost.title"),
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        self.cost_label = ctk.CTkLabel(cost_frame, text="-", anchor="w",
                                       font=ctk.CTkFont(family="Consolas", size=12))
        self.cost_label.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.refresh_ollama()
        self._refresh_oauth_status()

    # ------------------------------------------------------------------ #
    def _refresh_key_status(self) -> None:
        """Kimliğin NEREDEN çözüldüğünü gösterir - keyring, env, ya da SDK profili."""
        for provider, _, _ in KEY_FIELDS:
            status = config.credential_status(provider)
            if status["explicit"]:
                text = t("settings.keys.defined_source", source=status["source"])
                color = "#81c784"
            elif status["configured"]:
                text = t("settings.keys.implicit_source", source=status["source"])
                color = "#4fc3f7"
            else:
                text = "%s (%s)" % (t("settings.keys.missing"),
                                    ", ".join(status["checked_env_vars"]))
                color = "#ffb74d"
            self.key_status[provider].configure(text=text, text_color=color)

    def _test_credential(self, provider: str) -> None:
        """Kimliği gerçek bir API çağrısıyla doğrular (arka planda)."""
        self.key_status[provider].configure(text=t("settings.keys.testing"), text_color="#8a8a8a")
        threading.Thread(target=self._test_worker, args=(provider,), daemon=True,
                         name="credential-test").start()

    def _test_worker(self, provider: str) -> None:
        try:
            if provider == "huggingface":
                ok, detail = self._test_huggingface()
            else:
                from ...services.cloud_llm_service import create_client
                client = create_client(provider)
                ok = client.health_check()
                detail = client.last_health_error if not ok else (
                    t("settings.keys.test_ok", detail=client.credential.source))
        except Exception as exc:
            ok, detail = False, str(exc)
        color = "#81c784" if ok else "#e57373"
        text = detail if ok else t("settings.keys.test_failed", error=detail)
        post_to_ui(self, lambda: self.key_status[provider].configure(
            text=text[:110], text_color=color))

    @staticmethod
    def _test_huggingface():
        from ...services import hf_service
        token = hf_service.get_token()
        if not token:
            return False, config.missing_credential_message("huggingface")
        try:
            info = hf_service._api(token).whoami()
            return True, t("settings.hf.signed_in", name=info.get("name", "?"))
        except Exception as exc:
            return False, t("settings.hf.token_invalid", error=exc)

    def _save_key(self, provider: str) -> None:
        value = self.key_entries[provider].get().strip()
        saved = config.set_api_key(provider, value)
        if not saved:
            self.key_status[provider].configure(
                text=t("settings.keys.save_failed",
                       error=t("settings.keys.keyring_unavailable")),
                text_color="#e57373")
            return
        self.key_entries[provider].delete(0, "end")
        self._refresh_key_status()
        if value:
            # Durum satiri kaynagi zaten gosteriyor; kaydin gerceklestigini de soyle.
            self.key_status[provider].configure(
                text="%s - %s" % (t("settings.keys.saved"),
                                  self.key_status[provider].cget("text")))
        if self.on_settings_changed is not None:
            self.on_settings_changed()

    # ------------------------------------------------------------------ #
    # OAuth / CLI girisi
    # ------------------------------------------------------------------ #
    def _refresh_oauth_status(self) -> None:
        """Her sağlayıcı için CLI oturumu açılmış mi diye bakar."""
        for provider, (status_label, hint_label) in self.oauth_status_labels.items():
            info = config.oauth_status(provider)
            command = " ".join(info["command"])
            if info["logged_in"]:
                status_label.configure(
                    text=t("settings.oauth.logged_in", detail=info["detail"]),
                    text_color="#81c784")
                hint_label.configure(text="")
            elif not info["command"]:
                status_label.configure(text=info["detail"], text_color="#8a8a8a")
                hint_label.configure(text=info.get("note", ""))
            elif not config.cli_available(info["command"][0]):
                status_label.configure(
                    text=t("settings.oauth.not_installed",
                           command=info["command"][0], hint=info["install_hint"]),
                    text_color="#ffb74d")
                hint_label.configure(text=info["install_hint"])
            else:
                status_label.configure(text=info["detail"], text_color="#ffb74d")
                hint_label.configure(text=command + ("   |  " + info["note"] if info["note"] else ""))

    def _open_auth_dialog(self, provider: str) -> None:
        """Pipeline sekmesindekiyle aynı kimlik diyaloğunu açar."""
        from ..components.auth_dialog import AuthDialog
        AuthDialog(self.winfo_toplevel(), provider, on_done=self._after_auth_dialog)

    def _after_auth_dialog(self) -> None:
        self._refresh_key_status()
        self._refresh_oauth_status()
        if self.on_settings_changed is not None:
            self.on_settings_changed()

    def _open_ollama_dialog(self) -> None:
        from ..components.ollama_dialog import OllamaDialog
        OllamaDialog(self.winfo_toplevel(), on_done=lambda *_a: self.refresh_ollama())

    def _oauth_login(self, provider: str) -> None:
        """Giriş komutunu ayrı bir konsol penceresinde başlatır (tarayıcı açılır)."""
        info = config.oauth_status(provider)
        command = info["command"]
        status_label, hint_label = self.oauth_status_labels[provider]
        if not command:
            status_label.configure(text=t("settings.oauth.unsupported"),
                                   text_color="#ffb74d")
            hint_label.configure(text=info.get("note", ""))
            return
        if not config.cli_available(command[0]):
            status_label.configure(text=t("settings.oauth.command_not_found",
                                          command=command[0]),
                                   text_color="#e57373")
            hint_label.configure(text=info["install_hint"])
            return
        status_label.configure(text=t("auth.oauth.console_opened"),
                               text_color="#4fc3f7")
        try:
            config.launch_login_process(command)
        except Exception as exc:
            status_label.configure(text=t("settings.oauth.launch_failed", error=exc),
                                   text_color="#e57373")

    def _change_language(self, label: str) -> None:
        """Dili kaydeder ve yeniden başlatma gerektiğini söyler.

        Widget metinleri canlı değiştirilmiyor: bu boyutta bir arayüzde her
        etiketi yeniden kurmak gereksiz iş ve kırılgan. Ayar kaydedilir, kullanıcı
        uygulamayı yeniden açtığında yeni dil geçerli olur.
        """
        code = next((c for c, name in LANGUAGE_NAMES.items() if name == label), "en")
        config.save_settings({"language": code})
        self.language_hint.configure(text=t("settings.defaults.language_restart"))
        self.language_hint.grid()

    def _change_appearance(self, mode: str) -> None:
        ctk.set_appearance_mode(mode)
        config.save_settings({"appearance": mode})

    # ------------------------------------------------------------------ #
    def refresh_ollama(self) -> None:
        self.ollama_status.configure(text=t("settings.ollama.checking"), text_color="#8a8a8a")
        threading.Thread(target=self._check_ollama, daemon=True,
                         name="ollama-check").start()

    def _check_ollama(self) -> None:
        try:
            if not ollama_service.is_available():
                text, color = t("settings.ollama.daemon_down"), "#ffb74d"
            else:
                models = ollama_service.list_models()
                version = ollama_service.get_version() or "?"
                if models:
                    text = t("settings.ollama.running", version=version, count=len(models))
                else:
                    text = t("settings.ollama.no_models", version=version)
                color = "#81c784"
        except Exception as exc:  # pragma: no cover
            text, color = t("settings.ollama.check_failed", error=exc), "#e57373"
        post_to_ui(self, lambda: self.ollama_status.configure(text=text, text_color=color))

    def _pull_model(self) -> None:
        name = self.pull_entry.get().strip()
        if not name:
            self.pull_status.configure(text=t("settings.ollama.enter_model_name"),
                                       text_color="#ffb74d")
            return
        self.pull_button.configure(state="disabled")
        self.pull_progress.set(0)
        self.pull_status.configure(text=t("settings.ollama.pull_starting"), text_color="#8a8a8a")
        threading.Thread(target=self._pull_worker, args=(name,), daemon=True,
                         name="ollama-pull").start()

    def _pull_worker(self, name: str) -> None:
        def on_progress(event: Dict[str, Any]) -> None:
            percent = event.get("percent")
            status = event.get("status", "")
            post_to_ui(self, lambda: self._update_pull_ui(percent, status))

        try:
            ok = ollama_service.pull_model(name, on_progress=on_progress)
            message = (t("settings.ollama.pull_done", model=name) if ok
                       else t("settings.ollama.pull_failed", model=name))
            color = "#81c784" if ok else "#e57373"
        except Exception as exc:
            message, color = t("settings.ollama.pull_error", error=exc), "#e57373"
        post_to_ui(self, lambda: self._finish_pull(message, color))

    def _update_pull_ui(self, percent, status: str) -> None:
        if percent is not None:
            self.pull_progress.set(percent / 100.0)
            self.pull_status.configure(
                text="%s - %s" % (status, t("common.percent", value="%.1f" % percent)))
        else:
            self.pull_status.configure(text=status)

    def _finish_pull(self, message: str, color: str) -> None:
        self.pull_button.configure(state="normal")
        self.pull_status.configure(text=message, text_color=color)
        self.refresh_ollama()

    # ------------------------------------------------------------------ #
    def update_cost(self, summary: Dict[str, Any]) -> None:
        """Toplam maliyet özetini günceller (veriyi app_window state'ten alır)."""
        self.cost_label.configure(
            text=t(
                "settings.cost.summary",
                calls=format(summary.get("calls", 0), ","),
                input_tokens=format(summary.get("input_tokens", 0), ","),
                output_tokens=format(summary.get("output_tokens", 0), ","),
                cost="%.4f" % summary.get("cost_usd", 0.0),
            )
        )
