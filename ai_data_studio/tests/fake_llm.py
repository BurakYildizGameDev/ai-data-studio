"""Test için sahte LLM istemcileri - gerçek API çağrısı yapmadan pipeline koşturur.

BaseLLMClient._complete() yerine onceden hazirlanmis yanitlar dondururler; böylece
self-healing dongusu, orchestrator ve GUI entegrasyonu API key olmadan test edilebilir.
"""
from __future__ import annotations

import json
from typing import List, Optional

from ..services.llm_base import BaseLLMClient

SCHEMA_JSON = {
    "domain": "ecommerce_orders",
    "description": "Synthetic e-commerce order lines with customer age and basket value.",
    "row_count_target": 20000,
    "random_seed": 42,
    "columns": [
        {"name": "customer_age", "type": "int", "min": 18, "max": 80,
         "distribution": "normal", "mean": 38, "std": 12,
         "description": "Age of the ordering customer"},
        {"name": "basket_value", "type": "float", "min": 0, "max": 5000,
         "distribution": "lognormal", "description": "Total order value"},
        {"name": "item_count", "type": "int", "min": 1, "max": 30,
         "description": "Number of items in the order"},
        {"name": "shipping_cost", "type": "float", "min": 0, "max": 100,
         "description": "Shipping fee charged"},
        {"name": "returned", "type": "bool", "target_ratio": 0.08,
         "description": "Whether the order was returned"},
    ],
    "business_rules": [
        "shipping_cost <= basket_value",
        "not (item_count > 20 and basket_value < 50)",
    ],
    "correlations": [
        {"columns": ["item_count", "basket_value"], "expected_sign": "positive", "min_r": 0.3}
    ],
}

# Semaya uyan, kasitli gurultu iceren gecerli uretici kod.
GOOD_CODE = '''
import numpy as np
import pandas as pd


def generate_data(n_rows, seed):
    rng = np.random.default_rng(seed)

    customer_age = np.clip(rng.normal(38, 12, n_rows), 18, 80).astype(int)
    item_count = np.clip(rng.poisson(4, n_rows) + 1, 1, 30).astype(int)
    basket_value = np.clip(
        item_count * rng.lognormal(3.0, 0.6, n_rows), 0, 5000
    )
    shipping_cost = np.clip(rng.uniform(0, 25, n_rows), 0, 100)
    returned = rng.random(n_rows) < 0.08

    df = pd.DataFrame({
        "customer_age": customer_age,
        "basket_value": basket_value,
        "item_count": item_count,
        "shipping_cost": shipping_cost,
        "returned": returned,
    })

    # Gercekci gurultu: is kuralı ihlalleri ve aykırı degerler
    idx = rng.choice(n_rows, size=max(1, int(n_rows * 0.06)), replace=False)
    df.loc[idx, "shipping_cost"] = df.loc[idx, "basket_value"] + 10.0
    idx = rng.choice(n_rows, size=max(1, int(n_rows * 0.03)), replace=False)
    df.loc[idx, "customer_age"] = rng.integers(90, 130, len(idx))
    return df
'''

# Calisirken patlayan kod (self-healing testleri icin).
BROKEN_RUNTIME_CODE = '''
import numpy as np
import pandas as pd


def generate_data(n_rows, seed):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"customer_age": rng.normal(38, 12, n_rows) / 0 * np.nan}) + undefined_name
'''

# Calisan ama semaya uymayan kod (eksik kolonlar).
SCHEMA_MISMATCH_CODE = '''
import numpy as np
import pandas as pd


def generate_data(n_rows, seed):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"customer_age": np.clip(rng.normal(38, 12, n_rows), 18, 80).astype(int)})
'''

# Sandbox politikasini ihlal eden kod.
FORBIDDEN_IMPORT_CODE = '''
import os
import pandas as pd


def generate_data(n_rows, seed):
    os.system("dir")
    return pd.DataFrame({"customer_age": [30] * n_rows})
'''


