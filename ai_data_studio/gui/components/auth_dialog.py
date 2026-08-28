"""Kimlik ayarlama diyaloğu - API anahtarı VEYA OAuth/CLI girişi, uygulama içinden.

Hem Pipeline sekmesinden hem Ayarlar'dan açılır; kullanıcıyı terminale göndermez:
  * API anahtarı  -> gir, kaydet (keyring), test et
  * OAuth / CLI   -> giriş komutunu uygulama başlatır, tamamlanmasını kendisi izler

Sağlayıcı OAuth desteklemiyorsa (Gemini) yöntem seçici hiç gösterilmez; kullanıcıya
çalışmayan bir "giriş yap" düğmesi sunulmaz.

Tüm ağ/CLI işlemleri arka plan thread'inde; arayüz güncellemeleri post_to_ui ile.
"""
from __future__ import annotations

import threading
import webbrowser
from typing import Callable, Optional

import customtkinter as ctk

from ... import config
from ..thread_bridge import post_to_ui

PROVIDER_TITLES = {
    config.PROVIDER_ANTHROPIC: "Anthropic (Claude)",
    config.PROVIDER_GEMINI: "Google (Gemini)",
    "huggingface": "HuggingFace",
}
API_KEY_HELP = {
    config.PROVIDER_ANTHROPIC: "console.anthropic.com -> API Keys",
    config.PROVIDER_GEMINI: "aistudio.google.com/apikey",
    "huggingface": "huggingface.co/settings/tokens",
}

OK_COLOR = "#81c784"
WARN_COLOR = "#ffb74d"
ERR_COLOR = "#e57373"
INFO_COLOR = "#4fc3f7"
MUTED = "#8a8a8a"

# OAuth girisi baslatildiktan sonra tamamlanmasini bekleme suresi
LOGIN_POLL_MS = 2000
LOGIN_POLL_LIMIT = 150          # 150 x 2sn = 5 dakika


