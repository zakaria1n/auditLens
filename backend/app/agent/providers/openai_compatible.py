"""Provider OpenAI-compatible : OpenAI, DeepSeek, Gemini (endpoint compatible), autres testés.

docs/10 : « Compatible API ≠ même support des tool calls » — chaque couple
provider/model doit passer la matrice de compatibilité avant usage réel.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from ...core.errors import ProviderError
from .base import LLMProvider, LLMResponse

DEFAULT_BASE_URLS = {
    "openai": None,  # SDK officiel
    "deepseek": "https://api.deepseek.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "compatible": None,
    # OpenCode Zen — l'INFÉRENCE passe par /inference/openai/v1 (métadonnée `api` de chaque
    # modèle) ; /zen/v1 reste l'endpoint du catalogue (/models). Clé "public" = quota
    # anonyme journalier pour les modèles `-free`, clé personnelle = quota du compte.
    "opencode": "https://opencode.ai/inference/openai/v1",
}
ZEN_CATALOG_URL = "https://opencode.ai/zen/v1/models"
ZEN_USER_AGENT = "opencode/1.0.0"  # Cloudflare 1010 bloque les UA génériques type urllib

# Erreurs spécifiques OpenCode Zen → messages actionnables (FR)
ZEN_ERROR_HINTS = {
    "Free usage limit": (
        "OpenCode a refusé la demande avec FreeUsageLimitError. Ce message ne permet pas "
        "de déterminer le quota de votre compte ni la cause exacte. Les modèles de chat "
        "gratuits sont réservés à OpenCode selon la documentation du fournisseur."
    ),
    "FreeUsageLimitError": (
        "OpenCode a refusé la demande avec FreeUsageLimitError. Ce message ne permet pas "
        "de déterminer le quota de votre compte ni la cause exacte. Les modèles de chat "
        "gratuits sont réservés à OpenCode selon la documentation du fournisseur."
    ),
    "api_key_expired": (
        "Clé OpenCode Zen expirée — générez une nouvelle clé API dans la console OpenCode "
        "et resaisissez-la dans Réglages IA (BYOK)."
    ),
    "Error code: 1010": (
        "Requête bloquée par Cloudflare (User-Agent refusé) — mettre à jour AuditLens."
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
        if provider == "opencode":
            # Cloudflare rejette les UA SDK génériques (1010) : UA applicatif obligatoire
            kwargs["default_headers"] = {"User-Agent": ZEN_USER_AGENT}
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

    async def stream_chat(self, system: str, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[str | LLMResponse]:
        kwargs: dict[str, Any] = {"model": self.model_id, "messages": self._map_messages(system, messages), "max_tokens": self._max_tokens, "stream": True}
        if self._disable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in tools]
        content: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        stream = None
        try:
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content.append(delta.content)
                    yield delta.content
                for tc in delta.tool_calls or []:
                    call = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        call["id"] += tc.id
                    if tc.function:
                        call["name"] += tc.function.name or ""
                        call["arguments"] += tc.function.arguments or ""
            tool_calls = []
            for index, call in sorted(calls.items()):
                try:
                    arguments = json.loads(call["arguments"] or "{}")
                    if not isinstance(arguments, dict):
                        raise ValueError("arguments d'outil non-object")
                except (json.JSONDecodeError, ValueError) as exc:
                    raise ProviderError(f"Arguments d'outil invalides: {exc}") from exc
                if not call["name"]:
                    raise ProviderError("Nom d'outil manquant dans le flux provider")
                tool_calls.append({"id": call["id"] or f"call_{index}", "name": call["name"], "arguments": arguments})
            yield LLMResponse(content="".join(content) or None, tool_calls=tool_calls,
                              input_chars=len(system) + sum(len(str(m.get("content", ""))) for m in messages))
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(self._friendly_error(exc)) from exc
        finally:
            if stream is not None:
                await stream.close()

    def _friendly_error(self, exc: Exception) -> str:
        """Traduit les erreurs provider en messages actionnables : quota Zen,
        corps de réponse (la raison RÉELLE du 400/404 — ex. INVALID_ARGUMENT
        Google), endpoint appelé sur 404 (un base_url hérité d'un autre
        provider produit un endpoint faux, vu en test réel gemini)."""
        base = f"{self.provider_id}/{self.model_id}: {type(exc).__name__}: {exc}"
        text = str(exc)
        # corps de la réponse HTTP : souvent la seule information exploitable
        # (ex. Google renvoie {"error":{"message":"…","status":"INVALID_ARGUMENT"}})
        response = getattr(exc, "response", None)
        if response is not None and not text.strip("Error code: 0123456789 "):
            try:
                body = str(getattr(response, "text", "") or "").strip()
            except Exception:  # noqa: BLE001 — le corps est un bonus, jamais une erreur
                body = ""
            if body:
                base = f"{base} — {body[:400]}"
        for marker, hint in ZEN_ERROR_HINTS.items():
            if marker in text:
                return f"{base} — {hint}"
        request = getattr(exc, "request", None)
        url = str(getattr(request, "url", "") or "")
        if url and ("404" in text or "NotFound" in type(exc).__name__):
            base = f"{base} — endpoint appelé : {url}"
            expected = DEFAULT_BASE_URLS.get(self.provider_id)
            if expected and not url.startswith(expected.rstrip("/")):
                base += (f" — base_url attendue pour {self.provider_id} : {expected}"
                         " (une base_url héritée d'un autre provider ?)")
            elif self.provider_id == "openai":
                base += " — vérifiez l'identifiant du modèle (404 = modèle inexistant pour cette clé)"
        return base

    async def close(self) -> None:
        await self._client.close()
