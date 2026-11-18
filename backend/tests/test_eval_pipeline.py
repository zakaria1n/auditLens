"""Test smoke du pipeline d'évaluation (docs/17) : structure, Baseline A, Système B mock.

Exécuté sur les jeux fichiers uniquement (rapide, sans services externes).
Les anomalies injectées ne sont JAMAIS transmises à l'agent : elles servent au scoring.
"""

from __future__ import annotations

import pytest

from eval.ground_truth import FILES_EVAL, FILES_DEV, generate_files_dataset
from eval.runner import run_baseline_a, run_system_b


@pytest.mark.asyncio
async def test_baseline_a_detects_all_injected_issues_dev():
    """Baseline A : les règles déterministes détectent les 4 anomalies injectées (seed 9831)."""
    r = await run_baseline_a(FILES_DEV)
    assert r.error is None
    assert set(r.detected) == {"duplicate_order_id", "negative_quantity", "invalid_date", "missing_unit_price"}
    assert r.recall == 1.0
    assert r.missed == []


@pytest.mark.asyncio
async def test_baseline_a_detects_all_injected_issues_eval_held_out():
    """Jeu held-out (seed 5521, jamais utilisé pour ajuster quoi que ce soit)."""
    r = await run_baseline_a(FILES_EVAL)
    assert r.error is None
    assert r.recall == 1.0


@pytest.mark.asyncio
async def test_system_b_mock_pipeline_end_to_end():
    """Système B (mock) : run complet via l'app → constats fondés, evidences valides."""
    r = await run_system_b(FILES_DEV, {"provider": "mock"})
    assert r.error is None, r.error
    assert r.tool_calls >= 3
    assert r.evidence_valid is True
    assert r.recall == 1.0, f"détecté: {r.detected}, manqué: {r.missed}"
    # les constats citent des preuves et le validateur n'en a rejeté aucune de fondée
    rejected = [f for f in r.findings if f.get("status") == "rejected"]
    accepted_or_pending = [f for f in r.findings if f.get("status") in ("needs_review", "accepted")]
    assert accepted_or_pending, "au moins un constat fondé doit survivre au validateur"
    assert all(f["rejection_reason"] for f in rejected)


def test_generated_held_out_dataset_differs_from_dev():
    """Seeds distincts → données réellement différentes entre dev et eval (anti-fuite)."""
    import tempfile
    from pathlib import Path

    d1 = Path(tempfile.mkdtemp())
    d2 = Path(tempfile.mkdtemp())
    generate_files_dataset(d1, seed=9831)
    generate_files_dataset(d2, seed=5521)
    c1 = (d1 / "orders.csv").read_bytes()
    c2 = (d2 / "orders.csv").read_bytes()
    assert c1 != c2
