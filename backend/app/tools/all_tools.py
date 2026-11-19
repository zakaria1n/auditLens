"""Implémentation des tools V1 (docs/05) — catalogue complet, read-only.

Chaque handler : valide les entrées (via modèles Pydantic du registry), exécute
via le connecteur, crée ses Evidence immuables, retourne un ToolResult dont le
preview est minimisé (aucun secret, pas de dump brut vers le LLM).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from ..audit.controls import CONTROL_CATALOG, control_to_dict, get_control
from ..audit.rules import RULE_SETS, evaluate_rule_set, get_rule_set, profile_dataframe
from ..connectors.files.connector import FileConnector
from ..connectors.ssrf import validate_url
from ..core.errors import EvidenceNotFound
from ..core.ids import new_id
from ..core.redact import redact
from .odoo_generic_tools import (
    OdooAggregateInput,
    OdooDescribeModelInput,
    OdooFollowRelationInput,
    OdooListModelsInput,
    OdooQueryRecordsInput,
    tool_odoo_aggregate_records,
    tool_odoo_describe_model,
    tool_odoo_follow_relation,
    tool_odoo_list_models,
    tool_odoo_query_records,
    _validate_domain as _odoo_validate_domain,
)
from ..harness.contracts import ToolContext, ToolResult
from ..models import PermissionLevel, SourceType

# ==========================================================================
# Modèles d'entrée (validation schéma — docs/05 Policy Gate)
# ==========================================================================


class DiscoverSourceInput(BaseModel):
    source_id: str


class OdooReadInput(BaseModel):
    source_id: str
    date_from: str | None = None
    date_to: str | None = None
    limit: int = Field(default=100, ge=1, le=500)


class ApiInspectInput(BaseModel):
    source_id: str
    endpoint_ids: list[str] = Field(default_factory=list)


class ApiFetchInput(BaseModel):
    source_id: str
    endpoint_id: str
    filters: dict[str, str] = Field(default_factory=dict)


class WebJourneyInput(BaseModel):
    source_id: str
    journey_id: str


class DataProfileInput(BaseModel):
    evidence_id: str


class DataValidateInput(BaseModel):
    evidence_id: str
    rule_set_id: str


class EvidenceJoinInput(BaseModel):
    evidence_ids: list[str] = Field(min_length=2, max_length=2)
    left_key: str
    right_key: str
    label: str | None = None


class ControlDefInput(BaseModel):
    control_id: str


class EvidenceExcerptInput(BaseModel):
    evidence_id: str
    row_start: int = Field(default=0, ge=0)
    row_end: int = Field(default=5, ge=1, le=50)


class DataExploreInput(BaseModel):
    evidence_id: str
    spec: dict = Field(
        description=(
            "Spécification d'exploration TYPÉE : fields (projection), filter "
            "[{field, op: eq|ne|gt|gte|lt|lte|contains|in|not_null, value}], sort "
            "[{field, dir}], group_by + aggregate {op: count|sum|avg|min|max, field}, "
            "compare {left_field, right_field, op}, limit (<=50). Calculs déterministes."
        )
    )


class CorrelateRecordsInput(BaseModel):
    evidence_ids: list[str] = Field(min_length=2, max_length=2)
    left_key: str
    right_key: str
    compare_fields: list[dict] = Field(
        default_factory=list,
        description="champs comparés numériquement quand un lien existe : [{left, right}]",
    )
    normalize: bool = Field(
        default=False,
        description="correspondance exacte après normalisation (casse/espaces) => statut uncertain",
    )
    label: str | None = None


class EvidenceSearchInput(BaseModel):
    evidence_id: str
    query: str = Field(min_length=1, max_length=200, description="texte ou identifiant à rechercher (insensible à la casse)")
    field: str | None = Field(default=None, description="restreindre la recherche à un champ précis")
    max_hits: int = Field(default=10, ge=1, le=20)


# ==========================================================================
# Helpers
# ==========================================================================


async def _load_evidence(ctx: ToolContext, evidence_id: str):
    """Charge une evidence en vérifiant qu'elle appartient à la mission (scope docs/13)."""
    ev = await ctx.repo.get_evidence_meta(evidence_id, ctx.mission.id)
    if ev is None:
        raise EvidenceNotFound(f"evidence inconnue ou hors mission: {evidence_id}")
    full = ctx.store.load(ev)
    return ev, full


def _records_from_payload(full: dict) -> list[dict]:
    payload = full.get("payload", {})
    return payload.get("records") or []


# ==========================================================================
# Handlers
# ==========================================================================


async def tool_discover_source(ctx: ToolContext, args: dict) -> ToolResult:
    source = ctx.source
    assert source is not None
    connector = ctx.connectors.build(source)
    try:
        caps = await connector.discover()
        ok, msg = await connector.test_connection()
    finally:
        await connector.close()
    evidence_id = new_id("evidence")
    ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=source.id,
        type_="capabilities", title=f"Capabilities — {source.name}",
        payload={"capabilities": caps, "connection": {"ok": ok, "message": msg}},
        provenance={"tool": "discover_source", "source_type": source.type.value},
        summary={"source_type": source.type.value, "connection_ok": ok},
        evidence_id=evidence_id,
    )
    await ctx.repo.create_evidence_meta(ev)
    return ToolResult(
        tool_call_id="", tool="discover_source", source_id=source.id, status="success" if ok else "error",
        evidence_ids=[ev.id], record_count=None,
        preview={"connection": {"ok": ok, "message": msg}, "capabilities_summary": _caps_summary(caps)},
        error=None if ok else msg,
        warnings=[] if ok else ["connection_failed"],
    )


def _caps_summary(caps: dict) -> dict:
    if "models" in caps:  # odoo
        return {
            "type": "odoo",
            "installed_modules_count": len(caps.get("installed_modules", [])),
            "models": {
                m: {"available": v.get("available"), "record_count": v.get("record_count")}
                for m, v in caps.get("models", {}).items()
            },
        }
    if "journeys" in caps:  # web
        return {"type": "web", "journeys": caps["journeys"]}
    if "endpoints" in caps:  # api
        return {"type": "api", "endpoints": caps["endpoints"], "openapi": caps.get("openapi")}
    if "columns" in caps:  # file
        return {"type": "file", "rows": caps.get("rows"), "columns": [c["name"] for c in caps["columns"]]}
    return caps


