"""Windows standalone .exe derleme aracı.

Kullanım:
    .venv\\Scripts\\python.exe build_exe.py            # --onefile (varsayılan)
    .venv\\Scripts\\python.exe build_exe.py --onedir   # Klasör çıktısı (hızlı açılış)
    .venv\\Scripts\\python.exe build_exe.py --both     # İkisini birden
    .venv\\Scripts\\python.exe build_exe.py --console  # Hata ayıklama için konsollu

İki dağıtım profili, ikisi de aynı koddan:

  --onefile  dist/AIDataStudio.exe  - tek dosya, e-postayla gönderilir.
             Bedeli açılış süresi: bootloader her çalıştırmada arşivin tamamını
             %TEMP%\\_MEIxxxxx altına açar, uygulama kapanınca siler.
  --onedir   dist/AIDataStudio/     - klasör, zip'lenip ya da kurulumla dağıtılır.
             Açılışta hiçbir şey açılmaz; süre yalnızca kütüphane import'u kadardır.

İkisi farklı adlara yazar, bu yüzden yan yana durabilirler; temizlik de yalnızca
derlenen profilin kendi çıktısını siler.

Neden --collect-all: scipy / sklearn / numpy / pandas C uzantılı kütüphanelerdir.
Standart pyinstaller çağrısı veri dosyalarını ve dinamik DLL bağımlılıklarını
kaçırabilir; collect-all ile runtime bütünlüğü garanti edilir.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "AIDataStudio"
ENTRY = ROOT / "ai_data_studio" / "main.py"

# Gerekli veri paketlerini ve gizli kütüphane bağımlılıklarını eksiksiz topla.
COLLECT_ALL = ["scipy", "sklearn", "numpy", "pandas", "customtkinter", "faker", "pyarrow", "reportlab"]

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
    "ai_data_studio.locales.en",
    "ai_data_studio.locales.tr",
    "ai_data_studio.locales.de",
    "ai_data_studio.locales.fr",
    "ai_data_studio.locales.ja",
    "ai_data_studio.locales.ru",
    "ai_data_studio.locales.zh",
    "ai_data_studio.locales.es",
    "ai_data_studio.locales.hi",
    "ai_data_studio.licensing",
    "ai_data_studio.licensing.manager",
    "ai_data_studio.reporting",
    "ai_data_studio.reporting.pdf_report",
    "ai_data_studio.gui.components.license_dialog",
    # NOT: tools/license_admin.py BILEREK yok - lisans uretimi
    # satici tarafina ait, musteri paketine girmez.
    "reportlab",
    "runpy",
]

# Kod olmayan, calisma aninda okunan dosyalar: (kaynak, exe icindeki hedef dizin).
# --hidden-import yalnizca .py modullerini toplar; bu dosyalar onun disinda kalir.
# Iptal listesi eksik olursa load_revoked_keys() bos kume doner ve iptal edilmis
# anahtarlar exe'de sessizce kabul edilir - bu yuzden acikca eklenir.
DATA_FILES = [
    (ROOT / "ai_data_studio" / "licensing" / "revoked_keys.json", "ai_data_studio/licensing"),
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
        # Yalnizca BU profilin ciktisi silinir. Eskiden dist/ komple gidiyordu,
        # yani onedir derlemesi onefile exe'sini de goturuyordu ve ikisini
        # karsilastirmak icin her seferinde ikisini birden derlemek gerekiyordu.
        targets = [ROOT / "build", ROOT / "dist" / (APP_NAME + ".exe")
                   if onefile else ROOT / "dist" / APP_NAME]
        for path in targets:
            if path.is_dir():
                print("Temizleniyor: %s" % path)
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                print("Temizleniyor: %s" % path)
                path.unlink()

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
    for source, destination in DATA_FILES:
        if not source.exists():
            print("Veri dosyasi bulunamadi: %s" % source, file=sys.stderr)
            return 1
        cmd += ["--add-data", "%s%s%s" % (source, os.pathsep, destination)]

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
    if onefile:
        print("Profil: --onefile (tek dosya). Acilis suresi bootloader'in arsivi")
        print("        %TEMP%\\_MEIxxxxx altina acmasini da icerir.")
    else:
        print("Profil: --onedir (klasor). Acilista arsiv acilmaz; dagitirken")
        print("        klasorun TAMAMI gonderilmelidir, tek basina exe calismaz.")

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
    parser.add_argument("--both", action="store_true",
                        help="Her iki profili de derle (once onefile, sonra onedir)")
    parser.add_argument("--console", action="store_true",
                        help="Konsol penceresini birak (hata ayiklama)")
    parser.add_argument("--no-clean", action="store_true",
                        help="build/ ve dist/ dizinlerini silme")
    args = parser.parse_args()
    if args.both:
        for onefile in (True, False):
            code = build(onefile=onefile, console=args.console,
                         clean=not args.no_clean)
            if code != 0:
                return code
        return 0
    return build(onefile=not args.onedir, console=args.console, clean=not args.no_clean)


if __name__ == "__main__":
    raise SystemExit(main())
