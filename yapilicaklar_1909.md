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

## Yarın yapılacaklar

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

- [ ] Yarın tek yapılacak: `python -m build` çıktısını bir kez daha gözle kontrol et.
      **Dikkat:** `build/` dizini bayatlıyor — kontrolden önce `rm -rf build dist
      ai_data_studio.egg-info` yap, yoksa eski içeriği görürsün (bugün tam olarak bu oldu).

### 3. `build_exe.py` testi

- [ ] `python build_exe.py` çalıştır, hata vermeden bitmeli.
- [ ] Üretilen exe'yi aç: lisans rozeti başlıkta görünüyor mu, lisans diyaloğu açılıyor mu.
- [ ] Exe içinde `tools/` olmadığını doğrula (PyInstaller `--debug imports` çıktısında ara).
- [ ] `revoked_keys.json` exe'ye gömülmüş mü — `--add-data` gerekebilir; `manager.py`
      dosyayı `Path(__file__).parent`'tan okuyor, PyInstaller'da bu `_MEIPASS` altına düşer.
      **Bu muhtemelen çalışmayacak, kontrol et.**
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

- [ ] Svix imza doğrulaması **canlı bir teslimata karşı hiç test edilmedi** — `svix`
      paketi kurulu olmadığı için çapraz doğrulama yapılamadı. İlk gerçek webhook'ta
      doğrula; tutmazsa `{id}.{timestamp}.{body}` birleştirme sırasına bak.

### 6. Küçük işler

- [ ] Bu dosyanın adı `yapilicaklar_1909.md` — repodaki diğer dosya `YAPILACAKLAR.md`.
      Tutarlılık istersen `git mv yapilicaklar_1909.md YAPILACAKLAR_19092026.md`.
- [ ] `docs/` altına kısa bir `provenance.md` yaz: denetçiye verilecek "bu dosyayı nasıl
      doğrularsınız" sayfası. README'deki bölüm başlangıç olarak yeterli.
- [ ] CI'da POSIX izin testi (`test_license_file_is_owner_only_on_posix`) Windows'ta
      atlanıyor; ubuntu matrisinde koştuğunu bir kez gözle doğrula.

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
