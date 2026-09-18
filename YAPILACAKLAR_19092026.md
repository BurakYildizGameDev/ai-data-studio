# 19 Eylül 2026 — Yapılacaklar

18 Eylül'de yapılan güvenlik ve mimari temizliğinin özeti, ardından yarın sırayla
yapılması gerekenler.

---

## 18 Eylül'de yapılanlar

Bir güvenlik denetimi sonucu çıkan **20 bulgu** kapatıldı. Test sayısı 694'ten
**838**'e çıktı, tamamı yeşil. 14 commit, hepsi `main` üzerinde.

### KRİTİK (5)

| # | Bulgu | Commit |
| --- | --- | --- |
| K-1 | Ana imzalama özel anahtarı `test_licensing.py` içinde düz metindi ve commit edilmeyi bekliyordu. Anahtar döndürüldü, testler artık oturumluk anahtar üretiyor | `6cb3dd2`, `fc9a565` |
| K-2 | `AI_DATA_STUDIO_LICENSE_PUBKEY` ortam değişkeni güven kökünü kullanıcıya açıyordu: kendi anahtar çiftini üretip değişkeni set etmek tam Enterprise erişimi veriyordu | `6f17512` |
| K-3 | `contract.domain` dosya adına sanitize edilmeden giriyordu; `../../..` ile çıktı dizininin dışına, çalıştırılabilir `_generator.py` yazdırılabiliyordu | `7cae47b` |
| K-4 | Serbest metin ReportLab `Paragraph`'ına kaçışlanmadan basılıyordu: `<img src>` ile yerel dosya PDF'e gömülüyor, dengesiz etiket rapor üretimini düşürüyordu | `8450a6e` |
| K-5 | PDF denetim raporu pipeline'ın hiç üretmediği üç anahtarı okuyordu (`validation`, `privacy`, `raw_rows`); her rapor sıfır sayımlar ve sabit `0.38 / 0.89 / 0.04` gizlilik değerleri gösteriyordu | `bda132b` |

### ORTA (8)

- **O-1/O-2** Saat geri alma ve ayrıştırılamayan `expires_at` fail-open'ı — `00031a8`
- **O-3** `.license` dosyası POSIX'te 0644 yazılıyordu, artık 0600 — `0f04687`
- **O-4** Polar webhook'u Svix şemasını kullanmıyordu (gerçek bir webhook'u asla
  doğrulayamazdı) + replay penceresi yoktu — `ed352e6`
- **O-5** Provenance beyanı veri setine bağlandı (SHA-256), gizlilik denetimi durumu
  dürüstleşti — `534bbe9`
- **O-6** Sanity checker meşru korelasyonları eziyordu (4 ölçülmüş vaka) — `b072f20`
- **O-7** Provenance JSON yazımı **31.8x** bellek kullanıyordu, 0.9x'e indi — `d3460ad`
- **O-8** Isı haritası pyplot global durumunu iki thread'den sürüyordu — `0d99563`

### DÜŞÜK (5) — `69a8c85`

Lisans eksikliğinde PDF hatasının sessizce yutulması, PDF'in yerel saati "UTC" diye
etiketlemesi (3 saat sapma), provenance CSV'sinin `pandas.read_csv`'yi `ParserError` ile
düşürmesi, transitivity döngüsünün gereksiz `sorted()` çağrıları, keyring servis adı
tutarsızlığı.

### MİMARİ (4) — `fc9a565`

- **M-1** Provenance artık imzalı ve **tamamen çevrimdışı** doğrulanabiliyor.
  Güven zinciri: ana anahtar → lisans payload'ı → rapor public key'i → beyan imzası →
  veri özeti. `--verify-report` ve `api.verify_provenance()`.
- **M-2** `machine_id` (varsayılan `*`) ve `seats` beyan olarak taşınıyor, katı DRM yok.
- **M-3** Heartbeat pas geçildi; `revoked_keys.json` ile çevrimdışı iptal listesi.
- **M-4** `generate_signed_license()` ve webhook doğrulayıcıları `tools/license_admin.py`'a
  taşındı — pakette değil, `build_exe`'de değil.

### Yol boyunca bulunan, denetimde olmayan kusurlar

1. **`pandas.read_csv` float ayrıştırıcısı kayıplı.** `192.01837376109242` dosyaya
   yazılıyor, `...0924` olarak okunuyordu. İçerik özeti bu yüzden hiçbir zaman
   doğrulanamazdı. Okumalar artık `float_precision="round_trip"` kullanıyor.
