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
    "result.relational.pk_not_unique": "UYARI: '{table}' birincil anahtarı '{key}' tekil değil",
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
    "pipeline.error.parametric_relational": (
        "Parametrik motor çok tablolu üretimi desteklemiyor: yabancı anahtar "
        "tutarlılığını kuramıyor. Üretim motorunu 'LLM kod üretimi' yapın ya da "
        "ilişkisel kutusunu kapatın."
    ),
    "pipeline.error.folder_open": "Klasör açılamadı: {error}",
}
