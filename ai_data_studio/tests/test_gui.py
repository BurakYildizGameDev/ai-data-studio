"""GUI entegrasyon testleri: pencere açılışı, view geçişleri, model seçimi ve kuyruk döngüsü."""
import gc
import queue
import threading
import time
import tkinter
import unittest

# Tk yorumlayıcısı oluşturmak Windows'ta ara sıra düşüyor. Belirti değişken:
#   Can't find a usable init.tcl in the following directories: ...
#   couldn't read file ".../tcl8.6/auto.tcl": no such file or directory
#   invalid command name "tcl_findLibrary"
# Üçü de aynı geçici hata: Tcl, yorumlayıcıyı kurarken kendi kütüphane dosyalarını
# okuyamıyor. Uygulama kodunun kusuru değil - sade `tkinter.Tk()` ile de, bu paketten
# hiçbir şey içe aktarılmadan da oluşuyor. Tetikleyici pytest'in varsayılan fd tabanlı
# çıktı yakalaması: her test etrafında 1/2 numaralı dosya tanımlayıcılarını takas
# ediyor, `--capture=sys` ya da `-s` ile hiç görülmüyor. Yeniden deneme (önce gc, sonra
# kısa bekleme) toparlıyor; ölçümde 12 koşuda 5 deneme harcandı, hiçbiri düşmedi.
_TCL_BOOTSTRAP_MARKERS = ("init.tcl", "auto.tcl", "tcl_findlibrary", "tcl8.6")
_TK_CREATE_ATTEMPTS = 4


def make_tk(factory):
    """Tk kökü oluşturur; yalnızca Tcl açılış hatasında yeniden dener.

    Widget hataları (yanlış pencere yolu, geçersiz komut adı) yeniden denenmez -
    yoksa gerçek bir hatayı gizleriz.
    """
    last: Exception | None = None
    for attempt in range(_TK_CREATE_ATTEMPTS):
        try:
            return factory()
        except tkinter.TclError as exc:
            message = str(exc).lower()
            if not any(marker in message for marker in _TCL_BOOTSTRAP_MARKERS):
                raise
            last = exc
            gc.collect()          # önceki yorumlayıcının serbest bırakılmasını hızlandır
            time.sleep(0.05 * (attempt + 1))
    raise last  # type: ignore[misc]


try:
    import customtkinter as ctk
    _root = make_tk(ctk.CTk)
    _root.withdraw()
    _root.destroy()
    GUI_AVAILABLE = True
except Exception:  # pragma: no cover - headless ortam
    GUI_AVAILABLE = False


def _fake_result(with_plan: bool):
    """show_result icin en kucuk gecerli PipelineResult benzeri nesne."""
    import types

    import pandas as pd

    from ai_data_studio.core.project_planner import ProjectPlan
    from ai_data_studio.tests.test_project_planner import plan_dict

    plan = ProjectPlan.from_dict(plan_dict(), project="churn projesi")
    contract = plan.contract
    return types.SimpleNamespace(
        job_id=7,
        schema=contract.table(contract.root_table),
        plan=plan if with_plan else None,
        dataframe=pd.DataFrame({"tenure_months": [1, 2, 3], "churned": [0, 1, 0]}),
        report={"rows_in": 100, "rows_out": 90, "retention_pct": 90.0, "stages": []},
        generation_meta={"attempts": 1, "duration_s": 1.0},
        cost={"cost_usd": 0.0, "calls": 1},
        output_paths={},
        hub_url="",
    )


