"""Tools génériques Odoo READ-ONLY (Phase 2B/4) : schémas, handlers, enregistrement.

Complètent (sans remplacer) les tools spécialisés odoo_read_*/odoo_cross_check.
Sécurité : liste blanche d'opérations ORM read-only, blacklist modèles/champs
sensibles, bornes strictes, erreurs d'accès remontées explicitement.
"""

from __future__ import annotations

import json

from app.connectors.odoo.generic import (
    MAX_DOMAIN_LEN,
    MAX_LIMIT,
    MAX_RELATION_RECORDS,
    model_is_allowed,
)
from pydantic import BaseModel, Field

from ..harness.contracts import InputValidationError, ToolResult, validate_tool_args


class OdooListModelsInput(BaseModel):
    source_id: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=200, ge=1, le=500)


class OdooDescribeModelInput(BaseModel):
    source_id: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=120)


class OdooQueryRecordsInput(BaseModel):
    source_id: str
    model: str = Field(min_length=1, max_length=120)
    domain: list = Field(default_factory=list, max_length=50,
                         description="domaine Odoo borné (opérateurs read-only)")
    fields: list[str] = Field(default_factory=list, max_length=40)
    limit: int = Field(default=50, ge=1, le=200)
    order: str | None = Field(default=None, max_length=120)


class OdooFollowRelationInput(BaseModel):
    source_id: str
    model: str = Field(min_length=1, max_length=120)
    record_id: int = Field(ge=1)
    relation_field: str = Field(min_length=1, max_length=120)
    limit: int = Field(default=50, ge=1, le=200)


class OdooAggregateInput(BaseModel):
    source_id: str
    model: str = Field(min_length=1, max_length=120)
    group_by: str = Field(min_length=1, max_length=120)
    domain: list = Field(default_factory=list, max_length=50)
    aggregate_field: str | None = Field(default=None, max_length=120)
    aggregate_op: str = Field(default="count", pattern="^(count|sum|avg|min|max)$")
    limit: int = Field(default=20, ge=1, le=200)


ALLOWED_OPERATORS = {"=", "!=", ">", ">=", "<", "<=", "like", "ilike", "in", "not in"}


def _validate_domain(domain: list) -> str | None:
    """Domaine borné : structure JSON simple, opérateurs read-only allowlist."""
    if len(json.dumps(domain, default=str)) > MAX_DOMAIN_LEN:
        return "domaine trop volumineux"
    for clause in domain:
        if isinstance(clause, list) and len(clause) == 3:
            if str(clause[0]).startswith("&") or str(clause[0]).startswith("|") or str(clause[0]) == "!":
                continue  # opérateurs logiques Odoo
            if str(clause[1]) not in ALLOWED_OPERATORS:
                return f"opérateur non autorisé : {clause[1]!r}"
        elif isinstance(clause, dict):
            continue  # domaines JSON-2 simples
        else:
            return "clause de domaine invalide (liste [champ, op, valeur] attendue)"
    return None


async def _odoo_connector(ctx, source_id: str):
    source = await ctx.connectors.get_source(source_id)
    if source is None or source.type.value != "odoo":
        raise InputValidationError(f"source odoo inconnue : {source_id}")
    return ctx.connectors.build(source), source


async def tool_odoo_list_models(ctx, args) -> ToolResult:
    if not isinstance(args, dict):
        args = args.model_dump()
    connector, source = await _odoo_connector(ctx, args["source_id"])
    try:
        models = await connector.list_accessible_models(limit=args.get("limit", 50))
    finally:
        await connector.close()
    readable = [m for m in models if m.get("readable")]
    return ToolResult(
        tool_call_id="", tool="odoo_list_models", source_id=source.id, status="success",
        record_count=len(readable),
        preview={"readable_count": len(readable),
                 "models": [{"model": m["model"], "name": m["name"],
                             "record_count": m.get("record_count")} for m in readable[:100]]},
    )


async def tool_odoo_describe_model(ctx, args) -> ToolResult:
    if not isinstance(args, dict):
        args = args.model_dump()
    connector, source = await _odoo_connector(ctx, args["source_id"])
    try:
        out = await connector.describe_model(args["model"])
    finally:
        await connector.close()
    status = "success" if out.get("allowed") else "error"
    return ToolResult(tool_call_id="", tool="odoo_describe_model", source_id=source.id,
                      status=status, preview=out)


