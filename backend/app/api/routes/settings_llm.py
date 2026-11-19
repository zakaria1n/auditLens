"""Settings LLM BYOK : config runtime en mémoire, test de connexion sans exposer la clé (docs/10)."""

from __future__ import annotations

import json
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

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


class ModelSelectionBody(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Le modèle ne peut pas être vide")
        return value


@router.patch("/model")
async def select_model(body: ModelSelectionBody, request: Request):
    d = deps(request)
    current = resolve_llm_config(d.llm_runtime)
    if current["provider"] != body.provider:
        raise HTTPException(409, "Le fournisseur actif a changé. Rechargez la sélection.")
    if body.provider == "mock" and body.model != current["model"]:
        raise HTTPException(400, "Le provider mock utilise son modèle de test configuré.")
    # Ne remplacer ni clé, ni URL, ni autres options du fournisseur actif.
    d.llm_runtime["model"] = body.model
    return {"provider": body.provider, "model": body.model}


@router.get("")
async def get_llm_config(request: Request):
    d = deps(request)
    cfg = resolve_llm_config(d.llm_runtime)
    env_cfg = resolve_llm_config(None)
    return {
        "provider": cfg["provider"],
        "model": cfg["model"],
        "base_url": cfg.get("base_url"),
        "key_configured": bool(cfg.get("api_key")),
        "source": "runtime" if d.llm_runtime.get("provider") else ("env" if env_cfg.get("provider") not in (None, "mock") else "default"),
        "providers_available": ["mock", "opencode", "opencode-cli", "openai", "gemini", "anthropic", "deepseek", "compatible"],
        "note": "BYOK : la clé reste en mémoire backend, jamais loggée ni renvoyée. opencode-cli = modeles FREE OpenCode via votre app/CLI local (aucune cle ; ~10-20 s/appel). opencode (REST) requiert une cle Zen valide.",
    }


@router.put("")
async def set_llm_config(body: LLMConfigBody, request: Request):
    d = deps(request)
    previous = resolve_llm_config(d.llm_runtime)
    api_key = body.api_key if body.api_key is not None else (
        previous.get("api_key", "") if previous.get("provider") == body.provider else ""
    )
    d.llm_runtime.clear()
    d.llm_runtime.update({
        "provider": body.provider,
        "model": body.model,
        "base_url": None if body.provider == "opencode" else body.base_url,
        "api_key": api_key,
        "max_tokens": body.max_tokens,
        "disable_thinking": body.disable_thinking,
    })
    return {"ok": True, "provider": body.provider, "model": body.model}


@router.post("/test")
async def test_llm_config(request: Request, body: LLMConfigBody | None = None):
    """Test provider sans exposer la clé (docs/14). Mock => ok immédiat."""
    d = deps(request)
    if body is not None:
        previous = resolve_llm_config(d.llm_runtime)
        api_key = body.api_key if body.api_key is not None else (
            previous.get("api_key", "") if previous.get("provider") == body.provider else ""
        )
        cfg = {
            "provider": body.provider, "model": body.model,
            "base_url": None if body.provider == "opencode" else body.base_url,
            "api_key": api_key,
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


# --- Catalogues de modèles SUGGÉRÉS par provider (Phase UI — choix facilité) ---
# Listes statiques de modèles chat supportant les tool calls (condition docs/05),
# vérifiées à jour en novembre 2026. Ce NE SONT PAS des listes exhaustives :
# l'utilisateur peut toujours saisir librement un identifiant de modèle plus récent.
CURATED_MODELS: dict[str, list[dict]] = {
    "openai": [
        {"id": "gpt-4.1-mini", "name": "GPT-4.1 mini — rapide, bon rapport qualité/prix"},
        {"id": "gpt-4.1", "name": "GPT-4.1 — qualité maximale"},
        {"id": "gpt-4.1-nano", "name": "GPT-4.1 nano — le plus économique"},
        {"id": "gpt-4o-mini", "name": "GPT-4o mini"},
        {"id": "gpt-4o", "name": "GPT-4o"},
    ],
    "anthropic": [
        {"id": "claude-sonnet-4-5", "name": "Claude Sonnet 4.5 — recommandé (outils fiables)"},
        {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5 — rapide et économique"},
        {"id": "claude-opus-4-1", "name": "Claude Opus 4.1 — raisonnement profond"},
        {"id": "claude-3-5-haiku-latest", "name": "Claude 3.5 Haiku"},
    ],
    "deepseek": [
        {"id": "deepseek-chat", "name": "DeepSeek Chat (V3) — outil de chat principal"},
        {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R) — raisonnement étendu"},
    ],
    "gemini": [
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash — rapide, recommandé"},
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro — qualité maximale"},
        {"id": "gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash Lite — économique"},
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
    ],
    "mock": [{"id": "mock-scripted-v1", "name": "MockLLM scripté — tests sans clé ni réseau"}],
}

CURATED_NOTES: dict[str, str] = {
    "openai": "Suggestions plateformes OpenAI (nov. 2026). Tout modèle récent supportant les tool calls peut être saisi manuellement.",
    "anthropic": "Suggestions Anthropic (nov. 2026) via l'API Messages. Tout modèle récent supportant les outils peut être saisi manuellement.",
    "deepseek": "Suggestions DeepSeek API (nov. 2026). Les identifiants réels dépendent du compte.",
    "gemini": "Suggestions Google AI (nov. 2026) via l'API compatible OpenAI. Tout modèle récent peut être saisi.",
    "mock": "Provider de test : aucun appel réseau.",
    "compatible": "Endpoint compatible OpenAI générique (base_url requis) : la liste dépend du serveur — saisissez l'identifiant exact du modèle (ex. glm-5.3-flash sur Z.AI, llama3.1 sur Ollama local).",
    "opencode": "Catalogue dynamique : la liste live des modèles gratuits est récupérée via /api/settings/llm/opencode/models.",
    "opencode-cli": "Catalogue dynamique : la liste live des modèles gratuits est récupérée via /api/settings/llm/opencode/models (aucune clé requise).",
}


@router.get("/models")
async def list_provider_models(provider: str):
    """Modèles SUGGÉRÉS pour un provider (choix facilité dans l'UI). Source
    « curated » = liste statique vérifiée (nov. 2026) ; « none » = saisie libre
    avec explication. Jamais exhaustive : la saisie manuelle reste possible."""
    if provider not in CURATED_NOTES:
        raise HTTPException(400, f"provider inconnu : {provider}")
    return {
        "ok": True,
        "provider": provider,
        "source": "curated" if provider in CURATED_MODELS else "none",
        "models": CURATED_MODELS.get(provider, []),
        "note": CURATED_NOTES[provider],
    }
