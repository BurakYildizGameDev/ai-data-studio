"""AI Synthetic Data Studio - LLM tabanli sentetik veri uretimi ve validasyonu.

Hizli baslangic::

    from ai_data_studio import generate

    result = generate("e-commerce orders with churn", rows=50_000, provider="ollama")
    print(result.dataframe.head())
    print(result.report["retention_pct"])

Elinizde zaten veri varsa yalnizca dogrulama hattini kosturabilirsiniz::

    from ai_data_studio import validate

    clean, report = validate(df, schema_dict)

Isimler tembel yuklenir (PEP 562): ``import ai_data_studio`` pandas'i ve
saglayici SDK'larini ceki almaz, ilk erisimde yuklenirler. Bu modul bilerek
``typing``'i de ice almaz (tek basina ~10 ms); statik tipler ``__init__.pyi``
stub dosyasindan gelir.
"""
from __future__ import annotations

__version__ = "2.0.0"

# Genel isim -> (modul, modul icindeki isim)
_EXPORTS = {
    "generate": ("ai_data_studio.api", "generate"),
    "validate": ("ai_data_studio.api", "validate"),
    "build_config": ("ai_data_studio.api", "build_config"),
    "PipelineConfig": ("ai_data_studio.core.orchestrator", "PipelineConfig"),
    "PipelineResult": ("ai_data_studio.core.orchestrator", "PipelineResult"),
    "PipelineCancelled": ("ai_data_studio.core.orchestrator", "PipelineCancelled"),
    "run_pipeline": ("ai_data_studio.core.orchestrator", "run_pipeline"),
    "SchemaContract": ("ai_data_studio.core.schema_contract", "SchemaContract"),
    "DatasetContract": ("ai_data_studio.core.dataset_contract", "DatasetContract"),
    "Relationship": ("ai_data_studio.core.dataset_contract", "Relationship"),
    "ProjectPlan": ("ai_data_studio.core.project_planner", "ProjectPlan"),
    "ENGINE_LLM": ("ai_data_studio.core.orchestrator", "ENGINE_LLM"),
    "ENGINE_PARAMETRIC": ("ai_data_studio.core.orchestrator", "ENGINE_PARAMETRIC"),
    "ENGINE_AUTO": ("ai_data_studio.core.orchestrator", "ENGINE_AUTO"),
}

__all__ = ["__version__", *sorted(_EXPORTS)]


def __getattr__(name: str):
    """Genel API isimlerini ilk erisimde yukler (PEP 562)."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError("module %r has no attribute %r" % (__name__, name))
    from importlib import import_module

    value = getattr(import_module(target[0]), target[1])
    globals()[name] = value          # sonraki erisimler dogrudan gelsin
    return value


def __dir__():
    return sorted(__all__)
