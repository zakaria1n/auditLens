"""Tests de comptabilité d'évaluation (docs/17 v4) — empêche les métriques trompeuses.

Invariants :
- chaque exécution tentée compte (erreur, silence, budget épuisé → JAMAIS exclues) ;
- recall = 0.0 pour un run sans détection (jamais None quand des catégories sont attendues) ;
- l'inconclusif correct est DISTINCT d'une anomalie manquée ;
- les claims interdits comptent dans le dénominateur de précision ;
- les critères déclaratifs échouent explicitement (jamais acceptés par défaut).
"""

from __future__ import annotations

from eval.ground_truth import EvalCase
from eval.runner import CaseResult, eval_criteria, render_report, _score


def _case(**kw) -> EvalCase:
    base = dict(
        case_id="t", source_kind="api", objective="o",
        expected={
            "cat_a": ["alpha"],
            "cat_b": ["beta"],
        },
    )
    base.update(kw)
    return EvalCase(**base)


def test_score_detects_misses_and_baseline_fp():
    case = _case(baseline_map={"R1": "cat_a"})
    # 1 fait mappé (cat_a) + 1 fait non mappé (FP baseline)
    r = _score(case, "baseline_a", ["R1", "UNMAPPED_RULE"], duration=0.1)
    assert r.detected == ["cat_a"]
    assert r.missed == ["cat_b"]
    assert r.recall == 0.5
    # précision baseline : détectés / (détectés + faits non mappés)
    assert r.precision == round(1 / 2, 3)


def test_recall_zero_is_never_none_when_expected():
    case = _case()
    r = _score(case, "system_c", [], duration=0.1)  # run sans aucune détection
    assert r.recall == 0.0, "un run vide doit compter comme recall 0, pas être exclu"
    assert r.missed == ["cat_a", "cat_b"]
    assert r.precision is None  # aucune claim → précision non définie (mais run COMPTE)


def test_unsupported_claims_count_in_precision():
    case = _case(forbidden={"bad_claim": ["invention"]})
    r = _score(case, "system_c", ["alpha trouvée", "une invention non supportée"], duration=0.1)
    assert r.detected == ["cat_a"]
    assert r.unsupported_claims == ["bad_claim"]
    assert r.false_positives == ["unsupported_bad_claim"]
    assert r.precision == round(1 / 2, 3)


def test_correct_inconclusive_is_distinct_from_missed():
    case = _case(
        expected={"explicit_insufficient": ["aucune donnée"]},
        inconclusive_category="explicit_insufficient",
    )
    r = _score(case, "system_c", ["aucune donnée disponible"], duration=0.1)
    assert r.detected == ["explicit_insufficient"]
    assert r.missed == []
    assert r.correct_inconclusive is True


def test_inconclusive_not_produced_counts_as_missed():
    case = _case(
        expected={"explicit_insufficient": ["aucune donnée"]},
        inconclusive_category="explicit_insufficient",
    )
    r = _score(case, "system_c", ["des faits sans rapport"], duration=0.1)
    assert r.detected == []
    assert r.missed == ["explicit_insufficient"]
    assert r.correct_inconclusive is False
    assert r.recall == 0.0


def test_eval_criteria_no_silence():
    case = _case(criteria=["no_silence"])
    silent = CaseResult(case_id="t", system="system_c", findings=[])
    silent.findings = [{"status": "needs_review", "severity_proposed": "medium", "evidence_refs": ["ev_1"]}]
    voiced = silent
    mute = CaseResult(case_id="t", system="system_c", findings=[])
    mute.findings = [{"status": "needs_review", "severity_proposed": "info", "evidence_refs": []}]
    assert eval_criteria(case, voiced)["no_silence"] is True
    assert eval_criteria(case, mute)["no_silence"] is False
    assert eval_criteria(case, CaseResult(case_id="t", system="system_c", findings=[]))["no_silence"] is False


def test_eval_criteria_multi_evidence_threshold():
    case = _case(criteria=["multi_evidence>=2"])
    r = CaseResult(case_id="t", system="system_c", multi_evidence_findings=1)
    assert eval_criteria(case, r)["multi_evidence>=2"] is False
    r2 = CaseResult(case_id="t", system="system_c", multi_evidence_findings=2)
    assert eval_criteria(case, r2)["multi_evidence>=2"] is True


def test_eval_criteria_unknown_fails_explicitly():
    case = _case(criteria=["critere_inexistant"])
    r = CaseResult(case_id="t", system="system_c")
    assert eval_criteria(case, r)["critere_inexistant"] is False


def test_render_report_includes_every_run():
    results = [
        CaseResult(case_id="c1", system="system_b", recall=0.0, silent=True,
                   final_status="paused", findings=[]),
        CaseResult(case_id="c1", system="system_c", recall=1.0, detected=["cat"], precision=1.0),
        CaseResult(case_id="c2", system="system_c", recall=0.0, error="TimeoutError: boom"),
    ]
    report = render_report(results)
    # Le run en pause ET le run en erreur figurent tous les deux, jamais exclus.
    assert "3 exécutions (aucune exclue)" in report or "aucune exclue" in report
    assert "runs silencieux: 1" in report
    assert "erreurs d'exécution: 1" in report
    assert "budget épuisé/partiel: 1" in report


def test_inconclusive_primacy_keyword_miss_is_recovered():
    """Le constat publié PRIME sur le wording : un run avec constat publié et refs valides
    ne doit pas échouer parce que les mots du modèle ne matchent pas les mots-clés (v3)."""
    from eval.runner import apply_inconclusive_primacy

    case = _case(
        expected={"explicit_insufficient": ["insuffisante"]},
        inconclusive_category="explicit_insufficient",
        criteria=["no_silence"],
    )
    out = CaseResult(case_id="t", system="system_c")
    out.findings = [{
        "status": "needs_review", "severity_proposed": "medium",
        "evidence_refs": ["ev_1", "ev_2"],
        "statement": "Les données d'avoirs ne figurent pas dans le périmètre collecté.",
    }]
    apply_inconclusive_primacy(case, out)
    assert out.detected == ["explicit_insufficient"]
    assert out.missed == []
    assert out.correct_inconclusive is True
    assert out.recall == 1.0


def test_inconclusive_primacy_requires_published_finding():
    from eval.runner import apply_inconclusive_primacy

    case = _case(
        expected={"explicit_insufficient": ["insuffisante"]},
        inconclusive_category="explicit_insufficient",
        criteria=["no_silence"],
    )
    out = CaseResult(case_id="t", system="system_c")  # aucun constat publié
    out.findings = []
    apply_inconclusive_primacy(case, out)
    assert out.detected == []
    assert out.correct_inconclusive is False
