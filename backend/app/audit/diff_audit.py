"""Différentiel de re-audit (Phase 6/10) : comparaison HONNÊTE de findings entre
deux runs d'une même mission, avec statuts explicites et jamais de « résolu »
non prouvé.

Statuts :
- persistent : même clé de constat présente dans les deux runs, même contrôle,
  similarité d'énoncé suffisante ;
- resolved : absent du run actuel MAIS le contrôle a été réellement ré-inspecté
  lors du run actuel (assessment du même contrôle avec evidence) — sinon c'est
  `unknown` (l'absence d'un constat n'est pas une preuve de résolution) ;
- new : présent uniquement dans le run actuel ;
- unknown : incomparable (contrôles différents, énoncés trop différents, ou
  contrôle non ré-inspecté).

Clé stable : control_id + signature normalisée du titre (mots > 3 lettres, triés).
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

SIMILARITY_THRESHOLD = 0.6


def title_signature(title: str) -> str:
    words = [w.lower() for w in title.split() if len(w) > 3]
    return " ".join(sorted(words))


def _similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a, b).ratio() >= SIMILARITY_THRESHOLD


def diff_findings(
    base_findings, target_findings, target_controls_inspected: set[str] | None = None
) -> dict[str, Any]:
    """Compare les findings base (ancien run) vs target (run actuel).

    target_controls_inspected : contrôles réellement ré-inspectés par le run actuel
    (assessment avec evidence sur ce contrôle) — requis pour conclure « resolved ».
    """
    inspected = target_controls_inspected or set()

    base_by_control: dict[str, list] = {}
    for f in base_findings:
        base_by_control.setdefault(f.control_id or "", []).append(f)
    target_by_control: dict[str, list] = {}
    for f in target_findings:
        target_by_control.setdefault(f.control_id or "", []).append(f)

    entries: list[dict[str, Any]] = []
    matched_target_ids: set[str] = set()

    for base_f in base_findings:
        control = base_f.control_id or ""
        candidates = target_by_control.get(control, [])
        match = None
        best_ratio = 0.0
        base_sig = title_signature(base_f.title)
        for t in candidates:
            ratio = SequenceMatcher(None, base_sig, title_signature(t.title)).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                match = t
        if match is not None and _similar(base_sig, title_signature(match.title)):
            matched_target_ids.add(match.id)
            entries.append({
                "key": base_f.id,
                "status": "persistent",
                "control_id": control,
                "base": {"id": base_f.id, "title": base_f.title, "severity": base_f.severity_proposed.value,
                         "status": base_f.status.value},
                "target": {"id": match.id, "title": match.title, "severity": match.severity_proposed.value,
                           "status": match.status.value},
                "explanation": "constat à nouveau observé lors du run actuel (même contrôle, énoncé similaire)",
            })
        elif control in inspected:
            entries.append({
                "key": base_f.id,
                "status": "resolved",
                "control_id": control,
                "base": {"id": base_f.id, "title": base_f.title, "severity": base_f.severity_proposed.value,
                         "status": base_f.status.value},
                "target": None,
                "explanation": (
                    "absent du run actuel ET le contrôle a été ré-inspecté avec des preuves "
                    "— résolution crédible (à confirmer par la revue humaine)"
                ),
            })
        else:
            entries.append({
                "key": base_f.id,
                "status": "unknown",
                "control_id": control,
                "base": {"id": base_f.id, "title": base_f.title, "severity": base_f.severity_proposed.value,
                         "status": base_f.status.value},
                "target": None,
                "explanation": (
                    "absent du run actuel mais le contrôle n'a PAS été ré-inspecté : "
                    "l'absence d'observation n'est pas une preuve de résolution"
                ),
            })

    for target_f in target_findings:
        if target_f.id in matched_target_ids:
            continue
        entries.append({
            "key": target_f.id,
            "status": "new",
            "control_id": target_f.control_id or "",
            "base": None,
            "target": {"id": target_f.id, "title": target_f.title,
                       "severity": target_f.severity_proposed.value, "status": target_f.status.value},
            "explanation": "constat nouveau (non observé dans le run de référence)",
        })

    order = {"persistent": 0, "resolved": 1, "new": 2, "unknown": 3}
    entries.sort(key=lambda e: order.get(e["status"], 9))
    return {
        "entries": entries,
        "summary": {
            "base_total": len(base_findings),
            "target_total": len(target_findings),
            "persistent": sum(1 for e in entries if e["status"] == "persistent"),
            "resolved": sum(1 for e in entries if e["status"] == "resolved"),
            "new": sum(1 for e in entries if e["status"] == "new"),
            "unknown": sum(1 for e in entries if e["status"] == "unknown"),
        },
        "note": (
            "« resolved » exige que le contrôle ait été ré-inspecté avec preuves lors du run "
            "actuel ; sinon le statut reste unknown — l'absence d'observation n'est pas une "
            "preuve de résolution."
        ),
    }
