"""Slice verticale bout-en-bout (docs/18 étape 1) : upload → mission → run mock → findings → review.

Cas d'acceptation couverts : FAIL (anomalies), PASS (données conformes),
INCONCLUSIVE (preuves insuffisantes), UNAUTHORIZED (tool refusée par le backend),
rejet d'une evidence hallucinée, revue humaine, rapport.
"""

from __future__ import annotations

import pytest

from .conftest import run_mission, upload_csv


@pytest.mark.asyncio
async def test_fail_case_faulty_data_produces_finding_with_evidence(client, faulty_csv):
    up = await upload_csv(client, "orders_faulty.csv", faulty_csv)
    assert up["evidence_id"]
    result = await run_mission(client, up["source"]["id"], scenario="data_audit")
    assert result["run"]["status"] == "review_required"

    # Tool calls journalisés
    tc = (await client.get(f"/api/runs/{result['run_id']}/tool-calls")).json()["tool_calls"]
    names = [t["name"] for t in tc]
    assert "discover_source" in names and "data_profile" in names and "data_validate" in names

    # Evidence sourcées
    evs = (await client.get(f"/api/runs/{result['run_id']}/evidence")).json()["evidence"]
    ev_types = {e["type"] for e in evs}
    assert {"profile", "validation"} <= ev_types

    # Finding fondé sur la preuve de validation
    findings = (await client.get(f"/api/runs/{result['run_id']}/findings")).json()["findings"]
    assert len(findings) == 1
    f = findings[0]
    assert f["status"] == "needs_review"
    assert f["control_id"] == "DATA-01"
    validation_ev = next(e for e in evs if e["type"] == "validation")
    assert validation_ev["id"] in f["evidence_refs"]
    assert "violation" in f["statement"].lower() or "violation" in f["title"].lower()

    # Assessment déterministe : fail
    asm = (await client.get(f"/api/runs/{result['run_id']}/assessments")).json()["assessments"]
    assert asm[0]["control_id"] == "DATA-01"
    assert asm[0]["result"] == "fail"

    # Revue humaine : acceptation possible car preuve référencée
    r = await client.post(f"/api/findings/{f['id']}/review", json={"decision": "accepted", "reason": "vérifié ligne par ligne"})
    assert r.status_code == 200
    assert r.json()["finding"]["status"] == "accepted"

    # Rapport généré avec le constat accepté
    report = (await client.get(f"/api/runs/{result['run_id']}/report")).json()["report"]
    assert "accepted" in report["findings_included"] or f["id"] in report["findings_included"]
    assert "Rapport d'audit" in report["markdown"]


@pytest.mark.asyncio
async def test_pass_case_clean_data_no_finding(client, clean_csv):
    up = await upload_csv(client, "orders_clean.csv", clean_csv)
    result = await run_mission(client, up["source"]["id"], scenario="data_audit")
    assert result["run"]["status"] == "completed"

    findings = (await client.get(f"/api/runs/{result['run_id']}/findings")).json()["findings"]
    assert findings == []
    asm = (await client.get(f"/api/runs/{result['run_id']}/assessments")).json()["assessments"]
    assert asm[0]["result"] == "pass"
    assert asm[0]["evidence_refs"], "un pass doit citer ses evidences de validation"


@pytest.mark.asyncio
async def test_insufficient_evidence_never_passes(client, faulty_csv):
    """Scénario mock « insufficient » : l'agent déclare ne pas avoir les preuves → jamais `pass`."""
    up = await upload_csv(client, "orders_insuff.csv", faulty_csv)
    result = await run_mission(client, up["source"]["id"], scenario="insufficient")
    assert result["run"]["status"] == "completed"

    asm = (await client.get(f"/api/runs/{result['run_id']}/assessments")).json()["assessments"]
    assert asm[0]["result"] == "insufficient_evidence"
    findings = (await client.get(f"/api/runs/{result['run_id']}/findings")).json()["findings"]
    assert findings == []


@pytest.mark.asyncio
async def test_unauthorized_tool_blocked_by_backend(client, faulty_csv):
    """Une tool hors périmètre est refusée par le Policy Gate backend (docs/17 test d'acceptation)."""
    up = await upload_csv(client, "orders_unauth.csv", faulty_csv)
    result = await run_mission(client, up["source"]["id"], scenario="unauthorized")

    tc = (await client.get(f"/api/runs/{result['run_id']}/tool-calls")).json()["tool_calls"]
    blocked = [t for t in tc if t["status"] == "unauthorized"]
    assert blocked, "l'appel api_fetch_records sur une source fichier doit être journalisé comme unauthorized"
    assert blocked[0]["name"] == "api_fetch_records"

    # le run continue malgré le refus et collecte quand même les preuves autorisées
    evs = (await client.get(f"/api/runs/{result['run_id']}/evidence")).json()["evidence"]
    assert {"capabilities", "profile", "validation"} <= {e["type"] for e in evs}


@pytest.mark.asyncio
async def test_hallucinated_evidence_rejected_by_validator(client, faulty_csv):
    """Un finding qui cite une evidence inexistante est rejeté par le validateur (docs/03 frontière de confiance)."""
    up = await upload_csv(client, "orders_halluc.csv", faulty_csv)
    result = await run_mission(client, up["source"]["id"], scenario="hallucinated")

    findings = (await client.get(f"/api/runs/{result['run_id']}/findings")).json()["findings"]
    rejected = [f for f in findings if f["status"] == "rejected"]
    kept = [f for f in findings if f["status"] == "needs_review"]
    assert len(rejected) == 1
    assert "inexistantes" in rejected[0]["rejection_reason"] or "invalides" in rejected[0]["rejection_reason"]
    assert len(kept) == 1 and kept[0]["evidence_refs"]

    # un finding rejeté ne peut pas être revu
    r = await client.post(f"/api/findings/{rejected[0]['id']}/review", json={"decision": "accepted", "reason": "x"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_evidence_integrity_endpoint_and_scope(client, faulty_csv):
    up = await upload_csv(client, "orders_scope.csv", faulty_csv)
    # evidence d'import appartient au workspace d'imports (_imports) : accessible via mission ?
    evs_import = (await client.get(f"/api/missions/_imports/evidence")).json()["evidence"]
    assert evs_import

    # cross-project : une autre mission ne peut pas lire une evidence hors son périmètre via run
    r = await client.get(f"/api/evidence/{evs_import[0]['id']}", params={"mission_id": "mission_inexistante"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_events_history_and_health(client, faulty_csv):
    r = await client.get("/api/health")
    assert r.status_code == 200

    up = await upload_csv(client, "orders_events.csv", faulty_csv)
    result = await run_mission(client, up["source"]["id"], scenario="data_audit")
    # le flux SSE doit contenir les événements réels du run (historique puis stream)
    body = b""
    async with client.stream("GET", f"/api/runs/{result['run_id']}/events") as resp:
        assert resp.status_code == 200
        async for chunk in resp.aiter_bytes():
            body += chunk
            if b"run_completed" in body or b"stream_end" in body:
                break
    assert b"tool_started" in body
    assert b"evidence" in body
