"""EventBus : événements backend réels diffusés au frontend (SSE) — docs/02, docs/19.

Les animations UI reflètent uniquement ces événements, jamais des timers factices.
Les événements sont persistés (historique) et poussés aux abonnés SSE en direct.
"""

from __future__ import annotations

import asyncio

from ..models import RunEvent
from ..models.schemas import utcnow


class EventBus:
    def __init__(self, repo):
        self.repo = repo
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    async def publish(self, run_id: str, type_: str, data: dict) -> RunEvent:
        seq = await self.repo.append_event(RunEvent(seq=0, run_id=run_id, type=type_, data=data))
        event = RunEvent(seq=seq, run_id=run_id, type=type_, at=utcnow(), data=data)
        for queue in self._subscribers.get(run_id, set()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # abonné lent : il rattrapera via l'historique
                pass
        return event

    def subscribe(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.setdefault(run_id, set()).add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        self._subscribers.get(run_id, set()).discard(queue)
