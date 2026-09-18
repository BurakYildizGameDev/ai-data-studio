# -*- coding: utf-8 -*-
"""Türkçe katalog.

Anahtarlar ASCII kalır, değerler tam Türkçe olur. İngilizce katalogdaki her
anahtarın burada da karşılığı olmalı; eksik anahtar `tests/test_i18n.py`
tarafından yakalanır.
"""

MESSAGES = {
    # --- Ayarlar ekranı --------------------------------------------------- #
    "settings.keys.title": "API Anahtarları",
    "settings.keys.storage_note": (
        "Anahtarlar işletim sisteminin kimlik deposunda (keyring) saklanır, "
        "hiçbir zaman düz metin dosyaya yazılmaz."
    ),
    "settings.keys.save": "Kaydet",
    "settings.keys.test": "Test",
    "settings.keys.get_key": "Anahtar al",
    "settings.keys.placeholder": "(boş bırakılırsa {env_var} kullanılır)",
    "settings.keys.defined_source": "Tanımlı - kaynak: {source}",
    "settings.keys.implicit_source": "Anahtar girilmemiş ama {source} bulundu - denenecek",
    "settings.keys.missing": "Tanımlı değil",
    "settings.keys.saved": "Kimlik deposuna kaydedildi",
    "settings.keys.keyring_unavailable": "kimlik deposu kullanılamıyor - ortam değişkeni kullanın",
    "settings.keys.save_failed": "Kaydedilemedi: {error}",
    "settings.keys.testing": "Test ediliyor...",
    "settings.keys.test_ok": "Bağlantı başarılı - {detail}",
    "settings.keys.test_failed": "Başarısız: {error}",

    "settings.oauth.title": "OAuth / CLI ile Giriş",
    "settings.oauth.note": (
        "API anahtarı yerine tarayıcıdan oturum açabilirsiniz. Giriş komutu ayrı "
        "bir konsol penceresinde çalışır; bittikten sonra 'Yeniden tara' deyin."
    ),
    "settings.oauth.rescan": "Yeniden tara",
    "settings.oauth.login": "Giriş yap",
    "settings.oauth.logged_in": "Giriş yapılmış - {detail}",
    "settings.oauth.not_installed": "{command} kurulu değil ({hint})",
    "settings.oauth.not_logged_in": "Giriş yapılmamış",

    "settings.ollama.title": "Ollama (yerel modeller)",
    "settings.ollama.checking": "Kontrol ediliyor...",
    "settings.ollama.refresh": "Yenile",
    "settings.ollama.open_manager": "Model yöneticisini aç",
    "settings.ollama.quick_pull": "Hızlı indir",
    "settings.ollama.pull": "İndir",
    "settings.ollama.running": "Ollama {version} çalışıyor - {count} model kurulu",
    "settings.ollama.down": "Ollama daemon çalışmıyor. Başlatmak için: ollama serve",
    "settings.ollama.down_host": "Ollama servisi {host} adresinde yanıt vermiyor. Başlatmak için: ollama serve",
    "ollama.host.label": "Sunucu adresi",
    "ollama.host.save": "Kaydet",
    "ollama.host.saved": "Sunucu adresi kaydedildi: {host}",
    "ollama.host.invalid": "Bu adres okunamadı: {value}",
    "ollama.host.remote_hint": "Ollama başka bir makinede çalışabilir: adresini yazın (örn. http://192.168.1.20:11434) ve o makinede servisi OLLAMA_HOST=0.0.0.0 ollama serve ile başlatın. Kutuyu boş bırakırsanız OLLAMA_HOST ortam değişkeni geçerli olur.",
    "ollama.install.hint": "Ollama kurulu değil mi? İndirip kurun, sonra bir terminalde ilk modeli çekin:",
    "ollama.install.download": "Ollama'yı indir",
    "ollama.copy": "Kopyala",
    "ollama.copied": "Kopyalandı: {text}",

    "settings.defaults.title": "Varsayılanlar",
    "settings.defaults.theme": "Tema",
    "settings.defaults.language": "Dil",
    "settings.defaults.language_restart": (
        "Dil, uygulamayı bir sonraki açışınızda değişir."
    ),
    "settings.defaults.data_dir": "Veri dizini",

    "settings.cost.title": "LLM Maliyet Özeti",
    # --- Grafikler -------------------------------------------------------- #
    "charts.panel.title": "Validasyon Grafikleri",
    "charts.panel.placeholder": "Pipeline çalıştırıldıktan sonra grafikler burada görünür.",
    "charts.panel.empty": "Grafik üretilemedi.",
    "charts.retention.title": "Validasyon aşamaları",
    "charts.retention.x_label": "Ayıklanan satır",
    "charts.distribution.title": "{column} dağılımı",
    "charts.distribution.y_label": "Frekans",
    "charts.correlation.title": "Korelasyon matrisi",

    # --- İlerleme paneli --------------------------------------------------- #
    "progress.status.ready": "Hazır",
    "progress.status.finished": "Tamamlandı",
    "progress.button.start": "Pipeline'i Başlat",
    "progress.button.cancel": "İptal",
    # --- Ana pencere ------------------------------------------------------ #
    "app.tab.pipeline": "Pipeline",
    "app.tab.history": "Geçmiş",
    "app.tab.settings": "Ayarlar",
    "app.console.ready": "AI Synthetic Data Studio hazır.",
    "app.console.data_dir": "Veri dizini: {path}",
    "app.console.checkpoint": "Checkpoint kaydedildi: adım {step}",
    "app.console.db_recovered": (
        "Durum veritabanı bozuktu ve yeniden oluşturuldu; iş geçmişi sıfırlandı. "
        "Bozuk dosyanın yedeği: {path}"
    ),
    "app.resume.title": "Yarım kalmış iş",
    "app.resume.message": (
        "Job #{job_id} ({domain}) yarıda kalmış.\n\n"
        "Adım {step}/7 - {step_name}\nÜretilmiş satır: {rows}\n\n"
        "Bu işin ayarlarıyla yeniden başlatılsın mı?"
    ),
    "app.resume.accept": "Evet, ayarları yükle",
    "app.resume.decline": "Hayır",
    "app.resume.declined": "Job #{job_id} devam ettirilmedi.",
    "app.done.separator": "TAMAMLANDI",
    "app.done.summary": "Tamamlandı - {rows} temiz satır",
    "app.done.rows": "Job #{job_id}: {rows_in} ham -> {rows_out} temiz satır (%{retention} korundu)",
    "app.done.cost": "Maliyet: ${cost} ({calls} çağrı, {tokens} token)",
    "app.error.separator": "HATA",
    "app.error.header": "Hata",
    "app.error.prefix": "Hata: {message}",
    "app.error.no_result": "Pipeline sonuç döndürmedi",
    "app.cancelled.status": "İptal edildi",
    "app.cancelled.console": "Pipeline iptal edildi.",
    # --- Model seçici ------------------------------------------------------ #
    "model.provider": "Sağlayıcı",
    "model.provider.ollama": "Ollama (yerel)",
    "model.credential": "Kimlik",
    "model.model": "Model",
    "model.configure": "Ayarla",
    "model.manage": "Modeller",
    "model.list.none": "(kurulu model yok)",
    "model.list.loading": "(yükleniyor...)",
    "model.auth.api_key": "API anahtarı",
    "model.auth.oauth_token": "OAuth token",
    "model.auth.oauth": "OAuth",
    "model.auth.local": "Yerel - kimlik gerekmez",
    "model.auth.missing": "Tanımlı değil - {hint}",
    "model.auth.hint_key_only": "'Ayarla' ile ücretsiz API anahtarı girin",
    "model.auth.hint_oauth_unset": "OAuth girişi var ama ayarlanmamış - 'Ayarla'ya basın",
    "model.auth.hint_key_or_oauth": "anahtar girin veya OAuth ile giriş yapın",
    "model.agy.loading": "Antigravity CLI modelleri alınıyor...",
    "model.agy.list_failed": (
        "Antigravity CLI model listesi alınamadı. Bir terminalde `agy` çalıştırıp "
        "giriş yaptığınızdan emin olun."
    ),
    "model.agy.loaded": (
        "Antigravity CLI: {count} model. Ajan CLI yavaştır - tek adım dakikalar sürebilir."
    ),
    "model.ollama.checking": "Ollama kontrol ediliyor...",
    "model.ollama.installed": (
        "Ollama {version} - {count} model kurulu ({models}). Başkasını indirmek için 'Modeller'."
    ),
    "model.ollama.no_models": (
        "Ollama {version} çalışıyor ama hiç model kurulu değil. 'Modeller' butonundan indirin."
    ),
    "model.hardware.recommendation": "Donanım: {tier} - önerilen model {model}{note}",
    "model.hardware.not_installed": "(kurulu değil)",
    "model.ready.no_models": "Kullanılabilir model yok. 'Modeller' butonundan bir model indirin.",
    "model.ready.pick_model": "Önce bir model seçin.",
    "model.ready.no_credential": (
        "{provider} için kimlik tanımlı değil. 'Ayarla' ile API anahtarı girin veya "
        "OAuth ile giriş yapın."
    ),
    # --- Geçmiş ekranı ----------------------------------------------------- #
    "history.title": "Geçmiş İşler",
    "history.refresh": "Yenile",
    "history.clear": "Temizle",
    "history.jobs": "İşler",
    "history.pick_job": "Soldan bir iş seçin.",
    "history.cleared": "Tüm geçmiş işler temizlendi.",
    "history.empty": "Henüz çalıştırılmış bir iş yok.",
    "history.field.status": "Durum",
    "history.field.domain": "Domain",
    "history.field.prompt": "İstek",
    "history.field.provider": "Sağlayıcı",
    "history.field.created": "Oluşturuldu",
    "history.field.updated": "Güncellendi",
    "history.field.step": "Adım",
    "history.field.seed": "Random seed",
    "history.field.rows_generated": "Üretilen satır",
    "history.field.rows_clean": "Temiz satır",
    "history.field.cost": "LLM maliyeti",
    "history.field.calls": "{calls} çağrı",
    "history.field.output": "Çıktı",
    "history.section.error": "HATA",
    "history.section.schema": "ŞEMA",
    "history.section.validation": "VALİDASYON",
    "history.schema.columns": "Kolonlar: {columns}",
    "history.schema.rule": "kural: {rule}",
    "history.validation.rows": "{rows_in} -> {rows_out} satır (%{retention} korundu)",
    "history.validation.correlation": "korelasyon {pair}: r={r} [{verdict}]",
    "history.verdict.pass": "GEÇTİ",
    "history.verdict.fail": "KALDI",
    # --- Ollama model yöneticisi -------------------------------------------- #
    "ollama.legend": "Yeşil = kurulu (hemen kullanılabilir)   |   Gri = kurulu değil (indirilebilir)",
    "ollama.other_model": "Başka model",
    "ollama.manual_placeholder": "ollama.com/library üzerindeki tam ad, örn. llama3.2:3b",
    "ollama.cancel_pull": "İndirmeyi iptal et",
    "ollama.close": "Kapat",
    "ollama.list_unavailable": "Daemon çalışmadığı için model listesi alınamadı.",
    "ollama.daemon_running": "Ollama {version} çalışıyor - {count} model kurulu",
    "ollama.section.installed": "KURULU",
    "ollama.section.available": "İNDİRİLEBİLİR",
    "ollama.choose": "Seç ve kullan",
    "ollama.delete": "Sil",
    "ollama.deleted": "Silindi: {name}",
    "ollama.delete_failed": "Silinemedi: {error}",
    "ollama.need_name": "Önce bir model adı girin.",
    "ollama.already_pulling": "Zaten devam eden bir indirme var.",
    "ollama.pulling": "İndiriliyor: {name}",
    "ollama.pulled": "İndirildi: {name}",
    "ollama.pull_failed": "İndirilemedi: {name}",
    "ollama.pull_cancelled": "İndirme iptal edildi.",
    "ollama.cancelling": "İptal ediliyor...",
    # --- Kimlik diyaloğu ---------------------------------------------------- #
    "auth.title": "{provider} - kimlik ayarları",
    "auth.method.api_key": "API anahtarı",
    "auth.method.agy": "Antigravity CLI girişi",
    "auth.method.oauth": "OAuth / CLI girişi",
    "auth.api.title": "API anahtarını yapıştırın",
    "auth.api.storage_note": (
        "Anahtar işletim sisteminin kimlik deposuna (keyring) yazılır; düz metin "
        "dosyaya asla kaydedilmez."
    ),
    "auth.api.where_to_get": "Almak için: {url}",
    "auth.api.placeholder": "anahtarı buraya yapıştırın",
    "auth.api.show": "Göster",
    "auth.api.save_and_test": "Kaydet ve test et",
    "auth.api.clear": "Kayıtlı anahtarı sil",
    "auth.api.need_key": "Önce bir anahtar yapıştırın.",
    "auth.api.saved_testing": "Kaydedildi, test ediliyor...",
    "auth.api.no_key_url": "Bu sağlayıcı için anahtar adresi tanımlı değil.",
    "auth.api.opened_browser": "Tarayıcıda açıldı: {url}",
    "auth.api.cleared": "Kayıtlı anahtar silindi.",
    "auth.oauth.title": "Tarayıcı ile oturum aç",
    "auth.oauth.title_agy": "Antigravity CLI ile bağlan",
    "auth.oauth.subtitle": (
        "Aşağıdaki komut ayrı bir konsolda çalışır ve tarayıcınızı açar. Giriş "
        "tamamlanınca bu pencere kendiliğinden güncellenir."
    ),
    "auth.oauth.subtitle_agy": (
        "Bilgisayarınızdaki Antigravity CLI oturumu kullanılır - API anahtarı, GCP "
        "projesi veya faturalandırma gerekmez. Giriş yapmadıysanız aşağıdaki komut "
        "bir konsolda açılır."
    ),
    "auth.oauth.refresh_state": "Durumu yenile",
    "auth.oauth.test": "Bağlantıyı test et",
    "auth.oauth.unsupported": "Bu sağlayıcı için CLI girişi yok.",
    "auth.oauth.command_missing": "`{command}` komutu bulunamadı. Önce kurun: {hint}",
    "auth.oauth.launch_failed": "Giriş başlatılamadı: {error}",
    "auth.oauth.waiting": "Giriş bekleniyor...",
    "auth.oauth.console_opened": (
        "Konsol penceresi açıldı. Tarayıcıdan girişi tamamlayın - bittiğinde burası "
        "kendiliğinden güncellenecek."
    ),
    "auth.oauth.success": "Giriş başarılı.",
    "auth.oauth.timeout": "Giriş tamamlanmadı (zaman aşımı). Tekrar deneyebilirsiniz.",
    "auth.agy.speed_note": (
        "Not: Antigravity CLI etkileşimli bir ajandır ve her çağrıda kendi bağlamını "
        "yükler. Tek bir pipeline adımı birkaç dakika sürebilir; hız önemliyse AI "
        "Studio API anahtarını tercih edin."
    ),
    "auth.agy.use": "Antigravity CLI'ı kullan",
    "auth.agy.not_installed": "`agy` komutu bulunamadı. Antigravity CLI'ı kurun: {url}",
    "auth.agy.selected": "Antigravity CLI seçildi. Oturum doğrulanıyor...",
    "auth.current.in_use": "Şu an kullanılan: {source}",
    "auth.current.missing": (
        "Kimlik tanımlı değil. Aşağıdan bir API anahtarı girin veya OAuth ile oturum açın."
    ),
    "auth.test.running": "Bağlantı test ediliyor...",
    "auth.test.ok": "Başarılı - {detail}",
    "auth.test.signed_in_as": "Giriş yapıldı: {name}",
    # --- Pipeline ekranı: form ---------------------------------------------- #
    "pipeline.mode.domain": "Veri tarifi",
    "pipeline.mode.project": "Proje tarifi",
    "pipeline.form.title": "Ne üretmek istiyorsunuz?",
    "pipeline.example.domain": (
        "Mobil oyun reklamlarında kullanıcı etkileşim verisi: yaş, gelir, reklam "
        "süresi, izleme süresi ve tıklama."
    ),
    "pipeline.example.project": (
        "Online mağazamdan alışverişi kesecek müşterileri önceden tespit etmek "
        "istiyorum ki elde tutma ekibi onlara kampanya gönderebilsin."
    ),
    "pipeline.hint.domain": (
        "Domain'i serbest metinle anlatın; LLM şemayı kendisi çıkaracak."
    ),
    "pipeline.hint.project": (
        "Projenizi anlatın; sistem hangi verinin gerektiğine, hedef değişkene, sınıf "
        "dengesine, ayıklanacak sızıntı kolonlarına ve train/test ayrımına kendisi "
        "karar verir."
    ),
    "pipeline.rows.label": "Satır sayısı",
    "pipeline.rows.label_root": "Kök tablo satır sayısı",
    "pipeline.form.seed": "Random seed",
    "pipeline.form.locale": "Faker locale",
    "pipeline.form.formats": "Çıktı formatları",
    "pipeline.seed.hf": "HuggingFace'ten referans (seed) veri kullan",
    "pipeline.seed.hf_placeholder": "HF arama sorgusu veya dataset ID",
    "pipeline.seed.web": "Web'den canlı referans veri topla (Arama / URL)",
    "pipeline.seed.web_placeholder": "Arama konusu veya doğrudan https:// URL'i",
    "pipeline.engine.label": "Üretim motoru",
    "pipeline.engine.llm": "LLM kod üretimi",
    "pipeline.engine.parametric": "Parametrik (hızlı, LLM'siz)",
    "pipeline.engine.auto": "Otomatik (LLM, olmazsa parametrik)",
    "pipeline.engine.llm_hint": (
        "LLM üretici Python kodu yazar, sandbox'ta koşar; hata olursa kendini onarır. "
        "En esnek yol."
    ),
    "pipeline.engine.parametric_hint": (
        "Şema doğrudan vektörlere derlenir: LLM kodu yok, sandbox yok, milisaniyeler "
        "sürer. Şu an tek tablo destekleniyor."
    ),
    "pipeline.engine.auto_hint": (
        "Önce kod üretimi denenir; denemeler tükenirse koşu düşmez, parametrik motora "
        "geçilir."
    ),
    "pipeline.engine.time_series": "Zaman serisi ve hız analizi ekle",
    "pipeline.engine.expand_features": "Özellikleri genişlet (oranlar, gruplar, zaman türevleri)",
    "pipeline.engine.dirty": "Kontrollü kirli veri enjekte et (oran %)",
    "pipeline.engine.small_model_switched": "{model} küçük bir model olduğu için motor Parametrik'e alındı: LLM kod üretimi bu modelle başarısız oluyor, Parametrik aynı veriyi saniyeler içinde üretir. İsterseniz geri değiştirebilirsiniz.",
    "pipeline.engine.small_model_warning": "{model} küçük bir model: LLM kod üretimi bu modelle başarısız oluyor. Parametrik önerilir - Otomatik de sonunda oraya düşer, ama ancak üç başarısız kod turundan sonra.",
    "pipeline.relational.enable": "İlişkisel (çok tablolu) veri seti üret",
    "pipeline.relational.max_tables": "En fazla tablo",
    "pipeline.relational.repair": "Yetim yabancı anahtarları onar (kapalıysa yalnız raporlanır)",
    "pipeline.tab.console": "Konsol",
    "pipeline.tab.result": "Sonuç",
    "pipeline.tab.charts": "Grafikler",
    "pipeline.result.empty": "Henüz sonuç yok.",
    "pipeline.result.open_folder": "Çıktı klasörünü aç",
    # --- Sonuç sekmesi ------------------------------------------------------ #
    "result.section.engines": "MOTORLAR",
    "result.section.relational": "İLİŞKİSEL BÜTÜNLÜK",
    "result.section.plan": "PROJE PLANI",
    "result.section.stages": "AYIKLAMA AŞAMALARI",
    "result.section.rules": "İŞ KURALLARI",
    "result.section.correlations": "KORELASYON DOĞRULAMASI",
    "result.section.preserved": "KORUNAN ANOMALİLER (FRAUD / OUTLIER MUAFİYETİ)",
    "result.section.distribution": "DAĞILIM (KS) TESTİ",
    "result.section.outputs": "ÇIKTI DOSYALARI",
    "result.rows_value": "{rows} satır",
    "result.warning": "UYARI: {message}",
    "result.rows_raw": "Üretilen ham satır",
    "result.rows_validated": "Validasyondan geçen",
    "result.retention": "Korunan oran",
    "result.attempts": "Kod üretim denemesi",
    "result.sandbox_seconds": "Sandbox süresi (sn)",
    "result.cost": "Tahmini LLM maliyeti",
    "result.rule_violations": "{count} ihlal",
    "result.distribution.summary": "{passed}/{total} kolon referans dağılıma uyuyor (p > 0.05)",
    "result.charts_failed": "Grafikler çizilemedi: {error}",
    "result.engines.generation": "Üretim",
    "result.engines.time_series": "Zaman serisi",
    "result.engines.time_series_value": "{entities} tekil varlık, {bursts} hız patlaması",
    "result.engines.time_range": "Aralık",
    "result.engines.feature_expander": "Özellik genişletme",
    "result.engines.feature_value": "+{added} kolon (toplam {total})",
    "result.engines.added_columns": "Eklenen",
    "result.engines.dirty": "Kontrollü kirlilik",
    "result.engines.dirty_value": "{rows} satır (%{rate}), doğrulamadan SONRA",
    "result.engines.dirty_breakdown": "Dağılım",
    "result.engines.dirty_breakdown_value": (
        "eksik {missing}, yazım {typo}, uç değer {spike}, harf/boşluk {casing}"
    ),
    "result.engines.note": "Not",
    "result.engines.stats_note": "kolon istatistikleri kirlilikten ÖNCE hesaplandı",
    "result.relational.verdict": "Sonuç",
    "result.relational.failed": "BAŞARISIZ",
    "result.relational.repair": "Yetim onarımı",
    "result.relational.repair_off": "KAPALI (yalnızca raporlanıyor)",
    "result.relational.row_counts": "Tablo satır sayıları:",
    "result.relational.orphans_removed": "Onarımda silinen yetim",
    "result.relational.fk": "FK [{relationship}]: {orphans} yetim (%{pct}) {verdict}",
    "result.relational.violation": "İHLAL",
    "result.relational.cardinality": (
        "Kardinalite [{relationship}]: ort {observed} (beklenen {expected}) {verdict}"
    ),
    "result.relational.deviation": "SAPMA",
    "result.relational.pk_not_unique": "UYARI: '{table}' birincil anahtarı '{pk}' tekil değil",
    "result.plan.task_type": "Görev tipi",
    "result.plan.table_count": "Tablo sayısı",
    "result.plan.target": "Hedef değişken",
    "result.plan.class_balance": "Sınıf dengesi",
    "result.plan.positive_pct": "pozitif %{pct}",
    "result.plan.split": "Train/test ayrımı",
    "result.plan.reason": "gerekçe: {reason}",
    "result.plan.rationale": "Plan gerekçesi",
    "result.plan.leakage_header": "Ayıklanan sızıntı kolonları ({count} adet):",
    "result.plan.leakage": "Ayıklanan sızıntı",
    "result.plan.leakage_none": "yok",
    # --- Koşu döngüsü ve form doğrulama -------------------------------------- #
    "app.status.running": "Çalışıyor...",
    "app.run.separator": "YENİ PIPELINE",
    "app.run.domain": "Domain: {domain}",
    "app.run.parameters": "Sağlayıcı: {provider} / {model} | {rows} satır | seed {seed}",
    "app.error.already_running": "Zaten çalışan bir pipeline var.",
    "app.resume.loaded": (
        "Job #{job_id} ayarları yüklendi - 'Pipeline'i Başlat' ile aynı seed'le tekrar "
        "çalıştırabilirsiniz."
    ),
    "app.cancel.requested": "İptal isteği gönderildi, mevcut adım sonlandırılıyor...",
    "app.cancel.in_progress": "İptal ediliyor...",
    "pipeline.relational.project_mode_note": (
        "Proje kipinde kaç tablo gerektiğine planlayıcı karar verir; ilişkisel anahtarı "
        "bu yüzden kapalı."
    ),
    "pipeline.error.empty_project": "Önce projenizi anlatın.",
    "pipeline.error.empty_domain": "Önce ne üretmek istediğinizi yazın.",
    "pipeline.error.rows_not_int": "Satır sayısı bir tam sayı olmalı.",
    "pipeline.error.rows_not_positive": "Satır sayısı pozitif olmalı.",
    "pipeline.error.seed_not_int": "Random seed bir tam sayı olmalı.",
    "pipeline.error.no_format": "En az bir çıktı formatı seçin.",
    "pipeline.error.dirty_not_number": "Kirlilik oranı sayı olmalı (örn. 5).",
    "pipeline.error.dirty_range": "Kirlilik oranı %0 ile %100 arasında olmalı.",
    "pipeline.error.max_tables_not_int": "En fazla tablo bir tam sayı olmalı.",
    "pipeline.error.max_tables_range": "İlişkisel modda tablo sayısı 2 ile 12 arasında olmalı.",
    "pipeline.error.folder_open": "Klasör açılamadı: {error}",
    # --- Pipeline adımları -------------------------------------------------- #
    "step.1": "Servis kontrolü",
    "step.2": "Araştırma & şema üretimi",
    "step.3": "Seed veri arama (HuggingFace)",
    "step.4": "Kod üretimi & self-healing",
    "step.5": "Sandbox çalıştırma",
    "step.6": "Validasyon & ayıklama",
    "step.7": "Çıktı & durum kaydı",

    # --- Pipeline hataları --------------------------------------------------- #
    "pipeline.error.unknown_engine": "Bilinmeyen üretim motoru: {engine} (geçerli: {valid})",
    "pipeline.error.dirty_rate_range": "dirty_rate 0 ile 1 arasında olmalı, {value} verildi",
    "pipeline.error.max_tables_planner": "max_tables 1 ile {limit} arasında olmalı, {value} verildi",
    "pipeline.error.max_tables_relational": "max_tables 2 ile {limit} arasında olmalı, {value} verildi",
    "pipeline.error.unknown_fraud_table": (
        "--fraud-table '{table}' sözleşmede yok. Geçerli tablolar: {tables}"
    ),
    "pipeline.error.unknown_audit_table": (
        "--audit-table '{table}' sözleşmede yok. Geçerli tablolar: {tables} (ya da 'all')"
    ),
    "pipeline.error.unknown_ts_table": (
        "--ts-table '{table}' sözleşmede yok. Geçerli tablolar: {tables}"
    ),
    "pipeline.error.unknown_expand_table": (
        "--expand-table '{table}' sözleşmede yok. Geçerli tablolar: {tables}"
    ),
    "pipeline.error.unknown_dirty_table": (
        "--dirty-table '{table}' sözleşmede yok. Geçerli tablolar: {tables}"
    ),
    "pipeline.cancelled_by_user": "Pipeline kullanıcı tarafından iptal edildi",

    # --- Koşu ilerlemesi ------------------------------------------------------ #
    "run.checking_provider": "Sağlayıcı kontrol ediliyor: {provider} / {model}",
    "run.service_ready": "Servis hazır: {model}",
    "run.provider_model": "Sağlayıcı: {provider} | Model: {model}",
    "run.seed.hf_searching": "HuggingFace'te referans veri aranıyor...",
    "run.seed.loaded": "Seed veri yüklendi: {source} ({rows} satır)",
    "run.seed.columns": "Referans sütunlar ({count} adet): {columns}",
    "run.seed.none_found": "Uygun seed veri bulunamadı - şema sıfırdan üretilecek",
    "run.seed.web_searching": "Web'de referans veri aranıyor ve toplanıyor: '{query}'...",
    "run.seed.web_collected": "Web'den referans veri toplandı: {source} ({rows} satır, {columns} sütun)",
    "run.seed.extracted_columns": "Çıkarılan referans kolonlar: {columns}",
    "run.seed.web_none": "Web'den uygun veri çıkarılamadı - şema sıfırdan üretilecek",
    "run.seed.skipped": "Seed veri kullanılmıyor (atlandı)",
    "run.plan.analysing": "Proje analiz ediliyor: hangi veri gerekli?",
    "run.schema.relational": "LLM domain analiz ediyor ve ilişkisel Dataset Contract üretiyor...",
    "run.schema.single": "LLM domain analiz ediyor ve Schema Contract üretiyor...",
    "run.schema.contract_ready": (
        "Dataset Contract hazır: {tables} tablo, {relationships} ilişki (kök tablo: {root})"
    ),
    "run.schema.ready": "Şema hazır: {summary}",
    "run.audit.tables": "Gizlilik denetimi yapılacak tablolar: {tables}",
    "run.engine.parametric_selected": "Parametrik motor seçildi - kod üretimi ve sandbox atlanıyor",
    "run.engine.compiled_no_llm": "Şema doğrudan vektörel derlendi ({seconds} sn, LLM kodu yok)",
    "run.engine.compiled": "Şema doğrudan vektörel derlendi ({seconds} sn)",
    "run.engine.falling_back": "Parametrik motora düşülüyor (--engine auto)",
    "run.engine.small_model_warning": "{model} küçük bir model: LLM kod üretimi bu modelle başarısız oluyor (1.5B modelde ölçüm: 3 koşunun 0'ı). --engine parametric aynı veriyi başarısız kod turları olmadan üretir.",
    "run.codegen.writing": "Veri üreten kod yazılıyor...",
    "run.codegen.failed_warning": "UYARI: kod üretimi başarısız ({error})",
    "run.raw.generated": "Ham veri üretildi: {rows} satır ({attempts} deneme, {seconds} sn)",
    "run.raw.generated_relational": (
        "Ham veri üretildi: {tables} tablo, {rows} satır ({attempts} deneme, {seconds} sn)"
    ),
    "run.raw.saved": "Ham veri kaydedildi: {name} ({size} MB)",
    "run.fraud.injected": (
        "Dolandırıcılık senaryoları enjekte edildi: {rows} satır (oran: %{rate}, "
        "tablo: {table}, kolon: {column})"
    ),
    "run.time_series.applied": (
        "Zaman serisi dinamiği uygulandı: {entities} tekil varlık, {bursts} hız "
        "patlaması, medyan aralık {median} sn"
    ),
    "run.time_series.entity_warning": (
        "UYARI: '{column}' kolonu {rows} satırda {distinct} farklı değer taşıyor; hız "
        "metrikleri anlamsız kalır. Tekrar eden bir kolon verin: --ts-entity-col <kolon>"
    ),
    "run.features.expanded": "Özellik genişletme: {added} yeni kolon (toplam {total})",
    "run.validation.running": "Discriminator çalışıyor...",
    "run.validation.table": "Tablo doğrulanıyor: {table}",
    "run.validation.done": "Validasyon bitti: {rows_in} -> {rows_out} satır (%{retention} korundu)",
    "run.validation.table_rows": "{rows_in} -> {rows_out} satır (%{retention})",
    "run.relational.checking": "İlişkisel bütünlük denetleniyor ({count} ilişki)...",
    "run.relational.repair_disabled": "yetim onarımı kapalı (--no-repair-orphans)",
    "run.relational.contract_violated": "sözleşme ihlali sürüyor",
    "run.relational.failed": "UYARI: İlişkisel bütünlük denetimi başarısız - {reason}",
    "run.dirty.injected": (
        "Kontrollü kirlilik enjekte edildi: {rows} satır (%{rate}) - eksik {missing}, "
        "yazım hatası {typo}, uç değer {spike}, harf/boşluk {casing}"
    ),
    "run.dirty.audit_columns": "Denetim izi kolonları eklendi: is_corrupted, corruption_details",
    "run.output.writing": "Çıktı dosyaları yazılıyor...",
    "run.output.written": "Çıktı yazıldı: {kinds}",
    "run.output.skipped": "Çıktı dosyası yazılmadı (write_outputs=False)",
    "run.hub.uploading": "HuggingFace'e yükleniyor: {repo}",
    "run.hub.uploaded": "Yüklendi: {url}",
    "run.cost.summary": "LLM kullanımı: {calls} çağrı, {tokens} token, ~${cost}",
    "run.finished": "Tamamlandı. {rows} temiz satır, tahmini maliyet ${cost}",
    "run.finished_relational": "Tamamlandı. {tables} tablo, {rows} temiz satır, tahmini maliyet ${cost}",
    # --- Plan ve şema konsol dökümü ------------------------------------------ #
    "run.plan.ready": "Plan hazır: {summary}",
    "run.plan.rationale": "Gerekçe: {rationale}",
    "run.plan.target": "Hedef değişken: {target}",
    "run.plan.class_balance": "Sınıf dengesi: pozitif sınıf %{pct}",
    "run.plan.leakage": "Sızıntı yaratacağı için ayıklanan kolonlar ({count} adet):",
    "run.plan.split": "Train/test ayrımı: {kind} - {reason}",
    "run.schema.generation_order": "{tables} tablo, üretim sırası: {order}",
    "run.schema.table_line": "Tablo '{table}' | PK: {pk} | hedef {rows} satır",
    "run.schema.columns_header": "Tanımlanan kolonlar ({count} adet):",
    "run.schema.spec_range": "aralık: [{low}, {high}]",
    "run.schema.spec_distribution": "dağılım: {distribution}",
    "run.schema.spec_categories": "kategoriler: [{categories}]",
    "run.schema.spec_ratio": "oran: %{pct}",
    "run.schema.spec_not_null": "not null",
    "run.schema.rules_header": "İş kuralları ({count} adet):",
    "run.schema.rule": "Kural: {rule}",
    "run.schema.correlations_header": "Beklenen korelasyonlar ({count} adet):",
    "run.schema.relationships_header": "İlişkiler ({count} adet):",
    "run.schema.relationship": "{label} (ebeveyn başına ort {mean}; {bounds}{optional})",
    "run.schema.optional": "opsiyonel",

    # --- CLI ------------------------------------------------------------------ #
    "cli.auth.header": "Kimlik bilgisi durumu",
    "cli.auth.source": "kaynak: {source}",
    "cli.auth.implicit": "anahtar yok ama {source} bulundu - denenecek",
    "cli.auth.checked": "bakılan: keyring, {vars}",
    "cli.auth.oauth_logged_in": "OAuth: giriş yapılmış - {detail}",
    "cli.auth.oauth_missing": "OAuth: {command} kurulu değil ({hint})",
    "cli.auth.oauth_login": "OAuth: giriş için -> {command}",
    "cli.auth.note": "NOT:   {note}",
    "cli.auth.ollama_running": "Ollama {version} - {count} model",
    "cli.auth.ollama_down": "daemon çalışmıyor ({host})",
    "cli.auth.none_available": "Hiçbir sağlayıcı kullanılabilir değil.",
    "cli.error.domain_and_project": (
        "--domain ve --project birlikte kullanılamaz: ya veriyi tarif edin ya da "
        "projeyi anlatın"
    ),
    "cli.error.domain_or_project": "--domain veya --project zorunlu (veya --check-auth kullanın)",
    "cli.error.generic": "HATA: {error}",
    "cli.label.domain": "Domain",
    "cli.label.project": "Proje",
    "cli.label.provider": "Sağlayıcı",
    "cli.label.backend": "(arka uç: {backend})",
    "cli.label.target": "Hedef",
    "cli.label.target_value": "{rows} satır, seed {seed}",
    "cli.label.mode": "Mod",
    "cli.label.engine": "Motor",
    "cli.mode.planner": "proje planlayıcı (en fazla {limit} tablo, tablo sayısına plan karar verir)",
    "cli.mode.relational": "ilişkisel (en fazla {limit} tablo, yetim onarımı: {repair})",
    "cli.on": "açık",
    "cli.off": "KAPALI",
    "cli.engine.time_series": "zaman serisi",
    "cli.engine.expand_features": "özellik genişletme",
    "cli.engine.dirty": "kirlilik %{pct}",
    "cli.cancelled": "İptal edildi.",
    "cli.cancelled_with": "İptal edildi: {reason}",
    "cli.summary.job_done": "Job #{job_id} tamamlandı.",
    "cli.summary.clean_rows": "Temiz satır",
    "cli.summary.clean_rows_value": "{rows_out} / {rows_in} (%{retention} korundu)",
    "cli.summary.cost": "Maliyet",
    "cli.summary.outputs": "Çıktılar:",
    "cli.summary.plan": "Proje planı: {summary}",
    "cli.relational.integrity_failed": "İlişkisel bütünlük sağlanamadı ({count} ihlal).",
    # --- CLI --help ---------------------------------------------------------- #
    "cli.help.description": "AI Synthetic Data Studio - GUI'siz uçtan uca pipeline",
    "cli.help.domain": "Üretilecek veri setinin domain/görev tanımı",
    "run.contract.no_model_needed": "Hazır sözleşme verildi - model gerekmiyor, hiçbir yere istek gitmiyor",
    "run.contract.engine_forced": "  -> kod üretimi için de model gerekmez: parametrik motor çalışıyor",
    "run.contract.parsing": "Verilen sözleşme okunuyor...",
    "run.contract.loaded": "Sözleşme yüklendi: {domain} ({columns} kolon), istenen satır: {rows}",
    "pipeline.error.contract_needs_llm": "Hazır sözleşme modelsiz çalışır, bu yüzden şunlarla birlikte kullanılamaz: {features}",
    "pipeline.error.contract_invalid": "Verilen sözleşme okunamadı: {error}",
    "cli.help.template": "pakette gelen hazır bir sözleşmeden, hiçbir model olmadan üretir (bkz. --list-templates)",
    "cli.help.list_templates": "hazır sözleşme şablonlarını listeler ve çıkar",
    "cli.help.schema_file": "kendi Schema Contract JSON dosyanızdan, hiçbir model olmadan üretir",
    "cli.error.template_and_schema_file": "--template ve --schema-file birlikte kullanılamaz, birini seçin.",
    "cli.error.template_unknown": "Böyle bir şablon yok: {name}. Listelemek için --list-templates.",
    "cli.error.schema_file_unreadable": "Şema dosyası okunamadı: {error}",
    "cli.templates.none": "Bu derlemede şablon yok.",
    "cli.templates.header": "Hazır sözleşme şablonları (model yok, anahtar yok, ağ yok):",
    "cli.templates.detail": "{columns} kolon - {description}",
    "cli.templates.usage": "Kullanımı: ai-data-studio --template <ad> --rows 5000",
    "pipeline.template.label": "Şablon",
    "pipeline.template.none": "Yok (modelle üret)",
    "pipeline.template.hint": "Şablon seçilirse model gerekmez: sözleşme hazır gelir, veriyi parametrik motor derler.",
    "pipeline.error.no_model_or_template": "{reason} - ya Ayarla düğmesiyle bir API anahtarı girin, ya da Şablon listesinden birini seçip modelsiz üretin.",
    "cli.help.project": (
        "Veri yerine PROJEYİ anlat: planlayıcı hangi verinin gerektiğine, hedef "
        "değişkene, sınıf dengesine, ayıklanacak sızıntı kolonlarına ve train/test "
        "ayrımına kendisi karar verir"
    ),
    "cli.help.check_auth": "Tüm sağlayıcıların kimlik durumunu yazdırıp çık",
    "cli.help.model": "Sağlayıcıya özel model adı",
    "cli.help.locale": "Faker locale (örn. tr_TR)",
    "cli.help.hf_seed": "HuggingFace'ten referans veri çek",
    "cli.help.hf_dataset": "Belirli bir HF dataset id'si kullan",
    "cli.help.web_seed": "Web'den gerçek referans (seed) veri topla",
    "cli.help.web_query": "Web arama sorgusu veya doğrudan URL",
    "cli.help.formats": "Virgülle ayrılmış: csv,parquet,json",
    "cli.help.provenance": "CSV/Parquet çıktılarına yasal provenance şerhi ekle",
    "cli.help.export_pdf": "Yönetici özeti PDF Veri Kalitesi & Gizlilik Denetim Raporu üret (Pro)",
    "cli.help.push_to_hub": "Temiz veriyi bu HF repo_id'ye yükle",
    "cli.help.public": "HF repo'yu herkese açık oluştur",
    "cli.help.contamination": "IsolationForest anomali oranı (0 = kapalı, varsayılan). Örn: 0.05",
    "cli.help.no_correlation_guard": (
        "Outlier temizliği hedef korelasyonları bozarsa geri alma korumasını kapat"
    ),
    "cli.help.preserve_col": (
        "Z-score ve IsolationForest filtrelerinden muaf tutulacak anomali kolonu (örn: is_fraud)"
    ),
    "cli.help.preserve_val": "Anomali koruma değeri (varsayılan: 1 veya True)",
    "cli.help.inject_fraud": "Sentetik veriye parametrik dolandırıcılık (fraud) senaryoları enjekte et",
    "cli.help.fraud_rate": "Dolandırıcılık enjeksiyon oranı (varsayılan: 0.005 yani %0.5)",
    "cli.help.fraud_target_col": "Dolandırıcılık etiket kolonu (varsayılan: is_fraud)",
    "cli.help.audit_privacy": (
        "Sezgisel gizlilik kontrollerini çalıştır: en yakın komşu ezberleme testi "
        "(DCR/NNDR), dağılım farkı skoru ve tanımlayıcı kolon adı taraması - uyumluluk "
        "sertifikası değildir"
    ),
    "cli.help.fraud_table": "Dolandırıcılık enjeksiyonu hangi tabloya uygulansın (varsayılan: kök tablo)",
    "cli.help.audit_table": (
        "Gizlilik denetimi hangi tabloya uygulansın: boş = kök tablo (varsayılan), "
        "'all' = bütün tablolar, ya da bir tablo adı"
    ),
    "cli.help.ts_table": "Zaman serisi zenginleştirmesi hangi tabloya uygulansın (varsayılan: kök tablo)",
    "cli.help.expand_table": "Özellik genişletme hangi tabloya uygulansın (varsayılan: kök tablo)",
    "cli.help.dirty_table": "Kirli veri enjeksiyonu hangi tabloya uygulansın (varsayılan: kök tablo)",
    "cli.help.gemini_backend": (
        "Gemini arka ucunu bu koşu için seç: 'aistudio' (API anahtarı, hızlı) veya "
        "'cli' (Antigravity oturumu, yavaş). Kalıcı ayar değişmez"
    ),
    "cli.help.relational": "Çok tablolu (ilişkisel) veri seti üret: tablolar + yabancı anahtarlar",
    "cli.help.max_tables": (
        "İlişkisel modda üst tablo sınırı (varsayılan 6, sözleşmedeki sert sınır 12)"
    ),
    "cli.help.no_repair_orphans": (
        "Yetim yabancı anahtarları silme, hata olarak raporla (CI kapısı: bütünlük "
        "sağlanamazsa çıkış kodu 3)"
    ),
    "cli.help.engine": (
        "Üretim motoru: 'llm' kod üretir ve sandbox'ta koşar (varsayılan), 'parametric' "
        "şemayı doğrudan derler (LLM kodu yok; tek ve çok tablo), 'auto' kod üretimi "
        "tükenirse 'parametric'e düşer"
    ),
    "cli.help.time_series": (
        "Zaman serisi ve hız dinamiği ekle: kronolojik sıralama, sirkadiyen ritim, "
        "seconds_since_last_tx, hız patlamaları"
    ),
    "cli.help.ts_timestamp_col": "Zaman serisi zaman damgası kolonu (varsayılan: transaction_timestamp)",
    "cli.help.ts_entity_col": (
        "Zaman serisi varlık kimliği kolonu; yoksa üretilir (varsayılan: customer_id)"
    ),
    "cli.help.ts_start": "Zaman serisi başlangıcı (YYYY-MM-DD HH:MM:SS)",
    "cli.help.ts_end": "Zaman serisi bitişi (YYYY-MM-DD HH:MM:SS)",
    "cli.help.expand_features": (
        "Deterministik özellik genişletme: finansal oranlar, kredi notu, zaman "
        "türevleri ve davranışsal bayraklar ekle"
    ),
    "cli.help.dirty_rate": (
        "Kontrollü kirlilik oranı (0-1, 0 = kapalı). Doğrulamadan SONRA uygulanır; "
        "is_corrupted / corruption_details kolonları eklenir"
    ),
    "cli.help.hardware": (
        "Donanım profilini (CPU/RAM/GPU) ve önerilen yerel modeli yazdır, çık"
    ),
    # --- Doğrulayıcı ---------------------------------------------------------- #
    "validation.stage.duplicates": "Duplicate temizleme",
    "validation.stage.bounds": "Şema sınırları",
    "validation.stage.rules": "İş kuralları",
    "validation.stage.z_score": "Z-Score aykırı değer",
    "validation.started": "Validasyon başladı ({rows} satır)",
    "validation.finished": "Validasyon tamamlandı: {rows_in} -> {rows_out} satır (%{retention} korundu)",
    "validation.cancelled": "Validasyon kullanıcı tarafından iptal edildi",
    "validation.top_dropped_columns": "En çok elenen kolonlar: {columns}",
    "validation.rule_violation": "Kural ihlali: '{rule}' -> {rows} satır elendi (%{pct})",
    "validation.rule_suspicious": "UYARI: '{rule}' tek başına satırların %{pct} kadarını sildi -büyük olasılıkla kolon aralıklarıyla çelişiyor ya da üretici bu kuralı hiç uygulamadı. Şemadaki kuralı kontrol edin.",
    "validation.rule_skipped_every_row": "UYARI: '{rule}' kuralını hiçbir satır sağlamıyor - uygulansaydı veri seti boşalacaktı, bu yüzden atlandı. Kural kolon tipleri ya da aralıklarıyla çelişiyor; şemadaki kuralı kontrol edin.",
    "validation.z_skipped": "Z-Score atlanan kolonlar (kuyruk koruma): {columns}",
    "validation.z_outliers": "Z-Score aykırıları: {columns}",
    "validation.z_preserved": (
        "Z-Score anomali koruma: '{column}' kolonu sayesinde {rows} uç satır silinmekten korundu"
    ),
    "validation.iso_preserved": (
        "IsolationForest anomali koruma: '{column}' kolonu sayesinde {rows} uç satır korundu"
    ),
    "validation.preserved_summary": "Anomali koruma özeti: {rows} satır '{column}' etiketiyle korundu",
    "validation.correlation_regressed": (
        "UYARI: '{left} ~ {right}' korelasyonu temizlik yüzünden düştü: "
        "r={before} -> {after} (eşik {threshold})"
    ),
    "validation.correlation_guard_reverted": (
        "Korelasyon koruma devrede: outlier temizliği geri alınıyor ({rows} satır geri "
        "geldi). Kapatmak için --no-correlation-guard."
    ),
    "validation.correlation_line": (
        "Korelasyon [{pair}]: r={r} (beklenen: {sign}, min: {min_r}) [{verdict}]"
    ),
    "validation.correlations_unmet": "UYARI: {count} korelasyon beklentiyi karşılamadı: {pairs}",
    "validation.ks_summary": "KS Dağılım Testi: {passed}/{total} sayısal kolon referansla uyumlu",
    "validation.monotonicity_summary": "Monotonluk Denetimi: {passed}/{total} kural doğrulandı",
    "validation.monotonicity_line": (
        "[{x} -> {y} ({direction})]: Spearman r={r}, Dilim Uyumu=%{compliance} [{verdict}]"
    ),
    "validation.privacy_nndr": "Gizlilik & NNDR: DCR={dcr}, NNDR={nndr} (ezberleme riski: {risk})",
    "validation.hipaa_warning": "Tanımlayıcı kolon adı taraması: {summary}",
    "validation.hipaa_ok": (
        "Tanımlayıcı kolon adı taraması: eşleşme yok (yalnızca kolon adlarına bakıldı, "
        "değerler incelenmedi)"
    ),
    "validation.verdict.ok": "UYGUN",
    "validation.verdict.below": "BEKLENENİN ALTINDA",
    "validation.verdict.violation": "İHLAL",
    # --- Kod üretimi (yalnız konsol; LLM geri beslemesi çeviri dışı) ---------- #
    "codegen.starting": "Kod üretimi başlatılıyor (LLM)...",
    "codegen.written": "LLM Python kodunu oluşturdu ({lines} satır). Sandbox testi başlatılıyor...",
    "codegen.written_relational": (
        "LLM {tables} tablo için Python kodunu oluşturdu ({lines} satır). Sandbox "
        "testi başlatılıyor..."
    ),
    "codegen.attempt": "Deneme {attempt}/{total}: kod sandbox'ta çalıştırılıyor...",
    "codegen.attempt_failed": "Deneme {attempt} başarısız: {error}",
    "codegen.hint": "Çözüm ipucu: {hint}",
    "codegen.auto_import": "Eksik import otomatik eklendi ({line}), LLM çağrısı yapmadan yeniden çalıştırılıyor...",
    "codegen.return_wrapped": "Fonksiyon dışında bir `return` bulundu; kod çalışabilsin diye {name}(n_rows, seed) içine alındı...",
    "codegen.return_rebound": "Fonksiyon dışında kalan {count} `return` ifadesi {name} atamasına çevrildi; kodun zaten tanımladığı giriş noktası kullanılıyor...",
    "codegen.attempt_ok": "Deneme {attempt} başarılı: {rows} satır ({seconds} sn, {columns} sütun)",
    "codegen.attempt_ok_relational": (
        "Deneme {attempt} başarılı: {tables} tablo üretildi ({seconds} sn) - {counts}"
    ),
    "codegen.schema_mismatch": "Deneme {attempt}: {count} şema uyumsuzluğu bulundu",
    "codegen.mismatch_item": "Uyumsuzluk: {issue}",
    "codegen.mismatch_more": "... ve {count} uyumsuzluk daha",
    "codegen.repeated_error": "Aynı hata tekrarlandı - LLM'den yaklaşımını değiştirmesi isteniyor...",
    "codegen.feeding_back": "LLM'e hata geri besleniyor, kod düzeltiliyor...",
    "codegen.gave_up": "{attempts} denemede başarılı kod üretilemedi. Son hata:\n{error}",
    "codegen.fix_call_failed": "Kod düzeltme çağrısı başarısız: {error}",
    "codegen.unexpected_state": "Beklenmeyen durum",
    "codegen.cancelled": "Kullanıcı tarafından iptal edildi",
    # --- İlişkisel doğrulayıcı ------------------------------------------------ #
    "relational.orphans_removed": "Yetim satır temizliği [{relationship}]: {rows} satır elendi",
    "relational.pk_not_unique": (
        "UYARI: '{table}' birincil anahtarı '{pk}' tekil değil ({duplicates} tekrar, "
        "{nulls} boş)"
    ),
    "relational.fk_line": "Yabancı anahtar [{relationship}]: {orphans} yetim satır (%{pct}) [{verdict}]",
    "relational.verdict.orphans": "YETİM VAR",
    "relational.cardinality_line": (
        "Kardinalite [{relationship}]: ebeveyn başına ort {observed} (beklenen {expected}) [{verdict}]"
    ),

    # --- Monotonluk doğrulayıcı ------------------------------------------------ #
    "monotonicity.no_rules": "Tanımlanmış monotonluk kuralı bulunmamaktadır.",
    "monotonicity.report_title": "Monotonluk & Kredi Riski Skor Kartı Uyumluluk Raporu",
    "monotonicity.table_header": (
        "| Değişken X | Hedef/Bağımlı Y | Yön | Spearman $r_s$ | Dilim Uyumu | Çift "
        "Uyumu | Durum |"
    ),
    "monotonicity.compliant": "Uyumlu",
    "monotonicity.below_threshold": (
        "Dilim monotonluk uyumu (%{binned}) veya ikili uyum (%{pairwise}) eşiğin "
        "(%{threshold}) altında"
    ),
    "monotonicity.column_missing": "Kolon veri çerçevesinde bulunamadı veya veri boş",
    "monotonicity.not_enough_rows": "Yeterli geçerli sayısal satır yok (<10)",
    # --- HIPAA tanımlayıcı kataloğu -------------------------------------------- #
    "hipaa.title.names": "İsim ve soyisimler",
    "hipaa.title.geographic": "Eyalet/il altı coğrafi birimler",
    "hipaa.title.dates": "Kişiye doğrudan bağlı tarihler",
    "hipaa.title.phone": "Telefon numaraları",
    "hipaa.title.fax": "Faks numaraları",
    "hipaa.title.ssn": "Sosyal güvenlik / kimlik numarası (SSN / TCKN)",
    "hipaa.title.mrn": "Tıbbi kayıt / protokol numarası",
    "hipaa.title.health_plan": "Sağlık sigortası hesap numarası",
    "hipaa.title.account": "Banka / hesap numaraları",
    "hipaa.title.vehicle": "Araç tanımlayıcı ve plakalar (VIN)",
    "hipaa.title.device": "Cihaz tanımlayıcı ve seri numaraları",
    "hipaa.title.biometric": "Biyometrik tanımlayıcılar",
    "hipaa.title.face": "Yüz fotoğrafları ve benzer görüntüler",
    "hipaa.title.unique_code": "Her türlü benzersiz kod veya numara",
    "hipaa.title.email": "E-posta adresleri",
    "hipaa.title.certificate": "Sertifika / ehliyet numaraları",
    "hipaa.title.url": "Web adresleri (URL)",
    "hipaa.title.ip": "IP adresleri",
    "hipaa.category.direct": "Doğrudan tanımlayıcı",
    "hipaa.category.quasi": "Yarı tanımlayıcı (quasi-identifier)",
    "hipaa.category.timestamp": "Zaman damgası (date shifting gerekir)",
    "hipaa.category.health_system": "Sağlık sistemi kimliği",
    "hipaa.category.health_financial": "Finansal sağlık kimliği",
    "hipaa.category.financial": "Finansal tanımlayıcı",
    "hipaa.category.asset": "Varlık tanımlayıcı",
    "hipaa.category.hardware": "Donanım tanımlayıcı",
    "hipaa.category.digital": "Dijital iz",
    "hipaa.category.network": "Ağ tanımlayıcı",
    "hipaa.category.visual_biometric": "Görsel biyometri",
    "hipaa.category.government_id": "Resmi kimlik numarası",
    "hipaa.category.official_document": "Resmi belge",
    "hipaa.category.biometric": "Biyometrik veri",

    # --- Gizlilik denetim raporu ------------------------------------------------ #
    "privacy.report.title": "Gizlilik Kontrol Raporu (sezgisel)",
    "privacy.report.scope": (
        "**Kapsam:** yalnızca sezgisel kontroller - referans veriye karşı en yakın komşu "
        "ezberleme testi (DCR/NNDR), histogram tabanlı dağılım farkı skoru ve 18 HIPAA "
        "Safe Harbor tanımlayıcı kategorisini kontrol listesi olarak kullanan bir kolon "
        "adı taraması. Diferansiyel gizlilik garantisi ya da HIPAA uyumluluk sertifikası "
        "değildir."
    ),
    "privacy.report.table": "Tablo",
    "privacy.report.summary_heading": "Özet",
    "privacy.report.overall_status": "Genel durum",
    "privacy.report.guarantee": "Ezberleme kontrolü",
    "privacy.report.divergence": "Dağılım farkı",
    "privacy.report.divergence_note": (
        "ortak sayısal kolonlarda sentetik ve referans histogramları arasındaki ortalama "
        "Jensen-Shannon mesafesi (referans yüzdeliklerinde 20 kutu); 0 aynı histogram, 1 "
        "hiç örtüşme yok demektir. Küçük örneklemde aynı dağılım için bile 0'dan büyük "
        "çıkar. Bir gizlilik ölçüsü değildir."
    ),
    "privacy.report.memorisation_heading": "Referans Veri Ezberleme Analizi",
    "privacy.report.no_reference": (
        "Referans (seed) veri sağlanmadığı için DCR/NNDR karşılaştırması çalışmadı, yani "
        "**ezberleme riski ölçülmedi**."
    ),
    "privacy.report.no_reference_table": (
        "Bu tablo için referans (seed) veri yok; DCR/NNDR karşılaştırması yapılamadı, "
        "yani **ezberleme riski ölçülmedi**."
    ),
    "privacy.report.nn_intro": (
        "En yakın komşu analizi, sentetik satırların referans kayıtlara, referans "
        "kayıtların birbirine olduğundan daha yakın olup olmadığını kontrol eder. İkisi "
        "de iki veri setinin ortak sayısal kolonlarında, standartlaştırılarak, rastgele "
        "bir satır örnekleminde ölçülür; taban çizgisi sütunu aynı dağılımdan gelen, "
        "kopyalanmamış verinin nasıl göründüğünü gösterir:"
    ),
    "privacy.report.metric_header": (
        "| Metrik | Sentetik → referans | Referans → referans (taban çizgisi) | Risk "
        "seviyesi |"
    ),
    "privacy.report.dcr_p5": "5. yüzdelik DCR",
    "privacy.report.identical_matches": "Birebir eşleşen kayıt sayısı",
    "privacy.report.mean_nndr": "Ortalama NNDR",
    "privacy.report.low_nndr_share": "NNDR < 0.2 olan satır payı",
    "privacy.report.nndr_note_label": "NNDR yorumu:",
    "privacy.report.nndr_note": (
        "her değeri sabit bir eşikle değil taban çizgisiyle karşılaştırın. Bir iki "
        "sayısal kolonda düşük oranların hatırı sayılır bir payı normaldir. Taban "
        "çizgisinin belirgin üstündeki birebir eşleşmeler ya da düşük oranlar kopyalanmış "
        "veya neredeyse kopyalanmış kayıtlara işaret eder. Yalnızca DCR 5. yüzdeliğinin "
        "taban çizgisinin altında olması sentetik verinin yoğun bölgelerde toplandığı "
        "anlamına da gelebilir; bu yüzden riski en fazla MEDIUM'a çıkarır."
    ),
    "privacy.report.hipaa_heading": "Tanımlayıcı Kolon Adı Taraması",
    "privacy.report.hipaa_scope": (
        "Kolon **adları** 18 HIPAA Safe Harbor tanımlayıcı kategorisinin desenleriyle "
        "eşleştirilir ve yaş kolonunda 89'dan büyük değer aranır. Hücre değerlerine "
        "bakılmaz: ilgisiz bir adla saklanan tanımlayıcı gözden kaçar, adında desen geçen "
        "zararsız bir kolon (ör. `mobile_sessions`) ise işaretlenir."
    ),
    "privacy.report.audit_result": "Tarama sonucu",
    "privacy.report.all_passed": "EŞLEŞME YOK",
    "privacy.report.review_required": "İNCELENECEK KOLONLAR VAR",
    "privacy.report.age_over_89": "89 yaş üstü satır sayısı",
    "privacy.report.age_rule": "HIPAA kuralı: 89 yaş üstü 90+ olarak kümelenmelidir",
    "privacy.report.identifiers_heading": "Tanımlayıcı Desenine Uyan Kolon Adları",
    "privacy.report.identifiers_header": (
        "| Kolon adı | Tanımlayıcı kategorisi | Önerilen aksiyon |"
    ),
    "privacy.report.no_identifiers": (
        "Hiçbir kolon adı tanımlayıcı desenine uymadı. Hücre değerleri incelenmedi."
    ),
    "privacy.report.footer": (
        "Bu rapor AI Synthetic Data Studio PrivacyAuditor tarafından otomatik "
        "oluşturuldu. Kontroller sezgiseldir; veriyi paylaşmadan önce kendiniz de gözden "
        "geçirin."
    ),
    "privacy.action.mask": (
        "Gözden geçirin; maskeleyin ya da sentetik değerlerle (ör. Faker) değiştirin."
    ),
    "privacy.summary.compliant": "Tanımlayıcıya benzeyen kolon adı ve 89 yaş üstü kayıt bulunmadı.",
    "privacy.summary.findings": (
        "Tanımlayıcıya benzeyen {columns} kolon adı ve yaşı 89'dan büyük {ages} satır "
        "bulundu."
    ),
    "privacy.assessment.copies_found": (
        "Referans kayıtların olası kopyaları var (birebir eşleşme ya da düşük NNDR)"
    ),
    "privacy.assessment.no_copies": (
        "Örneklemde referans kayıtların kopyasına benzeyen satır bulunmadı"
    ),
    "privacy.assessment.not_measured": "Ölçülmedi - karşılaştırılacak referans veri yok",
    # --- Şema sözleşmesi doğrulaması -------------------------------------------- #
    "schema.error.empty_response": "LLM yanıtı boş - JSON bloğu bulunamadı",
    "schema.error.no_json": "LLM yanıtında geçerli JSON bloğu bulunamadı",
    "schema.error.must_be_object": "{where} bir nesne olmalı, {got} geldi",
    "schema.error.name_required": "{where}: 'name' zorunlu ve boş olmayan bir metin olmalı",
    "schema.error.bad_identifier": (
        "{where}: kolon adı '{name}' geçersiz - df.eval ile kullanılabilmesi için "
        "sadece harf/rakam/alt çizgi içermeli ve rakamla başlamamalı"
    ),
    "schema.error.bad_type": "{where} ('{name}'): 'type' şu değerlerden biri olmalı: {valid}",
    "schema.error.bad_distribution": (
        "{where} ('{name}'): bilinmeyen distribution '{distribution}' - geçerli: {valid}"
    ),
    "schema.error.min_gt_max": "{where} ('{name}'): min ({low}) max'tan ({high}) büyük olamaz",
    "schema.error.target_ratio_range": "{where} ('{name}'): target_ratio 0..1 aralığında olmalı, {value} geldi",
    "schema.error.zero_prob_range": "{where} ('{name}'): zero_prob 0..1 aralığında olmalı, {value} geldi",
    "schema.error.p_index_range": "{where} ('{name}'): tweedie p_index 1 ile 2 arasında olmalı, sınırlar hariç (ör. 1.5; Compound Poisson-Gamma), {value} geldi",
    "schema.error.std_negative": "{where} ('{name}'): std negatif olamaz",
    "schema.error.shape_positive": "{where} ('{name}'): shape pozitif olmalı",
    "schema.error.scale_positive": "{where} ('{name}'): scale pozitif olmalı",
    "schema.error.categories_required": (
        "{where} ('{name}'): type 'category' ise 'categories' listesi zorunlu"
    ),
    "schema.error.mean_required": "{where} ('{name}'): distribution 'normal' ise 'mean' zorunlu",
    "schema.error.contract_object": "Schema Contract bir JSON nesnesi olmalı, {got} geldi",
    "schema.error.domain_required": "'domain' boş olmayan bir metin olmalı",
    "schema.error.columns_required": "'columns' en az bir kolon içeren bir liste olmalı",
    "schema.error.duplicate_columns": "Tekrarlanan kolon adları: {columns}",
    "schema.error.row_count_positive": "'row_count_target' pozitif olmalı",
    "schema.error.row_count_int": "'row_count_target' tam sayı olmalı, {value} geldi",
    "schema.error.seed_int": "'random_seed' tam sayı olmalı",
    "schema.error.rules_list": "'business_rules' bir liste olmalı",
    "schema.error.correlations_list": "'correlations' bir liste olmalı",
    "schema.error.monotonicity_list": "'monotonicity_rules' bir liste olmalı",
    "schema.error.correlation_pair": "{where}: 'columns' tam olarak 2 kolon adı içermeli",
    "schema.error.expected_sign": "{where}: expected_sign 'positive' veya 'negative' olmalı, '{sign}' geldi",
    "schema.error.min_r_range": "{where}: min_r -1..1 aralığında olmalı",
    "schema.error.monotonicity_columns": (
        "{where}: 'column_x' ve 'column_y' (veya 2 elemanlı 'columns') zorunlu"
    ),
    "schema.error.direction": "{where}: direction 'increasing' veya 'decreasing' olmalı, '{direction}' geldi",
    "schema.error.min_compliance_range": "{where}: min_compliance_ratio 0..1 aralığında olmalı",
    "schema.error.primary_key_missing": "'{table}' tablosunda primary_key '{pk}' kolonlar arasında yok",
    "schema.error.numeric_bool": "{where}: '{field}' sayısal olmalı, boolean geldi",
    "schema.error.numeric_expected": "{where}: '{field}' sayısal olmalı, {value} geldi",
    "schema.warning.correlation_unknown_columns": (
        "Korelasyon kuralı düşürüldü - bilinmeyen kolon(lar) {columns} (tanımlı: {known})"
    ),
    "schema.warning.correlation_not_numeric": (
        "Korelasyon kuralı düşürüldü - {columns} sayısal/bool değil, korelasyon hesaplanamaz"
    ),
    "schema.warning.correlation_above_ceiling": "{columns} korelasyonu: min_r {requested}, bu True oranındaki bir bool kolonun ulaşabileceği en yüksek değerin ({ceiling}) üstünde - {lowered} değerine indirildi",
    "schema.warning.monotonicity_unknown_columns": (
        "Monotonluk kuralı düşürüldü - bilinmeyen kolon(lar) [{x}, {y}] (tanımlı: {known})"
    ),
    "schema.warning.monotonicity_not_numeric": (
        "Monotonluk kuralı düşürüldü - [{x}, {y}] sayısal/bool değil"
    ),
    "schema.warning.rule_unknown_names": "İş kuralı '{rule}' tanımlı olmayan ad(lar) içeriyor: {names} - kural çıkarıldı",
    "schema.warning.rule_unparseable": "İş kuralı '{rule}' geçerli bir satır ifadesi değil - kural çıkarıldı",
    "schema.warning.rule_type_mismatch": "İş kuralı '{rule}' sayısal/bool kolon(lar)ı {columns} metinle karşılaştırıyor, hiçbir satırda eşleşmez - kural çıkarıldı",
    "schema.warning.rule_pins_bool": "İş kuralı '{rule}' bool kolon(lar)ı {columns} tek bir değere sabitliyor, bu bir sınıfın tamamını silerdi - bu koşul kuraldan çıkarıldı",
    "schema.warning.bool_mean_as_ratio": "'{column}' kolonu: bool kolonun ortalaması True oranıdır - target_ratio={ratio} olarak kullanıldı",
    "schema.warning.p_index_boundary_dropped": "'{column}' kolonu: tweedie p_index {value} sınırın üzerinde (1 ile 2 arasında, sınırlar hariç olmalı) - çıkarıldı, varsayılan kullanılıyor",
    "schema.warning.preserve_column_missing": (
        "preserve_anomaly_column '{column}' tanımlı kolonlar arasında bulunamadı: {known}"
    ),
    # --- Veri seti sözleşmesi -------------------------------------------------- #
    "contract.error.contract_object": "Dataset Contract bir JSON nesnesi olmalı, {got} geldi",
    "contract.error.field_required": "{where}: '{field}' zorunlu ve boş olmayan bir metin olmalı",
    "contract.error.tables_required": "'tables' en az bir tablo içeren bir liste olmalı",
    "contract.error.duplicate_tables": "Tekrarlanan tablo adları: {tables}",
    "contract.error.relationships_list": "'relationships' bir liste olmalı",
    "contract.error.mean_per_parent_number": "{where}: 'mean_per_parent' sayı olmalı",
    "contract.error.mean_per_parent_positive": "{where}: 'mean_per_parent' pozitif olmalı",
    "contract.error.min_per_parent_int": "{where}: 'min_per_parent' tam sayı olmalı",
    "contract.error.max_per_parent_int": "{where}: 'max_per_parent' tam sayı olmalı",
    "contract.error.max_lt_min": (
        "{where}: 'max_per_parent' ({high}) 'min_per_parent'tan ({low}) küçük olamaz"
    ),
    "contract.error.relationship_table_missing": (
        "İlişki '{label}': {side} tablosu '{table}' tanımlı değil"
    ),
    "contract.error.relationship_column_missing": (
        "İlişki '{label}': '{column}' kolonu '{table}' tablosunda yok"
    ),
    "contract.error.self_parent": "İlişki '{label}': bir tablo kendi kendisinin ebeveyni olamaz",
    "contract.error.no_root_table": "Kök tablo bulunamadı - ilişkilerde döngü olabilir",
    "contract.error.cycle": (
        "İlişkilerde döngü var, üretim sırası çıkarılamıyor: {tables}"
    ),

    # --- Proje planlayıcı ------------------------------------------------------ #
    "plan.error.plan_object": "Proje planı bir JSON nesnesi olmalı, {got} geldi",
    "plan.error.leakage_list": "'excluded_leakage' bir liste olmalı",
    "plan.error.target_required": (
        "'{task}' görevinde 'target' zorunlu - hedef değişkeni olmayan bir veri seti "
        "eğitime hazır değildir"
    ),
    "plan.error.class_ratio_required": (
        "'{task}' görevinde 'positive_class_ratio' zorunlu - sınıf dengesi belirtilmemiş "
        "bir sınıflandırma veri seti kullanışlı değildir"
    ),
    "plan.error.class_ratio_range": "'positive_class_ratio' 0 ile 1 arasında olmalı, {value} geldi",
    "plan.error.split_column_missing": "split: '{column}' kolonu '{table}' tablosunda yok",
    "plan.error.split_not_datetime": (
        "split: zamana göre bölme için '{column}' bir 'datetime' kolonu olmalı, '{got}' türünde"
    ),
    "plan.warning.unsupervised_target": (
        "Görev 'unsupervised' ama bir hedef değişken verilmiş ({target}) - yok sayıldı."
    ),
    "plan.warning.class_ratio_ignored": "'{task}' görevinde sınıf dengesi anlamsız - yok sayıldı.",
    "plan.warning.class_ratio_extreme": (
        "Sınıf dengesi aşırı ({ratio}): bu orandaki bir hedef, üretilen satır sayısında "
        "anlamlı sayıda örnek vermeyebilir."
    ),
    "plan.warning.no_leakage": (
        "Hiçbir sızıntı kolonu ayıklanmamış. Çoğu gerçek problemde hedef olay sonrası "
        "bilinen en az bir alan vardır; plan bunu düşünmemiş olabilir."
    ),
    # --- Servis katmanı hataları ------------------------------------------------ #
    "service.error.package_missing": "`{package}` paketi kurulu değil",
    "service.error.auth_failed": (
        "Kimlik doğrulanamadı ({source}). Anahtar geçersiz veya süresi dolmuş."
    ),
    "service.error.forbidden": "Anahtarın bu işlem için yetkisi yok ({error}).",
    "service.error.unreachable": "Servise ulaşılamadı: {error}",
    "service.error.model_not_found": "Model bulunamadı: {model} ({error})",
    "service.error.anthropic_connection": "Anthropic bağlantı hatası: {error}",
    "service.error.anthropic_rate_limit": "Anthropic 5 denemenin sonunda da 429 (hız sınırı) döndürdü. Bir dakika bekleyip yeniden çalıştırın ya da daha küçük bir model seçin.",
    "service.error.anthropic_rate_limit_oauth": "Anthropic 5 denemenin sonunda da 429 (hız sınırı) döndürdü. Uygulama Claude Code abonelik oturumunuzu kullanıyor ve bu oturum kotasını açık her Claude Code penceresiyle paylaşıyor - onları kapatın ya da birkaç dakika bekleyin, veya bir ANTHROPIC_API_KEY tanımlayın.",
    "service.error.anthropic_bad_key": "Anthropic API anahtarı geçersiz: {error}",
    "service.error.anthropic_server": "Anthropic sunucu hatası {status}",
    "service.error.anthropic_api": "Anthropic API hatası {status}: {error}",
    "service.error.anthropic_empty": "Anthropic boş yanıt döndü (stop_reason={reason})",
    "service.error.gemini_request": "Gemini istek hatası: {error}",
    "service.error.gemini_server": "Gemini sunucu hatası: {error}",
    "service.error.gemini_api": "Gemini API hatası: {error}",
    "service.error.gemini_empty": "Gemini boş yanıt döndü",
    "service.error.ollama_unreachable": (
        "Ollama daemon'a bağlanılamadı ({host}). `ollama serve` çalışıyor mu?"
    ),
    "service.error.ollama_down": "Ollama daemon çalışmıyor ({host}). Başlatmak için: ollama serve",
    "service.error.ollama_model_missing": "Model kurulu değil: {model}. İndirmek için: ollama pull {model}",
    "service.error.ollama_bad_json_tags": "Ollama /api/tags geçersiz JSON döndü",
    "service.error.ollama_bad_json": "Ollama geçersiz JSON döndü",
    "service.error.ollama_pull_start": "Model indirme başlatılamadı: {error}",
    "service.error.ollama_pull": "Ollama pull hatası: {error}",
    "service.error.ollama_timeout": "Ollama yanıtı {seconds} saniyede gelmedi - daha küçük bir model deneyin",
    "service.error.ollama_call_failed": "Ollama çağrısı başarısız: {error}",
    "service.error.ollama_generic": "Ollama hatası: {error}",
    "service.error.ollama_empty": "Ollama boş yanıt döndü",
    "service.error.ollama_thinking_exhausted": "{model} çıktı bütçesinin tamamını ({tokens} token) düşünmeye harcadı ve cevap vermedi. deepseek-r1 gibi akıl yürüten modeller bu iş için yavaş - qwen2.5-coder gibi bir kod modeli önerilir.",
    "service.ollama.thinking_retry": "{model} çıktı bütçesini düşünmeye harcadı; {tokens} token ile bir kez daha deneniyor",
    "service.ollama.empty_retry": "{model} boş yanıt döndürdü; bir kez daha deneniyor",
    "service.error.hf_temporary": "HF geçici hata ({status}): {error}",
    "service.error.hf_auth": "HF yetkilendirme hatası ({status}): {error}",
    "service.error.hf_connection": "HF bağlantı hatası: {error}",
    "service.error.hf_generic": "HF hatası: {error}",
    "service.error.hf_dataset_empty": "Dataset boş veya okunamadı: {dataset}",
    "service.error.hf_no_token": (
        "HuggingFace token bulunamadı. Ayarlar sekmesinden girin veya HF_TOKEN ortam "
        "değişkenini tanımlayın."
    ),
    "service.error.hf_empty_data": "Yüklenecek veri boş",
    "service.error.schema_retries": (
        "{attempts} denemede geçerli Schema Contract üretilemedi. Son hata: {error}"
    ),
    "service.error.contract_retries": (
        "{attempts} denemede geçerli Dataset Contract üretilemedi. Son hata: {error}"
    ),
    "service.error.plan_retries": (
        "{attempts} denemede geçerli proje planı üretilemedi. Son hata: {error}"
    ),
    "run.error.health_check": "{provider} servisi doğrulanamadı (model: {model}). {detail}",
    "run.error.health_hint": "API anahtarını / daemon'u kontrol edin.",

    # --- Antigravity CLI (agy) ----------------------------------------------- #
    "service.agy.not_found": "`agy` komutu bulunamadı. Antigravity CLI kurulu değil: {url}",
    "service.agy.not_installed": "`agy` komutu bulunamadı - Antigravity CLI kurulu değil",
    "service.agy.session_unverified": (
        "Antigravity CLI kurulu ama oturum doğrulanamadı. "
        "Bir terminalde `agy` çalıştırıp giriş yapın."
    ),
    "service.agy.session_ok": "Antigravity CLI oturumu açık - {count} model kullanılabilir",
    "service.agy.model_invalid": (
        "Model '{model}' Antigravity CLI'da tanımlı değil. Pipeline sekmesinde "
        "Model listesini açıp geçerli bir tane seçin{hint}"
    ),
    "service.agy.model_hint": " (örn. {model})",
    "service.agy.no_details": "ayrıntı yok",
    "service.agy.not_found_hint": (
        "Antigravity CLI (`agy`) bulunamadı. Kurulum: {url} - ya da Gemini "
        "için AI Studio API anahtarı girin."
    ),
    "service.agy.credential_label": "Antigravity CLI (agy) oturumu",
    "service.agy.model_missing": "Model '{model}' Antigravity CLI'da yok. Kullanılabilir modeller: {models}",
    "service.agy.prompt_too_long": (
        "İstem Antigravity CLI için çok uzun ({length} karakter, sınır {limit}). "
        "Satır sayısını düşürün ya da AI Studio API anahtarına geçin."
    ),
    "service.agy.empty_attempts": (
        "Antigravity CLI {attempts} denemede de boş yanıt döndürdü. Ajan CLI'ı yanıt "
        "yerine bir araç çağırmış olabilir; AI Studio API anahtarına geçmek bu "
        "davranışı tamamen ortadan kaldırır. Ham çıktı: {output}"
    ),
    "service.agy.call_started": (
        "agy çağrısı başladı - CLI açılışı tek başına ~200 sn sürüyor, "
        "ilk adım olayı ondan sonra gelir."
    ),
    "service.agy.timeout": (
        "Antigravity CLI {seconds} saniyede yanıt vermedi. Ajan CLI'ı yavaştır; "
        "daha küçük bir model (örn. gemini-3.8-flash-low) deneyin ya da "
        "AI Studio API anahtarına geçin."
    ),
    "service.agy.exec_failed": "Antigravity CLI çalıştırılamadı: {error}",
    "service.agy.cli_error": "Antigravity CLI hata verdi: {error}",
    "service.agy.status_error": "Antigravity CLI '{status}' durumu döndürdü: {error}",
    "service.agy.still_running": "agy hâlâ çalışıyor ({seconds} sn)",
    "service.agy.step_progress": "agy adımı: {type} ({state}){duration}",
    "service.agy.step_duration": " - {seconds} sn",
    "service.agy.no_result_event": "Antigravity CLI sonuç olayı döndürmedi: {output}",

    # --- Validator kısa gerekçeleri ----------------------------------------- #
    "validation.z_skip.heavy_tail": "dağılım '{dist}' ağır kuyruklu/sayım tipi",
    "validation.z_skip.zero_inflated": "sıfır oranı %{pct} (sıfır-şişirilmiş)",
    "validation.z_skip.iqr_zero": "değerlerin yarısı tek noktada yığılı (IQR=0)",
    "validation.z_skip.bowley_skew": "Bowley çarpıklığı {skew} (simetrik değil)",
    "validation.iso_skip.few_rows": "yetersiz tam satır",
    "validation.corr_skip.not_numeric": "kolon sayısal değil veya yok",
    "validation.corr_skip.constant": "korelasyon hesaplanamadı (sabit kolon?)",
    "validation.dist_skip.no_seed": "seed_data_yok",
    "validation.dist_skip.no_scipy": "scipy kurulu değil",
    "validation.dist_skip.no_common_numeric": "ortak sayısal kolon bulunamadı",
    "validation.stage.correlation_guard": "Korelasyon koruma (geri alma)",

    # --- İlişkisel doğrulayıcı gerekçeleri ---------------------------------- #
    "relational.reason.no_table_or_column": "tablo veya kolon yok",
    "relational.reason.no_table": "tablo yok",
    "relational.reason.no_key_column": "anahtar kolonu yok",

    # --- Sözleşme hataları -------------------------------------------------- #
    "contract.error.min_per_parent_negative": "{where}: 'min_per_parent' negatif olamaz",
    "schema.error.foreign_keys_missing": "'{table}' tablosunda foreign_keys kolonlar arasında yok: {keys}",

    # --- Bulut ve Ollama dağınık hataları ----------------------------------- #
    "service.error.gemini_bad_key": (
        "Gemini API anahtarı geçersiz veya yetkisiz. https://aistudio.google.com/apikey "
        "üzerinden kontrol edin - ya da anahtarsız çalışmak için Antigravity CLI girişini seçin."
    ),
    "service.error.gemini_quota": (
        "Gemini kota sınırına takıldı. Biraz bekleyip tekrar deneyin ya da daha küçük bir model seçin."
    ),
    "service.error.gemini_model_missing": "Model '{model}' bulunamadı. Model listesinden başka birini seçin.",
    "service.error.gemini_rejected": "İstek reddedildi: {error}",
    "service.error.unknown_provider": "Bilinmeyen sağlayıcı: {provider}",
    "service.error.ollama_delete": "Model silinemedi: {error}",
    "console.title": "Konsol",
    "console.clear": "Temizle",
    "settings.cost.summary": "Toplam {calls} çağrı | {input_tokens} girdi + {output_tokens} çıktı token | tahmini ${cost}",
    "pipeline.engine.multi_agent": "🤖 Çoklu Ajan Konseyi (Multi-Agent)",
    # --- sonradan eklenenler: dogrulama, kimlik, ayarlar, donanim, planlayici --- #
    "common.percent": "%{value}",
    "common.unknown_error": "bilinmeyen hata",
    "schema.summary": "{domain} | {columns} kolon | hedef {rows} satır | seed {seed} | {rules} kural | {correlations} korelasyon",
    "schema.summary.monotonicity": " | {count} monotonluk kuralı",
    "schema.summary.anomaly": " | anomali koruma: {column}",
    "schema.error.missing_fields": "Schema Contract'ta zorunlu alan(lar) eksik: {fields}",
    "schema.error.root_table_missing": "root_table '{root}' tablolar arasında yok: {tables}",
    "contract.error.too_many_tables": "'tables' en fazla {limit} tablo içerebilir, {count} geldi",
    "schema.warning.distribution_dropped": "'{column}' kolonu: desteklenmeyen '{distribution}' dağılımı kaldırıldı - değerler min/max içinde üretilir",
    "schema.warning.datetime_bounds_moved": "'{column}' kolonu: datetime sınırları sayı değildi; aralık ({range}) açıklamaya taşındı",
    "schema.warning.normal_mean_filled": "'{column}' kolonu: 'normal' dağılımın ortalaması yoktu; min/max orta noktası ({mean}) kullanıldı",
    "validation.correlation_skipped": "Korelasyon [{pair}]: ölçülemedi - {reason}",
    "result.correlation_expected": "beklenen {sign} >= {min_r}",
    "relational.violation.mean": "ortalama {observed}, beklenen {expected} (+/-%{tolerance})",
    "relational.violation.max": "en yüksek {observed}, üst sınır {limit}",
    "run.warning_prefix": "UYARI: {message}",
    "run.agents.gathering": "🤖 Çoklu Ajan Konseyi toplanıyor (Domain, Statistician, Critic, Engineer)...",
    "run.agents.started": "[Ajan Konseyi] Müzakere ve denetim başlatıldı (en fazla {rounds} tur)...",
    "run.agents.consensus": "[Ajan Konseyi] Konsensüs sağlandı: {tables} tablo derlendi.",
    "cli.help.agentic": "Şemayı Çoklu Ajan Konseyi (Domain, Statistician, Critic, Engineer) ile birlikte tasarla.",
    "cli.help.max_agent_rounds": "Ajanlar arası karşıt eleştiri ve müzakere tur sayısı (varsayılan: 2).",
    "cli.auth.none_hint": "Ayarlar sekmesinden anahtar girin, veya:",
    "auth.source.unknown_provider": "bilinmeyen sağlayıcı",
    "auth.source.keyring": "işletim sistemi anahtarlığı (keyring)",
    "auth.source.env_var": "{var} ortam değişkeni",
    "auth.source.claude_code": "Claude Code OAuth oturumu",
    "auth.source.not_found": "hiçbir kaynakta bulunamadı",
    "auth.source.ant_profile": "`ant auth login` profili",
    "auth.source.agy_session": "Antigravity CLI (agy) oturumu",
    "auth.source.hf_login": "huggingface-cli login token'ı",
    "auth.source.direct": "doğrudan verildi",
    "auth.oauth.claude_note": "Açılan konsoldaki token'ı kopyalayıp yukarıdaki 'API anahtarı' alanına yapıştırın - böylece oturum süreli olmaktan çıkar.",
    "auth.oauth.claude_expired": "Claude Code oturumu bulundu ama SÜRESİ DOLMUŞ - yenilemek için bir terminalde `claude` çalıştırın",
    "auth.oauth.claude_active": "Claude Code OAuth ile oturum açık",
    "auth.oauth.hours_left": " (yaklaşık {hours} saat geçerli)",
    "auth.oauth.claude_expiring_note": "Bu oturum {hours} saat sonra doluyor. Kalıcı kullanım için 'Giriş yap' ile uzun ömürlü token üretin veya bir API anahtarı girin.",
    "auth.oauth.profile": "Profil: {path}",
    "auth.oauth.agy_installed": "Antigravity CLI kurulu - oturumu 'Test et' ile doğrulayın",
    "auth.oauth.agy_missing": "Antigravity CLI (`agy`) kurulu değil",
    "auth.oauth.agy_note": "Mevcut Antigravity oturumunuzu kullanır - API anahtarı, GCP projesi veya faturalandırma gerekmez. Karşılığında yavaştır: ajan CLI her çağrıda kendi bağlamını yüklediği için tek bir adım dakikalar sürebilir.",
    "auth.oauth.hf_token_saved": "Token kayıtlı",
    "auth.oauth.hf_not_logged_in": "huggingface-cli login yapılmamış",
    "auth.missing.message": "{provider} için kimlik bilgisi bulunamadı. Ayarlar sekmesinden anahtar girin veya {env_vars} ortam değişkenini tanımlayın{extra}.",
    "auth.missing.extra_anthropic": " ya da `claude` CLI ile oturum açın",
    "auth.missing.extra_gemini": " (https://aistudio.google.com adresinden ücretsiz alabilirsiniz) ya da Antigravity CLI girişini seçin",
    "auth.missing.extra_huggingface": " ya da `huggingface-cli login` çalıştırın",
    "settings.hf.signed_in": "Giriş yapıldı: {name}",
    "settings.hf.token_invalid": "Token doğrulanamadı: {error}",
    "settings.oauth.unsupported": "Bu sağlayıcı için OAuth girişi yok",
    "settings.oauth.command_not_found": "{command} bulunamadı",
    "settings.oauth.launch_failed": "Başlatılamadı: {error}",
    "settings.ollama.daemon_down": "Ollama servisi çalışmıyor - başlatmak için: ollama serve",
    "settings.ollama.no_models": "Ollama {version} çalışıyor - hiç model kurulu değil",
    "settings.ollama.check_failed": "Kontrol edilemedi: {error}",
    "settings.ollama.enter_model_name": "Önce bir model adı girin",
    "settings.ollama.pull_starting": "İndirme başlatılıyor...",
    "settings.ollama.pull_done": "İndirildi: {model}",
    "settings.ollama.pull_failed": "İndirilemedi: {model}",
    "settings.ollama.pull_error": "Hata: {error}",
    "service.error.refused": "Model isteği reddetti{detail}",
    "hardware.cores": "{physical} fiziksel / {logical} mantıksal",
    "hardware.cpu_unknown": "Bilinmeyen CPU",
    "hardware.gpu_none": "Yok / Entegre Grafik",
    "hardware.notes.enterprise": "Yüksek seviye GPU ({gpu}, {vram} GB VRAM). 14B ve 32B modeller tam CUDA hızında çalışabilir.",
    "hardware.notes.high": "Güçlü GPU ({gpu}, {vram} GB VRAM). 7B model tamamen ekran kartında gecikmesiz çalışır.",
    "hardware.notes.mid": "Orta seviye sistem ({vram} GB VRAM / {ram} GB RAM). 7B Q4 veya 3B model önerilir.",
    "hardware.notes.low": "Düşük donanım / entegre grafik. 986 MB'lık Qwen 1.5B modelini CPU modunda çalıştırın.",
    "hardware.report.title": "DONANIM PROFİLİ VE MODEL TAVSİYE RAPORU",
    "hardware.report.cpu": "İşlemci (CPU):",
    "hardware.report.cores": "Çekirdekler:",
    "hardware.report.ram": "Sistem RAM:",
    "hardware.report.ram_value": "{total} GB (Kullanılabilir: {available} GB)",
    "hardware.report.gpu": "Grafik Kartı:",
    "hardware.report.gpu_value": "{gpu} ({vram} GB VRAM)",
    "hardware.report.tier": "Donanım Kademesi:",
    "hardware.report.mode": "Çalışma Modu:",
    "hardware.report.model": "Önerilen Model:",
    "hardware.report.rows": "Önerilen Satır:",
    "hardware.report.rows_value": "{rows} satıra kadar optimize",
    "hardware.report.notes": "Açıklama:",
    "ollama.model.balanced": "Kod üretimi için dengeli - önerilen",
    "ollama.model.better_code": "Daha iyi kod, daha fazla RAM",
    "ollama.model.best_code": "En iyi kod kalitesi, 32 GB+ RAM",
    "ollama.model.strong_code": "Güçlü kod modeli",
    "ollama.model.general": "Genel amaçlı",
    "ollama.model.general_fast": "Genel amaçlı, hızlı",
    "ollama.model.light_fast": "Hafif, hızlı",
    "ollama.model.reasoning": "Güçlü akıl yürütme",
    "app.crash.title": "AI Synthetic Data Studio - Beklenmeyen hata",
    "app.crash.body": "Uygulama başlatılamadı.\n\n{error}\n\nAyrıntı: {path}",
    "plan.error.split_kind": "{where}: 'kind' şu değerlerden biri olmalı: {valid}",
    "plan.error.dataset_required": "'dataset' alanı zorunlu (Dataset Contract)",
    "plan.error.task_type": "'task_type' şu değerlerden biri olmalı: {valid}",
    "plan.error.leakage_required": "'excluded_leakage' alanı zorunlu - sızıntı yaratacak kolonları düşündüğünü göstermelisin (hiçbiri yoksa boş liste ver)",
    "plan.error.class_ratio_number": "'positive_class_ratio' sayı olmalı, {value} geldi",
    "plan.error.target_column_missing": "Hedef kolon '{column}', '{table}' tablosunda yok. Tanımlı kolonlar: {columns}",
    "plan.error.leakage_still_present": "Sızıntılı ilan edilen kolon(lar) sözleşmede hâlâ duruyor: {columns}. Ayıklanan kolonlar üretilmemeli - ya sözleşmeden ya da sızıntı listesinden çıkar.",
    "plan.error.target_is_leakage": "Hedef kolon '{column}' aynı zamanda sızıntı olarak işaretlenmiş",
    "plan.error.table_missing": "{where}: '{table}' tablosu sözleşmede yok. Tanımlı tablolar: {tables}",
    "plan.error.split_column_required": "split: '{kind}' bölme için 'column' zorunlu",
    "plan.error.ratio_disagreement": "Plan sınıf dengesini {plan_ratio} diyor ama '{target}' kolonunun target_ratio'su {column_ratio}. İkisi aynı sayıyı söylemeli.",
    "plan.warning.no_split": "Train/test ayrımı belirtilmemiş - varsayılan rastgele bölme doğru olmayabilir (zamana bağlı ya da aynı varlığa ait satırlar varsa).",
    "plan.summary.task": "görev: {task}",
    "plan.summary.target": "hedef: {target}",
    "plan.summary.positive_class": "pozitif sınıf: {ratio}",
    "plan.summary.tables": "{count} tablo",
    "plan.summary.leakage": "{count} sızıntı kolonu ayıklandı",
    "plan.summary.split": "bölme: {kind}",
    "web.more_sources": "(+{count} kaynak)",
    "hipaa.category.unique_key": "Benzersiz Anahtar",

    # --- Schema Sanity Checker ------------------------------------------- #
    "sanity.report.clean": "Şema sağlamlık denetimi geçti — anlamsal sorun bulunamadı.",
    "sanity.bounds.amount_missing_min": "'{column}' parasal bir tutara benziyor ama alt sınırı yok; negatif değer üretilemesin diye min 0 yapıldı.",
    "sanity.bounds.amount_negative_min": "'{column}' parasal bir tutara benziyor ama min={declared} verilmiş; 0'a çekildi. Negatif değer kastediliyorsa kolon adında belirtin (net_, adjustment_, ...) ya da otomatik düzeltmeyi kapatın.",
    "sanity.correlation.ambiguous_pair": "{col_a} ile {col_b} pozitif korelasyonun doğru olabileceği bir alan çifti; değiştirilmedi - kendiniz gözden geçirin.",
    "sanity.correlation.risk_asset_inverted": (
        "Olası anlamsal terslik: '{col_a}' ({cat_a}) ↔ '{col_b}' ({cat_b}) "
        "arasında NEGATİF korelasyon beklenir, ancak POZİTİF tanımlanmış."
    ),
    "sanity.correlation.positive_pair_inverted": (
        "Olası anlamsal terslik: '{col_a}' ↔ '{col_b}' bilinen bir pozitif çifttir, "
        "ancak NEGATİF korelasyon tanımlanmış."
    ),
    "sanity.monotonicity.asset_risk_inverted": (
        "Olası monotonluk terslikleri: '{col_x}' (varlık) ↑ → '{col_y}' (risk) "
        "AZALAN olmalı, ancak ARTAN olarak tanımlanmış."
    ),
    "sanity.monotonicity.risk_asset_inverted": (
        "Olası monotonluk terslikleri: '{col_x}' (risk) ↑ → '{col_y}' (varlık) "
        "AZALAN olmalı, ancak ARTAN olarak tanımlanmış."
    ),
    "sanity.transitivity.violation": (
        "Korelasyon geçişlilik çelişkisi: {col_a}~{col_b} ({sign_ab}), "
        "{col_b}~{col_c} ({sign_bc}) durumunda {col_a}~{col_c} için beklenen "
        "{sign_ab}×{sign_bc}, ancak ({sign_ac}) tanımlanmış."
    ),
    # --- Licensing & Pro Edition ----------------------------------------- #
    "license.error.pro_required": "{feature} özelliğini kullanmak için aktif bir Pro veya Enterprise lisansı gereklidir.",
    "license.status.missing": "Lisans yüklü değil (Topluluk Sürümü)",
    "license.status.invalid_format": "Geçersiz lisans anahtarı formatı",
    "license.status.invalid_encoding": "Hatalı lisans kodlaması",
    "license.status.signature_failed": "Geçersiz kriptografik imza",
    "license.status.invalid_payload": "Bozuk lisans verisi",
    "license.status.clock_tampered": "Lisans saat denetimi başarısız: sistem saati daha önce kaydedilen tarihin gerisinde. Sistem saatini düzeltip yeniden başlatın.",
    "license.status.bad_expiry": "Lisans bitiş tarihi okunamadı",
    "license.status.not_persisted": "Lisans doğrulandı ancak kaydedilemedi; yeniden başlatınca kaybolacak",
    "pipeline.warn.pdf_requires_license": "Denetim PDF'i yazılmadı: etkin bir Pro veya Enterprise lisansı gerekiyor.",
    "pipeline.warn.pdf_failed": "Denetim PDF'i yazılamadı: {error}",
    "license.status.revoked": "Bu lisans anahtarı iptal edilmiş ({license_key})",
    "verify.result.unsigned": "Bu dosyada provenance imzası yok; kökenini beyan ediyor ama bunu doğrulayan bir şey yok.",
    "verify.result.license": "Lisans imzası geçerli - {license_key} anahtarına verilmiş ({tier})",
    "verify.result.revoked": "Bu dosyayı imzalayan lisans iptal edilmiş",
    "verify.result.signature": "Beyan imzası geçerli - beyan o lisans tarafından üretilmiş",
    "verify.result.content": "İçerik özeti eşleşiyor - dosya, beyanın tarif ettiği veri",
    "verify.result.content_unchecked": "İçerik özeti denetlenmedi (veri dosyası verilmedi); beyan edilen {digest}...",
    "verify.error.unsigned": "Dosyada imza bloğu bulunamadı.",
    "verify.error.license_signature": "Gömülü lisans AI Synthetic Data Studio tarafından verilmemiş.",
    "verify.error.license_unreadable": "Gömülü lisans okunamadı: {error}",
    "verify.error.revoked": "{license_key} lisansı iptal listesinde.",
    "verify.error.no_report_key": "Lisans rapor imzalamadan önceki sürümden; rapor anahtarı taşımıyor.",
    "verify.error.report_signature": "Beyan, adını taşıdığı lisans tarafından imzalanmamış.",
    "verify.error.report_unreadable": "Beyan imzası okunamadı: {error}",
    "verify.error.content_mismatch": "Veri, beyandaki özetle eşleşmiyor; dosya imzalandıktan sonra değiştirilmiş.",
    "verify.error.token_format": "İmza bloğundaki lisans token'ı bozuk.",
    "cli.help.verify_report": "üretilmiş bir dosyanın provenance imzasını çevrimdışı doğrular (csv/json/parquet/pdf)",
    "cli.verify.missing_file": "dosya bulunamadı",
    "license.status.expired": "Lisans süresi {date} tarihinde doldu",
    "license.status.valid": "Aktif ve doğrulandı",
    "license.tier.community": "Topluluk Sürümü",
    "license.tier.pro": "Pro Sürüm",
    "license.tier.enterprise": "Kurumsal Sürüm",
    # --- GUI License & Edition Management -------------------------------- #
    "app.header.license_community": "Topluluk",
    "app.header.license_pro": "PRO",
    "app.header.license_enterprise": "KURUMSAL",
    "settings.license.title": "Lisans & Sürüm",
    "settings.license.note": "AI Synthetic Data Studio açık çekirdeklidir. Yönetici Özeti PDF Denetim Raporları ve gelişmiş uyumluluk araçları için Pro'yu etkinleştirin.",
    "settings.license.tier": "Mevcut Sürüm: {tier}",
    "settings.license.activate": "Lisans Etkinleştir...",
    "settings.license.deactivate": "Devre Dışı Bırak",
    "settings.license.deactivate_confirm": "Mevcut lisansı kaldırmak istediğinizden emin misiniz?",
    "settings.license.key_placeholder": "ADS-... lisans anahtarınızı buraya yapıştırın",
    "pipeline.button.export_pdf": "Denetim Raporu (PDF)",
    "pipeline.export.pdf_checkbox": "Yönetici Özeti PDF Denetim Raporu Üret (Pro)",
    "license.dialog.title": "Lisans & Sürüm Etkinleştirme",
    "license.dialog.heading": "Pro & Kurumsal Özelliklerin Kilidini Açın",
    "license.dialog.subheading": "Çevrimdışı doğrulama • Yönetici PDF Raporları • Uyumluluk Sertifikasyonu",
    "license.dialog.enter_key": "Lisans Anahtarını Girin",
    "license.dialog.activate_btn": "Lisansı Etkinleştir",
    "license.dialog.buy_btn": "Lisans Anahtarı Alın",
    "license.dialog.success": "Lisans başarıyla etkinleştirildi! {tier} sürümüne hoş geldiniz.",
    "license.dialog.activated_details": "Kayıtlı kullanıcı: {email} • Sürüm: {tier} • Bitiş: {expiry}",
}