@unittest.skipUnless(GUI_AVAILABLE, "Grafik ortami yok")
class TestAppWindow(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        from ai_data_studio import config
        self._settings_patch = mock.patch.object(
            config, "load_settings", return_value=dict(config.DEFAULT_SETTINGS)
        )
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)

        from ai_data_studio.gui.app_window import AppWindow
        self.app = make_tk(AppWindow)
        self.app.withdraw()          # gorunmez ac - CI/otomasyon icin
        self.app.update_idletasks()

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass

    def test_window_opens_with_all_tabs(self):
        from ai_data_studio.i18n import t

        names = self.app.tabview._name_list
        # Sekme adlari cevrilir; karsilastirma katalog uzerinden yapilmali.
        self.assertEqual(names, [t("app.tab.pipeline"), t("app.tab.history"),
                                 t("app.tab.settings")])

    def test_can_switch_between_views(self):
        from ai_data_studio.i18n import t

        for name in (t("app.tab.history"), t("app.tab.settings"), t("app.tab.pipeline")):
            self.app.tabview.set(name)
            self.app.update_idletasks()
            self.assertEqual(self.app.tabview.get(), name)

    def test_model_selector_lists_models(self):
        selector = self.app.pipeline_view.model_selector
        self.assertEqual(selector.provider, "anthropic")
        self.assertIn("claude-opus-5", selector.model_menu.cget("values"))

    def test_model_selector_switches_to_ollama(self):
        selector = self.app.pipeline_view.model_selector
        from ai_data_studio.gui.components.model_selector import PROVIDER_LABELS

        selector._on_provider_change(PROVIDER_LABELS["ollama"])
        self.app.update_idletasks()
        self.assertEqual(selector.provider, "ollama")
        # Daemon kapaliysa bile cokmemeli - liste ya modeller ya da uyari gosterir.
        self.assertTrue(selector.model_menu.cget("values"))

    def test_inner_pipeline_tabs(self):
        from ai_data_studio.i18n import t

        tabs = self.app.pipeline_view.tabs
        self.assertEqual(tabs._name_list, [t("pipeline.tab.console"),
                                           t("pipeline.tab.result"),
                                           t("pipeline.tab.charts")])

    def test_collect_inputs_returns_pipeline_config_fields(self):
        from unittest import mock
        from ai_data_studio.core.orchestrator import PipelineConfig

        selector = self.app.pipeline_view.model_selector
        with mock.patch.object(type(selector), "is_ready", return_value=True):
            inputs = self.app.pipeline_view.collect_inputs()
        cfg = PipelineConfig(**inputs)        # alan adlari eslesmezse TypeError
        self.assertGreater(cfg.row_count, 0)
        self.assertTrue(cfg.domain_prompt)

    def test_project_mode_fills_project_prompt(self):
        """Proje kipinde ayni metin hem domain_prompt hem project_prompt olmali."""
        from unittest import mock
        from ai_data_studio.gui.views.pipeline_view import MODE_PROJECT

        view = self.app.pipeline_view
        view.mode_selector.set(MODE_PROJECT)
        view._on_mode_change(MODE_PROJECT)
        self.assertTrue(view.is_project_mode)

        selector = view.model_selector
        with mock.patch.object(type(selector), "is_ready", return_value=True):
            inputs = view.collect_inputs()
        self.assertTrue(inputs["project_prompt"])
        self.assertEqual(inputs["project_prompt"], inputs["domain_prompt"])

    def test_row_count_label_follows_input_mode(self):
        """Proje kipinde satir sayisi KOK tabloya uygulanir; etiket bunu soylemeli."""
        from ai_data_studio.gui.views.pipeline_view import MODE_DOMAIN, MODE_PROJECT

        from ai_data_studio.i18n import t

        view = self.app.pipeline_view
        self.assertEqual(view.rows_label.cget("text"), t("pipeline.rows.label"))

        view.mode_selector.set(MODE_PROJECT)
        view._on_mode_change(MODE_PROJECT)
        self.assertEqual(view.rows_label.cget("text"), t("pipeline.rows.label_root"))

        view.mode_selector.set(MODE_DOMAIN)
        view._on_mode_change(MODE_DOMAIN)
        self.assertEqual(view.rows_label.cget("text"), t("pipeline.rows.label"))

    def test_result_tab_shows_project_plan(self):
        """CLI'in bastigi plan kararlari Sonuç sekmesinde de gorunmeli (F5)."""
        view = self.app.pipeline_view
        from ai_data_studio.i18n import t

        view.show_result(_fake_result(with_plan=True))
        text = view.result_box.get("1.0", "end-1c")

        self.assertIn(t("result.section.plan"), text)
        self.assertIn("customers.churned", text)        # hedef degisken
        self.assertIn(t("result.plan.positive_pct", pct="18.0"), text)  # sinif dengesi
        self.assertIn("temporal", text)                 # train/test ayrimi
        self.assertIn("cancellation_reason", text)      # ayiklanan sizinti kolonu

    def test_result_tab_has_no_plan_section_without_plan(self):
        """Veri tarifi kipinde plan yok - sonuc dokumu eskisi gibi kalmali."""
        view = self.app.pipeline_view
        view.show_result(_fake_result(with_plan=False))
        text = view.result_box.get("1.0", "end-1c")

        from ai_data_studio.i18n import t

        self.assertNotIn(t("result.section.plan"), text)
        self.assertIn(t("result.section.stages"), text)

    def test_start_is_blocked_with_actionable_message_when_no_credential(self):
        """Kullanicinin en çok takildigi yer: kimlik yokken 'Başlat' ne diyor?"""
        from unittest import mock

        selector = self.app.pipeline_view.model_selector
        with mock.patch.object(type(selector), "is_ready", return_value=False), \
             mock.patch.object(type(selector), "readiness_message",
                               return_value="Anthropic için kimlik tanımlı değil. "
                                            "'Ayarla' ile API anahtarı girin."):
            with self.assertRaises(ValueError) as ctx:
                self.app.pipeline_view.collect_inputs()
        message = str(ctx.exception)
        self.assertIn("Ayarla", message)          # ne yapacagini soyluyor
        self.assertIn("kimlik", message.lower())

    def test_readiness_reflects_credential_and_model(self):
        from unittest import mock
        from ai_data_studio import config
        from ai_data_studio.i18n import t

        selector = self.app.pipeline_view.model_selector
        with mock.patch.object(config, "credential_status",
                               return_value={"configured": True, "explicit": True,
                                             "source": "keyring", "kind": "api_key",
                                             "checked_env_vars": []}):
            selector._update_readiness()
            self.assertTrue(selector.is_ready())

        with mock.patch.object(config, "credential_status",
                               return_value={"configured": False, "explicit": False,
                                             "source": "yok", "kind": "none",
                                             "checked_env_vars": ["X"]}):
            selector._update_readiness()
            self.assertFalse(selector.is_ready())
            self.assertIn(t("model.configure"), selector.readiness_message())

    def test_empty_prompt_is_rejected(self):
        view = self.app.pipeline_view
        view.prompt_box.delete("1.0", "end")
        with self.assertRaises(ValueError):
            view.collect_inputs()

    def test_invalid_seed_is_rejected(self):
        view = self.app.pipeline_view
        view.seed_entry.delete(0, "end")
        view.seed_entry.insert(0, "abc")
        with self.assertRaises(ValueError):
            view.collect_inputs()

    def test_console_writes_and_clears(self):
        console = self.app.console
        console.write("test satırı", "success")
        self.assertIn("test satırı", console.get_text())
        console.clear()
        self.assertEqual(console.get_text().strip(), "")

    def test_start_pipeline_switches_to_console_tab(self):
        from unittest import mock
        from ai_data_studio.gui.views.pipeline_view import TAB_CONSOLE, TAB_CHARTS
        self.app.pipeline_view.tabs.set(TAB_CHARTS)
        with mock.patch("threading.Thread.start"):
            self.app.start_pipeline()
        self.assertEqual(self.app.pipeline_view.tabs.get(), TAB_CONSOLE)

    def test_progress_panel_updates(self):
        panel = self.app.pipeline_view.progress_panel
        panel.update_progress(4, 50.0, "Kod uretiliyor")
        self.app.update_idletasks()
        self.assertAlmostEqual(panel.progress_bar.get(), 0.5, places=3)
        self.assertIn("Kod uretiliyor", panel.status_label.cget("text"))

    def test_cancel_button_disabled_until_running(self):
        panel = self.app.pipeline_view.progress_panel
        self.assertEqual(panel.cancel_button.cget("state"), "disabled")
        panel.set_running(True)
        self.assertEqual(panel.cancel_button.cget("state"), "normal")
        self.assertEqual(panel.start_button.cget("state"), "disabled")

    def test_handle_event_updates_widgets_from_main_thread(self):
        """Kuyruk olayları arayüz bileşenlerini güvenle günceller."""
        self.app.handle_event("progress", {
            "step": 2, "total_steps": 7, "name": "Şema", "percent": 28.6,
            "message": "Şema hazır", "detail": {},
        })
        self.app.update_idletasks()
        self.assertIn("Şema hazır", self.app.console.get_text())
        self.assertAlmostEqual(self.app.pipeline_view.progress_panel.progress_bar.get(),
                               0.286, places=2)

        self.app.handle_event("error", "test hatası")
        self.assertIn("test hatası", self.app.console.get_text())

        from ai_data_studio.i18n import t

        self.app.handle_event("cancelled", None)
        self.assertIn(t("app.cancelled.console").lower(),
                      self.app.console.get_text().lower())

    def test_llm_progress_event_goes_to_console_without_moving_the_bar(self):
        """LLM cagrisinin icinden gelen ara durum: konsola dusmeli, yuzdeye dokunmamali."""
        panel = self.app.pipeline_view.progress_panel
        panel.update_progress(4, 50.0, "Kod uretiliyor")
        self.app.update_idletasks()

        self.app.handle_event("llm_progress", "agy adımı: agent_response (DONE) - 3.6 sn")
        self.app.update_idletasks()

        self.assertIn("agent_response", self.app.console.get_text())
        self.assertAlmostEqual(panel.progress_bar.get(), 0.5, places=3)

    def test_pipeline_task_passes_a_progress_callback(self):
        """Worker thread'den gelen bildirim widget'a degil kuyruga yazmali."""
        from unittest import mock
        from ai_data_studio.core.orchestrator import PipelineConfig

        captured = {}

        def fake_run_pipeline(cfg, cancel_event, state, llm_progress_cb=None):
            captured["cb"] = llm_progress_cb
            return iter(())

        cfg = PipelineConfig(domain_prompt="test", provider="fake", row_count=100)
        with mock.patch("ai_data_studio.gui.app_window.run_pipeline", fake_run_pipeline):
            self.app._pipeline_task(cfg, threading.Event())

        self.assertIsNotNone(captured["cb"])
        captured["cb"]("agy adımı: user_input (DONE)")
        self.assertEqual(self.app.ui_queue.get_nowait(),
                         ("llm_progress", "agy adımı: user_input (DONE)"))

    def test_full_pipeline_through_gui_queue(self):
        """PipelineWorker -> ui_queue -> poll_queue -> widget olay zinciri."""
        import tempfile
        from pathlib import Path

        from ai_data_studio.core.orchestrator import PipelineConfig, run_pipeline
        from ai_data_studio.tests.fake_llm import FakeLLMClient

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = PipelineConfig(domain_prompt="gui testi", provider="fake", row_count=2000,
                             export_formats=["csv"], output_dir=Path(tmp.name))

        def task_fn(cancel_event):
            return run_pipeline(cfg, cancel_event, self.app.state_manager,
                                llm_client=FakeLLMClient())

        self.app.cancel_event = threading.Event()
        self.app.ui_queue = queue.Queue()
        from ai_data_studio.core.orchestrator import PipelineWorker
        self.app.worker = PipelineWorker(task_fn, self.app.ui_queue, self.app.cancel_event)
        self.app.worker.start()

        # Ana thread'de poll dongusunu simule et.
        # NOT: Timer daemon olmali ve iptal edilmeli - aksi halde test 2 saniyede
        # bitse bile yorumlayici cikista bu thread'i suresi dolana kadar bekler
        # ve tum paket dakikalarca "bitmis gorunup" asili kalir.
        deadline = threading.Event()
        watchdog = threading.Timer(60, deadline.set)
        watchdog.daemon = True
        watchdog.start()
        self.addCleanup(watchdog.cancel)
        while self.app.worker.is_alive() and not deadline.is_set():
            self.app.poll_queue()
            self.app.update()
        self.app.worker.join(timeout=10)
        self.app.poll_queue()
        self.app.update_idletasks()

        from ai_data_studio.i18n import t

        self.assertIsNotNone(self.app._last_result, "Pipeline sonuç uretmedi")
        text = self.app.console.get_text()
        self.assertIn(t("app.done.separator"), text)
        self.assertIn("clean rows", text)
        # Sonuc sekmesi doldu ve grafikler cizildi
        self.assertIn("JOB #", self.app.pipeline_view.result_box.get("1.0", "end-1c"))
        self.assertGreater(len(self.app.pipeline_view.chart_panel._images), 0)


