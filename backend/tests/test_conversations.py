"""Tests ADR-16 — conversations chat-first : branches, compaction, annulation,
erreurs provider, périmètre, rétention. Scénarios mission §9 (backend-level)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.main import app

from app.agent.providers.base import ProviderToolCall

from .conftest import upload_csv


async def create_thread(client: httpx.AsyncClient, title: str = "Test conversation") -> dict:
    resp = await client.post("/api/conversations", json={"title": title})
    assert resp.status_code == 200, resp.text
    return resp.json()["thread"]


async def stream_turn(client: httpx.AsyncClient, thread_id: str, body: dict) -> list[dict]:
    events: list[dict] = []
    async with client.stream("POST", f"/api/conversations/{thread_id}/stream", json=body) as resp:
        assert resp.status_code == 200, await resp.aread()
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


async def wait_run_terminal(client: httpx.AsyncClient, run_id: str, timeout: float = 15.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/api/runs/{run_id}")
        status = r.json()["run"]["status"]
        if status in ("completed", "review_required", "partial", "failed", "paused", "cancelled"):
            return r.json()["run"]
        await asyncio.sleep(0.1)
    raise TimeoutError("run non terminé")


async def test_thread_crud_and_text_stream(client):
    thread = await create_thread(client)
    assert thread["status"] == "active"

    events = await stream_turn(client, thread["id"], {"content": "bonjour", "mode": "new"})
    types = [e["type"] for e in events]
    assert types[0] == "message" and types[1] == "head"
    assert "message" in types and events[-1]["type"] == "done"
    assistant_msgs = [e["message"] for e in events if e["type"] == "message" and e["message"]["role"] == "assistant"]
    assert assistant_msgs and "bonjour" in assistant_msgs[0]["parts"][0]["text"]

    resp = await client.get(f"/api/conversations/{thread['id']}")
    data = resp.json()
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
    assert data["thread"]["head_message_id"] == data["messages"][-1]["id"]

    listing = (await client.get("/api/conversations")).json()["threads"]
    assert any(t["id"] == thread["id"] for t in listing)


async def test_chat_audit_creates_mission_run_and_followups(client, tmp_path):
    src = await upload_csv(client, "orders.csv", _faulty())
    thread = await create_thread(client)
    events = await stream_turn(client, thread["id"], {
        "content": "audite cette source et investigue les incohérences", "mode": "new",
    })
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    tool_results = [e for e in events if e["type"] == "tool_result"]
    # séquence dépendante réelle : list_sources → create_audit (ids issus du résultat)
    assert [t["tool"] for t in tool_calls] == ["list_sources", "create_audit"]
    create_res = next(r for r in tool_results if r["tool"] == "create_audit")
    assert create_res["status"] == "complete"
    mission_id, run_id = create_res["result"]["mission_id"], create_res["result"]["run_id"]
    assert create_res["result"]["approved_active_tests"] is False

    run = await wait_run_terminal(client, run_id)
    assert run["status"] in ("completed", "review_required")

    thread_data = (await client.get(f"/api/conversations/{thread['id']}")).json()
    assert mission_id in thread_data["thread"]["mission_ids"]
    assert run_id in thread_data["thread"]["run_ids"]

    # suivi : statut du run + findings via tools chat (dernier message = create_audit → texte final)
    events2 = await stream_turn(client, thread["id"], {"content": "quel est le statut du run ?", "mode": "new"})
    calls2 = [e["tool"] for e in events2 if e["type"] == "tool_call"]
    assert "get_run_status" in calls2
    events3 = await stream_turn(client, thread["id"], {"content": "montre-moi les constats", "mode": "new"})
    calls3 = [e["tool"] for e in events3 if e["type"] == "tool_call"]
    assert "get_findings" in calls3
    findings_res = next(r for r in events3 if r["type"] == "tool_result" and r["tool"] == "get_findings")
    assert findings_res["result"]["mission_id"] == mission_id


def _faulty() -> str:
    return (
        "order_id,order_date,customer_id,product,quantity,unit_price,currency,status\n"
        "SO-1000,2026-09-01,CUST-201,P-001,5,120.50,MAD,sale\n"
        "SO-1001,2026-09-02,CUST-202,P-002,-3,80.00,MAD,done\n"
        "SO-1002,2026-13-45,CUST-203,P-003,2,45.00,EUR,sent\n"
        "SO-1001,2026-09-05,CUST-204,P-004,7,,EUR,draft\n"
    )


async def test_edit_creates_branch_and_history_preserved(client):
    thread = await create_thread(client)
    e1 = await stream_turn(client, thread["id"], {"content": "audit toutes les transactions", "mode": "new"})
    user1 = next(e["message"] for e in e1 if e["type"] == "message" and e["message"]["role"] == "user")
    asst1 = next(e["message"] for e in e1 if e["type"] == "message" and e["message"]["role"] == "assistant")

    e2 = await stream_turn(client, thread["id"], {
        "content": "audit uniquement octobre", "mode": "edit", "target_message_id": user1["id"],
    })
    user2 = next(e["message"] for e in e2 if e["type"] == "message" and e["message"]["role"] == "user")
    asst2 = next(e["message"] for e in e2 if e["type"] == "message" and e["message"]["role"] == "assistant")
    assert user2["parent_id"] is None  # même parent que l'original → branche sœur
    assert asst2["parent_id"] == user2["id"]

    data = (await client.get(f"/api/conversations/{thread['id']}")).json()
    # branche active = la nouvelle ; l'historique exécuté reste en base
    assert [m["id"] for m in data["messages"]] == [user2["id"], asst2["id"]]
    branches = (await client.get(f"/api/conversations/{thread['id']}/branches")).json()
    ids = {n["id"] for n in branches["nodes"]}
    assert {user1["id"], asst1["id"]}.issubset(ids)
    assert branches["head_message_id"] == asst2["id"]

    # retour sur l'ancienne branche : pointeur seul, aucune réécriture
    r = await client.post(f"/api/conversations/{thread['id']}/head", json={"message_id": asst1["id"]})
    assert r.status_code == 200
    data = (await client.get(f"/api/conversations/{thread['id']}")).json()
    assert [m["id"] for m in data["messages"]] == [user1["id"], asst1["id"]]


async def test_regenerate_creates_sibling(client):
    thread = await create_thread(client)
    e1 = await stream_turn(client, thread["id"], {"content": "explique le périmètre", "mode": "new"})
    asst1 = next(e["message"] for e in e1 if e["type"] == "message" and e["message"]["role"] == "assistant")

    e2 = await stream_turn(client, thread["id"], {
        "mode": "regenerate", "target_message_id": asst1["id"],
    })
    asst2 = next(e["message"] for e in e2 if e["type"] == "message" and e["message"]["role"] == "assistant")
    assert asst2["id"] != asst1["id"]
    assert asst2["parent_id"] == asst1["parent_id"]  # frères, l'original reste navigable

    data = (await client.get(f"/api/conversations/{thread['id']}")).json()
    assert data["thread"]["head_message_id"] == asst2["id"]
    assert len(data["messages"]) == 2  # user + assistant régénéré


async def test_archive_and_soft_delete_retain_evidence(client):
    src = await upload_csv(client, "orders.csv", _faulty())
    thread = await create_thread(client)
    events = await stream_turn(client, thread["id"], {"content": "audite cette source", "mode": "new"})
    run_id = next(r for r in events if r["type"] == "tool_result" and r["tool"] == "create_audit")["result"]["run_id"]
    await wait_run_terminal(client, run_id)
    evidence_before = (await client.get(f"/api/runs/{run_id}")).json()

    r = await client.post(f"/api/conversations/{thread['id']}/archive")
    assert r.json()["thread"]["status"] == "archived"
    listing = (await client.get("/api/conversations")).json()["threads"]
    assert all(t["id"] != thread["id"] or t["status"] == "archived" for t in listing)

    r = await client.delete(f"/api/conversations/{thread['id']}")
    assert r.status_code == 200
    listing = (await client.get("/api/conversations")).json()["threads"]
    assert all(t["id"] != thread["id"] for t in listing)  # masquée

    # rétention : run, mission et preuves immuables toujours en base
    run = await wait_run_terminal(client, run_id)
    assert run["status"] in ("completed", "review_required")
    events_resp = await client.get(f"/api/runs/{run_id}/evidence")
    assert events_resp.status_code == 200
    restore = await client.post(f"/api/conversations/{thread['id']}/restore")
    assert restore.json()["thread"]["status"] == "active"


async def test_compaction_triggers_and_search_recovers(client):
    thread = await create_thread(client)
    long_text = "incident " + "x" * 3800 + " REPERE-COMPACT-42"
    for i in range(8):
        await stream_turn(client, thread["id"], {"content": f"{long_text} tour {i}", "mode": "new"})
    data = (await client.get(f"/api/conversations/{thread['id']}")).json()
    assert data["thread"]["context_summary"], "la compaction doit produire un résumé"
    assert data["thread"]["compacted_message_count"] > 0
    assert data["thread"]["summary_upto_message_id"]

    # couche 1 intacte : TOUS les messages restent en base (branches endpoint = arbre complet)
    branches = (await client.get(f"/api/conversations/{thread['id']}/branches")).json()
    assert len(branches["nodes"]) >= 16

    # récupération d'une information compactée (hors contexte actif)
    r = await client.get(f"/api/conversations/{thread['id']}/search", params={"q": "REPERE-COMPACT-42"})
    results = r.json()["results"]
    assert results, "la recherche doit retrouver le contenu compacté"
    assert any(res["snippet"] for res in results)


async def test_cancel_persists_partial_and_thread_usable(client):
    thread = await create_thread(client)
    # annulation demandée AVANT le tour : la boucle s'arrête au premier contrôle
    app.state.chat_controls[thread["id"]] = "cancel"
    events = await stream_turn(client, thread["id"], {"content": "bonjour", "mode": "new"})
    app.state.chat_controls.pop(thread["id"], None)
    done = events[-1]
    assert done["type"] == "done" and done["status"] == "incomplete"
    asst = next(e["message"] for e in events if e["type"] == "message" and e["message"]["role"] == "assistant")
    assert asst["status"] == "incomplete"

    # la conversation reste utilisable après annulation
    events2 = await stream_turn(client, thread["id"], {"content": "reprends", "mode": "new"})
    assert events2[-1]["status"] == "complete"


async def test_provider_error_resilience(client):
    thread = await create_thread(client)
    # provider injoignable : erreur honnête, conversation intacte
    app.state.llm_runtime.update({
        "provider": "compatible", "model": "test-model", "api_key": "k",
        "base_url": "http://127.0.0.1:9/v1",  # port discard : connexion refusée
    })
    events = await stream_turn(client, thread["id"], {"content": "bonjour", "mode": "new"})
    app.state.llm_runtime.clear()
    assert events[-1]["type"] == "done" and events[-1]["status"] == "error"
    err_event = next(e for e in events if e["type"] == "error")
    assert err_event["message"]
    asst = next(e["message"] for e in events if e["type"] == "message" and e["message"]["role"] == "assistant")
    assert asst["status"] == "error" and "Erreur provider" in asst["parts"][-1]["text"]

    # provider rétabli : la conversation reste utilisable (état non corrompu)
    events2 = await stream_turn(client, thread["id"], {"content": "ça va ?", "mode": "new"})
    assert events2[-1]["status"] == "complete"
    data = (await client.get(f"/api/conversations/{thread['id']}")).json()
    assert len(data["messages"]) == 4  # user/assistant erreur + user/assistant ok


async def test_chat_scope_enforcement(client):
    """get_evidence/get_findings refusent tout ce qui est hors périmètre du thread."""
    from app.agent.chat import ChatService

    src = await upload_csv(client, "orders.csv", _faulty())
    thread = await create_thread(client)
    events = await stream_turn(client, thread["id"], {"content": "audite cette source", "mode": "new"})
    create = next(r for r in events if r["type"] == "tool_result" and r["tool"] == "create_audit")
    mission_id = create["result"]["mission_id"]
    await wait_run_terminal(client, create["result"]["run_id"])
    evid = (await client.get(f"/api/missions/{mission_id}/evidence")).json()
    assert evid.get("evidence"), "le run doit avoir produit des preuves"
    ev_id = evid["evidence"][0]["id"]

    service = ChatService()
    # thread SANS mission liée : toute demande de preuve/findings est refusée
    other = await create_thread(client, "autre conversation")
    t_other = await _thread_model(client, other["id"])
    out = await service._execute_chat_tool(
        _D(client), t_other, ProviderToolCall(id="tc1", name="get_evidence", arguments={"evidence_id": ev_id}), set(),
    )
    assert out["status"] == "error" and "périmètre" in out["error"]
    out2 = await service._execute_chat_tool(
        _D(client), t_other, ProviderToolCall(id="tc2", name="get_findings", arguments={"mission_id": mission_id}), set(),
    )
    assert out2["status"] == "error"
    # tool chat inconnue → refus explicite (jamais d'exécution hors catalogue)
    out3 = await service._execute_chat_tool(
        _D(client), t_other, ProviderToolCall(id="tc3", name="odoo_read_orders", arguments={}), set(),
    )
    assert out3["status"] == "error" and "inconnue" in out3["error"]


async def _thread_model(client: httpx.AsyncClient, thread_id: str):
    from app.models import ConversationThread
    data = (await client.get(f"/api/conversations/{thread_id}")).json()
    return ConversationThread.model_validate(data["thread"])


def _D(client: httpx.AsyncClient):
    """AppDeps construit manuellement pour tests unitaires du service chat."""
    from app.api.deps import AppDeps

    d = AppDeps.__new__(AppDeps)
    d.repo = app.state.repo
    d.store = app.state.store
    d.secrets = app.state.secrets
    d.executor = app.state.executor
    d.connectors = app.state.connectors
    d.bus = app.state.bus
    d.orchestrator = app.state.orchestrator
    d.input_models = app.state.input_models
    d.llm_runtime = app.state.llm_runtime
    d.run_controls = app.state.run_controls
    d.chat_controls = app.state.chat_controls
    d.run_semaphore = app.state.run_semaphore
    d.tasks = app.state.background_tasks
    d.settings = app.state.settings
    return d

async def test_thread_rename_and_pin_persist(client):
    thread = await create_thread(client, "Original")
    thread_id = thread["id"]
    response = await client.patch(f"/api/conversations/{thread_id}", json={"title": "  Audit ERP  ", "pinned": True})
    assert response.status_code == 200
    assert response.json()["thread"]["title"] == "Audit ERP"
    assert response.json()["thread"]["pinned"] is True
    listed = (await client.get("/api/conversations")).json()["threads"]
    assert next(t for t in listed if t["id"] == thread_id)["pinned"] is True
    assert (await client.patch(f"/api/conversations/{thread_id}", json={"title": "  "})).status_code == 422
    assert (await client.patch(f"/api/conversations/{thread_id}", json={"pinned": False})).json()["thread"]["pinned"] is False
    await client.delete(f"/api/conversations/{thread_id}")
    assert (await client.patch(f"/api/conversations/{thread_id}", json={"title": "No"})).status_code == 410

async def test_default_conversation_gets_first_message_title(client):
    thread = (await client.post('/api/conversations', json={})).json()['thread']
    await stream_turn(client, thread['id'], {'content': 'Verifier les ventes\nPeriode courante'})
    listing = (await client.get('/api/conversations')).json()['threads']
    assert next(item for item in listing if item['id'] == thread['id'])['title'] == 'Verifier les ventes'
    await stream_turn(client, thread['id'], {'content': 'Une autre question'})
    assert (await client.get(f"/api/conversations/{thread['id']}")).json()['thread']['title'] == 'Verifier les ventes'

async def test_chat_emits_provider_deltas_and_persists_final(client, monkeypatch):
    from app.agent.providers.base import LLMProvider, LLMResponse
    class StreamingProvider(LLMProvider):
        provider_id = 'fake-stream'
        model_id = 'fake-model'
        async def chat(self, system, messages, tools=None):
            raise AssertionError('streaming attendu')
        async def stream_chat(self, system, messages, tools=None):
            yield 'Bonjour'
            yield ' en direct'
            yield LLMResponse(content='Bonjour en direct')
    monkeypatch.setattr('app.agent.chat.build_provider', lambda *args, **kwargs: StreamingProvider())
    thread = await create_thread(client)
    events = await stream_turn(client, thread['id'], {'content': 'bonjour'})
    assert [e['text'] for e in events if e['type'] == 'text_delta'] == ['Bonjour', ' en direct']
    assert next(i for i, e in enumerate(events) if e['type'] == 'assistant_start') < next(i for i, e in enumerate(events) if e['type'] == 'text_delta')
    detail = (await client.get(f"/api/conversations/{thread['id']}")).json()
    assert detail['messages'][-1]['parts'] == [{'type': 'text', 'text': 'Bonjour en direct'}]

async def test_openai_stream_reassembles_tool_arguments():
    from types import SimpleNamespace as S
    from app.agent.providers.openai_compatible import OpenAICompatibleProvider
    from app.agent.providers.base import LLMResponse
    provider = OpenAICompatibleProvider('compatible', 'test', 'test', 'http://localhost:8009')
    class FakeStream:
        closed = False
        def __aiter__(self):
            async def generate():
                for chunk in [
                    S(choices=[S(delta=S(content='Avant ', tool_calls=None))]),
                    S(choices=[S(delta=S(content=None, tool_calls=[S(index=0, id='call_1', function=S(name='list_', arguments='{"x":'))]))]),
                    S(choices=[S(delta=S(content=None, tool_calls=[S(index=0, id=None, function=S(name='sources', arguments='1}'))]))]),
                ]:
                    yield chunk
            return generate()
        async def close(self): self.closed = True
    fake = FakeStream()
    async def create(**kwargs):
        assert kwargs['stream'] is True
        return fake
    provider._client.chat.completions.create = create
    events = [event async for event in provider.stream_chat('system', [], [])]
    assert events[0] == 'Avant '
    assert isinstance(events[-1], LLMResponse)
    assert events[-1].tool_calls[0].name == 'list_sources'
    assert events[-1].tool_calls[0].arguments == {'x': 1}
    assert fake.closed
    await provider.close()
