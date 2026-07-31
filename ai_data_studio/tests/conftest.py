r"""Test süiti izolasyonu - kullanıcının canlı veri dizinine asla dokunulmaz.

Bu dosya, herhangi bir test modülü içe aktarılmadan önce pytest tarafından yüklenir.
Burada `AIDATASTUDIO_DATA_DIR` geçici bir dizine yönlendirilir; böylece
`config.APP_DATA_DIR`, `config.DB_PATH`, çıktı/ham/çalışma dizinleri ve ayarlar dosyası
gerçek `%LOCALAPPDATA%\AIDataStudio` yerine tek kullanımlık bir kopyayı gösterir.

Neden gerekli: testler `get_state_manager()` üzerinden uygulamanın canlı
`app_state.db` dosyasını paylaşıyordu. Yoğun koşular (özellikle eşzamanlı yazma
testleri) dosyayı bozup kullanıcının iş geçmişini yok edebiliyor.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Dizin adı "AIDataStudio" olarak korunur: uygulama sözleşmesinin bir parçası ve
# test_services içindeki yol testi bunu doğruluyor.
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="aids_tests_"))
_TEST_DATA_DIR = _TMP_ROOT / "AIDataStudio"
_TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

os.environ["AIDATASTUDIO_DATA_DIR"] = str(_TEST_DATA_DIR)


def _cleanup() -> None:
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


atexit.register(_cleanup)

# Güvenlik ağı: paket conftest'ten önce içe aktarılmışsa (eklenti, IDE koşucusu ya da
# kök conftest yüzünden) modül düzeyindeki yollar hâlâ gerçek dizini gösterir.
# Bu durumda yolları yeniden hesaplayıp yerine koyarız - sessizce canlı veriye
# yazmaktansa açıkça düzeltmek doğrusu.
if "ai_data_studio.config" in sys.modules:  # pragma: no cover - koşucuya bağlı
    _cfg = sys.modules["ai_data_studio.config"]
    _cfg.APP_DATA_DIR = _TEST_DATA_DIR
    _cfg.DB_PATH = _TEST_DATA_DIR / "app_state.db"
    _cfg.OUTPUT_DIR = _TEST_DATA_DIR / "outputs"
    _cfg.RAW_DIR = _TEST_DATA_DIR / "raw"
    _cfg.WORK_DIR = _TEST_DATA_DIR / "work"
    _cfg.LOG_DIR = _TEST_DATA_DIR / "logs"
    _cfg.SETTINGS_PATH = _TEST_DATA_DIR / "settings.json"
    for _d in (_cfg.APP_DATA_DIR, _cfg.OUTPUT_DIR, _cfg.RAW_DIR, _cfg.WORK_DIR, _cfg.LOG_DIR):
        _d.mkdir(parents=True, exist_ok=True)

from ai_data_studio import config  # noqa: E402  (env değişkeni önce ayarlanmalı)

# Yanlış yapılandırma sessizce geçmesin: buradan sonrası gerçek veri dizinine yazamaz.
_resolved = Path(config.APP_DATA_DIR).resolve()
if _resolved != _TEST_DATA_DIR.resolve():  # pragma: no cover - savunma amaçlı
    raise RuntimeError(
        "Test izolasyonu kurulamadı: config.APP_DATA_DIR = %s (beklenen %s). "
        "Testler kullanıcının canlı veritabanını kullanırdı; koşu durduruldu."
        % (_resolved, _TEST_DATA_DIR)
    )