class TestEngineLines(unittest.TestCase):
    """Motor özeti saf metin üretimi - grafik ortamı gerektirmez."""

    def _report(self):
        return {
            "engines": {
                "generation": "parametric",
                "time_series": {"unique_entities": 250, "burst_anomalies_count": 40,
                                "time_range": "2026-08-01 to 2026-09-01"},
                "feature_expander": {"added_columns_count": 2, "total_columns": 9,
                                     "added_columns": ["age_group", "hour_of_day"]},
                "dirty_data": {"corrupted_rows": 100, "corrupted_rate": 0.05,
                               "corruption_breakdown": {"missing": 40, "typo": 30,
                                                        "outlier_spike": 20, "casing": 25}},
            }
        }

    def test_empty_when_no_engines_ran(self):
        from ai_data_studio.gui.views.pipeline_view import engine_lines
        self.assertEqual(engine_lines({}), [])
        self.assertEqual(engine_lines({"engines": {}}), [])

    def test_renders_every_engine_block(self):
        from ai_data_studio.gui.views.pipeline_view import engine_lines

        from ai_data_studio.i18n import t

        text = "\n".join(engine_lines(self._report()))
        self.assertIn("parametric", text)
        self.assertIn("250", text)                 # tekil varlik
        self.assertIn("age_group", text)           # turetilen kolon
        # Kirlilik sirasi mutlaka yazili olmali - hangi dilde olursa olsun.
        self.assertIn(t("result.engines.dirty_value", rows="100", rate="5.0"), text)

    def test_engine_label_round_trip(self):
        from ai_data_studio.gui.views import pipeline_view as pv

        for label, value in pv.ENGINE_LABELS.items():
            self.assertEqual(pv._engine_label(value), label)
        self.assertEqual(pv._engine_label("bilinmeyen"), next(iter(pv.ENGINE_LABELS)))


