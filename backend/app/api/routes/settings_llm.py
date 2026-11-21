"""Settings LLM BYOK : config runtime en mémoire, test de connexion sans exposer la clé (docs/10)."""

from __future__ import annotations

import json
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from ...agent.providers import build_provider, resolve_llm_config
from ...agent.providers.openai_compatible import DEFAULT_BASE_URLS, ZEN_CATALOG_URL, ZEN_USER_AGENT
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
                "message": "Connexion texte réussie ; les appels d’outils et le streaming ne sont pas vérifiés par ce test." if ok else "réponse vide"}
    except ProviderError as exc:
        return {"ok": False, "provider": cfg["provider"], "error": str(exc)}
    finally:
        await provider.close()


@router.get("/opencode/models")
async def list_opencode_free_models(api_key: str | None = None, mode: str = "free"):
    """Catalogue LIVE des modèles OpenCode Zen accessibles (clé "public" par défaut,
    ou clé BYOK fournie). Ne renvoie que les modèles chat supportant les tool calls —
    condition du harness (docs/05). Aucune clé n'est persistée ni journalisée."""
    if mode not in ("free", "api"):
        raise HTTPException(400, "mode de catalogue inconnu")
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
        is_free = mid.endswith("-free") or mid == "big-pickle"
        if mode == "free" and not is_free:
            continue
        # The free models are reserved for OpenCode. API mode only offers paid
        # models explicitly advertising the Chat Completions endpoint we use.
        if mode == "api":
            text_cost = (m.get("cost") or {}).get("text") or {}
            input_price = (text_cost.get("input") or {}).get("price")
            output_price = (text_cost.get("output") or {}).get("price")
            if (is_free or "chat-completions" not in (m.get("api") or {}) or
                not isinstance(input_price, (int, float)) or not isinstance(output_price, (int, float)) or
                max(input_price, output_price) <= 0):
                continue
        models.append({
            "id": mid,
            "name": m.get("name", mid),
            "context": m.get("limit", {}).get("context"),
            "structured_output": bool(caps.get("structured_output", False)),
        })
    return {"ok": True, "models": models}


# Conservative list of text models documented with function calling. A live
# catalogue confirms visibility to the key, not quota or actual tool compatibility.
CURATED_MODELS: dict[str, list[dict]] = {
    "openai": [
        {"id": "gpt-5-mini", "name": "GPT-5 mini"},
        {"id": "gpt-5.4", "name": "GPT-5.4"},
    ],
    "anthropic": [
        {"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5"},
        {"id": "claude-haiku-5-5", "name": "Claude Haiku 5.5"},
    ],
    "deepseek": [
        {"id": "deepseek-flash", "name": "DeepSeek Flash"},
        {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
    ],
    "gemini": [
        {"id": "gemini-4-hydrogen", "name": "Gemini 4 Hydrogen"},
        {"id": "gemini-4-carbon", "name": "Gemini 4 Carbon"},
        {"id": "gemini-4-neon", "name": "Gemini 4 Neon"},
        {"id": "gemini-4-argon", "name": "Gemini 4 Argon"},
    ],
    "mock": [{"id": "mock-scripted-v1", "name": "MockLLM scripté — tests sans clé ni réseau"}],
}

CURATED_NOTES: dict[str, str] = {
    provider: "Sélection documentée en novembre 2026 pour texte et outils ; l'accès et le quota dépendent de votre compte. Testez votre configuration."
    for provider in ("openai", "anthropic", "deepseek", "gemini")
}
CURATED_NOTES.update({
    "mock": "Provider de test : aucun appel réseau.",
    "compatible": "Endpoint compatible générique : base_url et identifiant saisis manuellement ; compatibilité à tester.",
    "opencode": "Les modèles gratuits sont réservés au client OpenCode ; catalogue via /api/settings/llm/opencode/models.",
    "opencode-cli": "Catalogue des modèles gratuits via /api/settings/llm/opencode/models (accès selon fournisseur).",
})

NON_CHAT_MODEL_HINTS = ("embedding", "whisper", "tts", "dall-e", "moderation", "realtime", "audio", "transcribe")


def filter_supported_models(provider: str, models: list[dict]) -> list[dict]:
    """Intersect live availability with documented models; don't infer capabilities from names."""
    candidates = CURATED_MODELS.get(provider)
    if candidates is None:
        return []
    live_ids = {str(model.get("id", "")).removeprefix("models/"): str(model.get("id", "")) for model in models}
    return [{**candidate, "id": live_ids[candidate["id"]]} for candidate in candidates if candidate["id"] in live_ids]


async def _list_models_live(provider: str, api_key: str, base_url: str | None = None) -> list[dict]:
    """Modèles visibles pour cette clé, sans garantie de quota ni de compatibilité.

    Le résultat est ensuite recoupé avec une liste documentée.
    """
    if provider == "anthropic":
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)
        try:
            page = await client.models.list(limit=100)
            return [{"id": m.id, "name": getattr(m, "display_name", None) or m.id} for m in page.data]
        finally:
            await client.close()
    from openai import AsyncOpenAI

    kwargs: dict = {"api_key": api_key, "timeout": 20.0}
    url = base_url or DEFAULT_BASE_URLS.get(provider)
    if url:
        kwargs["base_url"] = url
    client = AsyncOpenAI(**kwargs)
    try:
        page = await client.models.list()
        out = []
        for m in page.data:
            mid = str(m.id)
            if any(h in mid.lower() for h in NON_CHAT_MODEL_HINTS):
                continue
            out.append({"id": mid, "name": getattr(m, "display_name", None) or mid})
        return out
    finally:
        await client.close()


