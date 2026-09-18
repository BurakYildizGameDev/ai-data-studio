"""Pipeline yöneticisi - 7 aşamalı veri üretim ve doğrulama hattını yönetir.

  [1] Servis Kontrolü      -> Model sağlayıcısı / API anahtarı doğrulama
  [2] Araştırma & Schema   -> LLM domain analizi ve katı JSON şema kontratı üretimi
  [3] Seed Data Lookup     -> Web araması veya HuggingFace referans veri analizi
  [4] Kod Üretimi          -> LLM Python kod üretimi (self-healing, max 3 deneme)
  [5] Sandbox Çalıştırma   -> İzole subprocess + timeout + allowlist + bellek denetimi
  [6] Validasyon           -> Z-Score + IsolationForest + iş kuralları + korelasyon + KS
  [7] Çıktı & Durum Kaydı  -> CSV/JSON/Parquet + SQLite checkpoint + dataset card

run_pipeline() bir generator'dur: her adımda ilerleme sözlüğü yield eder ve
cancel_event kontrolü yapar. Nihai sonuç `return` ile döndürülür; PipelineWorker
bunu StopIteration.value üzerinden yakalar.

Terminalden çalıştırma (GUI'siz):
    python -m ai_data_studio.core.orchestrator --domain "e-ticaret sipariş verisi"
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import pandas as pd

from .. import config
from ..i18n import t
from ..services.llm_base import BaseLLMClient, LLMError
from . import relational_validator, validator
from .dataset_contract import MAX_TABLES, DatasetContract
from .project_planner import ProjectPlan
from .generator import GenerationFailedError, generate_dataset_and_execute
from .schema_contract import SchemaContract
from .state_manager import (
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_RUNNING,
    StateManager,
    get_state_manager,
)

log = logging.getLogger(__name__)

TOTAL_STEPS = 7

STEP_NAMES = {
    1: t("step.1"),
    2: t("step.2"),
    3: t("step.3"),
    4: t("step.4"),
    5: t("step.5"),
    6: t("step.6"),
    7: t("step.7"),
}

# Uretim motoru secenekleri.
#   llm        -> [4] kod uretimi + [5] sandbox (varsayilan; eski davranis birebir)
#   parametric -> ikisi de atlanir, sozlesme dogrudan vektorel derlenir (LLM kodu yok)
#   auto       -> once LLM denenir, kod uretimi tukendiginde parametrige duser
ENGINE_LLM = "llm"
ENGINE_PARAMETRIC = "parametric"
ENGINE_AUTO = "auto"
ENGINES = (ENGINE_LLM, ENGINE_PARAMETRIC, ENGINE_AUTO)


class PipelineCancelled(RuntimeError):
    """Kullanıcı pipeline'i iptal etti."""


@dataclass
class PipelineConfig:
    """Tek bir pipeline çalışmasının girdileri."""

    domain_prompt: str
    provider: str = config.PROVIDER_ANTHROPIC
    model: Optional[str] = None
    row_count: int = config.DEFAULT_ROW_TARGET
    random_seed: int = config.DEFAULT_RANDOM_SEED
    faker_locale: str = "en_US"
    use_hf_seed: bool = False
    hf_seed_query: str = ""
    hf_seed_dataset: str = ""
    use_web_seed: bool = False
    web_seed_query: str = ""
    export_formats: List[str] = field(default_factory=lambda: ["csv", "parquet"])
    output_dir: Optional[Path] = None
    # Kutuphane olarak cagrildiginda disk'e dosya birakmak istemeyebiliriz;
    # False ise [7] adimi veri/sema/kod/rapor dosyalarini hic yazmaz.
    write_outputs: bool = True
    # Yasal provenance serhi: True ise CSV basina "# PROVENANCE: ..." satirlari,
    # Parquet'e schema metadata, JSON'a "_provenance" ust duzey alani eklenir.
    provenance_header: bool = False
    # Yonetici ozeti PDF denetim raporu (Pro / Enterprise surum gerektirir)
    export_pdf: bool = False
    z_threshold: float = validator.DEFAULT_Z_THRESHOLD
    contamination: float = validator.DEFAULT_CONTAMINATION
    correlation_guard: bool = True
    max_retries: int = config.MAX_CODEGEN_RETRIES
    sandbox_timeout: int = config.SANDBOX_TIMEOUT_S
    push_to_hub: str = ""          # doluysa temiz veri bu repo_id'ye yuklenir
    hub_private: bool = True
    preserve_anomaly_column: Optional[str] = None
    preserve_anomaly_value: Any = None
    inject_fraud: bool = False
    fraud_rate: float = 0.005
    fraud_target_column: str = "is_fraud"
    # Enjeksiyonun uygulanacagi tablo: bos -> kok tablo (bugunku davranis).
    fraud_table: str = ""
    audit_privacy: bool = False
    # Hangi tablo(lar) gizlilik denetiminden gecsin: bos -> yalniz kok tablo
    # (bugunku davranis), "all" -> butun tablolar, tablo adi -> yalniz o tablo.
    audit_table: str = ""
    # Cok tablolu (iliskisel) uretim. Kapaliyken davranis birebir eskisi gibidir:
    # tek Schema Contract, tek DataFrame, duz rapor, ayni dosya adlari.
    relational: bool = False
    max_tables: int = 6
    # Doluysa pipeline domain tarifi yerine PROJE tarifi alir: planlayici hangi verinin
    # gerektigine kendisi karar verir ve sozlesmeyi uretir (bkz. core/project_planner).
    project_prompt: str = ""
    # Yetim yabanci anahtarlar bulundugunda True ise satirlar elenir, False ise
    # yalnizca raporlanir - CI kapisi olarak kullanilabilsin diye.
    repair_orphans: bool = True
    # --- Uretim motoru (bkz. ENGINES) --------------------------------- #
    # "parametric" ve "auto"nun parametrik yolu tek ve cok tablolu sozlesmeyi
    # dogrudan derler; iliskiselde cocuk yabanci anahtarlari ebeveynin uretilmis
    # anahtarlarindan cekilir (bkz. _generate_parametric).
    engine: str = ENGINE_LLM
    # --- [5.5] Uretim sonrasi, DOGRULAMA ONCESI zenginlestiriciler ----- #
    time_series: bool = False
    ts_timestamp_column: str = "transaction_timestamp"
    ts_entity_column: str = "customer_id"
    ts_start_date: str = ""        # bos -> TimeSeriesConfig varsayilani
    ts_end_date: str = ""
    ts_table: str = ""             # bos -> kok tablo
    expand_features: bool = False
    expand_table: str = ""         # bos -> kok tablo
    # --- [6.5] DOGRULAMA SONRASI kirli veri enjeksiyonu ---------------- #
    # 0 ise kapali. Sira bilincli: kirli veri doğrulamadan once enjekte edilirse
    # sema sinirlari / kategori denetimi tam da enjekte edilen satirlari eler.
    dirty_rate: float = 0.0
    dirty_table: str = ""          # bos -> kok tablo
    # --- Coklu Ajan Konseyi (Multi-Agent Council) ---------------------- #
    agentic: bool = False
    max_agent_rounds: int = 2

    def resolved_model(self) -> str:
        return self.model or config.DEFAULT_MODELS.get(self.provider, "")


