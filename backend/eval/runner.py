"""Runner d'évaluation : Baseline A (déterministe pur) vs Système B (déterministe + agent LLM).

- Baseline A : exécute directement les outils déterministes (aucun LLM).
- Système B  : pipeline complet via l'application (plan IA → approbation → tools →
  findings), sur un répertoire de données isolé.
- La vérité de terrain n'est utilisée qu'après exécution, pour le scoring.

Métriques (docs/17) : TP / FP / FN, precision, recall, validité des evidences citées,
taux de succès des tools, durée, budget LLM (caractères d'entrée approximatifs).
Matching par mots-clés : approximatif par nature — documenté dans le rapport.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .ground_truth import ALL_CASES, EvalCase, generate_files_dataset


@dataclass
class CaseResult:
    case_id: str
    system: str  # baseline_a | system_b (pipeline) | system_c (boucle agentique)
    detected: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    precision: float | None = None
    recall: float | None = None
    tool_calls: int = 0
    tool_errors: int = 0
    duration_s: float = 0.0
    llm_input_chars: int = 0
    evidence_valid: bool | None = None
    rejected_findings: int = 0
    resumes: int = 0            # ADR-15 : reprises après pause budget (évaluation auto)
    redundant_calls: int = 0    # appels identiques répétés (signature name+args)
    multi_evidence_findings: int = 0  # constats appuyés sur ≥2 preuves distinctes
    reverification_observed: bool = False  # même objectif observé ≥2 fois avec résultats différents
    final_status: str | None = None
    # Comptabilité inclusive (docs/17 v4) : toute exécution tentée figure aux résultats.
    silent: bool = False              # aucun constat publié (hors info) — « silence » de l'agent
    correct_inconclusive: bool = False  # l'incertitude attendue a été produite (≠ anomalie manquée)
    criteria_results: dict = field(default_factory=dict)  # critère déclaré → bool
    findings: list[dict] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------- Baseline A


async def run_baseline_a(case: EvalCase) -> CaseResult:
    """Exécute uniquement les outils déterministes correspondant au cas (aucun LLM)."""
    t0 = time.monotonic()
    facts: list[str] = []  # faits déterministes (rule_ids / violation rules / flags)

    if case.source_kind == "file":
        import pandas as pd

        from app.audit.rules import evaluate_rule_set, get_rule_set

        dataset_dir = Path(tempfile.mkdtemp(prefix="al_eval_"))
        generate_files_dataset(dataset_dir, seed=9831 if case.case_id.endswith("dev") else 5521)
        df = pd.read_csv(dataset_dir / "orders.csv")
        ruleset = get_rule_set("rs_orders_v1")
        assert ruleset
        result = evaluate_rule_set(df, ruleset)
        for v in result.violations:
            facts.append(v.rule_id)

    elif case.source_kind == "api":
        from app.connectors.api.connector import RestApiConnector
        from app.audit.api_contract import (
            compare_paginated_responses,
            detect_pagination_params,
            resolve_response_schema,
            validate_payload_against_schema,
        )

        import httpx as _httpx

        # Couverture FIXE du déterminisme : uniquement des endpoints déclarés statiques.
        # Aucun appel dépendant (id découvert dans une liste) — c'est la limite mesurée.
        if case.case_id == "agent_undocumented":
            baseline_endpoints = [("products", "/products"), ("orders", "/orders"),
                                  ("invoices", "/invoices"), ("health", "/health")]
        elif case.case_id == "agent_multistep":
            baseline_endpoints = [("products", "/products"), ("orders", "/orders"),
                                  ("invoices", "/invoices")]
        else:
            baseline_endpoints = [("products", "/products"), ("orders", "/orders"),
                                  ("invoices", "/invoices"), ("order_detail_999", "/orders/999")]
        connector = RestApiConnector(
            {"base_url": "http://localhost:8080", "openapi_url": "http://localhost:8080/contract.json",
             "allow_private_host": True,
             "endpoints": [
                 {"id": eid, "method": "GET", "path": path} for eid, path in baseline_endpoints
             ]},
            {},
        )
        spec = (await _httpx.AsyncClient().get("http://localhost:8080/contract.json")).json()
        for eid, path in baseline_endpoints:
            try:
                trace = await connector.fetch(eid)
                status = trace["response"]["status"]
                if str(status) not in (spec["paths"].get(path, {}).get("get", {}).get("responses") or {}):
                    facts.append("status_not_in_contract")
                schema = resolve_response_schema(spec, path, "get", str(status))
                if schema and trace["response"].get("json") is not None:
                    for v in validate_payload_against_schema(trace["response"]["json"], schema):
                        facts.append(v["rule"])
                if status == 200:
                    params = detect_pagination_params(spec, path, "get")
                    if params:
                        p1 = (await connector.fetch(eid, filters={"page": 1}))["response"]["json"]
                        p2 = (await connector.fetch(eid, filters={"page": 2}))["response"]["json"]
                        v = compare_paginated_responses(p1, p2)
                        if v:
                            facts.append(v["rule"])
            except Exception:
                continue
        await connector.close()

    elif case.source_kind == "web":
        from app.connectors.web.connector import WebConnector

        connector = WebConnector({
            "base_url": "http://localhost:8081",
            "allow_private_host": True,
            "journeys": [{"id": "j1", "name": "Parcours paiement commande", "steps": [
                {"action": "goto", "url": "/checkout"},
                {"action": "expect_text", "text": "Panier"},
                {"action": "click", "selector": "#payer"},
                {"action": "goto", "url": "/pay", "expect_status": 200},
                {"action": "expect_text", "text": "Paiement accepté"},
            ]},
        ]}, {})
        result = await connector.run_journey("j1")
        if not result["all_passed"]:
            facts.append("journey_failed")
        if result["console_errors"]:
            facts.append("console_errors")
        await connector.close()

    elif case.source_kind == "odoo":
        facts.extend(await _baseline_odoo_facts())

    elif case.source_kind == "multi":
        # Couverture FIXE par source (aucune corrélation inter-sources — c'est la limite
        # mesurée) : réconciliation Odoo + lecture contractuelle des endpoints déclarés.
        facts.extend(await _baseline_odoo_facts())
        from app.connectors.api.connector import RestApiConnector

        connector = RestApiConnector(
            {"base_url": "http://localhost:8080", "openapi_url": "http://localhost:8080/contract.json",
             "allow_private_host": True,
             "endpoints": [{"id": "external_orders", "method": "GET", "path": "/external_orders"},
                            {"id": "products", "method": "GET", "path": "/products"}]},
            {},
        )
        spec = (await httpx.AsyncClient().get("http://localhost:8080/contract.json")).json()
        for eid, path in [("external_orders", "/external_orders"), ("products", "/products")]:
            try:
                trace = await connector.fetch(eid)
                status = trace["response"]["status"]
                if str(status) not in (spec["paths"].get(path, {}).get("get", {}).get("responses") or {}):
                    facts.append("status_not_in_contract")
            except Exception:
                continue
        await connector.close()

    out = _score(case, "baseline_a", facts, duration=time.monotonic() - t0)
    # Le déterministe pur ne PUBLIE pas de constats : silence structurel, critères évalués
    # sur données vides — l'inégalité des livrables fait partie de la comparaison (docs/17 v4).
    out.silent = True
    out.criteria_results = eval_criteria(case, out)
    return out


async def _baseline_odoo_facts() -> list[str]:
    """Lectures + réconciliation déterministe Odoo (partagées par les cas odoo/multi)."""
    from app.connectors.odoo.connector import OdooConnector
    from app.audit.odoo_reconciliation import reconcile

    c = OdooConnector({"url": "http://localhost:8069", "db": "TP_zakaria", "username": "auditlens"},
                      {"password": "auditlens2026"})
    orders = await c.read("sale.order", None, 100)
    invoices = await c.read("account.move", None, 100)
    stock = await c.read("stock.move", None, 100)
    purchases = await c.read("purchase.order", None, 100)
    await c.close()
    result = reconcile(
        orders=orders["records"], order_lines=orders["lines"],
        invoices=invoices["records"], invoice_lines=invoices["lines"],
        stock_moves=stock["records"], pickings=stock["pickings"],
        quants=stock["quants"], purchases=purchases["records"],
    )
    return [v["rule_id"] for v in result["violations"]]


# ---------------------------------------------------------------- Système B


async def run_system_b(case: EvalCase, provider_cfg: dict, scenario: str | None = None,
                       investigation: bool = True) -> CaseResult:
    """Pipeline complet via l'application (ASGI in-process, données isolées).

    investigation=True  → System C (boucle agentique ADR-14, défaut de l'application)
    investigation=False → Baseline B (pipeline historique reproduit via interrupteur)
    Le mock scripted utilise le scénario `investigate` sur les cas agentiques (les
    modèles réels ignorent `scenario` — leur boucle est pilotée par leurs décisions).
    """
    import os

    if scenario is None:
        scenario = ("investigate"
                    if provider_cfg.get("provider") == "mock" and case.case_id.startswith("agent_")
                    else "data_audit")
    prev = os.environ.get("AUDITLENS_INVESTIGATION_LOOP")
    os.environ["AUDITLENS_INVESTIGATION_LOOP"] = "on" if investigation else "off"
    os.environ["AUDITLENS_DATA_DIR"] = tempfile.mkdtemp(prefix="al_eval_b_")
    from app.main import app

    t0 = time.monotonic()
    detected_facts: list[str] = []
    findings: list[dict] = []
    error: str | None = None
    tool_calls = tool_errors = 0
    llm_chars = 0
    evidence_valid = True
    rejected_count = 0

    t0 = time.monotonic()
    detected_facts: list[str] = []
    findings: list[dict] = []
    error: str | None = None
    tool_calls = tool_errors = 0
    llm_chars = 0
    evidence_valid = True
    rejected_count = 0
    resumes = 0
    redundant_calls = 0
    multi_evidence = 0
    reverification = False
    final_status: str | None = None

    try:
        async with app.router.lifespan_context(app):
            # config LLM injectée dans le runtime in-process (mémoire, jamais persistée)
            if provider_cfg and provider_cfg.get("provider"):
                app.state.llm_runtime.update(provider_cfg)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://eval", timeout=300) as c:
                source_ids = await _create_sources(c, case)
                mission = (await c.post("/api/missions", json={
                    "title": f"Eval {case.case_id}",
                    "objective": case.objective,
                    "source_ids": source_ids,
                    "control_ids": _controls_for(case),
                })).json()["mission"]

                # Simulation de l'approbateur humain (docs/04 étape 4) : l'évaluation automatique
                # approuve le plan proposé — sinon les tools approved-tests restent bloquées par le
                # Policy Gate (comportement voulu, vérifié par l'incident d'évaluation du 13/11).
                plan = (await c.post(f"/api/missions/{mission['id']}/plan")).json()["plan"]
                await c.post(f"/api/missions/{mission['id']}/approve",
                             json={"plan": plan, "note": "évaluation automatique — plan approuvé sans supervision"})

                run_id = (await c.post(f"/api/missions/{mission['id']}/run", json={
                    "provider": provider_cfg.get("provider"), "model": provider_cfg.get("model"),
                    "scenario": scenario,
                })).json()["run_id"]

                # Boucle d'attente : les statuts PAUSED (épuisement budget, ADR-15) déclenchent
                # une extension de budget AUTOMATIQUE — notée ici comme simulation d'autorisation
                # humaine par l'évaluation, comme l'approbation de plan — puis une reprise depuis
                # le checkpoint (max 2 extensions, mesurées dans les métriques).
                deadline = time.monotonic() + 600
                while time.monotonic() < deadline:
                    run = (await c.get(f"/api/runs/{run_id}")).json()["run"]
                    final_status = run["status"]
                    if run["status"] == "paused" and resumes < 2:
                        await c.post(f"/api/missions/{mission['id']}/extend-budget",
                                     json={"add_tool_calls": 12, "add_seconds": 120})
                        res = await c.post(f"/api/runs/{run_id}/resume")
                        if res.status_code == 200:
                            run_id = res.json()["run_id"]
                            resumes += 1
                            continue
                        break
                    if run["status"] in ("completed", "review_required", "partial", "failed", "cancelled"):
                        break
                    await asyncio.sleep(0.5)

                tool_calls_list = (await c.get(f"/api/runs/{run_id}/tool-calls")).json()["tool_calls"]
                tool_calls = len(tool_calls_list)
                tool_errors = sum(1 for t in tool_calls_list if t["status"] in ("error", "unauthorized"))
                llm_chars = run.get("input_chars_used", 0) or 0
                seen_signatures: set[str] = set()
                for t in tool_calls_list:
                    sig = f"{t['name']}::{json.dumps(t.get('args') or {}, ensure_ascii=False, sort_keys=True, default=str)}"
                    if sig in seen_signatures:
                        redundant_calls += 1
                    seen_signatures.add(sig)

                findings = (await c.get(f"/api/runs/{run_id}/findings")).json()["findings"]
                published = [f for f in findings if f.get("status") != "rejected"]
                multi_evidence = sum(
                    1 for f in published if len(set(f.get("evidence_refs") or [])) >= 2
                )
                # Vérification temporelle réelle : même (source, endpoint) observé ≥2 fois
                # avec des statuts HTTP DIFFÉRENTS (ex. 503 puis 200 — comparaison dans le temps).
                evidences = (await c.get(f"/api/missions/{mission['id']}/evidence")).json()["evidence"]
                obs_by_target: dict[tuple, set] = {}
                for e in evidences:
                    s = e.get("summary") or {}
                    if s.get("endpoint_id") and s.get("http_status"):
                        key = (e.get("source_id"), s["endpoint_id"])
                        obs_by_target.setdefault(key, set()).add(s["http_status"])
                reverification = any(len(statuses) >= 2 for statuses in obs_by_target.values())
                # diagnostics : outils exécutés + types d'evidence (visibilité sur le pipeline)
                run_diag = {
                    "run_id": run_id, "status": run["status"], "stop_reason": run.get("stop_reason"),
                    "resumes": resumes,
                    "tools": [(t["name"], t["status"]) for t in tool_calls_list],
                    "evidence_types": [e["type"] for e in (await c.get(f"/api/runs/{run_id}/evidence")).json()["evidence"]],
                }
                print(f"[eval:{case.case_id}] diag: {json.dumps(run_diag, ensure_ascii=False)}", file=sys.stderr)
                # Validité indépendante des citations (re-vérification hors validateur) :
                # périmètre MISSION (imports initiaux inclus) ; les findings REJETÉS par le
                # validateur structurel ne comptent pas — ils ne sont pas publiés (docs/14),
                # mais leur nombre est rapporté pour transparence.
                ev_ids = {e["id"] for e in evidences}
                rejected_count = 0
                for f in findings:
                    if f.get("status") == "rejected":
                        rejected_count += 1
                        continue
                    if any(ref not in ev_ids for ref in f["evidence_refs"]):
                        evidence_valid = False

                for f in findings:
                    if f.get("status") == "rejected":
                        continue
                    if (f.get("severity_proposed") or "info") != "info":
                        detected_facts.append(_finding_text(f))
                assessments = (await c.get(f"/api/runs/{run_id}/assessments")).json()["assessments"]
                for a in assessments:
                    for obs in a.get("observations", []):
                        detected_facts.append(obs)
                    if a.get("result") in ("fail", "needs_review"):
                        detected_facts.append(f"{a['control_id']} {a['result']}")
                    elif a.get("result") == "insufficient_evidence":
                        # Insuffisance EXPLICITE = résultat d'audit valide (docs/03 règle 1) :
                        # comptée comme un fait de détection pour les cas « preuves manquantes ».
                        detected_facts.append(f"{a['control_id']} : preuves insuffisantes pour conclure (insufficient_evidence)")
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if prev is None:
            os.environ.pop("AUDITLENS_INVESTIGATION_LOOP", None)
        else:
            os.environ["AUDITLENS_INVESTIGATION_LOOP"] = prev

    out = _score(case, "system_c" if investigation else "system_b",
                 detected_facts, duration=time.monotonic() - t0)
    out.tool_calls, out.tool_errors = tool_calls, tool_errors
    out.llm_input_chars = llm_chars
    out.evidence_valid = evidence_valid
    out.findings = findings  # DOIT précéder apply_inconclusive_primacy (lit out.findings)
    out.error = error
    apply_inconclusive_primacy(case, out)
    out.rejected_findings = rejected_count
    out.resumes = resumes
    out.redundant_calls = redundant_calls
    out.multi_evidence_findings = multi_evidence
    out.reverification_observed = reverification
    out.final_status = final_status
    # Comptabilité inclusive : toute exécution tentée figure, y compris le silence.
    published_non_info = [
        f for f in findings
        if f.get("status") != "rejected" and (f.get("severity_proposed") or "info") != "info"
    ]
    out.silent = len(published_non_info) == 0
    out.criteria_results = eval_criteria(case, out)
    return out


async def _create_sources(c: httpx.AsyncClient, case: EvalCase) -> list[str]:
    # Cas à état temporel (503×2→200) : reset du fixture AVANT chaque exécution pour la
    # reproductibilité — sinon les essais successifs reçoivent du 200 immédiat.
    if case.case_id in ("agent_flaky", "agent_transient_persistent"):
        try:
            # client réseau DIRECT : `c` est un transport ASGI in-process qui ignore les hosts
            async with httpx.AsyncClient(timeout=5) as direct:
                await direct.post("http://localhost:8080/__reset_flaky")
        except Exception:
            pass  # service absent : les cas api échoueront de toute façon au test de source
    """Crée les sources du cas et retourne leurs ids (1+ sources — `multi` = Odoo + API)."""
    if case.source_kind == "file":
        dataset_dir = Path(tempfile.mkdtemp(prefix="al_eval_"))
        generate_files_dataset(dataset_dir, seed=9831 if case.case_id.endswith("dev") else 5521)
        content = (dataset_dir / "orders.csv").read_bytes()
        up = await c.post("/api/sources/file", params={"name": f"{case.case_id}.csv", "rule_set_id": "rs_orders_v1"},
                          files={"file": ("orders.csv", content, "text/csv")})
        return [up.json()["source"]["id"]]
    if case.source_kind == "api":
        endpoints = [
            {"id": "products", "method": "GET", "path": "/products"},
            {"id": "orders", "method": "GET", "path": "/orders"},
            {"id": "invoices", "method": "GET", "path": "/invoices"},
        ]
        if case.case_id in ("agent_multistep", "agent_contradiction"):
            # Endpoint paramétré : permet l'appel DÉPENDANT (id issu de la liste).
            endpoints.append({"id": "order_detail", "method": "GET", "path": "/orders/{order_id}"})
        if case.case_id == "agent_undocumented":
            # Vivant mais ABSENT du contrat (docs/08 : non documenté ≠ violation).
            endpoints.append({"id": "health", "method": "GET", "path": "/health"})
        if case.case_id == "agent_flaky":
            # A6 : 503 aux 2 premiers appels puis 200 (étude de stabilité, hors contrat).
            endpoints = [{"id": "products", "method": "GET", "path": "/products"},
                         {"id": "reports", "method": "GET", "path": "/reports"}]
        if case.case_id == "agent_transient_persistent":
            # Généralisation tenue hors développement : reports (503×2→200, hors contrat)
            # ET export (500 permanent, CONTRAT 200) — distinguer les deux comportements.
            endpoints = [{"id": "reports", "method": "GET", "path": "/reports"},
                         {"id": "export", "method": "GET", "path": "/export"}]
        if case.case_id == "api_test":
            endpoints.append({"id": "order_detail_999", "method": "GET", "path": "/orders/999"})
        src = await c.post("/api/sources", json={
            "name": "eval-api", "type": "api",
            "config": {"base_url": "http://localhost:8080",
                       "openapi_url": "http://localhost:8080/contract.json",
                       "allow_private_host": True,
                       "endpoints": endpoints}})
        await c.post(f"/api/sources/{src.json()['source']['id']}/test")
        return [src.json()["source"]["id"]]
    if case.source_kind == "web":
        journeys = [{"id": "j1", "name": "Parcours paiement commande", "steps": [
            {"action": "goto", "url": "/checkout"},
            {"action": "expect_text", "text": "Panier"},
            {"action": "click", "selector": "#payer"},
            {"action": "goto", "url": "/pay", "expect_status": 200},
            {"action": "expect_text", "text": "Paiement accepté"},
        ]}]
        if case.case_id == "agent_web_orders":
            # W3 : la page commandes plante — parcours déclaré, le choix d'exécution
            # reste celui de l'agent (aucune référence W3 dans l'objectif).
            journeys.append({"id": "j2", "name": "Consultation des commandes", "steps": [
                {"action": "goto", "url": "/orders"},
                {"action": "expect_text", "text": "Vos commandes"},
            ]})
        src = await c.post("/api/sources", json={
            "name": "eval-web", "type": "web",
            "config": {"base_url": "http://localhost:8081", "allow_private_host": True,
                       "journeys": journeys}})
        await c.post(f"/api/sources/{src.json()['source']['id']}/test")
        return [src.json()["source"]["id"]]
    if case.source_kind in ("odoo", "multi"):
        ids = []
        odoo = await c.post("/api/sources", json={
            "name": "eval-odoo", "type": "odoo",
            "config": {"url": "http://localhost:8069", "db": "TP_zakaria", "username": "auditlens"},
            "secrets": {"password": "auditlens2026"}})
        await c.post(f"/api/sources/{odoo.json()['source']['id']}/test")
        ids.append(odoo.json()["source"]["id"])
        if case.source_kind == "multi":
            # Flux « partenaire » externe (planté : S00002 → 999999.0) pour la corrélation
            # inter-sources — endpoint distinct de la boutique de test.
            api_src = await c.post("/api/sources", json={
                "name": "eval-api-partner", "type": "api",
                "config": {"base_url": "http://localhost:8080",
                           "openapi_url": "http://localhost:8080/contract.json",
                           "allow_private_host": True,
                           "endpoints": [{"id": "external_orders", "method": "GET", "path": "/external_orders"},
                                          {"id": "products", "method": "GET", "path": "/products"}]}})
            await c.post(f"/api/sources/{api_src.json()['source']['id']}/test")
            ids.append(api_src.json()["source"]["id"])
        return ids
    raise ValueError(f"source_kind inconnu: {case.source_kind}")


def _controls_for(case: EvalCase) -> list[str]:
    return {
        "file": ["DATA-01"],
        "api": ["API-01"],
        "web": ["WEB-01"],
        "odoo": ["ERP-01", "ERP-02", "CROSS-01"],
        "multi": ["ERP-01", "ERP-02", "CROSS-01", "API-01"],
    }[case.source_kind]


def _finding_text(f: dict) -> str:
    return " ".join([f.get("title", ""), f.get("statement", ""), *f.get("observations", [])]).lower()


def apply_inconclusive_primacy(case: EvalCase, out: CaseResult) -> None:
    """Le critère déclaratif PRIME sur le matching par mots-clés pour la conclusion
    d'incertitude (docs/17 v4) : un constat publié avec refs valides est la preuve réelle
    de l'insuffisance — le wording exact du modèle ne doit pas faire échouer la mesure."""
    if (case.inconclusive_category and "no_silence" in case.criteria
            and case.inconclusive_category not in out.detected
            and any(f.get("status") != "rejected"
                    and (f.get("severity_proposed") or "info") != "info"
                    for f in out.findings)):
        out.detected.append(case.inconclusive_category)
        out.missed = [c for c in out.missed if c != case.inconclusive_category]
        out.correct_inconclusive = True
        out.recall = round(len(out.detected) / len(case.expected), 3) if case.expected else None
        out.precision = round(len(out.detected) / max(1, len(out.detected) + len(out.false_positives)), 3)


# ---------------------------------------------------------------- scoring


def _score(case: EvalCase, system: str, facts: list[str], duration: float) -> CaseResult:
    blob = " || ".join(facts).lower()
    detected: list[str] = []
    for category, keywords in case.expected.items():
        if any(re.search(kw, blob, re.IGNORECASE) for kw in keywords):
            detected.append(category)

    # mapping Baseline A : rule_id → catégorie explicite (plus précis que keywords)
    if system == "baseline_a" and case.baseline_map:
        detected = sorted({case.baseline_map[f] for f in facts if f in case.baseline_map})

    # Claims interdits (docs/17) : affirmations non supportées par la vérité de terrain.
    # Ex. déclarer une violation sur un endpoint non documenté mais sain, ou une fraude
    # confirmée sans contradiction confirmée. Comptés comme FP pour tous les systèmes.
    unsupported = [
        cat for cat, keywords in (case.forbidden or {}).items()
        if any(re.search(kw, blob, re.IGNORECASE) for kw in keywords)
    ]

    missed = [c for c in case.expected if c not in detected]
    # L'inconclusif correct est DISTINCT d'une anomalie manquée (docs/17 v4).
    correct_inconclusive = bool(case.inconclusive_category and case.inconclusive_category in detected)
    fp_categories = [f"unmatched_fact_{i}" for i in range(max(0, len(facts) - len(detected)))] if system == "baseline_a" else []
    fp_categories += [f"unsupported_{c}" for c in unsupported]
    precision = round(len(detected) / max(1, len(detected) + len(fp_categories)), 3) if (detected or fp_categories) else None
    recall = round(len(detected) / len(case.expected), 3) if case.expected else None
    return CaseResult(
        case_id=case.case_id, system=system, detected=detected, missed=missed,
        false_positives=fp_categories, unsupported_claims=unsupported,
        precision=precision, recall=recall, duration_s=round(duration, 2),
        correct_inconclusive=correct_inconclusive,
    )


# ---------------------------------------------------------------- critères déclaratifs


def eval_criteria(case: EvalCase, result: CaseResult) -> dict:
    """Évalue les critères de succès DÉCLARATIFS du cas sur les données structurées du
    run (constats publiés, appels, evidences) — au-delà du matching par mots-clés.

    - no_silence       : l'agent a PUBLIÉ au moins un constat (le silence est un échec
                         pour les cas où la conclusion — même incertaine — est attendue).
    - multi_evidence>=N: au moins N constats appuyés sur ≥2 evidences distinctes.
    - reverification   : un même endpoint/tool a été observé ≥2 fois avec des résultats
                         DIFFÉRENTS dans le temps (preuve d'une vérification temporelle réelle).
    """
    published = [f for f in result.findings if f.get("status") != "rejected"]
    non_info = [f for f in published if (f.get("severity_proposed") or "info") != "info"]
    out: dict[str, bool] = {}

    for criterion in case.criteria:
        if criterion == "no_silence":
            out[criterion] = len(non_info) > 0
        elif criterion.startswith("multi_evidence>="):
            threshold = int(criterion.split(">=")[1])
            out[criterion] = result.multi_evidence_findings >= threshold
        elif criterion == "reverification":
            out[criterion] = result.reverification_observed
        else:
            out[criterion] = False  # critère inconnu = échec explicite, jamais accepté par défaut
    return out


async def run_all(case_ids: list[str], provider_cfg: dict, trials: int = 1,
                  systems: tuple = ("baseline_a", "system_b", "system_c")) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case_id in case_ids:
        case = ALL_CASES[case_id]
        if "baseline_a" in systems:
            results.append(await run_baseline_a(case))
        for _ in range(trials):
            if "system_b" in systems:
                # Baseline B : pipeline historique reproduit (boucle agentique désactivée).
                results.append(await run_system_b(case, provider_cfg, investigation=False))
            if "system_c" in systems:
                # System C : boucle d'investigation agentique (défaut applicatif).
                results.append(await run_system_b(case, provider_cfg, investigation=True))
    return results


def render_report(results: list[CaseResult]) -> str:
    lines = ["# Rapport d'évaluation AuditLens — Baseline A vs Baseline B vs System C", ""]
    lines.append("| Cas | Système | Détecté | Manqué | Précision* | Rappel | Claims non supportés | Tools | Erreurs tools | Findings rejetés | Durée (s) | LLM chars | Evidences valides |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        lines.append(
            f"| {r.case_id} | {r.system} | {', '.join(r.detected) or '—'} | {', '.join(r.missed) or '—'} "
            f"| {r.precision if r.precision is not None else '—'} | {r.recall if r.recall is not None else '—'} "
            f"| {', '.join(r.unsupported_claims) or '—'} "
            f"| {r.tool_calls or '—'} | {r.tool_errors if r.tool_calls else '—'} "
            f"| {r.rejected_findings if r.tool_calls else '—'} | {r.duration_s} "
            f"| {r.llm_input_chars or '—'} | {r.evidence_valid if r.evidence_valid is not None else '—'} |"
        )
    lines += [
        "",
        "*Précision approximative : le matching détection/vérité est par mots-clés (documenté, docs/17).",
        "FP = faits déterministes non mappés (Baseline A) + claims non supportés (tous systèmes).",
        "baseline_a = déterministe pur · system_b = pipeline historique (boucle désactivée) · system_c = boucle agentique (ADR-14).",
        "",
    ]
    # agrégats (moyenne ± écart-type sur les essais quand trials > 1)
    import statistics as _stats

    for system in ("baseline_a", "system_b", "system_c"):
        rs = [r for r in results if r.system == system]
        if not rs:
            continue
        # Comptabilité INCLUSIVE (docs/17 v4) : chaque exécution tentée compte, y compris
        # erreurs, timeouts, budget épuisé et runs silencieux — jamais d'exclusion.
        ps = [r.precision for r in rs if r.precision is not None]
        rcs = [r.recall for r in rs if r.recall is not None]
        success = sum(
            1 for r in rs
            if not r.missed and not r.unsupported_claims
            and all(r.criteria_results.values()) and (r.evidence_valid is not False)
        )
        agg = (
            f"**{system}** — {len(rs)} exécutions (aucune exclue) · "
            f"succès complet: {success}/{len(rs)} · "
            f"runs silencieux: {sum(1 for r in rs if r.silent)} · "
            f"inconclusifs corrects: {sum(1 for r in rs if r.correct_inconclusive)} · "
            f"budget épuisé/partiel: {sum(1 for r in rs if (r.final_status or '') in ('partial', 'paused'))} · "
            f"échecs tool: {sum(r.tool_errors for r in rs)} · "
            f"erreurs d'exécution: {sum(1 for r in rs if r.error)}"
        )
        if ps:
            agg += f" · precision (exécutions avec constats): {_stats.mean(ps):.2f}"
        if rcs:
            agg += f" · recall (toutes exécutions attendues): {_stats.mean(rcs):.2f}"
        unsup = sum(len(r.unsupported_claims) for r in rs)
        crit_total = sum(len(r.criteria_results) for r in rs)
        crit_ok = sum(1 for r in rs for v in r.criteria_results.values() if v)
        agg += (
            f" · claims non supportés: {unsup} · reprises: {sum(r.resumes for r in rs)} · "
            f"appels redondants: {sum(r.redundant_calls for r in rs)} · "
            f"constats multi-preuves: {sum(r.multi_evidence_findings for r in rs)} · "
            f"critères déclaratifs: {crit_ok}/{crit_total}."
        )
        lines.append(agg)
    return "\n".join(lines)


def write_report(results: list[CaseResult], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "report.md"
    report.write_text(render_report(results), encoding="utf-8")
    (out_dir / "metrics.json").write_text(
        json.dumps([r.__dict__ | {} for r in results], indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return report