@unittest.skipUnless(GUI_AVAILABLE, "Grafik ortami yok")
class TestEngineControls(unittest.TestCase):
    """Pipeline ekranındaki motor anahtarları CLI bayraklarıyla eşleşmeli."""

    def setUp(self):
        from unittest import mock
        from ai_data_studio import config
        self._settings_patch = mock.patch.object(
            config, "load_settings", return_value=dict(config.DEFAULT_SETTINGS)
        )
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)

        from ai_data_studio.gui.app_window import AppWindow
        self.app = make_tk(AppWindow)
        self.app.withdraw()
        self.app.update_idletasks()
        self.view = self.app.pipeline_view

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass

    def _inputs(self):
        from unittest import mock
        selector = self.view.model_selector
        with mock.patch.object(type(selector), "is_ready", return_value=True):
            return self.view.collect_inputs()

    def test_defaults_match_cli_defaults(self):
        from ai_data_studio.core.orchestrator import ENGINE_LLM

        inputs = self._inputs()
        self.assertEqual(inputs["engine"], ENGINE_LLM)
        self.assertFalse(inputs["time_series"])
        self.assertFalse(inputs["expand_features"])
        self.assertEqual(inputs["dirty_rate"], 0.0)

    def test_selecting_parametric_reaches_pipeline_config(self):
        from ai_data_studio.core.orchestrator import ENGINE_PARAMETRIC, PipelineConfig
        from ai_data_studio.gui.views.pipeline_view import _engine_label

        self.view.engine_menu.set(_engine_label(ENGINE_PARAMETRIC))
        self.view._on_engine_change(self.view.engine_menu.get())
        self.view.time_series_var.set(True)
        self.view.expand_features_var.set(True)

        cfg = PipelineConfig(**self._inputs())     # alan adlari eslesmezse TypeError
        self.assertEqual(cfg.engine, ENGINE_PARAMETRIC)
        self.assertTrue(cfg.time_series)
        self.assertTrue(cfg.expand_features)

    def test_engine_hint_follows_selection(self):
        from ai_data_studio.core.orchestrator import ENGINE_PARAMETRIC
        from ai_data_studio.gui.views.pipeline_view import ENGINE_HINTS, _engine_label

        self.view.engine_menu.set(_engine_label(ENGINE_PARAMETRIC))
        self.view._on_engine_change(self.view.engine_menu.get())
        self.assertEqual(self.view.engine_hint.cget("text"), ENGINE_HINTS[ENGINE_PARAMETRIC])

    def test_dirty_rate_is_percentage(self):
        self.view.dirty_var.set(True)
        self.view._toggle_dirty()
        self.view.dirty_entry.delete(0, "end")
        self.view.dirty_entry.insert(0, "5")
        self.assertAlmostEqual(self._inputs()["dirty_rate"], 0.05)

    def test_dirty_entry_disabled_while_unchecked(self):
        self.view.dirty_var.set(False)
        self.view._toggle_dirty()
        self.assertEqual(str(self.view.dirty_entry.cget("state")), "disabled")

    def test_invalid_dirty_rate_is_rejected(self):
        self.view.dirty_var.set(True)
        self.view._toggle_dirty()
        self.view.dirty_entry.delete(0, "end")
        self.view.dirty_entry.insert(0, "abc")
        with self.assertRaises(ValueError):
            self._inputs()

        self.view.dirty_entry.delete(0, "end")
        self.view.dirty_entry.insert(0, "150")
        with self.assertRaises(ValueError):
            self._inputs()


