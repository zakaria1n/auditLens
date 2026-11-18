"""Runs : état, flux d'événements SSE, evidence, assessments, findings, rapport (docs/14)."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..deps import deps
from ...agent.providers import build_provider, resolve_llm_config
from ...core.ids import new_id
from ...models import AuditRun, MissionStatus, RunStatus, utcnow

router = APIRouter(prefix="/api/runs", tags=["runs"])

TERMINAL_STATUSES = {RunStatus.completed, RunStatus.failed, RunStatus.review_required,
                     RunStatus.partial, RunStatus.cancelled}
RESUMABLE_STATUSES = {RunStatus.paused, RunStatus.partial, RunStatus.failed}


@router.get("/{run_id}")
async def get_run(run_id: str, request: Request):
    d = deps(request)
    run = await d.repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run inconnu")
    return {"run": run.model_dump()}


@router.get("/{run_id}/checkpoint")
async def get_latest_checkpoint(run_id: str, request: Request):
    """Dernier checkpoint persistant d'investigation (ADR-15) — reprise et audit."""
    d = deps(request)
    run = await d.repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run inconnu")
    cp = await d.repo.latest_checkpoint(run_id)
    return {"checkpoint": cp.model_dump() if cp else None}


@router.post("/{run_id}/pause")
async def pause_run(run_id: str, request: Request):
    """Demande de pause : honorée par la boucle ENTRE deux tours (l'appel tool en cours,
    read-only et borné, se termine proprement — docs/05 exécution bornée)."""
    d = deps(request)
    run = await d.repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run inconnu")
    if run.status != RunStatus.running:
        raise HTTPException(400, f"run non pausable en statut {run.status.value} (running requis)")
    d.run_controls.setdefault(run_id, set()).add("pause")
    await d.bus.publish(run_id, "pause_requested", {"by": "auditor"})
    return {"ok": True, "status": run.status.value}


@router.post("/{run_id}/stop")
async def stop_run(run_id: str, request: Request):
    """Annulation gracieuse : checkpoint écrit, statut `cancelled`, preuves conservées."""
    d = deps(request)
    run = await d.repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run inconnu")
    if run.status != RunStatus.running:
        raise HTTPException(400, f"run non annulable en statut {run.status.value} (running requis)")
    d.run_controls.setdefault(run_id, set()).add("stop")
    await d.bus.publish(run_id, "stop_requested", {"by": "auditor"})
    return {"ok": True, "status": run.status.value}


@router.post("/{run_id}/resume")
async def resume_run(run_id: str, request: Request, body: dict | None = None):
    """Reprise depuis le dernier CHECKPOINT persistant (ADR-15).

    - Crée un NOUVEAU run dans la même mission (l'historique de l'ancien reste intact) ;
    - reconstruit l'état d'investigation (hypothèses, observations, budget consommé) ;
    - idempotent : les calculs déterministes déjà produits ne sont pas refaits
      (garde `odoo_cross_check` existant) et aucune couverture n'est re-planifiée.
    Body optionnel : {"provider": ..., "model": ...} (sinon provider du run d'origine).
    """
    d = deps(request)
    run = await d.repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run inconnu")
    if run.status not in RESUMABLE_STATUSES:
        raise HTTPException(400, f"run non reprenable en statut {run.status.value}")
    mission = await d.repo.get_mission(run.mission_id)
    if mission is None:
        raise HTTPException(404, "mission inconnue")

    cp = await d.repo.latest_checkpoint(run_id)
    if cp is None:
        raise HTTPException(400, "aucun checkpoint persistant pour ce run — reprise impossible")

    body = body or {}
    cfg = resolve_llm_config(d.llm_runtime)
    if body.get("provider"):
        cfg["provider"] = body["provider"]
        if body.get("model"):
            cfg["model"] = body["model"]
    try:
        provider = build_provider(cfg)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    new_run = AuditRun(
        id=new_id("run"), mission_id=mission.id, status=RunStatus.not_started,
        provider_id=provider.provider_id, model_id=provider.model_id,
    )
    await d.repo.create_run(new_run)
    await d.bus.publish(new_run.id, "run_resumed", {
        "from_run": run.id, "checkpoint_id": cp.id, "checkpoint_reason": cp.reason,
        "budget_consumed": cp.state.get("budget"),
    })
    mission.status = MissionStatus.running
    await d.repo.update_mission(mission)

    async def _worker():
        async with d.run_semaphore:
            try:
                await asyncio.wait_for(
                    d.orchestrator.execute_run(new_run, mission, provider,
                                               resume_state=cp.state),
                    timeout=mission.limits.max_seconds + 10,
                )
            except asyncio.TimeoutError:
                new_run.status = RunStatus.partial
                new_run.stop_reason = "budget_exhausted:max_seconds"
                new_run.finished_at = utcnow()
                await d.repo.update_run(new_run)
                await d.bus.publish(new_run.id, "run_completed",
                                    {"status": new_run.status.value, "stop_reason": new_run.stop_reason})
            finally:
                m = await d.repo.get_mission(mission.id)
                if m and m.status == MissionStatus.running:
                    m.status = MissionStatus.completed
                    await d.repo.update_mission(m)

    task = asyncio.create_task(_worker())
    d.tasks.add(task)
    task.add_done_callback(d.tasks.discard)
    return {"run_id": new_run.id, "resumed_from": run.id, "checkpoint_id": cp.id}


