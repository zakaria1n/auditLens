"""Live Agent Steering (Phase 8/10) : file d'instructions auditeur consommées à
frontière sûre par la boucle d'investigation.

- `submit` : enregistre l'instruction (id unique, anti-doublon par contenu) —
  statut `queued` ;
- `drain` (orchestrator, entre deux tours JAMAIS pendant un tool en vol) : marque
  `applied` et les injecte dans le prochain payload de décision ;
- revalidation périmètre : l'instruction ne PEUT pas ajouter de source hors mission
  ni approuver des tools — le Policy Gate reste l'autorité ;
- persistance : les directives acceptées sont conservées dans l'état de checkpoint.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SteeringInstruction:
    id: str
    run_id: str
    instruction: str  # déjà redacté côté route
    status: str = "queued"  # queued | applied | rejected
    detail: str = ""  # raison du rejet éventuel

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "run_id": self.run_id, "instruction": self.instruction,
                "status": self.status, "detail": self.detail}


class SteeringQueue:
    """File en mémoire par run (cycle de vie = run, comme run_controls ADR-15)."""

    def __init__(self) -> None:
        self._items: dict[str, list[SteeringInstruction]] = {}

    def submit(self, run_id: str, instruction: str) -> SteeringInstruction | None:
        text = instruction.strip()[:1000]
        if not text:
            return None
        existing = self._items.get(run_id, [])
        if any(i.instruction == text and i.status == "queued" for i in existing):
            return None  # anti-doublon
        item = SteeringInstruction(id=f"steer_{uuid.uuid4().hex[:12]}", run_id=run_id, instruction=text)
        self._items.setdefault(run_id, []).append(item)
        return item

    def drain(self, run_id: str) -> list[SteeringInstruction]:
        """Consomme les instructions en attente (frontière de tour) → status applied."""
        out: list[SteeringInstruction] = []
        for item in self._items.get(run_id, []):
            if item.status == "queued":
                item.status = "applied"
                out.append(item)
        return out

    def items(self, run_id: str) -> list[SteeringInstruction]:
        return list(self._items.get(run_id, []))

    def reset(self, run_id: str) -> None:
        self._items.pop(run_id, None)
