"""Windows standalone .exe derleme aracı.

Kullanım:
    .venv\\Scripts\\python.exe build_exe.py            # --onefile (varsayılan)
    .venv\\Scripts\\python.exe build_exe.py --onedir   # Klasör çıktısı (hızlı açılış)
    .venv\\Scripts\\python.exe build_exe.py --console  # Hata ayıklama için konsollu

Neden --collect-all: scipy / sklearn / numpy / pandas C uzantılı kütüphanelerdir.
Standart pyinstaller çağrısı veri dosyalarını ve dinamik DLL bağımlılıklarını
kaçırabilir; collect-all ile runtime bütünlüğü garanti edilir.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "AIDataStudio"
ENTRY = ROOT / "ai_data_studio" / "main.py"

# Gerekli veri paketlerini ve gizli kütüphane bağımlılıklarını eksiksiz topla.
COLLECT_ALL = ["scipy", "sklearn", "numpy", "pandas", "customtkinter", "faker", "pyarrow"]

# PyInstaller'in statik analizle bulamadigi, calisma aninda import edilen moduller.
HIDDEN_IMPORTS = [
    "sklearn.ensemble._iforest",
    "sklearn.utils._typedefs",
    "sklearn.neighbors._partition_nodes",
    "scipy.special.cython_special",
    "scipy._lib.messagestream",
    "pandas._libs.tslibs.base",
    "keyring.backends.Windows",
    "matplotlib.backends.backend_agg",
    "anthropic",
    "google.genai",
    "huggingface_hub",
    # Ceviri kataloglari importlib ile YUKLENIR (bkz. ai_data_studio/i18n.py);
    # PyInstaller'in statik analizi bu cagriyi goremez, elle bildirmek sart.
    "ai_data_studio.locales.en",
    "ai_data_studio.locales.tr",
]

# Paketlemeye gerek olmayan agir/gereksiz bagimliliklar - boyutu ciddi dusurur.
EXCLUDES = [
    "PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "jupyter", "notebook",
    "pytest", "sphinx", "torch", "tensorflow", "matplotlib.backends.backend_qt5agg",
    "matplotlib.backends.backend_tkagg", "tkinter.test", "test",
]


def build(onefile: bool = True, console: bool = False, clean: bool = True) -> int:
    if not ENTRY.exists():
        print("Giris dosyasi bulunamadi: %s" % ENTRY, file=sys.stderr)
        return 1

    if clean:
        for folder in ("build", "dist"):
            path = ROOT / folder
            if path.exists():
                print("Temizleniyor: %s" % path)
                shutil.rmtree(path, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(ENTRY),
        "--name", APP_NAME,
        "--onefile" if onefile else "--onedir",
        "--noconfirm",
        "--clean",
        # Paket koku import edilebilsin (main.py `ai_data_studio.*` import ediyor)
        "--paths", str(ROOT),
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    cmd.append("--console" if console else "--noconsole")

    for package in COLLECT_ALL:
        cmd += ["--collect-all", package]
    for module in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", module]
    for module in EXCLUDES:
        cmd += ["--exclude-module", module]

    icon = ROOT / "ai_data_studio" / "assets" / "icon.ico"
    if icon.exists():
        cmd += ["--icon", str(icon)]

    print("Build baslatiliyor (bu birkac dakika surebilir)...")
    print(" ".join(cmd[:8]), "...\n")
    started = time.perf_counter()
    result = subprocess.run(cmd, cwd=str(ROOT))
    duration = time.perf_counter() - started

    if result.returncode != 0:
        print("\nBuild BASARISIZ (exit %d)" % result.returncode, file=sys.stderr)
        return result.returncode

    target = ROOT / "dist" / (APP_NAME + ".exe" if onefile else APP_NAME)
    print("\n" + "=" * 70)
    print("Build tamamlandi (%.0f sn): %s" % (duration, target))
    if target.exists():
        size = (target.stat().st_size if target.is_file()
                else sum(f.stat().st_size for f in target.rglob("*") if f.is_file()))
        print("Boyut: %.1f MB" % (size / 1024 / 1024))
    print("=" * 70)
    print("\nSONRAKI ADIM - bu testi atlamayin:")
    print("  1. dist/ ciktisini Python KURULU OLMAYAN temiz bir Windows makineye kopyalayin")
    print("  2. Calistirin; pencere aciliyor mu, Ayarlar sekmesi yukleniyor mu bakin")
    print("  3. Kucuk bir pipeline kosun (1000 satir) - pandas/scipy/sklearn DLL'leri")
    print("     ancak gercek bir kosuda yuklenir")
    print("  4. Hata alirsaniz --console ile yeniden build alip traceback'i okuyun")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Data Studio .exe builder")
    parser.add_argument("--onedir", action="store_true",
                        help="Tek dosya yerine klasor cikti (daha hizli acilir)")
    parser.add_argument("--console", action="store_true",
                        help="Konsol penceresini birak (hata ayiklama)")
    parser.add_argument("--no-clean", action="store_true",
                        help="build/ ve dist/ dizinlerini silme")
    args = parser.parse_args()
    return build(onefile=not args.onedir, console=args.console, clean=not args.no_clean)


if __name__ == "__main__":
    raise SystemExit(main())