@router.get("")
async def list_runs(request: Request, mission_id: str | None = None):
    d = deps(request)
    return {"runs": [r.model_dump() for r in await d.repo.list_runs(mission_id)]}


@router.get("/{run_id}/events")
async def run_events(run_id: str, request: Request, after: int = 0):
    """Flux SSE des événements backend réels (docs/02 : animations = événements)."""
    d = deps(request)
    run = await d.repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run inconnu")

    async def generator():
        queue = d.bus.subscribe(run_id)
        last_seq = after
        try:
            # historique d'abord (l'abonnement est pris AVANT pour éviter les pertes)
            history = await d.repo.list_events(run_id, after_seq=after)
            for ev in history:
                last_seq = max(last_seq, ev.seq)
                yield f"id: {ev.seq}\ndata: {json.dumps(ev.model_dump(), ensure_ascii=False)}\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=4.0)
                except asyncio.TimeoutError:
                    current = await d.repo.get_run(run_id)
                    if current and current.status in TERMINAL_STATUSES:
                        break
                    continue
                if ev.seq <= last_seq:
                    continue  # déjà envoyé via l'historique
                last_seq = ev.seq
                yield f"id: {ev.seq}\ndata: {json.dumps(ev.model_dump(), ensure_ascii=False)}\n\n"
            yield 'event: end\ndata: {"status": "stream_end"}\n\n'
        finally:
            d.bus.unsubscribe(run_id, queue)

    return StreamingResponse(generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{run_id}/tool-calls")
async def list_tool_calls(run_id: str, request: Request):
    d = deps(request)
    return {"tool_calls": [t.model_dump() for t in await d.repo.list_tool_calls(run_id)]}


@router.get("/{run_id}/evidence")
async def list_run_evidence(run_id: str, request: Request):
    d = deps(request)
    return {"evidence": [e.model_dump() for e in await d.repo.list_evidence(run_id=run_id)]}


@router.get("/{run_id}/assessments")
async def list_assessments(run_id: str, request: Request):
    d = deps(request)
    return {"assessments": [a.model_dump() for a in await d.repo.list_assessments(run_id)]}


@router.get("/{run_id}/findings")
async def list_run_findings(run_id: str, request: Request):
    d = deps(request)
    return {"findings": [f.model_dump() for f in await d.repo.list_findings(run_id=run_id)]}


@router.get("/{run_id}/diff")
async def diff_runs(run_id: str, request: Request, base: str = ""):
    """Différentiel de findings entre le run de référence (base) et ce run (Phase 6/10).
    Statuts : persistent / resolved (contrôle ré-inspecté avec preuves) / new / unknown."""
    from ..audit.diff_audit import diff_findings

    d = deps(request)
    target = await d.repo.get_run(run_id)
    if target is None:
        raise HTTPException(404, "run cible inconnu")
    base_run = await d.repo.get_run(base) if base else None
    if base_run is None:
        raise HTTPException(404, "run de référence (base) inconnu")
    if base_run.mission_id != target.mission_id:
        raise HTTPException(400, "les deux runs doivent appartenir à la même mission")

    base_findings = await d.repo.list_findings(run_id=base)
    target_findings = await d.repo.list_findings(run_id=run_id)
    # contrôles réellement ré-inspectés par le run cible : assessments avec evidence
    inspected = {
        a.control_id
        for a in await d.repo.list_assessments(run_id)
        if a.evidence_refs
    }
    result = diff_findings(base_findings, target_findings, inspected)
    return {"base_run_id": base, "target_run_id": run_id, **result}


@router.get("/{run_id}/report")
async def get_report(run_id: str, request: Request):
    d = deps(request)
    report = await d.repo.get_latest_report(run_id)
    if report is None:
        raise HTTPException(404, "rapport non généré pour ce run")
    return {"report": report.model_dump()}
