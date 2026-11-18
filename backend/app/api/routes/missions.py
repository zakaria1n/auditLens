"""Missions : création, plan IA, approbation, lancement de run (docs/14)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...agent.providers import build_provider, resolve_llm_config
from ...audit.controls import control_to_dict, get_control
from ...audit.rules import RULE_SETS
from ...core.errors import ProviderError
from ...core.ids import new_id
from ..deps import deps
from ...models import (
    AuditMission,
    AuditRun,
    MissionStatus,
    RunStatus,
    utcnow,
)
from .sources import _create_initial_file_evidence

router = APIRouter(prefix="/api/missions", tags=["missions"])


class MissionCreate(BaseModel):
    title: str
    objective: str
    source_ids: list[str] = Field(default_factory=list)
    control_ids: list[str] = Field(default_factory=list)
    time_range: dict = Field(default_factory=dict)
    limits: dict | None = None


class ApproveBody(BaseModel):
    plan: dict  # plan proposé retourné par /plan, éventuellement édité
    note: str = ""


class RunBody(BaseModel):
    provider: str | None = None  # override runtime (BYOK) — sinon config Settings > AI Model
    model: str | None = None
    scenario: str | None = None  # scénario MockLLM (data_audit|insufficient|unauthorized|hallucinated)


@router.post("")
async def create_mission(body: MissionCreate, request: Request):
    d = deps(request)
    for sid in body.source_ids:
        if await d.repo.get_source(sid) is None:
            raise HTTPException(400, f"source inconnue: {sid}")
    for cid in body.control_ids:
        if get_control(cid) is None:
            raise HTTPException(400, f"contrôle inconnu: {cid} (catalogue: ERP-01, ERP-02, API-01, WEB-01, DATA-01, CROSS-01)")
    limits = body.limits or {}
    mission = AuditMission(
        id=new_id("mission"),
        title=body.title,
        objective=body.objective,
        source_ids=body.source_ids,
        control_ids=body.control_ids,
        time_range={"from": body.time_range.get("from"), "to": body.time_range.get("to")},
        limits={"max_tool_calls": limits.get("max_tool_calls", 12),
                "max_seconds": limits.get("max_seconds", 180),
                "max_input_chars": limits.get("max_input_chars", 400_000),
                "max_page_size": limits.get("max_page_size", 500),
                # ADR-15 : garde-fous d'urgence explicites (None → dérivés du budget tools)
                "max_decisions": limits.get("max_decisions"),
                "max_llm_calls": limits.get("max_llm_calls")},
    )
    await d.repo.create_mission(mission)
    await _link_import_evidence(d, mission)
    return {"mission": mission.model_dump()}


async def _link_import_evidence(d, mission: AuditMission) -> None:
    """Rattache les evidences d'import (mission `_imports`) au périmètre de la mission.

    Invariant docs/14 : une evidence ne peut provenir d'un autre périmètre. On crée
    une preuve mission-scopée référençant l'import d'origine (chemin + provenance).
    """
    for ev in await d.repo.list_evidence(mission_id="_imports"):
        if ev.source_id in mission.source_ids and ev.type == "raw_file":
            full = d.store.load(ev)
            linked = d.store.save(
                mission_id=mission.id, run_id=None, source_id=ev.source_id,
                type_="raw_file", title=ev.title,
                payload=full.get("payload", {}),
                provenance={**ev.provenance, "origin": "mission_link", "import_evidence": ev.id},
                evidence_id=new_id("evidence"),
            )
            await d.repo.create_evidence_meta(linked)


@router.get("")
async def list_missions(request: Request):
    d = deps(request)
    return {"missions": [m.model_dump() for m in await d.repo.list_missions()]}


@router.get("/{mission_id}")
async def get_mission(mission_id: str, request: Request):
    d = deps(request)
    mission = await d.repo.get_mission(mission_id)
    if mission is None:
        raise HTTPException(404, "mission inconnue")
    return {"mission": mission.model_dump()}


@router.post("/{mission_id}/plan")
async def propose_plan(mission_id: str, request: Request):
    """Propose un plan IA sans l'exécuter (docs/02 étape 4 — l'humain approuve ensuite)."""
    d = deps(request)
    mission = await d.repo.get_mission(mission_id)
    if mission is None:
        raise HTTPException(404, "mission inconnue")

    from ...agent.orchestrator import RunOrchestrator
    from ...agent.prompts import SYSTEM_PROMPT, plan_request

    cfg = resolve_llm_config(d.llm_runtime)
    try:
        provider = build_provider(cfg)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    sources = {s.id: s for s in [await d.connectors.get_source(sid) for sid in mission.source_ids] if s}
    source_types = {sid: s.type for sid, s in sources.items()}
    capabilities = request.app.state.registry.capabilities_for_mission(mission, source_types)
    initial_evidence = await d.repo.list_evidence(mission_id=mission.id)
    orchestrator = RunOrchestrator(d.repo, d.store, d.connectors, d.executor, d.bus, d.input_models)
    payload = orchestrator._sources_payload(sources, initial_evidence)
    controls = [control_to_dict(get_control(c)) for c in mission.control_ids if get_control(c)]

    resp = await provider.chat(SYSTEM_PROMPT, [
        {"role": "user", "content": plan_request(mission.model_dump(), payload, capabilities, controls)}
    ])
    await provider.close()
    plan = _parse_plan_response(resp.content, mission, provider)
    return {"plan": plan}


def _parse_plan_response(content: str | None, mission: AuditMission, provider) -> dict:
    import json
    import re

    from ...models import AuditPlan

    if content:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        payload = {}
        if match:
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                payload = {}
    else:
        payload = {}
    plan = AuditPlan(
        id=new_id("plan"), mission_id=mission.id, provider_id=provider.provider_id, model_id=provider.model_id,
        steps=payload.get("steps", []), evidence_expected=payload.get("evidence_expected", []),
        risks=payload.get("risks", []),
    )
    return plan.model_dump()


def _safe_json(content: str | None) -> dict:
    import json
    import re

    if not content:
        return {}
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


@router.post("/{mission_id}/approve")
async def approve_plan(mission_id: str, body: ApproveBody, request: Request):
    """Approbation humaine explicite (docs/04 étape 4). Sans elle, les tools approved-tests sont bloqués."""
    d = deps(request)
    mission = await d.repo.get_mission(mission_id)
    if mission is None:
        raise HTTPException(404, "mission inconnue")
    steps = body.plan.get("steps", [])
    approved_actions = [
        {"tool": s.get("tool"), "source_id": (s.get("args") or {}).get("source_id") or s.get("source_id")}
        for s in steps if isinstance(s, dict) and s.get("tool")
    ]
    mission.approved_plan = {
        "plan_id": body.plan.get("id"),
        "approved_actions": approved_actions,
        "note": body.note,
        "approved_at": utcnow(),
    }
    mission.status = MissionStatus.approved
    await d.repo.update_mission(mission)
    return {"mission": mission.model_dump()}


@router.post("/{mission_id}/run")
async def start_run(mission_id: str, request: Request, body: RunBody | None = None):
    d = deps(request)
    mission = await d.repo.get_mission(mission_id)
    if mission is None:
        raise HTTPException(404, "mission inconnue")
    if not mission.source_ids:
        raise HTTPException(400, "mission sans sources : aucune collecte possible")
    if body and body.provider:
        d.llm_runtime["provider"] = body.provider
        if body.model:
            d.llm_runtime["model"] = body.model

    cfg = resolve_llm_config(d.llm_runtime)
    scenario = (body.scenario if body else None) or "data_audit"
    try:
        provider = build_provider(cfg, scenario=scenario)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    run = AuditRun(
        id=new_id("run"), mission_id=mission.id, status=RunStatus.not_started,
        provider_id=provider.provider_id, model_id=provider.model_id,
    )
    await d.repo.create_run(run)
    mission.status = MissionStatus.running
    await d.repo.update_mission(mission)

    async def _worker():
        async with d.run_semaphore:  # worker local borné (docs/03)
            try:
                await asyncio.wait_for(
                    d.orchestrator.execute_run(run, mission, provider),
                    timeout=mission.limits.max_seconds + 10,
                )
            except asyncio.TimeoutError:
                run.status = RunStatus.partial
                run.stop_reason = "budget_exhausted:max_seconds"
                run.finished_at = utcnow()
                await d.repo.update_run(run)
                await d.bus.publish(run.id, "run_completed", {"status": run.status.value, "stop_reason": run.stop_reason})
            finally:
                mission_status = await d.repo.get_mission(mission_id)
                if mission_status and mission_status.status == MissionStatus.running:
                    # Un run en pause n'est pas terminé : la mission reste `approved`
                    # (reprise possible via /resume) — ADR-15.
                    latest = run.status if run.status else RunStatus.not_started
                    mission_status.status = (
                        MissionStatus.running if latest == RunStatus.paused else MissionStatus.completed
                    )
                    await d.repo.update_mission(mission_status)

    task = asyncio.create_task(_worker())
    d.tasks.add(task)
    task.add_done_callback(d.tasks.discard)
    return {"run_id": run.id, "status": run.status.value}


class ExtendBudgetBody(BaseModel):
    add_tool_calls: int = Field(default=12, ge=1, le=200)
    add_seconds: int = Field(default=120, ge=10, le=3600)


@router.post("/{mission_id}/extend-budget")
async def extend_budget(mission_id: str, body: ExtendBudgetBody, request: Request):
    """Autorisation HUMAINE explicite de ressources supplémentaires (ADR-15).

    Aucune augmentation automatique : le run en pause reste en pause tant que
    l'auditeur n'a pas approuvé l'extension, puis relance via /resume.
    """
    d = deps(request)
    mission = await d.repo.get_mission(mission_id)
    if mission is None:
        raise HTTPException(404, "mission inconnue")
    mission.limits.max_tool_calls += body.add_tool_calls
    mission.limits.max_seconds += body.add_seconds
    mission.limits.max_decisions = None  # les garde-fous dérivés suivent le nouveau budget
    mission.limits.max_llm_calls = None
    await d.repo.update_mission(mission)
    return {"mission": mission.model_dump(), "extension": {
        "add_tool_calls": body.add_tool_calls, "add_seconds": body.add_seconds,
    }}


@router.get("/catalog/controls")
async def list_controls(request: Request):
    from ...audit.controls import list_controls

    return {"controls": [control_to_dict(c) for c in list_controls()]}


@router.get("/catalog/rulesets")
async def list_rulesets(request: Request):
    return {"rule_sets": [rs.model_dump() for rs in RULE_SETS.values()]}
