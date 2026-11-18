"""Construction des ReportSnapshot (docs/14) — versionnés, données figées.

`ReportSnapshot` ne se régénère pas silencieusement : chaque nouvelle version
est explicite (revue humaine => version+1).
"""

from __future__ import annotations

from ..core.ids import new_id
from ..models import (
    AuditMission,
    AuditRun,
    Evidence,
    FindingCandidate,
    FindingStatus,
    ReportSnapshot,
    RunStatus,
)


def build_report(
    run: AuditRun,
    mission: AuditMission,
    assessments,
    evidence: list[Evidence],
    findings: list[FindingCandidate],
    version: int = 1,
) -> ReportSnapshot:
    assessed = [a.control_id for a in assessments]
    findings_included = [f.id for f in findings if f.status == FindingStatus.accepted]
    findings_pending = [f.id for f in findings if f.status == FindingStatus.needs_review]
    findings_rejected = [f.id for f in findings if f.status == FindingStatus.rejected]
    limitations: list[str] = []
    for a in assessments:
        limitations.extend(f"{a.control_id}: {l}" for l in a.limitations)

    lines = [
        f"# Rapport d'audit — {mission.title}",
        f"Run `{run.id}` — mission `{mission.id}` — version {version}",
        f"Période : {mission.time_range.get('from') or 'non précisée'} → {mission.time_range.get('to') or 'non précisée'}",
        f"Modèle : {run.provider_id}/{run.model_id} (prompts {run.prompt_version})",
        "",
        "## Objectif",
        mission.objective,
        "",
        "## Assessments",
    ]
    for a in assessments:
        lines.append(f"- **{a.control_id}** ({a.criterion_version}) : `{a.result.value}`")
        for obs in a.observations:
            lines.append(f"  - {obs}")
        for lim in a.limitations:
            lines.append(f"  - *limite : {lim}*")
    lines += ["", "## Constats (revue humaine)"]
    if not findings:
        lines.append("- aucun constat proposé pour ce run")
    for f in findings:
        if f.status == FindingStatus.rejected:
            lines.append(f"- ~~{f.title}~~ — **rejeté par le validateur** : {f.rejection_reason}")
            continue
        status_label = {
            FindingStatus.accepted: "accepté",
            FindingStatus.rejected: "rejeté",
            FindingStatus.needs_review: "en attente de revue",
            FindingStatus.needs_more_evidence: "preuves supplémentaires demandées",
        }.get(f.status, f.status.value)
        lines.append(f"- **{f.title}** — sévérité proposée : `{f.severity_proposed.value}`, statut : **{status_label}**")
        lines.append(f"  - {f.statement}")
        if f.evidence_refs:
            lines.append(f"  - preuves : {', '.join(f'`{r}`' for r in f.evidence_refs)}")
        if f.review:
            lines.append(f"  - revue ({f.review.reviewer}) : {f.review.decision} — {f.review.reason}")
        for u in f.uncertainties:
            lines.append(f"  - *incertitude : {u}*")
    lines += [
        "",
        "## Limites générales",
        f"- Contrôles couverts : {', '.join(assessed) or 'aucun'}",
        f"- Preuves collectées : {len(evidence)}",
        f"- Constats en attente de revue : {len(findings_pending)} ; rejetés par validateur : {len(findings_rejected)}",
        * [f"- {l}" for l in limitations[:20]],
        "",
        "> Ce rapport ne certifie aucune conformité globale. Les constats sont des propositions",
        "> fondées sur les preuves référencées et soumises à la décision de l'auditeur.",
    ]

    return ReportSnapshot(
        id=new_id("report"), run_id=run.id, mission_id=mission.id, version=version,
        period=mission.time_range, sources=mission.source_ids,
        assessed=assessed,
        partial=[run.stop_reason] if run.status == RunStatus.partial else [],
        not_assessed=[c for c in mission.control_ids if c not in assessed],
        findings_included=findings_included, findings_excluded=findings_rejected,
        limitations=limitations, model_id=run.model_id, provider_id=run.provider_id,
        prompt_version=run.prompt_version, markdown="\n".join(lines),
    )