class AuthDialog(ctk.CTkToplevel):
    """Tek bir sağlayıcı için kimlik ayarları."""

    def __init__(self, master, provider: str,
                 on_done: Optional[Callable[[], None]] = None):
        super().__init__(master)
        self.provider = provider
        self.on_done = on_done
        self._poll_count = 0

        self.title("%s - kimlik ayarları" % PROVIDER_TITLES.get(provider, provider))
        self.geometry("620x520")
        self.minsize(560, 470)
        self.transient(master)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- mevcut durum ------------------------------------------------ #
        self.current_label = ctk.CTkLabel(
            self, text="", anchor="w", justify="left", wraplength=560,
            font=ctk.CTkFont(size=12))
        self.current_label.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))

        # --- yontem secimi ------------------------------------------------ #
        self.oauth_supported = bool(config.oauth_status(provider).get("supported"))
        # Etiketler sağlayıcıya göre değişir; sabit metin yerine değişkende
        # tutuluyor (Gemini'nin anahtarsız yolu Antigravity CLI'dır).
        self.api_label = "API anahtarı"
        self.oauth_label = ("Antigravity CLI girişi"
                            if provider == config.PROVIDER_GEMINI
                            else "OAuth / CLI girişi")
        self.method = ctk.CTkSegmentedButton(
            self, values=[self.api_label, self.oauth_label],
            command=self._switch_method)
        if self.oauth_supported:
            self.method.grid(row=1, column=0, sticky="ew", padx=18)

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=2, column=0, sticky="nsew", padx=12, pady=10)
        self.body.grid_columnconfigure(0, weight=1)

        self._build_api_frame()
        if self.oauth_supported:
            self._build_oauth_frame()
        else:
            self.oauth_frame = None
            self.oauth_state = None

        # --- alt bar ------------------------------------------------------ #
        self.status = ctk.CTkLabel(self, text="", anchor="w", justify="left",
                                   wraplength=560, font=ctk.CTkFont(size=11))
        self.status.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 6))
        ctk.CTkButton(self, text="Kapat", width=100, command=self._close).grid(
            row=4, column=0, sticky="e", padx=18, pady=(0, 16))

        # Hangi yontem zaten kullaniliyorsa onunla ac
        # Kullanicinin ZATEN kullandigi yontemle ac. KIND_AUTH_TOKEN de OAuth'tur
        # (Claude Code oturumu); eskiden yalnizca KIND_SDK_DEFAULT sayiliyor ve
        # OAuth ile giris yapmis kullaniciya API anahtari formu aciliyordu.
        oauth_kinds = (config.KIND_SDK_DEFAULT, config.KIND_AUTH_TOKEN)
        cred = config.resolve_credential(provider)
        use_oauth = self.oauth_supported and (
            cred.kind in oauth_kinds
            or (cred.kind == config.KIND_NONE
                and config.oauth_status(provider).get("logged_in"))
        )
        self.method.set(self.oauth_label if use_oauth else self.api_label)
        self._switch_method(self.method.get())
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
    # API anahtari
    # ------------------------------------------------------------------ #
    def _build_api_frame(self) -> None:
        frame = ctk.CTkFrame(self.body)
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text="API anahtarını yapıştırın",
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(14, 2))
        help_lines = ["Anahtar Windows Credential Manager'a (keyring) yazılır, "
                      "düz metin dosyaya asla kaydedilmez.",
                      "Almak için: %s" % API_KEY_HELP.get(self.provider, "")]
        note = config.oauth_status(self.provider).get("note")
        if note and not self.oauth_supported:
            help_lines.append(note)
        ctk.CTkLabel(frame, text="\n".join(help_lines),
                     font=ctk.CTkFont(size=11), text_color=MUTED,
                     justify="left", wraplength=520).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 10))

        self.key_entry = ctk.CTkEntry(frame, show="*", height=36,
                                      placeholder_text="anahtarı buraya yapıştırın")
        self.key_entry.grid(row=2, column=0, sticky="ew", padx=(14, 8), pady=6)
        self.show_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(frame, text="Göster", variable=self.show_var, width=70,
                        command=lambda: self.key_entry.configure(
                            show="" if self.show_var.get() else "*")).grid(
            row=2, column=1, padx=(0, 14), pady=6)

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew", padx=14, pady=(6, 14))
        ctk.CTkButton(buttons, text="Kaydet ve test et", height=34,
                      command=self._save_and_test).pack(side="left")
        ctk.CTkButton(buttons, text="Anahtar al", height=34, width=110,
                      fg_color="#3a5a78", hover_color="#46698a",
                      command=self._open_key_page).pack(side="left", padx=(8, 0))
        ctk.CTkButton(buttons, text="Kayıtlı anahtarı sil", height=34, width=150,
                      fg_color="#8b3a3a", hover_color="#a04545",
                      command=self._clear_key).pack(side="left", padx=(8, 0))

        self.api_frame = frame

    def _save_and_test(self) -> None:
        value = self.key_entry.get().strip()
        if not value:
            self._set_status("Önce bir anahtar yapıştırın.", WARN_COLOR)
            return
        if not config.set_api_key(self.provider, value):
            self._set_status("keyring kullanılamıyor - ortam değişkeni kullanmalısınız.",
                             ERR_COLOR)
            return
        if self.provider == config.PROVIDER_GEMINI:
            # Anahtar girildiyse kullanıcı AI Studio yolunu seçmiş demektir;
            # aksi halde CLI seçili kalır ve anahtar hiç kullanılmaz.
            config.set_gemini_backend(config.GEMINI_BACKEND_AISTUDIO)
        self.key_entry.delete(0, "end")
        self._set_status("Kaydedildi, test ediliyor...", INFO_COLOR)
        self.refresh()
        self._test_async()

    def _open_key_page(self) -> None:
        """Anahtar alma sayfasını varsayılan tarayıcıda açar."""
        info = config.oauth_status(self.provider)
        url = info.get("api_key_url") or config.API_KEY_URLS.get(self.provider, "")
        if not url:
            self._set_status("Bu sağlayıcı için anahtar adresi tanımlı değil.", WARN_COLOR)
            return
        webbrowser.open(url)
        self._set_status("Tarayıcıda açıldı: %s" % url, INFO_COLOR)

    def _clear_key(self) -> None:
        config.set_api_key(self.provider, "")
        self._set_status("Kayıtlı anahtar silindi.", MUTED)
        self.refresh()

    # ------------------------------------------------------------------ #
    # OAuth / CLI
    # ------------------------------------------------------------------ #
    def _build_oauth_frame(self) -> None:
        frame = ctk.CTkFrame(self.body)
        frame.grid_columnconfigure(1, weight=1)
        info = config.oauth_status(self.provider)

        is_agy = self.provider == config.PROVIDER_GEMINI
        title = ("Antigravity CLI ile bağlan" if is_agy
                 else "Tarayıcı ile oturum aç")
        subtitle = ("Aşağıdaki komut ayrı bir konsolda çalışır ve tarayıcınızı açar. "
                    "Giriş tamamlanınca bu pencere kendiliğinden güncellenir.")
        if is_agy:
            subtitle = ("Bilgisayarınızdaki Antigravity CLI oturumu kullanılır - "
                        "API anahtarı, GCP projesi veya faturalandırma gerekmez. "
                        "Giriş yapmadıysanız aşağıdaki komut bir konsolda açılır.")
        ctk.CTkLabel(frame, text=title,
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(14, 2))
        ctk.CTkLabel(frame,
                     text=subtitle,
                     font=ctk.CTkFont(size=11), text_color=MUTED,
                     justify="left", wraplength=520).grid(
            row=1, column=0, columnspan=3, sticky="w", padx=14, pady=(0, 8))

        command_text = " ".join(info["command"]) if info["command"] else "-"
        ctk.CTkLabel(frame, text=command_text,
                     font=ctk.CTkFont(family="Consolas", size=12),
                     fg_color="#1f1f1f", corner_radius=6, anchor="w").grid(
            row=2, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 10), ipady=6)

        self.oauth_state = ctk.CTkLabel(frame, text="", anchor="w", justify="left",
                                        wraplength=520, font=ctk.CTkFont(size=11))
        self.oauth_state.grid(row=3, column=0, columnspan=3, sticky="ew", padx=14)

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.grid(row=4, column=0, columnspan=3, sticky="ew", padx=14, pady=10)
        self.login_button = ctk.CTkButton(buttons, text="Giriş yap", height=34,
                                          command=self._start_login)
        self.login_button.pack(side="left")
        ctk.CTkButton(buttons, text="Durumu yenile", height=34, width=130,
                      fg_color="#3a5a78", hover_color="#46698a",
                      command=self.refresh).pack(side="left", padx=(8, 0))
        ctk.CTkButton(buttons, text="Bağlantıyı test et", height=34, width=140,
                      fg_color="#3a5a78", hover_color="#46698a",
                      command=self._test_async).pack(side="left", padx=(8, 0))

        # --- Gemini'ye özel: bu yolu seç + hız uyarısı --------------------- #
        self.use_cli_button = None
        if is_agy:
            agy_box = ctk.CTkFrame(frame)
            agy_box.grid(row=5, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 12))
            agy_box.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                agy_box,
                text=("Not: Antigravity CLI etkileşimli bir ajandır ve her çağrıda "
                      "kendi bağlamını yükler. Tek bir pipeline adımı birkaç dakika "
                      "sürebilir; hız önemliyse AI Studio API anahtarını tercih edin."),
                font=ctk.CTkFont(size=11), text_color=WARN_COLOR,
                justify="left", wraplength=500).grid(
                row=0, column=0, sticky="w", padx=12, pady=(12, 8))

            self.use_cli_button = ctk.CTkButton(
                agy_box, text="Antigravity CLI'ı kullan", height=34,
                command=self._use_agy)
            self.use_cli_button.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.oauth_frame = frame

    def _use_agy(self) -> None:
        """Gemini'yi Antigravity CLI üzerinden kullanmaya geçirir ve doğrular."""
        from ...services import agy_service
        if not agy_service.is_available():
            self._set_status(
                "`agy` komutu bulunamadı. Antigravity CLI'ı kurun: %s"
                % agy_service.INSTALL_URL, ERR_COLOR)
            return
        config.set_gemini_backend(config.GEMINI_BACKEND_CLI)
        self._set_status("Antigravity CLI seçildi. Oturum doğrulanıyor...", INFO_COLOR)
        self.refresh()
        self._test_async()

    def _start_login(self) -> None:
        info = config.oauth_status(self.provider)
        command = info["command"]
        if not command:
            self._set_status("Bu sağlayıcı için CLI girişi yok.", WARN_COLOR)
            return
        if not config.cli_available(command[0]):
            self._set_status(
                "`%s` komutu bulunamadı. Önce kurun: %s" % (command[0], info["install_hint"]),
                ERR_COLOR)
            return
        try:
            config.launch_login_process(command)
        except Exception as exc:
            self._set_status("Giriş başlatılamadı: %s" % exc, ERR_COLOR)
            return

        self.login_button.configure(state="disabled", text="Giriş bekleniyor...")
        self._set_status("Konsol penceresi açıldı. Tarayıcıdan girişi tamamlayın - "
                         "bittiğinde burası kendiliğinden güncellenecek.", INFO_COLOR)
        self._poll_count = 0
        self._poll_login()

    def _poll_login(self) -> None:
        """Giriş tamamlandı mi diye periyodik bakar (kullanıcı 'yenile' demek zorunda kalmasın)."""
        if config.oauth_status(self.provider)["logged_in"]:
            self.login_button.configure(state="normal", text="Giriş yap")
            self._set_status("Giriş başarılı.", OK_COLOR)
            self.refresh()
            self._test_async()
            return
        self._poll_count += 1
        if self._poll_count >= LOGIN_POLL_LIMIT:
            self.login_button.configure(state="normal", text="Giriş yap")
            self._set_status("Giriş tamamlanmadı (zaman aşımı). Tekrar deneyebilirsiniz.",
                             WARN_COLOR)
            return
        post_to_ui(self, self._poll_login, delay_ms=LOGIN_POLL_MS)

    # ------------------------------------------------------------------ #
    def _switch_method(self, value: str) -> None:
        self.api_frame.grid_forget()
        if self.oauth_frame is not None:
            self.oauth_frame.grid_forget()
        target = (self.oauth_frame
                  if (value == self.oauth_label and self.oauth_frame is not None)
                  else self.api_frame)
        target.grid(row=0, column=0, sticky="nsew")

    def refresh(self) -> None:
        """Mevcut kimlik durumunu yeniden okuyup gösterir."""
        status = config.credential_status(self.provider)
        if status["explicit"]:
            text, color = "Su an kullanılan: %s" % status["source"], OK_COLOR
        elif status["configured"]:
            text, color = "Su an kullanılan: %s" % status["source"], INFO_COLOR
        else:
            text = ("Kimlik tanımlı değil. Aşağıdan bir API anahtarı girin veya "
                    "OAuth ile oturum açın.")
            color = WARN_COLOR
        self.current_label.configure(text=text, text_color=color)

        if self.oauth_state is None:
            return
        oauth = config.oauth_status(self.provider)
        if oauth["logged_in"]:
            state, state_color = "Giriş yapılmış - " + oauth["detail"], OK_COLOR
        elif not config.cli_available(oauth["command"][0] if oauth["command"] else ""):
            state = "`%s` kurulu değil - kurulum: %s" % (
                oauth["command"][0] if oauth["command"] else "?", oauth["install_hint"])
            state_color = WARN_COLOR
        else:
            state, state_color = oauth["detail"], WARN_COLOR
        if oauth.get("note"):
            state += "\n" + oauth["note"]
        self.oauth_state.configure(text=state, text_color=state_color)

    def _set_status(self, message: str, color: str = MUTED) -> None:
        self.status.configure(text=message, text_color=color)

    # ------------------------------------------------------------------ #
    def _test_async(self) -> None:
        self._set_status("Bağlantı test ediliyor...", INFO_COLOR)
        threading.Thread(target=self._test_worker, daemon=True,
                         name="auth-test").start()

    def _test_worker(self) -> None:
        ok, detail = test_credential(self.provider)
        post_to_ui(self, lambda: self._set_status(
            ("Başarılı - " if ok else "Başarısız - ") + detail,
            OK_COLOR if ok else ERR_COLOR))

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


def test_credential(provider: str):
    """Kimliği gerçek bir API çağrısıyla doğrular -> (başarılı_mi, açıklama)."""
    try:
        if provider == "huggingface":
            from ...services import hf_service
            token = hf_service.get_token()
            if not token:
                return False, config.missing_credential_message("huggingface")
            info = hf_service._api(token).whoami()
            return True, "Giriş yapıldı: %s" % info.get("name", "?")
        from ...services.cloud_llm_service import create_client
        client = create_client(provider)
        if client.health_check():
            return True, "kaynak: %s" % client.credential.source
        return False, client.last_health_error or "bilinmeyen hata"
    except Exception as exc:
        return False, str(exc)
