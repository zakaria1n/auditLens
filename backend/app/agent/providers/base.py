"""Abstraction LLMProvider (docs/10) : API interchangeable, BYOK, mock pour tests.

Format canonique des messages (traduit vers chaque API par l'adapter) :
- {"role": "user", "content": str}
- {"role": "assistant", "content": str|None, "tool_calls": [{id, name, arguments}]}
- {"role": "tool", "tool_call_id": str, "name": str, "content": str}
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from pydantic import BaseModel, Field


class ProviderToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ProviderToolCall] = Field(default_factory=list)
    input_chars: int = 0  # comptabilisé par l'adapter pour le budget (docs/04)
    # Usage réel du provider quand il l'expose (ADR-15) : {prompt_tokens, completion_tokens,
    # total_tokens}. Absent → None : le budget affiche « indisponible », jamais une estimation inventée.
    usage: dict[str, int] | None = None


class LLMProvider(ABC):
    provider_id: str = "base"
    model_id: str = "unknown"

    @abstractmethod
    async def chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Un tour de conversation. tools = [{name, description, parameters(JSON schema)}]."""

    async def stream_chat(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str | LLMResponse]:
        """Fallback explicite pour les providers sans streaming natif."""
        yield await self.chat(system, messages, tools)

    async def close(self) -> None:
        return None