async def _tool_odoo_read(ctx: ToolContext, args: dict, model: str, tool_name: str) -> ToolResult:
    source = ctx.source
    assert source is not None
    connector = ctx.connectors.build(source)
    try:
        data = await connector.read(model, {"from": args.get("date_from"), "to": args.get("date_to")}, args.get("limit", 100))
    finally:
        await connector.close()
    evidence_id = new_id("evidence")
    labels = {
        "sale.order": "Commandes de vente",
        "account.move": "Factures",
        "stock.move": "Mouvements de stock",
        "stock.picking": "Livraisons",
        "purchase.order": "Achats",
    }
    ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=source.id,
        type_="record_set", title=f"{labels.get(model, model)} — {source.name}",
        payload={
            "records": data["records"], "lines": data.get("lines", []),
            "pickings": data.get("pickings", []),
            "quants": data.get("quants", []),
            "model": model, "date_range": data["date_range"], "fields_limit": data["limit"],
        },
        provenance={"tool": tool_name, "connector": "odoo", "model": model},
        record_count=data["record_count"],
        summary={
            "model": model, "record_count": data["record_count"], "date_range": data["date_range"],
            "fields": sorted({k for r in data["records"] for k in r})[:20],
            # échantillon borné + redacté : le LLM peut corréler les valeurs sans dump complet (docs/06/09)
            "sample": redact(data["records"][:5]),
            "lines_sample": redact(data.get("lines", [])[:8]),
            "pickings_sample": redact(data.get("pickings", [])[:5]),
            "quants_sample": redact(data.get("quants", [])[:5]) if data.get("quants") else None,
            "sample_note": f"premiers {min(5, len(data['records']))} enregistrements (+ lignes) sur {len(data['records'])} — get_evidence_excerpt pour plus de détails",
        },
        evidence_id=evidence_id,
    )
    await ctx.repo.create_evidence_meta(ev)
    preview_records = data["records"][:3]
    return ToolResult(
        tool_call_id="", tool=tool_name, source_id=source.id, status="success",
        evidence_ids=[ev.id], record_count=data["record_count"],
        preview={
            "model": model, "record_count": data["record_count"], "date_range": data["date_range"],
            "sample": redact(preview_records),
        },
        warnings=data.get("warnings", []),
    )


async def tool_odoo_read_orders(ctx: ToolContext, args: dict) -> ToolResult:
    return await _tool_odoo_read(ctx, args, "sale.order", "odoo_read_orders")


async def tool_odoo_read_invoices(ctx: ToolContext, args: dict) -> ToolResult:
    return await _tool_odoo_read(ctx, args, "account.move", "odoo_read_invoices")


async def tool_odoo_read_stock(ctx: ToolContext, args: dict) -> ToolResult:
    return await _tool_odoo_read(ctx, args, "stock.move", "odoo_read_stock")


async def tool_odoo_read_purchases(ctx: ToolContext, args: dict) -> ToolResult:
    return await _tool_odoo_read(ctx, args, "purchase.order", "odoo_read_purchases")


class OdooCrossCheckInput(BaseModel):
    evidence_ids: list[str] = Field(min_length=3, max_length=4,
                                    description="evidences odoo : commandes, factures, stock (+ achats optionnel)")


async def tool_odoo_cross_check(ctx: ToolContext, args: dict) -> ToolResult:
    """Réconciliation DÉTERMINISTE des evidences Odoo collectées (aucun accès direct Odoo ici).

    Charge commandes/factures/stock (+ achats optionnels) depuis les preuves du run,
    applique les règles de docs/11 via app.audit.odoo_reconciliation.reconcile et
    produit une evidence `odoo_cross_check` : violations confirmed/suspicious traçables.
    """
    from ..audit.odoo_reconciliation import reconcile

    loaded: dict[str, dict] = {}
    for eid in args["evidence_ids"]:
        ev, full = await _load_evidence(ctx, eid)
        payload = full.get("payload") or {}
        loaded[ev.id] = {
            "type": ev.type, "title": ev.title, "model": payload.get("model"),
            "records": payload.get("records") or [],
            "lines": payload.get("lines") or [],
            "pickings": payload.get("pickings") or [],
            "quants": payload.get("quants") or [],
        }

    orders_ev = next((d for d in loaded.values() if d["model"] == "sale.order"), None)
    invoices_ev = next((d for d in loaded.values() if d["model"] == "account.move"), None)
    stock_ev = next((d for d in loaded.values() if d["model"] == "stock.move"), None)
    purchases_ev = next((d for d in loaded.values() if d["model"] == "purchase.order"), None)

    if not orders_ev or not invoices_ev or not stock_ev:
        return ToolResult(
            tool_call_id="", tool="odoo_cross_check", status="insufficient_evidence",
            error="odoo_cross_check requiert les evidences odoo_read_orders, odoo_read_invoices et odoo_read_stock",
            preview={"provided": {k: v["model"] for k, v in loaded.items()}},
        )

    result = reconcile(
        orders=orders_ev["records"],
        order_lines=orders_ev["lines"],
        invoices=invoices_ev["records"],
        invoice_lines=invoices_ev["lines"],
        stock_moves=stock_ev["records"],
        pickings=stock_ev["pickings"],
        quants=stock_ev["quants"],
        purchases=purchases_ev["records"] if purchases_ev else None,
    )

    evidence_id = new_id("evidence")
    source_ids = sorted({await _source_of(ctx, eid) for eid in args["evidence_ids"] if await _source_of(ctx, eid)}, key=str)
    ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id,
        source_id=source_ids[0] if source_ids else None,
        type_="odoo_cross_check", title="Réconciliation Odoo — commandes/factures/stock",
        payload={"reconciliation": result, "source_evidence_ids": list(loaded.keys())},
        provenance={"tool": "odoo_cross_check", "rules": "docs/11 ERP-01/ERP-02/CROSS-01",
                    "source_evidence": list(loaded.keys())},
        record_count=len(result["violations"]),
        summary={
            "confirmed": result["stats"]["confirmed"],
            "suspicious": result["stats"]["suspicious"],
            "stats": result["stats"],
            "violations": result["violations"][:12],
            "observations": result["observations"][:6],
            "limitations": result["limitations"],
            "source_evidence_ids": list(loaded.keys()),
        },
        evidence_id=evidence_id,
    )
    await ctx.repo.create_evidence_meta(ev)
    return ToolResult(
        tool_call_id="", tool="odoo_cross_check",
        status="success",
        source_id=source_ids[0] if source_ids else None,
        evidence_ids=[ev.id], record_count=len(result["violations"]),
        preview={
            "confirmed": result["stats"]["confirmed"],
            "suspicious": result["stats"]["suspicious"],
            "violations": result["violations"][:12],
            "observations": result["observations"][:6],
            "limitations": result["limitations"],
        },
        warnings=[l["message"] for l in result["limitations"]],
    )