2. **`pandas.to_json` float64'ü hiçbir `double_precision` ayarında tam yazmıyor.**
   Provenance JSON gövdesi standart kütüphane encoder'ıyla yazılıyor (~6x yavaş, yalnızca
   serh istendiğinde ödeniyor).
3. **`_write_table_files` çıktı dizinini yalnızca provenance açıkken oluşturuyordu**;
   aynı çağrı bayrağa göre çalışıyor ya da `OSError` veriyordu.

---

## 19 Eylül — durum

Güne CI kırmızı başladı: PDF raporu geldiğinden beri (`9ef9018`) altı test işi de
düşüyordu. Sebep tek değil, iki tane ve ikisi de eksik beyan:
`reportlab` hiçbir zaman `requirements.txt`'e yazılmamıştı, üstelik yokken
`class NumberedCanvas(canvas.Canvas)` modül yüklenirken NameError veriyordu — yani
`ai_data_studio.reporting` import'u komple düşüyor, pytest toplama aşamasında
ölüyordu. `cryptography` de yalnızca `google-auth` üzerinden dolaylı geliyordu.
Üçü de düzeltildi (`3bacbe9`), temiz bir venv'de 838 test yeşil.

Aşağıdaki liste bu notun yazıldığı sırayla güncellendi.

### 1. Özel anahtarı kasaya al — **ÖNCE BU** ⚠️

Anahtar 18 Eylül'de terminal çıktısında bir kez verildi ve geçici dosyası silindi.
Başka hiçbir yerde durmuyor.

- [ ] `ADS_LICENSE_PRIVATE_KEY` değerini parola yöneticisine kaydet (1Password / Bitwarden
      / KeePass — "AI Data Studio — licence signing key" adıyla).
- [ ] GitHub Actions secret olarak ekle: repo → Settings → Secrets and variables →
      Actions → `ADS_LICENSE_PRIVATE_KEY`.
- [ ] Kurtarma notu: anahtar kaybolursa `python tools/license_admin.py keygen` ile yeni
      çift üret, `DEFAULT_PUBLIC_KEY`'i güncelle, o güne kadarki tüm lisansları yeniden bas.
- [ ] **Karar:** anahtar 18 Eylül konuşma kaydında düz metin olarak geçti. Kayıt uzun süre
      saklanacaksa bugün `keygen` ile yeni çift üretip döndür — henüz dağıtılmış lisans
      olmadığı için maliyeti sıfır.

### 2. Paketleme — ✅ 18 Eylül'de yapıldı, doğrulandı

`pyproject.toml` zaten `include = ["ai_data_studio*"]` allowlist'i kullanıyor, yani
`tools/` hiçbir zaman wheel'e girmiyordu. Temiz bir derlemeyle doğrulandı:

```
tools/            : YOK (dogru)
test dosyasi      : 0 adet
revoked_keys.json : VAR
```

Bu arada **gerçek bir eksik bulundu ve düzeltildi:** `revoked_keys.json` paket verisine
dahil değildi. Kurulu sürümde `load_revoked_keys()` boş küme dönecek, yani iptal edilmiş
anahtarlar sessizce kabul edilecekti. `[tool.setuptools.package-data]` altına eklendi.

- [x] **19 Eylül:** `rm -rf build dist ai_data_studio.egg-info` sonrası `python -m build`
      ile yeniden derlendi ve wheel açılıp içine bakıldı:
      `tools/` yok, test dosyası 0 adet, `revoked_keys.json` var, `py.typed` var.
      sdist de aynı. Bu madde kapandı.

### 3. `build_exe.py` testi

- [x] `python build_exe.py` çalıştı: 188 sn, `dist/AIDataStudio.exe`, 187 MB, hata yok.
- [x] Exe içinde `tools/` **yok**, `license_admin` **yok**, `ai_data_studio.tests` **yok**,
      `reportlab` var (arşiv 9095 giriş; `CArchiveReader` ile listelendi).
- [x] **`revoked_keys.json` gerçekten gömülmüyordu — tahmin doğruydu, düzeltildi.**
      PyInstaller `--hidden-import` yalnızca `.py` modüllerini topluyor, veri dosyasını
      değil. Ölçüldü: aynı sondayı iki kez derledim, `--add-data` olmadan exe içinde
      `exists: False`, `load_revoked_keys() == set()` — yani iptal edilmiş anahtarlar
      exe'de sessizce kabul ediliyordu; `--add-data` ile `exists: True`,
      `keys == ['ADS-PROBE-0001']`. `build_exe.py`'a `DATA_FILES` eklendi,
      `manager.py` yolu `_MEIPASS` altında da arıyor, üç test eklendi.
