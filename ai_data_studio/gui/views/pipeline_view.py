"""Pipeline çalıştırma ekranı - girdi formu, ilerleme paneli, konsol ve grafikler.

Bu görünüm form bileşenlerini kurar ve kullanıcı parametrelerini toplar;
pipeline iş parçacığını yönetme ve kuyruk dinleme sorumluluğu app_window üzerindedir.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Callable, Dict, List

import customtkinter as ctk

from ... import config
from ...core.orchestrator import ENGINE_AUTO, ENGINE_LLM, ENGINE_PARAMETRIC
from ...i18n import t
from ..components.chart_panel import ChartPanel
from ..components.console_log import ConsoleLog
from ..components.model_selector import ModelSelector
from ..components.progress_panel import ProgressPanel
from ..ui_utils import COLOR_MUTED, left_align_tabs

FAKER_LOCALES = [
    "tr_TR", "en_US", "en_GB", "de_DE", "fr_FR", "es_ES", "it_IT",
    "nl_NL", "pt_BR", "ru_RU", "ja_JP", "zh_CN", "ar_SA",
]
ROW_PRESETS = ["1000", "10000", "50000", "100000", "250000", "500000"]

# Giris kipleri. Metinler kullaniciya gorunur; karsilastirmalar bu sabitler uzerinden
# yapilir, serbest metinle degil.
MODE_DOMAIN = t("pipeline.mode.domain")
MODE_PROJECT = t("pipeline.mode.project")

_EXAMPLE = {
    MODE_DOMAIN: t("pipeline.example.domain"),
    MODE_PROJECT: t("pipeline.example.project"),
}

# Satir sayisi kip'e gore farkli seyi ifade eder: veri tarifinde tek tablonun
# satir sayisi, proje tarifinde KOK tablonunki - cocuk tablolarin buyuklugu
# kardinaliteden cikar.
_ROWS_LABEL = {
    MODE_DOMAIN: t("pipeline.rows.label"),
    MODE_PROJECT: t("pipeline.rows.label_root"),
}

_HINT = {
    MODE_DOMAIN: t("pipeline.hint.domain"),
    MODE_PROJECT: t("pipeline.hint.project"),
}


# Ic sekme adlari: add() ve tab() AYNI degeri kullanmak zorunda.
TAB_CONSOLE = t("pipeline.tab.console")
TAB_RESULT = t("pipeline.tab.result")
TAB_CHARTS = t("pipeline.tab.charts")


# Uretim motorlari. Etiket kullaniciya gorunur, deger PipelineConfig.engine'e gider;
# karsilastirmalar her zaman DEGER uzerinden yapilir, etiket metniyle degil.
ENGINE_LABELS = {
    t("pipeline.engine.llm"): ENGINE_LLM,
    t("pipeline.engine.parametric"): ENGINE_PARAMETRIC,
    t("pipeline.engine.auto"): ENGINE_AUTO,
}

ENGINE_HINTS = {
    ENGINE_LLM: t("pipeline.engine.llm_hint"),
    ENGINE_PARAMETRIC: t("pipeline.engine.parametric_hint"),
    ENGINE_AUTO: t("pipeline.engine.auto_hint"),
}


def _engine_label(value: str) -> str:
    """Motor değerinden kullanıcıya görünen etikete döner (bilinmeyen -> LLM)."""
    for label, engine in ENGINE_LABELS.items():
        if engine == value:
            return label
    return next(iter(ENGINE_LABELS))


def _field(key: str, value) -> str:
    """Sonuç sekmesi için hizalı `etiket : değer` satırı.

    Etiket genişliği sabit tutuluyor; çeviri uzunlukları dilden dile değiştiği
    için hizalamayı metne değil biçimlendiriciye bırakıyoruz.
    """
    return "  %-36s: %s" % (t(key), value)

def engine_lines(report: Dict[str, Any]) -> List[str]:
    """Hangi motorların koştuğunu Sonuç sekmesi için metin bloğuna çevirir.

    CLI bunu konsola basıyor; arayüzün sessiz kalması "bu veriyi ne üretti"
    sorusunu cevapsız bırakır - özellikle kirlilik enjekte edilmişse.
    """
    engines = (report or {}).get("engines") or {}
    if not engines:
        return []

    lines = ["", t("result.section.engines"), "-" * 62,
             _field("result.engines.generation", engines.get("generation", "-"))]

    ts = engines.get("time_series")
    if ts:
        lines.append(_field("result.engines.time_series",
                            t("result.engines.time_series_value",
                              entities=format(ts.get("unique_entities", 0), ","),
                              bursts=ts.get("burst_anomalies_count", 0))))
        lines.append(_field("result.engines.time_range", ts.get("time_range", "-")))

    fe = engines.get("feature_expander")
    if fe:
        lines.append(_field("result.engines.feature_expander",
                            t("result.engines.feature_value",
                              added=fe.get("added_columns_count", 0),
                              total=fe.get("total_columns", 0))))
        added = fe.get("added_columns") or []
        if added:
            lines.append(_field("result.engines.added_columns", ", ".join(added)))

    dirty = engines.get("dirty_data")
    if dirty:
        breakdown = dirty.get("corruption_breakdown", {})
        lines.append(_field("result.engines.dirty",
                            t("result.engines.dirty_value",
                              rows=format(dirty.get("corrupted_rows", 0), ","),
                              rate="%.1f" % (dirty.get("corrupted_rate", 0.0) * 100))))
        lines.append(_field("result.engines.dirty_breakdown",
                            t("result.engines.dirty_breakdown_value",
                              missing=breakdown.get("missing", 0),
                              typo=breakdown.get("typo", 0),
                              spike=breakdown.get("outlier_spike", 0),
                              casing=breakdown.get("casing", 0))))
        lines.append(_field("result.engines.note", t("result.engines.stats_note")))
    return lines


def relational_lines(report: Dict[str, Any]) -> List[str]:
    """İlişkisel bütünlük sonucunu Sonuç sekmesi için metin bloğuna çevirir.

    CLI bunları konsola basıyor; arayüzün sessiz kalması kullanıcıyı yetim
    yabancı anahtarlara ve kardinalite sapmalarına kör bırakır.
    """
    rel = (report or {}).get("relational") or {}
    if not rel:
        return []

    lines = ["", t("result.section.relational"), "-" * 62,
             _field("result.relational.verdict",
                    t("history.verdict.pass") if rel.get("pass")
                    else t("result.relational.failed"))]
    if not rel.get("repair_enabled", True):
        lines.append(_field("result.relational.repair", t("result.relational.repair_off")))

    row_counts = rel.get("row_counts") or {}
    if row_counts:
        lines.append("  " + t("result.relational.row_counts"))
        for name in sorted(row_counts):
            lines.append("    %-24s %s" % (name, format(row_counts[name], ",")))

    removed = (rel.get("repair") or {}).get("removed_total")
    if removed:
        lines.append(_field("result.relational.orphans_removed",
                            t("result.rows_value", rows=format(removed, ","))))

    for fk in rel.get("foreign_keys") or []:
        lines.append("  " + t("result.relational.fk",
                              relationship=fk.get("relationship", "?"),
                              orphans=format(fk.get("orphan_rows", 0), ","),
                              pct="%.2f" % fk.get("orphan_pct", 0.0),
                              verdict="" if fk.get("pass")
                              else "<- " + t("result.relational.violation")))

    for card in rel.get("cardinality") or []:
        lines.append("  " + t("result.relational.cardinality",
                              relationship=card.get("relationship", "?"),
                              observed="%.2f" % card.get("observed_mean", 0.0),
                              expected="%.2f" % card.get("expected_mean", 0.0),
                              verdict="" if card.get("pass")
                              else "<- " + t("result.relational.deviation")))
        for violation in card.get("violations") or []:
            lines.append("      * %s" % violation)

    for pk in rel.get("primary_keys") or []:
        if not pk.get("pass"):
            lines.append("  " + t("result.relational.pk_not_unique",
                                  table=pk.get("table"), pk=pk.get("primary_key")))
    return lines


def plan_lines(plan) -> List[str]:
    """Proje planini Sonuç sekmesi için metin bloğuna çevirir.

    CLI aynı kararları basıyor; arayüzün sessiz kalması kullanıcıyı hedef değişkene,
    sınıf dengesine ve ayıklanan sızıntı kolonlarına kör bırakıyordu.
    """
    lines = ["", t("result.section.plan"), "-" * 62,
             _field("result.plan.task_type", plan.task_type),
             _field("result.plan.table_count", len(plan.contract.tables))]
    if plan.target is not None:
        lines.append(_field("result.plan.target", plan.target.label()))
    if plan.positive_class_ratio is not None:
        lines.append(_field("result.plan.class_balance",
                            t("result.plan.positive_pct",
                              pct="%.1f" % (plan.positive_class_ratio * 100))))
    if plan.split is not None:
        detail = plan.split.kind
        if plan.split.column:
            detail += " (%s.%s)" % (plan.split.table, plan.split.column)
        lines.append(_field("result.plan.split", detail))
        if plan.split.reason:
            lines.append("      " + t("result.plan.reason", reason=plan.split.reason))
    if plan.rationale:
        lines.append(_field("result.plan.rationale", plan.rationale))

    if plan.excluded_leakage:
        lines.append("  " + t("result.plan.leakage_header",
                              count=len(plan.excluded_leakage)))
        for excl in plan.excluded_leakage:
            lines.append("    - %s : %s" % (excl.column, excl.reason))
    else:
        # Bos liste bir karardir, sessizlik degil: plan "sizinti yok" demis.
        lines.append(_field("result.plan.leakage", t("result.plan.leakage_none")))

    for warning in plan.warnings:
        lines.append("  " + t("result.warning", message=warning))
    return lines


class PipelineView(ctk.CTkFrame):
    def __init__(self, master, on_start: Callable[[], None], on_cancel: Callable[[], None],
                 settings: Dict[str, Any], **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.settings = settings
        self._result_paths: Dict[str, str] = {}

        self.grid_columnconfigure(0, weight=3, uniform="cols")
        self.grid_columnconfigure(1, weight=4, uniform="cols")
        self.grid_rowconfigure(0, weight=1)

        # ================= SOL: girdi + ilerleme ========================= #
        # label_text kullanilmiyor: bos bir baslik bari dikey alanin
        # yaklasik 40 pikselini yiyor ve hicbir bilgi tasimiyordu.
        # Sol sutun iki parcali: ustte kaydirilabilir form, altta SABIT eylem
        # cubugu. Onceden ProgressPanel de kaydirma alanindaydi ve varsayilan
        # pencere boyutunda "Pipeline'i Baslat" ekranin altinda kaliyordu.
        left_col = ctk.CTkFrame(self, fg_color="transparent")
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left_col.grid_columnconfigure(0, weight=1)
        left_col.grid_rowconfigure(0, weight=1)

        left = ctk.CTkScrollableFrame(left_col, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_columnconfigure(0, weight=1)
        row = 0

        ctk.CTkLabel(left, text=t("pipeline.form.title"),
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=row, column=0, sticky="w", padx=10, pady=(2, 4))
        row += 1

        # Iki giris kipi: veriyi tarif etmek ya da PROJEYI anlatmak. Ikincisinde
        # hedef degisken, sinif dengesi, sizinti ayiklamasi ve train/test ayrimina
        # planlayici karar verir (bkz. core/project_planner).
        self.mode_selector = ctk.CTkSegmentedButton(
            left, values=[MODE_DOMAIN, MODE_PROJECT], command=self._on_mode_change)
        self.mode_selector.set(MODE_DOMAIN)
        self.mode_selector.grid(row=row, column=0, sticky="ew", padx=10, pady=(0, 6))
        row += 1

        self.prompt_box = ctk.CTkTextbox(left, height=88, wrap="word")
        self.prompt_box.grid(row=row, column=0, sticky="ew", padx=10, pady=(0, 4))
        self.prompt_box.insert("1.0", _EXAMPLE[MODE_DOMAIN])
        row += 1
        self.prompt_hint = ctk.CTkLabel(
            left, text=_HINT[MODE_DOMAIN],
            font=ctk.CTkFont(size=11), text_color=COLOR_MUTED,
            wraplength=430, justify="left")
        self.prompt_hint.grid(row=row, column=0, sticky="w", padx=10, pady=(0, 6))
        row += 1

        # --- model secici ------------------------------------------------ #
        self.model_selector = ModelSelector(
            left, provider=settings.get("provider", config.PROVIDER_ANTHROPIC),
            model=settings.get("model"),
        )
        self.model_selector.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 8))
        row += 1

        # --- parametreler ------------------------------------------------ #
        params = ctk.CTkFrame(left)
        params.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 8))
        params.grid_columnconfigure(1, weight=1)
        row += 1

        self.rows_label = ctk.CTkLabel(params, text=_ROWS_LABEL[MODE_DOMAIN])
        self.rows_label.grid(row=0, column=0, sticky="w", padx=(10, 8), pady=6)
        self.rows_box = ctk.CTkComboBox(params, values=ROW_PRESETS)
        self.rows_box.set(str(settings.get("row_count_target", config.DEFAULT_ROW_TARGET)))
        self.rows_box.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=6)

        ctk.CTkLabel(params, text=t("pipeline.form.seed")).grid(row=1, column=0, sticky="w",
                                                      padx=(10, 8), pady=6)
        self.seed_entry = ctk.CTkEntry(params)
        self.seed_entry.insert(0, str(settings.get("random_seed", config.DEFAULT_RANDOM_SEED)))
        self.seed_entry.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=6)

        ctk.CTkLabel(params, text=t("pipeline.form.locale")).grid(row=2, column=0, sticky="w",
                                                       padx=(10, 8), pady=6)
        self.locale_menu = ctk.CTkOptionMenu(params, values=FAKER_LOCALES)
        self.locale_menu.set(settings.get("faker_locale", "tr_TR"))
        self.locale_menu.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=6)

        ctk.CTkLabel(params, text=t("pipeline.form.formats")).grid(row=3, column=0, sticky="w",
                                                           padx=(10, 8), pady=6)
        formats_frame = ctk.CTkFrame(params, fg_color="transparent")
        formats_frame.grid(row=3, column=1, sticky="ew", padx=(0, 10), pady=6)
        selected_formats = settings.get("export_formats", ["csv", "parquet"])
        self.format_vars: Dict[str, ctk.BooleanVar] = {}
        for i, fmt in enumerate(("csv", "parquet", "json")):
            var = ctk.BooleanVar(value=fmt in selected_formats)
            ctk.CTkCheckBox(formats_frame, text=fmt, variable=var, width=60).grid(
                row=0, column=i, padx=(0, 8))
            self.format_vars[fmt] = var

        # --- Referans (Seed) Veri ---------------------------------------- #
        seed_frame = ctk.CTkFrame(left)
        seed_frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 8))
        seed_frame.grid_columnconfigure(0, weight=1)
        row += 1

        self.hf_seed_var = ctk.BooleanVar(value=settings.get("use_hf_seed", False))
        ctk.CTkCheckBox(seed_frame, text=t("pipeline.seed.hf"),
                        variable=self.hf_seed_var, command=self._toggle_seeds).grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 4))
        self.hf_query_entry = ctk.CTkEntry(
            seed_frame, placeholder_text=t("pipeline.seed.hf_placeholder"))
        self.hf_query_entry.insert(0, settings.get("hf_seed_query", ""))
        self.hf_query_entry.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))

        self.web_seed_var = ctk.BooleanVar(value=settings.get("use_web_seed", False))
        ctk.CTkCheckBox(seed_frame, text=t("pipeline.seed.web"),
                        variable=self.web_seed_var, command=self._toggle_seeds).grid(
            row=2, column=0, sticky="w", padx=10, pady=(4, 4))
        self.web_query_entry = ctk.CTkEntry(
            seed_frame, placeholder_text=t("pipeline.seed.web_placeholder"))
        self.web_query_entry.insert(0, settings.get("web_seed_query", ""))
        self.web_query_entry.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        self._toggle_seeds()

        # --- Motorlar ----------------------------------------------------- #
        # CLI'daki --engine / --time-series / --expand-features / --dirty-rate
        # bayraklarinin arayuz karsiligi. Etiketler ne yaptigini soyler; motor
        # adlari parantez icinde kalir ki CLI ile eslestirmek kolay olsun.
        engines_frame = ctk.CTkFrame(left)
        engines_frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 8))
        engines_frame.grid_columnconfigure(1, weight=1)
        row += 1

        ctk.CTkLabel(engines_frame, text=t("pipeline.engine.label")).grid(
            row=0, column=0, sticky="w", padx=(10, 8), pady=(10, 6))
        self.engine_menu = ctk.CTkOptionMenu(
            engines_frame, values=list(ENGINE_LABELS), command=self._on_engine_change)
        self.engine_menu.set(_engine_label(settings.get("engine", ENGINE_LLM)))
        self.engine_menu.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(10, 6))

        self.engine_hint = ctk.CTkLabel(
            engines_frame, text=ENGINE_HINTS[self.engine], font=ctk.CTkFont(size=11),
            text_color=COLOR_MUTED, wraplength=430, justify="left")
        self.engine_hint.grid(row=1, column=0, columnspan=2, sticky="w",
                              padx=10, pady=(0, 6))

        self.time_series_var = ctk.BooleanVar(value=settings.get("time_series", False))
        ctk.CTkCheckBox(engines_frame,
                        text=t("pipeline.engine.time_series"),
                        variable=self.time_series_var).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4))

        self.expand_features_var = ctk.BooleanVar(value=settings.get("expand_features", False))
        ctk.CTkCheckBox(engines_frame,
                        text=t("pipeline.engine.expand_features"),
                        variable=self.expand_features_var).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4))

        self.dirty_var = ctk.BooleanVar(value=float(settings.get("dirty_rate", 0.0)) > 0)
        ctk.CTkCheckBox(engines_frame, text=t("pipeline.engine.dirty"),
                        variable=self.dirty_var, command=self._toggle_dirty).grid(
            row=4, column=0, sticky="w", padx=10, pady=(0, 4))
        self.dirty_entry = ctk.CTkEntry(engines_frame, width=70)
        self.dirty_entry.insert(0, "%g" % (float(settings.get("dirty_rate", 0.0) or 0.05) * 100))
        self.dirty_entry.grid(row=4, column=1, sticky="w", padx=(0, 10), pady=(0, 4))
        self._toggle_dirty()

        self.agentic_var = ctk.BooleanVar(value=settings.get("agentic", False))
        ctk.CTkCheckBox(engines_frame, text="🤖 Çoklu Ajan Konseyi (Multi-Agent)",
                        variable=self.agentic_var).grid(
            row=5, column=0, columnspan=2, sticky="w", padx=10, pady=(4, 10))

        # --- Ilişkisel (çok tablolu) mod ---------------------------------- #
        # CLI'daki --relational / --max-tables / --no-repair-orphans karsiligi.
        relational_frame = ctk.CTkFrame(left)
        relational_frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(0, 8))
        relational_frame.grid_columnconfigure(1, weight=1)
        row += 1

        self.relational_var = ctk.BooleanVar(value=False)
        self.relational_check = ctk.CTkCheckBox(
            relational_frame, text=t("pipeline.relational.enable"),
            variable=self.relational_var, command=self._toggle_relational)
        self.relational_check.grid(row=0, column=0, columnspan=2, sticky="w",
                                   padx=10, pady=(10, 4))

        self.max_tables_label = ctk.CTkLabel(relational_frame,
                                             text=t("pipeline.relational.max_tables"))
        self.max_tables_label.grid(row=1, column=0, sticky="w", padx=(10, 8), pady=4)
        self.max_tables_entry = ctk.CTkEntry(relational_frame, width=70)
        self.max_tables_entry.insert(0, "6")
        self.max_tables_entry.grid(row=1, column=1, sticky="w", padx=(0, 10), pady=4)

        self.repair_orphans_var = ctk.BooleanVar(value=True)
        self.repair_orphans_check = ctk.CTkCheckBox(
            relational_frame, text=t("pipeline.relational.repair"),
            variable=self.repair_orphans_var)
        self.repair_orphans_check.grid(row=2, column=0, columnspan=2, sticky="w",
                                       padx=10, pady=(4, 10))

        self.relational_hint = ctk.CTkLabel(
            relational_frame, text="", font=ctk.CTkFont(size=11),
            text_color=COLOR_MUTED, wraplength=430, justify="left")
        self.relational_hint.grid(row=3, column=0, columnspan=2, sticky="w",
                                  padx=10, pady=(0, 8))
        self.relational_hint.grid_remove()
        self._toggle_relational()

        # --- ilerleme (kaydirma alaninin DISINDA, hep gorunur) ------------- #
        self.progress_panel = ProgressPanel(left_col, on_start=on_start,
                                            on_cancel=on_cancel)
        self.progress_panel.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        # ================= SAG: konsol + sonuc =========================== #
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(right)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        self.tabs.add(TAB_CONSOLE)
        self.tabs.add(TAB_RESULT)
        self.tabs.add(TAB_CHARTS)
        left_align_tabs(self.tabs)

        self.console = ConsoleLog(self.tabs.tab(TAB_CONSOLE))
        self.console.pack(fill="both", expand=True)

        result_tab = self.tabs.tab(TAB_RESULT)
        result_tab.grid_columnconfigure(0, weight=1)
        result_tab.grid_rowconfigure(0, weight=1)
        self.result_box = ctk.CTkTextbox(result_tab, wrap="word",
                                         font=ctk.CTkFont(family="Consolas", size=12))
        self.result_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.result_box.insert("1.0", t("pipeline.result.empty"))
        self.result_box.configure(state="disabled")

        actions = ctk.CTkFrame(result_tab, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.open_folder_button = ctk.CTkButton(
            actions, text=t("pipeline.result.open_folder"),
            command=self._open_output_folder, state="disabled")
        self.open_folder_button.pack(side="left")

        self.chart_panel = ChartPanel(self.tabs.tab(TAB_CHARTS))
        self.chart_panel.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ #
    def _toggle_seeds(self) -> None:
        self.hf_query_entry.configure(state="normal" if self.hf_seed_var.get() else "disabled")
        self.web_query_entry.configure(state="normal" if self.web_seed_var.get() else "disabled")

    def _toggle_hf(self) -> None:
        self._toggle_seeds()

    def _toggle_dirty(self) -> None:
        self.dirty_entry.configure(state="normal" if self.dirty_var.get() else "disabled")

    def _toggle_relational(self) -> None:
        """İlişkisel kutusunun bağlı alanlarını ve proje kipi çakışmasını yönetir.

        Proje kipinde tablo sayısına PLANLAYICI karar veriyor; iki anahtarın aynı
        anda açık olması kullanıcının birbiriyle çelişen iki şey söylemesi demek
        olurdu, o yüzden proje kipinde kutu devre dışı bırakılır.
        """
        project_mode = self.mode_selector.get() == MODE_PROJECT
        if project_mode:
            self.relational_var.set(False)
            self.relational_check.configure(state="disabled")
            self.relational_hint.configure(
                text=t("pipeline.relational.project_mode_note"))
            self.relational_hint.grid()
        else:
            self.relational_check.configure(state="normal")
            self.relational_hint.grid_remove()

        enabled = self.relational_var.get() and not project_mode
        state = "normal" if enabled else "disabled"
        self.max_tables_entry.configure(state=state)
        self.repair_orphans_check.configure(state=state)

    def _on_engine_change(self, _label: str) -> None:
        self.engine_hint.configure(text=ENGINE_HINTS.get(self.engine, ""))

    @property
    def engine(self) -> str:
        """Seçili üretim motorunun PipelineConfig değeri."""
        return ENGINE_LABELS.get(self.engine_menu.get(), ENGINE_LLM)

    def _open_output_folder(self) -> None:
        path = self._result_paths.get("csv") or next(iter(self._result_paths.values()), None)
        if not path:
            return
        folder = os.path.dirname(path)
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as exc:
            self.console.write(t("pipeline.error.folder_open", error=exc), "error")

    # ------------------------------------------------------------------ #
    def _on_mode_change(self, mode: str) -> None:
        """Kip degisince ipucu metnini, satir etiketini ve - metin dokunulmamissa -
        ornegi degistirir."""
        self.prompt_hint.configure(text=_HINT.get(mode, ""))
        self._toggle_relational()
        self.rows_label.configure(text=_ROWS_LABEL.get(mode, _ROWS_LABEL[MODE_DOMAIN]))
        current = self.prompt_box.get("1.0", "end-1c").strip()
        if current in ("", _EXAMPLE[MODE_DOMAIN], _EXAMPLE[MODE_PROJECT]):
            self.prompt_box.delete("1.0", "end")
            self.prompt_box.insert("1.0", _EXAMPLE.get(mode, ""))

    @property
    def is_project_mode(self) -> bool:
        return self.mode_selector.get() == MODE_PROJECT

    def collect_inputs(self) -> Dict[str, Any]:
        """Formdaki değerleri PipelineConfig alanlarına çevirir. Hatada ValueError."""
        prompt = self.prompt_box.get("1.0", "end-1c").strip()
        if not prompt:
            raise ValueError(
                t("pipeline.error.empty_project") if self.is_project_mode
                else t("pipeline.error.empty_domain")
            )

        try:
            rows = int(str(self.rows_box.get()).replace(",", "").replace(".", "").strip())
        except ValueError:
            raise ValueError(t("pipeline.error.rows_not_int")) from None
        if rows <= 0:
            raise ValueError(t("pipeline.error.rows_not_positive"))

        try:
            seed = int(self.seed_entry.get().strip())
        except ValueError:
            raise ValueError(t("pipeline.error.seed_not_int")) from None

        formats = [fmt for fmt, var in self.format_vars.items() if var.get()]
        if not formats:
            raise ValueError(t("pipeline.error.no_format"))

        dirty_rate = 0.0
        if self.dirty_var.get():
            try:
                dirty_rate = float(str(self.dirty_entry.get()).replace(",", ".").strip()) / 100.0
            except ValueError:
                raise ValueError(t("pipeline.error.dirty_not_number")) from None
            if not 0 < dirty_rate <= 1:
                raise ValueError(t("pipeline.error.dirty_range"))

        if not self.model_selector.is_ready():
            raise ValueError(self.model_selector.readiness_message())
        model = self.model_selector.model

        relational = bool(self.relational_var.get()) and not self.is_project_mode
        max_tables = 6
        if relational:
            try:
                max_tables = int(str(self.max_tables_entry.get()).strip())
            except ValueError:
                raise ValueError(t("pipeline.error.max_tables_not_int")) from None
            if not 2 <= max_tables <= 12:
                raise ValueError(t("pipeline.error.max_tables_range"))

        return {
            "relational": relational,
            "max_tables": max_tables,
            "repair_orphans": bool(self.repair_orphans_var.get()),
            "engine": self.engine,
            "time_series": bool(self.time_series_var.get()),
            "expand_features": bool(self.expand_features_var.get()),
            "dirty_rate": dirty_rate,
            "agentic": bool(self.agentic_var.get()),
            "domain_prompt": prompt,
            # Proje kipinde ayni metin plana da gecer; orchestrator project_prompt
            # doluysa sema uretimi yerine planlayiciyi calistirir.
            "project_prompt": prompt if self.is_project_mode else "",
            "provider": self.model_selector.provider,
            "model": model,
            "row_count": rows,
            "random_seed": seed,
            "faker_locale": self.locale_menu.get(),
            "export_formats": formats,
            "use_hf_seed": bool(self.hf_seed_var.get()),
            "hf_seed_query": self.hf_query_entry.get().strip(),
            "use_web_seed": bool(self.web_seed_var.get()),
            "web_seed_query": self.web_query_entry.get().strip(),
        }

    def show_result(self, result) -> None:
        """Pipeline sonucunu Sonuç sekmesinde özetler ve grafikleri çizer."""
        self._result_paths = dict(result.output_paths)
        report = result.report
        lines: List[str] = [
            "JOB #%d - %s" % (result.job_id, result.schema.domain),
            "=" * 62,
            "",
            _field("result.rows_raw", format(report["rows_in"], ",")),
            _field("result.rows_validated", format(report["rows_out"], ",")),
            _field("result.retention", "%%%.1f" % report["retention_pct"]),
            _field("result.attempts", result.generation_meta.get("attempts", 1)),
            _field("result.sandbox_seconds",
                   "%.1f" % result.generation_meta.get("duration_s", 0)),
            _field("result.cost", "$%.4f (%s)" % (
                result.cost.get("cost_usd", 0.0),
                t("history.field.calls", calls=result.cost.get("calls", 0)))),
        ]
        # Proje kipinde plan, sonucun kendisi kadar onemli: hangi hedefi ve hangi
        # sizinti ayiklamasini kabul ettigini gormeden kullanici veriye guvenemez.
        if getattr(result, "plan", None) is not None:
            lines += plan_lines(result.plan)

        # Motor bloğu: veriyi neyin ürettiği ve üzerine ne enjekte edildiği.
        lines += engine_lines(report)
        # İlişkisel bütünlük: yetim FK ve kardinalite sapmaları CLI'da basılıyor.
        lines += relational_lines(report)

        lines += ["", t("result.section.stages"), "-" * 62]
        for stage in report.get("stages", []):
            lines.append("  %-24s %8s -> %8s  (-%s)"
                         % (stage["stage"], format(stage["rows_before"], ","),
                            format(stage["rows_after"], ","), format(stage["removed"], ",")))

        rules = [r for r in report.get("business_rules", []) if r.get("status") == "applied"]
        if rules:
            lines += ["", t("result.section.rules"), "-" * 62]
            for rule in rules:
                lines.append("  %-44s %s" % (
                    rule["rule"][:44],
                    t("result.rule_violations",
                      count=format(rule["violations"], ","))))

        corrs = report.get("correlations", [])
        if corrs:
            lines += ["", t("result.section.correlations"), "-" * 62]
            for corr in corrs:
                lines.append("  %-28s r=%-7s beklenen %s>=%s  [%s]"
                             % ("/".join(corr["pair"]), corr.get("actual_r"),
                                corr.get("expected_sign"), corr.get("min_r"),
                                t("history.verdict.pass") if corr.get("pass")
                                else t("history.verdict.fail")))

        pres = report.get("preserved_anomalies") or {}
        if pres.get("total_preserved", 0) > 0:
            lines += ["", t("result.section.preserved"), "-" * 62,
                      _field("result.preserved.column",
                             "%s (%s)" % (pres.get("column"), pres.get("value"))),
                      _field("result.preserved.z_score",
                             t("result.rows_value",
                               rows=format(pres.get("z_score_preserved", 0), ","))),
                      _field("result.preserved.isolation_forest",
                             t("result.rows_value",
                               rows=format(pres.get("isolation_forest_preserved", 0), ","))),
                      _field("result.preserved.total",
                             t("result.rows_value",
                               rows=format(pres.get("total_preserved", 0), ",")))]

        dist = report.get("distributions") or {}
        if not dist.get("skipped"):
            lines += ["", t("result.section.distribution"), "-" * 62,
                      "  " + t("result.distribution.summary",
                              passed=dist.get("passed"), total=dist.get("total"))]
            for name, entry in (dist.get("columns") or {}).items():
                lines.append("  %-24s KS=%-7s p=%-8s [%s]"
                             % (name, entry["ks_stat"], entry["p_value"],
                                t("history.verdict.pass") if entry["pass"]
                                else t("history.verdict.fail")))

        lines += ["", t("result.section.outputs"), "-" * 62]
        for kind, path in sorted(result.output_paths.items()):
            lines.append("  %-8s %s" % (kind, path))
        if result.hub_url:
            lines += ["", "HuggingFace: %s" % result.hub_url]

        self.result_box.configure(state="normal")
        self.result_box.delete("1.0", "end")
        self.result_box.insert("1.0", "\n".join(lines))
        self.result_box.configure(state="disabled")
        self.open_folder_button.configure(state="normal")

        try:
            self.chart_panel.render(result.dataframe, result.schema, report,
                                    contract=getattr(result, "contract", None),
                                    tables=getattr(result, "tables", None))
        except Exception as exc:
            self.console.write(t("result.charts_failed", error=exc), "warning")

        self.tabs.set(TAB_RESULT)
