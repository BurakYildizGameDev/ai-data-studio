# -*- coding: utf-8 -*-
"""Domain Analyst Ajanı (DomainAnalystAgent).

Sektörel gereksinimleri, varlık (entity) modellerini, birincil/yabancıl anahtarları
ve iş kurallarını çıkaran uzman ajan.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..core.schema_contract import extract_json_block
from .base_agent import AgentMessage, BaseAgent, MessageType

log = logging.getLogger(__name__)

DOMAIN_ANALYST_SYSTEM_PROMPT = """You are a Principal Enterprise Data Architect and Domain Modeler.

Your role in the Multi-Agent Council is to analyze the user's business scenario and design the high-level data model:
1. Identify the core entities/tables required (single or relational).
2. For each entity, specify essential columns (identifiers, temporal/dates, numeric metrics, categorical states, and explicit TARGET/OUTCOME columns when applicable).
3. Specify cross-table foreign key relationships if multi-table.
4. Define real-world business constraints and rules that hold true in this domain (e.g. withdrawal_amount <= account_balance, discharge_date >= admission_date).

STRICT RULES:
- Do NOT generate probability distributions or copulas; the Statistician Agent handles that.
- Output ONLY valid JSON representing the domain specification. No prose, no markdown fences.
- The JSON must follow this structure:
{
  "domain": "<snake_case_domain_name>",
  "summary": "<one sentence domain description>",
  "target_column": "<name of primary target/outcome variable or null if unsupervised>",
  "tables": [
    {
      "name": "<table_name>",
      "primary_key": "<pk_column_name>",
      "parent_table": "<parent_name or null>",
      "foreign_key": "<fk_column_name or null>",
      "columns": [
        {
          "name": "<col_name>",
          "type": "int" | "float" | "bool" | "str" | "category" | "datetime",
          "purpose": "<brief role: identifier | demographic | metric | state | target>",
          "categories": ["<cat1>", "<cat2>"], // only if category
          "min": <optional number>,
          "max": <optional number>
        }
      ],
      "business_rules": [
        "<logical condition in pandas df.eval format, e.g. amount > 0>"
      ]
    }
  ]
}
"""

DOMAIN_ANALYST_REVISE_PROMPT = """You previously proposed a domain structure, but the Adversarial Critic Agent rejected/critiqued it.

Original Proposal:
{previous_proposal}

Critique / Deficiencies from Adversarial Critic:
{critique}

Revise the domain model to resolve all reported concerns:
- Drop or replace any leaked target features (target leakage).
- Fix any contradictory business rules.
- Address any regulatory or privacy (HIPAA/KVKK) violations.

Return ONLY the updated valid JSON structure."""


class DomainAnalystAgent(BaseAgent):
    """Domain analizi ve varlık modellemesi yapan uzman ajan."""

    def __init__(self, llm_client=None, temperature: float = 0.4):
        super().__init__(
            name="DomainAnalyst",
            role="Principal Data Architect",
            system_prompt=DOMAIN_ANALYST_SYSTEM_PROMPT,
            llm_client=llm_client,
            temperature=temperature,
        )

    def analyze(
        self,
        domain_prompt: str,
        relational: bool = False,
        seed_summary: str = "",
    ) -> Dict[str, Any]:
        """Kullanıcı istemini inceleyerek ilk varlık ve iş modeli taslağını çıkarır."""
        user_prompt = f"Domain Request: {domain_prompt}\nMode: {'Relational (Multi-table)' if relational else 'Single Table'}\n"
        if seed_summary:
            user_prompt += f"Seed Data Insights:\n{seed_summary}\n"
        user_prompt += "Produce the domain data architecture JSON now."

        raw = self.call_llm(user_prompt)
        data = extract_json_block(raw)
        self.send("Council", json.dumps(data), MessageType.PROPOSAL)
        return data

    def revise(
        self,
        previous_proposal: Dict[str, Any],
        critique_message: str,
    ) -> Dict[str, Any]:
        """Eleştiri geri bildirimini dikkate alarak domain modelini günceller."""
        user_prompt = DOMAIN_ANALYST_REVISE_PROMPT.format(
            previous_proposal=json.dumps(previous_proposal, indent=2),
            critique=critique_message,
        )
        raw = self.call_llm(user_prompt)
        data = extract_json_block(raw)
        self.send("Council", json.dumps(data), MessageType.REVISION)
        return data
