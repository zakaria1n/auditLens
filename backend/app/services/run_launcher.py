"""Lancement de run : mécanisme UNIQUE partagé (ADR-16).

Utilisé par la route missions (POST /{id}/run) et par le chat (tool create_audit).
Une seule implémentation → aucun second mécanisme de démarrage/persistance.
"""

from __future__ import annotations

import asyncio

from ..agent.providers.base import LLMProvider
from ..core.ids import new_id
from ..models import AuditMission, AuditRun, MissionStatus, RunStatus
from ..models.schemas import utcnow


async def launch_run(d, mission: AuditMission, provider: LLMProvider) -> AuditRun:
    """Crée le run, lance le worker borné (sémaphore local) et rend immédiatement.

    `d` : AppDeps (repo, orchestrator, bus, run_semaphore, tasks).
    """
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
                mission_status = await d.repo.get_mission(mission.id)
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
    return run
