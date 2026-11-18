"""Phase 1/10 — Smart System Discovery : intelligence structurée des sources.

- build_source_intelligence : capacités réelles, domaines génériques, opérations
  supportées/unsupported, permissions manquantes (approved-tests non accordés),
  prérequis — sans rien inventer.
- tool chat inspect_source : découverte lecture seule via le connecteur, état error
  si la découverte échoue, périmètre mission pour les permissions manquantes.
"""

from __future__ import annotations

from app.audit.discovery import build_source_intelligence
from app.harness.registry import ToolRegistry
from app.models import AuditMission, SourceConnection, SourceType


def _registry() -> ToolRegistry:
    from app.tools import register_all_tools

    registry = ToolRegistry()
    register_all_tools(registry)
    return registry


def test_file_source_intelligence_domains_and_ops():
    src = SourceConnection(id="src_f", name="orders.csv", type=SourceType.file)
    caps = {
        "connector": "file", "rows": 4, "truncated": False,
        "columns": [{"name": "order_id"}, {"name": "quantity"}],
    }
    intel = build_source_intelligence(src, caps, _registry())
    assert intel["connection_state"] == "connected"
    assert intel["domains"] == ["order_id", "quantity"]
    assert intel["capabilities"]["rows"] == 4
    ops = [o["tool"] for o in intel["supported_operations"]]
    assert "data_profile" in ops and "data_validate" in ops
    assert all(not t.startswith("odoo_read_") for t in ops)  # lectures source-scopées odoo exclues
    assert any("API" in u or "api" in u.lower() for u in intel["unsupported_operations"])
    assert intel["prerequisites"] == []


def test_api_source_missing_permissions_when_not_approved():
    src = SourceConnection(id="src_a", name="ERP API", type=SourceType.api, config={
        "endpoints": [{"id": "orders"}, {"id": "invoices"}],
    })
    mission = AuditMission(id="m1", title="t", objective="o", source_ids=["src_a"])
    intel = build_source_intelligence(src, {"endpoints": [{"id": "orders"}]}, _registry(), mission)
    assert intel["domains"] == ["orders"]
    missing = {m["tool"] for m in intel["missing_permissions"]}
    assert missing == {"api_inspect_contract"}  # lecture = read => supportée
    supported = {o["tool"] for o in intel["supported_operations"]}
    assert "api_fetch_records" in supported
    assert all(m["reason"] for m in intel["missing_permissions"])


def test_missing_permissions_disappear_once_approved():
    src = SourceConnection(id="src_a", name="ERP API", type=SourceType.api)
    mission = AuditMission(
        id="m1", title="t", objective="o", source_ids=["src_a"],
        approved_plan={"approved_actions": [{"tool": "api_fetch_records", "source_id": "src_a"}]},
    )
    intel = build_source_intelligence(src, {"endpoints": [{"id": "orders"}]}, _registry(), mission)
    missing = {m["tool"] for m in intel["missing_permissions"]}
    assert "api_fetch_records" not in missing
    assert "api_inspect_contract" in missing  # seule l'action approuvée est accordée


def test_odoo_unavailable_models_listed_as_unsupported():
    src = SourceConnection(id="src_o", name="Odoo", type=SourceType.odoo)
    caps = {"models": {
        "sale.order": {"available": True, "label": "Commandes"},
        "account.move": {"available": False, "reason": "module absent"},
    }}
    intel = build_source_intelligence(src, caps, _registry())
    assert "Commandes" in intel["domains"]
    assert intel["capabilities"]["models_available"] == ["sale.order"]
    assert any("account.move" in u for u in intel["unsupported_operations"])
    assert any("lecture seule" in u for u in intel["unsupported_operations"])


def test_discover_error_yields_error_state_and_prerequisite():
    src = SourceConnection(id="src_o", name="Odoo", type=SourceType.odoo)
    intel = build_source_intelligence(src, {"discover_error": "ConnectionError: refused"}, _registry())
    assert intel["connection_state"] == "error"
    assert "refused" in intel["discover_error"]
    assert any("connexion" in p.lower() for p in intel["prerequisites"])


async def test_chat_tool_inspect_source(client):
    from app.agent.chat import ChatService
    from app.agent.providers.base import ProviderToolCall
    from app.models import ConversationThread

    from .test_conversations import _D, _thread_model, create_thread, upload_csv

    await upload_csv(client, "orders.csv", _faulty := (
        "order_id,order_date,quantity\nSO-1,2026-01-01,2\n"
    ))
    thread = await create_thread(client)
    t = await _thread_model(client, thread["id"])
    service = ChatService()
    out = await service._execute_chat_tool(_D(client), t, ProviderToolCall(
        id="tc1", name="inspect_source", arguments={"source_id": "src_zzz"},
    ), set())
    assert out["status"] == "error"

    src = (await client.get("/api/sources")).json()["sources"][0]
    out2 = await service._execute_chat_tool(_D(client), t, ProviderToolCall(
        id="tc2", name="inspect_source", arguments={"source_id": src["id"]},
    ), set())
    assert out2["connection_state"] == "connected"
    assert "order_id" in out2["domains"]
    ops = [o["tool"] for o in out2["supported_operations"]]
    assert "data_profile" in ops
