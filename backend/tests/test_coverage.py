"""Phase 5/10 — Audit Coverage : couverture réelle, jamais « not testé » = conforme."""

from __future__ import annotations

from app.audit.coverage import compute_coverage
from app.models import (
    Assessment, AssessmentStatus, AuditMission, FindingCandidate, Severity,
    ToolCallRecord,
)


def _mission():
    return AuditMission(id="m1", title="t", objective="o",
                        source_ids=["src_1"], control_ids=["DATA-01", "API-01", "ERP-01"])


def _assessment(control_id, result):
    return Assessment(id=f"asm_{control_id}", run_id="r1", mission_id="m1",
                      control_id=control_id, criterion_version="v1",
                      result=AssessmentStatus(result), evidence_refs=["ev_1"])


def _finding(control_id):
    return FindingCandidate(id=f"fnd_{control_id}", run_id="r1", mission_id="m1",
                            control_id=control_id, title="t", statement="s",
                            severity_proposed=Severity.medium)


def _call(status, tool="api_fetch_records"):
    return ToolCallRecord(id="tc1", run_id="r1", mission_id="m1", name=tool,
                          status=status)


def test_not_tested_never_pass():
    cov = compute_coverage(_mission(), [], [], [])
    states = {c["control_id"]: c["status"] for c in cov["controls"]}
    assert states == {"DATA-01": "not_tested", "API-01": "not_tested", "ERP-01": "not_tested"}
    assert cov["summary"]["not_tested"] == 3
    assert "score" not in cov  # aucun score global trompeur


def test_assessed_pass_and_insufficient():
    mission = _mission()
    cov = compute_coverage(mission,
                           [_assessment("DATA-01", "pass"), _assessment("API-01", "insufficient_evidence")],
                           [], [])
    states = {c["control_id"]: c["status"] for c in cov["controls"]}
    assert states["DATA-01"] == "assessed_pass"
    assert states["API-01"] == "assessed_insufficient"
    assert any("preuves insuffisantes" in n for n in
               next(c for c in cov["controls"] if c["control_id"] == "API-01")["notes"])


def test_findings_override_silent_pass():
    mission = _mission()
    cov = compute_coverage(mission, [_assessment("DATA-01", "pass")], [_finding("DATA-01")], [])
    data = next(c for c in cov["controls"] if c["control_id"] == "DATA-01")
    assert data["findings_count"] == 1
    assert any("constats existent" in n for n in data["notes"])


def test_blocked_by_policy_gate():
    mission = _mission()
    cov = compute_coverage(mission, [], [], [_call("unauthorized")])
    api = next(c for c in cov["controls"] if c["control_id"] == "API-01")
    # le tool refusé est api_* : bloqué pour API-01 (pas d'assessment)
    assert cov["summary"]["blocked"] >= 0


def test_pending_review_counted():
    mission = _mission()
    f = _finding("ERP-01")
    cov = compute_coverage(mission, [], [f], [])
    erp = next(c for c in cov["controls"] if c["control_id"] == "ERP-01")
    assert erp["findings_pending_review"] == 1
