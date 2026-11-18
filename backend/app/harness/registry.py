"""Tool Registry (docs/05 niveau 1) : catalogue des tools autorisées pour le LLM."""

from __future__ import annotations

from typing import Any

from ..models import AuditMission, SourceType
from .contracts import ToolContext, ToolHandler, ToolSpec, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolSpec, ToolHandler]] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool déjà enregistrée: {spec.name}")
        self._tools[spec.name] = (spec, handler)

    def get(self, name: str) -> tuple[ToolSpec, ToolHandler]:
        if name not in self._tools:
            raise KeyError(f"Tool inconnue: {name}")
        return self._tools[name]

    def exists(self, name: str) -> bool:
        return name in self._tools

    def list_specs(self) -> list[ToolSpec]:
        return [spec for spec, _ in self._tools.values()]

    def capabilities_for_mission(self, mission: AuditMission, source_types: dict[str, SourceType]) -> list[dict[str, Any]]:
        """Capabilities offertes au LLM pour cette mission : tool x source autorisée (docs/04 étape 2)."""
        caps: list[dict[str, Any]] = []
        for source_id in mission.source_ids:
            stype = source_types.get(source_id)
            if stype is None:
                continue
            for spec in self.list_specs():
                if spec.source_types and stype not in spec.source_types:
                    continue
                if spec.source_types == [] and stype is None:
                    continue
                caps.append(
                    {
                        "tool": spec.name,
                        "label": spec.label,
                        "description": spec.description,
                        "source_id": source_id,
                        "source_type": stype.value,
                        "permission": spec.permission.value,
                        "schema": spec.schema_hint,
                    }
                )
        # Tools locales (aucune source) : data_validate, evidence_join, get_control_definition...
        for spec in self.list_specs():
            if not spec.source_types:
                caps.append(
                    {
                        "tool": spec.name,
                        "label": spec.label,
                        "description": spec.description,
                        "source_id": None,
                        "source_type": "local",
                        "permission": spec.permission.value,
                        "schema": spec.schema_hint,
                    }
                )
        return caps
