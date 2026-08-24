# -*- coding: utf-8 -*-
"""Küçük arayüz yardımcıları - CustomTkinter'in eksik bıraktığı yerleşim ayarları."""
from __future__ import annotations

import customtkinter as ctk

# Uygulama genelinde tek yerden yönetilen renkler.
COLOR_OK = "#81c784"
COLOR_WARN = "#ffb74d"
COLOR_ERROR = "#e57373"
COLOR_INFO = "#4fc3f7"
COLOR_MUTED = "#8a8a8a"


def left_align_tabs(tabview: ctk.CTkTabview, padx: int = 10) -> None:
    """Sekme başlıklarını ortalamak yerine sola yaslar.

    CTkTabview segmented button'ı varsayılan olarak ortalar; bu, sekmeleri
    ekranın ortasında yüzen bir ada gibi gösterip hiyerarşiyi bozuyor.
    Yalnızca yerleşimi değiştiriyoruz - widget'in kendisine dokunmuyoruz.
    """
    button = getattr(tabview, "_segmented_button", None)
    if button is None:                      # CustomTkinter iç yapısı değişirse sessizce geç
        return
    try:
        info = button.grid_info()
        button.grid(row=info.get("row", 0), column=info.get("column", 0),
                    columnspan=info.get("columnspan", 1),
                    sticky="w", padx=padx, pady=info.get("pady", 0))
    except Exception:
        pass


def show_if(widget, visible: bool) -> None:
    """Widget'i grid'de tutar ya da yer kaplamadan gizler.

    Boş bir durum etiketinin yine de satır yüksekliği kaplaması, arayüzde
    açıklanamayan boşluklara yol açıyordu.
    """
    try:
        if visible:
            widget.grid()
        else:
            widget.grid_remove()
    except Exception:
        pass


def status_dot(parent, text: str = "Hazır", color: str = COLOR_MUTED):
    """Sağ üstte 'nokta + metin' biçiminde durum göstergesi döndürür.

    Döner: (kapsayıcı_frame, nokta_label, metin_label)
    """
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    dot = ctk.CTkLabel(frame, text="●", font=ctk.CTkFont(size=14),
                       text_color=color, width=14)
    dot.pack(side="left", padx=(0, 6))
    label = ctk.CTkLabel(frame, text=text, anchor="w",
                         font=ctk.CTkFont(size=12), text_color=COLOR_MUTED)
    label.pack(side="left")
    return frame, dot, label
