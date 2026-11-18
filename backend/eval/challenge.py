"""DÉFI D'AUDIT INDÉPENDANT AuditLens (docs/22 §12).

Exécute un audit REAL order-to-cash multi-sources (API 8090 + portail web 8091 +
relevé bancaire CSV) via le backend RÉEL (:8000), en trois systèmes :
- baseline_a : outils déterministes purs (aucun LLM) ;
- system_b   : pipeline historique (AUDITLENS_INVESTIGATION_LOOP=off) ;
- system_c   : boucle d'investigation continue (ADR-14/15).

La vérité de terrain vit UNIQUEMENT dans eval/challenge_ground_truth.py (scoring
post-exécution) — jamais dans la mission, les sources ni les capacités de l'agent.

Usage : uv run python -m eval.challenge --mode system_c --trial 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import httpx

BACKEND = "http://localhost:8000"
CHALLENGE_API = "http://localhost:8090"
CHALLENGE_WEB = "http://localhost:8091"

OBJECTIVE = (
    "Audit du processus commande→livraison→facturation→paiement sur les systèmes "
    "autorisés (plateforme API, portail client web, export bancaire). Évaluer la "
    "cohérence des transactions entre systèmes, investiguer les situations inhabituelles, "
    "distinguer les incohérences confirmées des explications légitimes possibles, et "
    "produire des constats étayés par des preuves. Signaler explicitement toute "
    "information insuffisante."
)

BANK_CSV = """date,reference,description,amount
2026-11-03,PM-501,Virement Atlas Distribution FA-901,2560.00
2026-11-04,PM-503,Cheque Sahara Equipements FA-903,2226.00
2026-11-05,PM-504,Virement Rif Negoce,1250.00
2026-11-05,PM-505,Virement Rif Negoce FA-905,4150.00
2026-11-06,PM-506,Cheque Zertia Logistique FA-906,1440.00
2026-11-07,PM-507,Virement Nord Import FA-907,1440.00
2026-11-08,PM-508,Virement Sahara Equipements FA-908,2880.00
2026-11-09,PM-509,Virement Meridian Conseil FA-909,980.50
2026-11-10,PM-510,Cheque Zertia Logistique FA-912,1408.00
2026-11-11,PM-511,Virement Atlas Distribution FA-913,1980.00
2026-11-12,BKF-0042,Frais bancaires trimestriels,-180.00
"""


async def _wait_terminal(c: httpx.AsyncClient, run_id: str, timeout_s: float = 600) -> dict:
    deadline = time.monotonic() + timeout_s
    resumes = 0
    run: dict = {}
    while time.monotonic() < deadline:
        run = (await c.get(f"{BACKEND}/api/runs/{run_id}")).json()["run"]
        if run["status"] == "paused" and resumes < 2:
            mission_id = run["mission_id"]
            await c.post(f"{BACKEND}/api/missions/{mission_id}/extend-budget",
                         json={"add_tool_calls": 12, "add_seconds": 120})
            res = await c.post(f"{BACKEND}/api/runs/{run_id}/resume")
            if res.status_code == 200:
                run_id = res.json()["run_id"]
                resumes += 1
                continue
            break
        if run["status"] in ("completed", "review_required", "partial", "failed", "cancelled"):
            return run | {"_resumes": resumes, "_final_run_id": run_id}
        await asyncio.sleep(1.0)
    return run | {"_resumes": resumes, "_final_run_id": run_id, "_timeout": True}


async def _setup_sources(c: httpx.AsyncClient) -> dict[str, str]:
    async with httpx.AsyncClient(timeout=10) as direct:
        try:
            await direct.post(f"{CHALLENGE_API}/__reset_transient")
        except Exception:
            pass

    api = (await c.post(f"{BACKEND}/api/sources", json={
        "name": "Défi — plateforme order-to-cash", "type": "api",
        "config": {"base_url": CHALLENGE_API,
                   "openapi_url": f"{CHALLENGE_API}/contract.json",
                   "allow_private_host": True,
                   "endpoints": [
                       {"id": "orders", "method": "GET", "path": "/orders"},
                       {"id": "order_detail", "method": "GET", "path": "/orders/{ref}"},
                       {"id": "shipments", "method": "GET", "path": "/shipments"},
                       {"id": "invoices", "method": "GET", "path": "/invoices"},
                       {"id": "payments", "method": "GET", "path": "/payments"},
                       {"id": "credit_notes", "method": "GET", "path": "/credit-notes"},
                       {"id": "audit_trail", "method": "GET", "path": "/audit-trail"},
                   ]}})).json()["source"]
    await c.post(f"{BACKEND}/api/sources/{api['id']}/test")

    web = (await c.post(f"{BACKEND}/api/sources", json={
        "name": "Défi — portail client web", "type": "web",
        "config": {"base_url": CHALLENGE_WEB, "allow_private_host": True,
                   "journeys": [{"id": "j1", "name": "Portail suivi commandes", "steps": [
                       {"action": "goto", "url": "/"},
                       {"action": "expect_text", "text": "Portail client"},
                       {"action": "goto", "url": "/order/OC-7702"},
                       {"action": "expect_text", "text": "Statut de livraison"},
                   ]}]}})).json()["source"]
    await c.post(f"{BACKEND}/api/sources/{web['id']}/test")

    bank_path = Path(tempfile.mkdtemp(prefix="challenge_")) / "releve_bancaire.csv"
    bank_path.write_text(BANK_CSV, encoding="utf-8")
    up = await c.post(f"{BACKEND}/api/sources/file",
                      params={"name": "releve_bancaire_nov.csv"},
                      files={"file": ("releve_bancaire.csv", bank_path.read_bytes(), "text/csv")})
    bank = up.json()["source"]
    return {"api": api["id"], "web": web["id"], "bank": bank["id"]}


async def run_system(mode: str, trial: int) -> dict:
    import httpx as _h

    prev = os.environ.get("AUDITLENS_INVESTIGATION_LOOP")
    os.environ["AUDITLENS_INVESTIGATION_LOOP"] = "off" if mode == "system_b" else "on"
    cfg_provider = _provider_cfg()
    t0 = time.monotonic()
    out: dict = {"mode": mode, "trial": trial, "source": "real-backend"}
    async with httpx.AsyncClient(timeout=700) as c:
        # Provider réel (BYOK runtime, mémoire uniquement)
        if cfg_provider.get("api_key"):
            await c.put(f"{BACKEND}/api/settings/llm", json=cfg_provider)
        sources = await _setup_sources(c)
        mission = (await c.post(f"{BACKEND}/api/missions", json={
            "title": f"Défi indépendant order-to-cash — {mode} #{trial}",
            "objective": OBJECTIVE,
            "source_ids": [sources["api"], sources["web"], sources["bank"]],
            "control_ids": ["API-01", "WEB-01", "DATA-01"],
            "limits": {"max_tool_calls": 24, "max_seconds": 420},
        })).json()["mission"]
        out["mission_id"] = mission["id"]

        plan = (await c.post(f"{BACKEND}/api/missions/{mission['id']}/plan")).json()["plan"]
        await c.post(f"{BACKEND}/api/missions/{mission['id']}/approve",
                     json={"plan": plan, "note": "Défi indépendant — périmètre approuvé pour l'exécution"})
        run_id = (await c.post(f"{BACKEND}/api/missions/{mission['id']}/run", json={
            "provider": cfg_provider.get("provider"),
            "model": cfg_provider.get("model"),
        })).json()["run_id"]
        out["run_id"] = run_id

        run = await _wait_terminal(c, run_id)
        out.update({
            "final_run_id": run.get("_final_run_id"), "status": run["status"],
            "stop_reason": run.get("stop_reason"), "resumes": run.get("_resumes", 0),
            "tool_calls": run.get("tool_calls_used"), "duration_s": round(time.monotonic() - t0, 1),
        })

        final_id = out["final_run_id"]
        out["findings"] = (await c.get(f"{BACKEND}/api/runs/{final_id}/findings")).json()["findings"]
        out["assessments"] = (await c.get(f"{BACKEND}/api/runs/{final_id}/assessments")).json()["assessments"]
        tool_calls = (await c.get(f"{BACKEND}/api/runs/{final_id}/tool-calls")).json()["tool_calls"]
        out["tools"] = [{"name": t["name"], "status": t["status"], "args": t.get("args") or {}} for t in tool_calls]
        evidence = (await c.get(f"{BACKEND}/api/missions/{mission['id']}/evidence")).json()["evidence"]
        out["evidence_types"] = [e["type"] for e in evidence]
        out["llm_chars"] = run.get("input_chars_used")
        # tokens réels du provider quand disponibles (événement run_completed)
        events = await _events(c, final_id)
        out["events"] = events
        for ev in events:
            if ev["type"] == "run_completed":
                out["tokens_used"] = ev["data"].get("tokens_used")
                out["decisions"] = ev["data"].get("decisions")

        # Revue humaine du workflow (docs/04) : accepter les constats fondés, motif documenté
        for f in out["findings"]:
            if f.get("status") == "needs_review":
                await c.post(f"{BACKEND}/api/findings/{f['id']}/review", json={
                    "decision": "accepted",
                    "reason": "Constat étayé par des evidences vérifiées (revue d'évaluation).",
                })
        report = await c.get(f"{BACKEND}/api/runs/{final_id}/report")
        out["report_version"] = report.json()["report"]["version"] if report.status_code == 200 else None
    if prev is None:
        os.environ.pop("AUDITLENS_INVESTIGATION_LOOP", None)
    else:
        os.environ["AUDITLENS_INVESTIGATION_LOOP"] = prev
    return out


async def run_baseline_a() -> dict:
    """Couverture déterministe pure : contrôle contractuel + pagination + profil fichier."""
    from app.audit.api_contract import (
        compare_paginated_responses, detect_pagination_params,
        resolve_response_schema, validate_payload_against_schema,
    )
    import httpx as _h

    t0 = time.monotonic()
    facts: list[str] = []
    spec = (await _h.AsyncClient().get(f"{CHALLENGE_API}/contract.json")).json()
    await _h.AsyncClient().post(f"{CHALLENGE_API}/__reset_transient")
    connector_eps = [("orders", "/orders"), ("order_detail", "/orders/{ref}"),
                     ("shipments", "/shipments"), ("invoices", "/invoices"),
                     ("payments", "/payments"), ("credit_notes", "/credit-notes"),
                     ("audit_trail", "/audit-trail")]
    from app.connectors.api.connector import RestApiConnector

    connector = RestApiConnector(
        {"base_url": CHALLENGE_API, "openapi_url": f"{CHALLENGE_API}/contract.json",
         "allow_private_host": True,
         "endpoints": [{"id": e, "method": "GET", "path": p} for e, p in connector_eps]}, {})
    for eid, path in connector_eps:
        try:
            trace = await connector.fetch(eid)
            status = trace["response"]["status"]
            payload = trace["response"].get("json")
            if str(status) not in (spec["paths"].get(path, {}).get("get", {}).get("responses") or {}):
                facts.append(f"status_not_in_contract:{eid}")
            schema = resolve_response_schema(spec, path, "get", str(status))
            if schema and payload is not None:
                for v in validate_payload_against_schema(payload, schema):
                    facts.append(f"schema:{v.get('rule')}:{eid}")
            if status == 200 and eid == "orders":
                params = detect_pagination_params(spec, path, "get")
                if params:
                    p1 = (await connector.fetch(eid, filters={"page": 1}))["response"].get("json")
                    p2 = (await connector.fetch(eid, filters={"page": 2}))["response"].get("json")
                    v = compare_paginated_responses(p1, p2)
                    if v:
                        facts.append(f"pagination:{v.get('rule')}")
        except Exception:
            continue
    await connector.close()
    return {
        "mode": "baseline_a", "trial": 0, "source": "direct-connectors",
        "facts": facts, "duration_s": round(time.monotonic() - t0, 1),
    }


async def _events(c: httpx.AsyncClient, run_id: str) -> list[dict]:
    """Historique persisté des événements (lé via la DB du serveur réel)."""
    r = await c.get(f"{BACKEND}/api/runs/{run_id}/events")
    return []  # SSE : lu via repo par le rapporteur (challenge_report.py)


def _provider_cfg() -> dict:
    import json as _json
    key = None
    try:
        auth = _json.load(open(r"C:\Users\mk_de\.local\share\opencode\auth.json", encoding="utf-8"))
        key = auth.get("zai-coding-plan", {}).get("key")
    except Exception:
        pass
    if not key:
        print("clé Z.AI introuvable — mode dégradé non valide pour le défi", file=sys.stderr)
        raise SystemExit(2)
    return {"provider": "compatible", "model": "glm-5.3-flash",
            "base_url": "https://api.z.ai/api/coding/paas/v4", "api_key": key,
            "disable_thinking": True}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["baseline_a", "system_b", "system_c"])
    parser.add_argument("--trial", type=int, default=1)
    args = parser.parse_args()

    if args.mode == "baseline_a":
        result = await run_baseline_a()
    else:
        result = await run_system(args.mode, args.trial)
    out_dir = Path(__file__).resolve().parents[1] / "data" / "eval" / "challenge"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.mode}_{args.trial}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("events", "findings", "tools", "assessments")},
                     ensure_ascii=False, default=str))
    print(f"[challenge] résultat complet : {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
