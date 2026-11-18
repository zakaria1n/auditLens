"""Paramètres d'exécution AuditLens (env-first, secrets jamais dans le repo)."""

from __future__ import annotations

import os
from pathlib import Path
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _data_dir() -> Path:
    return Path(os.environ.get("AUDITLENS_DATA_DIR", BACKEND_DIR / "data"))


class Settings(BaseModel):
    """Configuration du service. Les secrets ne transitent jamais par ici."""

    data_dir: Path = Field(default_factory=_data_dir)
    db_path: Path = Field(default_factory=lambda: _data_dir() / "auditlens.db")
    evidence_dir: Path = Field(default_factory=lambda: _data_dir() / "evidence")
    uploads_dir: Path = Field(default_factory=lambda: _data_dir() / "uploads")
    secrets_path: Path = Field(default_factory=lambda: _data_dir() / "secrets.json")
    demo_dir: Path = Field(default_factory=lambda: _data_dir() / "demo")

    # Budgets par défaut (docs/04 — arrêts explicites)
    default_max_tool_calls: int = 12
    default_max_seconds: int = 180
    default_max_input_chars: int = 400_000  # approximation du budget tokens

    # Limites d'import (docs/13 — fichiers malveillants ou trop gros)
    max_upload_mb: int = 25
    allowed_upload_extensions: tuple[str, ...] = (".csv", ".xlsx", ".json")

    max_page_size: int = 500

    model_config = {"frozen": False}


def get_settings() -> Settings:
    return Settings()


# --- Fournisseurs LLM via variables d'environnement (docs/10) ---
LLM_ENV = {
    "provider": "AUDITLENS_LLM_PROVIDER",  # openai|gemini|anthropic|deepseek|compatible|mock
    "model": "AUDITLENS_LLM_MODEL",
    "base_url": "AUDITLENS_LLM_BASE_URL",
    "api_key": "AUDITLENS_LLM_KEY",
}


def llm_config_from_env() -> dict:
    return {k: os.environ.get(v) for k, v in LLM_ENV.items()}