async def _source_of(ctx: ToolContext, evidence_id: str) -> str | None:
    ev = await ctx.repo.get_evidence_meta(evidence_id, ctx.mission.id)
    return ev.source_id if ev else None


async def tool_api_inspect_contract(ctx: ToolContext, args: dict) -> ToolResult:
    """Vérification contractuelle déterministe (docs/08, docs/11 API-01) :
    statuts HTTP + validation schéma OpenAPI (types, required, nested) + sonde de pagination.

    Un comportement non documenté n'est PAS une violation : noté `not_documented` (docs/08)."""
    import json as _json

    import httpx

    from ..audit.api_contract import (
        compare_paginated_responses,
        detect_pagination_params,
        resolve_response_schema,
        validate_payload_against_schema,
    )

    source = ctx.source
    assert source is not None
    connector = ctx.connectors.build(source)
    spec: dict | None = None
    try:
        caps = await connector.discover()
        endpoint_ids = args.get("endpoint_ids") or [e["id"] for e in caps.get("endpoints", [])]

        # Contrat : openapi_url déclaré dans la config source (contrat écrit, pas l'auto-doc).
        spec_url = source.config.get("openapi_url")
        if spec_url:
            try:
                validate_url(str(spec_url), connector.allowed_hosts, allow_private=connector.allow_private)
                async with httpx.AsyncClient(timeout=connector.timeout, follow_redirects=False) as client:
                    spec_resp = await client.get(spec_url)
                if spec_resp.status_code == 200:
                    spec = spec_resp.json()
            except Exception:
                spec = None

        checks: list[dict] = []
        violations: list[dict] = []
        for eid in endpoint_ids[:10]:
            endpoint_cfg = connector._endpoint(eid) or {}
            method = str(endpoint_cfg.get("method", "GET")).upper()
            path = str(endpoint_cfg.get("path", ""))
            status_ok = True
            try:
                trace = await connector.fetch(eid, filters={})
                status = trace["response"]["status"]
                payload = trace["response"].get("json")
                status_ok = 200 <= status < 400
                check: dict = {
                    "endpoint_id": eid, "path": path, "method": method,
                    "status_http": status, "ok": status_ok,
                    "latency_ms": trace["response"]["latency_ms"],
                    "json_present": payload is not None,
                }

                # --- contrat documenté ? ---
                documented_statuses: list[str] = []
                if spec:
                    node = ((spec.get("paths") or {}).get(path) or {}).get(method.lower()) or {}
                    documented_statuses = sorted((node.get("responses") or {}).keys())
                check["documented_statuses"] = documented_statuses or None

                if not spec or not documented_statuses:
                    check["contract"] = "not_documented"  # pas une violation (docs/08)
                else:
                    check["contract"] = "documented"
                    # 1. statut hors contrat (ex. 500 quand seul 200/404 documentés)
                    if str(status) not in documented_statuses:
                        violations.append({
                            "endpoint_id": eid, "path": path, "rule": "status_not_in_contract",
                            "kind": "contract_violation", "severity_hint": "medium",
                            "expected": {"status": documented_statuses},
                            "actual": {"status": status},
                            "message": f"statut HTTP {status} absent des réponses documentées ({', '.join(documented_statuses)})",
                        })
                    # 2. validation schéma de la réponse (seulement si le statut observé est documenté)
                    schema = resolve_response_schema(spec, path, method, str(status))
                    if schema and payload is not None:
                        sv = validate_payload_against_schema(payload, schema)
                        for v in sv:
                            v.update({"endpoint_id": eid, "path": path, "kind": "contract_violation", "severity_hint": "medium"})
                        violations.extend(sv)
                    elif schema is None and payload is not None:
                        check["schema"] = "not_documented"
                    # 3. sonde de pagination (GET + paramètres de pagination déclarés)
                    if method == "GET" and status_ok and spec:
                        page_params = detect_pagination_params(spec, path, method)
                        check["pagination_params"] = page_params or None
                        if page_params:
                            try:
                                p1 = await connector.fetch(eid, filters={"page": 1})
                                p2 = await connector.fetch(eid, filters={"page": 2})
                                if p1["response"]["status"] == 200 and p2["response"]["status"] == 200:
                                    v = compare_paginated_responses(p1["response"].get("json"), p2["response"].get("json"))
                                    if v:
                                        v.update({"endpoint_id": eid, "path": path, "kind": "contract_violation", "severity_hint": "medium"})
                                        violations.append(v)
                            except Exception:
                                pass  # sonde non conclurante : pas une violation
            except Exception as exc:  # noqa: BLE001
                checks.append({"endpoint_id": eid, "path": path, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
                continue
            checks.append(check)
        openapi = caps.get("openapi")
    finally:
        await connector.close()

    evidence_id = new_id("evidence")
    ok_count = sum(1 for c in checks if c.get("ok"))
    confirmed_violations = [v for v in violations if v.get("rule") != "max_violations_truncated"]
    # Observabilité des échecs par endpoint (docs/06) : sans ceci, un 5xx sur un endpoint
    # non documenté serait invisible pour la boucle d'investigation (résumé = compteurs seuls).
    failed_endpoints = [
        {"endpoint_id": c.get("endpoint_id"), "path": c.get("path"),
         "status_http": c.get("status_http"), "error": (c.get("error") or "")[:160]}
        for c in checks if not c.get("ok")
    ][:10]
    ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=source.id,
        type_="contract_check", title=f"Contrat API — {source.name}",
        payload={"checks": checks, "violations": violations, "openapi": openapi,
                 "spec_source": source.config.get("openapi_url")},
        provenance={"tool": "api_inspect_contract", "connector": "api"},
        record_count=len(checks),
        summary={
            "endpoints_checked": len(checks), "ok": ok_count,
            "openapi_available": openapi is not None and "error" not in (openapi or {}),
            "contract_violations": len(confirmed_violations),
            "violations_sample": confirmed_violations[:8],
            "failed_endpoints": failed_endpoints,
        },
        evidence_id=evidence_id,
    )
    await ctx.repo.create_evidence_meta(ev)
    status = "success" if ok_count == len(checks) and checks else "partial"
    return ToolResult(
        tool_call_id="", tool="api_inspect_contract", source_id=source.id, status=status,
        evidence_ids=[ev.id], record_count=len(checks),
        preview={"checks": checks, "violations": violations[:10], "openapi": openapi,
                 "violation_count": len(confirmed_violations)},
        warnings=[] if status == "success" else ["endpoints en échec — voir contract_check"],
    )


async def tool_api_fetch_records(ctx: ToolContext, args: dict) -> ToolResult:
    source = ctx.source
    assert source is not None
    connector = ctx.connectors.build(source)
    try:
        trace = await connector.fetch(args["endpoint_id"], filters=args.get("filters", {}))
    finally:
        await connector.close()

    resp = trace["response"]
    records: list | None = None
    json_data = resp.get("json")
    if isinstance(json_data, list):
        records = json_data
    elif isinstance(json_data, dict):
        for key in ("items", "data", "results", "records"):
            if isinstance(json_data.get(key), list):
                records = json_data[key]
                break

    evidence_id = new_id("evidence")
    if records is not None:
        ev_type, title = "record_set", f"API {args['endpoint_id']} — {source.name}"
        payload: dict[str, Any] = {
            "records": records[:500], "endpoint_id": args["endpoint_id"],
            "http_status": resp["status"],
        }
        record_count = len(records)
    else:
        ev_type, title = "http_trace", f"Trace HTTP {args['endpoint_id']} — {source.name}"
        payload = {"trace": {k: v for k, v in trace.items() if k != "observed_at_latency"}}
        record_count = None

    ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=source.id,
        type_=ev_type, title=title, payload=payload,
        provenance={"tool": "api_fetch_records", "connector": "api", "endpoint_id": args["endpoint_id"]},
        record_count=record_count,
        summary={"endpoint_id": args["endpoint_id"], "http_status": resp["status"],
                 "record_count": record_count, "latency_ms": resp["latency_ms"],
                 "sample": redact((records or [])[:5]) if records else None},
        evidence_id=evidence_id,
    )
    await ctx.repo.create_evidence_meta(ev)
    http_ok = 200 <= resp["status"] < 400
    return ToolResult(
        tool_call_id="", tool="api_fetch_records", source_id=source.id,
        status="success" if http_ok else "error",
        evidence_ids=[ev.id], record_count=record_count,
        preview={"endpoint_id": args["endpoint_id"], "http_status": resp["status"],
                 "record_count": record_count, "latency_ms": resp["latency_ms"],
                 "body_excerpt": resp.get("body_excerpt", "")[:500]},
        error=None if http_ok else f"HTTP {resp['status']}",
    )


