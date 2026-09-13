# -*- coding: utf-8 -*-
"""AI Data Studio - Çoklu Ajan Konseyi (Multi-Agent Council) Paketi.

Uzmanlaşmış ajanlar:
- DomainAnalystAgent: Sektörel modelleme ve varlık ilişkileri.
- StatisticianAgent: Dağılımlar, parametreler ve korelasyonlar.
- AdversarialCriticAgent: Veri sızıntısı (leakage), HIPAA ve kural çelişkisi denetimi.
- SchemaEngineerAgent: Konsensüsü katı SchemaContract / DatasetContract formatına derler.
- CouncilCoordinator: Tartışma, müzakere ve konsensüs akışını yönetir.
"""
from .base_agent import AgentMessage, BaseAgent, MessageType
from .domain_analyst import DomainAnalystAgent
from .statistician import StatisticianAgent
from .adversarial_critic import AdversarialCriticAgent
from .schema_engineer import SchemaEngineerAgent
from .council_coordinator import CouncilCoordinator

__all__ = [
    "AgentMessage",
    "MessageType",
    "BaseAgent",
    "DomainAnalystAgent",
    "StatisticianAgent",
    "AdversarialCriticAgent",
    "SchemaEngineerAgent",
    "CouncilCoordinator",
]
