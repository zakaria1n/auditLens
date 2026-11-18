"""Audit Coverage Intelligence (Phase 5/10) : couverture RÉELLE des contrôles d'une
mission, calculée depuis les données backend (assessments, findings, tool_calls) —
jamais « non testé » confondu avec « conforme », aucun score global trompeur.

États possibles par contrôle :
- assessed_pass / assessed_fail / assessed_insufficient : un assessment existe
  (criterion_version cité) ;
- has_findings : constats (needs_review ou acceptés) rattachés au contrôle ;
- blocked : tool calls refusées par le Policy Gate sur ce périmètre (unauthorized) ;
- not_tested : aucun assessment ni tool call lié — JAMAIS assimilé à conforme.
"""

from __future__ import annotations

from typing import Any

from .controls import control_to_dict, get_control


def compute_coverage(
    mission, assessments: list, findings: list, tool_calls: list
) -> dict[str, Any]:
    controls_out: list[dict[str, Any]] = []
    for control_id in mission.control_ids:
        control = get_control(control_id)
        ctrl_assessments = [a for a in assessments if a.control_id == control_id]
        ctrl_findings = [f for f in findings if f.control_id == control_id]
        ctrl_calls = [t for t in tool_calls if t.mission_id == mission.id and t.status == "unauthorized"]
        ctrl_calls_any = [t for t in tool_calls if t.mission_id == mission.id]

        entry: dict[str, Any] = {
            "control_id": control_id,
            "title": control_to_dict(control).get("title") if control else control_id,
            "criterion_version": control.version if control else None,
            "assessment": None,
            "findings_count": len(ctrl_findings),
            "findings_pending_review": sum(1 for f in ctrl_findings if f.status == "needs_review"),
            "blocked": len(ctrl_calls) > 0 and not ctrl_assessments,
            "status": "not_tested",
            "evidence_refs": [],
            "notes": [],
        }
        if ctrl_assessments:
            latest = max(ctrl_assessments, key=lambda a: a.id)
            entry["assessment"] = {
                "id": latest.id, "result": latest.result.value,
                "criterion_version": latest.criterion_version,
                "evidence_refs": latest.evidence_refs, "limitations": latest.limitations,
            }
            entry["evidence_refs"] = latest.evidence_refs
            status_map = {
                "pass": "assessed_pass", "fail": "assessed_fail",
                "insufficient_evidence": "assessed_insufficient",
                "not_applicable": "not_applicable", "needs_review": "needs_review",
                "error": "assessed_insufficient", "not_tested": "not_tested",
            }
            entry["status"] = status_map.get(latest.result.value, "assessed_insufficient")
            if latest.result.value == "insufficient_evidence":
                entry["notes"].append("preuves insuffisantes : le contrôle n'a pas pu être conclu")
        elif ctrl_findings:
            entry["status"] = "findings_without_assessment"
            entry["notes"].append("constats rattachés mais aucun assessment formel")
        elif entry["blocked"]:
            entry["notes"].append("tool calls refusées par le Policy Gate (approbation manquante)")

        if ctrl_findings and entry["status"] in ("assessed_pass", "not_tested"):
            entry["notes"].append("des constats existent : voir avant de conclure")

        controls_out.append(entry)

    return {
        "mission_id": mission.id,
        "objective": mission.objective,
        "controls": controls_out,
        "summary": {
            "total": len(controls_out),
            "assessed": sum(1 for c in controls_out if c["status"].startswith("assessed")),
            "findings_related": sum(1 for c in controls_out if c["findings_count"] > 0),
            "blocked": sum(1 for c in controls_out if c["blocked"]),
            "not_tested": sum(1 for c in controls_out if c["status"] == "not_tested"),
        },
    }