async def tool_web_run_journey(ctx: ToolContext, args: dict) -> ToolResult:
    source = ctx.source
    assert source is not None
    connector = ctx.connectors.build(source)
    try:
        result = await connector.run_journey(args["journey_id"])
    finally:
        await connector.close()

    evidence_id = new_id("evidence")
    failed_steps = [s for s in result["steps"] if s.get("status") != "pass"]
    ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=source.id,
        type_="web_trace", title=f"Parcours {result['journey_name']} — {source.name}",
        payload={"trace": result},
        provenance={"tool": "web_run_journey", "connector": "web", "journey_id": args["journey_id"]},
        record_count=len(result["steps"]),
        summary={"journey_id": args["journey_id"], "all_passed": result["all_passed"],
                 "steps": len(result["steps"]), "failed_steps": len(failed_steps),
                 "console_errors": len(result["console_errors"])},
        attachments={
            # le store place chaque pièce dans {evidence_id}_files/ — nom de fichier simple ici
            "trace.json": json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
        },
        evidence_id=evidence_id,
    )
    await ctx.repo.create_evidence_meta(ev)
    return ToolResult(
        tool_call_id="", tool="web_run_journey", source_id=source.id,
        status="success" if result["all_passed"] else "partial",
        evidence_ids=[ev.id], record_count=len(result["steps"]),
        preview={"journey_id": args["journey_id"], "all_passed": result["all_passed"],
                 "steps": result["steps"], "console_errors": result["console_errors"][:10]},
        warnings=[] if result["all_passed"] else ["étapes en échec — voir web_trace"],
    )


async def tool_data_profile(ctx: ToolContext, args: dict) -> ToolResult:
    ev, full = await _load_evidence(ctx, args["evidence_id"])
    path = (full.get("payload") or {}).get("path")
    if not path:
        return ToolResult(tool_call_id="", tool="data_profile", status="error",
                          error=f"evidence {ev.id} n'est pas un fichier source (type={ev.type})")
    fc = FileConnector({"path": path})
    df = await fc.load_dataframe()
    profile = profile_dataframe(df)
    evidence_id = new_id("evidence")
    new_ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=ev.source_id,
        type_="profile", title=f"Profil — {ev.title}",
        payload={"profile": profile, "source_evidence_id": ev.id},
        provenance={"tool": "data_profile", "source_evidence": ev.id},
        record_count=profile["rows"],
        summary={"rows": profile["rows"], "columns": profile["columns"],
                 "nulls_total": sum(c["nulls"] for c in profile["column_profiles"])},
        evidence_id=evidence_id,
    )
    await ctx.repo.create_evidence_meta(new_ev)
    return ToolResult(
        tool_call_id="", tool="data_profile", source_id=ev.source_id, status="success",
        evidence_ids=[new_ev.id], record_count=profile["rows"], preview=redact(profile),
    )


async def tool_data_validate(ctx: ToolContext, args: dict) -> ToolResult:
    ev, full = await _load_evidence(ctx, args["evidence_id"])
    path = (full.get("payload") or {}).get("path")
    ruleset = get_rule_set(args["rule_set_id"])
    if ruleset is None:
        return ToolResult(tool_call_id="", tool="data_validate", status="error",
                          error=f"rule_set inconnu: {args['rule_set_id']} (disponibles: {sorted(RULE_SETS)})")
    if not path:
        return ToolResult(tool_call_id="", tool="data_validate", status="error",
                          error=f"evidence {ev.id} n'est pas un fichier source (type={ev.type})")
    fc = FileConnector({"path": path})
    df = await fc.load_dataframe()
    result = evaluate_rule_set(df, ruleset)
    evidence_id = new_id("evidence")
    new_ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=ev.source_id,
        type_="validation", title=f"Validation {ruleset.name} — {ev.title}",
        payload={"rule_set_result": result.model_dump(), "source_evidence_id": ev.id,
                 "contract_note": ruleset.contract_note},
        provenance={"tool": "data_validate", "rule_set_id": ruleset.id, "source_evidence": ev.id},
        record_count=result.violation_count,
        summary={"rule_set_id": ruleset.id, "rows": result.rows, "valid": result.valid,
                 "violation_count": result.violation_count,
                 "rules_failed": result.rules_failed,
                 "violations_sample": [v.model_dump() for v in result.violations[:10]]},
        evidence_id=evidence_id,
    )
    await ctx.repo.create_evidence_meta(new_ev)
    return ToolResult(
        tool_call_id="", tool="data_validate", status="success",
        source_id=ev.source_id, evidence_ids=[new_ev.id], record_count=result.violation_count,
        preview={"rule_set_id": ruleset.id, "rows": result.rows, "valid": result.valid,
                 "violation_count": result.violation_count,
                 "violations_sample": [v.model_dump() for v in result.violations[:10]],
                 "contract_note": ruleset.contract_note},
    )