@dataclass
class PipelineResult:
    """Tamamlanmış pipeline çıktısı.

    Iliskisel kosuda ``schema`` ve ``dataframe`` KOK tabloyu gosterir; butun
    tablolar ``tables`` icindedir. Boylece tek tablolu cagiranlar degismeden calisir.
    """

    job_id: int
    schema: SchemaContract
    dataframe: pd.DataFrame
    report: Dict[str, Any]
    code: str
    output_paths: Dict[str, str] = field(default_factory=dict)
    cost: Dict[str, Any] = field(default_factory=dict)
    generation_meta: Dict[str, Any] = field(default_factory=dict)
    hub_url: str = ""
    tables: Dict[str, pd.DataFrame] = field(default_factory=dict)
    contract: Optional[DatasetContract] = None
    plan: Optional[ProjectPlan] = None


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def run_pipeline(cfg: PipelineConfig,
                 cancel_event: Optional[threading.Event] = None,
                 state: Optional[StateManager] = None,
                 job_id: Optional[int] = None,
                 llm_client: Optional[BaseLLMClient] = None,
                 llm_progress_cb: Optional[Callable[[str], None]] = None
                 ) -> Iterator[Dict[str, Any]]:
    """Pipeline'ın 7 aşamasını çalıştırır; her adımda ilerleme durumu yield eder.

    Args:
        llm_client: Hazır bir istemci verilirse [1] adımı bunu kullanır
            (testlerde gerçek API çağrısı yapmadan pipeline'ı koşturmayı sağlar).
        llm_progress_cb: Tek bir LLM çağrısı SÜRERKEN gelen ara durumlar buraya
            yazılır. Generator o sırada yield edemez (çağrının içindeyiz), bu yüzden
            canlı akış ancak böyle dışarı çıkabiliyor: `agy` gibi dakikalarca süren
            ajan CLI'larında konsolun tek bilgi kaynağı budur.

    Yield edilen sözlük: {step, total_steps, name, message, percent, detail}
    Return değeri: PipelineResult
    """
    state = state or get_state_manager()
    cancel_event = cancel_event or threading.Event()

    # Motor secimi is'e baslamadan once dogrulanir: yanlis yazilmis bir bayrak
    # yuzunden dakikalarca suren bir LLM cagrisindan SONRA patlamak kotu.
    engine_choice = (cfg.engine or ENGINE_LLM).strip().lower()
    if engine_choice not in ENGINES:
        raise ValueError(t("pipeline.error.unknown_engine",
                           engine=cfg.engine, valid=", ".join(ENGINES)))
    if not 0.0 <= cfg.dirty_rate <= 1.0:
        raise ValueError(t("pipeline.error.dirty_rate_range", value=cfg.dirty_rate))

    def check_cancel() -> None:
        if cancel_event.is_set():
            raise PipelineCancelled(t("pipeline.cancelled_by_user"))

    # Yuzde asla geri gitmez. Iki yerde geri sarabiliyordu: seed verisi (adim 3)
    # semadan (adim 2) ONCE cekiliyor, ve self-healing yeniden denemesi sandbox'tan
    # (5) kod uretimine (4) donuyor. Ikisi de dogru davranis; geri saran bir
    # ilerleme cubugu ise kullaniciya hata gibi gorunuyordu. Adim numarasi spec'teki
    # kanonik numaradir ve oldugu gibi birakilir - yalnizca yuzde tek yone akar.
    furthest_percent = [0.0]

    def progress(step: int, message: str, fraction: float = 0.0,
                 level: str = config.PROGRESS_INFO, **detail: Any) -> Dict[str, Any]:
        """Adım içi ilerleme (fraction 0..1) dahil yüzde hesaplar.

        ``level`` olayın önem derecesidir ve konsol rengini BU belirler. Daha önce
        arayüz mesajın metninde "uyari"/"hata" arıyordu; metne bağlı bir eşleşme
        çeviri yapıldığı anda sessizce bozulur.
        """
        percent = round(((step - 1) + min(max(fraction, 0.0), 1.0)) / TOTAL_STEPS * 100, 1)
        percent = max(percent, furthest_percent[0])
        furthest_percent[0] = percent
        return {
            "step": step,
            "total_steps": TOTAL_STEPS,
            "name": STEP_NAMES[step],
            "message": message,
            "percent": percent,
            "level": level,
            "detail": detail,
        }

    if job_id is None:
        job_id = state.create_job(
            cfg.domain_prompt, provider=cfg.provider, model=cfg.resolved_model(),
            random_seed=cfg.random_seed,
        )
    state.save_checkpoint(job_id, status=STATUS_RUNNING, current_step=1,
                          step_name=STEP_NAMES[1], progress=0.0, error=None)

    try:
        # ---------------------------------------------------------------- #
        # [1] Servis kontrolu
        # ---------------------------------------------------------------- #
        check_cancel()
        yield progress(1, t("run.checking_provider", provider=cfg.provider,
                            model=cfg.resolved_model()))
        if llm_client is None:
            llm_client = _build_llm_client(cfg, state, job_id)
        if llm_progress_cb is not None:
            llm_client.progress_cb = llm_progress_cb
        yield progress(1, t("run.service_ready", model=llm_client.model), 1.0)
        yield progress(1, "  -> " + t("run.provider_model", provider=cfg.provider,
                                      model=llm_client.model), 1.0)
        if (engine_choice in (ENGINE_LLM, ENGINE_AUTO)
                and cfg.provider == config.PROVIDER_OLLAMA):
            from ..services.ollama_service import is_small_model
            if is_small_model(llm_client.model):
                # Davranis degismez (varsayilan motor bilincli olarak llm), ama kullanici
                # dakikalar sonra FAILED gormeden (llm) ya da bosa giden kod turlarini
                # beklemeden (auto) once nedenini ve cikisini bilmeli.
                yield progress(1, t("run.engine.small_model_warning", model=llm_client.model),
                               1.0, level=config.PROGRESS_WARNING)

        # ---------------------------------------------------------------- #
        # [3'] Seed veri - semadan ONCE cekilir ki sema onu referans alabilsin
        # ---------------------------------------------------------------- #
        seed_df: Optional[pd.DataFrame] = None
        seed_source = ""
        if cfg.use_hf_seed:
            check_cancel()
            yield progress(3, t("run.seed.hf_searching"))
            seed_df, seed_source = _fetch_seed_data(cfg)
            if seed_df is not None:
                state.save_checkpoint(job_id, seed_data_path=seed_source)
                yield progress(3, t("run.seed.loaded", source=seed_source,
                                    rows=format(len(seed_df), ",")), 1.0)
                cols_preview = ", ".join(list(seed_df.columns)[:5])
                if len(seed_df.columns) > 5:
                    cols_preview += "..."
                yield progress(3, "  -> " + t("run.seed.columns",
                                              count=len(seed_df.columns),
                                              columns=cols_preview), 1.0)
            else:
                yield progress(3, t("run.seed.none_found"), 1.0)
        elif getattr(cfg, "use_web_seed", False):
            check_cancel()
            web_q = cfg.web_seed_query or cfg.domain_prompt
            yield progress(3, t("run.seed.web_searching", query=web_q[:50]))
            from ..services import web_collector
            seed_df, seed_source = web_collector.collect_web_seed(web_q, cfg.domain_prompt, llm_client)
            if seed_df is not None and not seed_df.empty:
                state.save_checkpoint(job_id, seed_data_path="web:" + seed_source)
                yield progress(3, t("run.seed.web_collected", source=seed_source,
                                    rows=len(seed_df),
                                    columns=len(seed_df.columns)), 1.0)
                cols_preview = ", ".join(list(seed_df.columns)[:5])
                if len(seed_df.columns) > 5:
                    cols_preview += "..."
                yield progress(3, "  -> " + t("run.seed.extracted_columns",
                                              columns=cols_preview), 1.0)
            else:
                yield progress(3, t("run.seed.web_none"), 1.0)
        else:
            yield progress(3, t("run.seed.skipped"), 1.0)

        # ---------------------------------------------------------------- #
        # [2] Arastirma & Schema/Dataset Contract uretimi
        # ---------------------------------------------------------------- #
        # Sonuc her hâlukârda bir DatasetContract olarak tasinir: tek tablo bunun
        # N=1 ozel durumu, ayri bir kod yolu degil.
        check_cancel()
        state.save_checkpoint(job_id, current_step=2, step_name=STEP_NAMES[2])
        plan: Optional[ProjectPlan] = None
        if cfg.agentic:
            yield progress(2, t("run.agents.gathering"))
            from ..agents.council_coordinator import CouncilCoordinator

            coordinator = CouncilCoordinator(
                llm_client=llm_client,
                max_rounds=cfg.max_agent_rounds,
            )
            yield progress(2, "  ├─ " + t("run.agents.started", rounds=cfg.max_agent_rounds))
            compiled_result = coordinator.deliberate(
                domain_prompt=cfg.domain_prompt,
                row_count=cfg.row_count,
                seed=cfg.random_seed,
                locale=cfg.faker_locale,
                relational=cfg.relational,
                seed_summary=seed_source if seed_df is not None else "",
            )
            if isinstance(compiled_result, DatasetContract):
                contract = compiled_result
            else:
                contract = DatasetContract.from_schema(compiled_result)
            yield progress(2, "  └─ " + t("run.agents.consensus",
                                          tables=len(contract.table_names)), 1.0)
        elif cfg.project_prompt:
            # Planlayici yolu: kac tablo gerektigine plan karar verir, kullanici degil.
            if not 1 <= cfg.max_tables <= MAX_TABLES:
                raise ValueError(t("pipeline.error.max_tables_planner",
                                   limit=MAX_TABLES, value=cfg.max_tables))
            yield progress(2, t("run.plan.analysing"))
            plan = llm_client.generate_project_plan(
                cfg.project_prompt, row_count=cfg.row_count, seed=cfg.random_seed,
                locale=cfg.faker_locale, seed_dataframe=seed_df,
                max_tables=cfg.max_tables,
            )
            contract = plan.contract
        elif cfg.relational:
            # Iliskisel mod en az 2 tablo demektir; ust sinir sozlesmenin sert siniri.
            # Aksi halde istem kendisiyle celisir (min_tables=2, max_tables=1) ya da
            # model sozlesmenin reddedecegi kadar cok tablo uretir.
            if not 2 <= cfg.max_tables <= MAX_TABLES:
                raise ValueError(t("pipeline.error.max_tables_relational",
                                   limit=MAX_TABLES, value=cfg.max_tables))
            yield progress(2, t("run.schema.relational"))
            contract = llm_client.generate_dataset_schema(
                cfg.domain_prompt, row_count=cfg.row_count, seed=cfg.random_seed,
                locale=cfg.faker_locale, seed_dataframe=seed_df,
                max_tables=cfg.max_tables,
            )
        else:
            yield progress(2, t("run.schema.single"))
            contract = DatasetContract.from_schema(llm_client.generate_schema(
                cfg.domain_prompt, row_count=cfg.row_count, seed=cfg.random_seed,
                locale=cfg.faker_locale, seed_dataframe=seed_df,
            ))
        # Kok tablonun semasi: tek tablo bekleyen tuketiciler (GUI, HF karti,
        # gizlilik denetimi) bunu kullanir.
        schema = contract.table(contract.root_table)

        # Tek tabloda eskisi gibi Schema Contract JSON'i saklanir, iliskiselde tum
        # sozlesme. DatasetContract.from_dict ikisini de okuyabildigi icin gecmis
        # kayitlari yeniden okumak bozulmaz.
        state.save_checkpoint(
            job_id,
            schema_metadata=contract.to_dict() if cfg.relational else schema.to_dict(),
            domain=contract.domain,
            progress=2 / TOTAL_STEPS * 100,
        )
        if cfg.relational:
            yield progress(2, t("run.schema.contract_ready",
                                tables=len(contract.tables),
                                relationships=len(contract.relationships),
                                root=contract.root_table), 1.0,
                           schema=contract.to_dict(), warnings=contract.warnings)
        else:
            yield progress(2, t("run.schema.ready", summary=schema.summary()), 1.0,
                           schema=schema.to_dict(), warnings=schema.warnings)

        if plan is not None:
            yield from _plan_detail_events(plan, progress)
        yield from _schema_detail_events(contract, progress)

        # Gecersiz bir --audit-table SESSIZCE kabul edilmemeli: kullanici denetim
        # yaptigini sanip hic yapmamis olur. Sozlesme ancak burada bilindigi icin
        # kontrol bu noktada.
        if cfg.fraud_table and cfg.fraud_table not in contract.table_names:
            raise ValueError(t("pipeline.error.unknown_fraud_table",
                               table=cfg.fraud_table,
                               tables=", ".join(contract.table_names)))
        if cfg.audit_table and cfg.audit_table.lower() != "all":
            if cfg.audit_table not in contract.table_names:
                raise ValueError(t("pipeline.error.unknown_audit_table",
                                   table=cfg.audit_table,
                                   tables=", ".join(contract.table_names)))
        if cfg.ts_table and cfg.ts_table not in contract.table_names:
            raise ValueError(t("pipeline.error.unknown_ts_table",
                               table=cfg.ts_table,
                               tables=", ".join(contract.table_names)))
        if cfg.expand_table and cfg.expand_table not in contract.table_names:
            raise ValueError(t("pipeline.error.unknown_expand_table",
                               table=cfg.expand_table,
                               tables=", ".join(contract.table_names)))
        if cfg.dirty_table and cfg.dirty_table not in contract.table_names:
            raise ValueError(t("pipeline.error.unknown_dirty_table",
                               table=cfg.dirty_table,
                               tables=", ".join(contract.table_names)))
        if cfg.audit_privacy:
            audited = [n for n in contract.generation_order()
                       if _should_audit(n, cfg, contract)]
            yield progress(2, t("run.audit.tables", tables=", ".join(audited)), 1.0)

        # ---------------------------------------------------------------- #
        # [4] + [5] Kod uretimi (self-healing) & sandbox calistirma
        # ---------------------------------------------------------------- #
        check_cancel()
        state.save_checkpoint(job_id, current_step=4, step_name=STEP_NAMES[4])

        # Hangi motorun kostugu rapora yazilir; kullanicinin "bu veriyi ne uretti"
        # sorusunun cevabi ciktida durmali.
        engines_report: Dict[str, Any] = {"generation": engine_choice}
        raw_tables: Dict[str, pd.DataFrame]
        code: str
        gen_meta: Dict[str, Any]

        if engine_choice == ENGINE_PARAMETRIC:
            yield progress(4, t("run.engine.parametric_selected"))
            raw_tables, code, gen_meta = _generate_parametric(contract, cfg)
            yield progress(5, t("run.engine.compiled_no_llm",
                                seconds="%.3f" % gen_meta["duration_s"]), 1.0)
        else:
            yield progress(4, t("run.codegen.writing"))

            # Kuyruk uclusu: (mesaj, seviye, sandbox_asamasi_mi)
            messages: "queue.Queue[Tuple[str, str, bool]]" = queue.Queue()
            gen_result: Dict[str, Any] = {}

            def worker() -> None:
                try:
                    # Tek tablolu sozlesmede bu cagri kendiliginden tek tablo yoluna
                    # duser; ayri dallanma gerekmiyor.
                    produced, produced_code, meta = generate_dataset_and_execute(
                        contract, llm_client,
                        max_retries=cfg.max_retries,
                        timeout=cfg.sandbox_timeout,
                        cancel_event=cancel_event,
                        on_progress=lambda m, lv=config.PROGRESS_INFO, sb=False:
                            messages.put((m, lv, sb)),
                    )
                    gen_result["tables"] = produced
                    gen_result["code"] = produced_code
                    gen_result["meta"] = meta
                except BaseException as exc:  # noqa: BLE001 - ana thread'e tasinacak
                    gen_result["error"] = exc

            thread = threading.Thread(target=worker, name="codegen", daemon=True)
            thread.start()
            # Uretim surerken alt adim mesajlarini UI'a akitmaya devam et.
            while thread.is_alive() or not messages.empty():
                try:
                    message, level, is_sandbox = messages.get(timeout=0.2)
                except queue.Empty:
                    continue
                yield progress(5 if is_sandbox else 4, message, 0.5, level=level)
            thread.join()

            gen_error = gen_result.get("error")
            # "auto": kod uretimi denemeleri tukendiyse pipeline'i dusurmek yerine
            # parametrik motora gec. Yalnizca GenerationFailedError icin - iptal,
            # kimlik/servis hatasi ve iliskisel sozlesme fallback'e girmez.
            if (gen_error is not None
                    and engine_choice == ENGINE_AUTO
                    and isinstance(gen_error, GenerationFailedError)
                    and not cancel_event.is_set()):
                yield progress(4, t("run.codegen.failed_warning", error=gen_error), 0.9,
                               level=config.PROGRESS_WARNING)
                yield progress(4, "  -> " + t("run.engine.falling_back"), 0.9)
                raw_tables, code, gen_meta = _generate_parametric(contract, cfg)
                gen_meta["fallback_from"] = ENGINE_LLM
                gen_meta["fallback_reason"] = str(gen_error)
                engines_report["generation"] = "llm->parametric"
                yield progress(5, t("run.engine.compiled",
                                    seconds="%.3f" % gen_meta["duration_s"]), 1.0)
            elif gen_error is not None:
                raise gen_error
            else:
                raw_tables = gen_result["tables"]
                code = gen_result["code"]
                gen_meta = gen_result["meta"]
                gen_meta.setdefault("engine", ENGINE_LLM)
                engines_report["generation"] = ENGINE_LLM

        raw_df: pd.DataFrame = raw_tables[contract.root_table]

        raw_paths = _write_raw_tables(raw_tables, contract, job_id)
        raw_total = sum(len(df) for df in raw_tables.values())

        state.save_checkpoint(job_id, current_step=5, step_name=STEP_NAMES[5],
                              generated_rows_count=raw_total,
                              raw_data_path=raw_paths.get(contract.root_table, ""),
                              progress=5 / TOTAL_STEPS * 100)
        if contract.is_relational:
            yield progress(5, t("run.raw.generated_relational",
                                tables=len(raw_tables), rows=format(raw_total, ","),
                                attempts=gen_meta["attempts"],
                                seconds="%.1f" % gen_meta["duration_s"]),
                           1.0, rows=raw_total, attempts=gen_meta["attempts"],
                           row_counts={k: len(v) for k, v in raw_tables.items()})
            for name in contract.generation_order():
                yield progress(5, "  -> %s: %s" % (
                    name, t("result.rows_value",
                            rows=format(len(raw_tables[name]), ","))), 1.0)
        else:
            yield progress(5, t("run.raw.generated",
                                rows=format(len(raw_df), ","),
                                attempts=gen_meta["attempts"],
                                seconds="%.1f" % gen_meta["duration_s"]),
                           1.0, rows=len(raw_df), attempts=gen_meta["attempts"])
        for name, path in sorted(raw_paths.items()):
            try:
                raw_mb = Path(path).stat().st_size / (1024 * 1024)
                yield progress(5, "  -> " + t("run.raw.saved", name=Path(path).name,
                                              size="%.2f" % raw_mb), 1.0)
            except Exception:
                pass

        # Fraud / Anomali Senaryo Enjeksiyonu (isteğe bağlı)
        fraud_target_table = cfg.fraud_table or contract.root_table
        if cfg.inject_fraud:
            from .fraud_injector import inject_fraud_scenarios
            injected, fraud_info = inject_fraud_scenarios(
                raw_tables[fraud_target_table],
                fraud_rate=cfg.fraud_rate,
                target_column=cfg.fraud_target_column,
                seed=cfg.random_seed,
            )
            raw_tables[fraud_target_table] = injected
            if fraud_target_table == contract.root_table:
                raw_df = injected
            if not cfg.preserve_anomaly_column:
                cfg.preserve_anomaly_column = cfg.fraud_target_column
            yield progress(
                5,
                t("run.fraud.injected",
                  rows=fraud_info["injected_fraud_count"],
                  rate="%.2f" % (fraud_info["fraud_rate"] * 100),
                  table=fraud_target_table, column=cfg.fraud_target_column),
                1.0,
                fraud=fraud_info,
            )

        # ---------------------------------------------------------------- #
        # [5.5] Zenginlestirme - uretimden SONRA, dogrulamadan ONCE
        # ---------------------------------------------------------------- #
        # Bu iki motor kolon EKLER, satir silmez; doğrulama semada olmayan
        # kolonlara dokunmaz (validator kolon sirasini "sema + ekstralar" olarak
        # normalize eder), dolayisiyla eklenen kolonlar temizlikten sag cikar.
        # Iliskisel kosuda yalnizca KOK tabloya uygulanir - fraud enjeksiyonuyla
        # ayni kural, README'de yazili.
        target_ts_table = cfg.ts_table or contract.root_table
        if cfg.time_series:
            check_cancel()
            from .time_series_engine import TimeSeriesConfig, TimeSeriesEngine

            ts_cfg = TimeSeriesConfig(
                timestamp_column=cfg.ts_timestamp_column,
                entity_id_column=cfg.ts_entity_column or None,
                random_seed=cfg.random_seed,
            )
            if cfg.ts_start_date:
                ts_cfg.start_date = cfg.ts_start_date
            if cfg.ts_end_date:
                ts_cfg.end_date = cfg.ts_end_date
            ts_target_df = raw_tables[target_ts_table]
            ts_target_df, ts_meta = TimeSeriesEngine(ts_cfg).apply(ts_target_df)
            ts_meta["target_table"] = target_ts_table
            raw_tables[target_ts_table] = ts_target_df
            if target_ts_table == contract.root_table:
                raw_df = ts_target_df
            engines_report["time_series"] = ts_meta
            yield progress(5, t("run.time_series.applied",
                                entities=format(ts_meta.get("unique_entities", 0), ","),
                                bursts=ts_meta.get("burst_anomalies_count", 0),
                                median="%.0f" % ts_meta.get("median_delta_seconds", 0.0)),
                           1.0, time_series=ts_meta)
            yield progress(5, "  -> " + t("result.engines.time_range") + ": %s"
                           % ts_meta.get("time_range", "-"), 1.0)
            entities = ts_meta.get("unique_entities", 0)
            if entities > 0.5 * max(1, len(ts_target_df)):
                yield progress(5, t("run.time_series.entity_warning",
                                    column=cfg.ts_entity_column or "entity_id",
                                    rows=format(len(ts_target_df), ","),
                                    distinct=format(entities, ",")), 1.0,
                               level=config.PROGRESS_WARNING)

        target_expand_table = cfg.expand_table or contract.root_table
        if cfg.expand_features:
            check_cancel()
            from .feature_expander import expand_features

            expand_target_df = raw_tables[target_expand_table]
            expand_target_df, fe_meta = expand_features(expand_target_df)
            fe_meta["target_table"] = target_expand_table
            raw_tables[target_expand_table] = expand_target_df
            if target_expand_table == contract.root_table:
                raw_df = expand_target_df
            engines_report["feature_expander"] = fe_meta
            added = fe_meta.get("added_columns", [])
            yield progress(5, t("run.features.expanded",
                                added=fe_meta.get("added_columns_count", 0),
                                total=fe_meta.get("total_columns", len(expand_target_df.columns))),
                           1.0, feature_expander=fe_meta)
            if added:
                yield progress(5, "  -> " + t("result.engines.added_columns")
                               + ": %s" % ", ".join(added), 1.0)

        # ---------------------------------------------------------------- #
        # [6] Validasyon & ayiklama
        # ---------------------------------------------------------------- #
        # SIRA KRITIK: once her tablo tek basina temizlenir, SONRA iliskisel
        # butunluk onarilir. Tersi olmaz - tek tablo temizligi bir ebeveyn satiri
        # sildiginde cocuklari yetim kalir, bu yuzden yetim ayiklamasi en sonda.
        check_cancel()
        state.save_checkpoint(job_id, current_step=6, step_name=STEP_NAMES[6])
        yield progress(6, t("run.validation.running"))

        # Kuyruk ikilisi: (mesaj, seviye)
        val_messages: "queue.Queue[Tuple[str, str]]" = queue.Queue()
        val_result: Dict[str, Any] = {}

        def val_worker() -> None:
            try:
                cleaned: Dict[str, pd.DataFrame] = {}
                reports: Dict[str, Any] = {}
                for name in contract.generation_order():
                    if contract.is_relational:
                        def emit(message: str, level: str = config.PROGRESS_INFO,
                                 _table: str = name) -> None:
                            val_messages.put(("[%s] %s" % (_table, message), level))
                        val_messages.put((t("run.validation.table", table=name),
                                          config.PROGRESS_INFO))
                    else:
                        def emit(message: str, level: str = config.PROGRESS_INFO) -> None:
                            val_messages.put((message, level))
                    # Kok tabloya ozgu secenekler (seed karsilastirmasi, anomali
                    # koruma, gizlilik denetimi) yalnizca kok tabloda calisir.
                    is_root = name == contract.root_table
                    # Anomali muafiyeti, enjeksiyonun YAPILDIGI tabloya baglanir.
                    # Koke sabitlenseydi, cocuk tabloya enjekte edilen dolandiricilik
                    # satirlari Z-Score / IsolationForest tarafindan silinir ve kimse
                    # fark etmezdi.
                    preserves = name == fraud_target_table if cfg.inject_fraud else is_root
                    clean, rep = validator.run_validation(
                        raw_tables[name], contract.table(name),
                        seed_df=seed_df if is_root else None,
                        z_threshold=cfg.z_threshold, contamination=cfg.contamination,
                        preserve_anomaly_column=cfg.preserve_anomaly_column if preserves else None,
                        preserve_anomaly_value=cfg.preserve_anomaly_value,
                        audit_privacy=_should_audit(name, cfg, contract),
                        audit_table_name=name if contract.is_relational else "",
                        cancel_event=cancel_event, on_progress=emit,
                        correlation_guard=cfg.correlation_guard,
                    )
                    cleaned[name] = clean
                    reports[name] = rep
                val_result["tables"] = cleaned
                val_result["reports"] = reports
            except BaseException as exc:  # noqa: BLE001
                val_result["error"] = exc

        val_thread = threading.Thread(target=val_worker, name="validator", daemon=True)
        val_thread.start()
        while val_thread.is_alive() or not val_messages.empty():
            try:
                message, level = val_messages.get(timeout=0.2)
            except queue.Empty:
                continue
            yield progress(6, message, 0.5, level=level)
        val_thread.join()

        if "error" in val_result:
            raise val_result["error"]

        clean_tables: Dict[str, pd.DataFrame] = val_result["tables"]
        table_reports: Dict[str, Any] = val_result["reports"]

        # Tek tabloda rapor bugunku duz yapisini aynen korur; iliskiselde kok
        # tablonun raporu ustte kalir, tablo basina detay "tables" altina girer.
        report: Dict[str, Any] = dict(table_reports[contract.root_table])

        if contract.is_relational:
            check_cancel()
            yield progress(6, t("run.relational.checking",
                                count=len(contract.relationships)), 0.8)
            rel_lines: List[Tuple[str, str]] = []

            def collect_rel(message: str, level: str = config.PROGRESS_INFO) -> None:
                rel_lines.append((message, level))

            clean_tables, rel_report = relational_validator.validate_relationships(
                clean_tables, contract, repair=cfg.repair_orphans, emit=collect_rel,
            )
            for line, line_level in rel_lines:
                yield progress(6, line, 0.9, level=line_level)

            rel_report["repair_enabled"] = cfg.repair_orphans
            report["tables"] = table_reports
            report["relational"] = rel_report
            if not rel_report["pass"]:
                reason = (t("run.relational.repair_disabled")
                          if not cfg.repair_orphans
                          else t("run.relational.contract_violated"))
                yield progress(6, t("run.relational.failed", reason=reason),
                               0.95, level=config.PROGRESS_WARNING)

        clean_df: pd.DataFrame = clean_tables[contract.root_table]

        # ---------------------------------------------------------------- #
        # [6.5] Kontrollu kirli veri - DOGRULAMADAN SONRA
        # ---------------------------------------------------------------- #
        # SIRA KRITIK, tersi sessizce ise yaramaz: kirli veri dogrulamadan once
        # enjekte edilseydi sema sinirlari (validator.apply_schema_bounds) uc
        # degerleri, kategori denetimi yazim hatalarini ve null denetimi eksik
        # degerleri eleyecekti - yani tam olarak enjekte edilen satirlar. Kirlilik
        # bilincli bir cikti ozelligi; benchmark verisinin gurultusu olarak
        # DISARI cikmasi gerekiyor.
        dirty_target_table = cfg.dirty_table or contract.root_table
        if cfg.dirty_rate > 0:
            check_cancel()
            from .dirty_data_engine import DirtyDataConfig, DirtyDataEngine

            # ANAHTAR KOLONLAR BOZULMAZ. Kirlilik ilişkisel bütünlük denetiminden
            # SONRA calisiyor; birincil ya da yabanci anahtara null/yazim hatasi
            # enjekte edilseydi denetimden "0 yetim FK" damgasi almis bir veri seti
            # kirli anahtarlarla disari cikardi. Tek tabloda da PK'nin tekilligi
            # iddia edilmis oluyor, onu da bozmamak gerekiyor.
            dirty_cfg = DirtyDataConfig(
                dirty_rate=cfg.dirty_rate,
                random_seed=cfg.random_seed,
            )
            dirty_cfg.exclude_columns = set(dirty_cfg.exclude_columns) | _key_columns(contract)
            dirty_target_df = clean_tables[dirty_target_table]
            dirty_target_df, dirty_meta = DirtyDataEngine(dirty_cfg).corrupt(dirty_target_df)
            dirty_meta["target_table"] = dirty_target_table
            clean_tables[dirty_target_table] = dirty_target_df
            if dirty_target_table == contract.root_table:
                clean_df = dirty_target_df
            # Rapordaki kolon istatistikleri bu adimdan ONCE hesaplandi; okuyan
            # kisi yanilmasin diye bunu rapora acikca yaziyoruz.
            dirty_meta["applied_after_validation"] = True
            dirty_meta["column_stats_precede_corruption"] = True
            engines_report["dirty_data"] = dirty_meta
            breakdown = dirty_meta.get("corruption_breakdown", {})
            yield progress(6, t("run.dirty.injected",
                                rows=format(dirty_meta.get("corrupted_rows", 0), ","),
                                rate="%.1f" % (dirty_meta.get("corrupted_rate", 0.0) * 100),
                                missing=breakdown.get("missing", 0),
                                typo=breakdown.get("typo", 0),
                                spike=breakdown.get("outlier_spike", 0),
                                casing=breakdown.get("casing", 0)),
                           1.0, dirty_data=dirty_meta)
            yield progress(6, "  -> " + t("run.dirty.audit_columns"), 1.0)

        report["engines"] = engines_report
        report["generation"] = gen_meta
        report["seed_source"] = seed_source
        if plan is not None:
            report["project_plan"] = plan.to_dict()

        state.save_report(job_id, report)
        state.save_checkpoint(job_id,
                              validated_rows_count=sum(len(df) for df in clean_tables.values()),
                              progress=6 / TOTAL_STEPS * 100)
        yield progress(6, t("run.validation.done",
                            rows_in=format(report["rows_in"], ","),
                            rows_out=format(report["rows_out"], ","),
                            retention="%.1f" % report["retention_pct"]),
                       1.0, report=_report_summary(report))
        if contract.is_relational:
            for name in contract.generation_order():
                rep = table_reports[name]
                yield progress(6, "  -> %s: %s" % (name, t(
                    "run.validation.table_rows",
                    rows_in=format(rep["rows_in"], ","),
                    rows_out=format(rep["rows_out"], ","),
                    retention="%.1f" % rep["retention_pct"])), 1.0)

        # ---------------------------------------------------------------- #
        # [7] Cikti & durum kaydi
        # ---------------------------------------------------------------- #
        check_cancel()
        state.save_checkpoint(job_id, current_step=7, step_name=STEP_NAMES[7])
        if cfg.write_outputs:
            yield progress(7, t("run.output.writing"))
            output_paths = _write_outputs(clean_tables, contract, report, code, job_id,
                                          cfg, plan)
            yield progress(7, t("run.output.written",
                                kinds=", ".join(sorted(output_paths))), 0.6,
                           paths=output_paths)
        else:
            output_paths = {}
            yield progress(7, t("run.output.skipped"), 0.6)
        for kind, path in sorted(output_paths.items()):
            try:
                p = Path(path)
                sz = p.stat().st_size
                sz_str = ("%.1f KB" % (sz / 1024)) if sz < 1024 * 1024 else ("%.2f MB" % (sz / (1024 * 1024)))
                yield progress(7, "  • %-8s: %s (%s)" % (kind.upper(), p.name, sz_str), 0.7)
            except Exception:
                pass

        hub_url = ""
        if cfg.push_to_hub:
            check_cancel()
            yield progress(7, t("run.hub.uploading", repo=cfg.push_to_hub), 0.8)
            hub_url = _push_to_hub(clean_df, schema, report, llm_client, cfg, contract)
            yield progress(7, t("run.hub.uploaded", url=hub_url), 0.9, hub_url=hub_url)

        cost = state.get_cost_summary(job_id)
        if cost.get("calls", 0) > 0 or cost.get("cost_usd", 0.0) > 0:
            # get_cost_summary input_tokens/output_tokens dondurur; eskiden var olmayan
            # prompt_tokens/completion_tokens okunuyor ve toplam hep 0 basiliyordu.
            tot_tokens = cost.get("input_tokens", 0) + cost.get("output_tokens", 0)
            yield progress(7, "  -> " + t("run.cost.summary",
                                          calls=cost.get("calls", 0),
                                          tokens=format(tot_tokens, ","),
                                          cost="%.4f" % cost.get("cost_usd", 0.0)), 0.95)

        # Iliskisel kosuda tek bir "cikti dosyasi" yok; manifest hepsini isaret eder.
        state.save_checkpoint(job_id, status=STATUS_DONE, progress=100.0,
                              output_path=output_paths.get("manifest") or
                              output_paths.get("csv") or
                              next(iter(output_paths.values()), None))
        clean_total = sum(len(df) for df in clean_tables.values())
        if contract.is_relational:
            yield progress(7, t("run.finished_relational",
                                tables=len(clean_tables),
                                rows=format(clean_total, ","),
                                cost="%.4f" % cost.get("cost_usd", 0.0)), 1.0,
                           level=config.PROGRESS_SUCCESS, cost=cost)
        else:
            yield progress(7, t("run.finished",
                                rows=format(len(clean_df), ","),
                                cost="%.4f" % cost.get("cost_usd", 0.0)), 1.0,
                           level=config.PROGRESS_SUCCESS, cost=cost)

        return PipelineResult(
            job_id=job_id, schema=schema, dataframe=clean_df, report=report, code=code,
            output_paths=output_paths, cost=cost, generation_meta=gen_meta, hub_url=hub_url,
            tables=clean_tables, contract=contract, plan=plan,
        )

    except PipelineCancelled:
        state.save_checkpoint(job_id, status=STATUS_CANCELLED,
                              error=t("pipeline.cancelled_by_user"))
        raise
    except validator.ValidationCancelled as exc:
        state.save_checkpoint(job_id, status=STATUS_CANCELLED, error=str(exc))
        raise PipelineCancelled(str(exc)) from exc
    except GenerationFailedError as exc:
        if cancel_event.is_set():
            state.save_checkpoint(job_id, status=STATUS_CANCELLED, error=str(exc))
            raise PipelineCancelled(str(exc)) from exc
        state.save_checkpoint(job_id, status=STATUS_FAILED, error=str(exc))
        raise
    except LLMError as exc:
        # Yapilandirma/servis hatasi - kullanici hatasi, traceback gurultu yaratir.
        log.error("Pipeline durduruldu: %s", exc)
        state.save_checkpoint(job_id, status=STATUS_FAILED, error=str(exc))
        raise
    except Exception as exc:
        log.exception("Pipeline hatası")
        state.save_checkpoint(job_id, status=STATUS_FAILED, error=str(exc))
        raise


