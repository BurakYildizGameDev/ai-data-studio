# -*- coding: utf-8 -*-
"""Şema Mühendisi Ajanı (SchemaEngineerAgent).

Ajan konseyinin (Domain Analyst, Statistician, Adversarial Critic) vardığı
konsensüsü resmi ve doğrulanabilir bir SchemaContract / DatasetContract
sözleşmesine dönüştüren uzman ajan.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Union

from ..core.dataset_contract import DatasetContract
from ..core.schema_contract import SchemaContract, extract_json_block
from .base_agent import AgentMessage, BaseAgent, MessageType

log = logging.getLogger(__name__)

SCHEMA_ENGINEER_SYSTEM_PROMPT = """You are a Senior Data Engineer and Contract Compiler.

Your role in the Multi-Agent Council is to take the consensus reached by Domain Analyst, Statistician, and Adversarial Critic, and compile it into a STRICT, production-ready SchemaContract or DatasetContract JSON.

CRITICAL SPECIFICATION REQUIREMENTS:
1. Every column must have:
   - "name": valid snake_case identifier (letters, digits, underscore; no leading digit).
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
    ) -> Union[DatasetContract, SchemaContract]:
        """Ajanların üzerinde anlaştığı verileri resmi sözleşmeye dönüştürür."""
        user_prompt = (
            f"Mode: {'Relational (DatasetContract)' if relational else 'Single Table (SchemaContract)'}\n"
            f"Row Count: {row_count}, Seed: {seed}, Locale: {locale}\n\n"
            f"1. Domain Model:\n{json.dumps(domain_proposal, indent=2)}\n\n"
            f"2. Statistical Parameters:\n{json.dumps(statistical_proposal, indent=2)}\n\n"
            f"3. Critic Audit (Approved):\n{json.dumps(audit_report, indent=2)}\n\n"
            f"Compile this approved consensus into the strict Contract JSON now."
        )
        raw = self.call_llm(user_prompt)
        data = extract_json_block(raw)

        if relational:
            data["random_seed"] = seed
            contract = DatasetContract.from_dict(data)
            root = contract.table(contract.root_table)
            root.row_count_target = row_count
            for table in contract.tables:
                table.faker_locale = locale
                table.random_seed = seed
            self.send("Council", f"Compiled DatasetContract with {len(contract.tables)} tables", MessageType.APPROVAL)
            return contract
        else:
            # Tek tablo
            if "columns" not in data and "tables" in data and len(data["tables"]) > 0:
                # Eger LLM tek tabloda da tables dizisi vermisse ilkini al
                data = data["tables"][0]
            data["row_count_target"] = row_count
            data["random_seed"] = seed
            data["faker_locale"] = locale
            schema = SchemaContract.from_dict(data)
            self.send("Council", f"Compiled SchemaContract with {len(schema.columns)} columns", MessageType.APPROVAL)
            return schema
