"""Model seçici - sağlayıcı, kimlik durumu ve model listesi kontrolü.

Pipeline ekranından ayrılmadan:
  * Kimlik durumunu görüntüleme (API anahtarı / OAuth oturumu / yok)
  * Doğrudan anahtar girişi veya kimlik doğrulama (AuthDialog)
  * Ollama modellerini listeleme ve yönetme (OllamaDialog)

Ağ sorguları arka plan iş parçacığında yürütülür; sonuçlar post_to_ui ile ana thread'e iletilir.
"""
from __future__ import annotations

import threading
from typing import Callable, Dict, List, Optional

import customtkinter as ctk

from ... import config
from ...i18n import t
from ...services import ollama_service
from ..thread_bridge import post_to_ui
from ..ui_utils import show_if
from .auth_dialog import AuthDialog
from .ollama_dialog import OllamaDialog

PROVIDER_LABELS = {
    config.PROVIDER_ANTHROPIC: "Anthropic (Claude)",
    config.PROVIDER_GEMINI: "Google (Gemini)",
    config.PROVIDER_OLLAMA: t("model.provider.ollama"),
}
LABEL_TO_PROVIDER = {v: k for k, v in PROVIDER_LABELS.items()}

CLOUD_MODELS = {
    config.PROVIDER_ANTHROPIC: ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"],
    config.PROVIDER_GEMINI: ["gemini-2.5-pro", "gemini-2.5-flash"],
}

NO_MODEL = t("model.list.none")
LOADING = t("model.list.loading")

OK_COLOR = "#81c784"
WARN_COLOR = "#ffb74d"
INFO_COLOR = "#4fc3f7"
MUTED = "#8a8a8a"