class FakeLLMClient(BaseLLMClient):
    """Onceden belirlenmis yanitlari sırayla dondurur.

    Args:
        code_sequence: generate_code + her fix_code cagrisinda dondurulecek kodlar.
        schema_override: şema uretiminde dondurulecek ham JSON metni.
    """

    provider = "fake"

    def __init__(self, code_sequence: Optional[List[str]] = None,
                 schema_override: Optional[str] = None,
                 model: str = "fake-model", **kwargs):
        super().__init__(model, **kwargs)
        self.code_sequence = list(code_sequence or [GOOD_CODE])
        self.schema_override = schema_override
        self.calls: List[str] = []
        self.feedback_received: List[str] = []
        self._code_index = 0

    def health_check(self) -> bool:
        return True

    def _next_code(self) -> str:
        code = self.code_sequence[min(self._code_index, len(self.code_sequence) - 1)]
        self._code_index += 1
        return code

    def _complete(self, system: str, user: str, max_tokens: int = 16000,
                  temperature=None) -> str:
        self.calls.append(system[:40])
        # Sema uretimi
        if "Schema Contract" in system and "JSON" in system:
            if self.schema_override is not None:
                return self.schema_override
            return "Here is your schema:\n```json\n%s\n```" % json.dumps(SCHEMA_JSON)
        # Kod duzeltme
        if "debugging" in system:
            self.feedback_received.append(user)
            return self._next_code()
        # Dataset card
        if "dataset cards" in system:
            return "---\nlicense: mit\n---\n\n# Fake card\n"
        # Ilk kod uretimi
        return self._next_code()


# --------------------------------------------------------------------------- #
# Iliskisel (cok tablolu) sahte istemci
# --------------------------------------------------------------------------- #
DATASET_CONTRACT_JSON = {
    "domain": "saas_billing",
    "description": "Customers and the orders they placed.",
    "root_table": "customers",
    "random_seed": 42,
    "tables": [
        {
            "name": "customers",
            "domain": "customers",
            "row_count_target": 2000,
            "primary_key": "customer_id",
            "columns": [
                {"name": "customer_id", "type": "int", "min": 1, "max": 10 ** 9,
                 "description": "Surrogate key"},
                {"name": "tenure_months", "type": "int", "min": 0, "max": 120,
                 "description": "Months since signup"},
                {"name": "monthly_fee", "type": "float", "min": 0, "max": 500,
                 "distribution": "lognormal", "description": "Subscription fee"},
            ],
        },
        {
            "name": "orders",
            "domain": "orders",
            "row_count_target": 6000,
            "primary_key": "order_id",
            "foreign_keys": ["customer_id"],
            "columns": [
                {"name": "order_id", "type": "int", "min": 1, "max": 10 ** 9,
                 "description": "Surrogate key"},
                {"name": "customer_id", "type": "int", "min": 1, "max": 10 ** 9,
                 "description": "Owning customer"},
                {"name": "amount", "type": "float", "min": 0, "max": 5000,
                 "distribution": "gamma", "description": "Order total"},
                {"name": "item_count", "type": "int", "min": 1, "max": 30,
                 "description": "Line items"},
            ],
            "correlations": [
                {"columns": ["item_count", "amount"], "expected_sign": "positive",
                 "min_r": 0.3}
            ],
        },
    ],
    "relationships": [
        {"parent_table": "customers", "parent_key": "customer_id",
         "child_table": "orders", "child_key": "customer_id",
         "mean_per_parent": 3.0, "min_per_parent": 0, "max_per_parent": 50},
    ],
}

# Yabanci anahtari ebeveynin GERCEK anahtar dizisinden tureten dogru kod.
GOOD_RELATIONAL_CODE = '''
import numpy as np
import pandas as pd


def generate_dataset(n_rows, seed):
    rng = np.random.default_rng(seed)

    customer_id = np.arange(1, n_rows + 1)
    customers = pd.DataFrame({
        "customer_id": customer_id,
        "tenure_months": rng.integers(0, 120, n_rows),
        "monthly_fee": np.clip(rng.lognormal(3.4, 0.5, n_rows), 0, 500),
    })

    per_customer = rng.poisson(3.0, n_rows).clip(0, 50)
    owner = np.repeat(customer_id, per_customer)
    n_orders = owner.size
    item_count = np.clip(rng.poisson(4, n_orders) + 1, 1, 30).astype(int)
    amount = np.clip(item_count * rng.gamma(2.0, 18.0, n_orders), 0, 5000)
    orders = pd.DataFrame({
        "order_id": np.arange(1, n_orders + 1),
        "customer_id": owner,
        "amount": amount,
        "item_count": item_count,
    })
    return {"customers": customers, "orders": orders}
'''