def _relational_report():
    return {
        "rows_in": 100, "rows_out": 90, "retention_pct": 90.0, "stages": [],
        "relational": {
            "pass": False,
            "repair_enabled": True,
            "row_counts": {"customers": 2000, "orders": 5600},
            "repair": {"removed_total": 12},
            "foreign_keys": [{"relationship": "customers.customer_id -> orders.customer_id",
                              "orphan_rows": 3, "orphan_pct": 0.05, "pass": False}],
            "cardinality": [{"relationship": "customers.customer_id -> orders.customer_id",
                             "observed_mean": 2.80, "expected_mean": 3.00,
                             "pass": False, "violations": ["ortalama 2.80, beklenen 3.00"]}],
            "primary_keys": [{"table": "orders", "primary_key": "order_id", "pass": True}],
        },
    }


class TestRelationalLines(unittest.TestCase):
    """İlişkisel özet metni - grafik ortamı gerektirmez."""

    def test_empty_for_single_table_runs(self):
        from ai_data_studio.gui.views.pipeline_view import relational_lines
        self.assertEqual(relational_lines({}), [])
        self.assertEqual(relational_lines({"rows_in": 10}), [])

    def test_reports_row_counts_orphans_and_cardinality(self):
        from ai_data_studio.gui.views.pipeline_view import relational_lines

        from ai_data_studio.i18n import t

        text = "\n".join(relational_lines(_relational_report()))
        self.assertIn(t("result.relational.failed"), text)
        self.assertIn("2,000", text)                              # tablo satir sayisi
        self.assertIn("5,600", text)
        self.assertIn(t("result.relational.violation"), text)     # yetim FK
        self.assertIn(t("result.relational.deviation"), text)     # kardinalite
        self.assertIn("12", text)                                 # onarimda silinen

    def test_says_when_orphan_repair_is_off(self):
        from ai_data_studio.gui.views.pipeline_view import relational_lines

        report = _relational_report()
        from ai_data_studio.i18n import t

        report["relational"]["repair_enabled"] = False
        self.assertIn(t("result.relational.repair_off"),
                      "\n".join(relational_lines(report)))


