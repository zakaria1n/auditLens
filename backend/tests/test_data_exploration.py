"""Phase 2/10 — exploration bornée et déterministe (tool data_explore).

Calculs déterministes (filtre/tri/groupe/agrégat/comparaison) exécutés par le backend,
jamais par le modèle ; bornes respectées ; preuve source immuable ; champs inconnus
rejetés avec la liste des champs disponibles ; Decimal pour la précision.
"""

from __future__ import annotations

from app.audit.exploration import apply_exploration

RECORDS = [
    {"order_id": "SO-1", "customer": "A", "quantity": 5, "price": "120.50", "status": "sale"},
    {"order_id": "SO-2", "customer": "B", "quantity": -3, "price": "80.00", "status": "done"},
    {"order_id": "SO-3", "customer": "A", "quantity": 2, "price": None, "status": "sent"},
    {"order_id": "SO-4", "customer": "C", "quantity": 7, "price": "15.25", "status": "sale"},
    {"order_id": "SO-5", "customer": "A", "quantity": 1, "price": "10,00", "status": "sale"},
]


def test_filter_numeric_and_contains():
    out = apply_exploration(RECORDS, {"filter": [{"field": "quantity", "op": "gt", "value": 1}]})
    assert out["total_after_filters"] == 3  # 5, 2, 7
    out2 = apply_exploration(RECORDS, {"filter": [{"field": "status", "op": "contains", "value": "sal"}]})
    assert out2["total_after_filters"] == 3


def test_filter_not_null_excludes_missing():
    out = apply_exploration(RECORDS, {"filter": [{"field": "price", "op": "not_null"}]})
    assert out["total_after_filters"] == 4  # price None exclue


def test_sort_numeric_desc_then_limit():
    out = apply_exploration(RECORDS, {"sort": [{"field": "quantity", "dir": "desc"}], "limit": 2})
    assert [r["order_id"] for r in out["table"]] == ["SO-4", "SO-1"]
    assert out["returned_rows"] == 2 and out["total_after_filters"] == 5


def test_group_aggregate_sum_with_decimal_comma_and_nulls():
    out = apply_exploration(RECORDS, {
        "group_by": "customer", "aggregate": {"op": "sum", "field": "quantity"},
    })
    by_value = {g["value"]: g for g in out["groups"]}
    assert by_value["A"]["count"] == 3 and by_value["A"]["sum"] == "8"
    assert by_value["C"]["sum"] == "7"


def test_aggregate_avg_price_handles_comma_decimal_and_null():
    out = apply_exploration(RECORDS, {
        "filter": [{"field": "customer", "op": "eq", "value": "A"}],
        "group_by": "customer",
        "aggregate": {"op": "avg", "field": "price"},
    })
    g = out["groups"][0]
    assert g["nulls"] == 1  # price None comptée explicitement
    assert g["avg"] == "65.2500"  # (120.50 + 10.00) / 2 — Decimal, virgule FR gérée


def test_compare_fields_flags_mismatches():
    out = apply_exploration(RECORDS, {
        "compare": {"left_field": "quantity", "right_field": "quantity", "op": "eq"},
    })
    assert out["comparison"]["matches"] == 5 and out["comparison"]["mismatches"] == []


def test_unknown_field_rejected():
    out = apply_exploration(RECORDS, {"filter": [{"field": "inconnu", "op": "eq", "value": "x"}]})
    assert out["unknown_fields"] == ["inconnu"]


def test_projection_and_bounded_input():
    many = [{"id": i, "v": i % 3} for i in range(6000)]
    out = apply_exploration(many, {"fields": ["id"], "limit": 3})
    assert out["input_truncated"] is True
    assert out["total_input_rows"] == 6000 and out["explored_rows"] == 5000
    assert out["table"][0].keys() == {"id"}


async def test_data_explore_tool_end_to_end(client):
    """Intégration : tool harness data_explore sur une evidence record_set —
    calculs déterministes, evidence `exploration` créée, scope mission respecté."""
    import json

    from app.main import app

    src = (await upload_csv_file(client))["source"]  # la route renvoie {source, evidence_id}
    mission = (await client.post("/api/missions", json={
        "title": "t", "objective": "o", "source_ids": [src["id"]], "control_ids": ["DATA-01"],
    })).json()["mission"]

    records = [
        {"order_id": "SO-1", "quantity": 5, "expected_quantity": 5},
        {"order_id": "SO-2", "quantity": 3, "expected_quantity": 3},
        {"order_id": "SO-3", "quantity": 2, "expected_quantity": 7},  # incohérent
    ]
    ev = app.state.store.save(
        mission_id=mission["id"], run_id=None, source_id=src["id"],
        type_="record_set", title="Jeu de test",
        payload={"records": records}, provenance={"tool": "test"},
        record_count=3, evidence_id="ev_explore_test",
    )
    await app.state.repo.create_evidence_meta(ev)

    from app.harness.contracts import ToolContext

    ctx = ToolContext(
        mission=(await app.state.repo.get_mission(mission["id"])), run_id="run_test",
        source=None, secrets={}, store=app.state.store, repo=app.state.repo,
        connectors=app.state.connectors, extra={"tool_input_models": app.state.input_models},
    )
    result = await app.state.executor.execute("data_explore", {
        "evidence_id": "ev_explore_test",
        "spec": {"compare": {"left_field": "quantity", "right_field": "expected_quantity", "op": "eq"},
                 "sort": [{"field": "quantity", "dir": "desc"}], "limit": 10},
    }, ctx)
    assert result.status == "success", result.error
    preview = result.preview
    assert preview["mission_id"] == mission["id"]
    mism = preview["comparison"]["mismatches"]
    assert [(m["row_index"], m["left"], m["right"]) for m in mism] == [(2, "2", "7")]  # SO-3 détecté
    assert result.evidence_ids, "une evidence exploration doit être créée"
    saved = await app.state.repo.get_evidence_meta(result.evidence_ids[0], mission["id"])
    assert saved.type == "exploration" and saved.provenance["tool"] == "data_explore"
    json.dumps(saved.summary)  # sérialisable pour le LLM


async def upload_csv_file(client):
    from .conftest import upload_csv

    return await upload_csv(client, "orders.csv", (
        "order_id,order_date,quantity\nSO-1,2026-01-01,2\n"
    ))
