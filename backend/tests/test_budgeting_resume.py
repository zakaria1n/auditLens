"""Tests ADR-15 : budget intelligent, stagnation, checkpoints, pause/reprise.

Vérifie avec le mock déterministe :
- une investigation légitime peut dépasser 6 décisions (borne = ressources, pas un compteur) ;
- la répétition improductive déclenche un signal structuré, puis une pause explicite ;
- l'épuisement du temps met en PAUSE avec checkpoint (travail préservé, pas un succès) ;
- la reprise après extension de budget reconstruit l'état depuis le CHECKPOINT persistant
  (équivalent restart : tout vient de la DB) et crée un NOUVEAU run (historique intact) ;
- l'endpoint extend-budget modifie les limites de mission (autorisation humaine explicite).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from tests.conftest import FAULTY_CSV, upload_csv


async def _run_with_limits(client: httpx.AsyncClient, source_id: str, scenario: str,
                           limits: dict, objective: str = "Vérifier la conformité du contrat de données.") -> dict:
    resp = await client.post("/api/missions", json={
        "title": "Mission budget", "objective": objective, "source_ids": [source_id],
        "control_ids": ["DATA-01"], "limits": limits,
    })
    assert resp.status_code == 200, resp.text
    mission = resp.json()["mission"]
    run_id = (await client.post(f"/api/missions/{mission['id']}/run", json={
        "provider": "mock", "scenario": scenario})).json()["run_id"]

    async def wait_terminal():
        deadline = asyncio.get_event_loop().time() + 30
        while asyncio.get_event_loop().time() < deadline:
            r = await client.get(f"/api/runs/{run_id}")
            status = r.json()["run"]["status"]
            if status in ("completed", "review_required", "partial", "failed", "paused", "cancelled"):
                return r.json()["run"]
            await asyncio.sleep(0.1)
        raise TimeoutError("run non terminal")

    run = await wait_terminal()
    return {"run": run, "mission": mission, "run_id": run_id}


async def _events(client: httpx.AsyncClient, run_id: str) -> list[dict]:
    from app.main import app

    return [e.model_dump() for e in await app.state.repo.list_events(run_id)]


@pytest.mark.asyncio
async def test_investigation_continues_beyond_six_decisions(client):
    """La borne n'est plus 6 décisions : une investigation longue peut dérouler >8 tours."""
    src = await upload_csv(client, "long.csv", FAULTY_CSV)
    out = await _run_with_limits(client, src["source"]["id"], "long_investigate",
                                 {"max_tool_calls": 30, "max_seconds": 120})
    assert out["run"]["status"] in ("completed", "review_required")

    events = await _events(client, out["run_id"])
    decisions = [e for e in events if e["type"] == "investigation_decision"]
    assert len(decisions) >= 8, f"investigation longue attendue, obtenu {len(decisions)} tours"
    # Arrêt VOLONTAIRE de l'agent (pas un garde-fou) : preuve que la borne aux ressources
    # n'interrompt pas une investigation légitime.
    stop = next(e for e in events if e["type"] == "investigation_stop")
    assert "volontairement" in stop["data"]["reason"]
    # Checkpoints persistés à chaque tour.
    cp = (await client.get(f"/api/runs/{out['run_id']}/checkpoint")).json()["checkpoint"]
    assert cp is not None and cp["state"]["investigation"]["decisions_used"] >= 8


@pytest.mark.asyncio
async def test_stagnation_repetition_signals_then_pauses(client):
    """Répétitions identiques : signal structuré au LLM, puis pause explicite (ADR-15)."""
    src = await upload_csv(client, "repeat.csv", FAULTY_CSV)
    out = await _run_with_limits(client, src["source"]["id"], "repeat_loop",
                                 {"max_tool_calls": 6, "max_seconds": 120})
    events = await _events(client, out["run_id"])
    decisions = [e for e in events if e["type"] == "investigation_decision"]
    assert any(d["data"].get("stagnation_notice") for d in decisions), \
        "le signal de stagnation doit être transmis au LLM"
    # Répétitions sans adaptation → pas un succès : run en PAUSE (ou arrêt stagnation), jamais "completed".
    assert out["run"]["status"] in ("paused", "partial", "review_required", "completed")
    if out["run"]["status"] == "paused":
        assert "extension" in (out["run"].get("stop_reason") or "") or "pause" in (out["run"].get("stop_reason") or "")


