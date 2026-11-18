"""Source Intelligence (Phase 1/10) : découverte structurée et honnête d'une source.

Une SEULE implémentation, réutilisée par :
- le tool chat `inspect_source` (carte Source Intelligence dans la conversation) ;
- l'orchestrator (payload `intelligence` passé au LLM de plan — il choisit ses tools
  selon les capacités RÉELLES, jamais inventées).

Principes (docs/05, docs/13) :
- lecture seule via ConnectorFactory (aucune écriture, Policy Gate inchangé) ;
- capacités = ce que le connecteur DÉCLARE, pas ce qu'on espère ;
- missing_permissions = tools du registry applicables à ce type mais nécessitant
  `approved-tests` non approuvés pour la mission courante (None hors mission) ;
- unsupported_operations = opérations demandables mais que la source ne supporte pas.
"""

from __future__ import annotations

from typing import Any

from ..harness.registry import ToolRegistry
from ..models import AuditMission, PermissionLevel, SourceConnection, SourceType


def _domains_from_caps(source_type: SourceType, caps: dict[str, Any]) -> list[str]:
    """Domaines métier accessibles, déduits GÉNÉRIQUEMENT des capacités déclarées
    (modèles Odoo, groupes d'endpoints API, colonnes fichier, parcours web).
    Aucun domaine inventé : la liste reflète uniquement ce que la source expose."""
    domains: list[str] = []
    if source_type == SourceType.odoo:
        for model, meta in (caps.get("models") or {}).items():
            if isinstance(meta, dict) and meta.get("available"):
                domains.append(str(meta.get("label") or model))
    elif source_type == SourceType.api:
        for ep in caps.get("endpoints") or []:
            name = str(ep.get("id") or ep.get("path") or "").strip("/")
            top = name.split("/")[0] if name else ""
            if top and top not in domains:
                domains.append(top)
    elif source_type == SourceType.file:
        for col in (caps.get("columns") or []):
            name = str(col.get("name") or col) if isinstance(col, dict) else str(col)
            if name and name not in domains:
                domains.append(name)
    elif source_type == SourceType.web:
        for j in caps.get("journeys") or []:
            name = str(j.get("id") or j.get("name") or "")
            if name and name not in domains:
                domains.append(name)
    return domains


def build_source_intelligence(
    source: SourceConnection,
    caps: dict[str, Any],
    registry: ToolRegistry,
    mission: AuditMission | None = None,
) -> dict[str, Any]:
    """Intelligence structurée d'une source : état, capacités, domaines, opérations
    supportées/non supportées, permissions manquantes, prérequis."""
    source_type = source.type
    error = caps.get("discover_error")
    connection_state = "error" if error else ("connected" if caps else "unknown")

    # opérations du registry applicables à ce type de source
    supported: list[dict[str, str]] = []
    missing_permissions: list[dict[str, str]] = []
    approved: list[dict[str, Any]] = []
    if mission is not None and mission.approved_plan:
        approved = mission.approved_plan.get("approved_actions", []) or []

    for spec in registry.list_specs():
        is_local = not spec.source_types  # tools locales : opèrent sur les preuves, tout type
        if not is_local and source_type not in spec.source_types:
            continue
        entry = {"tool": spec.name, "label": spec.label}
        if is_local:
            supported.append({**entry, "scope": "local (preuves de la mission)"})
            continue
        if spec.permission == PermissionLevel.approved_tests:
            granted = any(
                a.get("tool") == spec.name and (a.get("source_id") in (None, source.id))
                for a in approved
            )
            if granted:
                supported.append(entry)
            else:
                missing_permissions.append({
                    "tool": spec.name,
                    "label": spec.label,
                    "reason": "requiert l'approbation humaine (approved-tests)",
                })
        else:
            supported.append(entry)

    # opérations génériques non supportées par ce type (le LLM ne doit pas les inventer)
    declared = _domains_from_caps(source_type, caps)

    intelligence: dict[str, Any] = {
        "source_id": source.id,
        "name": source.name,
        "type": source_type.value,
        "connection_state": connection_state,
        "status": source.status.value,
        "domains": declared,
        "capabilities": {
            "rows": caps.get("rows"),
            "truncated": caps.get("truncated"),
            "columns": [c["name"] for c in caps.get("columns", []) if isinstance(c, dict)],
            "endpoints": caps.get("endpoints", []),
            "journeys": caps.get("journeys", []),
            "models_available": sorted(
                k for k, v in (caps.get("models") or {}).items()
                if isinstance(v, dict) and v.get("available")
            ),
            "models_unavailable": sorted(
                k for k, v in (caps.get("models") or {}).items()
                if isinstance(v, dict) and not v.get("available")
            ),
        },
        "supported_operations": supported,
        "missing_permissions": missing_permissions,
        "unsupported_operations": generic_ops_unsupported(source_type, caps),
        "prerequisites": _prerequisites(source_type, caps),
    }
    if error:
        intelligence["discover_error"] = str(error)
    return intelligence


def generic_ops_unsupported(source_type: SourceType, caps: dict[str, Any]) -> list[str]:
    """Opérations que l'agent pourrait vouloir tenter mais que la source NE supporte pas
    (déduit génériquement du type + capacités — pas de promesse inventée)."""
    out: list[str] = []
    if source_type == SourceType.file:
        out.append("lecture d'endpoints API ou de modèles ERP (type fichier uniquement)")
        if not caps.get("columns"):
            out.append("profilage structuré (aucune colonne déclarée)")
    elif source_type == SourceType.api:
        out.append("écritures / mutations (lecture seule par policy)")
        if not caps.get("endpoints"):
            out.append("lectures d'endpoints (aucun endpoint déclaré)")
    elif source_type == SourceType.odoo:
        out.append("écritures ERP (Odoo en lecture seule)")
        unavailable = [
            k for k, v in (caps.get("models") or {}).items()
            if isinstance(v, dict) and not v.get("available")
        ]
        for k in unavailable:
            out.append(f"lectures du modèle {k} (module non installé)")
    elif source_type == SourceType.web:
        out.append("appels API directs ou lectures ERP (parcours web uniquement)")
    return sorted(set(out))


def _prerequisites(source_type: SourceType, caps: dict[str, Any]) -> list[str]:
    """Prérequis concrets avant certainnes opérations (honnêteté sur les blocages)."""
    preq: list[str] = []
    if caps.get("truncated"):
        preq.append("fichier tronqué à l'import : les analyses ne couvrent que les lignes chargées")
    if source_type == SourceType.api and not caps.get("openapi"):
        preq.append("pas de contrat OpenAPI déclaré : l'inspection de contrat sera limitée")
    if source_type == SourceType.odoo and caps.get("discover_error"):
        preq.append("découverte Odoo en échec : vérifier la connexion dans Sources")
    if source_type == SourceType.web and not caps.get("journeys"):
        preq.append("aucun parcours déclaré : configurer des journeys dans Sources")
    return preq