async def tool_evidence_join(ctx: ToolContext, args: dict) -> ToolResult:
    ev_left, full_left = await _load_evidence(ctx, args["evidence_ids"][0])
    ev_right, full_right = await _load_evidence(ctx, args["evidence_ids"][1])
    left_records = _records_from_payload(full_left)
    right_records = _records_from_payload(full_right)
    left_key, right_key = args["left_key"], args["right_key"]

    if not left_records or not right_records:
        return ToolResult(
            tool_call_id="", tool="evidence_join", status="insufficient_evidence",
            error="les evidences fournies ne contiennent pas d'enregistrements joignables (records)",
            preview={"left": ev_left.id, "right": ev_right.id},
        )
    if left_key not in left_records[0] or right_key not in right_records[0]:
        return ToolResult(
            tool_call_id="", tool="evidence_join", status="error",
            error=f"clé absente: {left_key!r} côté gauche / {right_key!r} côté droit",
        )

    right_index: dict[str, list[dict]] = {}
    for r in right_records:
        k = str(r.get(right_key))
        right_index.setdefault(k, []).append(r)

    matched, unmatched_left, pairs = 0, [], []
    unmatched_right_keys = set(right_index.keys())
    for lr in left_records:
        k = str(lr.get(left_key))
        hits = right_index.get(k)
        if hits:
            matched += 1
            unmatched_right_keys.discard(k)
            if len(pairs) < 10:
                pairs.append({"key": k, "left": redact(lr), "right": redact(hits[0])})
        else:
            if len(unmatched_left) < 10:
                unmatched_left.append({"key": k, "left": redact(lr)})

    evidence_id = new_id("evidence")
    new_ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=None,
        type_="join", title=args.get("label") or f"Jointure {ev_left.id} ⋈ {ev_right.id}",
        payload={
            "left_evidence_id": ev_left.id, "right_evidence_id": ev_right.id,
            "left_key": left_key, "right_key": right_key,
            "left_rows": len(left_records), "right_rows": len(right_records),
            "matched": matched, "unmatched_left_count": len(left_records) - matched,
            "unmatched_right_count": len(unmatched_right_keys),
            "pairs_sample": pairs, "unmatched_left_sample": unmatched_left,
        },
        provenance={"tool": "evidence_join", "left": ev_left.id, "right": ev_right.id},
        record_count=matched,
        summary={"matched": matched, "left_rows": len(left_records), "right_rows": len(right_records),
                 "unmatched_left_count": len(left_records) - matched,
                 "unmatched_right_count": len(unmatched_right_keys),
                 "join_keys": {"left": left_key, "right": right_key}},
        evidence_id=evidence_id,
    )
    await ctx.repo.create_evidence_meta(new_ev)
    return ToolResult(
        tool_call_id="", tool="evidence_join", status="success", evidence_ids=[new_ev.id],
        record_count=matched,
        preview={"matched": matched, "left_rows": len(left_records), "right_rows": len(right_records),
                 "unmatched_left_count": len(left_records) - matched,
                 "unmatched_right_count": len(unmatched_right_keys),
                 "pairs_sample": pairs, "unmatched_left_sample": unmatched_left},
        warnings=["les IDs de deux systèmes ne sont pas nécessairement identiques — vérifier la signification de la clé (docs/06)"],
    )


async def tool_get_control_definition(ctx: ToolContext, args: dict) -> ToolResult:
    control = get_control(args["control_id"])
    if control is None:
        return ToolResult(tool_call_id="", tool="get_control_definition", status="error",
                          error=f"contrôle inconnu: {args['control_id']} (catalogue: {sorted(CONTROL_CATALOG)})")
    return ToolResult(
        tool_call_id="", tool="get_control_definition", status="success",
        record_count=1, preview=control_to_dict(control),
    )


async def tool_get_evidence_excerpt(ctx: ToolContext, args: dict) -> ToolResult:
    ev, full = await _load_evidence(ctx, args["evidence_id"])
    records = _records_from_payload(full)
    start, end = args["row_start"], args["row_start"] + args["row_end"]
    excerpt = records[start:end]
    evidence_id = new_id("evidence")
    new_ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=ev.source_id,
        type_="excerpt", title=f"Extrait [{start}:{end}] — {ev.title}",
        payload={"source_evidence_id": ev.id, "row_start": start, "row_end": min(end, len(records)),
                 "records": redact(excerpt), "total_records": len(records)},
        provenance={"tool": "get_evidence_excerpt", "source_evidence": ev.id},
        record_count=len(excerpt),
        summary={"source_evidence_id": ev.id, "range": [start, min(end, len(records))],
                 "total_records": len(records)},
        evidence_id=evidence_id,
    )
    await ctx.repo.create_evidence_meta(new_ev)
    return ToolResult(
        tool_call_id="", tool="get_evidence_excerpt", status="success",
        source_id=ev.source_id, evidence_ids=[new_ev.id], record_count=len(excerpt),
        preview={"range": [start, min(end, len(records))], "total_records": len(records),
                 "records": redact(excerpt)},
        warnings=(["plage au-delà du total"] if start >= len(records) else []),
    )


MAX_SEARCH_SCAN = 5000  # bornes CPU : arrêt du scan au-delà (docs/05 exécution bornée)