@unittest.skipUnless(GUI_AVAILABLE, "Grafik ortami yok")
class TestRelationalControls(unittest.TestCase):
    """Pipeline ekranındaki ilişkisel anahtarlar CLI bayraklarıyla eşleşmeli."""

    def setUp(self):
        from unittest import mock
        from ai_data_studio import config
        self._settings_patch = mock.patch.object(
            config, "load_settings", return_value=dict(config.DEFAULT_SETTINGS)
        )
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)

        from ai_data_studio.gui.app_window import AppWindow
        self.app = make_tk(AppWindow)
        self.app.withdraw()
        self.app.update_idletasks()
        self.view = self.app.pipeline_view

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass

    def _inputs(self):
        from unittest import mock
        selector = self.view.model_selector
        with mock.patch.object(type(selector), "is_ready", return_value=True):
            return self.view.collect_inputs()

    def test_defaults_are_single_table(self):
        inputs = self._inputs()
        self.assertFalse(inputs["relational"])
        self.assertTrue(inputs["repair_orphans"])

    def test_enabling_reaches_pipeline_config(self):
        from ai_data_studio.core.orchestrator import PipelineConfig

        self.view.relational_var.set(True)
        self.view._toggle_relational()
        self.view.max_tables_entry.delete(0, "end")
        self.view.max_tables_entry.insert(0, "4")
        self.view.repair_orphans_var.set(False)

        cfg = PipelineConfig(**self._inputs())
        self.assertTrue(cfg.relational)
        self.assertEqual(cfg.max_tables, 4)
        self.assertFalse(cfg.repair_orphans)

    def test_project_mode_disables_the_relational_switch(self):
        """Proje kipinde tablo sayısına planlayıcı karar verir - iki anahtar
        çelişemez."""
        from ai_data_studio.gui.views.pipeline_view import MODE_PROJECT

        self.view.relational_var.set(True)
        self.view._toggle_relational()
        self.view.mode_selector.set(MODE_PROJECT)
        self.view._on_mode_change(MODE_PROJECT)

        self.assertFalse(self.view.relational_var.get())
        self.assertEqual(str(self.view.relational_check.cget("state")), "disabled")
        self.assertFalse(self._inputs()["relational"])

    def test_parametric_engine_with_relational_is_accepted_in_the_form(self):
        """Parametrik motor ilişkisel kipte de desteklenir."""
        from ai_data_studio.core.orchestrator import ENGINE_PARAMETRIC
        from ai_data_studio.gui.views.pipeline_view import _engine_label

        self.view.relational_var.set(True)
        self.view._toggle_relational()
        self.view.engine_menu.set(_engine_label(ENGINE_PARAMETRIC))
        inputs = self._inputs()
        self.assertTrue(inputs["relational"])
        self.assertEqual(inputs["engine"], ENGINE_PARAMETRIC)

    def test_table_count_bounds_are_enforced(self):
        self.view.relational_var.set(True)
        self.view._toggle_relational()
        for bad in ("1", "13", "abc"):
            self.view.max_tables_entry.delete(0, "end")
            self.view.max_tables_entry.insert(0, bad)
            with self.assertRaises(ValueError):
                self._inputs()


@unittest.skipUnless(GUI_AVAILABLE, "Grafik ortami yok")
class TestChartPanelTableSelector(unittest.TestCase):
    """Grafik paneli çok tablolu koşuda tablo seçici gösterir."""

    def setUp(self):
        import customtkinter as ctk
        from ai_data_studio.gui.components.chart_panel import ChartPanel

        self.root = make_tk(ctk.CTk)
        self.root.withdraw()
        self.panel = ChartPanel(self.root)
        self.panel.pack()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def _two_tables(self):
        import pandas as pd
        from ai_data_studio.core.dataset_contract import DatasetContract
        from ai_data_studio.tests.fake_llm import DATASET_CONTRACT_JSON

        contract = DatasetContract.from_dict(DATASET_CONTRACT_JSON)
        tables = {
            "customers": pd.DataFrame({"customer_id": range(50),
                                       "tenure_months": range(50),
                                       "monthly_fee": [float(i) for i in range(50)]}),
            "orders": pd.DataFrame({"order_id": range(80), "customer_id": range(80),
                                    "order_amount": [float(i) for i in range(80)]}),
        }
        return contract, tables

    def test_selector_is_hidden_for_a_single_table(self):
        import pandas as pd
        from ai_data_studio.core.schema_contract import SchemaContract
        from ai_data_studio.tests.fake_llm import SCHEMA_JSON

        schema = SchemaContract.from_dict(SCHEMA_JSON)
        df = pd.DataFrame({c.name: [1, 2, 3] for c in schema.columns})
        self.panel.render(df, schema, {"stages": []})
        self.root.update_idletasks()
        self.assertEqual(self.panel.table_menu.winfo_manager(), '')

    def test_selector_lists_every_table_in_generation_order(self):
        contract, tables = self._two_tables()
        self.panel.render(tables["customers"], contract.table("customers"),
                          {"stages": []}, contract=contract, tables=tables)
        self.root.update_idletasks()
        self.assertEqual(self.panel.table_menu.winfo_manager(), 'grid')
        self.assertEqual(list(self.panel.table_menu.cget("values")),
                         list(contract.generation_order()))
        self.assertEqual(self.panel.table_menu.get(), contract.root_table)

    def test_switching_table_redraws_without_leaking_images(self):
        """Eski görüntüler temizlenmeli: _images listesi çöp toplayıcıya karşı
        referans tutuyor, temizlenmezse bellek büyür."""
        contract, tables = self._two_tables()
        self.panel.render(tables["customers"], contract.table("customers"),
                          {"stages": []}, contract=contract, tables=tables)
        first = len(self.panel._images)
        self.assertGreater(first, 0)

        self.panel._on_table_change("orders")
        self.root.update_idletasks()
        self.assertGreater(len(self.panel._images), 0)
        self.assertLessEqual(len(self.panel._images), first + 1)

    def test_clear_hides_the_selector_again(self):
        contract, tables = self._two_tables()
        self.panel.render(tables["customers"], contract.table("customers"),
                          {"stages": []}, contract=contract, tables=tables)
        self.panel.clear()
        self.root.update_idletasks()
        self.assertEqual(self.panel.table_menu.winfo_manager(), '')
        self.assertEqual(self.panel._images, [])


