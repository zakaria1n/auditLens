"""Phase 10/10 — Remediation & Verification : transitions humaines contrôlées,
'verified' verrouillé derrière un run de vérification avec preuves."""

from __future__ import annotations

from app.audit.remediation import (
    apply_human_transition,
    apply_verification_result,
    build_action_plan,
    validate_transition,
)


def _plan():
    return build_action_plan("f1", [
        "Corriger la saisie des quantités négatives (contrôle à la saisie)",
        "Revoir le mapping de la colonne date",
    ], priorities={"Corriger la saisie des quantités négatives (contrôle à la saisie)": "high"})


def test_initial_plan_proposed_with_priorities():
    plan = _plan()
    assert plan["actions"][0]["status"] == "proposed"
    assert plan["actions"][0]["priority"] == "high"
    assert "distinguishées" in plan["note"]


def test_human_flow_proposed_to_ready_to_verify():
    plan = _plan()
    for status in ("accepted", "in_progress", "ready_to_verify"):
        plan, err = apply_human_transition(plan, "act_1", status)
        assert err is None, (status, err)
    assert plan["actions"][0]["status"] == "ready_to_verify"
    assert plan["actions"][0]["history"][-1] == {"from": "in_progress", "to": "ready_to_verify", "by": "auditor"}


def test_human_cannot_mark_verified():
    plan = _plan()
    plan, _ = apply_human_transition(plan, "act_1", "accepted")
    plan, err = apply_human_transition(plan, "act_1", "verified")
    assert err and "run de vérification" in err
    assert plan["actions"][0]["status"] == "accepted"  # inchangé


def test_verification_run_grants_verified_with_evidence():
    plan = _plan()
    plan, _ = apply_human_transition(plan, "act_1", "accepted")
    plan, _ = apply_human_transition(plan, "act_1", "in_progress")
    plan, _ = apply_human_transition(plan, "act_1", "ready_to_verify")
    plan, err = apply_verification_result(plan, "act_1", verified=True, evidence_ids=["ev_v1"])
    assert err is None
    action = plan["actions"][0]
    assert action["status"] == "verified"
    assert action["verification_evidence_ids"] == ["ev_v1"]
    assert action["history"][-1]["by"] == "verification_run"


def test_verified_without_evidence_refused():
    plan = _plan()
    plan, _ = apply_human_transition(plan, "act_1", "accepted")
    plan, _ = apply_human_transition(plan, "act_1", "in_progress")
    plan, _ = apply_human_transition(plan, "act_1", "ready_to_verify")
    plan, err = apply_verification_result(plan, "act_1", verified=True, evidence_ids=[])
    assert err and "exige au moins une evidence" in err


def test_verify_fix_refused_before_ready():
    plan = _plan()
    plan, err = apply_verification_result(plan, "act_1", verified=False, evidence_ids=["ev_x"])
    assert err and "ready_to_verify" in err


def test_unknown_action_and_status():
    plan = _plan()
    plan, err = apply_human_transition(plan, "nope", "accepted")
    assert err and "inconnue" in err
    plan, err = apply_human_transition(plan, "act_1", "teleported")
    assert err and "interdite" in err
    assert validate_transition("ghost", "x") is not None
