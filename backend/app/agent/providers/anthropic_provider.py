"""Provider Anthropic Claude (messages API + tool use)."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic

from ...core.errors import ProviderError
from .base import LLMProvider, LLMResponse


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str, api_key: str):
        self.provider_id = "anthropic"
        self.model_id = model
        self._client = AsyncAnthropic(api_key=api_key)
        self._max_tokens = 4096

    def _map_messages(self, messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        pending_results: list[dict] = []

        def flush_results(target: list[dict]) -> None:
            if pending_results:
                target.append({"role": "user", "content": pending_results.copy()})
                pending_results.clear()

        for m in messages:
            role = m.get("role")
            if role == "user":
                flush_results(out)
                out.append({"role": "user", "content": str(m.get("content", ""))})
            elif role == "assistant":
                flush_results(out)
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": str(m["content"])})
                for c in m.get("tool_calls") or []:
                    blocks.append({
                        "type": "tool_use", "id": c["id"], "name": c["name"],
                        "input": c.get("arguments", {}),
                    })
                if blocks:
                    out.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                pending_results.append({
                    "type": "tool_result", "tool_use_id": m["tool_call_id"],
                    "content": str(m.get("content", "")),
                })
        flush_results(out)
        return out

    async def chat(self, system: str, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": self._map_messages(messages),
        }
        if tools:
            kwargs["tools"] = [
                {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                for t in tools
            ]
        total_chars = len(system) + sum(len(str(m.get("content", ""))) for m in messages)
        try:
            resp = await self._client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"anthropic/{self.model_id}: {type(exc).__name__}: {exc}") from exc

        content_text: str | None = None
        tool_calls = []
        for block in resp.content:
            if block.type == "text":
                content_text = (content_text or "") + block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id, "name": block.name,
                    "arguments": block.input if isinstance(block.input, dict) else {},
                })
        return LLMResponse(content=content_text, tool_calls=tool_calls, input_chars=total_chars)

    async def stream_chat(self, system: str, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[str | LLMResponse]:
        kwargs: dict[str, Any] = {"model": self.model_id, "max_tokens": self._max_tokens, "system": system, "messages": self._map_messages(messages)}
        if tools:
            kwargs["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield event.delta.text
                result = await stream.get_final_message()
            text = "".join(block.text for block in result.content if block.type == "text")
            calls = [{"id": block.id, "name": block.name, "arguments": block.input if isinstance(block.input, dict) else {}} for block in result.content if block.type == "tool_use"]
            yield LLMResponse(content=text or None, tool_calls=calls, input_chars=len(system) + sum(len(str(m.get("content", ""))) for m in messages))
        except Exception as exc:
            raise ProviderError(f"anthropic/{self.model_id}: {type(exc).__name__}: {exc}") from exc

    async def close(self) -> None:
        await self._client.close()
