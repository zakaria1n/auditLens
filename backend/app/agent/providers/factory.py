"""Factory des providers LLM (docs/10). Config prioritaire : runtime (BYOK UI) puis env."""

from __future__ import annotations

from ...core.settings import llm_config_from_env
from .anthropic_provider import AnthropicProvider
from .base import LLMProvider
from .mock import MockLLMProvider
from .openai_compatible import OpenAICompatibleProvider


def resolve_llm_config(runtime_config: dict | None = None) -> dict:
    """Runtime (saisi dans Settings > AI Model, en mémoire uniquement) > variables d'env."""
    env = llm_config_from_env()
    cfg = {
        "provider": env.get("provider") or "mock",
        "model": env.get("model") or "",
        "base_url": env.get("base_url"),
        "api_key": env.get("api_key") or "",
    }
    if runtime_config:
        for key in ("provider", "model", "base_url", "api_key"):
            if runtime_config.get(key):
                cfg[key] = runtime_config[key]
        for extra in ("max_tokens", "disable_thinking"):
            if runtime_config.get(extra) is not None:
                cfg[extra] = runtime_config[extra]
    if cfg["provider"] == "mock":
        cfg["model"] = cfg["model"] or "mock-scripted-v1"
    return cfg


def build_provider(config: dict, scenario: str = "data_audit") -> LLMProvider:
    provider = config.get("provider", "mock")
    if provider == "mock":
        return MockLLMProvider(scenario=scenario)
    api_key = config.get("api_key") or ""
    model = config.get("model") or ""
    if provider == "opencode":
        # OpenCode Zen : les modèles `-free` sont accessibles anonymement avec "public"
        # (endpoint public documenté, ~200 req/jour/IP — voir docs/21 ADR-10).
        api_key = api_key or "public"
        model = model or "glm-5.3-flash-free"
    if not api_key:
        raise ValueError(
            f"clé API manquante pour le provider '{provider}' — configurer BYOK (Settings > AI Model) ou AUDITLENS_LLM_KEY"
        )
    if provider == "anthropic":
        return AnthropicProvider(model=model or "claude-sonnet-4-5", api_key=api_key)
    if provider in ("openai", "deepseek", "gemini", "compatible", "opencode"):
        return OpenAICompatibleProvider(
            provider=provider, model=model, api_key=api_key, base_url=config.get("base_url"),
            max_tokens=config.get("max_tokens"),
            disable_thinking=bool(config.get("disable_thinking")),
        )
    raise ValueError(f"provider LLM inconnu: {provider}")
