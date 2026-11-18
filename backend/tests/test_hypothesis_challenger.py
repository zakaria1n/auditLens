"""Phase 4/10 — Hypothesis Challenger : alternatives, contradictions, révisions.

Le modèle doit chercher des explications alternatives et des preuves contraires
AVANT de conclure 'supported' ; les révisions sont horodatées dans l'état ; les
evidence refs invalides restent rejetées (docs/06) — rien n'est simulé.
"""

from __future__ import annotations

from app.agent.investigation import (
    CHALLENGER_CONSIGNES,
    Hypothesis,
    HypothesisRevision,
    InvestigationState,
    investigation_request,
)


def _state() -> InvestigationState:
    st = InvestigationState()
    st.decisions = 2
    return st


EVIDENCE_INDEX = {"ev_1": object(), "ev_2": object(), "ev_3": object()}


def test_alternatives_and_contradictions_stored():
    st = _state()
    notes = st.apply_hypotheses([{
        "id": "h1", "statement": "Les factures ne correspondent pas aux livraisons",
        "status": "inconclusive", "evidence_refs": ["ev_1"],
        "alternatives": [
            {"id": "alt_1", "statement": "Erreur de saisie date", "evidence_refs": ["ev_2"]},
            {"id": "alt_2", "statement": "Référence inexistante (hypothèse inventée)", "evidence_refs": ["ev_999"]},
        ],
        "contradicted_by": ["ev_3", "ev_999"],
    }], EVIDENCE_INDEX)
    h = st.hypotheses[0]
    assert h.alternatives[0]["id"] == "alt_1"
    # l'alternative avec evidence inexistante est épurée (comme les refs principales)
    assert h.alternatives[1]["evidence_refs"] == []
    assert h.contradicted_by == ["ev_3"]  # ev_999 hors mission ignorée
    assert any("ev_999" in n for n in notes) or notes == []


def test_revision_recorded_on_change():
    st = _state()
    st.apply_hypotheses([{"id": "h1", "statement": "Hypothèse initiale", "status": "open", "evidence_refs": []}], EVIDENCE_INDEX)
    st.decisions = 3
    st.apply_hypotheses([{
        "id": "h1", "statement": "Hypothèse révisée après contradictions",
        "status": "inconclusive", "evidence_refs": ["ev_1"],
        "revision_note": "preuve contraire ev_1 trouvée",
    }], EVIDENCE_INDEX)
    h = st.hypotheses[0]
    assert len(h.revisions) == 1
    rev: HypothesisRevision = h.revisions[0]
    assert rev.turn == 3 and rev.status == "open" and rev.statement == "Hypothèse initiale"
    assert rev.note == "preuve contraire ev_1 trouvée"
    # sérialisable pour le checkpoint (ADR-15) — révisions incluses
    payload = st.to_payload()
    assert payload["hypotheses"][0]["revisions"][0]["note"] == "preuve contraire ev_1 trouvée"


def test_no_revision_when_unchanged():
    st = _state()
    st.apply_hypotheses([{"id": "h1", "statement": "Stable", "status": "open", "evidence_refs": []}], EVIDENCE_INDEX)
    st.apply_hypotheses([{"id": "h1", "statement": "Stable", "status": "open", "evidence_refs": []}], EVIDENCE_INDEX)
    assert st.hypotheses[0].revisions == []


def test_checkpoint_roundtrip_preserves_challenger_fields():
    st = _state()
    st.apply_hypotheses([{
        "id": "h1", "statement": "H", "status": "open", "evidence_refs": ["ev_1"],
        "alternatives": [{"id": "alt_1", "statement": "A", "evidence_refs": ["ev_2"]}],
        "contradicted_by": ["ev_3"],
    }], EVIDENCE_INDEX)
    payload = st.to_payload()
    st2 = InvestigationState()
    st2.hypotheses = [
        Hypothesis(
            id=h["id"], statement=h["statement"], status=h["status"],
            evidence_refs=h["evidence_refs"],
            alternatives=h.get("alternatives", []),
            contradicted_by=h.get("contradicted_by", []),
            revisions=[HypothesisRevision(**r) for r in h.get("revisions", [])],
        )
        for h in payload.get("hypotheses", []) if isinstance(h, dict)
    ]
    assert st2.hypotheses[0].alternatives[0]["statement"] == "A"
    assert st2.hypotheses[0].contradicted_by == ["ev_3"]


def test_challenger_consignes_in_decision_prompt():
    st = _state()
    prompt = investigation_request(
        objective="o", controls=[], capabilities=[], evidence_summaries=[],
        state=st, remaining_tool_calls=5, remaining_decisions=5,
    )
    assert "CHALLENGER" in prompt and "alternatives" in prompt and "contradicted_by" in prompt
    assert CHALLENGER_CONSIGNES in prompt