@unittest.skipUnless(GUI_AVAILABLE, "Grafik ortami yok")
class TestChartRendering(unittest.TestCase):
    """Matplotlib Agg backend ve CTkImage render deseni."""

    def test_matplotlib_uses_agg_backend(self):
        import ai_data_studio.gui.components.chart_panel  # noqa: F401  (Agg'i set eder)
        import matplotlib
        self.assertEqual(matplotlib.get_backend().lower(), "agg")

    def test_charts_render_to_ctkimage(self):
        import customtkinter as ctk
        import numpy as np
        import pandas as pd

        from ai_data_studio.gui.components import chart_panel

        root = make_tk(ctk.CTk)
        root.withdraw()
        self.addCleanup(root.destroy)

        rng = np.random.default_rng(0)
        df = pd.DataFrame({"a": rng.normal(0, 1, 500), "b": rng.normal(5, 2, 500)})
        report = {"stages": [{"stage": "Duplicate", "removed": 12},
                             {"stage": "Z-Score", "removed": 30}]}

        self.assertIsInstance(chart_panel.make_retention_chart(report), ctk.CTkImage)
        self.assertIsInstance(chart_panel.make_distribution_chart(df, "a"), ctk.CTkImage)
        self.assertIsInstance(chart_panel.make_correlation_chart(df, ["a", "b"]), ctk.CTkImage)

    def test_no_interactive_backend_import(self):
        """FigureCanvasTkAgg kullanilmamali - PyInstaller'da çakışır.

        Docstring/yorum metni değil, gerçek kod taranir (AST)."""
        offenders = _scan_identifiers(_gui_dir(), {"FigureCanvasTkAgg"})
        self.assertEqual(offenders, [],
                         "Interaktif matplotlib backend'i kullanan dosyalar: %s" % offenders)


def _gui_dir():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent / "gui"


