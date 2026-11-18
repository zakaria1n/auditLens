"""API de test pour auditer AuditLens (docs/08, docs/12) — anomalies contrôlées et documentées.

Anomalies PLANTÉES (l'audit doit les détecter) :
  A1. GET /orders/{id} avec id=999 → 500 au lieu du 404 documenté (contrat d'erreur violé)
  A2. GET /invoices → champ `total` renvoyé en STRING au lieu de number (schéma OpenAPI violé)
  A3. GET /orders?page=N → pagination cassée : page 2 renvoie la même chose que page 1
  A4. GET /orders/3 → 500 : visible UNIQUEMENT en appel dépendant (détail d'une commande
      découverte dans la liste) — un audit à couverture fixe (endpoints déclarés seuls) la manque
  A5. GET /orders/7 : statut "confirmed" dans la LISTE mais "cancelled" dans le DÉTAIL
      (contradiction interne liste/détail — hors contrat, uniquement par investigation)
  A6. GET /reports → instable : 503 aux 2 premiers appels puis 200 (récupération/réessai)
  CMD-1042 (id 42) : total 999.0 côté API — doit être recoupé avec une source externe
      (corrélation cross-source : le même ordre porte un montant différent dans le fichier)
  /health : endpoint VIVANT mais NON documenté dans le contrat → ne doit PAS produire de violation
Conforme :
  - GET /products → 200 + schéma OK
  - GET /orders → 200 + schéma OK (les en-têtes seulement)

Lancer : uv run uvicorn test_services.api_service:app --port 8080
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse

app = FastAPI(
    title="API Facturation de test (AuditLens)",
    version="1.0.0",
    description="Service de démonstration avec anomalies contrôlées pour l'évaluation d'audit.",
)

_ORDERS = [
    {"id": i, "ref": f"CMD-{1000 + i}", "customer": f"CUST-{i % 5}", "total": round(100.0 * i, 2), "status": "confirmed"}
    for i in range(1, 21)
]
# Cas « legit_credit » : la commande 4 porte un total NÉGATIF visible dans la liste
# (apparente anomalie) — son DÉTAIL révèle l'explication légitime (avoir / credit_note).
_ORDERS[3] = {"id": 4, "ref": "CMD-1004", "customer": "CUST-4", "total": -50.0, "status": "confirmed"}
# A5 : le détail de la commande 7 contredit la liste (cancelled vs confirmed)
# E : commande CMD-1042 (id 42) présente dans la liste pour corrélation cross-source
_ORDERS.append({"id": 42, "ref": "CMD-1042", "customer": "CUST-2", "total": 999.0, "status": "confirmed"})
_FLAKY_CALLS = {"count": 0}  # A6 : compteur d'appels pour l'instabilité simulée
_EXPORT_CALLS = {"count": 0}  # export : échec PERMANENT (chaque appel → 500)
_INVOICES = [
    {"id": i, "order_ref": f"CMD-{1000 + i}", "total": str(round(100.0 * i, 2)), "paid": i % 2 == 0}  # A2: string !
    for i in range(1, 6)
]
_PRODUCTS = [
    {"sku": "P-001", "name": "Clavier mécanique", "price": 49.9},
    {"sku": "P-002", "name": "Souris sans fil", "price": 19.9},
    {"sku": "P-003", "name": "Écran 27\"", "price": 199.0},
]


@app.get("/contract.json", include_in_schema=False)
def hand_written_contract():
    """Contrat OpenAPI 3.0 écrit à la main (réaliste : le contrat documente l'ATTENDU,
    l'implémentation diverge — c'est précisément ce que l'audit doit détecter)."""
    import json

    contract = {
        "openapi": "3.0.3",
        "info": {"title": "API Facturation de test (AuditLens)", "version": "1.0.0"},
        "paths": {
            "/products": {
                "get": {
                    "operationId": "list_products",
                    "responses": {
                        "200": {
                            "description": "Liste des produits",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ProductList"}}},
                        }
                    },
                }
            },
            "/orders": {
                "get": {
                    "operationId": "list_orders",
                    "parameters": [
                        {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                        {"name": "size", "in": "query", "schema": {"type": "integer", "default": 10}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Commandes paginées (le contrat exige une pagination effective)",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/OrderPage"}}},
                        }
                    },
                }
            },
            "/orders/{order_id}": {
                "get": {
                    "operationId": "get_order",
                    "parameters": [
                        {"name": "order_id", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                    "responses": {
                        "200": {"description": "Commande", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Order"}}}},
                        "404": {
                            "description": "Commande inexistante",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                        },
                    },
                }
            },
            "/invoices": {
                "get": {
                    "operationId": "list_invoices",
                    "responses": {
                        "200": {
                            "description": "Factures",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/InvoiceList"}}},
                        }
                    },
                }
            },
            "/export": {
                "get": {
                    "operationId": "export_data",
                    "responses": {
                        "200": {
                            "description": "Export des données",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ExportResult"}}},
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "Product": {
                    "type": "object",
                    "required": ["sku", "name", "price"],
                    "properties": {
                        "sku": {"type": "string"},
                        "name": {"type": "string"},
                        "price": {"type": "number"},
                    },
                },
                "ProductList": {
                    "type": "object",
                    "required": ["items", "count"],
                    "properties": {
                        "items": {"type": "array", "items": {"$ref": "#/components/schemas/Product"}},
                        "count": {"type": "integer"},
                    },
                },
                "Order": {
                    "type": "object",
                    "required": ["id", "ref", "customer", "total", "status"],
                    "properties": {
                        "id": {"type": "integer"},
                        "ref": {"type": "string"},
                        "customer": {"type": "string"},
                        "total": {"type": "number"},
                        "status": {"type": "string", "enum": ["draft", "confirmed", "cancelled"]},
                    },
                },
                "OrderPage": {
                    "type": "object",
                    "required": ["items", "page", "total"],
                    "properties": {
                        "items": {"type": "array", "items": {"$ref": "#/components/schemas/Order"}},
                        "page": {"type": "integer"},
                        "total": {"type": "integer"},
                    },
                },
                "ErrorResponse": {
                    "type": "object",
                    "required": ["error"],
                    "properties": {
                        "error": {"type": "string"},
                        "detail": {"type": "object"},
                    },
                },
                "Invoice": {
                    "type": "object",
                    "required": ["id", "order_ref", "total", "paid"],
                    "properties": {
                        "id": {"type": "integer"},
                        "order_ref": {"type": "string"},
                        "total": {"type": "number"},
                        "paid": {"type": "boolean"},
                    },
                },
                "InvoiceList": {
                    "type": "object",
                    "required": ["items", "count"],
                    "properties": {
                        "items": {"type": "array", "items": {"$ref": "#/components/schemas/Invoice"}},
                        "count": {"type": "integer"},
                    },
                },
                "ExportResult": {
                    "type": "object",
                    "required": ["items", "count"],
                    "properties": {
                        "items": {"type": "array", "items": {"type": "object"}},
                        "count": {"type": "integer"},
                    },
                },
            }
        },
    }
    return Response(content=json.dumps(contract), media_type="application/json")


@app.get("/openapi.json", include_in_schema=False)
def openapi_override():  # FastAPI génère /openapi.json : on laisse le sien
    from fastapi.openapi.utils import get_openapi

    return get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)


@app.get("/products", operation_id="list_products", summary="Liste des produits")
def list_products():
    return {"items": _PRODUCTS, "count": len(_PRODUCTS)}


@app.get("/orders", operation_id="list_orders", summary="Commandes paginées")
def list_orders(page: int = 1, size: int = 10):
    # A3 : pagination cassée — le paramètre page est IGNORÉ volontairement
    start = 0
    items = _ORDERS[start:start + size]
    return {"items": items, "page": page, "total": len(_ORDERS)}


@app.get("/orders/{order_id}", operation_id="get_order", summary="Détail d'une commande")
def get_order(order_id: int):
    if order_id == 999:
        # A1 : le contrat documente 404 ici, mais le serveur plante en 500
        raise RuntimeError("boom: KeyError 'customer_id' (anomalie plantée A1)")
    if order_id == 3:
        # A4 : plantée sur un id de la LISTE (visible en investigation) — le détail plante
        raise RuntimeError("boom: KeyError 'shipping_address' (anomalie plantée A4)")
    if order_id == 7:
        # A5 : le détail contredit la liste (annulée vs confirmée) — hors contrat
        return {"id": 7, "ref": "CMD-1007", "customer": "CUST-2", "total": 700.0, "status": "cancelled"}
    if order_id == 4:
        # legit_credit : le détail révèle l'explication légitime du total négatif (avoir)
        return {"id": 4, "ref": "CMD-1004", "customer": "CUST-4", "total": -50.0,
                "status": "confirmed", "type": "credit_note",
                "credit_for": "CMD-1003"}
    if order_id == 42:
        # E : CMD-1042 — le montant doit être recoupé avec une source externe (999 vs fichier)
        return {"id": 42, "ref": "CMD-1042", "customer": "CUST-2", "total": 999.0, "status": "confirmed"}
    for o in _ORDERS:
        if o["id"] == order_id:
            return o
    raise HTTPException(status_code=404, detail={"error": "not_found", "order_id": order_id})


@app.get("/reports", operation_id="list_reports", summary="Rapports générés (endpoint d'étude de stabilité)")
def list_reports():
    # A6 : 503 aux 2 premiers appels puis 200 — l'agent doit réessayer/documenter l'instabilité
    _FLAKY_CALLS["count"] += 1
    if _FLAKY_CALLS["count"] <= 2:
        return JSONResponse(status_code=503, content={"error": "temporarily_unavailable",
                                                      "attempt": _FLAKY_CALLS["count"]})
    return {"items": [{"report_id": "R-001", "period": "2026-10", "total": 4200.0}], "count": 1}


@app.get("/export", operation_id="export_data", summary="Export des données (documenté, en échec permanent)")
def export_data():
    # Cas « transient_vs_persistent » : échec 500 SYSTÉMATIQUE — une re-vérification
    # temporelle doit conclure « persistant », jamais « transitoire ».
    _EXPORT_CALLS["count"] += 1
    raise RuntimeError(f"boom: export worker crashed (échec permanent, appel {_EXPORT_CALLS['count']})")


@app.post("/__reset_flaky", include_in_schema=False)
def reset_flaky():
    """Réinitialise les compteurs d'instabilité (fixture de test — l'évaluation appelle
    ce reset AVANT chaque exécution pour que le scénario 503×2→200 soit reproductible)."""
    _FLAKY_CALLS["count"] = 0
    _EXPORT_CALLS["count"] = 0
    return {"ok": True}


@app.get("/external_orders", operation_id="external_orders", summary="Flux externe « partenaire » (scénario corrélation inter-sources)")
def external_orders():
    # E : référence S00002 (commande RÉELLE de l'ERP de test) avec un montant externe
    # volontairement différent de celui de l'ERP — l'agent doit recouper les deux sources.
    return {"items": [
        {"order_ref": "S00002", "partner": "CUST-2", "external_total": 999999.0, "currency": "MAD"},
    ], "count": 1}


@app.get("/health", operation_id="health", summary="Sonde de vivacité (non documentée au contrat)")
def health():
    # VIVANT et sain : ne doit JAMAIS produire de violation (non documenté ≠ violation, docs/08)
    return {"status": "ok"}


@app.get("/invoices", operation_id="list_invoices", summary="Factures")
def list_invoices():
    return {"items": _INVOICES, "count": len(_INVOICES)}


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request, exc: RuntimeError):
    return JSONResponse(status_code=500, content={"error": "internal_error", "detail": str(exc)})
