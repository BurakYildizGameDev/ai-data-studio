"""Arka plan thread'inden ana thread'e güvenli geçiş köprüsü.

CustomTkinter/Tk widget'lari yalnızca ana thread'den güncellenebilir. Arka plan
thread'leri sonuçlarını `widget.after(0, callback)` ile ana thread'e taşır - ancak
kullanıcı bu sırada pencereyi kapatırsa Tk yorumlayıcısı yok olmuş olur ve `after()`
`RuntimeError: main thread is not in main loop` (veya TclError) firlatir.

post_to_ui() bu yarısı sessizce yutar: pencere yoksa yapılacak bir güncelleme de yoktur.
"""
from __future__ import annotations

import logging
import tkinter
from typing import Any, Callable

log = logging.getLogger(__name__)


def post_to_ui(widget, callback: Callable[[], Any], delay_ms: int = 0) -> bool:
    """callback'i ana thread'de çalıştırmak üzere kuyruğa alır.

    Returns:
        True - kuyruğa alındı; False - pencere kapanmış, güncelleme atlandı.
    """
    try:
        if not widget.winfo_exists():
            return False
        widget.after(delay_ms, lambda: _guarded(widget, callback))
        return True
    except (RuntimeError, tkinter.TclError):
        # Pencere kapaniyor / kapanmis - guncellenecek bir sey yok.
        return False


def _guarded(widget, callback: Callable[[], Any]) -> None:
    """after() tetiklendiğinde widget hâlâ duruyor mu diye son bir kez bakar."""
    try:
        if not widget.winfo_exists():
            return
        callback()
    except tkinter.TclError:
        pass
    except Exception:
        log.exception("Arayüz güncellemesi başarısız")
