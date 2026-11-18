"""Evidence (lecture + vérification d'intégrité) et Findings (revue humaine) — docs/14."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...core.errors import EvidenceNotFound
from ..deps import deps
from ...models import FindingStatus, MissionStatus

router = APIRouter(tags=["evidence_findings"])


@router.get("/api/evidence/{evidence_id}")
async def get_evidence(evidence_id: str, request: Request, mission_id: str):
    d = deps(request)
    ev = await d.repo.get_evidence_meta(evidence_id, mission_id)
    if ev is None:
        raise HTTPException(404, "evidence inconnue ou hors mission")
    full = d.store.load(ev)  # lève ValueError si checksum différent (docs/13)
    return {
        "evidence": {**ev.model_dump(), "integrity_verified": True},
        "payload": full.get("payload"),
    }


class ReviewBody(BaseModel):
    decision: str  # accepted | rejected | needs_more_evidence
    reason: str = ""


@router.post("/api/findings/{finding_id}/review")
async def review_finding(finding_id: str, body: ReviewBody, request: Request):
    """Revue humaine : Accept / Reject / Needs More Evidence avec justification (docs/02 étape 8)."""
    d = deps(request)
    if body.decision not in (FindingStatus.accepted.value, FindingStatus.rejected.value, FindingStatus.needs_more_evidence.value):
        raise HTTPException(400, "décision invalide (accepted|rejected|needs_more_evidence)")
    finding = await d.repo.get_finding(finding_id)
    if finding is None:
        raise HTTPException(404, "finding inconnu")
    if finding.status == FindingStatus.rejected:
        raise HTTPException(400, "finding déjà rejeté par le validateur structurel — revue impossible")

    from ...models import AuditorReview

    finding.review = AuditorReview(decision=body.decision, reason=body.reason)  # type: ignore[arg-type]
    finding.status = FindingStatus(body.decision)
    if body.decision == "accepted" and not finding.evidence_refs:
        # Invariant docs/14 — refus serveur explicite
        raise HTTPException(400, "un finding sans evidence ne peut pas être confirmé (procédure manuelle requise)")
    await d.repo.update_finding(finding)
    await _regenerate_report(d, finding.run_id)
    return {"finding": finding.model_dump()}


async def _regenerate_report(d, run_id: str) -> None:
    """Revue humaine => nouvelle version explicite du rapport (docs/14 : pas de régénération silencieuse)."""
    from ...findings.reports import build_report

    run = await d.repo.get_run(run_id)
    if run is None:
        return
    mission = await d.repo.get_mission(run.mission_id)
    if mission is None:
        return
    previous = await d.repo.get_latest_report(run_id)
    version = (previous.version if previous else 0) + 1
    report = build_report(
        run, mission,
        await d.repo.list_assessments(run_id),
        await d.repo.list_evidence(run_id=run_id),
        await d.repo.list_findings(run_id=run_id),
        version=version,
    )
    await d.repo.create_report(report)


@router.get("/api/findings")
async def list_findings(request: Request, run_id: str | None = None, mission_id: str | None = None):
    d = deps(request)
    return {"findings": [f.model_dump() for f in await d.repo.list_findings(run_id, mission_id)]}


@router.get("/api/missions/{mission_id}/evidence")
async def list_mission_evidence(mission_id: str, request: Request):
    d = deps(request)
    return {"evidence": [e.model_dump() for e in await d.repo.list_evidence(mission_id=mission_id)]}
