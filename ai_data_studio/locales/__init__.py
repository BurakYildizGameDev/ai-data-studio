"""Çeviri katalogları.

Her dil bir modül ve tek bir ``MESSAGES`` sözlüğü taşır. Katalog düz Python
olduğu için PyInstaller paketine kendiliğinden girer - derlenecek `.mo` dosyası
yoktur (bkz. ``ai_data_studio/i18n.py``).

Yeni bir dil eklemek: bu dizine ``<kod>.py`` koy, ``MESSAGES`` sözlüğünü
İngilizce katalogdaki anahtarların TAMAMIYLA doldur ve ``i18n.LANGUAGE_NAMES``
sözlüğüne kodu ekle. Eksik anahtarlı katalog testi düşürür.
"""
