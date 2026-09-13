"""Ana pencere - queue polling, durum yönetimi ve arayüz koordinasyonu.

Thread güvenliği prensibi: CustomTkinter ana UI thread'i dışında çağrılmaz.
  * Ağır arka plan işleri PipelineWorker thread'inde koşar ve widget'lara dokunmaz.
  * Worker yalnızca ui_queue'ya olay nesneleri gönderir.
  * Ana thread `after(100, poll_queue)` ile kuyruğu tüketir ve arayüzü günceller.

Veritabanı kuralı: GUI bileşenleri doğrudan veritabanı bağlantısı açmaz,
tüm kalıcılık işlemleri StateManager üzerinden yürütülür.
"""
from __future__ import annotations

import logging
import queue
import threading
from functools import partial
from pathlib import Path
from typing import Any, Dict, Optional

import customtkinter as ctk

from .. import config
from ..core.orchestrator import (
    PipelineConfig,
    PipelineResult,
    PipelineWorker,
    run_pipeline,
)
from ..core.state_manager import get_state_manager
from .thread_bridge import post_to_ui
from .ui_utils import (
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_MUTED,
    COLOR_OK,
    COLOR_WARN,
    left_align_tabs,
    status_dot,
)
from ..i18n import t
from .views.history_view import HistoryView
from .views.pipeline_view import PipelineView
from .views.settings_view import SettingsView

log = logging.getLogger(__name__)

POLL_INTERVAL_MS = 100

# Sekme adlari: add() ve tab() AYNI degeri kullanmak zorunda. Cevrilmis metin
# dogrudan bir tanimlayici gibi kullanildigi icin tek yerden uretiliyor.
TAB_PIPELINE = t("app.tab.pipeline")
TAB_HISTORY = t("app.tab.history")
TAB_SETTINGS = t("app.tab.settings")

# Pipeline olaylarinin onem derecesi -> konsol stili. Eskiden mesajin METNINDE
# "uyari"/"hata" araniyordu; arayuz cevrilir cevrilmez o eslesme sessizce
# bozulurdu. Severity artik olayin kendisinde geliyor (bkz. config.PROGRESS_*).
_LEVEL_STYLES = {
    config.PROGRESS_INFO: "info",
    config.PROGRESS_SUCCESS: "success",
    config.PROGRESS_WARNING: "warning",
    config.PROGRESS_ERROR: "error",
}