async def tool_data_explore(ctx: ToolContext, args: dict) -> ToolResult:
    """Exploration bornée et déterministe d'une evidence d'enregistrements (Phase 2/10).
    Le LLM décide QUOI explorer ; les calculs sont exécutés ici (aucun SQL, aucune
    exécution arbitraire). Le résultat devient une evidence `exploration` traçable."""
    from ..audit.exploration import MAX_EXPLORE_ROWS, apply_exploration

    ev, full = await _load_evidence(ctx, args["evidence_id"])
    records = _records_from_payload(full)
    if not records and ev.type == "raw_file" and (full.get("payload") or {}).get("path"):
        # fichier source (CSV/XLSX/JSON) : enregistrements normalisés via le connecteur
        from ..connectors.files.connector import FileConnector

        fc = FileConnector({"path": (full.get("payload") or {}).get("path"),
                            "original_name": ev.title})
        records = await fc.load_records(limit=MAX_EXPLORE_ROWS)
    if not records:
        return ToolResult(
            tool_call_id="", tool="data_explore", source_id=ev.source_id,
            status="insufficient_evidence",
            error=f"l'evidence {ev.id} ne contient pas d'enregistrements exploitables (type={ev.type})",
        )
    spec = args.get("spec") or {}
    if not isinstance(spec, dict) or not any(
        k in spec for k in ("filter", "sort", "group_by", "aggregate", "compare", "fields")
    ):
        return ToolResult(
            tool_call_id="", tool="data_explore", status="error",
            error="spec vide : fournir au moins une opération (filter/sort/group_by/aggregate/compare/fields)",
        )
    result = apply_exploration(records, spec)
    if result.get("unknown_fields"):
        return ToolResult(
            tool_call_id="", tool="data_explore", status="error",
            error=f"champs inconnus dans la spécification : {', '.join(result['unknown_fields'])} "
                  f"(champs disponibles : {', '.join(sorted(records[0].keys()))})",
        )
    result["source_evidence_id"] = ev.id
    result["source_evidence_title"] = ev.title
    result["mission_id"] = ctx.mission.id

    new_ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=ev.source_id,
        type_="exploration", title=f"Exploration — {ev.title}",
        payload={"exploration": result, "source_evidence_id": ev.id, "spec": spec},
        provenance={"tool": "data_explore", "source_evidence": ev.id, "spec": spec},
        record_count=result["returned_rows"],
        summary={
            "source_evidence_id": ev.id, "total_after_filters": result["total_after_filters"],
            "returned_rows": result["returned_rows"],
            "comparison": result.get("comparison"), "groups": result.get("groups"),
        },
        evidence_id=new_id("evidence"),
    )
    await ctx.repo.create_evidence_meta(new_ev)
    return ToolResult(
        tool_call_id="", tool="data_explore", source_id=ev.source_id, status="success",
        evidence_ids=[new_ev.id], record_count=result["returned_rows"], preview=redact(result),
    )


async def tool_correlate_records(ctx: ToolContext, args: dict) -> ToolResult:
    """Corrélation cross-système GÉNÉRIQUE (Phase 3/10) : résolution d'entités par clés
    explicites entre deux evidences d'enregistrements — matched / uncertain (clé
    normalisée) / unmatched / conflicting (écart de valeurs comparées). Aucune
    correspondance inventée : chaque lien cite les evidences et row_index."""
    from ..audit.correlation import correlate

    ev_left, full_left = await _load_evidence(ctx, args["evidence_ids"][0])
    ev_right, full_right = await _load_evidence(ctx, args["evidence_ids"][1])
    left_records = _records_from_payload(full_left)
    right_records = _records_from_payload(full_right)
    if not left_records or not right_records:
        return ToolResult(
            tool_call_id="", tool="correlate_records",
            status="insufficient_evidence",
            error="correlate_records requiert deux evidences d'enregistrements non vides",
        )
    for side, key, rec in (("left_key", args["left_key"], left_records),
                           ("right_key", args["right_key"], right_records)):
        if key not in rec[0]:
            return ToolResult(
                tool_call_id="", tool="correlate_records", status="error",
                error=f"{side}={key!r} absent des champs disponibles "
                      f"({', '.join(sorted(rec[0].keys()))})",
            )
    result = correlate(
        left_records, right_records, args["left_key"], args["right_key"],
        left_label=ev_left.title, right_label=ev_right.title,
        left_evidence_id=ev_left.id, right_evidence_id=ev_right.id,
        compare_fields=args.get("compare_fields") or [],
        normalize=bool(args.get("normalize")),
    )
    result["mission_id"] = ctx.mission.id
    new_ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=ev_left.source_id,
        type_="correlation", title=f"Corrélation — {ev_left.title} × {ev_right.title}",
        payload={"correlation": result, "spec": args},
        provenance={"tool": "correlate_records", "left": ev_left.id, "right": ev_right.id},
        record_count=result["stats"]["matched"] + result["stats"]["uncertain"],
        summary={"stats": result["stats"], "conflicts": result["conflicts"][:10]},
        evidence_id=new_id("evidence"),
    )
    await ctx.repo.create_evidence_meta(new_ev)
    return ToolResult(
        tool_call_id="", tool="correlate_records", source_id=ev_left.source_id,
        status="success", evidence_ids=[new_ev.id], preview=redact(result),
    )


async def tool_evidence_search(ctx: ToolContext, args: dict) -> ToolResult:
    """Recherche bornée DANS une preuve collectée (aucun accès externe, docs/14).

    L'agent investigateur localise un enregistrement précis cité par une réconciliation
    (ex. une commande flaggée) sans parcourir la preuve page par page : identifiant métier,
    sous-chaîne sur un champ. Chaque hit est redacté et traçable (evidence de type excerpt).
    """
    ev, full = await _load_evidence(ctx, args["evidence_id"])
    payload = full.get("payload") or {}
    query = str(args["query"]).lower()
    field_filter = args.get("field")
    max_hits = args.get("max_hits", 10)
    hits: list[dict] = []
    scanned = 0
    truncated_scan = False
    for section in ("records", "lines", "pickings", "quants"):
        rows = payload.get(section)
        if not isinstance(rows, list):
            continue
        for idx, row in enumerate(rows):
            scanned += 1
            if scanned > MAX_SEARCH_SCAN:
                truncated_scan = True
                break
            if not isinstance(row, dict) or len(hits) >= max_hits:
                if len(hits) >= max_hits:
                    break
                continue
            if field_filter:
                value = row.get(field_filter)
                matched = value is not None and query in str(value).lower()
            else:
                matched = query in json.dumps(row, ensure_ascii=False, default=str).lower()
            if matched:
                hits.append({"section": section, "index": idx, "record": redact(row)})
        if len(hits) >= max_hits or truncated_scan:
            break

    evidence_id = new_id("evidence")
    new_ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=ev.source_id,
        type_="excerpt", title=f"Recherche «{args['query'][:40]}» — {ev.title}",
        payload={
            "source_evidence_id": ev.id, "query": args["query"], "field": field_filter,
            "hits": hits, "rows_scanned": scanned, "scan_truncated": truncated_scan,
        },
        provenance={"tool": "evidence_search", "source_evidence": ev.id},
        record_count=len(hits),
        summary={"source_evidence_id": ev.id, "query": args["query"], "field": field_filter,
                 "hit_count": len(hits), "rows_scanned": scanned, "scan_truncated": truncated_scan},
        evidence_id=evidence_id,
    )
    await ctx.repo.create_evidence_meta(new_ev)
    return ToolResult(
        tool_call_id="", tool="evidence_search", status="success",
        source_id=ev.source_id, evidence_ids=[new_ev.id], record_count=len(hits),
        preview={"query": args["query"], "hit_count": len(hits), "hits": hits,
                 "rows_scanned": scanned, "scan_truncated": truncated_scan},
        warnings=(["scan interrompu à la limite bornée — affiner la requête"] if truncated_scan else []),
    )


