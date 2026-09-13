# -*- coding: utf-8 -*-
"""Temel Ajan (Base Agent) ve Mesajlaşma Protokolü.

Hafif, saf Python ve bağımlılıksız (zero-dependency) multi-agent mimarisi.
Tüm uzmanlaşmış ajanlar BaseAgent sınıfından türer ve AgentMessage nesneleri
üzerinden haberleşir.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..services.llm_base import BaseLLMClient

log = logging.getLogger(__name__)


class MessageType(str, Enum):
    """Ajanlar arası mesaj türleri."""
    PROPOSAL = "proposal"       # İlk taslak veya öneri
    CRITIQUE = "critique"       # Eleştiri / red / eksik bildirimi
    REVISION = "revision"       # Düzeltilmiş yeni sürüm
    APPROVAL = "approval"       # Onay / konsensüs sağlandı
    SYSTEM = "system"           # Sistem / koordinasyon bildirimi


@dataclass
class AgentMessage:
    """Ajanlar arası iletilen yapılandırılmış mesaj."""

    sender: str
    recipient: str
    content: str
    message_type: MessageType = MessageType.PROPOSAL
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sender": self.sender,
            "recipient": self.recipient,
            "content": self.content,
            "message_type": self.message_type.value,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        snippet = self.content[:60] + "..." if len(self.content) > 60 else self.content
        return f"AgentMessage({self.sender} -> {self.recipient} [{self.message_type.value}]: {snippet!r})"


class BaseAgent:
    """Tüm uzmanlaşmış ajanların türediği taban sınıf."""

    def __init__(
        self,
        name: str,
        role: str,
        system_prompt: str,
        llm_client: Optional[BaseLLMClient] = None,
        temperature: float = 0.4,
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.llm_client = llm_client
        self.temperature = temperature
        self.inbox: List[AgentMessage] = []
        self.outbox: List[AgentMessage] = []

    def receive(self, message: AgentMessage) -> None:
        """Gelen kutusuna mesaj ekler."""
        self.inbox.append(message)

    def call_llm(
        self,
        user_prompt: str,
        system_override: Optional[str] = None,
        max_tokens: int = 8000,
        temperature: Optional[float] = None,
    ) -> str:
        """LLM istemcisini kullanarak tamamlama yapar."""
        if self.llm_client is None:
            raise RuntimeError(f"Agent '{self.name}' için LLM istemcisi tanımlanmamış.")

        system = system_override or self.system_prompt
        temp = self.temperature if temperature is None else temperature
        return self.llm_client._complete(
            system=system,
            user=user_prompt,
            max_tokens=max_tokens,
            temperature=temp,
        )

    def send(
        self,
        recipient: str,
        content: str,
        message_type: MessageType = MessageType.PROPOSAL,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentMessage:
        """Yeni bir mesaj üretip giden kutusuna ekler."""
        msg = AgentMessage(
            sender=self.name,
            recipient=recipient,
            content=content,
            message_type=message_type,
            metadata=metadata or {},
        )
        self.outbox.append(msg)
        return msg

    def clear_history(self) -> None:
        """Gelen ve giden kutularını sıfırlar."""
        self.inbox.clear()
        self.outbox.clear()

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} role={self.role!r}>"
