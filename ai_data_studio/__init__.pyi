"""Tip stub'i - calisma zamaninda tembel yuklenen genel API'yi statik olarak acar.

``__init__.py`` bu isimleri PEP 562 ``__getattr__`` ile cozer; tip denetleyiciler
ve IDE'ler ise bu dosyayi okur.
"""
from .api import build_config as build_config
from .api import compile_dataset as compile_dataset
from .api import compile_schema as compile_schema
from .api import generate as generate
from .api import validate as validate
from .core.orchestrator import ENGINE_AUTO as ENGINE_AUTO
from .core.orchestrator import ENGINE_LLM as ENGINE_LLM
from .core.orchestrator import ENGINE_PARAMETRIC as ENGINE_PARAMETRIC
from .core.orchestrator import PipelineCancelled as PipelineCancelled
from .core.orchestrator import PipelineConfig as PipelineConfig
from .core.orchestrator import PipelineResult as PipelineResult
from .core.orchestrator import run_pipeline as run_pipeline
from .core.dataset_contract import DatasetContract as DatasetContract
from .core.dataset_contract import Relationship as Relationship
from .core.project_planner import ProjectPlan as ProjectPlan
from .core.schema_contract import SchemaContract as SchemaContract

__version__: str
__all__: list[str]
