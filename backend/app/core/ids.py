"""Générateurs d'identifiants traçables (docs/05, docs/14)."""

from __future__ import annotations

import itertools
import uuid

_counters: dict[str, itertools.count] = {}
_sequences: dict[str, int] = {}

PREFIXES = {
    "source": "src",
    "mission": "mission",
    "run": "run",
    "tool_call": "tc",
    "evidence": "ev",
    "finding": "finding",
    "assessment": "asm",
    "report": "report",
    "step": "step",
    "plan": "plan",
    "journey": "journey",
}


def new_id(kind: str, sequential: bool = False) -> str:
    """Retourne un identifiant du type ev_0001 (séquentiel) ou ev_a1b2c3d4 (uuid).

    Le séquentiel améliore la lisibilité en démo ; l'uuid évite les collisions
    entre bases/réinitialisations.
    """
    prefix = PREFIXES.get(kind, kind)
    if sequential:
        seq = _sequences.get(kind, 0) + 1
        _sequences[kind] = seq
        return f"{prefix}_{seq:04d}"
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def reset_sequences(start: int = 0) -> None:
    for k in _sequences:
        _sequences[k] = start


def short_uuid() -> str:
    return uuid.uuid4().hex[:8]
