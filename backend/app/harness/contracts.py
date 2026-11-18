"""Contrats du Tool Harness (docs/05) : ToolSpec, ToolResult, ToolContext."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, TYPE_CHECKING

from pydantic import BaseModel, Field

from ..models import (
    AuditMission,
    PermissionLevel,
    SourceConnection,
    SourceType,
    utcnow,
)
from ..evidence.store import EvidenceStore
from ..persistence.repository import Repository

if TYPE_CHECKING:  # évite les imports circulaires
    from ..connectors.factory import ConnectorFactory

ToolStatus = Literal[
    "success", "error", "unauthorized", "partial", "insufficient_evidence"
]


class ToolResult(BaseModel):
    """Contrat de retour d'une tool (docs/05). Rien de secret dans preview."""

    tool_call_id: str
    tool: str
    source_id: str | None = None
    status: ToolStatus
    observed_at: str = Field(default_factory=utcnow)
    evidence_ids: list[str] = Field(default_factory=list)
    record_count: int | None = None
    warnings: list[str] = Field(default_factory=list)
    preview: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class ToolContext:
    """Dépendances fournies à chaque exécution de tool."""

    mission: AuditMission
    run_id: str
    source: SourceConnection | None
    secrets: dict[str, Any]
    store: EvidenceStore
    repo: Repository
    connectors: "ConnectorFactory"
    extra: dict[str, Any] = field(default_factory=dict)


ToolHandler = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]


class ToolSpec(BaseModel):
    """Description d'une tool pour le Registry et le LLM (docs/05)."""

    name: str
    label: str  # étiquette lisible affichée dans l'UI (docs/02)
    description: str
    source_types: list[SourceType]  # types de sources compatibles ([] = toutes)
    permission: PermissionLevel
    input_model_name: str  # nom du modèle Pydantic des entrées
    schema_hint: dict[str, Any]  # JSON-schema simplifié pour le LLM


class InputValidationError(ValueError):
    pass


def validate_tool_args(input_model: type[BaseModel], args: dict[str, Any]) -> dict[str, Any]:
    """Valide et normalise les arguments via le modèle Pydantic de la tool."""
    try:
        parsed = input_model.model_validate(args)
    except Exception as exc:  # pydantic ValidationError
        raise InputValidationError(f"Arguments invalides pour la tool: {exc}") from exc
    return parsed.model_dump(exclude_none=True)
