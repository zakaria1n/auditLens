"""Tool Executor (docs/05 niveau 3) : exécute localement, trace, insère comme tool call.

Journalisation systématique (y compris refus) : docs/13 « Toute tool call ... écrit un audit log ».
"""

from __future__ import annotations

import time

from ..core.errors import PolicyViolation
from ..core.ids import new_id
from ..core.redact import redact
from ..models import ToolCallRecord
from .contracts import InputValidationError, ToolContext, ToolResult, validate_tool_args
from .policy import PolicyGate
from .registry import ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, gate: PolicyGate):
        self.registry = registry
        self.gate = gate

    async def execute(self, name: str, args: dict, ctx: ToolContext) -> ToolResult:
        call_id = new_id("tool_call")
        try:
            spec, handler = self.registry.get(name)
        except KeyError:
            # Le modèle a proposé une tool hors catalogue : refus journalisé, run non interrompu
            msg = f"tool inconnue: {name!r} — hors catalogue autorisé"
            await self._record(ctx, call_id, name, args, "error", 0, [], msg)
            return ToolResult(tool_call_id=call_id, tool=name, source_id=args.get("source_id"), status="error", error=msg)
        source = None
        if args.get("source_id"):
            source = await ctx.connectors.get_source(args["source_id"])

        t0 = time.monotonic()

        # Policy Gate — un refus est enregistré et retourné, jamais silencieux.
        try:
            self.gate.check(spec, args, ctx.mission, source)
        except PolicyViolation as exc:
            await self._record(ctx, call_id, name, args, "unauthorized", int((time.monotonic() - t0) * 1000), [], str(exc))
            return ToolResult(
                tool_call_id=call_id, tool=name, source_id=args.get("source_id"),
                status="unauthorized", error=str(exc),
                preview={"blocked_reason": str(exc)},
            )

        # Validation du schéma d'entrée.
        try:
            from ..models import PermissionLevel

            model = ctx.extra["tool_input_models"][name]
            clean_args = validate_tool_args(model, args)
        except InputValidationError as exc:
            await self._record(ctx, call_id, name, args, "error", int((time.monotonic() - t0) * 1000), [], str(exc))
            return ToolResult(tool_call_id=call_id, tool=name, source_id=args.get("source_id"), status="error", error=str(exc))

        # Exécution dans le système (le handler crée ses evidences).
        try:
            result = await handler(ctx, clean_args)
        except Exception as exc:  # noqa: BLE001 — toute erreur tool devient un résultat traçable
            latency = int((time.monotonic() - t0) * 1000)
            msg = f"{type(exc).__name__}: {exc}"
            await self._record(ctx, call_id, name, clean_args, "error", latency, [], msg)
            return ToolResult(tool_call_id=call_id, tool=name, source_id=clean_args.get("source_id"), status="error", error=msg)

        result.tool_call_id = call_id
        await self._record(
            ctx, call_id, name, clean_args, result.status, int((time.monotonic() - t0) * 1000),
            result.evidence_ids, result.error, warnings=result.warnings,
        )
        return result

    async def _record(
        self, ctx: ToolContext, call_id: str, name: str, args: dict, status: str,
        latency_ms: int, evidence_ids: list[str], error: str | None, warnings: list[str] | None = None,
    ) -> None:
        rec = ToolCallRecord(
            id=call_id, run_id=ctx.run_id, mission_id=ctx.mission.id, name=name,
            source_id=args.get("source_id"), args=redact(args), status=status,  # type: ignore[arg-type]
            latency_ms=latency_ms, evidence_ids=evidence_ids, warnings=warnings or [], error=error,
        )
        await ctx.repo.create_tool_call(rec)
