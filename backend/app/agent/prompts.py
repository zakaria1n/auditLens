"""Prompts système et requêtes structurées (docs/04).

Le LLM oriente l'investigation ; il ne décide ni des permissions ni des calculs.
Les tâches sont marquées `TASK:` pour permettre un mock déterministe en test.
"""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """Tu es l'agent d'audit d'AuditLens. Règles non négociables :
1. Aucune assertion de conformité sans critère explicite ET evidence référencée. `Insufficient evidence` est un résultat valide et préférable à une invention.
2. Tu utilises uniquement les tools autorisées listées ; le backend peut refuser un appel hors périmètre (c'est normal, continue autrement).
3. Donnée contradictoire ≠ fraude certaine ; propose `needs_review`.
4. Cite les evidence_ids exacts reçus. Un evidence_id inventé sera rejeté par le validateur.
5. Ne demande jamais de secrets ; ne propose aucune action mutante.
6. Tes réponses aux tâches TASK sont du JSON strict, sans texte autour."""

PLAN_SCHEMA = {
    "steps": [{"tool": "str", "source_id": "str|null", "args": {}, "rationale": "str"}],
    "evidence_expected": ["str"],
    "risks": ["str"],
}

FINDINGS_SCHEMA = {
    "findings": [{
        "control_id": "str|null",
        "title": "str",
        "statement": "str — constat précis fondé sur les preuves",
        "severity_proposed": "info|low|medium|high",
        "evidence_refs": ["ev_..."],
        "observations": ["str"],
        "method": "str",
        "limitations": ["str"],
        "recommendations": ["str"],
        "uncertainties": ["str"],
    }]
}


def plan_request(
    mission_dict: dict, sources_payload: list[dict], capabilities: list[dict],
    controls: list[dict], intelligence: dict[str, dict] | None = None,
) -> str:
    payload = {
        "mission": {
            "id": mission_dict["id"], "objective": mission_dict["objective"],
            "control_ids": mission_dict.get("control_ids", []),
            "time_range": mission_dict.get("time_range", {}),
            "limits": mission_dict.get("limits", {}),
        },
        "sources": sources_payload,
        "capabilities": capabilities,
        "controls": controls,
    }
    if intelligence:
        payload["source_intelligence"] = intelligence
    exact_tools = ", ".join(sorted({c["tool"] for c in capabilities}))
    return (
        "TASK: propose_plan\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n"
        "Propose un plan d'investigation borné (max tools du budget). CONTRAINTES STRICTES:\n"
        f"1. tool doit être copié MOT POUR MOT depuis cette liste (aucun synonyme, aucun raccourci): [{exact_tools}]\n"
        "2. respecte le `schema` exact de chaque tool (champs requis dans args);\n"
        "3. pour data_profile/data_validate, evidence_id = un id de `initial_evidence_ids` de la source fichier;\n"
        "4. pour les sources odoo, utilise odoo_read_orders (commandes), odoo_read_invoices (factures), odoo_read_stock (mouvements) — jamais un nom générique;\n"
        "5. odoo_cross_check et evidence_join s'exécutent APRÈS les lectures avec les evidence_ids RÉELS retournés par ces lectures — si tu ne connais pas encore ces ids, ne les place pas dans le plan : propose-les en investigation complémentaire.\n"
        f"Réponds en JSON: {json.dumps(PLAN_SCHEMA, ensure_ascii=False)}"
    )


def findings_request(
    evidence_summaries: list[dict], controls: list[dict], objective: str,
    investigation_state: dict | None = None,
) -> str:
    payload = {"objective": objective, "evidence_summaries": evidence_summaries, "controls": controls}
    if investigation_state:
        payload["investigation"] = investigation_state
    violations_hint = ""
    if any(s.get("type") in ("contract_check", "odoo_cross_check") for s in evidence_summaries):
        violations_hint = (
            "CONSIGNE : des violations déterministes figurent dans les evidences "
            "(contract_check, odoo_cross_check). Chaque violation confirmée (kind=confirmed) doit donner lieu "
            "à un constat fondé sur l'evidence correspondante ; les situations kind=suspicious donnent des constats "
            "prudentiels (needs_review) avec leurs limitations. Ne reformule pas une violation comme un fait nouveau : "
            "cite l'evidence source. Signale AUSSI les points conformes si un contrôle l'exige.\n"
        )
    # Observabilité générale : endpoints en échec vus par le contrôle contractuel (docs/06).
    failed_eps = []
    for s in evidence_summaries:
        if s.get("type") == "contract_check":
            failed_eps.extend((s.get("summary") or {}).get("failed_endpoints") or [])
    if failed_eps:
        sample = "; ".join(
            f"{f.get('endpoint_id')} → {f.get('status_http') or (f.get('error') or 'erreur')[:40]}"
            for f in failed_eps[:4]
        )
        violations_hint += (
            f"ATTENTION : des endpoints ont répondu en ÉCHEC lors du contrôle ({sample}). "
            "Un échec observé UNE fois peut être transitoire : si des observations plus récentes du "
            "même endpoint existent (tour différent), compare-les et qualifie (persistant vs "
            "intermittent) en citant chaque evidence ; sinon signale l'incertitude explicitement "
            "plutôt qu'une conclusion définitive.\n"
        )
    return (
        "TASK: propose_findings\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n"
        f"{violations_hint}"
        "Formule les constats proposés, chacun fondé sur des evidence_ids reçus. "
        "Si les preuves sont insuffisantes pour un critère, ne produis PAS de finding sur ce critère. "
        f"Réponds en JSON: {json.dumps(FINDINGS_SCHEMA, ensure_ascii=False)}"
    )


def summarize_evidence_for_llm(evidence: list[Any]) -> list[dict]:
    """Version minimisée : id, type, source, titre, summary (jamais de payload brut — docs/06)."""
    return [
        {
            "id": e.id,
            "type": e.type,
            "source_id": e.source_id,
            "title": e.title,
            "observed_at": e.observed_at,
            "summary": e.summary or {},
        }
        for e in evidence
    ]
