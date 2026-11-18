"""Rapporteur du DÉFI INDÉPENDANT : scoring + classification des traces.

Usage : uv run python -m eval.challenge_report
Lit data/eval/challenge/*.json + les événements persistés du serveur réel
(data/auditlens.db), score contre challenge_ground_truth, distingue les actions
dirigées par le modèle des exécutions déterministes, et produit le rapport.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from pathlib import Path

from eval.challenge_ground_truth import EXPECTED, classify_facts

DIR = Path(__file__).resolve().parents[1] / "data" / "eval" / "challenge"
DB = Path(__file__).resolve().parents[1] / "data" / "auditlens.db"


def load_events(run_ids: list[str]) -> dict[str, list[dict]]:
    """Événements persistés du serveur réel (lecture directe SQLite, read-only)."""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out: dict[str, list[dict]] = {}
    try:
        for rid in run_ids:
            rows = conn.execute(
                "SELECT seq, run_id, type, at, data FROM run_events WHERE run_id=? ORDER BY seq",
                (rid,),
            ).fetchall()
            out[rid] = [
                {"seq": r["seq"], "run_id": r["run_id"], "type": r["type"], "at": r["at"],
                 "data": json.loads(r["data"])}
                for r in rows
            ]
    finally:
        conn.close()
    return out


def finding_text(f: dict) -> str:
    return " || ".join([f.get("title", ""), f.get("statement", ""),
                        *f.get("observations", [])])


def score(result: dict, events: list[dict]) -> dict:
    findings = [f for f in result.get("findings", []) if f.get("status") != "rejected"]
    non_info = [f for f in findings if (f.get("severity_proposed") or "info") != "info"]
    blob = " || ".join(finding_text(f) for f in non_info).lower()
    for a in result.get("assessments", []):
        blob += " || " + " || ".join(str(o) for o in a.get("observations", []))

    detected, forbidden, legit = classify_facts(blob)
    tools = result.get("tools", [])
    tool_errors = sum(1 for t in tools if t.get("status") in ("error", "unauthorized"))
    redundancies = 0
    seen: set[str] = set()
    for t in tools:
        sig = f"{t.get('name')}::{json.dumps(t.get('args') or {}, sort_keys=True, default=str)}"
        if sig in seen:
            redundancies += 1
        seen.add(sig)
    return {
        "mode": result.get("mode"), "trial": result.get("trial"),
        "status": result.get("status"), "stop_reason": result.get("stop_reason"),
        "run_id": result.get("final_run_id") or result.get("run_id"),
        "mission_id": result.get("mission_id"),
        "detected": detected,
        "missed": [c for c in EXPECTED if c not in detected],
        "forbidden_hit": forbidden, "legit_bonus": legit,
        "silent": len(non_info) == 0,
        "published_findings": len(non_info),
        "multi_evidence_findings": sum(
            1 for f in non_info if len(set(f.get("evidence_refs") or [])) >= 2),
        "tool_calls": len(tools), "tool_errors": tool_errors,
        "redundant_calls": redundancies,
        "duration_s": result.get("duration_s"),
        "tokens_used": result.get("tokens_used"),
        "decisions": result.get("decisions"),
        "resumes": result.get("resumes"),
        "evidence_types": result.get("evidence_types"),
    }


def classify_actions(events: list[dict]) -> dict:
    """Actions dirigées par le modèle (boucle) vs exécutions de couverture déterministe."""
    plan_tools: list[str] = []
    loop_tools: list[str] = []
    hypotheses: list[dict] = []
    revisions = 0
    decisions_seq: list[dict] = []
    warnings: list[str] = []
    for ev in events:
        d = ev["data"]
        if ev["type"] == "plan":
            plan_tools = [s.get("tool") for s in d.get("steps", [])]
        elif ev["type"] == "investigation_decision":
            decisions_seq.append({"turn": d.get("turn"), "decision": d.get("decision"),
                                  "tool": d.get("tool"),
                                  "rationale": str(d.get("rationale", ""))[:220]})
            if d.get("decision") == "call_tool" and d.get("tool"):
                loop_tools.append(d["tool"])
        elif ev["type"] in ("hypothesis_created", "hypothesis_updated"):
            if ev["type"] == "hypothesis_updated":
                revisions += 1
            hypotheses.append(d)
        elif ev["type"] in ("warning", "budget_warning"):
            warnings.append(str(d.get("message") or d.get("resources")))
    return {
        "plan_tools": plan_tools,
        "loop_tool_calls": loop_tools,
        "decisions_sequence": decisions_seq,
        "hypotheses": hypotheses,
        "hypothesis_revisions": revisions,
        "warnings": warnings[:6],
    }


def main() -> None:
    files = sorted(DIR.glob("*.json"))
    scored: list[dict] = []
    run_ids: list[str] = []
    raw: dict[str, dict] = {}
    for f in files:
        r = json.loads(f.read_text(encoding="utf-8"))
        key = f.stem
        raw[key] = r
        if not f.stem.startswith("baseline_a"):
            rid = r.get("final_run_id") or r.get("run_id")
            if rid:
                run_ids.append(rid)

    events_by_run = load_events(run_ids)

    lines = ["# Défi indépendant order-to-cash — résultats", ""]
    lines.append("| Mode | Essai | Statut | Détecté | Manqués | FP interdits | Silence | Constats | Multi-preuves | Tools | Err | Red | Durée |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")

    for key in sorted(raw):
        r = raw[key]
        if key.startswith("baseline_a"):
            blob = " || ".join(r.get("facts", []))
            detected, forbidden, _ = classify_facts(blob)
            scored.append({"mode": "baseline_a", "trial": 0, "status": "n/a",
                           "run_id": None, "detected": detected,
                           "missed": [c for c in EXPECTED if c not in detected],
                           "forbidden_hit": forbidden, "silent": False,
                           "published_findings": None, "multi_evidence_findings": None,
                           "tool_calls": 10, "tool_errors": None,
                           "redundant_calls": None, "duration_s": r.get("duration_s"),
                           "tokens_used": None, "resumes": 0})
            continue
        events = events_by_run.get(r.get("final_run_id") or r.get("run_id"), [])
        s = score(r, events)
        s["actions"] = classify_actions(events)
        scored.append(s)

    def short(cats: list[str]) -> str:
        renamed = [
            c.replace("payment_wrong_invoice_", "PM-").replace("over_shipment_", "SUR-LIVR ")
            .replace("invoice_without_shipment_", "FACT-SANS-EXP ")
            .replace("bank_vs_api_amount_", "BANQUE ")
            .replace("transient_", "TRANSITOIRE ")
            .replace("web_vs_api_status_", "WEB ")
            for c in cats
        ]
        return ", ".join(renamed) or "—"

    for s in scored:
        lines.append(
            f"| {s['mode']} | {s.get('trial')} | {s.get('status', '—')} | {short(s['detected'])} | {len(s['missed'])} "
            f"| {short(s.get('forbidden_hit', [])) or '—'} | {s.get('silent')} | {s.get('published_findings', '—')} "
            f"| {s.get('multi_evidence_findings', '—')} | {s.get('tool_calls', '—')} | {s.get('tool_errors', '—')} "
            f"| {s.get('redundant_calls', '—')} | {s.get('duration_s', '—')} |"
        )
    lines.append("")

    for s in scored:
        if s["mode"] == "baseline_a":
            continue
        a = s.get("actions", {})
        lines.append(f"## {s['mode']} #{s.get('trial')} — run {s.get('run_id')}")
        lines.append(f"- plan de couverture : {a.get('plan_tools')}")
        lines.append(f"- tools de boucle (dirigés par le modèle) : {a.get('loop_tool_calls') or '— (mode B : boucle désactivée)'}")
        if a.get("warnings"):
            lines.append(f"- alertes : {a.get('warnings')}")
        lines.append(f"- hypothèses ({a.get('hypothesis_revisions')} révision(s)) :")
        for h in a.get("hypotheses", []):
            lines.append(f"    - [{h.get('status')}] {h.get('id')}: {str(h.get('statement', ''))[:220]}")
        if a.get("decisions_sequence"):
            lines.append("- décisions de la boucle :")
            for d in a.get("decisions_sequence", []):
                lines.append(f"    - tour {d.get('turn')}: {d.get('decision')} {d.get('tool') or ''} — {d.get('rationale', '')}")
        lines.append("")

    out = DIR / "REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:12]))
    print(f"[challenge_report] rapport complet : {out}")


if __name__ == "__main__":
    main()
