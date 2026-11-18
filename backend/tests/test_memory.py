"""Phase 9/10 — Audit Memory : récupération autorisée, références jamais assimilées
à des preuves vérifiées, frontière workspace respectée."""

from __future__ import annotations

from app.audit.memory import build_memory_results
from app.models import FindingCandidate, Severity


def _f(id_, mission, title, statement, review="needs_review"):
    return FindingCandidate(id=id_, run_id="r1", mission_id=mission, control_id="DATA-01",
                            title=title, statement=statement, severity_proposed=Severity.medium,
                            status=review)


MISSIONS = {"m1": {"title": "Audit 2025 — Orders"}}


def test_retrieval_returns_flagged_memory():
    findings = [_f("f1", "m1", "Quantités négatives", "Quantité négative détectée ligne 2")]
    out = build_memory_results("quantités", findings, MISSIONS, {"r1": "conv_1"})
    assert len(out) == 1
    r = out[0]
    assert r["memory"] is True  # jamais traité comme preuve vérifiée
    assert r["thread_id"] == "conv_1"
    assert r["evidence_refs"] == []  # vérification => get_evidence d'origine


def test_no_fabricated_relation_when_query_misses():
    findings = [_f("f1", "m1", "Quantités négatives", "x")]
    assert build_memory_results("fraude fiscale", findings, MISSIONS, {}) == []


def test_bounded_results():
    findings = [_f(f"f{i}", "m1", "Violation", f"contenu commun {i}") for i in range(20)]
    out = build_memory_results("violation", findings, MISSIONS, {})
    assert len(out) == 8  # MAX_RESULTS


def test_review_status_surfaced():
    findings = [_f("f1", "m1", "Écart", "x", review="accepted")]
    out = build_memory_results("écart", findings, MISSIONS, {})
    assert out[0]["review_status"] == "accepted"
