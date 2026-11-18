"""Bibliothèque de rapports (ADR-17) : archive centralisée, recherche, lien vers
la conversation d'origine. Les rapports restent versionnés par run (invariant docs/14)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..deps import deps

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("")
async def list_reports(request: Request, q: str | None = None):
    """Tous les rapports générés (toutes conversations/missions confondues), triés
    par date décroissante. `q` filtre sur titre de mission / modèle / id de rapport."""
    d = deps(request)
    needle = (q or "").strip().lower()
    # une entrée par run : la dernière version seulement (les versions restent consultables
    # depuis la page du rapport — invariant docs/14 « rapports versionnés »)
    latest_by_run: dict[str, object] = {}
    for rep in await d.repo.list_reports():
        if rep.run_id not in latest_by_run:
            latest_by_run[rep.run_id] = rep
    out = []
    for rep in latest_by_run.values():
        mission = await d.repo.get_mission(rep.mission_id)
        thread = await d.repo.find_thread_by_run(rep.run_id)
        item = {
            "id": rep.id,
            "run_id": rep.run_id,
            "mission_id": rep.mission_id,
            "mission_title": mission.title if mission else "mission inconnue",
            "version": rep.version,
            "created_at": rep.created_at,
            "model_id": rep.model_id,
            "provider_id": rep.provider_id,
            "findings_included": len(rep.findings_included),
            "thread_id": thread.id if thread else None,
        }
        if needle and needle not in (
            item["mission_title"] + " " + item["model_id"] + " " + item["id"] + " " + item["run_id"]
        ).lower():
            continue
        out.append(item)
    return {"reports": out}
