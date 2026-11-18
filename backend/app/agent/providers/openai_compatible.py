"""Provider OpenAI-compatible : OpenAI, DeepSeek, Gemini (endpoint compatible), autres testés.

docs/10 : « Compatible API ≠ même support des tool calls » — chaque couple
provider/model doit passer la matrice de compatibilité avant usage réel.
"""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from ...core.errors import ProviderError
from .base import LLMProvider, LLMResponse

DEFAULT_BASE_URLS = {
    "openai": None,  # SDK officiel
    "deepseek": "https://api.deepseek.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "compatible": None,
    "opencode": "https://opencode.ai/zen/v1",  # OpenCode Zen — modèles -free (api_key "public")
}

# Erreurs spécifiques OpenCode Zen → messages actionnables (FR)
ZEN_ERROR_HINTS = {
    "Free usage limit": (
        "Limite gratuite OpenCode Zen atteinte pour cette IP (~200 requêtes/jour). "
        "Réessayez plus tard (quota quotidien) ou fournissez une clé OpenCode Zen payante."
    ),
    "FreeUsageLimitError": (
        "Limite gratuite OpenCode Zen atteinte pour cette IP (~200 requêtes/jour). "
        "Réessayez plus tard (quota quotidien) ou fournissez une clé OpenCode Zen payante."
    ),
}


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, provider: str, model: str, api_key: str, base_url: str | None = None,
                 max_tokens: int | None = None, disable_thinking: bool = False):
        if provider not in DEFAULT_BASE_URLS:
            raise ProviderError(f"provider openai-compatible inconnu: {provider}")
        self.provider_id = provider
        self.model_id = model
        url = base_url or DEFAULT_BASE_URLS[provider]
        kwargs: dict[str, Any] = {"api_key": api_key}
        if url:
            kwargs["base_url"] = url
        self._client = AsyncOpenAI(**kwargs)
        # Les modèles de raisonnement consomment ce budget AVANT `content` (docs Z_API_FREE) :
        # 8192 par défaut + fallback sur reasoning_content + option disable_thinking.
        self._max_tokens = max_tokens or 8192
        self._disable_thinking = disable_thinking

    def _map_messages(self, system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            role = m.get("role")
            if role == "user":
                out.append({"role": "user", "content": str(m.get("content", ""))})
            elif role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": m.get("content")}
                calls = m.get("tool_calls") or []
                if calls:
                    entry["tool_calls"] = [
                        {
                            "id": c["id"], "type": "function",
                            "function": {"name": c["name"], "arguments": json.dumps(c.get("arguments", {}))},
                        }
                        for c in calls
                    ]
                    if entry["content"] is None:
                        entry["content"] = ""
                out.append(entry)
            elif role == "tool":
                out.append({
                    "role": "tool", "tool_call_id": m["tool_call_id"],
                    "content": str(m.get("content", "")),
                })
        return out

    async def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        mapped = self._map_messages(system, messages)
        kwargs: dict[str, Any] = {"model": self.model_id, "messages": mapped, "max_tokens": self._max_tokens}
        if self._disable_thinking:
            # Compat Z.AI / GLM : couper le raisonnement pour les tâches structurées (réponse directe)
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        if tools:
            kwargs["tools"] = [
                {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
                for t in tools
            ]
        total_chars = len(system) + sum(len(str(m.get("content", ""))) for m in messages)
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(self._friendly_error(exc)) from exc

        choice = resp.choices[0] if resp.choices else None
        content = choice.message.content if choice else None
        reasoning = getattr(choice.message, "reasoning_content", None) if choice else None
        if not content and reasoning:
            # Modèle de raisonnement : le JSON peut être complet dans reasoning_content
            content = reasoning
        tool_calls = []
        for tc in (choice.message.tool_calls or []) if choice else []:
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append({"id": tc.id or f"call_{len(tool_calls)}", "name": tc.function.name, "arguments": arguments})
        usage: dict[str, int] | None = None
        raw_usage = getattr(resp, "usage", None)
        if raw_usage is not None:
            usage = {
                "prompt_tokens": getattr(raw_usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(raw_usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(raw_usage, "total_tokens", 0) or 0,
            }
        return LLMResponse(content=content, tool_calls=tool_calls, input_chars=total_chars, usage=usage)

    def _friendly_error(self, exc: Exception) -> str:
        """Traduit les erreurs provider en messages actionnables (ex. quota Zen)."""
        base = f"{self.provider_id}/{self.model_id}: {type(exc).__name__}: {exc}"
        text = str(exc)
        for marker, hint in ZEN_ERROR_HINTS.items():
            if marker in text:
                return f"{base} — {hint}"
        return base

    async def close(self) -> None:
        await self._client.close()
