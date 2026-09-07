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
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import pandas as pd

from .. import config
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
    1: "Servis kontrolü",
    2: "Araştırma & şema üretimi",
    3: "Seed veri arama (HuggingFace)",
    4: "Kod üretimi & self-healing",
    5: "Sandbox çalıştırma",
    6: "Validasyon & ayıklama",
    7: "Çıktı & durum kaydı",
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
    audit_privacy: bool = False
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
    # "parametric" ve "auto"nun parametrik yolu SU AN TEK TABLOLUDUR: sozlesmeyi
    # dogrudan derler, yabanci anahtar tutarliligini kuramaz. Iliskisel kosuda
    # bu yuzden acik hata verilir, sessizce LLM'e donulmez.
    engine: str = ENGINE_LLM
    # --- [5.5] Uretim sonrasi, DOGRULAMA ONCESI zenginlestiriciler ----- #
    time_series: bool = False
    ts_timestamp_column: str = "transaction_timestamp"
    ts_entity_column: str = "customer_id"
    ts_start_date: str = ""        # bos -> TimeSeriesConfig varsayilani
    ts_end_date: str = ""
    expand_features: bool = False
    # --- [6.5] DOGRULAMA SONRASI kirli veri enjeksiyonu ---------------- #
    # 0 ise kapali. Sira bilincli: kirli veri doğrulamadan once enjekte edilirse
    # sema sinirlari / kategori denetimi tam da enjekte edilen satirlari eler.
    dirty_rate: float = 0.0

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
        raise ValueError("Bilinmeyen üretim motoru: %r (geçerli: %s)"
                         % (cfg.engine, ", ".join(ENGINES)))
    if engine_choice == ENGINE_PARAMETRIC and cfg.relational:
        raise ValueError(
            "Parametrik motor ilişkisel (çok tablolu) üretimi desteklemiyor. "
            "--relational ile --engine llm kullanın ya da --engine parametric için "
            "--relational'ı kaldırın."
        )
    if not 0.0 <= cfg.dirty_rate <= 1.0:
        raise ValueError("dirty_rate 0 ile 1 arasında olmalı, %r verildi" % cfg.dirty_rate)

    def check_cancel() -> None:
        if cancel_event.is_set():
            raise PipelineCancelled("Pipeline kullanıcı tarafından iptal edildi")

    # Yuzde asla geri gitmez. Iki yerde geri sarabiliyordu: seed verisi (adim 3)
    # semadan (adim 2) ONCE cekiliyor, ve self-healing yeniden denemesi sandbox'tan
    # (5) kod uretimine (4) donuyor. Ikisi de dogru davranis; geri saran bir
    # ilerleme cubugu ise kullaniciya hata gibi gorunuyordu. Adim numarasi spec'teki
    # kanonik numaradir ve oldugu gibi birakilir - yalnizca yuzde tek yone akar.
    furthest_percent = [0.0]

    def progress(step: int, message: str, fraction: float = 0.0,
                 **detail: Any) -> Dict[str, Any]:
        """Adım içi ilerleme (fraction 0..1) dahil yüzde hesaplar."""
        percent = round(((step - 1) + min(max(fraction, 0.0), 1.0)) / TOTAL_STEPS * 100, 1)
        percent = max(percent, furthest_percent[0])
        furthest_percent[0] = percent
        return {
            "step": step,
            "total_steps": TOTAL_STEPS,
            "name": STEP_NAMES[step],
            "message": message,
            "percent": percent,
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
        yield progress(1, "Sağlayıcı kontrol ediliyor: %s / %s"
                       % (cfg.provider, cfg.resolved_model()))
        if llm_client is None:
            llm_client = _build_llm_client(cfg, state, job_id)
        if llm_progress_cb is not None:
            llm_client.progress_cb = llm_progress_cb
        yield progress(1, "Servis hazır: %s" % llm_client.model, 1.0)
        yield progress(1, "  -> Sağlayıcı: %s | Model: %s" % (cfg.provider, llm_client.model), 1.0)

        # ---------------------------------------------------------------- #
        # [3'] Seed veri - semadan ONCE cekilir ki sema onu referans alabilsin
        # ---------------------------------------------------------------- #
        seed_df: Optional[pd.DataFrame] = None
        seed_source = ""
        if cfg.use_hf_seed:
            check_cancel()
            yield progress(3, "HuggingFace'te referans veri aranıyor...")
            seed_df, seed_source = _fetch_seed_data(cfg)
            if seed_df is not None:
                state.save_checkpoint(job_id, seed_data_path=seed_source)
                yield progress(3, "Seed veri yüklendi: %s (%s satır)"
                               % (seed_source, format(len(seed_df), ",")), 1.0)
                cols_preview = ", ".join(list(seed_df.columns)[:5])
                if len(seed_df.columns) > 5:
                    cols_preview += "..."
                yield progress(3, "  -> Referans sütunlar (%d adet): %s" % (len(seed_df.columns), cols_preview), 1.0)
            else:
                yield progress(3, "Uygun seed veri bulunamadı - şema sıfırdan üretilecek", 1.0)
        elif getattr(cfg, "use_web_seed", False):
            check_cancel()
            web_q = cfg.web_seed_query or cfg.domain_prompt
            yield progress(3, "Web'de referans veri aranıyor ve toplanıyor: '%s'..." % web_q[:50])
            from ..services import web_collector
            seed_df, seed_source = web_collector.collect_web_seed(web_q, cfg.domain_prompt, llm_client)
            if seed_df is not None and not seed_df.empty:
                state.save_checkpoint(job_id, seed_data_path="web:" + seed_source)
                yield progress(3, "Web'den referans veri toplandı: %s (%d satır, %d sütun)"
                               % (seed_source, len(seed_df), len(seed_df.columns)), 1.0)
                cols_preview = ", ".join(list(seed_df.columns)[:5])
                if len(seed_df.columns) > 5:
                    cols_preview += "..."
                yield progress(3, "  -> Çıkarılan referans kolonlar: %s" % cols_preview, 1.0)
            else:
                yield progress(3, "Web'den uygun veri çıkarılamadı - şema sıfırdan üretilecek", 1.0)
        else:
            yield progress(3, "Seed veri kullanılmıyor (atlandı)", 1.0)

        # ---------------------------------------------------------------- #
        # [2] Arastirma & Schema/Dataset Contract uretimi
        # ---------------------------------------------------------------- #
        # Sonuc her hâlukârda bir DatasetContract olarak tasinir: tek tablo bunun
        # N=1 ozel durumu, ayri bir kod yolu degil.
        check_cancel()
        state.save_checkpoint(job_id, current_step=2, step_name=STEP_NAMES[2])
        plan: Optional[ProjectPlan] = None
        if cfg.project_prompt:
            # Planlayici yolu: kac tablo gerektigine plan karar verir, kullanici degil.
            if not 1 <= cfg.max_tables <= MAX_TABLES:
                raise ValueError(
                    "max_tables 1 ile %d arasında olmalı, %d verildi"
                    % (MAX_TABLES, cfg.max_tables)
                )
            yield progress(2, "Proje analiz ediliyor: hangi veri gerekli?")
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
                raise ValueError(
                    "max_tables 2 ile %d arasında olmalı, %d verildi"
                    % (MAX_TABLES, cfg.max_tables)
                )
            yield progress(2, "LLM domain analiz ediyor ve ilişkisel Dataset Contract üretiyor...")
            contract = llm_client.generate_dataset_schema(
                cfg.domain_prompt, row_count=cfg.row_count, seed=cfg.random_seed,
                locale=cfg.faker_locale, seed_dataframe=seed_df,
                max_tables=cfg.max_tables,
            )
        else:
            yield progress(2, "LLM domain analiz ediyor ve Schema Contract üretiyor...")
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
            yield progress(2, "Dataset Contract hazır: %d tablo, %d ilişki (kök tablo: %s)"
                           % (len(contract.tables), len(contract.relationships),
                              contract.root_table), 1.0,
                           schema=contract.to_dict(), warnings=contract.warnings)
        else:
            yield progress(2, "Şema hazır: %s" % schema.summary(), 1.0,
                           schema=schema.to_dict(), warnings=schema.warnings)

        if plan is not None:
            yield from _plan_detail_events(plan, progress)
        yield from _schema_detail_events(contract, progress)

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
            yield progress(4, "Parametrik motor seçildi - kod üretimi ve sandbox atlanıyor")
            raw_tables, code, gen_meta = _generate_parametric(contract, cfg)
            yield progress(5, "Şema doğrudan vektörel derlendi (%.3f sn, LLM kodu yok)"
                           % gen_meta["duration_s"], 1.0)
        else:
            yield progress(4, "Veri üreten kod yazılıyor...")

            messages: "queue.Queue[str]" = queue.Queue()
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
                        on_progress=messages.put,
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
                    message = messages.get(timeout=0.2)
                except queue.Empty:
                    continue
                step = 5 if "sandbox" in message.lower() else 4
                yield progress(step, message, 0.5)
            thread.join()

            gen_error = gen_result.get("error")
            # "auto": kod uretimi denemeleri tukendiyse pipeline'i dusurmek yerine
            # parametrik motora gec. Yalnizca GenerationFailedError icin - iptal,
            # kimlik/servis hatasi ve iliskisel sozlesme fallback'e girmez.
            if (gen_error is not None
                    and engine_choice == ENGINE_AUTO
                    and isinstance(gen_error, GenerationFailedError)
                    and not cancel_event.is_set()
                    and not contract.is_relational):
                yield progress(4, "UYARI: Kod üretimi başarısız (%s)" % gen_error, 0.9)
                yield progress(4, "  -> Parametrik motora düşülüyor (--engine auto)", 0.9)
                raw_tables, code, gen_meta = _generate_parametric(contract, cfg)
                gen_meta["fallback_from"] = ENGINE_LLM
                gen_meta["fallback_reason"] = str(gen_error)
                engines_report["generation"] = "llm->parametric"
                yield progress(5, "Şema doğrudan vektörel derlendi (%.3f sn)"
                               % gen_meta["duration_s"], 1.0)
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
            yield progress(5, "Ham veri üretildi: %d tablo, %s satır (%d deneme, %.1f sn)"
                           % (len(raw_tables), format(raw_total, ","),
                              gen_meta["attempts"], gen_meta["duration_s"]),
                           1.0, rows=raw_total, attempts=gen_meta["attempts"],
                           row_counts={k: len(v) for k, v in raw_tables.items()})
            for name in contract.generation_order():
                yield progress(5, "  -> %s: %s satır"
                               % (name, format(len(raw_tables[name]), ",")), 1.0)
        else:
            yield progress(5, "Ham veri üretildi: %s satır (%d deneme, %.1f sn)"
                           % (format(len(raw_df), ","), gen_meta["attempts"],
                              gen_meta["duration_s"]),
                           1.0, rows=len(raw_df), attempts=gen_meta["attempts"])
        for name, path in sorted(raw_paths.items()):
            try:
                raw_mb = Path(path).stat().st_size / (1024 * 1024)
                yield progress(5, "  -> Ham veri kaydedildi: %s (%.2f MB)"
                               % (Path(path).name, raw_mb), 1.0)
            except Exception:
                pass

        # Fraud / Anomali Senaryo Enjeksiyonu (isteğe bağlı)
        if cfg.inject_fraud:
            from .fraud_injector import inject_fraud_scenarios
            # Iliskisel kosuda enjeksiyon KOK tabloya uygulanir (bkz. README).
            raw_df, fraud_info = inject_fraud_scenarios(
                raw_df,
                fraud_rate=cfg.fraud_rate,
                target_column=cfg.fraud_target_column,
                seed=cfg.random_seed,
            )
            raw_tables[contract.root_table] = raw_df
            if not cfg.preserve_anomaly_column:
                cfg.preserve_anomaly_column = cfg.fraud_target_column
            yield progress(
                5,
                "Dolandırıcılık senaryoları enjekte edildi: %d satır (oran: %%%.2f, kolon: %s)"
                % (fraud_info["injected_fraud_count"], fraud_info["fraud_rate"] * 100, cfg.fraud_target_column),
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
            raw_df, ts_meta = TimeSeriesEngine(ts_cfg).apply(raw_df)
            raw_tables[contract.root_table] = raw_df
            engines_report["time_series"] = ts_meta
            yield progress(5, "Zaman serisi dinamiği uygulandı: %s tekil varlık, "
                              "%d hız patlaması, medyan aralık %.0f sn"
                           % (format(ts_meta.get("unique_entities", 0), ","),
                              ts_meta.get("burst_anomalies_count", 0),
                              ts_meta.get("median_delta_seconds", 0.0)),
                           1.0, time_series=ts_meta)
            yield progress(5, "  -> Zaman aralığı: %s" % ts_meta.get("time_range", "-"), 1.0)
            # Hiz metrikleri ancak varlik kolonu TEKRAR ediyorsa anlamli. Neredeyse
            # tekil bir kolonda (orn. surrogate id) her satir kendi varligi olur ve
            # seconds_since_last_tx satirlarin nerdeyse tamaminda dolgu degerine
            # duser - kullanici bunu bilmeden hiz ozelligi uzerine model kurar.
            entities = ts_meta.get("unique_entities", 0)
            if entities > 0.5 * max(1, len(raw_df)):
                yield progress(5, "UYARI: '%s' kolonu %s satırda %s farklı değer taşıyor; "
                                  "hız metrikleri anlamsız kalır. Tekrar eden bir kolon "
                                  "verin: --ts-entity-col <kolon>"
                               % (cfg.ts_entity_column or "entity_id",
                                  format(len(raw_df), ","), format(entities, ",")), 1.0)

        if cfg.expand_features:
            check_cancel()
            from .feature_expander import expand_features

            raw_df, fe_meta = expand_features(raw_df)
            raw_tables[contract.root_table] = raw_df
            engines_report["feature_expander"] = fe_meta
            added = fe_meta.get("added_columns", [])
            yield progress(5, "Özellik genişletme: %d yeni kolon (toplam %d)"
                           % (fe_meta.get("added_columns_count", 0),
                              fe_meta.get("total_columns", len(raw_df.columns))),
                           1.0, feature_expander=fe_meta)
            if added:
                yield progress(5, "  -> Eklenen kolonlar: %s" % ", ".join(added), 1.0)

        # ---------------------------------------------------------------- #
        # [6] Validasyon & ayiklama
        # ---------------------------------------------------------------- #
        # SIRA KRITIK: once her tablo tek basina temizlenir, SONRA iliskisel
        # butunluk onarilir. Tersi olmaz - tek tablo temizligi bir ebeveyn satiri
        # sildiginde cocuklari yetim kalir, bu yuzden yetim ayiklamasi en sonda.
        check_cancel()
        state.save_checkpoint(job_id, current_step=6, step_name=STEP_NAMES[6])
        yield progress(6, "Discriminator çalışıyor...")

        val_messages: "queue.Queue[str]" = queue.Queue()
        val_result: Dict[str, Any] = {}

        def val_worker() -> None:
            try:
                cleaned: Dict[str, pd.DataFrame] = {}
                reports: Dict[str, Any] = {}
                for name in contract.generation_order():
                    if contract.is_relational:
                        def emit(message: str, _table: str = name) -> None:
                            val_messages.put("[%s] %s" % (_table, message))
                        val_messages.put("Tablo doğrulanıyor: %s" % name)
                    else:
                        emit = val_messages.put
                    # Kok tabloya ozgu secenekler (seed karsilastirmasi, anomali
                    # koruma, gizlilik denetimi) yalnizca kok tabloda calisir.
                    is_root = name == contract.root_table
                    clean, rep = validator.run_validation(
                        raw_tables[name], contract.table(name),
                        seed_df=seed_df if is_root else None,
                        z_threshold=cfg.z_threshold, contamination=cfg.contamination,
                        preserve_anomaly_column=cfg.preserve_anomaly_column if is_root else None,
                        preserve_anomaly_value=cfg.preserve_anomaly_value,
                        audit_privacy=cfg.audit_privacy and is_root,
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
                message = val_messages.get(timeout=0.2)
            except queue.Empty:
                continue
            yield progress(6, message, 0.5)
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
            yield progress(6, "İlişkisel bütünlük denetleniyor (%d ilişki)..."
                           % len(contract.relationships), 0.8)
            rel_lines: List[str] = []
            clean_tables, rel_report = relational_validator.validate_relationships(
                clean_tables, contract, repair=cfg.repair_orphans, emit=rel_lines.append,
            )
            for line in rel_lines:
                yield progress(6, line, 0.9)

            rel_report["repair_enabled"] = cfg.repair_orphans
            report["tables"] = table_reports
            report["relational"] = rel_report
            if not rel_report["pass"]:
                reason = ("yetim onarımı kapalı (--no-repair-orphans)"
                          if not cfg.repair_orphans else "sözleşme ihlali sürüyor")
                yield progress(6, "UYARI: İlişkisel bütünlük denetimi başarısız - %s" % reason, 0.95)

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
            clean_df, dirty_meta = DirtyDataEngine(dirty_cfg).corrupt(clean_df)
            clean_tables[contract.root_table] = clean_df
            # Rapordaki kolon istatistikleri bu adimdan ONCE hesaplandi; okuyan
            # kisi yanilmasin diye bunu rapora acikca yaziyoruz.
            dirty_meta["applied_after_validation"] = True
            dirty_meta["column_stats_precede_corruption"] = True
            engines_report["dirty_data"] = dirty_meta
            breakdown = dirty_meta.get("corruption_breakdown", {})
            yield progress(6, "Kontrollü kirlilik enjekte edildi: %s satır (%%%.1f) - "
                              "eksik %d, yazım hatası %d, uç değer %d, harf/boşluk %d"
                           % (format(dirty_meta.get("corrupted_rows", 0), ","),
                              dirty_meta.get("corrupted_rate", 0.0) * 100,
                              breakdown.get("missing", 0), breakdown.get("typo", 0),
                              breakdown.get("outlier_spike", 0), breakdown.get("casing", 0)),
                           1.0, dirty_data=dirty_meta)
            yield progress(6, "  -> Denetim izi kolonları eklendi: is_corrupted, "
                              "corruption_details", 1.0)

        report["engines"] = engines_report
        report["generation"] = gen_meta
        report["seed_source"] = seed_source
        if plan is not None:
            report["project_plan"] = plan.to_dict()

        state.save_report(job_id, report)
        state.save_checkpoint(job_id,
                              validated_rows_count=sum(len(df) for df in clean_tables.values()),
                              progress=6 / TOTAL_STEPS * 100)
        yield progress(6, "Validasyon bitti: %s -> %s satır (%%%.1f korundu)"
                       % (format(report["rows_in"], ","), format(report["rows_out"], ","),
                          report["retention_pct"]),
                       1.0, report=_report_summary(report))
        if contract.is_relational:
            for name in contract.generation_order():
                rep = table_reports[name]
                yield progress(6, "  -> %s: %s -> %s satır (%%%.1f)"
                               % (name, format(rep["rows_in"], ","),
                                  format(rep["rows_out"], ","), rep["retention_pct"]), 1.0)

        # ---------------------------------------------------------------- #
        # [7] Cikti & durum kaydi
        # ---------------------------------------------------------------- #
        check_cancel()
        state.save_checkpoint(job_id, current_step=7, step_name=STEP_NAMES[7])
        if cfg.write_outputs:
            yield progress(7, "Çıktı dosyaları yazılıyor...")
            output_paths = _write_outputs(clean_tables, contract, report, code, job_id,
                                          cfg, plan)
            yield progress(7, "Çıktı yazıldı: %s" % ", ".join(sorted(output_paths)), 0.6,
                           paths=output_paths)
        else:
            output_paths = {}
            yield progress(7, "Çıktı dosyası yazılmadı (write_outputs=False)", 0.6)
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
            yield progress(7, "HuggingFace'e yükleniyor: %s" % cfg.push_to_hub, 0.8)
            hub_url = _push_to_hub(clean_df, schema, report, llm_client, cfg)
            yield progress(7, "Yüklendi: %s" % hub_url, 0.9, hub_url=hub_url)

        cost = state.get_cost_summary(job_id)
        if cost.get("calls", 0) > 0 or cost.get("cost_usd", 0.0) > 0:
            tot_tokens = cost.get("prompt_tokens", 0) + cost.get("completion_tokens", 0)
            yield progress(7, "  -> LLM Kullanımı: %d çağrı, %s token, ~$%.4f"
                           % (cost.get("calls", 0), format(tot_tokens, ","), cost.get("cost_usd", 0.0)), 0.95)

        # Iliskisel kosuda tek bir "cikti dosyasi" yok; manifest hepsini isaret eder.
        state.save_checkpoint(job_id, status=STATUS_DONE, progress=100.0,
                              output_path=output_paths.get("manifest") or
                              output_paths.get("csv") or
                              next(iter(output_paths.values()), None))
        clean_total = sum(len(df) for df in clean_tables.values())
        if contract.is_relational:
            yield progress(7, "Tamamlandı. %d tablo, %s temiz satır, tahmini maliyet $%.4f"
                           % (len(clean_tables), format(clean_total, ","),
                              cost.get("cost_usd", 0.0)), 1.0, cost=cost)
        else:
            yield progress(7, "Tamamlandı. %s temiz satır, tahmini maliyet $%.4f"
                           % (format(len(clean_df), ","), cost.get("cost_usd", 0.0)), 1.0,
                           cost=cost)

        return PipelineResult(
            job_id=job_id, schema=schema, dataframe=clean_df, report=report, code=code,
            output_paths=output_paths, cost=cost, generation_meta=gen_meta, hub_url=hub_url,
            tables=clean_tables, contract=contract, plan=plan,
        )

    except PipelineCancelled:
        state.save_checkpoint(job_id, status=STATUS_CANCELLED, error="Kullanıcı iptal etti")
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
    yield progress(2, "Plan hazır: %s" % plan.summary(), 1.0, plan=plan.to_dict())
    if plan.rationale:
        yield progress(2, "  -> Gerekçe: %s" % plan.rationale, 1.0)
    if plan.target is not None:
        yield progress(2, "  -> Hedef değişken: %s" % plan.target.label(), 1.0)
    if plan.positive_class_ratio is not None:
        yield progress(2, "  -> Sınıf dengesi: pozitif sınıf %%%.1f"
                       % (plan.positive_class_ratio * 100), 1.0)
    if plan.excluded_leakage:
        yield progress(2, "  -> Sızıntı yaratacağı için ayıklanan kolonlar (%d adet):"
                       % len(plan.excluded_leakage), 1.0)
        for excl in plan.excluded_leakage:
            yield progress(2, "  • %s - %s" % (excl.column, excl.reason), 1.0)
    if plan.split is not None:
        detail = plan.split.kind
        if plan.split.column:
            detail += " (%s.%s)" % (plan.split.table, plan.split.column)
        yield progress(2, "  -> Train/test ayrımı: %s - %s"
                       % (detail, plan.split.reason), 1.0)
    for warning in plan.warnings:
        yield progress(2, "UYARI: %s" % warning, 1.0)


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
        yield progress(2, "  -> %d tablo, üretim sırası: %s"
                       % (len(contract.tables), " -> ".join(contract.generation_order())), 1.0)

    for schema in contract.tables:
        if multi:
            pk = schema.primary_key or "-"
            yield progress(2, "  -> Tablo '%s' | PK: %s | hedef %s satır"
                           % (schema.table_name, pk,
                              format(schema.row_count_target, ",")), 1.0)
        yield progress(2, "  -> Tanımlanan kolonlar (%d adet):" % len(schema.columns), 1.0)
        for col in schema.columns:
            specs = []
            if col.min is not None or col.max is not None:
                specs.append("aralık: [%s, %s]" % (col.min if col.min is not None else "-inf",
                                                   col.max if col.max is not None else "+inf"))
            if col.distribution:
                specs.append("dağılım: %s" % col.distribution)
            if col.categories:
                cats = ", ".join(repr(c) for c in col.categories[:3])
                if len(col.categories) > 3:
                    cats += ", ..."
                specs.append("kategoriler: [%s]" % cats)
            if col.target_ratio is not None:
                specs.append("oran: %%%.1f" % (col.target_ratio * 100))
            if not col.nullable:
                specs.append("not null")
            spec_str = (" (%s)" % ", ".join(specs)) if specs else ""
            yield progress(2, "  • %s: %s%s" % (col.name, col.type, spec_str), 1.0)

        if schema.business_rules:
            yield progress(2, "  -> İş kuralları (%d adet):" % len(schema.business_rules), 1.0)
            for rule in schema.business_rules:
                yield progress(2, "  • Kural: %s" % rule, 1.0)

        if schema.correlations:
            yield progress(2, "  -> Beklenen korelasyonlar (%d adet):" % len(schema.correlations), 1.0)
            for corr in schema.correlations:
                yield progress(2, "  • %s <-> %s (%s, min_r=%.2f)"
                               % (corr.columns[0], corr.columns[1],
                                  corr.expected_sign, corr.min_r), 1.0)

        for warning in schema.warnings:
            yield progress(2, "UYARI: %s" % warning, 1.0)

    if contract.relationships:
        yield progress(2, "  -> İlişkiler (%d adet):" % len(contract.relationships), 1.0)
        for rel in contract.relationships:
            bounds = "min %d" % rel.min_per_parent
            if rel.max_per_parent is not None:
                bounds += ", max %d" % rel.max_per_parent
            yield progress(2, "  • %s (ebeveyn başına ort %.1f; %s%s)"
                           % (rel.label(), rel.mean_per_parent, bounds,
                              ", opsiyonel" if rel.nullable else ""), 1.0)

    for warning in contract.warnings:
        yield progress(2, "UYARI: %s" % warning, 1.0)


def _build_llm_client(cfg: PipelineConfig, state: StateManager,
                      job_id: int) -> BaseLLMClient:
    """[1] Servis kontrolü - sağlayıcıyı kurar, erişilemiyorsa anlamlı hata verir."""
    from ..services.cloud_llm_service import create_client

    client = create_client(cfg.provider, cfg.model, state_manager=state, job_id=job_id)
    if not client.health_check():
        raise LLMError(
            "%s servisi doğrulanamadı (model: %s). %s"
            % (cfg.provider, client.model,
               client.last_health_error or "API key'i / daemon'u kontrol edin.")
        )
    return client


# Parametrik kosuda LLM kodu olmadigi icin cikti klasorune bu sablon yazilir.
# Amac dekoratif degil: uretim %100 deterministik oldugundan bu dosya veri setini
# birebir yeniden uretir, yani "kod ciktisi" sozu bos kalmaz.
_PARAMETRIC_CODE_TEMPLATE = '''"""Bu veri seti ParametricEngine ile üretildi - LLM kod üretimi kullanılmadı.

Şema sözleşmesi aşağıya gömülüdür; üretim deterministiktir, bu dosya aynı seed
ile aynı veri setini birebir yeniden üretir.

GEREKSİNİM: LLM'in yazdığı üretici dosyalarının aksine bu dosya ai_data_studio
paketini içeri alır - motorun kendisi paketin içindedir. Çalıştırmadan önce paket
import edilebilir olmalı:

    pip install ai-data-studio      # ya da depo kökünden: pip install -e .
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

    Iliskisel sozlesme kabul edilmez: parametrik motor kolonlari bagimsiz
    dagilimlardan cekiyor, yabanci anahtar tutarliligini kuramiyor. Sessizce
    yetim satir uretmektense acik hata veriyoruz.
    """
    from .parametric_engine import compile_schema_to_dataframe

    if contract.is_relational:
        raise ValueError(
            "Parametrik motor şu an tek tablolu üretimi destekliyor (sözleşmede "
            "%d tablo var). İlişkisel üretim için --engine llm kullanın; yabancı "
            "anahtar tutarlılığını yalnızca kod üretimi yolu kuruyor."
            % len(contract.tables)
        )

    schema = contract.table(contract.root_table)
    started = time.perf_counter()
    df = compile_schema_to_dataframe(schema, n_rows=cfg.row_count, seed=cfg.random_seed)
    duration = time.perf_counter() - started
    code = _PARAMETRIC_CODE_TEMPLATE % {
        "schema_json": json.dumps(schema.to_dict(), ensure_ascii=False, indent=2),
        "rows": cfg.row_count,
        "seed": cfg.random_seed,
    }
    meta: Dict[str, Any] = {
        "attempts": 1,
        "duration_s": round(duration, 4),
        "engine": ENGINE_PARAMETRIC,
        "rows": len(df),
        "columns": len(df.columns),
    }
    log.info("Parametrik motor: %d satır, %d kolon, %.3f sn",
             len(df), len(df.columns), duration)
    return {contract.root_table: df}, code, meta


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
        stem = "job_%d_raw" % job_id if not contract.is_relational else "job_%d_%s_raw" % (job_id, name)
        target = config.RAW_DIR / (stem + ".parquet")
        try:
            df.to_parquet(target, index=False)
        except Exception as exc:
            log.warning("Ham veri parquet olarak kaydedilemedi (%s): %s", name, exc)
            target = config.RAW_DIR / (stem + ".csv")
            df.to_csv(target, index=False, encoding="utf-8")
        paths[name] = str(target)
    return paths


def _write_table_files(df: pd.DataFrame, out_dir: Path, stem: str,
                       formats: List[str]) -> Dict[str, str]:
    """Bir tablonun veri dosyalarini istenen formatlarda yazar."""
    written: Dict[str, str] = {}
    if "csv" in formats:
        target = out_dir / (stem + ".csv")
        df.to_csv(target, index=False, encoding="utf-8")   # Bolum 10.5
        written["csv"] = str(target)
    if "parquet" in formats:
        target = out_dir / (stem + ".parquet")
        try:
            df.to_parquet(target, index=False)
            written["parquet"] = str(target)
        except Exception as exc:
            log.warning("Parquet yazılamadı (pyarrow eksik olabilir): %s", exc)
    if "json" in formats:
        target = out_dir / (stem + ".json")
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
    stem = "job_%d_%s" % (job_id, contract.domain)
    paths: Dict[str, str] = {}

    formats = [f.lower() for f in (cfg.export_formats or ["csv"])]
    if contract.is_relational:
        table_files: Dict[str, Dict[str, str]] = {}
        for name in contract.generation_order():
            written = _write_table_files(tables[name], out_dir,
                                         "job_%d_%s" % (job_id, name), formats)
            table_files[name] = written
            for kind, path in written.items():
                paths["%s:%s" % (kind, name)] = path
    else:
        table_files = {}
        paths.update(_write_table_files(tables[contract.root_table], out_dir, stem, formats))

    schema_json = contract.to_json() if contract.is_relational else schema.to_json()
    config.write_text(out_dir / (stem + "_schema.json"), schema_json)
    paths["schema"] = str(out_dir / (stem + "_schema.json"))

    config.write_text(out_dir / (stem + "_generator.py"), code)
    paths["code"] = str(out_dir / (stem + "_generator.py"))

    config.write_json(out_dir / (stem + "_report.json"), report)
    paths["report"] = str(out_dir / (stem + "_report.json"))

    if plan is not None:
        # Plan sozlesmeden ayri yazilir: hedef, sinif dengesi, ayiklanan sizinti
        # kolonlari ve bolme stratejisi veri setiyle birlikte tasinmali.
        config.write_text(out_dir / (stem + "_plan.json"), plan.to_json())
        paths["plan"] = str(out_dir / (stem + "_plan.json"))

    if "privacy_audit" in report and report["privacy_audit"]:
        try:
            from .privacy_auditor import PrivacyAuditReport, DCRResult, NNDRResult, HIPAAAuditResult
            pa_data = report["privacy_audit"]
            dcr_obj = DCRResult(**pa_data["dcr"]) if pa_data.get("dcr") else None
            nndr_obj = NNDRResult(**pa_data["nndr"]) if pa_data.get("nndr") else None
            hipaa_obj = HIPAAAuditResult(
                identifiers_found=pa_data["hipaa"]["identifiers_found"],
                age_greater_than_89_count=pa_data["hipaa"]["age_greater_than_89_count"],
                passed=pa_data["hipaa"]["passed"],
                summary=pa_data["hipaa"]["summary"],
            ) if pa_data.get("hipaa") else HIPAAAuditResult()
            audit_obj = PrivacyAuditReport(
                has_reference_data=pa_data.get("has_reference_data", False),
                dcr=dcr_obj,
                nndr=nndr_obj,
                empirical_epsilon=pa_data.get("empirical_epsilon"),
                privacy_guarantee=pa_data.get("privacy_guarantee", "Standard"),
                hipaa_audit=hipaa_obj,
                overall_privacy_status=pa_data.get("overall_privacy_status", "COMPLIANT"),
            )
            md_path = out_dir / (stem + "_privacy_report.md")
            config.write_text(md_path, audit_obj.to_markdown())
            paths["privacy_report"] = str(md_path)
        except Exception as exc:
            log.warning("Gizlilik raporu markdown yazılamadı: %s", exc)

    if contract.is_relational:
        manifest_path = out_dir / (stem + "_manifest.json")
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
                  if k in ("schema", "code", "report", "privacy_report", "plan")},
    }


def _push_to_hub(df: pd.DataFrame, schema: SchemaContract, report: Dict[str, Any],
                 llm_client: BaseLLMClient, cfg: PipelineConfig) -> str:
    from ..services import hf_service
    return hf_service.push_dataset(
        df, cfg.push_to_hub, schema, report=report, llm_client=llm_client,
        private=cfg.hub_private,
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
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m ai_data_studio.core.orchestrator",
        description="AI Synthetic Data Studio - GUI'siz uçtan uca pipeline",
    )
    p.add_argument("--domain", help="Üretilecek veri setinin domain/görev tanımı")
    p.add_argument("--project",
                   help="Veri yerine PROJEYİ anlat: planlayıcı hangi verinin gerektiğine, "
                        "hedef değişkene, sınıf dengesine, ayıklanacak sızıntı kolonlarına "
                        "ve train/test ayrımına kendisi karar verir")
    p.add_argument("--check-auth", action="store_true",
                   help="Tüm sağlayıcıların kimlik durumunu yazdırıp çıkar")
    p.add_argument("--provider", default=config.PROVIDER_ANTHROPIC,
                   choices=[config.PROVIDER_ANTHROPIC, config.PROVIDER_GEMINI,
                            config.PROVIDER_OLLAMA])
    p.add_argument("--model", default=None, help="Sağlayıcıya özel model adı")
    p.add_argument("--rows", type=int, default=config.DEFAULT_ROW_TARGET)
    p.add_argument("--seed", type=int, default=config.DEFAULT_RANDOM_SEED)
    p.add_argument("--locale", default="en_US", help="Faker locale (or: tr_TR)")
    p.add_argument("--hf-seed", action="store_true", help="HuggingFace'ten referans veri çek")
    p.add_argument("--hf-dataset", default="", help="Belirli bir HF dataset id'si kullan")
    p.add_argument("--web-seed", action="store_true", help="Web'den gerçek referans (seed) veri topla")
    p.add_argument("--web-query", default="", help="Web arama sorgusu veya doğrudan URL")
    p.add_argument("--formats", default="csv,parquet", help="Virgülle ayrılmış: csv,parquet,json")
    p.add_argument("--output-dir", default=None)
    p.add_argument("--push-to-hub", default="", help="Temiz veriyi bu HF repo_id'ye yükle")
    p.add_argument("--public", action="store_true", help="HF repo'yu herkese açık oluştur")
    p.add_argument("--timeout", type=int, default=config.SANDBOX_TIMEOUT_S)
    p.add_argument("--max-retries", type=int, default=config.MAX_CODEGEN_RETRIES)
    p.add_argument("--contamination", type=float, default=validator.DEFAULT_CONTAMINATION,
                   help="IsolationForest anomali orani (0 = kapalı, varsayılan). Örn: 0.05")
    p.add_argument("--no-correlation-guard", action="store_true",
                   help="Outlier temizliği hedef korelasyonları bozarsa geri alma korumasını kapat")
    p.add_argument("--z-threshold", type=float, default=validator.DEFAULT_Z_THRESHOLD)
    p.add_argument("--preserve-anomaly-col", default=None,
                   help="Z-score ve IsolationForest filtrelerinden muaf tutulacak anomali kolonu (örn: is_fraud)")
    p.add_argument("--preserve-anomaly-val", default=None,
                   help="Anomali koruma değeri (varsayılan: 1 veya True)")
    p.add_argument("--inject-fraud", action="store_true",
                   help="Sentetik veriye parametrik dolandırıcılık (fraud) senaryoları enjekte et")
    p.add_argument("--fraud-rate", type=float, default=0.005,
                   help="Dolandırıcılık enjeksiyon oranı (varsayılan: 0.005 yani %%0.5)")
    p.add_argument("--fraud-target-col", default="is_fraud",
                   help="Dolandırıcılık etiket kolonu (varsayılan: is_fraud)")
    p.add_argument("--audit-privacy", action="store_true",
                   help="NNDR, Diferansiyel Gizlilik ve HIPAA Safe Harbor denetimi yap")
    p.add_argument("--gemini-backend", default=None,
                   choices=[config.GEMINI_BACKEND_AISTUDIO, config.GEMINI_BACKEND_CLI],
                   help="Gemini arka ucunu bu koşu için seç: 'aistudio' (API anahtarı, hızlı) "
                        "veya 'cli' (Antigravity oturumu, yavaş). Kalıcı ayar değişmez")
    p.add_argument("--relational", action="store_true",
                   help="Çok tablolu (ilişkisel) veri seti üret: tablolar + yabancı anahtarlar")
    p.add_argument("--max-tables", type=int, default=6,
                   help="İlişkisel modda üst tablo sınırı (varsayılan 6, sözleşmedeki sert sınır 12)")
    p.add_argument("--no-repair-orphans", action="store_true",
                   help="Yetim yabancı anahtarları silme, hata olarak raporla "
                        "(CI kapısı: bütünlük sağlanamazsa çıkış kodu 3)")
    # --- Uretim ve zenginlestirme motorlari ---------------------------- #
    p.add_argument("--engine", default=ENGINE_LLM, choices=list(ENGINES),
                   help="Üretim motoru: 'llm' kod üretir ve sandbox'ta koşar "
                        "(varsayılan), 'parametric' şemayı doğrudan derler "
                        "(LLM kodu yok, tek tablo), 'auto' kod üretimi tükenirse "
                        "parametriğe düşer")
    p.add_argument("--time-series", action="store_true",
                   help="Zaman serisi ve hız dinamiği ekle: kronolojik sıralama, "
                        "sirkadiyen ritim, seconds_since_last_tx, hız patlamaları")
    p.add_argument("--ts-timestamp-col", default="transaction_timestamp",
                   help="Zaman serisi zaman damgası kolonu (varsayılan: transaction_timestamp)")
    p.add_argument("--ts-entity-col", default="customer_id",
                   help="Zaman serisi varlık kimliği kolonu; yoksa üretilir "
                        "(varsayılan: customer_id)")
    p.add_argument("--ts-start", default="", help="Zaman serisi başlangıcı (YYYY-MM-DD HH:MM:SS)")
    p.add_argument("--ts-end", default="", help="Zaman serisi bitişi (YYYY-MM-DD HH:MM:SS)")
    p.add_argument("--expand-features", action="store_true",
                   help="Deterministik özellik genişletme: finansal oranlar, kredi "
                        "notu, zaman türevleri ve davranışsal bayraklar ekle")
    p.add_argument("--dirty-rate", type=float, default=0.0,
                   help="Kontrollü kirlilik oranı (0-1, 0 = kapalı). Doğrulamadan "
                        "SONRA uygulanır; is_corrupted / corruption_details kolonları eklenir")
    p.add_argument("--hardware", action="store_true",
                   help="Donanım profilini (CPU/RAM/GPU) ve önerilen yerel modeli yazdır, çık")
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def check_auth() -> int:
    """Her sağlayıcı için kimliğin nereden çözüldüğünü yazdırır."""
    print("Kimlik bilgisi durumu")
    print("-" * 72)
    ok_any = False
    for provider in (config.PROVIDER_ANTHROPIC, config.PROVIDER_GEMINI, "huggingface"):
        status = config.credential_status(provider)
        if status["explicit"]:
            mark, note = "[OK]  ", "kaynak: %s" % status["source"]
            ok_any = True
        elif status["configured"]:
            mark, note = "[?]   ", "anahtar yok ama %s bulundu - denenecek" % status["source"]
            ok_any = True
        else:
            mark = "[YOK] "
            note = "bakılan: keyring, %s" % ", ".join(status["checked_env_vars"])
        print("%s%-12s %s" % (mark, provider, note))

        oauth = config.oauth_status(provider)
        if oauth["supported"]:
            if oauth["logged_in"]:
                print("        OAuth: giriş yapılmış - %s" % oauth["detail"])
            elif not config.cli_available(oauth["command"][0]):
                print("        OAuth: %s kurulu değil (%s)"
                      % (oauth["command"][0], oauth["install_hint"]))
            else:
                print("        OAuth: giriş için -> %s" % " ".join(oauth["command"]))
            if oauth["note"]:
                print("        NOT:   %s" % oauth["note"])

    from ..services import ollama_service
    if ollama_service.is_available():
        models = ollama_service.list_model_names()
        print("[OK]  %-12s Ollama %s - %d model" %
              (config.PROVIDER_OLLAMA, ollama_service.get_version() or "?", len(models)))
        ok_any = True
    else:
        print("[YOK] %-12s daemon çalışmıyor (%s)"
              % (config.PROVIDER_OLLAMA, config.OLLAMA_HOST))

    print("-" * 72)
    if not ok_any:
        print("Hiçbir sağlayıcı kullanılabilir değil.")
        print("  Ayarlar sekmesinden anahtar girin, veya:")
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
        print("--domain ve --project birlikte kullanılamaz: ya veriyi tarif edin "
              "ya da projeyi anlatın", file=sys.stderr)
        return 2
    if not args.domain and not args.project:
        print("--domain veya --project zorunlu (veya --check-auth kullanın)",
              file=sys.stderr)
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
        audit_privacy=args.audit_privacy,
        relational=args.relational,
        max_tables=args.max_tables,
        repair_orphans=not args.no_repair_orphans,
        engine=args.engine,
        time_series=args.time_series,
        ts_timestamp_column=args.ts_timestamp_col,
        ts_entity_column=args.ts_entity_col,
        ts_start_date=args.ts_start,
        ts_end_date=args.ts_end,
        expand_features=args.expand_features,
        dirty_rate=args.dirty_rate,
    )

    state = get_state_manager()
    state.mark_stale_jobs_interrupted()
    cancel_event = threading.Event()

    print("AI Synthetic Data Studio")
    print("%-10s: %s" % ("Proje" if cfg.project_prompt else "Domain", cfg.domain_prompt))
    backend_note = ""
    if cfg.provider == config.PROVIDER_GEMINI:
        backend_note = " (arka uç: %s)" % config.gemini_backend()
    print("Sağlayıcı : %s / %s%s" % (cfg.provider, cfg.resolved_model(), backend_note))
    print("Hedef     : %s satır, seed %d" % (format(cfg.row_count, ","), cfg.random_seed))
    if cfg.project_prompt:
        print("Mod       : proje planlayıcı (en fazla %d tablo, tablo sayısına plan karar verir)"
              % cfg.max_tables)
    elif cfg.relational:
        print("Mod       : ilişkisel (en fazla %d tablo, yetim onarımı: %s)"
              % (cfg.max_tables, "açık" if cfg.repair_orphans else "KAPALI"))
    engine_extras = []
    if cfg.time_series:
        engine_extras.append("zaman serisi")
    if cfg.expand_features:
        engine_extras.append("özellik genişletme")
    if cfg.dirty_rate > 0:
        engine_extras.append("kirlilik %%%.1f" % (cfg.dirty_rate * 100))
    if cfg.engine != ENGINE_LLM or engine_extras:
        print("Motor     : %s%s"
              % (cfg.engine, (" + " + ", ".join(engine_extras)) if engine_extras else ""))
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
        print("\nIptal edildi.")
        return 130
    except PipelineCancelled as exc:
        print("\nIptal edildi: %s" % exc)
        return 130
    except Exception as exc:
        print("\nHATA: %s" % exc, file=sys.stderr)
        return 1

    if result is None:
        print("Pipeline sonuç döndürmedi.", file=sys.stderr)
        return 1

    print("-" * 72)
    print("Job #%d tamamlandı." % result.job_id)
    print("Temiz satır : %s / %s (%%%.1f korundu)"
          % (format(result.report["rows_out"], ","), format(result.report["rows_in"], ","),
             result.report["retention_pct"]))
    tot_tokens = result.cost.get("prompt_tokens", 0) + result.cost.get("completion_tokens", 0)
    print("Maliyet     : $%.4f (%s çağrı, %s token)"
          % (result.cost.get("cost_usd", 0.0), result.cost.get("calls", 0), format(tot_tokens, ",")))
    print("Çıktılar:")
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
        print("Proje planı: %s" % plan.summary())
        if plan.target is not None:
            print("  Hedef değişken   : %s" % plan.target.label())
        if plan.positive_class_ratio is not None:
            print("  Sınıf dengesi    : pozitif %%%.1f" % (plan.positive_class_ratio * 100))
        if plan.split is not None:
            print("  Train/test       : %s%s" % (
                plan.split.kind,
                (" (%s.%s)" % (plan.split.table, plan.split.column)) if plan.split.column else ""))
        for excl in plan.excluded_leakage:
            print("  Ayıklanan sızıntı: %s - %s" % (excl.column, excl.reason))

    rel = result.report.get("relational")
    if rel:
        print("-" * 72)
        print("İlişkisel bütünlük: %s" % ("UYGUN" if rel.get("pass") else "BAŞARISIZ"))
        for name, count in sorted((rel.get("row_counts") or {}).items()):
            print("  %-24s %s satır" % (name, format(count, ",")))
        for fk in rel.get("foreign_keys", []):
            print("  FK %-40s %s yetim (%%%.2f)"
                  % (fk.get("relationship", "?"), format(fk.get("orphan_rows", 0), ","),
                     fk.get("orphan_pct", 0.0)))
        for card in rel.get("cardinality", []):
            print("  Kardinalite %-33s ort %.2f (beklenen %.2f)%s"
                  % (card.get("relationship", "?"), card.get("observed_mean", 0.0),
                     card.get("expected_mean", 0.0), "" if card.get("pass") else "  <-- SAPMA"))
        removed = (rel.get("repair") or {}).get("removed_total", 0)
        if removed:
            print("  Elenen yetim satır: %s" % format(removed, ","))
        # CI kapisi: yetim FK ya da tekil olmayan PK gercek bir butunluk ihlalidir,
        # cikis kodu 3 olur. Kardinalite sapmasi istatistikseldir - uyarilir ama
        # tek basina kosuyu dusurmez, aksi halde --no-repair-orphans'siz normal
        # kosular rastgele basarisiz gorunurdu.
        broken = ([r for r in rel.get("primary_keys", []) if not r.get("pass")]
                  + [r for r in rel.get("foreign_keys", []) if not r.get("pass")])
        if broken:
            print("İlişkisel bütünlük sağlanamadı (%d ihlal)." % len(broken), file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
