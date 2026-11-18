"""Remediation & Verification Assistant (Phase 10/10) : plan d'action structuré
par constat, transitions contrôlées par l'HUMAIN, vérification par preuve.

Invariants :
- l'agent ne modifie JAMAIS un ERP/production — il ne fait que proposer ;
- action humaine « Completed » ≠ constat techniquement vérifié : seul un run de
  vérification avec evidence `remediation_verification` passe le statut verified ;
- toutes les transitions sont tracées (history horodaté).
"""

from __future__ import annotations

from typing import Any, Literal

ActionStatus = Literal[
    "proposed", "accepted", "in_progress", "ready_to_verify", "verified", "not_verified"
]

HUMAN_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"accepted", "rejected"},
    "accepted": {"in_progress"},
    "in_progress": {"ready_to_verify"},
    "ready_to_verify": {"in_progress"},  # retour arrière humain autorisé
    "verified": set(),                    # verrouillé : seul un run de vérification décide
    "not_verified": {"in_progress"},
}


def validate_transition(current: str, next_status: str) -> str | None:
    """Erreur FR si la transition n'est pas autorisée pour un humain."""
    allowed = HUMAN_TRANSITIONS.get(current)
    if allowed is None:
        return f"statut {current!r} inconnu"
    if next_status not in allowed:
        if next_status == "verified":
            return "'verified' requiert un run de vérification (utilisez la vérification dédiée)"
        return f"transition {current!r} -> {next_status!r} interdite "
    if next_status == "verified":
        return "'verified' requiert un run de vérification (utilisez la vérification dédiée)"
    return None


def build_action_plan(
    finding_id: str,
    recommendations: list[str],
    priorities: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Plan initial : actions PROPOSÉES depuis les recommendations du constat.
    L'humain accepte/rejette ; 'verified' n'est jamais posé ici."""
    actions = []
    for i, rec in enumerate(recommendations[:6]):
        actions.append({
            "id": f"act_{i + 1}",
            "description": rec,
            "priority": (priorities or {}).get(rec, "medium"),
            "status": "proposed",
            "owner": None,  # saisie humaine optionnelle
            "verification_evidence_ids": [],
            "history": [],
        })
    return {
        "finding_id": finding_id,
        "actions": actions,
        "note": (
            "propositions de l'agent — distinguishées des corrections vérifiées ; "
            "l'humain contrôle l'acceptation et le statut ; 'verified' requiert un "
            "run de vérification avec preuve."
        ),
    }


def apply_human_transition(plan: dict[str, Any], action_id: str, next_status: str) -> tuple[dict[str, Any], str | None]:
    """Transition initiée par l'HUMAIN. Retourne (plan, erreur). 'verified' refusé :
    seul un run de vérification passe une action en verified (set_verification)."""
    for action in plan.get("actions", []):
        if action.get("id") == action_id:
            error = validate_transition(action["status"], next_status)
            if error:
                return plan, error
            if next_status == "verified":
                return plan, "'verified' requiert un run de vérification (utilisez la vérification dédiée)"
            action["history"].append({
                "from": action["status"], "to": next_status, "by": "auditor",
            })
            action["status"] = next_status
            return plan, None
    return plan, f"action inconnue : {action_id}"


def apply_verification_result(plan: dict[str, Any], action_id: str, verified: bool, evidence_ids: list[str]) -> tuple[dict[str, Any], str | None]:
    """Statut 'verified'/'not_verified' posé UNIQUEMENT par un run de vérification
    ayant produit des preuves (remediation_verification). Traçabilité complète."""
    for action in plan.get("actions", []):
        if action.get("id") == action_id:
            if action["status"] not in ("ready_to_verify", "verified", "not_verified"):
                return plan, f"action en statut {action['status']!r} : passez d'abord par 'ready_to_verify'"
            if verified and not evidence_ids:
                return plan, "'verified' exige au moins une evidence de vérification"
            action["history"].append({
                "from": action["status"],
                "to": "verified" if verified else "not_verified",
                "by": "verification_run",
                "evidence_ids": list(evidence_ids),
            })
            action["status"] = "verified" if verified else "not_verified"
            action["verification_evidence_ids"] = list(evidence_ids)
            return plan, None
    return plan, f"action inconnue : {action_id}"
