"""Tests de la boucle d'investigation agentique (ADR-14).

Vérifie avec le mock déterministe :
- la boucle exécute des appels DÉPENDANTS post-coverage et journalise décisions/hypothèses/arrêt ;
- un refus Policy Gate pendant la boucle est une observation structurée (le run ne casse pas) ;
- l'interrupteur AUDITLENS_INVESTIGATION_LOOP=off reproduit le pipeline historique (Baseline B) ;
- parse_decision dégrade prudemment (arrêt explicite, jamais d'exception) ;
- evidence_search localise des enregistrements dans une preuve (outil d'investigation borné).
"""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import run_mission, upload_csv


async def _events(client: httpx.AsyncClient, run_id: str) -> list[dict]:
    # /events est un flux SSE : on lit l'historique persisté via l'app (docs/19).
    from app.main import app

    events = await app.state.repo.list_events(run_id)
    return [e.model_dump() for e in events]


async def _tool_calls(client: httpx.AsyncClient, run_id: str) -> list[dict]:
    resp = await client.get(f"/api/runs/{run_id}/tool-calls")
    assert resp.status_code == 200, resp.text
    return resp.json()["tool_calls"]


@pytest.mark.asyncio
async def test_loop_investigates_dependent_call_and_hypotheses(client):
    """Scénario `investigate` : hypothèse → extrait de preuve → révision → arrêt explicite."""
    src = await upload_csv(client, "loop.csv", await _faulty_csv(client))
    out = await run_mission(client, src["source"]["id"], scenario="investigate")
    assert out["run"]["status"] in ("completed", "review_required")

    events = await _events(client, out["run_id"])
    types = [e["type"] for e in events]
    assert "phase" in types
    assert "investigation_decision" in types, "la boucle doit journaliser ses décisions"
    assert "hypothesis_created" in types, "l'agent doit consigner une hypothèse"
    assert "hypothesis_updated" in types, "l'agent doit réviser l'hypothèse après observation"
    assert "investigation_stop" in types, "l'arrêt doit être explicite et raisonné"

    decisions = [e for e in events if e["type"] == "investigation_decision"]
    assert any(d["data"]["decision"] == "call_tool" for d in decisions)
    assert any(d["data"]["decision"] == "stop" for d in decisions)
    stop = next(e for e in events if e["type"] == "investigation_stop")
    assert stop["data"]["reason"], "stop sans rationale"

    updated = next(e for e in events if e["type"] == "hypothesis_updated")
    assert updated["data"]["status"] in ("supported", "inconclusive")
    # Prudence : sans contenu observé (extrait vide sur un fichier sans records), l'hypothèse
    # ne peut pas être déclarée « supported ».
    if "enregistrements=0" in str(updated["data"]["statement"]):
        assert updated["data"]["status"] == "inconclusive"
    # Révision appuyée sur une evidence RÉELLE créée pendant la boucle (appel dépendant).
    assert updated["data"]["evidence_refs"], "l'hypothèse révisée doit citer une preuve réelle"

    tools = await _tool_calls(client, out["run_id"])
    names = [t["name"] for t in tools]
    assert "get_evidence_excerpt" in names, "la boucle doit pouvoir exécuter des tools post-plan"
    # L'appel de boucle vient APRÈS la couverture planifiée (ordre des événements séquencés).
    event_tools = [e["data"].get("tool") for e in events if e["type"] == "tool_started"]
    assert event_tools.index("get_evidence_excerpt") > event_tools.index("data_profile")
    # L'agent a ciblé une preuve RÉELLE de la mission (pas un id inventé).
    excerpt_call = next(t for t in tools if t["name"] == "get_evidence_excerpt")
    assert excerpt_call["args"].get("evidence_id", "").startswith("ev_")


@pytest.mark.asyncio
async def test_loop_blocked_tool_is_structured_observation(client):
    """Un refus Policy Gate pendant la boucle ne casse pas le run et est consigné."""
    src = await upload_csv(client, "blocked.csv", await _faulty_csv(client))
    out = await run_mission(client, src["source"]["id"], scenario="blocked")
    assert out["run"]["status"] in ("completed", "review_required", "partial")

    events = await _events(client, out["run_id"])
    decisions = [e for e in events if e["type"] == "investigation_decision"]
    assert any(d["data"]["decision"] == "call_tool" for d in decisions)
    assert any(d["data"]["decision"] == "update_hypotheses" for d in decisions)
    stop = next(e for e in events if e["type"] == "investigation_stop")
    assert "Refus" in stop["data"]["reason"]

    tools = await _tool_calls(client, out["run_id"])
    assert any(t["status"] == "unauthorized" for t in tools), "le refus doit être journalisé (docs/13)"
    created = next(e for e in events if e["type"] == "hypothesis_created")
    assert created["data"]["id"] == "h_blocked"


