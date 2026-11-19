"""Phase 1 fiabilité — evidence_search sur evidences raw_file (JSON plat/imbriqué/
JSONL/CSV) et régression des preuves structurées (records/pickings/lines).

Distinctions explicites exigées (jamais de succès trompeur avec rows_scanned=0) :
- aucune correspondance → success, hit_count=0, rows_scanned>0 ;
- rien de consultable → insufficient_evidence ;
- fichier brut illisible (malformé, supprimé) → error ;
- bornes → scan_truncated / file_truncated + warnings.
Chaque hit est traçable : evidence excerpt, source_evidence_id, index d'enregistrement.
"""

from __future__ import annotations

import json

from app.main import app as fastapp

FLAT_JSON = json.dumps([
    {"order_id": "SO-1", "customer": "Alpha", "quantity": 5, "status": "sale"},
    {"order_id": "SO-2", "customer": "Beta", "quantity": 2, "status": "done"},
    {"order_id": "SO-3", "customer": "Gamma", "quantity": -1, "status": "sale"},
])

NESTED_JSON = json.dumps({
    "meta": {"generated": "2026-11-18", "version": 2},
    "orders": [
        {"id": "SO-10", "client": {"name": "Société Nord", "city": "Lille"}, "amount": 120.5},
        {"id": "SO-11", "client": {"name": "Société Sud", "city": "Marseille"}, "amount": 0},
    ],
})

JSONL_CONTENT = (
    '{"order_id": "JL-1", "quantity": 3}\n'
    '{"order_id": "JL-2", "quantity": 4}\n'
)

MALFORMED_JSON = '{"order_id": "SO-9", "quantity'  # tronqué — syntaxe invalide


