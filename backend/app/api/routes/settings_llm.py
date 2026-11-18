"""Settings LLM BYOK : config runtime en mémoire, test de connexion sans exposer la clé (docs/10)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...agent.providers import build_provider, resolve_llm_config
from ...core.errors import ProviderError
from ..deps import deps

router = APIRouter(prefix="/api/settings/llm", tags=["settings"])


class LLMConfigBody(BaseModel):
    provider: str  # openai | gemini | anthropic | deepseek | compatible | opencode | mock
    model: str = ""
    base_url: str | None = None
    api_key: str | None = None  # conservé en mémoire uniquement — jamais persisté ni retourné
    max_tokens: int | None = None  # optionnel (défaut 8192 pour providers compatibles)
    disable_thinking: bool | None = None  # optionnel (Z.AI/GLM : réponse directe sans raisonnement)


@router.get("")
async def get_llm_config(request: Request):
    d = deps(request)
    cfg = resolve_llm_config(d.llm_runtime)
    env_cfg = resolve_llm_config(None)
    return {
        "provider": cfg["provider"],
        "model": cfg["model"],
        "base_url": cfg.get("base_url"),
        "key_configured": bool(cfg.get("api_key")) or cfg["provider"] in ("mock", "opencode"),
        "source": "runtime" if d.llm_runtime.get("provider") else ("env" if env_cfg.get("provider") not in (None, "mock") else "default"),
        "providers_available": ["mock", "opencode", "openai", "gemini", "anthropic", "deepseek", "compatible"],
        "note": "BYOK : la clé reste en mémoire backend, jamais loggée ni renvoyée. OpenCode Zen : modèles -free anonymes (~200 req/jour/IP).",
    }


@router.put("")
async def set_llm_config(body: LLMConfigBody, request: Request):
    d = deps(request)
    d.llm_runtime.clear()
    d.llm_runtime.update({
        "provider": body.provider,
        "model": body.model,
        "base_url": body.base_url,
        "api_key": body.api_key or "",
        "max_tokens": body.max_tokens,
        "disable_thinking": body.disable_thinking,
    })
    return {"ok": True, "provider": body.provider, "model": body.model}


@router.post("/test")
async def test_llm_config(request: Request, body: LLMConfigBody | None = None):
    """Test provider sans exposer la clé (docs/14). Mock => ok immédiat."""
    d = deps(request)
    if body is not None:
        cfg = {
            "provider": body.provider, "model": body.model,
            "base_url": body.base_url, "api_key": body.api_key or "",
        }
    else:
        cfg = resolve_llm_config(d.llm_runtime)
    try:
        provider = build_provider(cfg)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if provider.provider_id == "mock":
        return {"ok": True, "provider": "mock", "message": "MockLLM actif — tools testables sans clé API"}
    try:
        resp = await provider.chat(
            "Tu es un test de connexion. Réponds uniquement par le JSON {\"ok\": true}.",
            [{"role": "user", "content": "test"}],
        )
        ok = bool(resp.content or resp.tool_calls)
        return {"ok": ok, "provider": provider.provider_id, "model": provider.model_id,
                "message": "connexion réussie" if ok else "réponse vide"}
    except ProviderError as exc:
        return {"ok": False, "provider": cfg["provider"], "error": str(exc)}
    finally:
        await provider.close()
