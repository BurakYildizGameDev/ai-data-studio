# -*- coding: utf-8 -*-
"""Çoklu Ajan Konseyi (Multi-Agent Council) Birim Testleri.

Ajanların bağımsız davranışlarını, aralarındaki mesajlaşmayı, karşıt eleştiri
(adversarial critique) döngüsünü, konsensüs mekanizmasını ve orchestrator
entegrasyonunu doğrular.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
import pytest

from ai_data_studio.agents.base_agent import AgentMessage, BaseAgent, MessageType
from ai_data_studio.agents.domain_analyst import DomainAnalystAgent
from ai_data_studio.agents.statistician import StatisticianAgent
from ai_data_studio.agents.adversarial_critic import AdversarialCriticAgent
from ai_data_studio.agents.schema_engineer import SchemaEngineerAgent
from ai_data_studio.agents.council_coordinator import CouncilCoordinator
from ai_data_studio.core.dataset_contract import DatasetContract
from ai_data_studio.core.schema_contract import SchemaContract
from ai_data_studio.services.llm_base import BaseLLMClient


class MockAgentLLM(BaseLLMClient):
    """Ajan testleri için sıralı veya koşullu yanıt dönen sahte LLM."""

    provider = "mock_agent"

    def __init__(self, responses: Optional[List[str]] = None):
        super().__init__(model="mock-agent-v1")
        self.responses: List[str] = list(responses or [])
        self.calls: List[Dict[str, Any]] = []

    def health_check(self) -> bool:
        return True

    def _complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 8000,
        temperature: Optional[float] = None,
    ) -> str:
        self.calls.append({"system": system, "user": user})
        if self.responses:
            return self.responses.pop(0)
        # Varsayılan boş JSON nesnesi
        return "{}"


# --------------------------------------------------------------------------- #
# 1. Base Agent & Messaging Testleri
# --------------------------------------------------------------------------- #
def test_agent_message_creation_and_dict():
    msg = AgentMessage(
        sender="Critic",
        recipient="DomainAnalyst",
        content="Target leakage detected in column 'post_event_status'",
        message_type=MessageType.CRITIQUE,
        metadata={"severity": "HIGH"},
    )
    d = msg.to_dict()
    assert d["sender"] == "Critic"
    assert d["recipient"] == "DomainAnalyst"
    assert d["message_type"] == "critique"
    assert d["metadata"]["severity"] == "HIGH"
    assert "Target leakage" in repr(msg)


def test_base_agent_send_receive_clear():
    agent = BaseAgent(name="Tester", role="QA", system_prompt="Be accurate")
    msg = AgentMessage(
        sender="Coordinator",
        recipient="Tester",
        content="Perform audit",
        message_type=MessageType.PROPOSAL,
    )
    agent.receive(msg)
    assert len(agent.inbox) == 1
    assert agent.inbox[0].content == "Perform audit"

    sent = agent.send("Coordinator", "Audit complete", MessageType.APPROVAL)
    assert len(agent.outbox) == 1
    assert sent.recipient == "Coordinator"

    agent.clear_history()
    assert len(agent.inbox) == 0
    assert len(agent.outbox) == 0


# --------------------------------------------------------------------------- #
# 2. DomainAnalystAgent Testleri
# --------------------------------------------------------------------------- #
def test_domain_analyst_analyze_and_revise():
    sample_domain = {
        "domain": "ecommerce_orders",
        "summary": "Customer purchases",
        "target_column": "returned",
        "tables": [
            {
                "name": "orders",
                "primary_key": "order_id",
                "columns": [
                    {"name": "order_id", "type": "int"},
                    {"name": "amount", "type": "float"},
                    {"name": "returned", "type": "bool"},
                ],
                "business_rules": ["amount > 0"],
            }
        ],
    }
    client = MockAgentLLM([json.dumps(sample_domain), json.dumps(sample_domain)])
    agent = DomainAnalystAgent(llm_client=client)

    result = agent.analyze("Online shopping store")
    assert result["domain"] == "ecommerce_orders"
    assert len(result["tables"]) == 1
    assert len(agent.outbox) == 1

    revised = agent.revise(result, "Remove column returned")
    assert revised["domain"] == "ecommerce_orders"
    assert len(agent.outbox) == 2


# --------------------------------------------------------------------------- #
# 3. StatisticianAgent Testleri
# --------------------------------------------------------------------------- #
def test_statistician_enrich():
    stat_output = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {"name": "amount", "type": "float", "distribution": "lognormal", "mean": 100.0, "std": 30.0},
                    {"name": "returned", "type": "bool", "target_ratio": 0.05},
                ],
                "correlations": [
                    {"columns": ["amount", "returned"], "expected_sign": "positive", "min_r": 0.2}
                ],
            }
        ]
    }
    client = MockAgentLLM([json.dumps(stat_output)])
    agent = StatisticianAgent(llm_client=client)

    result = agent.enrich({"domain": "ecommerce"})
    assert len(result["tables"][0]["columns"]) == 2
    assert result["tables"][0]["columns"][0]["distribution"] == "lognormal"


# --------------------------------------------------------------------------- #
# 4. AdversarialCriticAgent Testleri
# --------------------------------------------------------------------------- #
def test_adversarial_critic_rejects_and_approves():
    critique_resp = {
        "approved": False,
        "confidence_score": 0.4,
        "leakage_findings": [{"column": "chargeback_date", "reason": "Future knowledge", "severity": "HIGH"}],
        "rule_conflicts": [],
        "compliance_issues": [],
        "verdict_summary": "Chargeback date leaks fraud target.",
    }
    approval_resp = {
        "approved": True,
        "confidence_score": 0.95,
        "leakage_findings": [],
        "rule_conflicts": [],
        "compliance_issues": [],
        "verdict_summary": "Schema is sound and leakage-free.",
    }

    client = MockAgentLLM([json.dumps(critique_resp), json.dumps(approval_resp)])
    agent = AdversarialCriticAgent(llm_client=client)

    # 1. Tur: Red
    rep1 = agent.audit("Credit card fraud", {})
    assert rep1["approved"] is False
    assert len(rep1["leakage_findings"]) == 1
    assert agent.outbox[0].message_type == MessageType.CRITIQUE

    # 2. Tur: Onay
    rep2 = agent.audit("Credit card fraud", {})
    assert rep2["approved"] is True
    assert agent.outbox[1].message_type == MessageType.APPROVAL


# --------------------------------------------------------------------------- #
# 5. SchemaEngineerAgent & CouncilCoordinator Entegrasyonu
# --------------------------------------------------------------------------- #
def test_schema_engineer_compiles_valid_schema():
    valid_schema_dict = {
        "domain": "telecom_churn",
        "description": "Customer churn modeling",
        "row_count_target": 1000,
        "random_seed": 42,
        "columns": [
            {"name": "tenure", "type": "int", "distribution": "uniform", "min": 1, "max": 72},
            {"name": "monthly_charges", "type": "float", "distribution": "normal", "mean": 65.0, "std": 15.0},
            {"name": "contract_type", "type": "category", "categories": ["month-to-month", "one-year", "two-year"]},
            {"name": "churn", "type": "bool", "target_ratio": 0.15},
        ],
        "business_rules": ["monthly_charges > 0"],
        "correlations": [
            {"columns": ["tenure", "churn"], "expected_sign": "negative", "min_r": 0.25}
        ],
    }

    client = MockAgentLLM([json.dumps(valid_schema_dict)])
    engineer = SchemaEngineerAgent(llm_client=client)

    contract = engineer.compile(
        domain_proposal={},
        statistical_proposal={},
        audit_report={"approved": True},
        row_count=1000,
        seed=42,
        relational=False,
    )
    assert isinstance(contract, SchemaContract)
    assert contract.domain == "telecom_churn"
    assert len(contract.columns) == 4
    assert contract.row_count_target == 1000


def test_council_coordinator_deliberation_workflow():
    """Tüm konseyin (Domain -> Stat -> Critic [red] -> Revize -> Critic [onay] -> Engineer) akışını test eder."""
    domain_p1 = {"domain": "hospital_admissions", "summary": "Patient records", "tables": []}
    stat_p1 = {"tables": [{"name": "admissions", "columns": []}]}
    critic_reject = {
        "approved": False,
        "leakage_findings": [{"column": "discharge_status", "reason": "Post-admission outcome"}],
        "verdict_summary": "Discharge status must be removed.",
    }
    domain_p2 = {"domain": "hospital_admissions", "summary": "Patient records (revised)", "tables": []}
    stat_p2 = {"tables": [{"name": "admissions", "columns": []}]}
    critic_approve = {
        "approved": True,
        "verdict_summary": "Clean and safe schema.",
    }
    final_schema = {
        "domain": "hospital_admissions",
        "description": "Clean admissions dataset",
        "row_count_target": 500,
        "random_seed": 123,
        "columns": [
            {"name": "patient_age", "type": "int", "distribution": "normal", "mean": 52.0},
            {"name": "icu_admitted", "type": "bool", "target_ratio": 0.08},
        ],
        "business_rules": ["patient_age >= 0"],
        "correlations": [],
    }

    # Sırayla LLM çağrı yanıtları:
    # 1. domain_analyst.analyze
    # 2. statistician.enrich
    # 3. critic.audit (red)
    # 4. domain_analyst.revise
    # 5. statistician.revise
    # 6. critic.audit (onay)
    # 7. engineer.compile
    client = MockAgentLLM([
        json.dumps(domain_p1),
        json.dumps(stat_p1),
        json.dumps(critic_reject),
        json.dumps(domain_p2),
        json.dumps(stat_p2),
        json.dumps(critic_approve),
        json.dumps(final_schema),
    ])

    progress_events = []
    def on_progress(agent: str, msg: str, level: str):
        progress_events.append((agent, level))

    coordinator = CouncilCoordinator(llm_client=client, max_rounds=2, progress_cb=on_progress)
    contract = coordinator.deliberate(
        domain_prompt="Hospital in-patient emergency admissions",
        row_count=500,
        seed=123,
        relational=False,
    )

    assert isinstance(contract, SchemaContract)
    assert contract.domain == "hospital_admissions"
    assert contract.row_count_target == 500
    assert len(coordinator.transcript) >= 5

    # Ajan ara durumlarının bildirildiğini doğrula
    agents_reported = {ev[0] for ev in progress_events}
    assert "DomainAnalyst" in agents_reported
    assert "Statistician" in agents_reported
    assert "AdversarialCritic" in agents_reported
    assert "SchemaEngineer" in agents_reported


# --------------------------------------------------------------------------- #
# 6. Pipeline Entegrasyon Testi (run_pipeline with agentic=True)
# --------------------------------------------------------------------------- #
from ai_data_studio.core.orchestrator import run_pipeline, PipelineConfig
from ai_data_studio.tests.fake_llm import GOOD_CODE, SCHEMA_JSON


class FakeAgenticPipelineLLM(BaseLLMClient):
    provider = "fake_agentic"

    def __init__(self):
        super().__init__(model="fake-agentic")

    def health_check(self) -> bool:
        return True

    def _complete(self, system: str, user: str, max_tokens: int = 8000, temperature=None) -> str:
        if "Domain Modeler" in system:
            return json.dumps({"domain": "ecommerce_orders", "summary": "Online orders", "tables": []})
        if "Quantitative Statistician" in system:
            return json.dumps({"tables": []})
        if "Adversarial Red-Team Critic" in system:
            return json.dumps({"approved": True, "verdict_summary": "Passed inspection"})
        if "Contract Compiler" in system:
            return json.dumps(SCHEMA_JSON)
        # Kod üretimi
        return GOOD_CODE


def test_pipeline_agentic_integration():
    client = FakeAgenticPipelineLLM()
    cfg = PipelineConfig(
        domain_prompt="e-commerce retail",
        row_count=1000,
        random_seed=42,
        agentic=True,
        max_agent_rounds=1,
        write_outputs=False,
    )
    iterator = run_pipeline(cfg, llm_client=client)
    events = []
    result = None
    while True:
        try:
            ev = next(iterator)
            events.append(ev)
        except StopIteration as stop:
            result = stop.value
            break

    assert result is not None
    assert result.dataframe is not None
    assert len(result.dataframe) > 0
    assert result.schema.domain == "ecommerce_orders"

    # Step 2'de konsey olaylarının geçtiğini doğrula
    from ai_data_studio.i18n import t

    step2_msgs = [e["message"] for e in events if e["step"] == 2]
    assert t("run.agents.gathering") in step2_msgs
    assert any(t("run.agents.consensus", tables=1) in m for m in step2_msgs)