# ==========================================================================
# Registre : specs + handlers + modèles d'entrée
# ==========================================================================

ALL = "all"


def _spec(name: str, label: str, description: str, source_types: list[SourceType],
          permission: PermissionLevel, input_model: type[BaseModel], schema_hint: dict) -> dict:
    return {
        "spec": {
            "name": name, "label": label, "description": description,
            "source_types": source_types, "permission": permission,
            "input_model_name": input_model.__name__, "schema_hint": schema_hint,
        },
        "handler": None,  # rempli dans register_all_tools
        "input_model": input_model,
    }


TOOL_DEFS: list[dict] = [
    _spec("discover_source", "Découvrir la source",
          "Teste la connexion et liste les capacités réelles de la source (modèles Odoo disponibles, endpoints API, parcours web, colonnes du fichier).",
          [], PermissionLevel.read, DiscoverSourceInput,
          {"type": "object", "properties": {"source_id": {"type": "string"}}, "required": ["source_id"]}),
    _spec("odoo_read_orders", "Lire les commandes ERP",
          "Lit les commandes de vente Odoo (sale.order) sur une période : quantités, états, dates.",
          [SourceType.odoo], PermissionLevel.read, OdooReadInput,
          {"type": "object", "properties": {"source_id": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["source_id"]}),
    _spec("odoo_read_invoices", "Lire les factures ERP",
          "Lit les factures clients Odoo (account.move) : montants, références, statut paiement.",
          [SourceType.odoo], PermissionLevel.read, OdooReadInput,
          {"type": "object", "properties": {"source_id": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["source_id"]}),
    _spec("odoo_read_stock", "Lire les mouvements de stock ERP",
          "Lit les mouvements de stock Odoo (stock.move) : quantités demandées/réalisées, états, pickings et quantités on-hand (stock.quant).",
          [SourceType.odoo], PermissionLevel.read, OdooReadInput,
          {"type": "object", "properties": {"source_id": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["source_id"]}),
    _spec("odoo_read_purchases", "Lire les achats ERP",
          "Lit les commandes d'achat Odoo (purchase.order) : quantités, réceptions, montants.",
          [SourceType.odoo], PermissionLevel.read, OdooReadInput,
          {"type": "object", "properties": {"source_id": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["source_id"]}),
    _spec("odoo_cross_check", "Réconcilier commandes / factures / stock ERP",
          "Réconciliation DÉTERMINISTE des evidences Odoo collectées : quantités commandées/livrées/facturées (avoirs et livraisons partielles gérés), références de picking orphelines, stock on-hand négatif, chronologies. Chaque violation cite ses faits ; kind=confirmed ou suspicious.",
          [], PermissionLevel.local, OdooCrossCheckInput,
          {"type": "object", "properties": {"evidence_ids": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 4}}, "required": ["evidence_ids"]}),
    _spec("api_inspect_contract", "Vérifier l'API",
          "Interroge les endpoints approuvés et vérifie le contrat (statut, schéma OpenAPI). Tests actifs nécessitant approbation.",
          [SourceType.api], PermissionLevel.approved_tests, ApiInspectInput,
          {"type": "object", "properties": {"source_id": {"type": "string"}, "endpoint_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["source_id"]}),
    _spec("api_fetch_records", "Lire les enregistrements API",
          "Effectue une requête GET vérifiable sur un endpoint approuvé et enregistre la réponse.",
          [SourceType.api], PermissionLevel.read, ApiFetchInput,
          {"type": "object", "properties": {"source_id": {"type": "string"}, "endpoint_id": {"type": "string"}, "filters": {"type": "object"}}, "required": ["source_id", "endpoint_id"]}),
    _spec("web_run_journey", "Contrôler un parcours web",
          "Exécute le parcours déclaré (Playwright) : étapes, assertions, captures d'écran, erreurs JS. Tests actifs nécessitant approbation.",
          [SourceType.web], PermissionLevel.approved_tests, WebJourneyInput,
          {"type": "object", "properties": {"source_id": {"type": "string"}, "journey_id": {"type": "string"}}, "required": ["source_id", "journey_id"]}),
    _spec("data_profile", "Analyser les données",
          "Profil statistique d'un fichier importé : types, nulls, uniques, valeurs aberrantes candidates.",
          [], PermissionLevel.local, DataProfileInput,
          {"type": "object", "properties": {"evidence_id": {"type": "string"}}, "required": ["evidence_id"]}),
    _spec("data_validate", "Valider les données",
          "Applique un jeu de règles déterministes (rule_set) et retourne les violations par enregistrement.",
          [], PermissionLevel.local, DataValidateInput,
          {"type": "object", "properties": {"evidence_id": {"type": "string"}, "rule_set_id": {"type": "string"}}, "required": ["evidence_id", "rule_set_id"]}),
    _spec("evidence_join", "Recouper les preuves",
          "Joint deux evidences d'enregistrements sur une clé métier et documente correspondances / non-correspondances.",
          [], PermissionLevel.local, EvidenceJoinInput,
          {"type": "object", "properties": {"evidence_ids": {"type": "array", "items": {"type": "string"}}, "left_key": {"type": "string"}, "right_key": {"type": "string"}, "label": {"type": "string"}}, "required": ["evidence_ids", "left_key", "right_key"]}),
    _spec("get_control_definition", "Lire la définition d'un contrôle",
          "Retourne le critère versionné, la méthode et les preuves attendues d'un contrôle du catalogue.",
          [], PermissionLevel.read, ControlDefInput,
          {"type": "object", "properties": {"control_id": {"type": "string"}}, "required": ["control_id"]}),
    _spec("get_evidence_excerpt", "Extraire un extrait de preuve",
          "Retourne un extrait borné d'une evidence d'enregistrements, minimisé et traçable.",
          [], PermissionLevel.read, EvidenceExcerptInput,
          {"type": "object", "properties": {"evidence_id": {"type": "string"}, "row_start": {"type": "integer"}, "row_end": {"type": "integer"}}, "required": ["evidence_id"]}),
    _spec("data_explore", "Explorer les données",
          "Exploration bornée et DÉTERMINISTE d'une evidence d'enregistrements : filtre, tri, group_by+agrégat (count/sum/avg/min/max), comparaison de champs, projection, limite. Spéc JSON typée — calculs exécutés par le backend, jamais par le modèle.",
          [], PermissionLevel.local, DataExploreInput,
          {"type": "object", "properties": {"evidence_id": {"type": "string"}, "spec": {"type": "object", "properties": {"fields": {"type": "array", "items": {"type": "string"}}, "filter": {"type": "array", "items": {"type": "object", "properties": {"field": {"type": "string"}, "op": {"type": "string", "enum": ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "not_null"]}, "value": {}}}}, "sort": {"type": "array", "items": {"type": "object", "properties": {"field": {"type": "string"}, "dir": {"type": "string", "enum": ["asc", "desc"]}}}}, "group_by": {"type": "string"}, "aggregate": {"type": "object", "properties": {"op": {"type": "string", "enum": ["count", "sum", "avg", "min", "max"]}, "field": {"type": "string"}}}, "compare": {"type": "object", "properties": {"left_field": {"type": "string"}, "right_field": {"type": "string"}, "op": {"type": "string", "enum": ["eq", "ne", "gt", "gte", "lt", "lte"]}}}, "limit": {"type": "integer"}}}, "required": ["evidence_id", "spec"]}}),
    _spec("odoo_list_models", "Lister les modèles Odoo",
          "Découverte des modèles métier installés et lisibles par le compte d'audit (hors modèles techniques/sensibles).",
          ["odoo"], PermissionLevel.read, OdooListModelsInput,
          {"type": "object", "properties": {"source_id": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["source_id"]}),
    _spec("odoo_describe_model", "Décrire un modèle Odoo",
          "Métadonnées d'un modèle : champs sûrs, types, relations, nombre d'enregistrements. Modèles techniques/sensibles refusés.",
          ["odoo"], PermissionLevel.read, OdooDescribeModelInput,
          {"type": "object", "properties": {"model": {"type": "string"}}, "required": ["model"]}),
    _spec("odoo_query_records", "Lire des enregistrements Odoo",
          "search_read borné (<=200) sur n'importe quel modèle autorisé : domaine read-only allowlist, champs sûrs, ordre.",
          ["odoo"], PermissionLevel.read, OdooQueryRecordsInput,
          {"type": "object", "properties": {"source_id": {"type": "string"}, "model": {"type": "string"}, "domain": {"type": "array"}, "fields": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"}, "order": {"type": "string"}}, "required": ["source_id", "model"]}),
    _spec("odoo_follow_relation", "Suivre une relation Odoo",
          "Suit many2one/one2many/many2many depuis un enregistrement vers son comodèle (lecture bornée).",
          ["odoo"], PermissionLevel.read, OdooFollowRelationInput,
          {"type": "object", "properties": {"source_id": {"type": "string"}, "model": {"type": "string"}, "record_id": {"type": "integer"}, "relation_field": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["source_id", "model", "record_id", "relation_field"]}),
    _spec("odoo_aggregate_records", "Agréger des enregistrements Odoo",
          "read_group borné par champ de groupement + agrégat (count/sum/avg/min/max) avec repli déterministe.",
          ["odoo"], PermissionLevel.read, OdooAggregateInput,
          {"type": "object", "properties": {"source_id": {"type": "string"}, "model": {"type": "string"}, "group_by": {"type": "string"}, "domain": {"type": "array"}, "aggregate_field": {"type": "string"}, "aggregate_op": {"type": "string", "enum": ["count", "sum", "avg", "min", "max"]}, "limit": {"type": "integer"}}, "required": ["source_id", "model", "group_by"]}),
    _spec("correlate_records", "Corréler deux systèmes",
          "Résolution d'entités GÉNÉRIQUE entre deux evidences d'enregistrements par clés explicites : liens matched/uncertain, non-correspondances, contradictions de valeurs comparées. Chaque lien cite les evidences et row_index — aucune relation inventée.",
          [], PermissionLevel.local, CorrelateRecordsInput,
          {"type": "object", "properties": {"evidence_ids": {"type": "array", "items": {"type": "string"}}, "left_key": {"type": "string"}, "right_key": {"type": "string"}, "compare_fields": {"type": "array", "items": {"type": "object", "properties": {"left": {"type": "string"}, "right": {"type": "string"}}}}, "normalize": {"type": "boolean"}, "label": {"type": "string"}}, "required": ["evidence_ids", "left_key", "right_key"]}),
    _spec("evidence_search", "Rechercher dans une preuve",
          "Recherche bornée (insensible à la casse) dans une preuve collectée : localise un enregistrement par identifiant métier ou sous-chaîne (records/lines/pickings/quants), champ optionnel. Hit redactés et traçables.",
          [], PermissionLevel.read, EvidenceSearchInput,
          {"type": "object", "properties": {"evidence_id": {"type": "string"}, "query": {"type": "string"}, "field": {"type": "string"}, "max_hits": {"type": "integer"}}, "required": ["evidence_id", "query"]}),
]


def register_all_tools(registry) -> dict[str, type[BaseModel]]:
    """Enregistre toutes les tools dans le registry. Retourne les modèles d'entrée par tool."""
    from ..harness.registry import ToolRegistry
    from ..harness.contracts import ToolSpec

    handlers = {
        "discover_source": tool_discover_source,
        "odoo_read_orders": tool_odoo_read_orders,
        "odoo_read_invoices": tool_odoo_read_invoices,
        "odoo_read_stock": tool_odoo_read_stock,
        "odoo_read_purchases": tool_odoo_read_purchases,
        "odoo_cross_check": tool_odoo_cross_check,
        "api_inspect_contract": tool_api_inspect_contract,
        "api_fetch_records": tool_api_fetch_records,
        "web_run_journey": tool_web_run_journey,
        "data_profile": tool_data_profile,
        "data_validate": tool_data_validate,
        "evidence_join": tool_evidence_join,
        "data_explore": tool_data_explore,
        "correlate_records": tool_correlate_records,
        "get_control_definition": tool_get_control_definition,
        "get_evidence_excerpt": tool_get_evidence_excerpt,
                "evidence_search": tool_evidence_search,
        "odoo_list_models": tool_odoo_list_models,
        "odoo_describe_model": tool_odoo_describe_model,
        "odoo_query_records": tool_odoo_query_records,
        "odoo_follow_relation": tool_odoo_follow_relation,
        "odoo_aggregate_records": tool_odoo_aggregate_records,
    }
    input_models: dict[str, type[BaseModel]] = {}
    for item in TOOL_DEFS:
        d = item["spec"]
        name = d["name"]
        spec = ToolSpec(
            name=name, label=d["label"], description=d["description"],
            source_types=d["source_types"], permission=d["permission"],
            input_model_name=d["input_model_name"], schema_hint=d["schema_hint"],
        )
        assert isinstance(registry, ToolRegistry)
        registry.register(spec, handlers[name])
        input_models[name] = item["input_model"]
    return input_models
