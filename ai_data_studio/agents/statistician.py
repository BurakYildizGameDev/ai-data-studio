# -*- coding: utf-8 -*-
"""İstatistikçi ve Aktüer Ajanı (StatisticianAgent).

Tablodaki kolonlara gerçekçi istatistiksel dağılımları (Tweedie, ZIP, Gamma, Pareto vb.),
sayısal sınırları, hedef korelasyonları ve monotonluk kurallarını atayan uzman ajan.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..core.schema_contract import extract_json_block
from .base_agent import AgentMessage, BaseAgent, MessageType

log = logging.getLogger(__name__)

STATISTICIAN_SYSTEM_PROMPT = """You are a Senior Quantitative Statistician and Actuary.

Your role in the Multi-Agent Council is to take the structural domain proposal produced by the Domain Analyst and enrich it with mathematically sound statistical parameters:
1. Assign appropriate probability distributions to numeric columns:
   - "normal" (requires mean, optional std)
   - "lognormal" (for positively skewed amounts/incomes, requires mean, std)
   - "exponential" (for inter-arrival times/waiting times)
   - "gamma" (for positive claim severity, shape, scale)
   - "poisson" (for event counts)
   - "zip" (zero-inflated poisson for sparse insurance/defect counts, zero_prob, mean)
   - "tweedie" (compound poisson-gamma for pure risk premiums, p_index between 1.1 and 1.9)
   - "pareto" or "gpd" (for heavy-tailed catastrophe/extreme loss values, shape, scale)
   - "uniform" (for random identifiers or flat bounds)
2. Specify realistic bounds: min, max, mean, std.
3. For boolean target/outcome variables, specify "target_ratio" (e.g. 0.02 for imbalanced fraud).
4. Specify pairwise correlations between numeric/bool columns:
   [{"columns": ["driver_col", "outcome_col"], "expected_sign": "positive"|"negative", "min_r": 0.3, "method": "pearson"|"spearman"}]
5. Specify monotonicity rules where business logic requires rank ordering (e.g. higher income -> higher credit limit).

STRICT RULES:
- Output ONLY valid JSON containing the enriched tables with full statistical configurations. No prose, no markdown fences.
- Return the full table structures matching the SchemaContract specification.
"""

STATISTICIAN_REVISE_PROMPT = """You previously designed statistical distributions and correlations, but the Adversarial Critic reported issues.

Current Statistical Proposal:
{previous_proposal}

Adversarial Critic Feedback:
{critique}

Revise the distributions, parameters, and correlations to fix all issues.
Ensure all correlation pairs reference existing numeric/bool columns.
Return ONLY the updated valid JSON."""


class StatisticianAgent(BaseAgent):
    """İstatistiksel modelleme ve dağılım ataması yapan uzman ajan."""

    def __init__(self, llm_client=None, temperature: float = 0.3):
        super().__init__(
            name="Statistician",
            role="Senior Quantitative Statistician & Actuary",
            system_prompt=STATISTICIAN_SYSTEM_PROMPT,
            llm_client=llm_client,
            temperature=temperature,
        )

    def enrich(self, domain_proposal: Dict[str, Any]) -> Dict[str, Any]:
        """Domain Analyst'ın varlık taslağını istatistiksel dağılımlar ve korelasyonlarla zenginleştirir."""
        user_prompt = (
            f"Here is the Domain Analyst's architecture proposal:\n"
            f"{json.dumps(domain_proposal, indent=2)}\n\n"
            f"Assign mathematically rigorous distributions, bounds, correlations, and target ratios now."
        )
        raw = self.call_llm(user_prompt)
        data = extract_json_block(raw)
        self.send("Council", json.dumps(data), MessageType.PROPOSAL)
        return data

    def revise(
        self,
        previous_proposal: Dict[str, Any],
        critique_message: str,
    ) -> Dict[str, Any]:
        """Eleştiri sonrası istatistiksel parametreleri revize eder."""
        user_prompt = STATISTICIAN_REVISE_PROMPT.format(
            previous_proposal=json.dumps(previous_proposal, indent=2),
            critique=critique_message,
        )
        raw = self.call_llm(user_prompt)
        data = extract_json_block(raw)
        self.send("Council", json.dumps(data), MessageType.REVISION)
        return data
