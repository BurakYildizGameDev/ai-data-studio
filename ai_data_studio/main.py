"""AI Synthetic Data Studio - CustomTkinter GUI giriş noktasi.

Çalıştırma:
    python -m ai_data_studio.main          (depo kokunden)
    AIDataStudio.exe                       (PyInstaller ile paketlendiğiçinde)
"""
from __future__ import annotations

import sys
import traceback


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--sandbox-runner":
        from ai_data_studio.core.generator import run_sandbox_child
        return run_sandbox_child(sys.argv[2:])

    try:
        from ai_data_studio import config as _config
        _config.force_utf8_stdio()
    except Exception:
        pass

    # Dil, ilk widget kurulmadan cozulmeli: modul duzeyindeki etiket sozlukleri
    # (orn. pipeline_view.ENGINE_LABELS) import aninda t() cagiriyor.
    try:
        from ai_data_studio import config as _cfg, i18n as _i18n
        _i18n.set_language(_cfg.load_settings().get("language", _i18n.DEFAULT_LANGUAGE))
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
        error_line = message.strip().splitlines()[-1]
        crash_log = config.LOG_DIR / "crash.log"
        try:
            # Cokme i18n'in kendisinden de gelmis olabilir: dialog yine de acilmali.
            from ai_data_studio.i18n import t
            title = t("app.crash.title")
            body = t("app.crash.body", error=error_line, path=crash_log)
        except Exception:
            title = "AI Synthetic Data Studio - Unexpected error"
            body = "The application could not start.\n\n%s\n\nDetails: %s" % (error_line, crash_log)
        try:
            import tkinter.messagebox as messagebox
            messagebox.showerror(title, body)
        except Exception:
            if sys.stderr is not None:
                sys.stderr.write(message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