# --------------------------------------------------------------------------- #
# Adim yardimcilari
# --------------------------------------------------------------------------- #
def _plan_detail_events(plan: ProjectPlan,
                        progress: Callable[..., Dict[str, Any]]
                        ) -> Iterator[Dict[str, Any]]:
    """[2] Planlayicinin verdigi kararlari konsola dokur.

    Bu dokum isin gorunur degeri: kullanici hangi hedefi, hangi sinif dengesini ve
    hangi sizinti ayiklamasini kabul ettigini gormeden plana guvenemez.
    """
    yield progress(2, t("run.plan.ready", summary=plan.summary()), 1.0,
                   plan=plan.to_dict())
    if plan.rationale:
        yield progress(2, "  -> " + t("run.plan.rationale", rationale=plan.rationale), 1.0)
    if plan.target is not None:
        yield progress(2, "  -> " + t("run.plan.target", target=plan.target.label()), 1.0)
    if plan.positive_class_ratio is not None:
        yield progress(2, "  -> " + t("run.plan.class_balance",
                                      pct="%.1f" % (plan.positive_class_ratio * 100)), 1.0)
    if plan.excluded_leakage:
        yield progress(2, "  -> " + t("run.plan.leakage",
                                      count=len(plan.excluded_leakage)), 1.0)
        for excl in plan.excluded_leakage:
            yield progress(2, "  • %s - %s" % (excl.column, excl.reason), 1.0)
    if plan.split is not None:
        detail = plan.split.kind
        if plan.split.column:
            detail += " (%s.%s)" % (plan.split.table, plan.split.column)
        yield progress(2, "  -> " + t("run.plan.split", kind=detail,
                                      reason=plan.split.reason), 1.0)
    for warning in plan.warnings:
        yield progress(2, t("run.warning_prefix", message=warning), 1.0,
                       level=config.PROGRESS_WARNING)


