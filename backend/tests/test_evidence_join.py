"""Tests evidence_join et connecteur fichiers (CSV/XLSX/JSON) — outils locales docs/05/09."""

from __future__ import annotations

import json

import pytest

from app.audit.rules import get_rule_set, evaluate_rule_set
from app.connectors.base import ConnectorFactory
from app.connectors.files.connector import FileConnector
from app.harness.contracts import ToolContext
from app.models import AuditMission
from app.evidence.store import EvidenceStore
from app.persistence.database import Database
from app.persistence.repository import Repository
from app.tools.all_tools import tool_data_validate, tool_evidence_join


@pytest.mark.asyncio
async def test_file_connector_formats(tmp_path):
    import pandas as pd

    # CSV
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_id,quantity\nA,1\nB,2\n", encoding="utf-8")
    fc = FileConnector({"path": str(csv_path)})
    df = await fc.load_dataframe()
    assert len(df) == 2

    # JSON (liste d'objets)
    json_path = tmp_path / "orders.json"
    json_path.write_text(json.dumps([{"order_id": "A", "quantity": 1}]), encoding="utf-8")
    df_json = await FileConnector({"path": str(json_path)}).load_dataframe()
    assert len(df_json) == 1

    # XLSX
    xlsx_path = tmp_path / "orders.xlsx"
    pd.DataFrame([{"order_id": "A", "quantity": 3}]).to_excel(xlsx_path, index=False)
    df_xlsx = await FileConnector({"path": str(xlsx_path)}).load_dataframe()
    assert len(df_xlsx) == 1

    caps = await FileConnector({"path": str(csv_path)}).discover()
    assert caps["rows"] == 2 and caps["columns"][0]["name"] == "order_id"


@pytest.mark.asyncio
async def test_evidence_join_documents_unmatched(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    repo = Repository(db)
    store = EvidenceStore(tmp_path / "ev")

    mission = AuditMission(id="mission_j", title="t", objective="t", source_ids=["src_a", "src_b"])
    await repo.create_mission(mission)

    ev_left = store.save(
        mission_id=mission.id, run_id="run_1", source_id="src_a", type_="record_set",
        title="orders", payload={"records": [
            {"order_id": "SO-1", "quantity": 5},
            {"order_id": "SO-2", "quantity": 3},
            {"order_id": "SO-3", "quantity": 1},
        ]}, provenance={"tool": "test"}, evidence_id="ev_left0001",
    )
    ev_right = store.save(
        mission_id=mission.id, run_id="run_1", source_id="src_b", type_="record_set",
        title="invoices", payload={"records": [
            {"order_id": "SO-1", "amount": 100},
            {"order_id": "SO-9", "amount": 50},  # facture détachée
        ]}, provenance={"tool": "test"}, evidence_id="ev_right01",
    )
    await repo.create_evidence_meta(ev_left)
    await repo.create_evidence_meta(ev_right)

    connectors = ConnectorFactory(repo, None)
    ctx = ToolContext(
        mission=mission, run_id="run_1", source=None, secrets={},
        store=store, repo=repo, connectors=connectors, extra={},
    )
    result = await tool_evidence_join(ctx, {
        "evidence_ids": [ev_left.id, ev_right.id], "left_key": "order_id", "right_key": "order_id",
        "label": "commandes ⋈ factures",
    })
    assert result.status == "success"
    preview = result.preview
    assert preview["matched"] == 1
    assert preview["unmatched_left_count"] == 2
    assert preview["unmatched_right_count"] == 1
    join_ev = await repo.get_evidence_meta(result.evidence_ids[0], mission.id)
    assert join_ev is not None and join_ev.type == "join"
    await db.close()


@pytest.mark.asyncio
async def test_data_validate_via_tool(tmp_path):
    db = Database(str(tmp_path / "t2.db"))
    await db.connect()
    repo = Repository(db)
    store = EvidenceStore(tmp_path / "ev2")
    mission = AuditMission(id="mission_v", title="t", objective="t", source_ids=["src_f"])
    await repo.create_mission(mission)

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_id,order_date,customer_id,product,quantity,unit_price,currency,status\n"
        "SO-1,2026-09-01,C1,P1,-5,10,MAD,sale\n",  # quantité négative
        encoding="utf-8",
    )
    ev_file = store.save(
        mission_id=mission.id, run_id=None, source_id="src_f", type_="raw_file",
        title="fichier", payload={"path": str(csv_path)}, provenance={"origin": "upload"},
        evidence_id="ev_file0001",
    )
    await repo.create_evidence_meta(ev_file)

    connectors = ConnectorFactory(repo, None)
    ctx = ToolContext(
        mission=mission, run_id="run_2", source=None, secrets={},
        store=store, repo=repo, connectors=connectors,
        extra={},
    )
    result = await tool_data_validate(ctx, {"evidence_id": ev_file.id, "rule_set_id": "rs_orders_v1"})
    assert result.status == "success"
    assert result.record_count == 1  # une violation (quantity négative)
    assert result.preview["valid"] is False
    await db.close()
