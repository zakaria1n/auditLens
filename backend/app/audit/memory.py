"""Audit Memory & Context Retrieval (Phase 9/10) : récupération AUTORISÉE
d'investigations antérieures pertinentes — références uniquement, jamais traitées
comme des preuves vérifiées.

- `search_investigations` (tool chat) : recherche LIKE bornée dans les findings de
  TOUS les run/mission de l'utilisateur local (mono-utilisateur docs/03) ;
- chaque résultat cite : mission, run, statut de revue, date, lien preuve/rapport ;
- frontières : workspace courant uniquement (champ workspace_id vérifié) ;
- les résultats portent le flag `memory: true` — assistant statements ≠ preuve ;
- la vérification factuelle passe TOUJOURS par la preuve d'origine (get_evidence).
"""

from __future__ import annotations

from typing import Any

MAX_RESULTS = 8
SNIPPET_WIDTH = 200


def build_memory_results(
    query: str,
    findings: list,          # FindingCandidate (toutes missions du workspace courant)
    missions_by_id: dict[str, Any],
    threads_by_run: dict[str, str],
) -> list[dict[str, Any]]:
    needle = query.strip().lower()
    out: list[dict[str, Any]] = []
    for f in findings:
        haystack = f"{f.title} {f.statement} {f.control_id or ''}".lower()
        if needle not in haystack:
            continue
        mission = missions_by_id.get(f.mission_id)
        mission_title = (mission['title'] if isinstance(mission, dict) else mission.title) if mission else 'mission inconnue'
        out.append({
            "memory": True,  # JAMAIS traité comme preuve vérifiée
            "finding_id": f.id,
            "mission_id": f.mission_id,
            "mission_title": mission_title,
            "run_id": f.run_id,
            "control_id": f.control_id,
            "title": f.title,
            "statement": f.statement[:SNIPPET_WIDTH],
            "severity": f.severity_proposed.value,
            "review_status": f.status.value,
            "created_at": f.created_at,
            "thread_id": threads_by_run.get(f.run_id),
            "evidence_refs": f.evidence_refs,  # vérification => get_evidence sur preuve d'origine
        })
        if len(out) >= MAX_RESULTS:
            break
    return out
