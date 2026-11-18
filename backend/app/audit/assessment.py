"""Évaluation des assessments : déterministe quand c'est possible (docs/11).

- DATA-01 / API-01 / WEB-01 : évalués depuis les evidences factuelles, sans LLM.
- ERP-01 / ERP-02 / CROSS-01 : investigation agent => `needs_review` si des
  constats existent, `insufficient_evidence` sinon. Jamais de pass/fail par intuition.
"""

from __future__ import annotations

from ..core.ids import new_id
from ..models import Assessment, AssessmentStatus, Evidence, FindingCandidate
from .controls import Control


def _find(evidence_list: list[Evidence], type_: str) -> list[Evidence]:
    return [e for e in evidence_list if e.type == type_]


def evaluate_assessment(
    control: Control,
    run_evidence: list[Evidence],
    findings: list[FindingCandidate],
    run_id: str,
    mission_id: str,
) -> Assessment:
    observations: list[str] = []
    limitations: list[str] = []
    refs: list[str] = []
    result: AssessmentStatus

    if control.evaluator == "data_rules":
        validations = _find(run_evidence, "validation")
        profiles = _find(run_evidence, "profile")
        refs = [e.id for e in validations + profiles]
        if not validations:
            result = AssessmentStatus.insufficient_evidence
            limitations.append("aucune evidence de validation (data_validate) pour ce contrôle")
        else:
            all_valid = all((e.summary or {}).get("valid") is True for e in validations)
            total_violations = sum(int((e.summary or {}).get("violation_count") or 0) for e in validations)
            if all_valid:
                result = AssessmentStatus.pass_
                observations.append(f"{len(validations)} validation(s) sans violation sur {sum(int((e.summary or {}).get('rows') or 0) for e in validations)} lignes")
            else:
                result = AssessmentStatus.fail
                observations.append(f"{total_violations} violation(s) de règle(s) détectée(s)")
        # finding associé => toujours needs_review humain pour l'interprétation
        related = [f for f in findings if f.control_id == control.id]
        if related and result == AssessmentStatus.fail:
            limitations.append("interprétation métier requise : voir findings associés")

    elif control.evaluator == "api_contract":
        checks = _find(run_evidence, "contract_check")
        refs = [e.id for e in checks]
        if not checks:
            result = AssessmentStatus.insufficient_evidence
            limitations.append("aucun résultat de test contractuel (api_inspect_contract)")
        else:
            status_ok = all((e.summary or {}).get("endpoints_checked", 0) == (e.summary or {}).get("ok", 0)
                            and (e.summary or {}).get("endpoints_checked", 0) > 0 for e in checks)
            contract_violations = sum(int((e.summary or {}).get("contract_violations") or 0) for e in checks)
            if contract_violations > 0:
                result = AssessmentStatus.fail
                observations.append(f"{contract_violations} violation(s) de contrat documenté (schéma, statut, pagination)")
            elif status_ok:
                result = AssessmentStatus.pass_
                observations.append("tous les endpoints approuvés répondent selon le contrat")
            else:
                result = AssessmentStatus.fail
                observations.append("au moins un endpoint approuvé ne répond pas conformément")

    elif control.evaluator == "web_journey":
        traces = _find(run_evidence, "web_trace")
        refs = [e.id for e in traces]
        if not traces:
            result = AssessmentStatus.insufficient_evidence
            limitations.append("aucune trace de parcours (web_run_journey)")
        else:
            all_passed = all((e.summary or {}).get("all_passed") is True for e in traces)
            if all_passed:
                result = AssessmentStatus.pass_
                observations.append("tous les parcours exécutés passent leurs assertions")
            else:
                result = AssessmentStatus.fail
                observations.append("au moins un parcours échoue à ses assertions")

    elif control.evaluator == "odoo_reconciliation":
        # Évaluation déterministe depuis l'evidence odoo_cross_check (réconciliation docs/11).
        cross_checks = _find(run_evidence, "odoo_cross_check")
        refs = [e.id for e in cross_checks]
        if not cross_checks:
            result = AssessmentStatus.insufficient_evidence
            limitations.append("aucune evidence de réconciliation (odoo_cross_check) pour ce contrôle")
        else:
            confirmed = sum(int((e.summary or {}).get("confirmed") or 0) for e in cross_checks)
            suspicious = sum(int((e.summary or {}).get("suspicious") or 0) for e in cross_checks)
            if confirmed > 0:
                result = AssessmentStatus.fail
                observations.append(f"{confirmed} violation(s) confirmée(s) : contradiction interne entre preuves collectées")
            elif suspicious > 0:
                # Les situations suspectes requièrent l'interprétation métier — jamais pass automatique.
                result = AssessmentStatus.needs_review
                observations.append(f"{suspicious} situation(s) suspecte(s) à investiguer (aucune contradiction interne confirmée)")
            else:
                result = AssessmentStatus.pass_
                observations.append("réconciliation sans violation (quantités cohérentes, références rattachables, stock non négatif)")
        related = [f for f in findings if f.control_id == control.id]
        if related:
            limitations.append("interprétation métier requise : voir findings associés")

    else:  # agent_correlation (ERP-01, CROSS-01)
        related = [f for f in findings if f.control_id == control.id and f.status.value in ("needs_review", "accepted")]
        refs = sorted({r for f in related for r in f.evidence_refs})
        if related:
            result = AssessmentStatus.needs_review
            observations.append(
                f"{len(related)} constat(s) proposé(s) par l'agent — revue humaine requise"
            )
        else:
            result = AssessmentStatus.insufficient_evidence
            limitations.append(
                "aucun constat corrélé produit ; ce contrôle requiert une investigation agent (preuves ou accès manquants)"
            )

    return Assessment(
        id=new_id("assessment"),
        run_id=run_id,
        mission_id=mission_id,
        control_id=control.id,
        criterion_version=control.version,
        result=result,
        evidence_refs=refs,
        observations=observations,
        method=control.method,
        limitations=limitations,
    )
