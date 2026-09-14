# -*- coding: utf-8 -*-
"""Şema Mühendisi Ajanı (SchemaEngineerAgent).

Ajan konseyinin (Domain Analyst, Statistician, Adversarial Critic) vardığı
konsensüsü resmi ve doğrulanabilir bir SchemaContract / DatasetContract
sözleşmesine dönüştüren uzman ajan.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Union

from ..core.dataset_contract import DatasetContract
from ..core.schema_contract import SchemaContract, extract_json_block
from .base_agent import AgentMessage, BaseAgent, MessageType

log = logging.getLogger(__name__)

SCHEMA_ENGINEER_SYSTEM_PROMPT = """You are a Senior Data Engineer and Contract Compiler.

Your role in the Multi-Agent Council is to take the consensus reached by Domain Analyst, Statistician, and Adversarial Critic, and compile it into a STRICT, production-ready SchemaContract or DatasetContract JSON.

CRITICAL SPECIFICATION REQUIREMENTS:
1. Every column must have:
   - "name": valid pure ASCII snake_case English identifier (letters, digits, underscore; no leading digit; pure ASCII English regardless of user prompt language).
   - "type": "int" | "float" | "bool" | "str" | "category" | "datetime".
   - "distribution": "normal" | "uniform" | "lognormal" | "exponential" | "poisson" | "gamma" | "tweedie" | "zip" | "gpd" | "pareto" | "categorical".
   - "mean" (REQUIRED when distribution is "normal").
   - "categories" (REQUIRED when type is "category", must be non-empty list of strings).
   - "target_ratio" (for boolean target columns, 0.0 to 1.0).
2. "business_rules": list of pandas df.eval() expressions (e.g. "age >= 18", "end_date >= start_date").
3. "correlations": list of objects with {"columns": ["col_a", "col_b"], "expected_sign": "positive"|"negative", "min_r": <float>, "method": "pearson"|"spearman"}.
4. Output format:
   - If single table: Root JSON must have "domain", "description", "row_count_target", "random_seed", "columns", "business_rules", "correlations".
   - If relational: Root JSON must have "domain", "description", "root_table", "tables" (array of table schemas with primary_key), "relationships" (array of parent-child foreign keys).

Return ONLY valid JSON. No prose, no markdown fences."""


def _domain_slug(*candidates: Any) -> str:
    """Modelin unuttuğu ``domain`` için ASCII snake_case bir ad (dosya adlarında kullanılır)."""
    for candidate in candidates:
        if isinstance(candidate, str):
            slug = re.sub(r"[^a-z0-9]+", "_", candidate.lower()).strip("_")[:40].rstrip("_")
            if slug:
                return slug
    return "synthetic_data"


class SchemaEngineerAgent(BaseAgent):
    """Konsensüsü resmi SchemaContract/DatasetContract nesnesine derleyen uzman ajan."""

    def __init__(self, llm_client=None, temperature: float = 0.2):
        super().__init__(
            name="SchemaEngineer",
            role="Senior Data Engineer & Contract Compiler",
            system_prompt=SCHEMA_ENGINEER_SYSTEM_PROMPT,
            llm_client=llm_client,
            temperature=temperature,
        )

    def compile(
        self,
        domain_proposal: Dict[str, Any],
        statistical_proposal: Dict[str, Any],
        audit_report: Dict[str, Any],
        row_count: int = 1000,
        seed: int = 42,
        locale: str = "en_US",
        relational: bool = False,
        domain_prompt: str = "",
    ) -> Union[DatasetContract, SchemaContract]:
        """Ajanların üzerinde anlaştığı verileri resmi sözleşmeye dönüştürür.

        Ana şema yolu ile aynı üret -> doğrula -> hatayı geri besle döngüsünü
        (``BaseLLMClient._generate_validated``) kullanır. Önceden tek atışta
        ``from_dict`` çağrılıyordu: ``qwen2.5-coder:1.5b`` ile 3 koşunun 3'ü
        modelin ``domain`` alanını unutması yüzünden bu adımda düştü.
        """
        user_prompt = (
            f"Mode: {'Relational (DatasetContract)' if relational else 'Single Table (SchemaContract)'}\n"
            f"Row Count: {row_count}, Seed: {seed}, Locale: {locale}\n\n"
            f"1. Domain Model:\n{json.dumps(domain_proposal, indent=2)}\n\n"
            f"2. Statistical Parameters:\n{json.dumps(statistical_proposal, indent=2)}\n\n"
            f"3. Critic Audit (Approved):\n{json.dumps(audit_report, indent=2)}\n\n"
            f"Compile this approved consensus into the strict Contract JSON now."
        )
        # Alan bizde zaten belli; yalnızca onu unuttu diye bir LLM turu harcanmaz.
        fallback_domain = _domain_slug(domain_proposal.get("domain")
                                       if isinstance(domain_proposal, dict) else None,
                                       domain_prompt)

        def parse(raw: str) -> Union[DatasetContract, SchemaContract]:
            data = extract_json_block(raw)
            if relational:
                data.setdefault("domain", fallback_domain)
                data["random_seed"] = seed
                contract = DatasetContract.from_dict(data)
                root = contract.table(contract.root_table)
                root.row_count_target = row_count
                for table in contract.tables:
                    table.faker_locale = locale
                    table.random_seed = seed
                return contract
            if "columns" not in data and isinstance(data.get("tables"), list) and data["tables"]:
                # Model tek tabloda da tables dizisi verdiyse ilkini al.
                table = dict(data["tables"][0])
                table.setdefault("domain", data.get("domain"))
                data = table
            if not isinstance(data.get("domain"), str) or not data["domain"].strip():
                data["domain"] = fallback_domain
            data["row_count_target"] = row_count
            data["random_seed"] = seed
            data["faker_locale"] = locale
            return SchemaContract.from_dict(data)

        system = self.system_prompt
        if self.llm_client is None:
            raise RuntimeError(f"Agent '{self.name}' için LLM istemcisi tanımlanmamış.")
        result = self.llm_client._generate_validated(
            system, user_prompt, 8000, parse,
            "Dataset Contract" if relational else "Şema",
            "service.error.contract_retries" if relational else "service.error.schema_retries")

        if isinstance(result, DatasetContract):
            self.send("Council", f"Compiled DatasetContract with {len(result.tables)} tables",
                      MessageType.APPROVAL)
        else:
            self.send("Council", f"Compiled SchemaContract with {len(result.columns)} columns",
                      MessageType.APPROVAL)
        return result
