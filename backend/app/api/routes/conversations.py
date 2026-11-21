"""Conversations chat-first (ADR-16) : threads, branches, streaming SSE.

Le backend reste la source de vérité : le frontend (assistant-ui external store)
n'invente aucun message ; tout contenu affiché provient de chat_messages.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from ...agent.chat import ChatService
from ...core.ids import new_id
from ..deps import deps
from ...models import ConversationStatus, ConversationThread, utcnow

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ThreadCreate(BaseModel):
    title: str | None = None


class ThreadUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    pinned: bool | None = None

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Le titre ne peut pas être vide")
        return value


class HeadBody(BaseModel):
    message_id: str


class StreamBody(BaseModel):
    content: str | None = None
    mode: str = "new"  # new | edit | regenerate
    target_message_id: str | None = None


class PresentationRepairBody(BaseModel):
    specification: dict
    issue: dict = Field(default_factory=dict)


@router.post("/{thread_id}/repair-presentation")
async def repair_presentation_for_thread(thread_id: str, body: PresentationRepairBody, request: Request):
    import hashlib
    from collections import OrderedDict
    from ...agent.presentation_repair import repair_presentation
    from ...agent.providers import build_provider, resolve_llm_config

    thread = await _get_thread_or_404(request, thread_id)
    if thread.status == ConversationStatus.deleted:
        raise HTTPException(410, "conversation supprimée")
    encoded = json.dumps(body.specification, ensure_ascii=False, sort_keys=True)
    if len(encoded) > 24000:
        raise HTTPException(422, "Présentation trop volumineuse")
    attempts = getattr(request.app.state, "presentation_repair_attempts", None)
    if attempts is None:
        attempts = request.app.state.presentation_repair_attempts = OrderedDict()
    attempt_id = (thread_id, hashlib.sha256(encoded.encode('utf-8')).hexdigest())
    if attempt_id in attempts:
        raise HTTPException(409, "Une tentative a déjà été effectuée pour cette présentation.")
    attempts[attempt_id] = None
    if len(attempts) > 1024:
        attempts.popitem(last=False)
    provider = None
    try:
        provider = build_provider(resolve_llm_config(deps(request).llm_runtime), scenario="chat")
        return {"specification": await repair_presentation(provider, body.specification, body.issue)}
    except Exception as exc:
        # Do not return raw provider exceptions or request content.
        raise HTTPException(422, "La présentation n'a pas pu être corrigée.") from exc
    finally:
        if provider is not None:
            await provider.close()


async def _get_thread_or_404(request: Request, thread_id: str) -> ConversationThread:
    d = deps(request)
    thread = await d.repo.get_thread(thread_id)
    if thread is None:
        raise HTTPException(404, "conversation inconnue")
    return thread


@router.get("")
async def list_threads(request: Request):
    d = deps(request)
    threads = await d.repo.list_threads()
    return {
        "threads": [
            {
                "id": t.id, "title": t.title, "pinned": t.pinned, "status": t.status.value,
                "head_message_id": t.head_message_id, "mission_ids": t.mission_ids,
                "run_ids": t.run_ids, "updated_at": t.updated_at,
                "compacted_message_count": t.compacted_message_count,
            }
            for t in threads
        ]
    }


@router.post("")
async def create_thread(body: ThreadCreate, request: Request):
    d = deps(request)
    thread = ConversationThread(
        id=new_id("conv"),
        title=(body.title or "Nouvelle conversation").strip()[:120],
    )
    await d.repo.create_thread(thread)
    return {"thread": thread.model_dump(mode="json")}


@router.get("/{thread_id}")
async def get_thread(thread_id: str, request: Request):
    d = deps(request)
    thread = await _get_thread_or_404(request, thread_id)
    all_msgs = await d.repo.list_thread_messages(thread_id)
    by_id = {m.id: m for m in all_msgs}
    chain: list = []
    cur = by_id.get(thread.head_message_id) if thread.head_message_id else None
    while cur is not None:
        chain.append(cur)
        cur = by_id.get(cur.parent_id) if cur.parent_id else None
    chain.reverse()
    return {
        "thread": thread.model_dump(mode="json"),
        "messages": [m.model_dump(mode="json") for m in chain],
    }


@router.patch("/{thread_id}")
async def update_thread_metadata(thread_id: str, body: ThreadUpdate, request: Request):
    d = deps(request)
    thread = await _get_thread_or_404(request, thread_id)
    if thread.status == ConversationStatus.deleted:
        raise HTTPException(410, "conversation supprimée")
    # Colonnes indépendantes : ne pas écraser le head ou les liens d'un run actif.
    if body.title is not None:
        await d.repo.db.execute("UPDATE conversation_threads SET title=? WHERE id=? AND workspace_id=?",
                                (body.title, thread.id, thread.workspace_id))
    if body.pinned is not None:
        await d.repo.db.execute("UPDATE conversation_threads SET pinned=? WHERE id=? AND workspace_id=?",
                                (int(body.pinned), thread.id, thread.workspace_id))
    updated = await d.repo.get_thread(thread_id)
    return {"thread": updated.model_dump(mode="json")}


@router.get("/{thread_id}/branches")
async def get_branches(thread_id: str, request: Request):
    """Arbre complet des messages (toutes branches) — le UI construit les sélecteurs."""
    d = deps(request)
    thread = await _get_thread_or_404(request, thread_id)
    msgs = await d.repo.list_thread_messages(thread_id)
    return {
        "head_message_id": thread.head_message_id,
        "nodes": [
            {
                "id": m.id, "parent_id": m.parent_id, "role": m.role.value,
                "status": m.status, "created_at": m.created_at,
                "preview": next((p.get("text", "")[:120] for p in m.parts if p.get("type") == "text"), ""),
            }
            for m in msgs
        ],
    }


@router.post("/{thread_id}/head")
async def set_head(thread_id: str, body: HeadBody, request: Request):
    """Changement de branche active (aucune donnée déplacée ni réécrite)."""
    d = deps(request)
    thread = await _get_thread_or_404(request, thread_id)
    msg = await d.repo.get_chat_message(body.message_id)
    if msg is None or msg.thread_id != thread_id:
        raise HTTPException(404, "message introuvable dans cette conversation")
    thread.head_message_id = body.message_id
    thread.updated_at = utcnow()
    await d.repo.update_thread(thread)
    return {"thread": thread.model_dump(mode="json")}


@router.post("/{thread_id}/stream")
async def stream_turn(thread_id: str, body: StreamBody, request: Request):
    """Un tour de conversation en SSE. Événements : message, delta-tool (tool_call/
    tool_result), compaction, head, error, done — tous issus du backend."""
    d = deps(request)
    thread = await _get_thread_or_404(request, thread_id)
    if thread.status == ConversationStatus.deleted:
        raise HTTPException(410, "conversation supprimée")

    service = ChatService()

    async def _gen():
        try:
            async for event in service.run_turn(
                d, thread, body.content, mode=body.mode, target_message_id=body.target_message_id,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except ValueError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'status': 'error'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/{thread_id}/cancel")
async def cancel_turn(thread_id: str, request: Request):
    d = deps(request)
    await _get_thread_or_404(request, thread_id)
    d.chat_controls[thread_id] = "cancel"
    return {"ok": True}


@router.post("/{thread_id}/archive")
async def archive_thread(thread_id: str, request: Request):
    """Archivage = masquage de la sidebar ; conversation et liens preuves conservés."""
    d = deps(request)
    thread = await _get_thread_or_404(request, thread_id)
    thread.status = ConversationStatus.archived
    thread.updated_at = utcnow()
    await d.repo.update_thread(thread)
    return {"thread": thread.model_dump(mode="json")}


@router.post("/{thread_id}/restore")
async def restore_thread(thread_id: str, request: Request):
    d = deps(request)
    thread = await _get_thread_or_404(request, thread_id)
    thread.status = ConversationStatus.active
    thread.updated_at = utcnow()
    await d.repo.update_thread(thread)
    return {"thread": thread.model_dump(mode="json")}


@router.delete("/{thread_id}")
async def delete_thread(thread_id: str, request: Request):
    """Soft-delete : messages et liens vers preuves/runs conservés en base (rétention
    d'audit) ; les preuves immuables ne sont jamais touchées (docs/23 §3)."""
    d = deps(request)
    thread = await _get_thread_or_404(request, thread_id)
    thread.status = ConversationStatus.deleted
    thread.updated_at = utcnow()
    await d.repo.update_thread(thread)
    return {"ok": True, "retention": "messages et preuves conservés (soft-delete)"}


@router.get("/{thread_id}/search")
async def search_thread(thread_id: str, q: str, request: Request):
    """Recherche couche 1 pour l'auditeur (toutes branches, historique complet)."""
    d = deps(request)
    thread = await _get_thread_or_404(request, thread_id)
    msgs = await d.repo.search_thread_messages(thread_id, q, limit=20)
    return {
        "query": q, "head_message_id": thread.head_message_id,
        "results": [
            {
                "id": m.id, "role": m.role.value,
                "created_at": m.created_at, "status": m.status,
                "snippet": next(
                    (p.get("text", "")[:200] for p in m.parts if p.get("type") == "text"), "",
                ),
            }
            for m in msgs
        ],
    }
