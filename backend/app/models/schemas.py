"""Modèles de données AuditLens — docs/14 (entités, statuts, contrats de sortie).

Aucune assertion de conformité sans critère + evidence : les modèles portent
les champs `control_id`, `criterion_version`, `evidence_refs`, `limitations`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core.ids import new_id


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SourceType(str, Enum):
    odoo = "odoo"
    api = "api"
    web = "web"
    file = "file"


class SourceStatus(str, Enum):
    untested = "untested"
    connected = "connected"
    failed = "failed"


class PermissionLevel(str, Enum):
    """docs/05 : permission par tool."""

    read = "read"
    approved_tests = "approved-tests"
    local = "local"


class SourceConnection(BaseModel):
    id: str
    workspace_id: str = "ws_default"
    name: str
    type: SourceType
    config: dict[str, Any] = Field(default_factory=dict)
    secrets_ref: str | None = None  # clé dans le store de secrets, jamais la valeur
    status: SourceStatus = SourceStatus.untested
    last_test_at: str | None = None
    last_test_message: str | None = None
    created_at: str = Field(default_factory=utcnow)


class MissionLimits(BaseModel):
    """docs/04 — arrêts explicites. ADR-15 : la boucle d'investigation est bornée par
    les RESSOURCES (tools, temps, entrée LLM) ; `max_decisions` n'est qu'un garde-fou
    d'urgence, dérivé par défaut — jamais la cause d'arrêt normale."""

    max_tool_calls: int = 12
    max_seconds: int = 180
    max_input_chars: int = 400_000
    max_page_size: int = 500
    max_decisions: int | None = None  # None → dérivé (garde-fou d'urgence)
    max_llm_calls: int | None = None  # None → dérivé (garde-fou d'urgence)


class MissionStatus(str, Enum):
    draft = "draft"
    planned = "planned"
    approved = "approved"
    running = "running"
    completed = "completed"
    failed = "failed"


class AuditMission(BaseModel):
    id: str
    workspace_id: str = "ws_default"
    title: str
    objective: str
    source_ids: list[str] = Field(default_factory=list)
    control_ids: list[str] = Field(default_factory=list)
    time_range: dict[str, str | None] = Field(default_factory=dict)  # {"from": ..., "to": ...}
    limits: MissionLimits = Field(default_factory=MissionLimits)
    status: MissionStatus = MissionStatus.draft
    approved_plan: dict[str, Any] | None = None  # plan approuvé par l'humain
    created_at: str = Field(default_factory=utcnow)


class RunStatus(str, Enum):
    """docs/02 — états obligatoires. ADR-15 : `paused`/`cancelled` pour le runtime à
    checkpoints (un run en pause n'est ni terminé ni réussi) ; `awaiting_permission`
    et `needs_input` réutilisés tels quels pour approbation budget / demande d'info."""

    not_started = "not_started"
    awaiting_permission = "awaiting_permission"
    running = "running"
    needs_input = "needs_input"
    paused = "paused"
    cancelled = "cancelled"
    partial = "partial"
    failed = "failed"
    completed = "completed"
    review_required = "review_required"


class AuditRun(BaseModel):
    id: str
    mission_id: str
    status: RunStatus = RunStatus.not_started
    provider_id: str = "mock"
    model_id: str = "mock-scripted"
    prompt_version: str = "v1"
    tool_calls_used: int = 0
    input_chars_used: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    stop_reason: str | None = None  # budget_exhausted | insufficient_access | completed | error
    error: str | None = None


class InvestigationCheckpoint(BaseModel):
    """ADR-15 — point de reprise persistant d'une investigation (survit au restart).

    `state` porte : objectif, sources, preuves référencées, hypothèses (actives/rejetées),
    questions ouvertes, historique de décisions, budget consommé, dernière observation
    significative, steps de couverture déjà exécutés, raison d'arrêt/pause.
    """

    id: str
    run_id: str
    mission_id: str
    reason: str  # turn | paused | budget_exhausted | stopped | stagnation | completed
    state: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow)