@pytest.mark.asyncio
async def test_loop_disabled_reproduces_historical_pipeline(client, monkeypatch):
    """Baseline B (pipeline sans boucle) : aucun événement d'investigation."""
    monkeypatch.setenv("AUDITLENS_INVESTIGATION_LOOP", "off")
    src = await upload_csv(client, "noboop.csv", await _faulty_csv(client))
    out = await run_mission(client, src["source"]["id"], scenario="investigate")
    assert out["run"]["status"] in ("completed", "review_required")

    types = [e["type"] for e in await _events(client, out["run_id"])]
    assert "investigation_decision" not in types
    assert "hypothesis_created" not in types
    assert "investigation_stop" not in types


@pytest.mark.asyncio
async def test_parse_decision_safe_fallbacks():
    from app.agent.investigation import parse_decision

    # payload illisible → arrêt prudent explicite
    d = parse_decision({"decision": 42, "foo": "bar"})
    assert d["decision"] == "stop"
    assert d["stop_rationale"]
    # call_tool sans tool → arrêt prudent
    d = parse_decision({"decision": "call_tool", "args": {"x": 1}})
    assert d["decision"] == "stop"
    assert d["stop_rationale"]
    # décision normale : args non-dict → {}
    d = parse_decision({"decision": "call_tool", "tool": "data_profile", "args": "nope"})
    assert d["decision"] == "call_tool" and d["args"] == {}
    # stop sans rationale → rationale par défaut
    d = parse_decision({"decision": "stop"})
    assert d["stop_rationale"]
    # hypotheses non-liste → ignorées
    d = parse_decision({"decision": "update_hypotheses", "hypotheses": "bad"})
    assert d["hypotheses"] == []


@pytest.mark.asyncio
async def test_evidence_search_localizes_records(client):
    """evidence_search localise enregistrements et lignes par identifiant, champ optionnel."""
    from app.core.ids import new_id
    from app.harness.contracts import ToolContext
    from app.main import app
    from app.models import AuditMission
    from app.tools.all_tools import tool_evidence_search

    repo, store = app.state.repo, app.state.store
    mission = AuditMission(
        id=new_id("mission"), title="t", objective="o", source_ids=[], control_ids=[],
        time_range={}, limits={"max_tool_calls": 5, "max_seconds": 60, "max_input_chars": 100_000, "max_page_size": 500},
    )
    await repo.create_mission(mission)
    eid = new_id("evidence")
    ev = store.save(
        mission_id=mission.id, run_id=None, source_id=None, type_="record_set",
        title="Commandes test",
        payload={
            "records": [{"order_id": "SO-1000", "total": 10}, {"order_id": "SO-1042", "total": 3}],
            "lines": [{"order_id": "SO-1042", "qty": 2}],
        },
        provenance={"tool": "test"}, record_count=2, summary={}, evidence_id=eid,
    )
    await repo.create_evidence_meta(ev)

    ctx = ToolContext(
        mission=mission, run_id=None, source=None, secrets={}, store=store, repo=repo,
        connectors=app.state.connectors, extra={"tool_input_models": app.state.input_models},
    )
    res = await tool_evidence_search(ctx, {"evidence_id": eid, "query": "SO-1042"})
    assert res.status == "success"
    assert res.record_count == 2  # 1 enregistrement + 1 ligne
    assert {h["section"] for h in res.preview["hits"]} == {"records", "lines"}
    assert res.evidence_ids, "la recherche doit produire une preuve traçable"

    r2 = await tool_evidence_search(ctx, {"evidence_id": eid, "query": "3", "field": "total"})
    assert r2.record_count == 1
    assert r2.preview["hits"][0]["record"]["order_id"] == "SO-1042"

    r3 = await tool_evidence_search(ctx, {"evidence_id": eid, "query": "absent_chez_nous"})
    assert r3.record_count == 0 and r3.status == "success"

    # hors mission : refus (scope docs/13)
    from app.core.errors import EvidenceNotFound

    with pytest.raises(EvidenceNotFound):
        await tool_evidence_search(ctx, {"evidence_id": "evidence_inconnu", "query": "x"})


async def _faulty_csv(client) -> str:
    from tests.conftest import FAULTY_CSV

    return FAULTY_CSV