def _scan_identifiers(directory, forbidden: set) -> list:
    """Dizindeki Python dosyalarinda yasakli adlarin GERÇEK kod kullanimini arar.

    Metin taramasi yapmaz - docstring ve yorumlarda geçen ad bulgu sayilmaz.
    """
    import ast

    offenders = []
    for path in sorted(directory.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            hit = None
            if isinstance(node, ast.Import):
                hit = next((a.name.split(".")[0] for a in node.names
                            if a.name.split(".")[0] in forbidden), None)
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                hit = root if root in forbidden else next(
                    (a.name for a in node.names if a.name in forbidden), None)
            elif isinstance(node, ast.Name) and node.id in forbidden:
                hit = node.id
            elif isinstance(node, ast.Attribute) and node.attr in forbidden:
                hit = node.attr
            if hit:
                offenders.append("%s:%s -> %s" % (path.name, node.lineno, hit))
    return offenders


class TestArchitectureRules(unittest.TestCase):
    """Grafik ortami gerektirmeyen statik mimari kuralları denetimi."""

    def test_gui_never_opens_sqlite_directly(self):
        """GUI kodunda doğrudan veritabanı erişimi olmamalı (StateManager kullanılmalı).

        Docstring/yorum metni değil, gerçek kod taranır (AST)."""
        offenders = _scan_identifiers(_gui_dir(), {"sqlite3"})
        self.assertEqual(offenders, [],
                         "GUI dosyaları doğrudan SQLite'a bağlanıyor: %s" % offenders)

    def test_all_file_writes_specify_utf8(self):
        """to_csv / to_json / open çağrılarında utf-8 encoding zorunludur."""
        import re
        from pathlib import Path

        package = Path(__file__).resolve().parent.parent
        offenders = []
        for path in package.rglob("*.py"):
            if path.parent.name == "tests":
                continue
            source = path.read_text(encoding="utf-8")
            for match in re.finditer(r"\.to_csv\(([^)]*)\)", source, re.DOTALL):
                if "encoding" not in match.group(1):
                    offenders.append("%s: to_csv" % path.name)
            for match in re.finditer(r"(?<![.\w])open\(([^)]*)\)", source, re.DOTALL):
                args = match.group(1)
                if '"w"' in args or "'w'" in args or '"r"' in args or "'r'" in args:
                    if "encoding" not in args:
                        offenders.append("%s: open" % path.name)
        self.assertEqual(offenders, [], "encoding='utf-8' eksik: %s" % offenders)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(GUI_AVAILABLE, "Grafik ortami yok")
class TestAuthAndOllamaDialogs(unittest.TestCase):
    """Uygulama içi kimlik ve Ollama model yönetimi diyaloglari."""

    def setUp(self):
        import customtkinter as ctk
        self.root = make_tk(ctk.CTk)
        self.root.withdraw()
        self.addCleanup(self._destroy)

    def _destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_auth_dialog_offers_both_methods(self):
        from ai_data_studio import config
        from ai_data_studio.gui.components.auth_dialog import AuthDialog
        from ai_data_studio.i18n import t

        # Etiket sağlayıcıya göre değişir: Gemini'nin anahtarsız yolu Antigravity CLI.
        gemini = AuthDialog(self.root, config.PROVIDER_GEMINI)
        self.root.update_idletasks()
        self.assertEqual(list(gemini.method.cget("values")),
                         [t("auth.method.api_key"), t("auth.method.agy")])
        gemini.destroy()

        claude = AuthDialog(self.root, config.PROVIDER_ANTHROPIC)
        self.root.update_idletasks()
        self.assertEqual(list(claude.method.cget("values")),
                         [t("auth.method.api_key"), t("auth.method.oauth")])
        claude.destroy()

    def test_auth_dialog_opens_for_both_providers(self):
        from ai_data_studio import config
        from ai_data_studio.gui.components.auth_dialog import AuthDialog

        # Gemini iki yol sunar: AI Studio anahtari + Antigravity CLI oturumu.
        gemini = AuthDialog(self.root, config.PROVIDER_GEMINI)
        self.root.update_idletasks()
        self.assertTrue(gemini.oauth_supported)
        self.assertIsNotNone(gemini.oauth_frame)
        self.assertIn("aistudio.google.com", _all_text(gemini.api_frame))
        # CLI bolumu: bu yolu secme butonu + hiz uyarisi
        self.assertIsNotNone(gemini.use_cli_button)
        oauth_text = _all_text(gemini.oauth_frame)
        self.assertIn("Antigravity CLI", oauth_text)
        self.assertIn(config.AGY_EXECUTABLE, oauth_text)
        gemini.destroy()

        anthropic = AuthDialog(self.root, config.PROVIDER_ANTHROPIC)
        self.root.update_idletasks()
        self.assertTrue(hasattr(anthropic, "oauth_frame"))
        anthropic.destroy()

    def test_auth_dialog_shows_login_command(self):
        from ai_data_studio import config
        from ai_data_studio.gui.components.auth_dialog import AuthDialog

        dialog = AuthDialog(self.root, config.PROVIDER_ANTHROPIC)
        self.root.update_idletasks()
        self.assertTrue(dialog.oauth_supported)
        command = " ".join(config.oauth_status(config.PROVIDER_ANTHROPIC)["command"])
        self.assertIn(command, _all_text(dialog.oauth_frame))
        dialog.destroy()

    def test_ollama_dialog_lists_installed_and_available(self):
        from unittest import mock
        from ai_data_studio.gui.components.ollama_dialog import OllamaDialog
        from ai_data_studio.services import ollama_service

        catalog = [
            {"name": "qwen2.5-coder:14b", "installed": True, "size": "9.0 GB",
             "detail": "14.8B Q4_K_M"},
            {"name": "llama3.1:8b", "installed": False, "size": "4.9 GB",
             "detail": "Genel amacli"},
        ]
        with mock.patch.object(ollama_service, "is_available", return_value=True), \
             mock.patch.object(ollama_service, "get_version", return_value="0.6.2"), \
             mock.patch.object(ollama_service, "catalog", return_value=catalog):
            dialog = OllamaDialog(self.root)
            dialog._render(True, "0.6.2", catalog)
            self.root.update_idletasks()

        from ai_data_studio.i18n import t

        labels = _all_text(dialog.list_frame)
        self.assertIn(t("ollama.section.installed"), labels)
        self.assertIn(t("ollama.section.available"), labels)
        self.assertIn("qwen2.5-coder:14b", labels)
        self.assertIn("llama3.1:8b", labels)
        self.assertIn("9.0 GB", labels)
        dialog.destroy()

    def test_ollama_dialog_handles_dead_daemon(self):
        from ai_data_studio.gui.components.ollama_dialog import OllamaDialog

        dialog = OllamaDialog(self.root)
        dialog._render(False, None, [])
        self.root.update_idletasks()
        self.assertIn("ollama serve", dialog.daemon_label.cget("text"))
        dialog.destroy()


def _all_text(widget) -> str:
    """Bir widget agacindaki tüm metinleri tek stringde toplar."""
    parts = []
    for child in widget.winfo_children():
        try:
            if "text" in child.keys():
                parts.append(str(child.cget("text")))
        except Exception:
            pass
        parts.append(_all_text(child))
    return " ".join(parts)