class ToolCallRecord(BaseModel):
    id: str
    run_id: str
    mission_id: str
    name: str
    source_id: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)  # args sanitizés (sans secrets)
    status: Literal["success", "error", "unauthorized", "partial", "insufficient_evidence", "blocked"]
    latency_ms: int | None = None
    observed_at: str = Field(default_factory=utcnow)
    evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class Evidence(BaseModel):
    """Preuve immuable : checksum + provenance (docs/05, docs/13)."""

    id: str
    mission_id: str
    run_id: str | None = None
    source_id: str | None = None
    type: str  # record_set | profile | validation | http_trace | web_trace | excerpt | raw_file | join
    title: str
    observed_at: str = Field(default_factory=utcnow)
    provenance: dict[str, Any] = Field(default_factory=dict)  # tool, params, connector
    checksum: str  # sha256 du payload canonique
    storage_ref: str  # chemin relatif dans data/evidence
    record_count: int | None = None
    summary: dict[str, Any] | None = None  # version minimisée envoyée au LLM
    payload: dict[str, Any] | None = None  # charge utile (chargée à la demande depuis le store)


class AssessmentStatus(str, Enum):
    """docs/11 — statuts d'assessment."""

    pass_ = "pass"
    fail = "fail"
    insufficient_evidence = "insufficient_evidence"
    not_applicable = "not_applicable"
    not_tested = "not_tested"
    error = "error"
    needs_review = "needs_review"


class Assessment(BaseModel):
    id: str
    run_id: str
    mission_id: str
    control_id: str
    criterion_version: str
    result: AssessmentStatus
    evidence_refs: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    method: str = ""
    limitations: list[str] = Field(default_factory=list)


class FindingStatus(str, Enum):
    needs_review = "needs_review"
    accepted = "accepted"
    rejected = "rejected"
    needs_more_evidence = "needs_more_evidence"


class Severity(str, Enum):
    info = "info"
    low = "low"
    medium = "medium"
    high = "high"


class FindingCandidate(BaseModel):
    """Contrat de sortie docs/04 — tout finding est needs_review à la création."""

    id: str
    run_id: str
    mission_id: str
    control_id: str | None = None
    title: str
    statement: str
    severity_proposed: Severity = Severity.medium
    evidence_refs: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    method: str = ""
    limitations: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    status: FindingStatus = FindingStatus.needs_review
    review: "AuditorReview | None" = None
    rejection_reason: str | None = None  # si rejeté par le validateur structurel
    created_at: str = Field(default_factory=utcnow)


class AuditorReview(BaseModel):
    decision: Literal["accepted", "rejected", "needs_more_evidence"]
    reviewer: str = "auditor"
    reason: str = ""
    timestamp: str = Field(default_factory=utcnow)


class ReportSnapshot(BaseModel):
    id: str
    run_id: str
    mission_id: str
    version: int = 1
    created_at: str = Field(default_factory=utcnow)
    period: dict[str, str | None] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    assessed: list[str] = Field(default_factory=list)  # control_ids
    partial: list[str] = Field(default_factory=list)
    not_assessed: list[str] = Field(default_factory=list)
    findings_included: list[str] = Field(default_factory=list)  # accepted uniquement
    findings_excluded: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    model_id: str = ""
    provider_id: str = ""
    prompt_version: str = "v1"
    markdown: str = ""


class AuditPlanStep(BaseModel):
    id: str = Field(default_factory=lambda: new_id("step"))
    tool: str
    source_id: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    requires_approval: bool = False


class AuditPlan(BaseModel):
    id: str
    mission_id: str
    provider_id: str
    model_id: str
    steps: list[AuditPlanStep] = Field(default_factory=list)
    evidence_expected: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow)


class RunEvent(BaseModel):
    """Événement backend diffusé au frontend (docs/02 — animations = événements réels)."""

    seq: int
    run_id: str
    type: str  # run_started | plan | tool_started | tool_completed | evidence | finding | assessment | run_completed | run_failed | needs_input
    at: str = Field(default_factory=utcnow)
    data: dict[str, Any] = Field(default_factory=dict)


FindingCandidate.model_rebuild()