class AppWindow(ctk.CTk):
    """AI Synthetic Data Studio ana penceresi."""

    def __init__(self):
        super().__init__()
        self.settings = config.load_settings()
        ctk.set_appearance_mode(self.settings.get("appearance", "dark"))
        ctk.set_default_color_theme("blue")

        self.title("AI Synthetic Data Studio")
        self.geometry("1280x820")
        self.minsize(1080, 700)

        self.state_manager = get_state_manager()
        self.ui_queue: "queue.Queue" = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: Optional[PipelineWorker] = None
        self._polling = False
        self._last_result: Optional[PipelineResult] = None

        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Bolum 6.2: onceki calisedan kalan job'lari isaretle ve devam sor.
        interrupted = self.state_manager.mark_stale_jobs_interrupted()
        if interrupted:
            log.info("%d yarım kalmış job 'interrupted' olarak işaretlendi", interrupted)
        post_to_ui(self, self._offer_resume, delay_ms=400)

    # ------------------------------------------------------------------ #
    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, height=54, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text="  AI Synthetic Data Studio",
                     font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=12)
        status_frame, self.header_dot, self.header_status = status_dot(
            header, t("progress.status.ready"))
        status_frame.grid(row=0, column=1, sticky="e", padx=16)

        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=10, pady=(6, 10))
        self.tabview.add(TAB_PIPELINE)
        self.tabview.add(TAB_HISTORY)
        self.tabview.add(TAB_SETTINGS)
        left_align_tabs(self.tabview)

        self.pipeline_view = PipelineView(
            self.tabview.tab(TAB_PIPELINE),
            on_start=self.start_pipeline,
            on_cancel=self.on_cancel_click,
            settings=self.settings,
        )
        self.pipeline_view.pack(fill="both", expand=True)

        self.history_view = HistoryView(self.tabview.tab(TAB_HISTORY), self.state_manager)
        self.history_view.pack(fill="both", expand=True)

        self.settings_view = SettingsView(self.tabview.tab(TAB_SETTINGS),
                                          on_settings_changed=self._on_settings_changed)
        self.settings_view.pack(fill="both", expand=True)
        self.settings_view.update_cost(self.state_manager.get_cost_summary())

        self.console = self.pipeline_view.console
        self.console.write(t("app.console.ready"), "success")
        self.console.write(t("app.console.data_dir", path=config.APP_DATA_DIR), "muted")
        backup = getattr(self.state_manager, "recovered_backup_path", None)
        if backup:
            self.console.write(t("app.console.db_recovered", path=backup), "error")

    def _set_header(self, text: str, color: str = COLOR_MUTED) -> None:
        """Sağ üst durum göstergesini (nokta + metin) günceller."""
        self.header_dot.configure(text_color=color)
        self.header_status.configure(text=text)

    def _on_settings_changed(self) -> None:
        self.pipeline_view.model_selector.refresh_models()

    # ------------------------------------------------------------------ #
    # Resume (Bolum 6.2)
    # ------------------------------------------------------------------ #
    def _offer_resume(self) -> None:
        job = self.state_manager.get_resumable_job()
        if not job:
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title(t("app.resume.title"))
        dialog.geometry("480x220")
        dialog.transient(self)
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)

        step = job["current_step"] or 0
        rows = job["generated_rows_count"] or 0
        message = t("app.resume.message",
                    job_id=job["job_id"],
                    domain=job["domain"] or job["prompt"][:40],
                    step=step, step_name=job["step_name"] or "-",
                    rows=format(rows, ","))
        ctk.CTkLabel(dialog, text=message, justify="left", wraplength=430).grid(
            row=0, column=0, sticky="nsew", padx=20, pady=(20, 10))

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 20))
        buttons.grid_columnconfigure((0, 1), weight=1)

        def resume() -> None:
            dialog.destroy()
            self._prefill_from_job(job)

        def dismiss() -> None:
            dialog.destroy()
            self.console.write(t("app.resume.declined", job_id=job["job_id"]), "muted")

        ctk.CTkButton(buttons, text=t("app.resume.accept"), command=resume).grid(
            row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkButton(buttons, text=t("app.resume.decline"), command=dismiss, fg_color="#555555",
                      hover_color="#666666").grid(row=0, column=1, sticky="ew", padx=(5, 0))

    def _prefill_from_job(self, job: Dict[str, Any]) -> None:
        """Yarım kalan işin girdilerini forma doldurur."""
        view = self.pipeline_view
        view.prompt_box.delete("1.0", "end")
        view.prompt_box.insert("1.0", job["prompt"] or "")
        view.seed_entry.delete(0, "end")
        view.seed_entry.insert(0, str(job["random_seed"]))
        schema = self.state_manager.get_schema(job["job_id"])
        if schema:
            view.rows_box.set(str(schema.get("row_count_target", config.DEFAULT_ROW_TARGET)))
        self.console.write(t("app.resume.loaded", job_id=job["job_id"]), "step")
        self.tabview.set(TAB_PIPELINE)

    # ------------------------------------------------------------------ #
    # Pipeline baslatma / iptal (Bolum 6.6)
    # ------------------------------------------------------------------ #
    def start_pipeline(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.console.write(t("app.error.already_running"), "warning")
            return

        try:
            inputs = self.pipeline_view.collect_inputs()
        except ValueError as exc:
            self.console.write(str(exc), "error")
            self.pipeline_view.progress_panel.set_error(str(exc))
            return

        config.save_settings({
            "provider": inputs["provider"],
            "model": inputs["model"],
            "faker_locale": inputs["faker_locale"],
            "row_count_target": inputs["row_count"],
            "random_seed": inputs["random_seed"],
            "use_hf_seed": inputs["use_hf_seed"],
            "hf_seed_query": inputs["hf_seed_query"],
            "use_web_seed": inputs.get("use_web_seed", False),
            "web_seed_query": inputs.get("web_seed_query", ""),
            "export_formats": inputs["export_formats"],
            "engine": inputs.get("engine", "llm"),
            "time_series": inputs.get("time_series", False),
            "expand_features": inputs.get("expand_features", False),
            "dirty_rate": inputs.get("dirty_rate", 0.0),
            "agentic": inputs.get("agentic", False),
        })

        cfg = PipelineConfig(**inputs)
        self.cancel_event = threading.Event()
        self.ui_queue = queue.Queue()
        self._last_result = None

        self.console.write_separator(t("app.run.separator"))
        self.console.write(t("app.run.domain", domain=cfg.domain_prompt), "step")
        self.console.write(
            t("app.run.parameters", provider=cfg.provider, model=cfg.resolved_model(),
              rows=format(cfg.row_count, ","), seed=cfg.random_seed), "muted")
        self.pipeline_view.progress_panel.reset()
        self.pipeline_view.progress_panel.set_running(True)
        self.pipeline_view.chart_panel.clear()
        self.pipeline_view.tabs.set("Konsol")
        self._set_header(t("app.status.running"), COLOR_INFO)

        task_fn = partial(self._pipeline_task, cfg)
        self.worker = PipelineWorker(task_fn, self.ui_queue, self.cancel_event)
        self.worker.start()

        if not self._polling:
            self._polling = True
            self.after(POLL_INTERVAL_MS, self.poll_queue)

    def _pipeline_task(self, cfg: PipelineConfig, cancel_event: threading.Event):
        """Worker thread'de çalışır - StateManager disinda hiçbir paylaşımlı
        duruma dokunmaz, widget'a hiç dokunmaz."""
        return run_pipeline(cfg, cancel_event, self.state_manager,
                            llm_progress_cb=self._on_llm_progress)

    def _on_llm_progress(self, message: str) -> None:
        """LLM çağrısının İÇİNDEN, worker thread'de çağrılır.

        Widget'a dokunmak yasak; tek yaptığı kuyruğa yazmak. Ekrana basma işini
        ana thread'deki poll_queue yapar.
        """
        self.ui_queue.put(("llm_progress", message))

    def on_cancel_click(self) -> None:
        if self.worker is None or not self.worker.is_alive():
            return
        self.cancel_event.set()
        self.console.write(t("app.cancel.requested"), "warning")
        self.pipeline_view.progress_panel.status_label.configure(
            text=t("app.cancel.in_progress"))

    # ------------------------------------------------------------------ #
    # Queue polling - TUM widget guncellemeleri burada, ana thread'de
    # ------------------------------------------------------------------ #
    def poll_queue(self) -> None:
        try:
            while True:
                event, data = self.ui_queue.get_nowait()
                self.handle_event(event, data)
        except queue.Empty:
            pass

        if self.worker is not None and self.worker.is_alive():
            self.after(POLL_INTERVAL_MS, self.poll_queue)
        else:
            # Worker bitti; kuyruğu bir kez daha bosaltip polling'i durdur.
            try:
                while True:
                    event, data = self.ui_queue.get_nowait()
                    self.handle_event(event, data)
            except queue.Empty:
                pass
            self._polling = False

    def handle_event(self, event: str, data: Any) -> None:
        if event == "progress":
            self._handle_progress(data)
        elif event == "done":
            self._handle_done(data)
        elif event == "error":
            self._handle_error(data)
        elif event == "cancelled":
            self._handle_cancelled()
        elif event == "llm_progress":
            # Uzun suren bir LLM cagrisinin icinden gelen ara durum: yuzdeye
            # dokunmaz, yalnizca konsola dusulur.
            self.console.write(str(data), "muted")
        elif event == "checkpoint_saved":
            # GUI kendi DB sorgusunu atmaz, checkpoint'i event'ten ogrenir (Bolum 10.2)
            self.console.write(t("app.console.checkpoint", step=data.get("step")), "muted")

    def _handle_progress(self, data: Dict[str, Any]) -> None:
        message = data["message"]
        self.pipeline_view.progress_panel.update_progress(
            data["step"], data["percent"], message)

        # Onem derecesi olaydan gelir. Girinti/madde imi ise BICIMDIR, dile bagli
        # degil: alt satirlari ayirt etmek icin ona bakmak guvenli.
        severity = data.get("level", config.PROGRESS_INFO)
        level = _LEVEL_STYLES.get(severity, "info")
        if severity == config.PROGRESS_INFO:
            if message.startswith("  ->") or message.startswith("    ->"):
                level = "detail"
            elif message.startswith("  •") or message.startswith("•"):
                level = "substep"
            elif data["detail"].get("schema"):
                level = "step"

        # Alt detay veya girintili adımları daha temiz ve belirgin göster
        if message.startswith("  ") or message.startswith("•"):
            self.console.write("       " + message.strip(), level, timestamp=False)
        else:
            self.console.write("[%d/7] %s" % (data["step"], message), level)
        self._set_header("%.0f%% - %s" % (data["percent"], data["name"]), COLOR_INFO)

    def _handle_done(self, result: Optional[PipelineResult]) -> None:
        self._last_result = result
        if result is None:
            self._handle_error(t("app.error.no_result"))
            return
        self.pipeline_view.progress_panel.set_finished(
            t("app.done.summary", rows=format(len(result.dataframe), ",")))
        self.console.write_separator(t("app.done.separator"))
        self.console.write(
            t("app.done.rows", job_id=result.job_id,
              rows_in=format(result.report["rows_in"], ","),
              rows_out=format(result.report["rows_out"], ","),
              retention="%.1f" % result.report["retention_pct"]),
            "success")
        tot_tokens = result.cost.get("prompt_tokens", 0) + result.cost.get("completion_tokens", 0)
        self.console.write(
            t("app.done.cost", cost="%.4f" % result.cost.get("cost_usd", 0.0),
              calls=result.cost.get("calls", 0), tokens=format(tot_tokens, ",")),
            "detail")
        for kind, path in sorted(result.output_paths.items()):
            try:
                sz = Path(path).stat().st_size
                sz_str = ("%.1f KB" % (sz / 1024)) if sz < 1024 * 1024 else ("%.2f MB" % (sz / (1024 * 1024)))
                self.console.write("  %-8s %s (%s)" % (kind, path, sz_str), "muted")
            except Exception:
                self.console.write("  %-8s %s" % (kind, path), "muted")
        if result.hub_url:
            self.console.write("HuggingFace: %s" % result.hub_url, "substep")
        self._set_header(t("progress.status.finished"), COLOR_OK)

        self.pipeline_view.show_result(result)
        self.history_view.refresh()
        self.settings_view.update_cost(self.state_manager.get_cost_summary())

    def _handle_error(self, message: str) -> None:
        self.pipeline_view.progress_panel.set_error(
            t("app.error.prefix", message=str(message)[:80]))
        self.console.write_separator(t("app.error.separator"))
        self.console.write(str(message), "error")
        self._set_header(t("app.error.header"), COLOR_ERROR)
        self.history_view.refresh()

    def _handle_cancelled(self) -> None:
        self.pipeline_view.progress_panel.set_error(t("app.cancelled.status"))
        self.console.write(t("app.cancelled.console"), "warning")
        self._set_header(t("app.cancelled.status"), COLOR_WARN)
        self.history_view.refresh()

    # ------------------------------------------------------------------ #
    def _on_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.cancel_event.set()
            self.worker.join(timeout=3.0)
        try:
            self.state_manager.close()
        except Exception:
            pass
        self.destroy()


def launch() -> None:
    """Uygulamayı başlatır (main.py buradan çağırır)."""
    config.setup_logging()
    app = AppWindow()
    app.mainloop()
