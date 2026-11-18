"""Findings Validator (docs/03, docs/04) : vérification structurelle automatique.

- Chaque evidence_ref doit exister ET appartenir à la mission → sinon REJET explicite.
- finding sans preuve : jamais `confirmed` ; garde needs_review + limitation.
- La validation sémantique reste humaine (review).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..core.ids import new_id
from ..models import Evidence, FindingCandidate, FindingStatus, Severity
from ..audit.controls import get_control


async def validate_findings(
    proposed: list[dict[str, Any]],
    *,
    run_id: str,
    mission_id: str,
    evidence_index: dict[str, Evidence],
) -> tuple[list[FindingCandidate], list[str]]:
    """Retourne (findings_valides_ou_rejetés, reasons). Les rejets sont persistés pour transparence."""
    out: list[FindingCandidate] = []
    rejections: list[str] = []

    for raw in proposed:
        fid = new_id("finding")
        try:
            severity = Severity(raw.get("severity_proposed", "medium"))
        except ValueError:
            severity = Severity.medium

        control_id = raw.get("control_id") or None
        if control_id and get_control(control_id) is None:
            rejections.append(f"{fid}: control_id inconnu {control_id!r} — rejeté")
            out.append(FindingCandidate(
                id=fid, run_id=run_id, mission_id=mission_id,
                title=str(raw.get("title", "constat"))[:200],
                statement=str(raw.get("statement", "")),
                severity_proposed=severity,
                evidence_refs=[str(r) for r in raw.get("evidence_refs", [])],
                status=FindingStatus.rejected,
                rejection_reason=f"control_id inconnu: {control_id}",
            ))
            continue

        # Evidence refs : existence + appartenance mission
        valid_refs: list[str] = []
        unknown_refs: list[str] = []
        for ref in raw.get("evidence_refs", []):
            ref = str(ref)
            if ref in evidence_index:
                valid_refs.append(ref)
            else:
                unknown_refs.append(ref)

        if unknown_refs:
            rejections.append(
                f"{fid}: evidence inexistante ou hors mission {unknown_refs} — finding rejeté"
            )
            out.append(FindingCandidate(
                id=fid, run_id=run_id, mission_id=mission_id,
                control_id=control_id,
                title=str(raw.get("title", "constat"))[:200],
                statement=str(raw.get("statement", "")),
                severity_proposed=severity,
                evidence_refs=[str(r) for r in raw.get("evidence_refs", [])],
                observations=[str(o) for o in raw.get("observations", [])],
                method=str(raw.get("method", "")),
                limitations=[str(l) for l in raw.get("limitations", [])],
                recommendations=[str(r) for r in raw.get("recommendations", [])],
                uncertainties=[str(u) for u in raw.get("uncertainties", [])],
                status=FindingStatus.rejected,
                rejection_reason=f"evidence_refs invalides (inexistantes ou hors mission): {unknown_refs}",
            ))
            continue

        limitations = [str(l) for l in raw.get("limitations", [])]
        if not valid_refs:
            # Invariant docs/14 : finding sans preuve ne peut être confirmé.
            limitations.append(
                "aucune evidence référencée — ce constat ne peut jamais être confirmé sans procédure manuelle documentée"
            )

        out.append(FindingCandidate(
            id=fid, run_id=run_id, mission_id=mission_id,
            control_id=control_id,
            title=str(raw.get("title", "constat"))[:200],
            statement=str(raw.get("statement", "")),
            severity_proposed=severity,
            evidence_refs=valid_refs,
            observations=[str(o) for o in raw.get("observations", [])],
            method=str(raw.get("method", "")),
            limitations=limitations,
            recommendations=[str(r) for r in raw.get("recommendations", [])],
            uncertainties=[str(u) for u in raw.get("uncertainties", [])],
            status=FindingStatus.needs_review,
        ))

    return out, rejections