# Yabanci anahtari uyduran kod: yetim satir uretir (onarim testleri icin).
ORPHAN_RELATIONAL_CODE = '''
import numpy as np
import pandas as pd


def generate_dataset(n_rows, seed):
    rng = np.random.default_rng(seed)

    customer_id = np.arange(1, n_rows + 1)
    customers = pd.DataFrame({
        "customer_id": customer_id,
        "tenure_months": rng.integers(0, 120, n_rows),
        "monthly_fee": np.clip(rng.lognormal(3.4, 0.5, n_rows), 0, 500),
    })

    n_orders = n_rows * 3
    item_count = np.clip(rng.poisson(4, n_orders) + 1, 1, 30).astype(int)
    amount = np.clip(item_count * rng.gamma(2.0, 18.0, n_orders), 0, 5000)
    # Kasitli hata: anahtarlar ebeveyn dizisinden degil, genis bir araliktan.
    orders = pd.DataFrame({
        "order_id": np.arange(1, n_orders + 1),
        "customer_id": rng.integers(1, n_rows * 2, n_orders),
        "amount": amount,
        "item_count": item_count,
    })
    return {"customers": customers, "orders": orders}
'''


class FakeRelationalLLMClient(BaseLLMClient):
    """Iliskisel sozlesme + cok tablolu uretici kod dondurur.

    Prompt ayrimi sistem metnine bakarak yapilir; boylece ayni istemci hem
    ``generate_dataset_schema`` hem ``generate_dataset_code`` cagrilarina yanit verir.
    """

    provider = "fake"

    def __init__(self, code_sequence: Optional[List[str]] = None,
                 contract_override: Optional[str] = None,
                 model: str = "fake-model", **kwargs):
        super().__init__(model, **kwargs)
        self.code_sequence = list(code_sequence or [GOOD_RELATIONAL_CODE])
        self.contract_override = contract_override
        self.calls: List[str] = []
        self._code_index = 0

    def health_check(self) -> bool:
        return True

    def _next_code(self) -> str:
        code = self.code_sequence[min(self._code_index, len(self.code_sequence) - 1)]
        self._code_index += 1
        return code

    def _complete(self, system: str, user: str, max_tokens: int = 16000,
                  temperature=None) -> str:
        if "NORMALISED RELATIONAL" in system:
            self.calls.append("dataset_schema")
            if self.contract_override is not None:
                return self.contract_override
            return "```json\n%s\n```" % json.dumps(DATASET_CONTRACT_JSON)
        if "debugging" in system:
            self.calls.append("fix_code")
            return self._next_code()
        if "dataset cards" in system:
            return "---\nlicense: mit\n---\n\n# Fake card\n"
        self.calls.append("dataset_code")
        return self._next_code()


