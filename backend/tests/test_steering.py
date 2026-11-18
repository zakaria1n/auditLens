"""Phase 8/10 — Live Agent Steering : file d'instructions, frontière de tour,
anti-doublon, périmètre inchangé."""

from __future__ import annotations

from app.agent.steering import SteeringQueue


def test_submit_and_drain():
    q = SteeringQueue()
    item = q.submit("r1", "focus sur les factures")
    assert item is not None and item.status == "queued"
    drained = q.drain("r1")
    assert len(drained) == 1 and drained[0].status == "applied"
    assert q.drain("r1") == []  # rien en attente après consommation


def test_duplicate_instruction_rejected():
    q = SteeringQueue()
    q.submit("r1", "focus sur les factures")
    q.submit("r1", "focus sur les factures")  # même contenu, encore queued
    assert len(q.items("r1")) == 1  # anti-doublon


def test_isolated_per_run():
    q = SteeringQueue()
    q.submit("r1", "a")
    assert q.items("r2") == []
    assert q.drain("r2") == []


def test_reset_on_new_mission_cycle():
    q = SteeringQueue()
    q.submit("r1", "x")
    q.reset("r1")
    assert q.items("r1") == []


def test_empty_instruction_ignored():
    q = SteeringQueue()
    assert q.submit("r1", "   ") is None


async def test_steering_route_end_to_end(client):
    """Intégration route : submit sur run en cours => queued ; drain à la frontière."""
    from app.main import app

    from .conftest import upload_csv
    from .test_conversations import wait_run_terminal

    src = (await upload_csv(client, "orders.csv", (
        "order_id,order_date,quantity\nSO-1,2026-01-01,2\n"
    )))["source"]
    mission = (await client.post("/api/missions", json={
        "title": "t", "objective": "o", "source_ids": [src["id"]], "control_ids": ["DATA-01"],
    })).json()["mission"]
    run_id = (await client.post(f"/api/missions/{mission['id']}/run", json={})).json()["run_id"]

    # une instruction immédiatement (le run mock est rapide : peut être déjà terminé => 409)
    r = await client.post(f"/api/runs/{run_id}/steer", json={"instruction": "focus sur les quantités négatives"})
    assert r.status_code in (200, 409)
    await wait_run_terminal(client, run_id)
    # status endpoint toujours disponible
    r2 = await client.get(f"/api/runs/{run_id}/steer")
    assert r2.status_code == 200
    assert isinstance(r2.json()["steering"], list)
