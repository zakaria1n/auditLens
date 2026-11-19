"""Phase 2A/4 — JSON first-class : parsing multi-structures, aplatissement pointé,
bornes, discovery de structure, integration data_explore / corrélation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.connectors.files.connector import FileConnector
from app.harness.contracts import ToolContext
from app.connectors.files.json_parser import load_json_file, load_json_records


def _write(tmp_path: Path, content: str, name="data.json") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_flat_array_records(tmp_path):
    p = _write(tmp_path, json.dumps([
        {"id": 1, "amount": 10}, {"id": 2, "amount": 20},
    ]))
    records, structure = load_json_records(p)
    assert len(records) == 2 and records[0]["id"] == 1
    assert structure["root"] == "array"
    assert "id" in structure["candidate_identifiers"]


def test_object_with_array_field(tmp_path):
    p = _write(tmp_path, json.dumps({
        "meta": "rapport 2026", "orders": [{"id": "A"}, {"id": "B"}],
    }))
    records, structure = load_json_records(p)
    assert structure["root"] == "object_with_array"
    assert structure["root_array_field"] == "orders"
    assert structure["sibling_fields"] == ["meta"]
    assert records[0]["id"] == "A"


def test_nested_objects_flattened_dotted_paths(tmp_path):
    p = _write(tmp_path, json.dumps([{
        "order": {"id": "SO-1", "customer": {"name": "A", "contact": {"email": "a@b.co"}}},
        "total": 100,
    }]))
    records, structure = load_json_records(p)
    assert records[0]["order.id"] == "SO-1"
    assert records[0]["order.customer.contact.email"] == "a@b.co"
    paths = {f["path"] for f in structure["fields"]}
    assert "order.customer.name" in paths


def test_nested_array_serialized_as_cell(tmp_path):
    p = _write(tmp_path, json.dumps([{"id": "SO-1", "lines": [{"qty": 1}, {"qty": 2}]}]))
    records, structure = load_json_records(p)
    cell = records[0]["lines"]
    assert isinstance(cell, str) and json.loads(cell) == [{"qty": 1}, {"qty": 2}]
    assert "lines" in structure["nested_arrays"]


def test_mixed_types_and_missing_fields(tmp_path):
    p = _write(tmp_path, json.dumps([
        {"id": "A", "amount": 10}, {"id": "B", "amount": "20"}, {"id": "C"},
    ]))
    records, structure = load_json_records(p)
    amount = next(f for f in structure["fields"] if f["path"] == "amount")
    assert set(amount["types"]) >= {"number"}
    assert amount["missing"] == 1  # C sans amount


def test_primitive_root(tmp_path):
    p = _write(tmp_path, "42")
    records, structure = load_json_records(p)
    assert records == [{"value": 42}] and structure["root"] == "primitive"


def test_jsonl_supported(tmp_path):
    p = _write(tmp_path, '{"id": 1}\n{"id": 2}\n', name="data.jsonl")
    records, structure = load_json_records(p)
    assert len(records) == 2 and structure["kind"] == "jsonl"


def test_malformed_json_clear_error(tmp_path):
    p = _write(tmp_path, "{not valid")
    with pytest.raises(ValueError, match="malformé"):
        load_json_file(p)


def test_size_limit(tmp_path):
    p = _write(tmp_path, json.dumps([{"x": "y" * 100}]))
    import app.connectors.files.json_parser as jp

    original = jp.MAX_BYTES
    jp.MAX_BYTES = 10
    try:
        with pytest.raises(ValueError, match="trop grand"):
            load_json_file(p)
    finally:
        jp.MAX_BYTES = original


def test_connector_json_end_to_end(tmp_path):
    p = _write(tmp_path, json.dumps([
        {"order": {"id": "SO-1"}, "amount": 100},
        {"order": {"id": "SO-2"}, "amount": 200},
    ]))
    fc = FileConnector({"path": str(p), "original_name": "data.json"})
    df_records = fc._load_sync()
    assert list(df_records.columns) == ["order.id", "amount"]


async def test_connector_load_records_bounded(tmp_path):
    p = _write(tmp_path, json.dumps([{"id": i} for i in range(50)]))
    fc = FileConnector({"path": str(p)})
    records = await fc.load_records(limit=10)
    assert len(records) == 10


async def test_data_explore_on_json_raw_file(client, tmp_path):
    """Intégration : upload JSON via la route officielle => data_explore sur chemins pointés."""
    p = _write(tmp_path, json.dumps([
        {"order": {"id": "SO-1"}, "quantity": 5, "expected": 5},
        {"order": {"id": "SO-2"}, "quantity": 2, "expected": 9},  # incohérent
    ]))
    resp = await client.post(
        "/api/sources/file", params={"name": "orders.json", "rule_set_id": "rs_orders_v1"},
        files={"file": ("orders.json", p.read_bytes(), "application/json")},
    )
    assert resp.status_code == 200, resp.text

    mission = (await client.post("/api/missions", json={
        "title": "t", "objective": "o", "source_ids": [resp.json()["source"]["id"]],
        "control_ids": ["DATA-01"],
    })).json()["mission"]

    from app.api.routes.missions import _link_import_evidence
    from app.models import AuditMission

    state_mission = await client._transport.app.state.repo.get_mission(mission["id"])
    await _link_import_evidence(client._transport.app.state, AuditMission.model_validate(state_mission))
    evidence_meta = (await client.get(f"/api/missions/{mission['id']}/evidence")).json()["evidence"]
    evidence_id = next(e["id"] for e in evidence_meta if e["type"] == "raw_file")
    ctx = ToolContext(
        mission=state_mission, run_id="r_json", source=None, secrets={},
        store=client._transport.app.state.store, repo=client._transport.app.state.repo,
        connectors=client._transport.app.state.connectors,
        extra={"tool_input_models": client._transport.app.state.input_models},
    )
    result = await client._transport.app.state.executor.execute(
        "data_explore",
        {"evidence_id": evidence_id,
         "spec": {"compare": {"left_field": "quantity", "right_field": "expected", "op": "eq"}}},
        ctx,
    )
    assert result.status == "success", result.error
    assert result.preview["comparison"]["mismatches"], "SO-2 incohérence détectée"
    assert result.preview["table"][0]["order.id"] == "SO-1"