# --------------------------------------------------------------------------- #
# Proje planlayici sahte istemcisi
# --------------------------------------------------------------------------- #
PROJECT_PLAN_JSON = {
    "rationale": "Churn tahmini icin musteri ozellikleri ve siparis gecmisi gerekir.",
    "task_type": "binary_classification",
    "target": {"table": "customers", "column": "churned"},
    "positive_class_ratio": 0.2,
    "excluded_leakage": [
        {"column": "cancellation_reason",
         "reason": "yalnizca musteri ayrildiktan sonra doldurulur"},
        {"column": "refund_issued_at",
         "reason": "churn sonrasi olay; hedefi dogrudan ele verir"},
    ],
    "split": {"kind": "temporal", "column": "signup_at", "table": "customers",
              "reason": "gelecegi tahmin ediyoruz; rastgele bolme zaman sizdirir"},
    "dataset": {
        "domain": "saas_churn",
        "root_table": "customers",
        "random_seed": 42,
        "tables": [
            {
                "name": "customers", "domain": "customers", "row_count_target": 2000,
                "primary_key": "customer_id",
                "columns": [
                    {"name": "customer_id", "type": "int", "min": 1, "max": 10 ** 9},
                    {"name": "signup_at", "type": "datetime",
                     "description": "kayit tarihi, 2021-01-01 ile 2024-12-31 arasi"},
                    {"name": "tenure_months", "type": "int", "min": 0, "max": 120},
                    {"name": "monthly_fee", "type": "float", "min": 0, "max": 500,
                     "distribution": "lognormal"},
                    {"name": "churned", "type": "bool"},
                ],
            },
            {
                "name": "orders", "domain": "orders", "row_count_target": 6000,
                "primary_key": "order_id", "foreign_keys": ["customer_id"],
                "columns": [
                    {"name": "order_id", "type": "int", "min": 1, "max": 10 ** 9},
                    {"name": "customer_id", "type": "int", "min": 1, "max": 10 ** 9},
                    {"name": "amount", "type": "float", "min": 0, "max": 5000,
                     "distribution": "gamma"},
                    {"name": "item_count", "type": "int", "min": 1, "max": 30},
                ],
                "correlations": [
                    {"columns": ["item_count", "amount"], "expected_sign": "positive",
                     "min_r": 0.3}
                ],
            },
        ],
        "relationships": [
            {"parent_table": "customers", "parent_key": "customer_id",
             "child_table": "orders", "child_key": "customer_id",
             "mean_per_parent": 3.0, "min_per_parent": 0, "max_per_parent": 50},
        ],
    },
}

PLANNED_DATASET_CODE = '''
import numpy as np
import pandas as pd


def generate_dataset(n_rows, seed):
    rng = np.random.default_rng(seed)

    customer_id = np.arange(1, n_rows + 1)
    signup_at = pd.Timestamp("2021-01-01") + pd.to_timedelta(
        rng.integers(0, 1460, n_rows), unit="D")
    customers = pd.DataFrame({
        "customer_id": customer_id,
        "signup_at": signup_at,
        "tenure_months": rng.integers(0, 120, n_rows),
        "monthly_fee": np.clip(rng.lognormal(3.4, 0.5, n_rows), 0, 500),
        "churned": rng.random(n_rows) < 0.2,
    })

    per_customer = rng.poisson(3.0, n_rows).clip(0, 50)
    owner = np.repeat(customer_id, per_customer)
    n_orders = owner.size
    item_count = np.clip(rng.poisson(4, n_orders) + 1, 1, 30).astype(int)
    amount = np.clip(item_count * rng.gamma(2.0, 18.0, n_orders), 0, 5000)
    orders = pd.DataFrame({
        "order_id": np.arange(1, n_orders + 1),
        "customer_id": owner,
        "amount": amount,
        "item_count": item_count,
    })
    return {"customers": customers, "orders": orders}
'''


class FakePlannerLLMClient(BaseLLMClient):
    """Proje plani + cok tablolu uretici kod dondurur."""

    provider = "fake"

    def __init__(self, code_sequence: Optional[List[str]] = None,
                 plan_override: Optional[str] = None,
                 model: str = "fake-model", **kwargs):
        super().__init__(model, **kwargs)
        self.code_sequence = list(code_sequence or [PLANNED_DATASET_CODE])
        self.plan_override = plan_override
        self.calls: List[str] = []
        self._code_index = 0

    def health_check(self) -> bool:
        return True

    def _next_code(self) -> str:
        code = self.code_sequence[min(self._code_index, len(self.code_sequence) - 1)]
        self._code_index += 1
        return code

    def _complete(self, system: str, user: str, max_tokens: int = 16000,
                  temperature=None) -> str:
        if "PROJECT" in system and "DESCRIPTION" in system:
            self.calls.append("project_plan")
            if self.plan_override is not None:
                return self.plan_override
            return "```json\n%s\n```" % json.dumps(PROJECT_PLAN_JSON)
        if "debugging" in system:
            self.calls.append("fix_code")
            return self._next_code()
        if "dataset cards" in system:
            return "---\nlicense: mit\n---\n\n# Fake card\n"
        self.calls.append("dataset_code")
        return self._next_code()