async def _upload(client, content: str, name: str, media: str = "application/json") -> dict:
    resp = await client.post(
        "/api/sources/file", params={"name": name},
        files={"file": (name, content.encode("utf-8"), media)},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _setup(client, content: str, name: str = "orders.json", media: str = "application/json"):
    """Upload → mission → contexte tool + evidence raw_file mission-scopée."""
    data = await _upload(client, content, name, media)
    src = data["source"]
    mission = (await client.post("/api/missions", json={
        "title": "t", "objective": "o", "source_ids": [src["id"]],
    })).json()["mission"]
    from app.harness.contracts import ToolContext

    ctx = ToolContext(
        mission=(await fastapp.state.repo.get_mission(mission["id"])), run_id="run_test",
        source=None, secrets={}, store=fastapp.state.store, repo=fastapp.state.repo,
        connectors=fastapp.state.connectors,
        extra={"tool_input_models": fastapp.state.input_models},
    )
    evs = await fastapp.state.repo.list_evidence(mission_id=mission["id"])
    raw_ev = next(e for e in evs if e.type == "raw_file")
    return ctx, raw_ev


async def _search(ctx, ev, query: str, **kw):
    return await fastapp.state.executor.execute(
        "evidence_search", {"evidence_id": ev.id, "query": query, **kw}, ctx,
    )


async def test_search_flat_json_hit(client):
    ctx, ev = await _setup(client, FLAT_JSON)
    result = await _search(ctx, ev, "SO-2")
    assert result.status == "success", result.error
    assert result.preview["rows_scanned"] == 3
    assert result.preview["hit_count"] == 1
    assert result.preview["records_source"] == "raw_file"
    hit = result.preview["hits"][0]
    assert hit["section"] == "records" and hit["index"] == 1
    assert hit["record"]["order_id"] == "SO-2"


async def test_search_no_match_is_success_not_misleading(client):
    """Aucune correspondance ≠ rien de consultable : rows_scanned>0, note explicite."""
    ctx, ev = await _setup(client, FLAT_JSON)
    result = await _search(ctx, ev, "introuvable-xyz-000")
    assert result.status == "success", result.error
    assert result.preview["hit_count"] == 0
    assert result.preview["rows_scanned"] == 3
    assert "aucune correspondance" in result.preview["note"]
    saved = await fastapp.state.repo.get_evidence_meta(result.evidence_ids[0], ctx.mission.id)
    assert saved.record_count == 0


async def test_search_nested_json_dotted_field(client):
    ctx, ev = await _setup(client, NESTED_JSON)
    result = await _search(ctx, ev, "nord", field="client.name")
    assert result.status == "success", result.error
    assert result.preview["hit_count"] == 1
    assert result.preview["hits"][0]["record"]["client.name"] == "Société Nord"
    # la même sous-chaîne dans client.city ne matche PAS le filtre client.name
    result2 = await _search(ctx, ev, "lille", field="client.name")
    assert result2.preview["hit_count"] == 0 and result2.preview["rows_scanned"] == 2
    # sans filtre, la sous-chaîne traverse tout l'enregistrement
    result3 = await _search(ctx, ev, "lille")
    assert result3.preview["hit_count"] == 1


async def test_search_nested_traversal_on_payload_records(client):
    """Champ imbriqué non aplati (preuve structurée) : traversée chemin pointé."""
    from app.harness.contracts import ToolContext

    mission = (await client.post("/api/missions", json={
        "title": "t", "objective": "o",
    })).json()["mission"]
    ctx = ToolContext(
        mission=(await fastapp.state.repo.get_mission(mission["id"])), run_id="run_test",
        source=None, secrets={}, store=fastapp.state.store, repo=fastapp.state.repo,
        connectors=fastapp.state.connectors,
        extra={"tool_input_models": fastapp.state.input_models},
    )
    ev = fastapp.state.store.save(
        mission_id=mission["id"], run_id=None, source_id=None, type_="record_set",
        title="nested", payload={"records": [
            {"id": "A", "client": {"name": "Société X"}},
            {"id": "B", "client": {"name": "Société Y"}},
        ]},
        provenance={"tool": "test"}, evidence_id="ev_nested_payload",
    )
    await fastapp.state.repo.create_evidence_meta(ev)
    result = await _search(ctx, ev, "société x", field="client.name")
    assert result.status == "success", result.error
    assert result.preview["hit_count"] == 1
    assert result.preview["hits"][0]["index"] == 0
    assert result.preview["records_source"] == "payload"


async def test_search_jsonl(client):
    ctx, ev = await _setup(client, JSONL_CONTENT, name="events.jsonl")
    result = await _search(ctx, ev, "JL-2")
    assert result.status == "success", result.error
    assert result.preview["hit_count"] == 1
    assert result.preview["rows_scanned"] == 2


async def test_search_numeric_value(client):
    ctx, ev = await _setup(client, FLAT_JSON)
    result = await _search(ctx, ev, "-1", field="quantity")  # quantité négative
    assert result.preview["hit_count"] == 1
    assert result.preview["hits"][0]["record"]["order_id"] == "SO-3"


async def test_search_malformed_json_is_error(client):
    """Fichier malformé → error explicite, pas de succès trompeur ni d'exception brute."""
    ctx, ev = await _setup(client, MALFORMED_JSON, name="broken.json")
    result = await _search(ctx, ev, "SO-9")
    assert result.status == "error"
    assert "fichier source illisible" in result.error
    assert result.preview["rows_scanned"] == 0
    assert not result.evidence_ids  # aucune evidence excerpt créée sur erreur


async def test_search_no_searchable_records(client):
    """Preuve sans enregistrements (profile) → insufficient_evidence, jamais success."""
    from app.harness.contracts import ToolContext

    mission = (await client.post("/api/missions", json={
        "title": "t", "objective": "o",
    })).json()["mission"]
    ctx = ToolContext(
        mission=(await fastapp.state.repo.get_mission(mission["id"])), run_id="run_test",
        source=None, secrets={}, store=fastapp.state.store, repo=fastapp.state.repo,
        connectors=fastapp.state.connectors,
        extra={"tool_input_models": fastapp.state.input_models},
    )
    ev = fastapp.state.store.save(
        mission_id=mission["id"], run_id=None, source_id=None, type_="profile",
        title="profil", payload={"stats": {"rows": 42}},
        provenance={"tool": "test"}, evidence_id="ev_profile_test",
    )
    await fastapp.state.repo.create_evidence_meta(ev)
    result = await _search(ctx, ev, "42")
    assert result.status == "insufficient_evidence"
    assert "aucun enregistrement consultable" in result.error
    assert not result.evidence_ids


async def test_search_max_hits_bound(client):
    ctx, ev = await _setup(client, FLAT_JSON)
    result = await _search(ctx, ev, "SO", max_hits=1)
    assert result.status == "success"
    assert result.preview["hit_count"] == 1  # stop dès max_hits


async def test_search_scan_limit_truncation(client, monkeypatch):
    """Borne CPU sur preuve structurée : scan_truncated + warning affiné."""
    monkeypatch.setattr("app.tools.all_tools.MAX_SEARCH_SCAN", 2)
    from app.harness.contracts import ToolContext

    mission = (await client.post("/api/missions", json={
        "title": "t", "objective": "o",
    })).json()["mission"]
    ctx = ToolContext(
        mission=(await fastapp.state.repo.get_mission(mission["id"])), run_id="run_test",
        source=None, secrets={}, store=fastapp.state.store, repo=fastapp.state.repo,
        connectors=fastapp.state.connectors,
        extra={"tool_input_models": fastapp.state.input_models},
    )
    ev = fastapp.state.store.save(
        mission_id=mission["id"], run_id=None, source_id=None, type_="record_set",
        title="bulk", payload={"records": [
            {"id": f"R{i}", "tag": "hit"} for i in range(6)
        ]},
        provenance={"tool": "test"}, evidence_id="ev_bulk_test",
    )
    await fastapp.state.repo.create_evidence_meta(ev)
    result = await _search(ctx, ev, "hit")
    assert result.status == "success"
    assert result.preview["rows_scanned"] == 2
    assert result.preview["scan_truncated"] is True
    assert any("affiner la requête" in w for w in result.warnings)


async def test_search_raw_file_load_bound_warns(client, monkeypatch):
    """Fichier brut > borne de chargement : file_truncated signalé honnêtement."""
    monkeypatch.setattr("app.tools.all_tools.MAX_SEARCH_SCAN", 2)
    ctx, ev = await _setup(client, FLAT_JSON)
    result = await _search(ctx, ev, "SO-3")  # 3e enregistrement, hors borne
    assert result.status == "success"
    assert result.preview["file_truncated"] is True
    assert any("borné" in w for w in result.warnings)


async def test_search_named_sections_regression(client):
    """Régression preuves structurées multi-sections (pickings) : comportement conservé."""
    from app.harness.contracts import ToolContext

    mission = (await client.post("/api/missions", json={
        "title": "t", "objective": "o",
    })).json()["mission"]
    ctx = ToolContext(
        mission=(await fastapp.state.repo.get_mission(mission["id"])), run_id="run_test",
        source=None, secrets={}, store=fastapp.state.store, repo=fastapp.state.repo,
        connectors=fastapp.state.connectors,
        extra={"tool_input_models": fastapp.state.input_models},
    )
    ev = fastapp.state.store.save(
        mission_id=mission["id"], run_id=None, source_id=None, type_="record_set",
        title="stock", payload={"pickings": [
            {"name": "WH/PICK/0001", "qty": 4},
            {"name": "WH/PICK/0002", "qty": 2},
        ]},
        provenance={"tool": "test"}, evidence_id="ev_pickings_test",
    )
    await fastapp.state.repo.create_evidence_meta(ev)
    result = await _search(ctx, ev, "WH/PICK/0002")
    assert result.status == "success", result.error
    assert result.preview["hit_count"] == 1
    assert result.preview["hits"][0]["section"] == "pickings"
    assert result.preview["hits"][0]["index"] == 1


async def test_search_evidence_provenance(client):
    """La preuve excerpt est traçable : source_evidence_id, provenance tool, intégrité."""
    ctx, ev = await _setup(client, FLAT_JSON)
    result = await _search(ctx, ev, "SO-2")
    saved = await fastapp.state.repo.get_evidence_meta(result.evidence_ids[0], ctx.mission.id)
    assert saved.type == "excerpt"
    assert saved.provenance["tool"] == "evidence_search"
    assert saved.provenance["source_evidence"] == ev.id
    assert fastapp.state.store.verify(saved) is True
    full = fastapp.state.store.load(saved)
    assert full["payload"]["source_evidence_id"] == ev.id
    assert full["payload"]["records_source"] == "raw_file"


async def test_search_csv_raw_file_regression(client):
    """CSV brut : même fallback connecteur, recherche fonctionnelle."""
    ctx, ev = await _setup(
        client,
        "order_id,quantity\nSO-C1,5\nSO-C2,3\n", name="orders.csv", media="text/csv",
    )
    result = await _search(ctx, ev, "SO-C2")
    assert result.status == "success", result.error
    assert result.preview["hit_count"] == 1
    assert result.preview["records_source"] == "raw_file"


async def test_data_explore_raw_json_and_malformed(client):
    """data_explore sur raw_file JSON : projection chemin pointé OK ; malformé → error."""
    ctx, ev = await _setup(client, NESTED_JSON)
    result = await fastapp.state.executor.execute("data_explore", {
        "evidence_id": ev.id,
        "spec": {"fields": ["id", "client.name", "amount"],
                 "filter": [{"field": "client.city", "op": "eq", "value": "Lille"}]},
    }, ctx)
    assert result.status == "success", result.error
    assert result.preview["table"] == [{
        "id": "SO-10", "client.name": "Société Nord", "amount": 120.5,
    }]

    ctx2, ev2 = await _setup(client, MALFORMED_JSON, name="broken2.json")
    result2 = await fastapp.state.executor.execute("data_explore", {
        "evidence_id": ev2.id, "spec": {"fields": ["order_id"]},
    }, ctx2)
    assert result2.status == "error"
    assert "fichier source illisible" in result2.error