def _schema_detail_events(contract: DatasetContract,
                          progress: Callable[..., Dict[str, Any]]
                          ) -> Iterator[Dict[str, Any]]:
    """[2] Konsol dokumu: tablo basina kolonlar, is kurallari, korelasyonlar.

    Tek tabloda cikti eskisiyle birebir ayni kalir (tablo basligi basilmaz);
    iliskiselde her tablo kendi basligi altinda listelenir ve sonda iliski
    semasi yazilir.
    """
    multi = contract.is_relational
    if multi:
        yield progress(2, "  -> " + t("run.schema.generation_order",
                                      tables=len(contract.tables),
                                      order=" -> ".join(contract.generation_order())), 1.0)

    for schema in contract.tables:
        if multi:
            pk = schema.primary_key or "-"
            yield progress(2, "  -> " + t("run.schema.table_line",
                                          table=schema.table_name, pk=pk,
                                          rows=format(schema.row_count_target, ",")), 1.0)
        yield progress(2, "  -> " + t("run.schema.columns_header",
                                      count=len(schema.columns)), 1.0)
        for col in schema.columns:
            specs = []
            if col.min is not None or col.max is not None:
                specs.append(t("run.schema.spec_range",
                               low=col.min if col.min is not None else "-inf",
                               high=col.max if col.max is not None else "+inf"))
            if col.distribution:
                specs.append(t("run.schema.spec_distribution",
                               distribution=col.distribution))
            if col.categories:
                cats = ", ".join(repr(c) for c in col.categories[:3])
                if len(col.categories) > 3:
                    cats += ", ..."
                specs.append(t("run.schema.spec_categories", categories=cats))
            if col.target_ratio is not None:
                specs.append(t("run.schema.spec_ratio",
                               pct="%.1f" % (col.target_ratio * 100)))
            if not col.nullable:
                specs.append(t("run.schema.spec_not_null"))
            spec_str = (" (%s)" % ", ".join(specs)) if specs else ""
            yield progress(2, "  • %s: %s%s" % (col.name, col.type, spec_str), 1.0)

        if schema.business_rules:
            yield progress(2, "  -> " + t("run.schema.rules_header",
                                          count=len(schema.business_rules)), 1.0)
            for rule in schema.business_rules:
                yield progress(2, "  • " + t("run.schema.rule", rule=rule), 1.0)

        if schema.correlations:
            yield progress(2, "  -> " + t("run.schema.correlations_header",
                                          count=len(schema.correlations)), 1.0)
            for corr in schema.correlations:
                yield progress(2, "  • %s <-> %s (%s, min_r=%.2f)"
                               % (corr.columns[0], corr.columns[1],
                                  corr.expected_sign, corr.min_r), 1.0)

        for warning in schema.warnings:
            yield progress(2, t("run.warning_prefix", message=warning), 1.0,
                           level=config.PROGRESS_WARNING)

    if contract.relationships:
        yield progress(2, "  -> " + t("run.schema.relationships_header",
                                      count=len(contract.relationships)), 1.0)
        for rel in contract.relationships:
            bounds = "min %d" % rel.min_per_parent
            if rel.max_per_parent is not None:
                bounds += ", max %d" % rel.max_per_parent
            yield progress(2, "  • " + t("run.schema.relationship",
                                         label=rel.label(),
                                         mean="%.1f" % rel.mean_per_parent,
                                         bounds=bounds,
                                         optional=", " + t("run.schema.optional")
                                         if rel.nullable else ""), 1.0)

    for warning in contract.warnings:
        yield progress(2, t("run.warning_prefix", message=warning), 1.0,
                       level=config.PROGRESS_WARNING)


