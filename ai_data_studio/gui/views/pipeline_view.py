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
MODE_DOMAIN = "Veri tarifi"
MODE_PROJECT = "Proje tarifi"

_EXAMPLE = {
    MODE_DOMAIN: ("Mobil oyun reklamlarında kullanıcı etkileşim verisi: "
                  "yaş, gelir, reklam süresi, izleme süresi ve tıklama."),
    MODE_PROJECT: ("Online mağazamdan alışverişi kesecek müşterileri önceden "
                   "tespit etmek istiyorum ki elde tutma ekibi onlara kampanya "
                   "gönderebilsin."),
}

# Satir sayisi kip'e gore farkli seyi ifade eder: veri tarifinde tek tablonun
# satir sayisi, proje tarifinde KOK tablonunki - cocuk tablolarin buyuklugu
# kardinaliteden cikar.
_ROWS_LABEL = {
    MODE_DOMAIN: "Satır sayısı",
    MODE_PROJECT: "Kök tablo satır sayısı",
}

_HINT = {
    MODE_DOMAIN: "Domain'i serbest metinle anlatın; LLM şemayı kendisi çıkaracak.",
    MODE_PROJECT: ("Projenizi anlatın; sistem hangi verinin gerektiğine, hedef "
                   "değişkene, sınıf dengesine, ayıklanacak sızıntı kolonlarına ve "
                   "train/test ayrımına kendisi karar verir."),
}