class ModelSelector(ctk.CTkFrame):
    """Sağlayıcı + kimlik + model seçimi."""

    def __init__(self, master, on_change: Optional[Callable[[str, str], None]] = None,
                 provider: str = config.PROVIDER_ANTHROPIC,
                 model: Optional[str] = None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_change = on_change
        self._provider = provider
        self._ready = False
        self._ready_reason = ""
        # Ollama listesi yuklenirken arka planda doldurulur; None = henuz bilinmiyor.
        self._hardware = None
        self.grid_columnconfigure(1, weight=1)

        # --- saglayici ---------------------------------------------------- #
        ctk.CTkLabel(self, text=t("model.provider")).grid(row=0, column=0, sticky="w",
                                                   padx=(10, 8), pady=(8, 4))
        self.provider_menu = ctk.CTkOptionMenu(
            self, values=list(PROVIDER_LABELS.values()), command=self._on_provider_change)
        self.provider_menu.set(PROVIDER_LABELS.get(provider, PROVIDER_LABELS[
            config.PROVIDER_ANTHROPIC]))
        self.provider_menu.grid(row=0, column=1, columnspan=2, sticky="ew",
                                padx=(0, 10), pady=(8, 4))

        # --- kimlik ------------------------------------------------------- #
        ctk.CTkLabel(self, text=t("model.credential")).grid(row=1, column=0, sticky="w",
                                                padx=(10, 8), pady=4)
        self.auth_label = ctk.CTkLabel(self, text="", anchor="w",
                                       font=ctk.CTkFont(size=11))
        self.auth_label.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=4)
        self.auth_button = ctk.CTkButton(self, text=t("model.configure"), width=90,
                                         command=self._open_auth)
        self.auth_button.grid(row=1, column=2, padx=(0, 10), pady=4)

        # --- model -------------------------------------------------------- #
        ctk.CTkLabel(self, text=t("model.model")).grid(row=2, column=0, sticky="w",
                                               padx=(10, 8), pady=4)
        self.model_menu = ctk.CTkComboBox(self, values=[""], command=self._on_model_change)
        self.model_menu.grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=4)
        self.manage_button = ctk.CTkButton(self, text=t("model.manage"), width=90,
                                           command=self._open_ollama)
        self.manage_button.grid(row=2, column=2, padx=(0, 10), pady=4)

        self.status_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11),
                                         text_color=MUTED, anchor="w", justify="left",
                                         wraplength=330)
        self.status_label.grid(row=3, column=0, columnspan=3, sticky="ew",
                               padx=10, pady=(2, 8))
        show_if(self.status_label, False)   # bosken satir yuksekligi kaplamasin

        self.refresh(preferred=model)

    # ------------------------------------------------------------------ #
    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        value = (self.model_menu.get() or "").strip()
        # Yer tutucu girdiler model DEGILDIR. Karsilastirma sabitler uzerinden
        # yapilir; cevrilmis metnin bicimine guvenilemez.
        return "" if value in (NO_MODEL, LOADING) else value

    def is_ready(self) -> bool:
        """Pipeline başlatılabilir mi?"""
        return self._ready

    def readiness_message(self) -> str:
        return self._ready_reason

    # ------------------------------------------------------------------ #
    def _on_provider_change(self, label: str) -> None:
        self._provider = LABEL_TO_PROVIDER.get(label, config.PROVIDER_ANTHROPIC)
        self.refresh()

    def _on_model_change(self, _value: str = "") -> None:
        self._update_readiness()
        if self.on_change is not None:
            self.on_change(self._provider, self.model)

    def refresh(self, preferred: Optional[str] = None) -> None:
        """Kimlik ve model listesini tazeler."""
        is_ollama = self._provider == config.PROVIDER_OLLAMA
        # Bulut saglayicilarda "Modeller" butonunun devre disi bir kopyasini
        # gostermek yerine tamamen gizliyoruz - iki ayni isimli butondan biri
        # hep gri duruyor ve hangisinin ne yaptigi anlasilmiyordu.
        show_if(self.manage_button, is_ollama)
        show_if(self.auth_button, not is_ollama)

        if is_ollama:
            self.auth_label.configure(text=t("model.auth.local"), text_color=MUTED)
            self.model_menu.configure(values=[LOADING])
            self.model_menu.set(LOADING)
            self._set_status(t("model.ollama.checking"), MUTED)
            threading.Thread(target=self._load_ollama, args=(preferred,), daemon=True,
                             name="ollama-model-list").start()
            return

        self._set_status("")          # Ollama'dan kalan mesaji temizle
        self._show_cloud_auth()

        # Gemini CLI yolunda modeller sabit degil - `agy models` ne diyorsa o.
        if (self._provider == config.PROVIDER_GEMINI
                and config.gemini_backend() == config.GEMINI_BACKEND_CLI):
            self.model_menu.configure(values=[LOADING])
            self.model_menu.set(LOADING)
            self._set_status(t("model.agy.loading"), MUTED)
            threading.Thread(target=self._load_agy, args=(preferred,), daemon=True,
                             name="agy-model-list").start()
            return

        models = CLOUD_MODELS.get(self._provider, [])
        default = preferred or config.DEFAULT_MODELS.get(self._provider, "")
        self._apply_models(models, default if default in models else
                           (models[0] if models else ""))

    # ------------------------------------------------------------------ #
    def _load_agy(self, preferred: Optional[str]) -> None:
        """`agy models` cagrisi - alt surec baslatir, arka planda kosmali."""
        from ...services import agy_service
        try:
            models = agy_service.list_models()
        except Exception:  # pragma: no cover - CLI her turlu hatayi verebilir
            models = []
        post_to_ui(self, lambda: self._on_agy_loaded(models, preferred))

    def _on_agy_loaded(self, models, preferred: Optional[str]) -> None:
        if not models:
            self._apply_models([NO_MODEL], NO_MODEL)
            self._set_status(t("model.agy.list_failed"), WARN_COLOR)
            return
        names = [model_id for model_id, _label in models]
        default = preferred if preferred in names else (
            config.DEFAULT_AGY_MODEL if config.DEFAULT_AGY_MODEL in names else names[0])
        self._apply_models(names, default)
        self._set_status(t("model.agy.loaded", count=len(names)), OK_COLOR)

    # ------------------------------------------------------------------ #
    def _show_cloud_auth(self) -> None:
        """Kimliğin API anahtarından mi OAuth'tan mi geldiğini gösterir."""
        cred = config.resolve_credential(self._provider)
        labels = {
            config.KIND_API_KEY: (t("model.auth.api_key"), OK_COLOR),
            config.KIND_AUTH_TOKEN: (t("model.auth.oauth_token"), OK_COLOR),
            config.KIND_SDK_DEFAULT: (t("model.auth.oauth"), INFO_COLOR),
        }
        if cred.kind in labels:
            prefix, color = labels[cred.kind]
            self.auth_label.configure(text="%s - %s" % (prefix, _short(cred.source)),
                                      text_color=color)
            return

        oauth = config.oauth_status(self._provider)
        if not oauth.get("supported"):
            hint = t("model.auth.hint_key_only")
        elif oauth.get("logged_in"):
            hint = t("model.auth.hint_oauth_unset")
        else:
            hint = t("model.auth.hint_key_or_oauth")
        self.auth_label.configure(text=t("model.auth.missing", hint=hint),
                                  text_color=WARN_COLOR)

    def _open_auth(self) -> None:
        AuthDialog(self.winfo_toplevel(), self._provider, on_done=self._after_auth)

    def _after_auth(self) -> None:
        # Diyalogda arka uç değişmiş olabilir (AI Studio <-> Antigravity CLI) ve
        # iki yolun model listeleri tamamen farklıdır. Yalnızca kimlik etiketini
        # tazelemek, listede eski sağlayıcının modelini bırakıyor ve CLI'a
        # "gemini-2.5-pro" gibi tanımadığı bir ad gidiyordu.
        # preferred olarak mevcut seçimi veriyoruz: yeni listede varsa korunur,
        # yoksa _apply_models zaten geçerli bir varsayılana düşer.
        self.refresh(preferred=self.model or None)

    def _open_ollama(self) -> None:
        OllamaDialog(self.winfo_toplevel(), on_done=self._after_ollama,
                     preselect=self.model or None)

    def _after_ollama(self, chosen: Optional[str] = None) -> None:
        self.refresh(preferred=chosen)

    # ------------------------------------------------------------------ #
    def _load_ollama(self, preferred: Optional[str]) -> None:
        try:
            available = ollama_service.is_available()
            models = ollama_service.list_models() if available else []
            version = ollama_service.get_version() if available else None
        except Exception as exc:  # pragma: no cover
            available, models, version = False, [], None
            _ = exc
        # Donanim profili de burada, ARKA PLANDA cikarilir: nvidia-smi bir alt
        # surec caliştiriyor, ana thread'de yapilirsa arayuz donar.
        self._hardware = self._profile_hardware()
        post_to_ui(self, lambda: self._on_ollama_loaded(available, models, version, preferred))

    @staticmethod
    def _profile_hardware():
        """Donanım profili; çıkarılamazsa None (arayüz bu yüzden hiç düşmemeli)."""
        try:
            from ...core.hardware_profiler import profile_hardware
            return profile_hardware()
        except Exception as exc:  # pragma: no cover - psutil/sürücü sorunları
            _ = exc
            return None

    def _on_ollama_loaded(self, available: bool, models: List[Dict],
                          version, preferred: Optional[str]) -> None:
        if not available:
            self._apply_models([NO_MODEL], NO_MODEL)
            self._set_status(t("settings.ollama.down"), WARN_COLOR)
            return
        if not models:
            self._apply_models([NO_MODEL], NO_MODEL)
            self._set_status(t("model.ollama.no_models", version=version or "?"),
                             WARN_COLOR)
            return

        names = [m["name"] for m in models]
        # Kullanicinin secimi her zaman once gelir; yoksa donanima uygun model
        # kuruluysa o secilir. Yanlis boyutta bir model secmek bu projede en sik
        # gorulen basarisizlik nedeni (bkz. hardware_profiler).
        recommended = getattr(self._hardware, "recommended_model", "") if self._hardware else ""
        if preferred in names:
            default = preferred
        elif recommended in names:
            default = recommended
        else:
            default = names[0]
        self._apply_models(names, default)
        sizes = {m["name"]: m["size_gb"] for m in models}
        status = t("model.ollama.installed", version=version or "?", count=len(names),
                   models=", ".join("%s %.1fGB" % (n.split(":")[0], sizes[n])
                                    for n in names[:3]))
        if self._hardware is not None:
            status += "\n" + t(
                "model.hardware.recommendation",
                tier=self._hardware.hardware_tier,
                model=self._hardware.recommended_model,
                note="" if recommended in names else " " + t("model.hardware.not_installed"))
        self._set_status(status, OK_COLOR)

    def _apply_models(self, values: List[str], selected: str) -> None:
        self.model_menu.configure(values=values or [""])
        self.model_menu.set(selected)
        self._on_model_change()

    # ------------------------------------------------------------------ #
    def _set_status(self, text: str, color: str = MUTED) -> None:
        """Durum satirini yazar; metin bossa satiri tamamen gizler."""
        self.status_label.configure(text=text, text_color=color)
        show_if(self.status_label, bool(text))

    def _update_readiness(self) -> None:
        """Başlat butonunun anlamlı bir hata verebilmesi için durumu hesaplar."""
        if not self.model:
            self._ready = False
            self._ready_reason = (
                t("model.ready.no_models")
                if self._provider == config.PROVIDER_OLLAMA
                else t("model.ready.pick_model"))
            return
        if self._provider == config.PROVIDER_OLLAMA:
            self._ready, self._ready_reason = True, ""
            return
        if config.credential_status(self._provider)["configured"]:
            self._ready, self._ready_reason = True, ""
            return
        self._ready = False
        self._ready_reason = t(
            "model.ready.no_credential",
            provider=PROVIDER_LABELS.get(self._provider, self._provider))


def _short(text: str, limit: int = 34) -> str:
    return text if len(text) <= limit else text[:limit - 3] + "..."
