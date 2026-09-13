# -*- coding: utf-8 -*-
"""Ajan Konseyi Koordinatörü (CouncilCoordinator).

DomainAnalyst, Statistician, AdversarialCritic ve SchemaEngineer ajanları arasındaki
iş birliği, tartışma (debate), karşıt eleştiri ve konsensüs sürecini yönetir.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ..core.dataset_contract import DatasetContract
from ..core.schema_contract import SchemaContract
from ..services.llm_base import BaseLLMClient
from .adversarial_critic import AdversarialCriticAgent
from .base_agent import AgentMessage, MessageType
from .domain_analyst import DomainAnalystAgent
from .schema_engineer import SchemaEngineerAgent
from .statistician import StatisticianAgent

log = logging.getLogger(__name__)


class CouncilCoordinator:
    """Çoklu ajan konseyini yöneten koordinatör sınıf."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        max_rounds: int = 2,
        progress_cb: Optional[Callable[[str, str, str], None]] = None,
    ):
        self.llm_client = llm_client
        self.max_rounds = max(1, max_rounds)
        self.progress_cb = progress_cb

        # Ajanların başlatılması
        self.domain_analyst = DomainAnalystAgent(llm_client=llm_client)
        self.statistician = StatisticianAgent(llm_client=llm_client)
        self.critic = AdversarialCriticAgent(llm_client=llm_client)
        self.engineer = SchemaEngineerAgent(llm_client=llm_client)

        # Tartışma tutanağı (transcript)
        self.transcript: List[AgentMessage] = []

    def _notify(self, agent_name: str, message: str, level: str = "info") -> None:
        """Kullanıcı arayüzüne veya konsola ajan ara durumunu bildirir."""
        if self.progress_cb:
            try:
                self.progress_cb(agent_name, message, level)
            except Exception as exc:
                log.debug("Ajan ilerleme bildirimi hatası: %s", exc)

    def deliberate(
        self,
        domain_prompt: str,
        row_count: int = 1000,
        seed: int = 42,
        locale: str = "en_US",
        relational: bool = False,
        seed_summary: str = "",
    ) -> Union[DatasetContract, SchemaContract]:
        """Ajan konseyini toplar, tartışmayı yönetir ve nihai sözleşmeyi döndürür."""
        self.transcript.clear()

        # ----------------------------------------------------------------- #
        # Adım 1: Domain Analizi & Varlık Modellemesi
        # ----------------------------------------------------------------- #
        self._notify("DomainAnalyst", "Sektörel varlıklar ve iş kuralları modelleniyor...", "info")
        domain_proposal = self.domain_analyst.analyze(
            domain_prompt=domain_prompt,
            relational=relational,
            seed_summary=seed_summary,
        )
        self.transcript.extend(self.domain_analyst.outbox)
        summary = domain_proposal.get("summary", domain_prompt[:50])
        self._notify("DomainAnalyst", f"Varlık modeli oluşturuldu: {summary}", "success")

        # ----------------------------------------------------------------- #
        # Adım 2: İstatistiksel Dağılım ve Korelasyon Ataması
        # ----------------------------------------------------------------- #
        self._notify("Statistician", "Olasılık dağılımları ve korelasyonlar hesaplanıyor...", "info")
        stat_proposal = self.statistician.enrich(domain_proposal)
        self.transcript.extend(self.statistician.outbox)
        self._notify("Statistician", "Matematiksel dağılım ve korelasyon taslağı tamamlandı.", "success")

        # ----------------------------------------------------------------- #
        # Adım 3: Karşıt Denetim ve Tartışma Döngüsü (Debate Loop)
        # ----------------------------------------------------------------- #
        audit_report: Dict[str, Any] = {}
        for round_idx in range(1, self.max_rounds + 1):
            self._notify(
                "AdversarialCritic",
                f"Şema denetleniyor (Round {round_idx}/{self.max_rounds}): Sızıntı ve HIPAA taraması...",
                "info",
            )
            audit_report = self.critic.audit(domain_prompt, stat_proposal)
            self.transcript.extend(self.critic.outbox)

            is_approved = bool(audit_report.get("approved", False))
            verdict = audit_report.get("verdict_summary", "Denetim tamamlandı")

            if is_approved:
                self._notify("AdversarialCritic", f"✅ Onaylandı: {verdict}", "success")
                break

            # Kusur veya sızıntı bulundu
            leakage = audit_report.get("leakage_findings", [])
            conflicts = audit_report.get("rule_conflicts", [])
            issues = []
            if leakage:
                cols = [f["column"] for f in leakage if "column" in f]
                issues.append(f"Target Leakage ({', '.join(cols)})")
            if conflicts:
                issues.append(f"{len(conflicts)} kural çelişkisi")

            issues_text = "; ".join(issues) if issues else verdict
            self._notify("AdversarialCritic", f"⚠️ Revizyon İstendi: {issues_text}", "warning")

            if round_idx < self.max_rounds:
                # Düzeltme turu
                self._notify("DomainAnalyst", "Eleştiriler doğrultusunda şema revize ediliyor...", "info")
                critique_feedback = (
                    f"Findings from Adversarial Critic:\n"
                    f"Leakage: {leakage}\n"
                    f"Rule Conflicts: {conflicts}\n"
                    f"Summary: {verdict}"
                )
                domain_proposal = self.domain_analyst.revise(domain_proposal, critique_feedback)
                stat_proposal = self.statistician.revise(stat_proposal, critique_feedback)
            else:
                self._notify(
                    "AdversarialCritic",
                    f"Maksimum tartışma turuna ({self.max_rounds}) ulaşıldı. En iyi konsensüs ile devam ediliyor.",
                    "warning",
                )

        # ----------------------------------------------------------------- #
        # Adım 4: Sözleşme Derleme (SchemaEngineer)
        # ----------------------------------------------------------------- #
        self._notify("SchemaEngineer", "Konsensüs nihai Schema Contract sözleşmesine derleniyor...", "info")
        contract = self.engineer.compile(
            domain_proposal=domain_proposal,
            statistical_proposal=stat_proposal,
            audit_report=audit_report,
            row_count=row_count,
            seed=seed,
            locale=locale,
            relational=relational,
        )
        self.transcript.extend(self.engineer.outbox)
        self._notify("SchemaEngineer", "Sözleşme başarıyla derlendi ve onaylandı.", "success")

        return contract
