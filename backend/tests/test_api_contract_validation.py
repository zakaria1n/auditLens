"""Tests de régression — validation de contrat OpenAPI (problème A2/A3 de l'évaluation précédente).

Le contrat documente `total: number` ; l'implémentation renvoie une string (A2).
Le contrat documente une pagination `page` effective ; page=2 renvoie page=1 (A3).
Un statut non documenté (500 vs 200/404) est une violation de statut (A1).
Un comportement NON documenté ne doit PAS être rapporté comme violation.
"""

from __future__ import annotations

import httpx
import pytest

from app.audit.api_contract import (
    compare_paginated_responses,
    detect_pagination_params,
    resolve_response_schema,
    validate_payload_against_schema,
)

CONTRACT = {
    "openapi": "3.0.3",
    "paths": {
        "/invoices": {
            "get": {
                "responses": {
                    "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/InvoiceList"}}}}
                }
            }
        },
        "/orders": {
            "get": {
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer"}},
                    {"name": "size", "in": "query", "schema": {"type": "integer"}},
                ],
                "responses": {
                    "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/OrderPage"}}}}
                },
            }
        },
        "/mystery": {"get": {"responses": {}}},  # aucun schéma documenté
    },
    "components": {
        "schemas": {
            "InvoiceList": {
                "type": "object",
                "required": ["items", "count"],
                "properties": {
                    "items": {"type": "array", "items": {"$ref": "#/components/schemas/Invoice"}},
                    "count": {"type": "integer"},
                },
            },
            "Invoice": {
                "type": "object",
                "required": ["id", "total", "paid"],
                "properties": {
                    "id": {"type": "integer"},
                    "total": {"type": "number"},  # le contrat promet un NOMBRE
                    "paid": {"type": "boolean"},
                },
            },
            "OrderPage": {
                "type": "object",
                "required": ["items", "page"],
                "properties": {
                    "items": {"type": "array", "items": {"type": "object"}},
                    "page": {"type": "integer"},
                },
            },
        }
    },
}


def test_detects_type_mismatch_string_vs_number():
    """A2 — montant renvoyé en string alors que le contrat promet number."""
    payload = {"items": [{"id": 1, "total": "100.0", "paid": False}], "count": 1}
    schema = resolve_response_schema(CONTRACT, "/invoices", "get")
    assert schema is not None
    violations = validate_payload_against_schema(payload, schema)
    rules = [v["rule"] for v in violations]
    assert any("type" in r for r in rules), violations
    total_v = next(v for v in violations if "total" in v["pointer"])
    assert total_v["actual"] == "100.0"


def test_valid_payload_produces_no_violation():
    payload = {"items": [{"id": 1, "total": 100.0, "paid": True}], "count": 1}
    schema = resolve_response_schema(CONTRACT, "/invoices", "get")
    assert validate_payload_against_schema(payload, schema) == []


def test_missing_required_field_detected():
    payload = {"items": [], "count": 1}  # count présent mais "items" vide : OK ;
    # test séparé : count manquant
    payload_missing = {"items": []}
    schema = resolve_response_schema(CONTRACT, "/invoices", "get")
    violations = validate_payload_against_schema(payload_missing, schema)
    assert any(v["rule"].endswith("required") for v in violations)


def test_nullable_field_is_not_a_violation():
    contract = {
        "paths": {"/x": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {
            "type": "object", "properties": {"note": {"type": "string", "nullable": True}}
        }}}}}}}},
    }
    schema = resolve_response_schema(contract, "/x", "get")
    assert validate_payload_against_schema({"note": None}, schema) == []


def test_undocumented_endpoint_is_not_a_violation():
    """docs/08 : un comportement non documenté n'est PAS rapporté comme violation."""
    assert resolve_response_schema(CONTRACT, "/mystery", "get") is None
    assert detect_pagination_params(CONTRACT, "/mystery", "get") == []


def test_pagination_params_detected_and_probe_flags_identical_pages():
    """A3 — pagination documentée mais ignorée par le serveur."""
    assert set(detect_pagination_params(CONTRACT, "/orders", "get")) == {"page", "size"}
    page1 = {"items": [{"id": 1}, {"id": 2}], "page": 1}
    page2 = {"items": [{"id": 1}, {"id": 2}], "page": 2}  # mêmes items → cassée
    violation = compare_paginated_responses(page1, page2)
    assert violation is not None and violation["rule"] == "pagination_not_implemented"
    # pages réellement différentes → pas de violation
    page2_ok = {"items": [{"id": 3}], "page": 2}
    assert compare_paginated_responses(page1, page2_ok) is None
    # pages vides : rien à comparer, pas une violation
    assert compare_paginated_responses({"items": []}, {"items": []}) is None


def test_ref_resolution_follows_components():
    schema = resolve_response_schema(CONTRACT, "/invoices", "get")
    # le $ref imbriqué est résolu jusqu'au schéma Invoice (total: number)
    items_schema = schema["properties"]["items"]["items"]
    assert items_schema["properties"]["total"]["type"] == "number"
    assert items_schema["required"] == ["id", "total", "paid"]


# ---------- Intégration contre le service de test réel (skip si absent) ----------

def _service_up() -> bool:
    try:
        httpx.get("http://localhost:8080/products", timeout=2.0)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _service_up(), reason="service de test API (:8080) non démarré")
def test_live_contract_check_detects_A1_A2_A3():
    """Intégration : les 3 anomalies plantées du service sont détectées par la tool réelle."""
    import asyncio

    from app.audit.rules import get_rule_set  # noqa: F401 (garde-fou d'import)
    from app.connectors.api.connector import RestApiConnector

    async def run():
        connector = RestApiConnector(
            {
                "base_url": "http://localhost:8080",
                "openapi_url": "http://localhost:8080/contract.json",
                "allow_private_host": True,
                "endpoints": [
                    {"id": "products", "method": "GET", "path": "/products"},
                    {"id": "orders", "method": "GET", "path": "/orders"},
                    {"id": "invoices", "method": "GET", "path": "/invoices"},
                    {"id": "order_detail_999", "method": "GET", "path": "/orders/999"},
                ],
            },
            {},
        )
        spec_resp = await httpx.AsyncClient().get("http://localhost:8080/contract.json")
        spec = spec_resp.json()

        violations: list[dict] = []
        # A1 : statut non documenté
        trace = await connector.fetch("order_detail_999")
        assert trace["response"]["status"] == 500
        assert "500" not in (spec["paths"]["/orders/{order_id}"]["get"]["responses"] or {})
        # schéma non documenté pour 500 → pas de validation payload (undefined ≠ violation)
        assert resolve_response_schema(spec, "/orders/{order_id}", "get", "500") is None

        # A2 : schéma du 200 /invoices → type mismatch
        inv_trace = await connector.fetch("invoices")
        schema = resolve_response_schema(spec, "/invoices", "get", "200")
        violations = validate_payload_against_schema(inv_trace["response"]["json"], schema)
        assert any("total" in v["pointer"] and "type" in v["rule"] for v in violations)

        # A3 : sonde pagination
        params = detect_pagination_params(spec, "/orders", "get")
        assert params, "le contrat doit documenter page/size"
        p1 = (await connector.fetch("orders", filters={"page": 1}))["response"]["json"]
        p2 = (await connector.fetch("orders", filters={"page": 2}))["response"]["json"]
        v = compare_paginated_responses(p1, p2)
        assert v is not None and v["rule"] == "pagination_not_implemented"
        await connector.close()
        return violations

    found = asyncio.run(run())
    assert found, "A2 doit produire au moins une violation de schéma"