def _build_llm_client(cfg: PipelineConfig, state: StateManager,
                      job_id: int) -> BaseLLMClient:
    """[1] Servis kontrolü - sağlayıcıyı kurar, erişilemiyorsa anlamlı hata verir."""
    from ..services.cloud_llm_service import create_client

    client = create_client(cfg.provider, cfg.model, state_manager=state, job_id=job_id)
    if not client.health_check():
        raise LLMError(t(
            "run.error.health_check", provider=cfg.provider, model=client.model,
            detail=client.last_health_error or t("run.error.health_hint")))
    return client


# Parametrik kosuda LLM kodu olmadigi icin cikti klasorune bu sablon yazilir.
# Amac dekoratif degil: uretim %100 deterministik oldugundan bu dosya veri setini
# birebir yeniden uretir, yani "kod ciktisi" sozu bos kalmaz.
_PARAMETRIC_CODE_TEMPLATE = '''"""Generated by ParametricEngine - no LLM-written generator code was used.

The Schema Contract is embedded below. Generation is deterministic: running this
file with the same seed reproduces the dataset exactly.

REQUIREMENT: unlike LLM-written generator files, this file imports the
ai_data_studio package, because the engine itself lives there. Make sure the
package is importable before running it:

    pip install -e .                # from the repository root
"""
import json

from ai_data_studio.core.parametric_engine import compile_schema_to_dataframe
from ai_data_studio.core.schema_contract import SchemaContract

SCHEMA = json.loads(r"""
%(schema_json)s
""")


def generate_data(n_rows=%(rows)d, seed=%(seed)d):
    return compile_schema_to_dataframe(SchemaContract.from_dict(SCHEMA),
                                       n_rows=n_rows, seed=seed)


if __name__ == "__main__":
    print(generate_data().head())
'''

_PARAMETRIC_RELATIONAL_CODE_TEMPLATE = '''"""Relational dataset generated by ParametricEngine - no LLM-written generator code was used.

The Dataset Contract is embedded below. Generation is deterministic: running this
file with the same seed reproduces the dataset exactly.

REQUIREMENT: unlike LLM-written generator files, this file imports the
ai_data_studio package, because the engine itself lives there. Make sure the
package is importable before running it:

    pip install -e .                # from the repository root
"""
import json

from ai_data_studio.core.dataset_contract import DatasetContract
from ai_data_studio.core.parametric_engine import compile_dataset_to_dataframes

CONTRACT = json.loads(r"""
%(contract_json)s
""")


def generate_dataset(n_rows=%(rows)d, seed=%(seed)d):
    return compile_dataset_to_dataframes(DatasetContract.from_dict(CONTRACT),
                                         root_rows=n_rows, seed=seed)


if __name__ == "__main__":
    tables = generate_dataset()
    for name, df in tables.items():
        print(f"--- {name} ({len(df)} satır) ---")
        print(df.head())
'''


def _privacy_report_from_dict(pa_data: Dict[str, Any]):
    """Rapordaki sözlüğü tekrar :class:`PrivacyAuditReport` nesnesine çevirir."""
    from .privacy_auditor import DCRResult, HIPAAAuditResult, NNDRResult, PrivacyAuditReport

    dcr_obj = DCRResult(**pa_data["dcr"]) if pa_data.get("dcr") else None
    nndr_obj = NNDRResult(**pa_data["nndr"]) if pa_data.get("nndr") else None
    hipaa_obj = HIPAAAuditResult(
        identifiers_found=pa_data["hipaa"]["identifiers_found"],
        age_greater_than_89_count=pa_data["hipaa"]["age_greater_than_89_count"],
        passed=pa_data["hipaa"]["passed"],
        summary=pa_data["hipaa"]["summary"],
    ) if pa_data.get("hipaa") else HIPAAAuditResult()
    return PrivacyAuditReport(
        has_reference_data=pa_data.get("has_reference_data", False),
        table_name=pa_data.get("table_name", ""),
        dcr=dcr_obj,
        nndr=nndr_obj,
        # Eski kayıtlardaki "empirical_epsilon" farklı (ve yanıltıcı) bir ölçüydü;
        # yeni skor adı altında gösterilmez.
        distribution_divergence=pa_data.get("distribution_divergence"),
        distribution_divergence_columns=pa_data.get("distribution_divergence_columns") or {},
        privacy_guarantee=pa_data.get("privacy_guarantee", ""),
        hipaa_audit=hipaa_obj,
        overall_privacy_status=pa_data.get("overall_privacy_status", "NO_ISSUES_FOUND"),
    )


# --------------------------------------------------------------------------- #
# Cikti yolu guvenligi
# --------------------------------------------------------------------------- #
_STEM_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_stem(value: str, fallback: str = "dataset") -> str:
    """Serbest metni dosya adi parcasina indirger.

    ``contract.domain`` ve tablo adlari LLM yanitindan ya da paylasilan bir
    sema JSON'undan gelir; sema dogrulamasi ikisinin de icerigini sinirlamaz
    (kolon adlarinin aksine). Dogrudan dosya adina girdiklerinde ``../..``
    ile cikti dizininden kacip keyfi dosya yazilmasina izin veriyorlardi -
    ozellikle calistirilabilir ``_generator.py`` dosyasi.
    """
    cleaned = _STEM_SAFE_RE.sub("_", str(value or "")).strip("._-")
    return cleaned[:64] or fallback


def _out_path(out_dir: Path, filename: str) -> Path:
    """``out_dir/filename`` yolunu kurar ve dizin sinirini asmadigini dogrular.

    _safe_stem zaten ayraclari temizliyor; bu, cagiranin onu atlamasi
    durumunda devreye giren ikinci savunma katmani.
    """
    base = Path(out_dir)
    target = base / filename
    resolved_base = base.resolve()
    resolved_target = target.resolve()
    if resolved_target != resolved_base and not resolved_target.is_relative_to(resolved_base):
        raise ValueError(
            "cikti yolu cikti dizininin disina tasiyor: %r" % filename)
    return target


def _write_privacy_reports(report: Dict[str, Any], contract: DatasetContract,
                           out_dir: Path, stem: str, job_id: int) -> Dict[str, str]:
    """Gizlilik denetimi yapılan HER tablo için markdown rapor yazar.

    Tek tabloda dosya adı ve çıktı anahtarı birebir eskisi gibi kalır
    (``job_<id>_<domain>_privacy_report.md`` / ``privacy_report``); ilişkiselde
    tablo başına ``job_<id>_<tablo>_privacy_report.md`` yazılır ve anahtar
    ``privacy_report:<tablo>`` olur.
    """
    written: Dict[str, str] = {}

    # (cikti_anahtari, dosya_govde_adi, denetim_sozlugu)
    targets: List[Tuple[str, str, Dict[str, Any]]] = []
    if not contract.is_relational:
        if report.get("privacy_audit"):
            targets.append(("privacy_report", stem, report["privacy_audit"]))
    else:
        for name in contract.generation_order():
            table_report = (report.get("tables") or {}).get(name) or {}
            if table_report.get("privacy_audit"):
                targets.append(("privacy_report:%s" % name,
                                "job_%d_%s" % (job_id, _safe_stem(name)),
                                table_report["privacy_audit"]))

    for key, file_stem, pa_data in targets:
        try:
            audit_obj = _privacy_report_from_dict(pa_data)
            md_path = _out_path(out_dir, file_stem + "_privacy_report.md")
            config.write_text(md_path, audit_obj.to_markdown())
            written[key] = str(md_path)
        except Exception as exc:
            log.warning("Gizlilik raporu markdown yazılamadı (%s): %s", key, exc)
    return written


def _should_audit(name: str, cfg: PipelineConfig, contract: DatasetContract) -> bool:
    """Bu tablo gizlilik denetiminden geçsin mi?

    ``audit_table`` boşsa yalnız kök tablo denetlenir - eski davranış. ``"all"``
    bütün tabloları, bir tablo adı yalnız o tabloyu denetler.
    """
    if not cfg.audit_privacy:
        return False
    if not cfg.audit_table:
        return name == contract.root_table
    if cfg.audit_table.lower() == "all":
        return True
    return name == cfg.audit_table