- [ ] Üretilen exe'yi aç: lisans rozeti başlıkta görünüyor mu, lisans diyaloğu açılıyor mu.
      (Gözle bakılacak, bende kalan tek exe maddesi bu.)
- [ ] Exe'de PDF dışa aktarımı dene (lisanssız → uyarı, lisanslı → PDF).

### 4. LemonSqueezy ürün ve webhook kurulumu

- [ ] LemonSqueezy hesabında iki ürün aç: **Pro** ve **Enterprise**.
- [ ] Webhook secret'ı üret, `LEMONSQUEEZY_WEBHOOK_SECRET` olarak sakla.
- [ ] Sipariş karşılama akışını yaz: webhook gelir →
      `tools/license_admin.py` `verify_lemonsqueezy_webhook()` ile imzayı doğrula →
      `generate_signed_license()` ile token bas → müşteriye e-postayla gönder.
- [ ] **Tekrar oynatma koruması:** imza doğrulaması replay penceresi kontrol ediyor ama
      "bir kez işlendi" tablosunu çağıran tutmalı. Event id'yi kalıcı bir yerde sakla.
- [ ] Sunucusuz kalmak istiyorsak: webhook'u bir GitHub Action veya tek seferlik bir
      serverless fonksiyon (Cloudflare Worker / Vercel) ile karşıla — kalıcı sunucu değil.
- [ ] Test siparişi ver, uçtan uca token üretimini doğrula.
- [ ] Üretilen token'ı gerçek uygulamada aktive et, `--export-pdf` çalışıyor mu bak.
- [ ] Aynı PDF'i `--verify-report` ile doğrula: üç denetim de PASS olmalı.

### 5. Polar.sh (opsiyonel, LemonSqueezy'den sonra)

- [x] **19 Eylül: çapraz doğrulama yapıldı, imza uyuşuyor.** `svix 2.5.0` kuruldu;
      imzayı kütüphaneye attırıp `verify_polar_webhook()` ile doğruladık, sonra tersini
      yaptık — `svix.verify()` bizim geçerli saydığımızı da kabul ediyor. Gövde
      değiştirilince, `msg_id` değişince ve timestamp eskiyince reddediliyor, rotasyonlu
      başlıkta ikinci imza tutuyor. `{id}.{timestamp}.{body}` sırası doğruymuş.
      Üç test eklendi (`TestPolarAgainstTheRealSvixLibrary`); `svix` yoksa atlanıyor,
      `requirements-dev.txt`'e girdi. CI yalnızca `requirements.txt` kurduğu için orada
      atlanır — yerelde `pip install -r requirements-dev.txt` ile koşar.
- [ ] Geriye kalan tek belirsizlik: Polar'ın **gerçekte** gönderdiği başlık adları ve
      gövdenin birebir baytları. İlk canlı teslimatta ham isteği logla ve bir kez bak.

### 6. Küçük işler

- [x] Dosya adı `YAPILACAKLAR_19092026.md` oldu (`git mv`).
- [x] `docs/provenance.md` yazıldı ve README ile `docs/README.md`'den bağlandı. İçindeki
      bütün çıktılar gerçek: imzasız, imzalı ve veri değiştirilmiş üç durum tek
      kullanımlık bir ana anahtarla üretilip `verify_output_file` ile koşturuldu.
- [ ] CI'da POSIX izin testi (`test_license_file_is_owner_only_on_posix`) Windows'ta
      atlanıyor; ubuntu matrisinde koştuğunu bir kez gözle doğrula. CI bugüne kadar
      kırmızıydı, yani bu hiç görülmedi — `3bacbe9` sonrası ilk yeşil koşuda bak.

---

## Açık bırakılan, bilinçli kararlar

Bunlar eksik değil, **karar**. Koda ve commit mesajlarına da yazıldı.

- **Saat damgası kullanıcının yazabildiği bir dosyada.** Saat geri alma bypass'ını
  imkânsız kılmaz, maliyetini yükseltir. Kesin çözüm sunucu tarafı doğrulamaydı;
  offline-first kalmak için bilinçli olarak alınmadı.
- **Provenance özeti beyanı veriye bağlar, imzalamaz — ama lisanslıysa imzalanır.**
  Lisanssız çıktıda hem veriyi hem başlığı değiştiren biri tutarlı bir dosya üretebilir.
- **Makine bağlama uygulanmıyor.** `machine_id` ve `seats` yalnızca beyan.
- **Community sürümünde PDF yok.** Doğrulama (`--verify-report`) ise bilerek ücretsiz ve
  açık kaynak: denetçinin dosyayı kontrol etmek için lisans alması saçma olurdu.