async def tool_odoo_query_records(ctx, args) -> ToolResult:
    if not isinstance(args, dict):
        args = args.model_dump()
    domain_error = _validate_domain(args.get("domain", []))
    if domain_error:
        return ToolResult(tool_call_id="", tool="odoo_query_records",
                          status="error", error=domain_error)
    connector, source = await _odoo_connector(ctx, args["source_id"])
    try:
        out = await connector.query_records(
            args["model"], args.get("domain", []), args.get("fields") or None,
            limit=args.get("limit", 50), order=args.get("order"),
        )
    finally:
        await connector.close()
    if not out.get("allowed", True):
        return ToolResult(tool_call_id="", tool="odoo_query_records", source_id=source.id,
                          status="unauthorized", error=out.get("error"))
    if out.get("error"):
        return ToolResult(tool_call_id="", tool="odoo_query_records", source_id=source.id,
                          status="error", error=out["error"])
    new_ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=source.id,
        type_="record_set", title=f"Odoo générique — {args['model']}",
        payload={"records": out["records"], "model": args["model"], "domain": args.get("domain", [])},
        provenance={"tool": "odoo_query_records", "domain": args.get("domain", [])},
        record_count=out["count"],
        summary={"model": args["model"], "records": out["count"]},
    )
    await ctx.repo.create_evidence_meta(new_ev)
    return ToolResult(tool_call_id="", tool="odoo_query_records", source_id=source.id,
                      status="success", evidence_ids=[new_ev.id], record_count=out["count"])


async def tool_odoo_follow_relation(ctx, args) -> ToolResult:
    if not isinstance(args, dict):
        args = args.model_dump()
    connector, source = await _odoo_connector(ctx, args["source_id"])
    try:
        out = await connector.follow_relation(
            args["model"], args["record_id"], args["relation_field"], limit=args.get("limit", 50),
        )
    finally:
        await connector.close()
    if not out.get("allowed", True):
        return ToolResult(tool_call_id="", tool="odoo_follow_relation", source_id=source.id,
                          status="unauthorized", error=out.get("error"))
    if out.get("error"):
        return ToolResult(tool_call_id="", tool="odoo_follow_relation", source_id=source.id,
                          status="error", error=out["error"])
    records = out.get("records", [])
    new_ev = ctx.store.save(
        mission_id=ctx.mission.id, run_id=ctx.run_id, source_id=source.id,
        type_="record_set",
        title=f"Odoo relation {args['relation_field']} — {args['model']}#{args['record_id']}",
        payload={"records": records, "model": out.get("comodel"),
                 "via": f"{args['model']}.{args['relation_field']}#{args['record_id']}"},
        provenance={"tool": "odoo_follow_relation",
                    "via": f"{args['model']}.{args['relation_field']}#{args['record_id']}"},
        record_count=len(records),
        summary={"records": len(records), "comodel": out.get("comodel"),
                 "relation_type": out.get("relation_type")},
    )
    await ctx.repo.create_evidence_meta(new_ev)
    return ToolResult(tool_call_id="", tool="odoo_follow_relation", source_id=source.id,
                      status="success", evidence_ids=[new_ev.id], record_count=len(records))


async def tool_odoo_aggregate_records(ctx, args) -> ToolResult:
    if not isinstance(args, dict):
        args = args.model_dump()
    domain_error = _validate_domain(args.get("domain", []))
    if domain_error:
        return ToolResult(tool_call_id="", tool="odoo_aggregate_records",
                          status="error", error=domain_error)
    connector, source = await _odoo_connector(ctx, args["source_id"])
    try:
        out = await connector.aggregate_records(
            args["model"], args["group_by"], args.get("domain", []),
            aggregate_field=args.get("aggregate_field"),
            aggregate_op=args.get("aggregate_op", "count"), limit=args.get("limit", 50),
        )
    finally:
        await connector.close()
    if not out.get("allowed", True):
        return ToolResult(tool_call_id="", tool="odoo_aggregate_records", source_id=source.id,
                          status="unauthorized", error=out.get("error"))
    if out.get("error"):
        return ToolResult(tool_call_id="", tool="odoo_aggregate_records", source_id=source.id,
                          status="error", error=out["error"])
    return ToolResult(tool_call_id="", tool="odoo_aggregate_records", source_id=source.id,
                      status="success", record_count=len(out.get("groups", [])),
                      preview={"groups": out.get("groups", [])[:50],
                               "fallback": out.get("fallback")})