def _key_columns(contract: DatasetContract) -> set:
    """Sözleşmedeki bütün anahtar kolon adları (küçük harfe indirgenmiş).

    Birincil anahtarlar ve ilişkilerin iki ucu. Kirlilik enjeksiyonu bunlara
    dokunmamalı: veri, ilişkisel bütünlük denetiminden geçtikten sonra kirletiliyor.
    """
    keys = set()
    for name in contract.table_names:
        primary = getattr(contract.table(name), "primary_key", None)
        if primary:
            keys.add(str(primary).lower())
    for rel in contract.relationships:
        keys.add(str(rel.parent_key).lower())
        keys.add(str(rel.child_key).lower())
    return keys


def _generate_parametric(contract: DatasetContract, cfg: PipelineConfig
                         ) -> Tuple[Dict[str, pd.DataFrame], str, Dict[str, Any]]:
    """[4]+[5] yerine geçen parametrik derleme - LLM kodu yok, sandbox yok.

    Dönüş imzası ``generate_dataset_and_execute`` ile birebir aynıdır; böylece
    çağıran taraf hangi motorun koştuğunu bilmek zorunda kalmaz.
    Tek tablolu ve çok tablolu (ilişkisel) sözleşmelerin ikisini de destekler.
    """
    from .parametric_engine import ParametricEngine

    engine = ParametricEngine(seed=cfg.random_seed)
    started = time.perf_counter()

    if contract.is_relational:
        raw_tables = engine.compile_relational(contract, root_rows=cfg.row_count, seed=cfg.random_seed)
        duration = time.perf_counter() - started
        code = _PARAMETRIC_RELATIONAL_CODE_TEMPLATE % {
            "contract_json": json.dumps(contract.to_dict(), ensure_ascii=False, indent=2),
            "rows": cfg.row_count,
            "seed": cfg.random_seed,
        }
    else:
        schema = contract.table(contract.root_table)
        df = engine.compile(schema, n_rows=cfg.row_count, seed=cfg.random_seed)
        duration = time.perf_counter() - started
        code = _PARAMETRIC_CODE_TEMPLATE % {
            "schema_json": json.dumps(schema.to_dict(), ensure_ascii=False, indent=2),
            "rows": cfg.row_count,
            "seed": cfg.random_seed,
        }
        raw_tables = {contract.root_table: df}

    total_rows = sum(len(df) for df in raw_tables.values())
    total_cols = sum(len(df.columns) for df in raw_tables.values())
    meta: Dict[str, Any] = {
        "attempts": 1,
        "duration_s": round(duration, 4),
        "engine": ENGINE_PARAMETRIC,
        "rows": total_rows,
        "columns": total_cols,
        "is_relational": contract.is_relational,
        "row_counts": {name: len(df) for name, df in raw_tables.items()},
    }
    log.info("Parametrik motor: %s, %.3f sn",
             ", ".join(f"{name}={len(df)}" for name, df in raw_tables.items()),
             duration)
    return raw_tables, code, meta


def _fetch_seed_data(cfg: PipelineConfig):
    """[3] HuggingFace seed veri. Başarısız olursa pipeline'i kırmaz, None döner."""
    from ..services import hf_service

    try:
        dataset_id = cfg.hf_seed_dataset
        if not dataset_id:
            query = cfg.hf_seed_query or cfg.domain_prompt
            results = hf_service.search_datasets(query, limit=5)
            if not results:
                return None, ""
            dataset_id = results[0]["id"]
        df = hf_service.load_seed_dataframe(dataset_id, max_rows=2000)
        return df, dataset_id
    except Exception as exc:
        log.warning("Seed veri alınamadı: %s", exc)
        return None, ""


def _write_raw_tables(tables: Dict[str, pd.DataFrame], contract: DatasetContract,
                     job_id: int) -> Dict[str, str]:
    """[5] Ham (temizlenmemis) tablolari diske yazar. Tablo adi -> dosya yolu."""
    paths: Dict[str, str] = {}
    for name, df in tables.items():
        # Tek tabloda eski dosya adi korunur; cok tabloda tablo adi eklenir.
        stem = ("job_%d_raw" % job_id if not contract.is_relational
                else "job_%d_%s_raw" % (job_id, _safe_stem(name)))
        target = config.RAW_DIR / (stem + ".parquet")
        try:
            df.to_parquet(target, index=False)
        except Exception as exc:
            log.warning("Ham veri parquet olarak kaydedilemedi (%s): %s", name, exc)
            target = config.RAW_DIR / (stem + ".csv")
            df.to_csv(target, index=False, encoding="utf-8")
        paths[name] = str(target)
    return paths


# --------------------------------------------------------------------------- #
# Provenance metadata helpers (EU AI Act Art. 50 / GDPR / HIPAA)
# --------------------------------------------------------------------------- #
_PROVENANCE_TEXT = (
    "100% Synthetic Data - Non-PII - Generated Locally by AI Synthetic Data Studio. "
    "This dataset contains no real personal identifiable information."
)
_PROVENANCE_COMPLIANCE = "EU AI Act Art. 50 / Non-Personal Data"
_PROVENANCE_GENERATOR = "ai-data-studio"


