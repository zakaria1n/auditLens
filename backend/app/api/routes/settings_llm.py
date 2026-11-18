"""Settings LLM BYOK : config runtime en mémoire, test de connexion sans exposer la clé (docs/10)."""

from __future__ import annotations

import json
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...agent.providers import build_provider, resolve_llm_config
from ...agent.providers.openai_compatible import ZEN_CATALOG_URL, ZEN_USER_AGENT
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
        "providers_available": ["mock", "opencode", "opencode-cli", "openai", "gemini", "anthropic", "deepseek", "compatible"],
        "note": "BYOK : la clé reste en mémoire backend, jamais loggée ni renvoyée. opencode-cli = modeles FREE OpenCode via votre app/CLI local (aucune cle ; ~10-20 s/appel). opencode (REST) requiert une cle Zen valide.",
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


@router.get("/opencode/models")
async def list_opencode_free_models(api_key: str | None = None):
    """Catalogue LIVE des modèles OpenCode Zen accessibles (clé "public" par défaut,
    ou clé BYOK fournie). Ne renvoie que les modèles chat supportant les tool calls —
    condition du harness (docs/05). Aucune clé n'est persistée ni journalisée."""
    key = api_key or "public"
    req = urllib.request.Request(ZEN_CATALOG_URL, headers={
        "Authorization": f"Bearer {key}", "User-Agent": ZEN_USER_AGENT,
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read()).get("data", [])
    except Exception as exc:  # noqa: BLE001 — liste indisponible = message clair, pas de mock
        return {"ok": False, "error": f"catalogue indisponible : {exc}", "models": []}
    models = []
    for m in data:
        caps = m.get("capabilities", {})
        if m.get("type") != "chat" or not caps.get("tools", {}).get("supported"):
            continue
        mid = m["id"]
        # uniquement les modèles gratuits : suffixe -free + big-pickle (raisonnement price 0)
        if not (mid.endswith("-free") or mid == "big-pickle"):
            continue
        models.append({
            "id": mid,
            "name": m.get("name", mid),
            "context": m.get("limit", {}).get("context"),
            "structured_output": bool(caps.get("structured_output", False)),
        })
    return {"ok": True, "models": models}
