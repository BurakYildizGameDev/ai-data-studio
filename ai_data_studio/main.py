"""AI Synthetic Data Studio - CustomTkinter GUI giriş noktasi.

Çalıştırma:
    python -m ai_data_studio.main          (depo kokunden)
    AIDataStudio.exe                       (PyInstaller ile paketlendiğiçinde)
"""
from __future__ import annotations

import sys
import traceback


def main() -> int:
    try:
        from ai_data_studio import config as _config
        _config.force_utf8_stdio()
    except Exception:
        pass

    try:
        from ai_data_studio.gui.app_window import launch
    except ImportError:
        # PyInstaller --onefile icinde paket koku sys.path'te olmayabilir.
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from ai_data_studio.gui.app_window import launch

    try:
        launch()
        return 0
    except Exception:
        # --noconsole modunda stderr yok; hatayi log dosyasina ve bir dialog'a yaz.
        from ai_data_studio import config

        message = traceback.format_exc()
        try:
            config.write_text(config.LOG_DIR / "crash.log", message)
        except Exception:
            pass
        try:
            import tkinter.messagebox as messagebox
            messagebox.showerror(
                "AI Synthetic Data Studio - Beklenmeyen hata",
                "Uygulama başlatılamadı.\n\n%s\n\nAyrinti: %s"
                % (message.strip().splitlines()[-1], config.LOG_DIR / "crash.log"),
            )
        except Exception:
            if sys.stderr is not None:
                sys.stderr.write(message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