def _write_csv_with_provenance(df: pd.DataFrame, path: Path) -> None:
    """CSV dosyasinin basina provenance yorum satiri ekler.

    ``pd.read_csv(..., comment='#')`` ile okunabilir; standart araclar
    yorum satirini otomatik atlar.
    """
    import io
    buf = io.StringIO()
    buf.write("# PROVENANCE: %s\n" % _PROVENANCE_TEXT)
    buf.write("# COMPLIANCE: %s\n" % _PROVENANCE_COMPLIANCE)
    df.to_csv(buf, index=False, encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(buf.getvalue(), encoding="utf-8")


def _write_parquet_with_provenance(df: pd.DataFrame, path: Path) -> None:
    """Parquet dosyasina schema metadata olarak provenance ekler.

    Kolon yapisi bozulmaz; ``pd.read_parquet()`` normal okur.
    Metadata ``pq.read_schema(path).metadata`` ile gorulebilir.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pandas(df)
    existing_meta = table.schema.metadata or {}
    provenance_meta = {
        b"provenance": _PROVENANCE_TEXT.encode("utf-8"),
        b"compliance": _PROVENANCE_COMPLIANCE.encode("utf-8"),
        b"generator": _PROVENANCE_GENERATOR.encode("utf-8"),
    }
    merged = {**existing_meta, **provenance_meta}
    table = table.replace_schema_metadata(merged)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(path))


def _write_json_with_provenance(df: pd.DataFrame, path: Path) -> None:
    """JSON dosyasina ust duzey ``_provenance`` anahtari ekler."""
    import json as _json
    records = _json.loads(df.to_json(orient="records", force_ascii=False))
    output = {
        "_provenance": {
            "notice": _PROVENANCE_TEXT,
            "compliance": _PROVENANCE_COMPLIANCE,
            "generator": _PROVENANCE_GENERATOR,
        },
        "data": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_table_files(df: pd.DataFrame, out_dir: Path, stem: str,
                       formats: List[str],
                       provenance: bool = False) -> Dict[str, str]:
    """Bir tablonun veri dosyalarini istenen formatlarda yazar.

    *provenance* True ise dosyalara yasal serh eklenir:
      - CSV: dosya basina ``# PROVENANCE: ...`` yorum satiri
      - Parquet: schema metadata (``provenance``, ``compliance``, ``generator``)
      - JSON: ust duzey ``_provenance`` anahtari
    """
    written: Dict[str, str] = {}
    if "csv" in formats:
        target = _out_path(out_dir, stem + ".csv")
        if provenance:
            _write_csv_with_provenance(df, target)
        else:
            df.to_csv(target, index=False, encoding="utf-8")
        written["csv"] = str(target)
    if "parquet" in formats:
        target = _out_path(out_dir, stem + ".parquet")
        try:
            if provenance:
                _write_parquet_with_provenance(df, target)
            else:
                df.to_parquet(target, index=False)
            written["parquet"] = str(target)
        except Exception as exc:
            log.warning("Parquet yazılamadı (pyarrow eksik olabilir): %s", exc)
    if "json" in formats:
        target = _out_path(out_dir, stem + ".json")
        if provenance:
            _write_json_with_provenance(df, target)
        else:
            df.to_json(target, orient="records", force_ascii=False, indent=2)
        written["json"] = str(target)
    return written


def _write_outputs(tables: Dict[str, pd.DataFrame], contract: DatasetContract,
                   report: Dict[str, Any], code: str, job_id: int,
                   cfg: PipelineConfig,
                   plan: Optional[ProjectPlan] = None) -> Dict[str, str]:
    """[7] Temiz veri + şema + kod + rapor dosyalarını yazar (hepsi UTF-8).

    Tek tabloda dosya adlari eskisiyle birebir ayni kalir. Iliskiselde her tablo
    ``job_<id>_<tablo>.<format>`` olarak yazilir, uzerine bir ``manifest.json``
    eklenir; manifest hangi dosyanin hangi tabloya ait oldugunu ve iliski semasini
    tasir. Cikti anahtarlari da o zaman ``csv:orders`` bicimini alir.
    """
    out_dir = Path(cfg.output_dir or config.OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    schema = contract.table(contract.root_table)
    stem = "job_%d_%s" % (job_id, _safe_stem(contract.domain))
    paths: Dict[str, str] = {}

    formats = [f.lower() for f in (cfg.export_formats or ["csv"])]
    if contract.is_relational:
        table_files: Dict[str, Dict[str, str]] = {}
        for name in contract.generation_order():
            written = _write_table_files(tables[name], out_dir,
                                         "job_%d_%s" % (job_id, _safe_stem(name)), formats,
                                         provenance=cfg.provenance_header)
            table_files[name] = written
            for kind, path in written.items():
                paths["%s:%s" % (kind, name)] = path
    else:
        table_files = {}
        paths.update(_write_table_files(tables[contract.root_table], out_dir, stem, formats,
                                        provenance=cfg.provenance_header))

    schema_json = contract.to_json() if contract.is_relational else schema.to_json()
    schema_path = _out_path(out_dir, stem + "_schema.json")
    config.write_text(schema_path, schema_json)
    paths["schema"] = str(schema_path)

    code_path = _out_path(out_dir, stem + "_generator.py")
    config.write_text(code_path, code)
    paths["code"] = str(code_path)

    report_path = _out_path(out_dir, stem + "_report.json")
    config.write_json(report_path, report)
    paths["report"] = str(report_path)

    if plan is not None:
        # Plan sozlesmeden ayri yazilir: hedef, sinif dengesi, ayiklanan sizinti
        # kolonlari ve bolme stratejisi veri setiyle birlikte tasinmali.
        plan_path = _out_path(out_dir, stem + "_plan.json")
        config.write_text(plan_path, plan.to_json())
        paths["plan"] = str(plan_path)

    paths.update(_write_privacy_reports(report, contract, out_dir, stem, job_id))

    if cfg.export_pdf or "pdf" in formats:
        from ..reporting import generate_pdf_report, is_pdf_available
        if is_pdf_available():
            pdf_path = _out_path(out_dir, stem + "_audit_report.pdf")
            try:
                generate_pdf_report(
                    dataframe=tables[contract.root_table],
                    schema=schema,
                    report=report,
                    output_path=pdf_path,
                    job_id=job_id,
                    domain=contract.domain,
                    enforce_pro=True,
                )
                paths["pdf"] = str(pdf_path)
            except Exception as exc:
                log.warning("PDF denetim raporu üretilemedi: %s", exc)

    if contract.is_relational:
        manifest_path = _out_path(out_dir, stem + "_manifest.json")
        config.write_json(manifest_path,
                          _build_manifest(tables, contract, report, job_id,
                                          table_files, paths))
        paths["manifest"] = str(manifest_path)

    return paths


def _build_manifest(tables: Dict[str, pd.DataFrame], contract: DatasetContract,
                    report: Dict[str, Any], job_id: int,
                    table_files: Dict[str, Dict[str, str]],
                    paths: Dict[str, str]) -> Dict[str, Any]:
    """Iliskisel ciktinin dizin dosyasi: hangi dosya hangi tablo, iliskiler nasil."""
    relational = report.get("relational") or {}
    return {
        "job_id": job_id,
        "domain": contract.domain,
        "root_table": contract.root_table,
        "random_seed": contract.random_seed,
        "generation_order": contract.generation_order(),
        "tables": {
            name: {
                "rows": int(len(tables[name])),
                "primary_key": contract.table(name).primary_key,
                "foreign_keys": list(contract.table(name).foreign_keys),
                "columns": [c.name for c in contract.table(name).columns],
                "files": table_files.get(name, {}),
                "retention_pct": (report.get("tables", {}).get(name, {}) or {}).get("retention_pct"),
            }
            for name in contract.generation_order()
        },
        "relationships": [r.to_dict() for r in contract.relationships],
        "integrity": {
            "pass": relational.get("pass"),
            "repair_enabled": relational.get("repair_enabled"),
            "orphans_removed": (relational.get("repair") or {}).get("removed_total", 0),
            "foreign_keys": relational.get("foreign_keys", []),
            "cardinality": relational.get("cardinality", []),
            "primary_keys": relational.get("primary_keys", []),
        },
        "files": {k: v for k, v in paths.items()
                  if k in ("schema", "code", "report", "plan")
                  or k.split(":", 1)[0] == "privacy_report"},
    }


def _push_to_hub(df: pd.DataFrame, schema: SchemaContract, report: Dict[str, Any],
                 llm_client: BaseLLMClient, cfg: PipelineConfig,
                 contract: Optional[DatasetContract] = None) -> str:
    from ..services import hf_service
    return hf_service.push_dataset(
        df, cfg.push_to_hub, schema, report=report, llm_client=llm_client,
        private=cfg.hub_private, contract=contract,
    )


def _report_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    """UI'a gönderilecek hafif rapor özeti (tam rapor çok büyük olabilir)."""
    summary = {
        "rows_in": report.get("rows_in"),
        "rows_out": report.get("rows_out"),
        "retention_pct": report.get("retention_pct"),
        "stages": [{k: s[k] for k in ("stage", "rows_before", "rows_after", "removed")}
                   for s in report.get("stages", [])],
        "correlations": report.get("correlations", []),
        "distributions": {k: v for k, v in (report.get("distributions") or {}).items()
                          if k != "columns"},
    }
    if report.get("engines"):
        summary["engines"] = report["engines"]
    relational = report.get("relational")
    if relational:
        summary["relational"] = {
            "pass": relational.get("pass"),
            "row_counts": relational.get("row_counts", {}),
            "orphans_removed": (relational.get("repair") or {}).get("removed_total", 0),
            "foreign_keys": relational.get("foreign_keys", []),
            "cardinality": relational.get("cardinality", []),
        }
    return summary


# --------------------------------------------------------------------------- #
# GUI worker (Bolum 6.6)
# --------------------------------------------------------------------------- #
class PipelineWorker(threading.Thread):
    """Ağır işi arka planda koşturur, UI ile yalnızca queue üzerinden konuşur.

    CustomTkinter thread-safe değildir: bu thread hiçbir widget'a dokunmaz.
    Ana thread `after()` ile ui_queue'yu okur (bkz. gui/app_window.py).
    """

    def __init__(self, task_fn: Callable[[threading.Event], Iterator[Dict[str, Any]]],
                 ui_queue: "queue.Queue", cancel_event: threading.Event):
        super().__init__(daemon=True, name="pipeline-worker")
        self.task_fn = task_fn
        self.ui_queue = ui_queue
        self.cancel_event = cancel_event

    def run(self) -> None:
        try:
            iterator = self.task_fn(self.cancel_event)
            while True:
                if self.cancel_event.is_set():
                    iterator.close()
                    self.ui_queue.put(("cancelled", None))
                    return
                try:
                    progress = next(iterator)
                except StopIteration as stop:
                    self.ui_queue.put(("done", stop.value))
                    return
                self.ui_queue.put(("progress", progress))
        except PipelineCancelled:
            self.ui_queue.put(("cancelled", None))
        except Exception as exc:
            log.exception("Pipeline worker hatası")
            self.ui_queue.put(("error", str(exc)))


# --------------------------------------------------------------------------- #
# CLI Giriş Noktası
# --------------------------------------------------------------------------- #
def _help(key: str) -> str:
    """argparse yardım metni.

    argparse yardım metinlerine %-biçimlendirme uygular (ornegin %(default)s).
    Çeviri metnindeki düz bir yüzde işareti bu yüzden çift yazılmalı; kaçışı
    kataloğa sızdırmak yerine burada yapıyoruz - çevirmen argparse bilmek
    zorunda değil.
    """
    return t(key).replace("%", "%%")


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m ai_data_studio.core.orchestrator",
        description=t("cli.help.description"),
    )
    p.add_argument("--domain", help=_help("cli.help.domain"))
    p.add_argument("--project",
                   help=_help("cli.help.project"))
    p.add_argument("--check-auth", action="store_true",
                   help=_help("cli.help.check_auth"))
    p.add_argument("--provider", default=config.PROVIDER_ANTHROPIC,
                   choices=[config.PROVIDER_ANTHROPIC, config.PROVIDER_GEMINI,
                            config.PROVIDER_OLLAMA])
    p.add_argument("--model", default=None, help=_help("cli.help.model"))
    p.add_argument("--rows", type=int, default=config.DEFAULT_ROW_TARGET)
    p.add_argument("--seed", type=int, default=config.DEFAULT_RANDOM_SEED)
    p.add_argument("--locale", default="en_US", help=_help("cli.help.locale"))
    p.add_argument("--hf-seed", action="store_true", help=_help("cli.help.hf_seed"))
    p.add_argument("--hf-dataset", default="", help=_help("cli.help.hf_dataset"))
    p.add_argument("--web-seed", action="store_true", help=_help("cli.help.web_seed"))
    p.add_argument("--web-query", default="", help=_help("cli.help.web_query"))
    p.add_argument("--formats", default="csv,parquet", help=_help("cli.help.formats"))
    p.add_argument("--provenance", action="store_true",
                   help=_help("cli.help.provenance"))
    p.add_argument("--export-pdf", action="store_true",
                   help=_help("cli.help.export_pdf"))
    p.add_argument("--output-dir", default=None)
    p.add_argument("--push-to-hub", default="", help=_help("cli.help.push_to_hub"))
    p.add_argument("--public", action="store_true", help=_help("cli.help.public"))
    p.add_argument("--timeout", type=int, default=config.SANDBOX_TIMEOUT_S)
    p.add_argument("--max-retries", type=int, default=config.MAX_CODEGEN_RETRIES)
    p.add_argument("--contamination", type=float, default=validator.DEFAULT_CONTAMINATION,
                   help=_help("cli.help.contamination"))
    p.add_argument("--no-correlation-guard", action="store_true",
                   help=_help("cli.help.no_correlation_guard"))
    p.add_argument("--z-threshold", type=float, default=validator.DEFAULT_Z_THRESHOLD)
    p.add_argument("--preserve-anomaly-col", default=None,
                   help=_help("cli.help.preserve_col"))
    p.add_argument("--preserve-anomaly-val", default=None,
                   help=_help("cli.help.preserve_val"))
    p.add_argument("--inject-fraud", action="store_true",
                   help=_help("cli.help.inject_fraud"))
    p.add_argument("--fraud-rate", type=float, default=0.005,
                   help=_help("cli.help.fraud_rate"))
    p.add_argument("--fraud-target-col", default="is_fraud",
                   help=_help("cli.help.fraud_target_col"))
    p.add_argument("--audit-privacy", action="store_true",
                   help=_help("cli.help.audit_privacy"))
    p.add_argument("--fraud-table", default="",
                   help=_help("cli.help.fraud_table"))
    p.add_argument("--audit-table", default="",
                   help=_help("cli.help.audit_table"))
    p.add_argument("--gemini-backend", default=None,
                   choices=[config.GEMINI_BACKEND_AISTUDIO, config.GEMINI_BACKEND_CLI],
                   help=_help("cli.help.gemini_backend"))
    p.add_argument("--relational", action="store_true",
                   help=_help("cli.help.relational"))
    p.add_argument("--max-tables", type=int, default=6,
                   help=_help("cli.help.max_tables"))
    p.add_argument("--no-repair-orphans", action="store_true",
                   help=_help("cli.help.no_repair_orphans"))
    # --- Uretim ve zenginlestirme motorlari ---------------------------- #
    p.add_argument("--engine", default=ENGINE_LLM, choices=list(ENGINES),
                   help=_help("cli.help.engine"))
    p.add_argument("--time-series", action="store_true",
                   help=_help("cli.help.time_series"))
    p.add_argument("--ts-timestamp-col", default="transaction_timestamp",
                   help=_help("cli.help.ts_timestamp_col"))
    p.add_argument("--ts-entity-col", default="customer_id",
                   help=_help("cli.help.ts_entity_col"))
    p.add_argument("--ts-start", default="", help=_help("cli.help.ts_start"))
    p.add_argument("--ts-end", default="", help=_help("cli.help.ts_end"))
    p.add_argument("--ts-table", default="", help=_help("cli.help.ts_table"))
    p.add_argument("--expand-features", action="store_true",
                   help=_help("cli.help.expand_features"))
    p.add_argument("--expand-table", default="", help=_help("cli.help.expand_table"))
    p.add_argument("--dirty-rate", type=float, default=0.0,
                   help=_help("cli.help.dirty_rate"))
    p.add_argument("--dirty-table", default="", help=_help("cli.help.dirty_table"))
    p.add_argument("--agentic", action="store_true",
                   help=_help("cli.help.agentic"))
    p.add_argument("--max-agent-rounds", type=int, default=2,
                   help=_help("cli.help.max_agent_rounds"))
    p.add_argument("--hardware", action="store_true",
                   help=_help("cli.help.hardware"))
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def check_auth() -> int:
    """Her sağlayıcı için kimliğin nereden çözüldüğünü yazdırır."""
    print(t("cli.auth.header"))
    print("-" * 72)
    ok_any = False
    for provider in (config.PROVIDER_ANTHROPIC, config.PROVIDER_GEMINI, "huggingface"):
        status = config.credential_status(provider)
        if status["explicit"]:
            mark = "[OK]  "
            note = t("cli.auth.source", source=status["source"])
            ok_any = True
        elif status["configured"]:
            mark = "[?]   "
            note = t("cli.auth.implicit", source=status["source"])
            ok_any = True
        else:
            mark = "[--]  "
            note = t("cli.auth.checked",
                     vars=", ".join(status["checked_env_vars"]))
        print("%s%-12s %s" % (mark, provider, note))

        oauth = config.oauth_status(provider)
        if oauth["supported"]:
            if oauth["logged_in"]:
                print("        " + t("cli.auth.oauth_logged_in",
                                        detail=oauth["detail"]))
            elif not config.cli_available(oauth["command"][0]):
                print("        " + t("cli.auth.oauth_missing",
                                        command=oauth["command"][0],
                                        hint=oauth["install_hint"]))
            else:
                print("        " + t("cli.auth.oauth_login",
                                        command=" ".join(oauth["command"])))
            if oauth["note"]:
                print("        " + t("cli.auth.note", note=oauth["note"]))

    from ..services import ollama_service
    if ollama_service.is_available():
        models = ollama_service.list_model_names()
        print("[OK]  %-12s %s" % (config.PROVIDER_OLLAMA, t(
            "cli.auth.ollama_running",
            version=ollama_service.get_version() or "?", count=len(models))))
        ok_any = True
    else:
        print("[--]  %-12s %s" % (config.PROVIDER_OLLAMA,
                                    t("cli.auth.ollama_down", host=config.OLLAMA_HOST)))

    print("-" * 72)
    if not ok_any:
        print(t("cli.auth.none_available"))
        print("  " + t("cli.auth.none_hint"))
        print("    $env:ANTHROPIC_API_KEY = \"sk-ant-...\"")
        print("    $env:GEMINI_API_KEY    = \"...\"")
        print("    ollama serve")
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    # Turkce yardim/hata metinleri cp437 gibi konsollarda cokmesin diye
    # argparse devreye girmeden once stdio'yu UTF-8'e sabitle.
    config.force_utf8_stdio()
    args = _build_arg_parser().parse_args(argv)
    config.setup_logging(logging.DEBUG if args.verbose else logging.WARNING)

    # Arka uc secimi surec-yerel: settings.json'a yazmadan yalnizca bu kosuyu etkiler.
    if args.gemini_backend:
        os.environ[config.GEMINI_BACKEND_ENV] = args.gemini_backend

    if args.check_auth:
        return check_auth()
    if args.hardware:
        from .hardware_profiler import format_hardware_report
        print(format_hardware_report())
        return 0
    if args.domain and args.project:
        print(t("cli.error.domain_and_project"), file=sys.stderr)
        return 2
    if not args.domain and not args.project:
        print(t("cli.error.domain_or_project"), file=sys.stderr)
        return 2

    cfg = PipelineConfig(
        domain_prompt=args.domain or args.project,
        project_prompt=args.project or "",
        provider=args.provider,
        model=args.model,
        row_count=args.rows,
        random_seed=args.seed,
        faker_locale=args.locale,
        use_hf_seed=args.hf_seed or bool(args.hf_dataset),
        hf_seed_dataset=args.hf_dataset,
        use_web_seed=args.web_seed or bool(args.web_query),
        web_seed_query=args.web_query,
        export_formats=[f.strip() for f in args.formats.split(",") if f.strip()],
        provenance_header=args.provenance,
        export_pdf=args.export_pdf,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        push_to_hub=args.push_to_hub,
        hub_private=not args.public,
        sandbox_timeout=args.timeout,
        max_retries=args.max_retries,
        contamination=args.contamination,
        z_threshold=args.z_threshold,
        correlation_guard=not args.no_correlation_guard,
        preserve_anomaly_column=args.preserve_anomaly_col,
        preserve_anomaly_value=args.preserve_anomaly_val,
        inject_fraud=args.inject_fraud,
        fraud_rate=args.fraud_rate,
        fraud_target_column=args.fraud_target_col,
        fraud_table=args.fraud_table,
        audit_privacy=args.audit_privacy,
        audit_table=args.audit_table,
        relational=args.relational,
        max_tables=args.max_tables,
        repair_orphans=not args.no_repair_orphans,
        engine=args.engine,
        time_series=args.time_series,
        ts_timestamp_column=args.ts_timestamp_col,
        ts_entity_column=args.ts_entity_col,
        ts_start_date=args.ts_start,
        ts_end_date=args.ts_end,
        ts_table=args.ts_table,
        expand_features=args.expand_features,
        expand_table=args.expand_table,
        dirty_rate=args.dirty_rate,
        dirty_table=args.dirty_table,
        agentic=args.agentic,
        max_agent_rounds=args.max_agent_rounds,
    )

    state = get_state_manager()
    state.mark_stale_jobs_interrupted()
    cancel_event = threading.Event()

    print("AI Synthetic Data Studio")
    print("%-10s: %s" % (t("cli.label.project") if cfg.project_prompt
                         else t("cli.label.domain"), cfg.domain_prompt))
    backend_note = ""
    if cfg.provider == config.PROVIDER_GEMINI:
        backend_note = " " + t("cli.label.backend", backend=config.gemini_backend())
    print("%-10s: %s / %s%s" % (t("cli.label.provider"), cfg.provider,
                                cfg.resolved_model(), backend_note))
    print("%-10s: %s" % (t("cli.label.target"),
                         t("cli.label.target_value",
                           rows=format(cfg.row_count, ","), seed=cfg.random_seed)))
    if cfg.project_prompt:
        print("%-10s: %s" % (t("cli.label.mode"),
                             t("cli.mode.planner", limit=cfg.max_tables)))
    elif cfg.relational:
        print("%-10s: %s" % (t("cli.label.mode"), t(
            "cli.mode.relational", limit=cfg.max_tables,
            repair=t("cli.on") if cfg.repair_orphans else t("cli.off"))))
    engine_extras = []
    if cfg.time_series:
        engine_extras.append(t("cli.engine.time_series"))
    if cfg.expand_features:
        engine_extras.append(t("cli.engine.expand_features"))
    if cfg.dirty_rate > 0:
        engine_extras.append(t("cli.engine.dirty",
                                pct="%.1f" % (cfg.dirty_rate * 100)))
    if cfg.engine != ENGINE_LLM or engine_extras:
        print("%-10s: %s%s" % (t("cli.label.engine"), cfg.engine,
                               (" + " + ", ".join(engine_extras)) if engine_extras else ""))
    print("-" * 72)

    def print_llm_progress(message: str) -> None:
        # Cagri suruyorken basiliyor; yuzde/adim numarasi yok cunku adim degismedi.
        print("           %s" % message, flush=True)

    iterator = run_pipeline(cfg, cancel_event, state,
                            llm_progress_cb=print_llm_progress)
    result: Optional[PipelineResult] = None
    try:
        while True:
            try:
                event = next(iterator)
            except StopIteration as stop:
                result = stop.value
                break
            msg = event["message"]
            if msg.startswith("  ") or msg.startswith("•"):
                print("           %s" % msg.strip())
            else:
                print("[%d/%d] %5.1f%% | %s" % (event["step"], event["total_steps"],
                                                event["percent"], msg))
    except KeyboardInterrupt:
        cancel_event.set()
        iterator.close()
        print("\n" + t("cli.cancelled"))
        return 130
    except PipelineCancelled as exc:
        print("\n" + t("cli.cancelled_with", reason=exc))
        return 130
    except Exception as exc:
        print("\n" + t("cli.error.generic", error=exc), file=sys.stderr)
        return 1

    if result is None:
        print(t("app.error.no_result"), file=sys.stderr)
        return 1

    print("-" * 72)
    print(t("cli.summary.job_done", job_id=result.job_id))
    print("%-12s: %s" % (t("cli.summary.clean_rows"), t(
        "cli.summary.clean_rows_value",
        rows_out=format(result.report["rows_out"], ","),
        rows_in=format(result.report["rows_in"], ","),
        retention="%.1f" % result.report["retention_pct"])))
    tot_tokens = result.cost.get("input_tokens", 0) + result.cost.get("output_tokens", 0)
    print("%-12s: %s" % (t("cli.summary.cost"), t(
        "app.done.cost", cost="%.4f" % result.cost.get("cost_usd", 0.0),
        calls=result.cost.get("calls", 0), tokens=format(tot_tokens, ","))))
    print(t("cli.summary.outputs"))
    for kind, path in sorted(result.output_paths.items()):
        try:
            sz = Path(path).stat().st_size
            sz_str = ("%.1f KB" % (sz / 1024)) if sz < 1024 * 1024 else ("%.2f MB" % (sz / (1024 * 1024)))
            print("  %-8s %s (%s)" % (kind, path, sz_str))
        except Exception:
            print("  %-8s %s" % (kind, path))
    if result.hub_url:
        print("HuggingFace : %s" % result.hub_url)

    if result.plan is not None:
        plan = result.plan
        print("-" * 72)
        print(t("cli.summary.plan", summary=plan.summary()))
        if plan.target is not None:
            print("  %-18s: %s" % (t("result.plan.target"), plan.target.label()))
        if plan.positive_class_ratio is not None:
            print("  %-18s: %s" % (t("result.plan.class_balance"), t(
                "result.plan.positive_pct",
                pct="%.1f" % (plan.positive_class_ratio * 100))))
        if plan.split is not None:
            print("  %-18s: %s%s" % (t("result.plan.split"),
                plan.split.kind,
                (" (%s.%s)" % (plan.split.table, plan.split.column)) if plan.split.column else ""))
        for excl in plan.excluded_leakage:
            print("  %-18s: %s - %s" % (t("result.plan.leakage"),
                                          excl.column, excl.reason))

    rel = result.report.get("relational")
    if rel:
        print("-" * 72)
        print("%s: %s" % (t("result.section.relational"),
                          t("history.verdict.pass") if rel.get("pass")
                          else t("result.relational.failed")))
        for name, count in sorted((rel.get("row_counts") or {}).items()):
            print("  %-24s %s" % (name, t("result.rows_value",
                                          rows=format(count, ","))))
        for fk in rel.get("foreign_keys", []):
            print("  " + t("result.relational.fk",
                           relationship=fk.get("relationship", "?"),
                           orphans=format(fk.get("orphan_rows", 0), ","),
                           pct="%.2f" % fk.get("orphan_pct", 0.0), verdict=""))
        for card in rel.get("cardinality", []):
            print("  " + t("result.relational.cardinality",
                           relationship=card.get("relationship", "?"),
                           observed="%.2f" % card.get("observed_mean", 0.0),
                           expected="%.2f" % card.get("expected_mean", 0.0),
                           verdict="" if card.get("pass")
                           else "<-- " + t("result.relational.deviation")))
        removed = (rel.get("repair") or {}).get("removed_total", 0)
        if removed:
            print("  %s: %s" % (t("result.relational.orphans_removed"),
                                format(removed, ",")))
        # CI kapisi: yetim FK ya da tekil olmayan PK gercek bir butunluk ihlalidir,
        # cikis kodu 3 olur. Kardinalite sapmasi istatistikseldir - uyarilir ama
        # tek basina kosuyu dusurmez, aksi halde --no-repair-orphans'siz normal
        # kosular rastgele basarisiz gorunurdu.
        broken = ([r for r in rel.get("primary_keys", []) if not r.get("pass")]
                  + [r for r in rel.get("foreign_keys", []) if not r.get("pass")])
        if broken:
            print(t("cli.relational.integrity_failed", count=len(broken)),
                  file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