def plan_lines(plan) -> List[str]:
    """Proje planini Sonuç sekmesi için metin bloğuna çevirir.

    CLI aynı kararları basıyor; arayüzün sessiz kalması kullanıcıyı hedef değişkene,
    sınıf dengesine ve ayıklanan sızıntı kolonlarına kör bırakıyordu.
    """
    lines = ["", "PROJE PLANI", "-" * 62,
             "  Görev tipi             : %s" % plan.task_type,
             "  Tablo sayısı           : %d" % len(plan.contract.tables)]
    if plan.target is not None:
        lines.append("  Hedef değişken         : %s" % plan.target.label())
    if plan.positive_class_ratio is not None:
        lines.append("  Sınıf dengesi          : pozitif %%%.1f"
                     % (plan.positive_class_ratio * 100))
    if plan.split is not None:
        detail = plan.split.kind
        if plan.split.column:
            detail += " (%s.%s)" % (plan.split.table, plan.split.column)
        lines.append("  Train/test ayrımı      : %s" % detail)
        if plan.split.reason:
            lines.append("      gerekçe: %s" % plan.split.reason)
    if plan.rationale:
        lines.append("  Plan gerekçesi         : %s" % plan.rationale)

    if plan.excluded_leakage:
        lines.append("  Ayıklanan sızıntı kolonları (%d adet):" % len(plan.excluded_leakage))
        for excl in plan.excluded_leakage:
            lines.append("    - %s : %s" % (excl.column, excl.reason))
    else:
        # Bos liste bir karardir, sessizlik degil: plan "sizinti yok" demis.
        lines.append("  Ayıklanan sızıntı      : yok")

    for warning in plan.warnings:
        lines.append("  UYARI: %s" % warning)
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

        ctk.CTkLabel(left, text="Ne üretmek istiyorsunuz?",
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

        ctk.CTkLabel(params, text="Random seed").grid(row=1, column=0, sticky="w",
                                                      padx=(10, 8), pady=6)
        self.seed_entry = ctk.CTkEntry(params)
        self.seed_entry.insert(0, str(settings.get("random_seed", config.DEFAULT_RANDOM_SEED)))
        self.seed_entry.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=6)

        ctk.CTkLabel(params, text="Faker locale").grid(row=2, column=0, sticky="w",
                                                       padx=(10, 8), pady=6)
        self.locale_menu = ctk.CTkOptionMenu(params, values=FAKER_LOCALES)
        self.locale_menu.set(settings.get("faker_locale", "tr_TR"))
        self.locale_menu.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=6)

        ctk.CTkLabel(params, text="Çıktı formatları").grid(row=3, column=0, sticky="w",
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
        ctk.CTkCheckBox(seed_frame, text="HuggingFace'ten referans (seed) veri kullan",
                        variable=self.hf_seed_var, command=self._toggle_seeds).grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 4))
        self.hf_query_entry = ctk.CTkEntry(
            seed_frame, placeholder_text="HF arama sorgusu veya dataset ID")
        self.hf_query_entry.insert(0, settings.get("hf_seed_query", ""))
        self.hf_query_entry.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))

        self.web_seed_var = ctk.BooleanVar(value=settings.get("use_web_seed", False))
        ctk.CTkCheckBox(seed_frame, text="Web'den canlı referans veri topla (Arama / URL)",
                        variable=self.web_seed_var, command=self._toggle_seeds).grid(
            row=2, column=0, sticky="w", padx=10, pady=(4, 4))
        self.web_query_entry = ctk.CTkEntry(
            seed_frame, placeholder_text="Arama konusu veya doğrudan https:// URL'i")
        self.web_query_entry.insert(0, settings.get("web_seed_query", ""))
        self.web_query_entry.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        self._toggle_seeds()

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
        self.tabs.add("Konsol")
        self.tabs.add("Sonuç")
        self.tabs.add("Grafikler")
        left_align_tabs(self.tabs)

        self.console = ConsoleLog(self.tabs.tab("Konsol"))
        self.console.pack(fill="both", expand=True)

        result_tab = self.tabs.tab("Sonuç")
        result_tab.grid_columnconfigure(0, weight=1)
        result_tab.grid_rowconfigure(0, weight=1)
        self.result_box = ctk.CTkTextbox(result_tab, wrap="word",
                                         font=ctk.CTkFont(family="Consolas", size=12))
        self.result_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.result_box.insert("1.0", "Henüz sonuç yok.")
        self.result_box.configure(state="disabled")

        actions = ctk.CTkFrame(result_tab, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.open_folder_button = ctk.CTkButton(
            actions, text="Çıktı klasörünü aç", command=self._open_output_folder, state="disabled")
        self.open_folder_button.pack(side="left")

        self.chart_panel = ChartPanel(self.tabs.tab("Grafikler"))
        self.chart_panel.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ #
    def _toggle_seeds(self) -> None:
        self.hf_query_entry.configure(state="normal" if self.hf_seed_var.get() else "disabled")
        self.web_query_entry.configure(state="normal" if self.web_seed_var.get() else "disabled")

    def _toggle_hf(self) -> None:
        self._toggle_seeds()

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
            self.console.write("Klasör açılamadı: %s" % exc, "error")

    # ------------------------------------------------------------------ #
    def _on_mode_change(self, mode: str) -> None:
        """Kip degisince ipucu metnini, satir etiketini ve - metin dokunulmamissa -
        ornegi degistirir."""
        self.prompt_hint.configure(text=_HINT.get(mode, ""))
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
                "Önce projenizi anlatın." if self.is_project_mode
                else "Önce ne üretmek istediğinizi yazın."
            )

        try:
            rows = int(str(self.rows_box.get()).replace(",", "").replace(".", "").strip())
        except ValueError:
            raise ValueError("Satır sayısı bir tam sayı olmalı.") from None
        if rows <= 0:
            raise ValueError("Satır sayısı pozitif olmalı.")

        try:
            seed = int(self.seed_entry.get().strip())
        except ValueError:
            raise ValueError("Random seed bir tam sayı olmalı.") from None

        formats = [fmt for fmt, var in self.format_vars.items() if var.get()]
        if not formats:
            raise ValueError("En az bir çıktı formatı seçin.")

        if not self.model_selector.is_ready():
            raise ValueError(self.model_selector.readiness_message())
        model = self.model_selector.model

        return {
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
            "Üretilen ham satır     : %s" % format(report["rows_in"], ","),
            "Validasyondan geçen    : %s" % format(report["rows_out"], ","),
            "Korunan oran           : %%%.1f" % report["retention_pct"],
            "Kod üretim denemesi    : %d" % result.generation_meta.get("attempts", 1),
            "Sandbox süresi         : %.1f sn" % result.generation_meta.get("duration_s", 0),
            "Tahmini LLM maliyeti   : $%.4f (%s çağrı)"
            % (result.cost.get("cost_usd", 0.0), result.cost.get("calls", 0)),
        ]
        # Proje kipinde plan, sonucun kendisi kadar onemli: hangi hedefi ve hangi
        # sizinti ayiklamasini kabul ettigini gormeden kullanici veriye guvenemez.
        if getattr(result, "plan", None) is not None:
            lines += plan_lines(result.plan)

        lines += [
            "",
            "AYIKLAMA AŞAMALARI",
            "-" * 62,
        ]
        for stage in report.get("stages", []):
            lines.append("  %-24s %8s -> %8s  (-%s)"
                         % (stage["stage"], format(stage["rows_before"], ","),
                            format(stage["rows_after"], ","), format(stage["removed"], ",")))

        rules = [r for r in report.get("business_rules", []) if r.get("status") == "applied"]
        if rules:
            lines += ["", "IS KURALLARI", "-" * 62]
            for rule in rules:
                lines.append("  %-44s %s ihlal" % (rule["rule"][:44],
                                                   format(rule["violations"], ",")))

        corrs = report.get("correlations", [])
        if corrs:
            lines += ["", "KORELASYON DOĞRULAMASI", "-" * 62]
            for corr in corrs:
                lines.append("  %-28s r=%-7s beklenen %s>=%s  [%s]"
                             % ("/".join(corr["pair"]), corr.get("actual_r"),
                                corr.get("expected_sign"), corr.get("min_r"),
                                "GEÇTİ" if corr.get("pass") else "KALDI"))

        pres = report.get("preserved_anomalies") or {}
        if pres.get("total_preserved", 0) > 0:
            lines += ["", "KORUNAN ANOMALİLER (FRAUD / OUTLIER MUAFİYETİ)", "-" * 62,
                      "  Hedef anomali kolonu               : %s (değer: %s)"
                      % (pres.get("column"), pres.get("value")),
                      "  Z-Score tarafından korunan         : %s satır"
                      % format(pres.get("z_score_preserved", 0), ","),
                      "  IsolationForest tarafından korunan : %s satır"
                      % format(pres.get("isolation_forest_preserved", 0), ","),
                      "  Toplam korunan anomali             : %s satır"
                      % format(pres.get("total_preserved", 0), ",")]

        dist = report.get("distributions") or {}
        if not dist.get("skipped"):
            lines += ["", "DAĞILIM (KS) TESTİ", "-" * 62,
                      "  %s/%s kolon referans dağılıma uyuyor (p > 0.05)"
                      % (dist.get("passed"), dist.get("total"))]
            for name, entry in (dist.get("columns") or {}).items():
                lines.append("  %-24s KS=%-7s p=%-8s [%s]"
                             % (name, entry["ks_stat"], entry["p_value"],
                                "GEÇTİ" if entry["pass"] else "KALDI"))

        lines += ["", "ÇIKTI DOSYALARI", "-" * 62]
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
            self.chart_panel.render(result.dataframe, result.schema, report)
        except Exception as exc:
            self.console.write("Grafikler çizilemedi: %s" % exc, "warning")

        self.tabs.set("Sonuç")