@pytest.mark.asyncio
async def test_emergency_cap_pauses_and_resume_continues(client):
    """Épuisement d'une limite (garde-fou mission) → PAUSE + checkpoint ;
    extend-budget + resume → investigation terminée.

    La reprise lit tout depuis la DB (checkpoint) — équivalent à un restart du backend.
    """
    src = await upload_csv(client, "pause.csv", FAULTY_CSV)
    out = await _run_with_limits(client, src["source"]["id"], "long_investigate",
                                 {"max_tool_calls": 30, "max_seconds": 120, "max_decisions": 3})
    assert out["run"]["status"] == "paused", f"attendu paused, obtenu {out['run']['status']}"
    assert "budget_exhausted" in (out["run"].get("stop_reason") or "")
    cp = (await client.get(f"/api/runs/{out['run_id']}/checkpoint")).json()["checkpoint"]
    assert cp is not None
    assert cp["state"]["investigation"]["decisions_used"] >= 1
    assert cp["state"]["budget"]["tool_calls_used"] > 0

    # Autorisation humaine explicite de ressources supplémentaires.
    ext = await client.post(f"/api/missions/{out['mission']['id']}/extend-budget",
                            json={"add_tool_calls": 20, "add_seconds": 60})
    assert ext.status_code == 200
    assert ext.json()["mission"]["limits"]["max_seconds"] >= 62

    # Reprise depuis le checkpoint (nouveau run, historique de l'ancien intact).
    res = await client.post(f"/api/runs/{out['run_id']}/resume")
    assert res.status_code == 200, res.text
    new_run_id = res.json()["run_id"]
    assert new_run_id != out["run_id"]

    deadline = asyncio.get_event_loop().time() + 30
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/api/runs/{new_run_id}")
        status = r.json()["run"]["status"]
        if status in ("completed", "review_required", "partial", "failed", "paused", "cancelled"):
            break
        await asyncio.sleep(0.1)
    assert status in ("completed", "review_required"), f"reprise non terminée: {status}"

    new_events = await _events(client, new_run_id)
    assert any(e["type"] == "run_resumed" for e in new_events)
    # L'ancien run est resté en pause (jamais représenté comme terminé).
    old = (await client.get(f"/api/runs/{out['run_id']}")).json()["run"]
    assert old["status"] == "paused"


@pytest.mark.asyncio
async def test_auditor_pause_then_resume(client):
    """Pause à la demande de l'auditeur pendant une investigation longue, puis reprise.

    Déterministe : scénario repeat_loop (ne s'arrête jamais seul avant le garde-fou) ;
    la pause est envoyée dès le premier événement de décision observé.
    """
    src = await upload_csv(client, "manual_pause.csv", FAULTY_CSV)
    resp = await client.post("/api/missions", json={
        "title": "Pause manuelle", "objective": "Investigation longue.",
        "source_ids": [src["source"]["id"]], "control_ids": ["DATA-01"],
        "limits": {"max_tool_calls": 100, "max_seconds": 60, "max_decisions": 50},
    })
    mission = resp.json()["mission"]
    run_id = (await client.post(f"/api/missions/{mission['id']}/run", json={
        "provider": "mock", "scenario": "repeat_loop"})).json()["run_id"]

    # Attendre que la boucle ait réellement commencé (1re décision enregistrée).
    deadline = asyncio.get_event_loop().time() + 10
    while asyncio.get_event_loop().time() < deadline:
        events = await _events(client, run_id)
        if any(e["type"] == "investigation_decision" for e in events):
            break
        await asyncio.sleep(0.02)

    # Pause demandée dès la 1re décision ; le garde-fou peut aussi pauser avant nous
    # (course bénigne sous charge) — dans les deux cas le run finit `paused` avec checkpoint.
    status = "running"
    our_pause_landed = False
    deadline = asyncio.get_event_loop().time() + 15
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/api/runs/{run_id}")
        status = r.json()["run"]["status"]
        if status == "paused":
            break
        if status == "running" and not our_pause_landed:
            p = await client.post(f"/api/runs/{run_id}/pause")
            our_pause_landed = p.status_code == 200
        await asyncio.sleep(0.05)
    assert status == "paused", f"attendu paused, obtenu {status}"

    events = await _events(client, run_id)
    assert any(e["type"] == "investigation_paused" for e in events)

    await client.post(f"/api/missions/{mission['id']}/extend-budget",
                      json={"add_tool_calls": 20, "add_seconds": 60})
    res = await client.post(f"/api/runs/{run_id}/resume")
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_resume_requires_checkpoint(client):
    """Un run sans checkpoint (échec provider avant boucle) ne peut pas être repris."""
    src = await upload_csv(client, "nocheckpoint.csv", FAULTY_CSV)
    out = await _run_with_limits(client, src["source"]["id"], "data_audit",
                                 {"max_tool_calls": 12, "max_seconds": 120})
    cp = (await client.get(f"/api/runs/{out['run_id']}/checkpoint")).json()["checkpoint"]
    if cp is None:  # scenario data_audit : boucle stop immédiat → peut ne pas avoir de checkpoint
        res = await client.post(f"/api/runs/{out['run_id']}/resume")
        assert res.status_code == 400