class ModelCatalogBody(BaseModel):
    provider: str
    api_key: str | None = None
    base_url: str | None = None


@router.post("/models")
async def list_provider_models_with_key(request: Request, body: ModelCatalogBody):
    return await _list_provider_models(request, body.provider, body.api_key, body.base_url)


@router.get("/models")
async def list_provider_models(request: Request, provider: str, api_key: str | None = None, base_url: str | None = None):
    if api_key:
        raise HTTPException(400, "Envoyez la clé dans le corps POST, pas dans l'URL.")
    return await _list_provider_models(request, provider, None, base_url)


async def _list_provider_models(request: Request, provider: str, api_key: str | None = None, base_url: str | None = None):
    """Modèles pour un provider (choix facilité dans l'UI).

    Stratégie : LIVE d'abord — la liste réelle exposée par le provider pour
    cette clé (clé fournie par l'UI, sinon clé runtime du même provider ;
    jamais renvoyée ni journalisée). Repli : liste statique vérifiée
    (« curated », nov. 2026) + warning explicite. « none » = saisie libre
    expliquée (compatible dépend du base_url, opencode = catalogue Zen dédié).
    """
    if provider not in CURATED_NOTES:
        raise HTTPException(400, f"provider inconnu : {provider}")
    d = deps(request)
    cfg = resolve_llm_config(d.llm_runtime)
    key = api_key or (cfg.get("api_key") or "" if cfg.get("provider") == provider else "")
    live_base = base_url or (cfg.get("base_url") if cfg.get("provider") == provider else None)
    liveable = provider in ("openai", "anthropic", "deepseek", "gemini") and bool(key)
    if provider == "compatible" and key and live_base:
        liveable = True  # sans base_url, /models n'a aucun sens sur un générique
    if liveable:
        try:
            models = await _list_models_live(provider, key, live_base)
            if provider != "compatible":
                models = filter_supported_models(provider, models)
            return {
                "ok": True, "provider": provider, "source": "live",
                "models": models, "note": CURATED_NOTES[provider],
                "detail": "Catalogue LIVE filtré ; disponibilité et capacités réelles à tester avec votre clé.",
                **({"warning": "Aucun modèle documenté trouvé pour cette clé. Vérifiez les droits ou saisissez un modèle compatible."} if not models else {}),
            }
        except Exception as exc:  # noqa: BLE001 — repli honnête, la raison est affichée
            live_warning = f"liste live indisponible ({type(exc).__name__}) — suggestions statiques affichées"
        else:
            live_warning = "liste live vide pour cette clé — suggestions statiques affichées"
    else:
        live_warning = None
    return {
        "ok": True,
        "provider": provider,
        "source": "curated" if provider in CURATED_MODELS else "none",
        "models": CURATED_MODELS.get(provider, []),
        "note": CURATED_NOTES[provider],
        **({"warning": live_warning} if live_warning else {}),
    }
