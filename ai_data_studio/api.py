"""AI Synthetic Data Studio - programatik (kütüphane) arayüzü.

Bu modül, GUI ve CLI'ın kullandığı aynı pipeline'ı üç satırlık bir Python
çağrısına indirger::

    from ai_data_studio import generate

    result = generate("e-commerce orders with churn", rows=50_000, provider="ollama")
    result.dataframe.head()

Ağır bağımlılıklar (pandas, sklearn, sağlayıcı SDK'ları) yalnızca bu modül
içeri alındığında yüklenir; ``import ai_data_studio`` tek başına ucuz kalır
(bkz. ``ai_data_studio/__init__.py`` içindeki tembel yükleme).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Sequence, Tuple

from . import config
from .core import validator
from .core.orchestrator import (
    ENGINE_AUTO,
    ENGINE_LLM,
    ENGINE_PARAMETRIC,
    PipelineConfig,
    PipelineResult,
    run_pipeline,
)
from .core.schema_contract import SchemaContract

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd
    from .services.llm_base import BaseLLMClient

__all__ = [
    "generate",
    "validate",
    "compile_dataset",
    "compile_schema",
    "build_config",
    "ENGINE_LLM",
    "ENGINE_PARAMETRIC",
    "ENGINE_AUTO",
]


def build_config(
    domain: str,
    *,
    project: str = "",
    rows: int = config.DEFAULT_ROW_TARGET,
    seed: int = config.DEFAULT_RANDOM_SEED,
    provider: str = config.PROVIDER_ANTHROPIC,
    model: Optional[str] = None,
    locale: str = "en_US",
    formats: Optional[Sequence[str]] = None,
    output_dir: Optional[Any] = None,
    z_threshold: float = validator.DEFAULT_Z_THRESHOLD,
    contamination: float = validator.DEFAULT_CONTAMINATION,
    correlation_guard: bool = True,
    preserve_anomaly_column: Optional[str] = None,
    preserve_anomaly_value: Any = None,
    inject_fraud: bool = False,
    fraud_rate: float = 0.005,
    fraud_target_column: str = "is_fraud",
    fraud_table: str = "",
    audit_privacy: bool = False,
    audit_table: str = "",
    use_web_seed: bool = False,
    web_seed_query: str = "",
    use_hf_seed: bool = False,
    hf_seed_dataset: str = "",
    max_retries: int = config.MAX_CODEGEN_RETRIES,
    sandbox_timeout: int = config.SANDBOX_TIMEOUT_S,
    push_to_hub: str = "",
    hub_private: bool = True,
    relational: bool = False,
    max_tables: int = 6,
    repair_orphans: bool = True,
    engine: str = ENGINE_LLM,
    time_series: bool = False,
    ts_timestamp_column: str = "transaction_timestamp",
    ts_entity_column: str = "customer_id",
    ts_start_date: str = "",
    ts_end_date: str = "",
    ts_table: str = "",
    expand_features: bool = False,
    expand_table: str = "",
    dirty_rate: float = 0.0,
    dirty_table: str = "",
    agentic: bool = False,
    max_agent_rounds: int = 2,
) -> PipelineConfig:
    """Okunabilir anahtar kelimelerden bir :class:`PipelineConfig` kurar.

    Dosya yazma kurali:

    * ``output_dir`` da ``formats`` da verilmemisse hicbir dosya yazilmaz -
      sonuc yalnizca bellekte doner. Kutuphane kullaniminda beklenen budur.
    * Ikisinden biri verilmisse disa aktarim acilir; ``formats`` verilmemisse
      ``["csv"]`` varsayilir, ``output_dir`` verilmemisse varsayilan cikti
      dizini kullanilir.

    Proje planlayici:

    * ``project="..."`` verildiginde ``domain`` yerine PROJE tarifi kullanilir;
      hangi tablolarin gerektigine, hedef degiskene, sinif dengesine, ayiklanacak
      sizinti kolonlarina ve train/test ayrimina plan karar verir. Sonucun ``plan``
      alani :class:`ProjectPlan` olur.

    Iliskisel mod:

    * ``relational=True`` cok tablolu bir veri seti uretir; sonucun ``tables``
      alani tablo adindan DataFrame'e eslesir, ``dataframe`` kok tabloyu gosterir.
    * ``repair_orphans=False`` yetim yabanci anahtarlari silmez, yalnizca
      raporlar - CI kapisi olarak kullanilir.

    Uretim motoru (``engine``):

    * ``"llm"`` (varsayilan) LLM'e uretici Python kodu yazdirir ve sandbox'ta
      kosturur - self-healing dongusu buradadir.
    * ``"parametric"`` sozlesmeyi dogrudan numpy/pandas vektorlerine derler:
      kod uretimi ve sandbox tamamen atlanir, uretim deterministiktir ve
      milisaniyeler surer. Cok tablolu iliskisel sozlesmeleri de destekler.
    * ``"auto"`` once LLM'i dener, kod uretimi denemeleri tukenirse parametrik
      motora duser.

    Zenginlestirme motorlari:

    * ``time_series=True`` kronolojik siralama, sirkadiyen ritim, varlik bazli
      ``seconds_since_last_tx`` ve hiz patlamalari ekler (hedef: ``ts_table``).
    * ``expand_features=True`` finansal oranlar, yas/kredi siniflandirmasi ve
      zaman turevleri gibi deterministik kolonlar turetir (hedef: ``expand_table``).
    * ``dirty_rate`` (0-1) kontrollu gurultu enjekte eder (hedef: ``dirty_table``).
      **Dogrulamadan SONRA** calisir: aksi halde sema sinirlari ve kategori denetimi
      tam da enjekte edilen satirlari elerdi. ``is_corrupted`` ve
      ``corruption_details`` denetim kolonlari eklenir.

    Hangi motorun kostugu sonucun ``report["engines"]`` alanindadir.
    """
    exporting = output_dir is not None or formats is not None
    export_formats = [f.strip().lower() for f in (formats or ["csv"]) if str(f).strip()]

    return PipelineConfig(
        domain_prompt=domain,
        provider=provider,
        model=model,
        row_count=rows,
        random_seed=seed,
        faker_locale=locale,
        export_formats=export_formats,
        output_dir=Path(output_dir) if output_dir is not None else None,
        write_outputs=exporting,
        z_threshold=z_threshold,
        contamination=contamination,
        correlation_guard=correlation_guard,
        preserve_anomaly_column=preserve_anomaly_column,
        preserve_anomaly_value=preserve_anomaly_value,
        inject_fraud=inject_fraud,
        fraud_rate=fraud_rate,
        fraud_target_column=fraud_target_column,
        fraud_table=fraud_table,
        audit_privacy=audit_privacy,
        audit_table=audit_table,
        use_web_seed=use_web_seed,
        web_seed_query=web_seed_query,
        use_hf_seed=use_hf_seed,
        hf_seed_dataset=hf_seed_dataset,
        max_retries=max_retries,
        sandbox_timeout=sandbox_timeout,
        push_to_hub=push_to_hub,
        hub_private=hub_private,
        relational=relational,
        max_tables=max_tables,
        repair_orphans=repair_orphans,
        project_prompt=project,
        engine=engine,
        time_series=time_series,
        ts_timestamp_column=ts_timestamp_column,
        ts_entity_column=ts_entity_column,
        ts_start_date=ts_start_date,
        ts_end_date=ts_end_date,
        ts_table=ts_table,
        expand_features=expand_features,
        expand_table=expand_table,
        dirty_rate=dirty_rate,
        dirty_table=dirty_table,
        agentic=agentic,
        max_agent_rounds=max_agent_rounds,
    )


def generate(
    domain: str = "",
    *,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    llm_client: Optional["BaseLLMClient"] = None,
    **kwargs: Any,
) -> PipelineResult:
    """Uctan uca pipeline'i calistirir ve sonucu dondurur.

    Args:
        domain: Uretilecek veri setinin domain/gorev tanimi (dogal dil).
        on_progress: Her adimda cagrilan geri arama. Kendisine
            ``{step, total_steps, name, message, percent, ...}`` sozlugu gecilir.
        cancel_event: Set edildiginde pipeline erken durur.
        llm_client: Hazir bir istemci - testlerde gercek API cagrisi yapmadan
            pipeline'i kosturmak icin.
        **kwargs: :func:`build_config` parametreleri (rows, seed, provider, ...).

    Returns:
        :class:`PipelineResult` - ``.dataframe``, ``.report``, ``.schema``,
        ``.code``, ``.output_paths``, ``.cost`` alanlarini tasir. Iliskisel
        kosuda ayrica ``.tables`` (tablo adi -> DataFrame) ve ``.contract``
        (:class:`DatasetContract`) dolar; ``.dataframe`` kok tabloyu gosterir.

    Raises:
        TypeError: Taninmayan bir anahtar kelime verildiginde.

    Example:
        >>> result = generate("credit card transactions with fraud",
        ...                   rows=10_000, provider="ollama")
        >>> len(result.dataframe)
        10000

        Cok tablolu:

        >>> result = generate("saas billing", rows=5_000, relational=True)
        >>> sorted(result.tables)
        ['customers', 'invoices', 'subscriptions']
        >>> result.report["relational"]["pass"]
        True

        Projeden veri seti:

        >>> result = generate(project="predict which subscribers churn next month")
        >>> result.plan.target.label()
        'customers.churned'
        >>> [e.column for e in result.plan.excluded_leakage]
        ['cancellation_reason']
    """
    project = kwargs.get("project", "")
    if not domain and not project:
        raise TypeError("generate() needs either 'domain' or 'project'")
    # Proje modunda job kaydi ve raporlar proje metnini tasir.
    cfg = build_config(domain or project, **kwargs)
    iterator = run_pipeline(cfg, cancel_event, llm_client=llm_client)

    while True:
        try:
            event = next(iterator)
        except StopIteration as stop:
            return stop.value
        if on_progress is not None:
            on_progress(event)


def validate(
    df: "pd.DataFrame",
    schema: Any,
    *,
    seed_df: Optional["pd.DataFrame"] = None,
    **kwargs: Any,
) -> Tuple["pd.DataFrame", Dict[str, Any]]:
    """Elinizdeki bir DataFrame'i Discriminator hattindan gecirir.

    Uretim adimini atlar; yalnizca temizlik ve dogrulama calisir. Boylece
    baska bir kaynaktan gelen veriyi de ayni kalite kapisindan gecirebilirsiniz.

    Args:
        df: Denetlenecek veri.
        schema: :class:`SchemaContract` ornegi ya da ondan uretilebilecek bir
            sozluk / JSON metni.
        seed_df: Varsa KS dagilim kiyasi icin referans veri.
        **kwargs: :func:`ai_data_studio.core.validator.run_validation`
            parametreleri (z_threshold, contamination, correlation_guard, ...).

    Returns:
        ``(temiz_dataframe, rapor)`` ikilisi.
    """
    if not isinstance(schema, SchemaContract):
        if isinstance(schema, str):
            schema = SchemaContract.from_json(schema)
        else:
            schema = SchemaContract.from_dict(schema)
    return validator.run_validation(df, schema, seed_df=seed_df, **kwargs)



def compile_dataset(
    contract: Any,
    *,
    rows: Optional[int] = None,
    seed: Optional[int] = None,
) -> Any:
    """Verilen DatasetContract veya SchemaContract'ı (veya sözlük temsilini)
    100% yerel, çevrimdışı ve deterministik olarak pandas DataFrame(ler)ine derler.

    Jupyter Notebook veya script içinde tek satırda kullanım sağlar::

        from ai_data_studio import compile_dataset

        # Çok tablolu (ilişkisel) sözleşme:
        tables = compile_dataset(dataset_dict, rows=10_000)
        # tables['customers'], tables['orders']

        # Tek tablolu sözleşme:
        df = compile_dataset(schema_dict, rows=50_000)
    """
    from .core.dataset_contract import DatasetContract
    from .core.parametric_engine import compile_dataset_to_dataframes, compile_schema_to_dataframe
    from .core.schema_contract import SchemaContract

    if isinstance(contract, DatasetContract):
        return compile_dataset_to_dataframes(contract, root_rows=rows, seed=seed)
    if isinstance(contract, SchemaContract):
        return compile_schema_to_dataframe(contract, n_rows=rows, seed=seed)
    if isinstance(contract, dict):
        contract_copy = dict(contract)
        if "tables" in contract_copy:
            if "domain" not in contract_copy:
                contract_copy["domain"] = "synthetic_dataset"
            raw_tables = []
            for t in contract_copy.get("tables", []):
                if isinstance(t, dict):
                    t_copy = dict(t)
                    if "domain" not in t_copy:
                        t_copy["domain"] = t_copy.get("name", "table")
                    raw_tables.append(t_copy)
                else:
                    raw_tables.append(t)
            contract_copy["tables"] = raw_tables
            if "root_table" not in contract_copy and raw_tables:
                first = raw_tables[0]
                contract_copy["root_table"] = first.get("name", "") if isinstance(first, dict) else getattr(first, "name", "")
            dc = DatasetContract.from_dict(contract_copy)
            return compile_dataset_to_dataframes(dc, root_rows=rows, seed=seed)

        if "domain" not in contract_copy:
            contract_copy["domain"] = "synthetic_data"
        sc = SchemaContract.from_dict(contract_copy)
        return compile_schema_to_dataframe(sc, n_rows=rows, seed=seed)
    raise TypeError(
        "compile_dataset() expects a DatasetContract, SchemaContract or dict, got %s"
        % type(contract).__name__
    )


def compile_schema(
    schema: Any,
    *,
    rows: Optional[int] = None,
    seed: Optional[int] = None,
) -> "pd.DataFrame":
    """Verilen SchemaContract'ı (veya sözlük temsilini) tek bir DataFrame'e derler."""
    from .core.parametric_engine import compile_schema_to_dataframe
    from .core.schema_contract import SchemaContract

    if isinstance(schema, SchemaContract):
        return compile_schema_to_dataframe(schema, n_rows=rows, seed=seed)
    if isinstance(schema, dict):
        s_copy = dict(schema)
        if "domain" not in s_copy:
            s_copy["domain"] = "synthetic_data"
        sc = SchemaContract.from_dict(s_copy)
        return compile_schema_to_dataframe(sc, n_rows=rows, seed=seed)
    raise TypeError(
        "compile_schema() expects a SchemaContract or dict, got %s"
        % type(schema).__name__
    )
