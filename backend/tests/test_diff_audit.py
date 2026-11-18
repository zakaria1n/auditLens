"""Phase 6/10 — différentiel de re-audit : statuts honnêtes, jamais de résolution
non prouvée.

Règles clés :
- persistent : même contrôle + énoncé similaire (>= seuil) ;
- resolved UNIQUEMENT si le contrôle a été ré-inspecté (assessment avec preuves) ;
- sinon unknown : l'absence d'observation n'est pas une preuve de résolution ;
- new : constat nouveau sans base comparable.
"""

from __future__ import annotations

from app.audit.diff_audit import diff_findings
from app.models import FindingCandidate, Severity


def _f(id_, control, title, status="needs_review"):
    return FindingCandidate(id=id_, run_id="r", mission_id="m", control_id=control,
                            title=title, statement="s", severity_proposed=Severity.medium,
                            status=status)


def test_persistent_same_control_similar_title():
    base = [_f("f1", "DATA-01", "Violations du Data Contract détectées")]
    target = [_f("f2", "DATA-01", "Violations du Data Contract détectées à nouveau")]
    out = diff_findings(base, target, {"DATA-01"})
    assert out["summary"]["persistent"] == 1 and out["summary"]["resolved"] == 0


def test_resolved_requires_control_reinspected():
    base = [_f("f1", "DATA-01", "Violations du Data Contract détectées")]
    # contrôle ré-inspecté => resolved crédible
    out = diff_findings(base, [], {"DATA-01"})
    assert out["summary"]["resolved"] == 1
    # contrôle NON ré-inspecté => unknown, jamais resolved
    out2 = diff_findings(base, [], set())
    assert out2["summary"]["unknown"] == 1 and out2["summary"]["resolved"] == 0
    assert "pas une preuve de résolution" in out2["entries"][0]["explanation"]


def test_new_finding_flagged():
    base = []
    target = [_f("f2", "API-01", "Endpoint approuvé en erreur HTTP")]
    out = diff_findings(base, target, {"API-01"})
    assert out["summary"]["new"] == 1


def test_different_controls_are_unknown_not_matched():
    base = [_f("f1", "DATA-01", "Violations du Data Contract détectées")]
    target = [_f("f2", "API-01", "Violations du Data Contract détectées")]
    # seul API-01 ré-inspecté (le finding cible est sur API-01) : DATA-01 non ré-inspecté
    out = diff_findings(base, target, {"API-01"})
    # contrôle différent => jamais appariés (f1 unknown car non ré-inspecté, f2 new)
    assert out["summary"]["persistent"] == 0
    statuses = {e["status"] for e in out["entries"]}
    assert statuses == {"unknown", "new"}


def test_summary_counts_consistent():
    base = [_f("f1", "DATA-01", "Violations détectées"), _f("f2", "ERP-01", "Écart réconciliation")]
    target = [_f("f3", "DATA-01", "Violations détectées encore"), _f("f4", "API-01", "Endpoint en erreur")]
    out = diff_findings(base, target, {"DATA-01"})
    s = out["summary"]
    assert s["base_total"] == 2 and s["target_total"] == 2
    assert s["persistent"] + s["resolved"] + s["unknown"] == 2
    assert s["new"] == 1
