# -*- coding: utf-8 -*-
"""Karşıt Eleştirmen ve Uyum Ajanı (AdversarialCriticAgent).

Şeytanın avukatı (Red Team) rolünü üstlenerek şemayı veri sızıntısı (target leakage),
çelişkili iş kuralları, istatistiksel tutarsızlıklar ve HIPAA/KVKK ihlalleri açısından
amansızca denetleyen uzman ajan.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..core.schema_contract import extract_json_block
from .base_agent import AgentMessage, BaseAgent, MessageType

log = logging.getLogger(__name__)

ADVERSARIAL_CRITIC_SYSTEM_PROMPT = """You are the Chief Data Auditor and Adversarial Red-Team Critic for a synthetic data studio.

Your sole duty is to CHALLENGE and CRITIQUE the dataset schema proposed by the Domain Analyst and Statistician.
You must rigorously check for:

1. TARGET LEAKAGE (Critical):
   Are there features that would only be known AFTER the target/outcome event occurs?
   Examples of leakage:
   - "chargeback_date" or "fraud_case_closed" in an "is_fraud" detection dataset.
   - "death_certificate_signed" in an "in_hospital_mortality" dataset.
   - "churn_reason" in a "customer_churn" dataset.
   If target leakage is found, name the column and demand its exclusion!

2. BUSINESS RULE CONTRADICTIONS:
   Are there conflicting constraints or rules that are mathematically impossible to satisfy?
   Examples: min > max, rules referencing non-existent columns, circular dependencies.

3. STATISTICAL FEASIBILITY:
   - Does a strictly positive distribution (Gamma, Lognormal, Pareto) have negative bounds?
   - Do correlation pairs reference non-numeric/non-bool columns?
   - Are category lists empty for "category" types?

4. REGULATORY & PRIVACY RISKS (HIPAA / GDPR / KVKK):
   Are there raw personal identifiers (e.g. raw SSN, unmasked full name, direct national ID) that violate HIPAA Safe Harbor 18 or privacy standards?

STRICT RULES:
- Output ONLY valid JSON. No prose, no markdown fences.
- The JSON structure MUST be:
{
  "approved": true | false,
  "confidence_score": <float between 0.0 and 1.0>,
  "leakage_findings": [
    {"column": "<col_name>", "reason": "<why it leaks>", "severity": "HIGH"|"MEDIUM"|"LOW"}
  ],
  "rule_conflicts": [
    {"rule": "<rule_expression>", "problem": "<why it is contradictory>"}
  ],
  "compliance_issues": [
    {"issue": "<description>", "recommendation": "<fix>"}
  ],
  "verdict_summary": "<concise 1-2 sentence verdict>"
}
"""


class AdversarialCriticAgent(BaseAgent):
    """Veri sızıntısı ve kural çelişkilerini denetleyen karşıt eleştirmen ajan."""

    def __init__(self, llm_client=None, temperature: float = 0.2):
        super().__init__(
            name="AdversarialCritic",
            role="Chief Data Auditor & Red Team Critic",
            system_prompt=ADVERSARIAL_CRITIC_SYSTEM_PROMPT,
            llm_client=llm_client,
            temperature=temperature,
        )

    def audit(
        self,
        domain_prompt: str,
        proposal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Taslağı denetler; onay (approved=True) veya eleştiri raporu döndürür."""
        user_prompt = (
            f"Original Domain Prompt: {domain_prompt}\n\n"
            f"Proposed Architecture and Statistics:\n"
            f"{json.dumps(proposal, indent=2)}\n\n"
            f"Perform rigorous adversarial critique now. Identify any target leakage, rule contradictions, or privacy violations."
        )
        raw = self.call_llm(user_prompt)
        report = extract_json_block(raw)

        is_approved = bool(report.get("approved", False))
        msg_type = MessageType.APPROVAL if is_approved else MessageType.CRITIQUE

        self.send(
            "Council",
            content=report.get("verdict_summary", "Audit completed"),
            message_type=msg_type,
            metadata=report,
        )
        return report
