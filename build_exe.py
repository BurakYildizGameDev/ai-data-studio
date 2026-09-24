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
import re
import shutil
import subprocess
import sys
import time
import zipfile
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
# Sozlesme sablonlari: modelsiz yolun tamami bunlara bagli.
DATA_FILES += [(path, "ai_data_studio/templates")
               for path in sorted((ROOT / "ai_data_studio" / "templates").glob("*.json"))]
# Lisans metni paketin icinde de bulunmali: PolyForm Noncommercial'in "Notices"
# maddesi, yazilimin bir kopyasini alan herkesin sartlari da almasini sart
# kosuyor - yalnizca depoya koymak bunu karsilamaz. Ticari EULA da ayni
# yere: $19'luk Pro anahtari satan bir paket, anahtarin sartlarini da tasimali.
LICENSE_FILES = [ROOT / "LICENSE", ROOT / "LICENSE-COMMERCIAL.md"]
DATA_FILES += [(path, ".") for path in LICENSE_FILES]

# Paketlemeye gerek olmayan agir/gereksiz bagimliliklar - boyutu ciddi dusurur.
EXCLUDES = [
    "PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "jupyter", "notebook",
    "pytest", "sphinx", "torch", "tensorflow", "matplotlib.backends.backend_qt5agg",
    "matplotlib.backends.backend_tkagg", "tkinter.test", "test",
]


# Zip'e girmemesi gereken artiklar. PyInstaller normalde bunlari uretmez ama
# klasorde elle denenmis bir sey kalmis olabilir; dagitilan arsiv temiz olmali.
ZIP_EXCLUDE_DIRS = {"__pycache__", ".pytest_cache"}
ZIP_EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".log", ".zip")


def project_version() -> str:
    """pyproject.toml'daki surum. Paketi IMPORT etmeden okunur: derleme
    betigi uygulamanin bagimliliklarini yuklemek zorunda kalmasin."""
    try:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return "0.0.0"
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def package_zip(folder: Path) -> Path:
    """onedir klasorunu tek bir dagitim arsivine koyar.

    Arsivin icinde klasor KORUNUR (``AIDataStudio/AIDataStudio.exe``): onedir
    ciktisinda exe yanindaki ``_internal`` olmadan calismaz, duz acilan bir zip
    ise kullanicinin masaustune 9000 dosya doker.
    """
    target = folder.parent / ("%s-%s-win64.zip" % (folder.name, project_version()))
    if target.exists():
        target.unlink()

    written = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob("*")):
            if any(part in ZIP_EXCLUDE_DIRS for part in path.parts):
                continue
            if path.is_dir():
                continue
            if path.suffix.lower() in ZIP_EXCLUDE_SUFFIXES:
                continue
            archive.write(path, folder.name + "/" + str(path.relative_to(folder)).replace(os.sep, "/"))
            written += 1

        # Lisans exe'nin icine de gomulu (DATA_FILES), ama orada _internal/
        # altinda dokuz bin dosyanin arasinda kaliyor. Arsivi acan kisinin
        # bakacagi yerde, exe'nin yaninda da bir kopya dursun.
        for license_file in LICENSE_FILES:
            if license_file.is_file():
                archive.write(license_file, folder.name + "/" + license_file.name)
                written += 1

    size_mb = target.stat().st_size / 1024 / 1024
    print("Dagitim arsivi: %s (%d dosya, %.1f MB)" % (target, written, size_mb))
    return target


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
    parser.add_argument("--zip", action="store_true",
                        help="onedir ciktisini dagitima hazir bir zip'e koy")
    args = parser.parse_args()

    def finish(code: int, onefile: bool) -> int:
        """Onedir ciktisi istendiyse zip'lenir; onefile zaten tek dosya."""
        if code == 0 and args.zip and not onefile:
            folder = ROOT / "dist" / APP_NAME
            if not folder.is_dir():
                print("Zip icin onedir ciktisi bulunamadi: %s" % folder,
                      file=sys.stderr)
                return 1
            package_zip(folder)
        return code

    if args.both:
        for onefile in (True, False):
            code = finish(build(onefile=onefile, console=args.console,
                                clean=not args.no_clean), onefile)
            if code != 0:
                return code
        return 0
    onefile = not args.onedir
    if args.zip and onefile:
        print("--zip yalnizca --onedir (ya da --both) ciktisi icin anlamlidir.",
              file=sys.stderr)
        return 2
    return finish(build(onefile=onefile, console=args.console,
                        clean=not args.no_clean), onefile)


if __name__ == "__main__":
    raise SystemExit(main())
