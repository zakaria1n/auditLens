"""Validation de contrat OpenAPI déterministe (docs/08, docs/11 API-01).

Fonctions pures (testables sans réseau) :
- résolution des schémas de réponse ($ref, nullable OpenAPI 3.0),
- validation du payload par jsonschema (types, required, nested, enum),
- détection d'un contrat de pagination et comparaison page 1 vs page 2.

Règle docs/08 : un comportement NON documenté n'est PAS une violation de contrat —
on le note `not_documented` sans le compter comme violation.
"""

from __future__ import annotations

from typing import Any

import jsonschema

PAGINATION_PARAM_NAMES = {"page", "size", "limit", "offset", "per_page", "page_size"}
PAGINATION_RESPONSE_HINTS = {"page", "total", "total_pages", "items", "results", "data"}


# ---------- Résolution OpenAPI ----------

def resolve_ref(spec: dict, node: Any, depth: int = 0) -> Any:
    """Résout récursivement les $ref internes (components/...) avec garde anti-cycle."""
    if depth > 12:
        return node
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            target: Any = spec
            for part in ref[2:].split("/"):
                if not isinstance(target, dict) or part not in target:
                    return node  # ref non résoluble : on garde le nœud tel quel
                target = target[part]
            return resolve_ref(spec, target, depth + 1)
        return {k: resolve_ref(spec, v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_ref(spec, v, depth + 1) for v in node]
    return node


def resolve_response_schema(spec: dict, path: str, method: str, status: str = "200") -> dict | None:
    """Schéma JSON de la réponse (content application/json) ou None si non documenté."""
    path_item = (spec.get("paths") or {}).get(path) or {}
    op = path_item.get(method.lower()) or {}
    responses = op.get("responses") or {}
    node = responses.get(status) or responses.get(str(status)[0] + "XX") or responses.get("default")
    if node is None:
        return None
    node = resolve_ref(spec, node)
    content = node.get("content") if isinstance(node, dict) else None
    if not isinstance(content, dict):
        return None
    schema = media.get("schema") if isinstance((media := content.get("application/json") or {}), dict) else None
    if not isinstance(schema, dict):
        return None
    return _normalize_nullable(resolve_ref(spec, schema))


def _normalize_nullable(schema: dict) -> dict:
    """OpenAPI 3.0 `nullable: true` → anyOf [..., null] (dialecte jsonschema)."""
    if not isinstance(schema, dict):
        return schema
    if schema.get("nullable") is True:
        base = {k: v for k, v in schema.items() if k != "nullable"}
        return {"anyOf": [base, {"type": "null"}]}
    return {k: _normalize_nullable(v) if isinstance(v, dict) else v for k, v in schema.items()}


# ---------- Validation de payload ----------

def validate_payload_against_schema(payload: Any, schema: dict, max_violations: int = 50) -> list[dict]:
    """Valide le payload et retourne des violations traçables (JSON Pointer + attendu/observé)."""
    violations: list[dict] = []
    validator_cls = jsonschema.validators.validator_for(schema)
    validator = validator_cls(schema)
    for error in validator.iter_errors(payload):
        if len(violations) >= max_violations:
            violations.append({
                "pointer": "-",
                "rule": "max_violations_truncated",
                "expected": "-",
                "actual": f"> {max_violations} erreurs",
                "message": "trop de violations — liste tronquée",
            })
            break
        violations.append({
            "pointer": "$" + ("".join(f"/{p}" for p in error.absolute_path) or ""),
            "rule": f"schema:{error.validator}",
            "expected": jsonsafe(error.schema) if isinstance(error.schema, (dict, list)) else error.schema,
            "actual": jsonsafe(error.instance),
            "message": error.message[:300],
        })
    return violations


def jsonsafe(value: Any) -> Any:
    try:
        import json

        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)[:200]


# ---------- Pagination ----------

def detect_pagination_params(spec: dict, path: str, method: str) -> list[str]:
    """Paramètres de requête du contrat qui ressemblent à de la pagination."""
    op = ((spec.get("paths") or {}).get(path) or {}).get(method.lower()) or {}
    params = resolve_ref(spec, op.get("parameters") or [])
    names = []
    for p in params:
        if isinstance(p, dict) and p.get("in") == "query" and str(p.get("name", "")).lower() in PAGINATION_PARAM_NAMES:
            names.append(str(p["name"]))
    return names


def compare_paginated_responses(page1: Any, page2: Any) -> dict | None:
    """Compare deux pages : identiques → pagination non implémentée (violation)."""
    if not isinstance(page1, dict) or not isinstance(page2, dict):
        return None
    items1 = _first_list(page1)
    items2 = _first_list(page2)
    if items1 is None or items2 is None:
        return None
    if not items1:
        return None  # rien à comparer (données vides) — pas une violation
    fingerprint1 = _fingerprint(items1)
    fingerprint2 = _fingerprint(items2)
    if fingerprint1 == fingerprint2:
        return {
            "pointer": "$",
            "rule": "pagination_not_implemented",
            "expected": "page=2 renvoie des enregistrements différents de page=1",
            "actual": "page=1 et page=2 renvoient le même contenu",
            "message": "le paramètre de pagination est ignoré par le serveur (contrat documenté)",
        }
    return None


def _first_list(payload: dict) -> list | None:
    for key in ("items", "results", "data", "records"):
        v = payload.get(key)
        if isinstance(v, list):
            return v
    for v in payload.values():
        if isinstance(v, list):
            return v
    return None


def _fingerprint(items: list) -> Any:
    """Empreinte stable du contenu d'une page (ids si présents, sinon hash du contenu)."""
    import json

    if items and all(isinstance(i, dict) and "id" in i for i in items):
        return [i["id"] for i in items]
    return json.dumps(items, sort_keys=True, ensure_ascii=False)
