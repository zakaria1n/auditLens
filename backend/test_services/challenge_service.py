"""Plateforme « order-to-cash » de test pour le DÉFI D'AUDIT INDÉPENDANT AuditLens (port 8090).

Environnement ISOLÉ, identifiants frais, mécaniques d'anomalies différentes des cas de
développement (8080). La vérité de terrain n'est documentée QUE dans le rapport final
d'évaluation — jamais dans ce fichier sous forme de commentaires révélant les réponses.

Processus métier : commande → expédition → facture → paiement (+ avoirs).
Certaines chaînes sont parfaitement saines ; d'autres non (l'agent doit distinguer).

Lancer : uv run uvicorn test_services.challenge_service:app --port 8090
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(
    title="Plateforme Order-to-Cash (défi AuditLens)",
    version="2.0.0",
    description="Environnement d'audit indépendant — données synthétiques isolées.",
)

# ---------------------------------------------------------------- données (identifiants frais)

_CUSTOMERS = {
    "CL-101": {"name": "Atlas Distribution", "city": "Casablanca"},
    "CL-102": {"name": "Nord Import SA", "city": "Rabat"},
    "CL-103": {"name": "Sahara Équipements", "city": "Marrakech"},
    "CL-104": {"name": "Rif Négoce", "city": "Tanger"},
    "CL-105": {"name": "Zertia Logistique", "city": "Agadir"},
    "CL-106": {"name": "Meridian Conseil", "city": "Casablanca"},
}

_ORDERS = [
    {"ref": "OC-7701", "customer": "CL-101", "qty": 8, "unit_price": 320.0, "total": 2560.0, "status": "completed"},
    {"ref": "OC-7702", "customer": "CL-102", "qty": 5, "unit_price": 540.0, "total": 2700.0, "status": "cancelled"},
    {"ref": "OC-7703", "customer": "CL-103", "qty": 12, "unit_price": 185.5, "total": 2226.0, "status": "completed"},
    {"ref": "OC-7704", "customer": "CL-101", "qty": 3, "unit_price": 890.0, "total": 2670.0, "status": "completed"},
    {"ref": "OC-7705", "customer": "CL-104", "qty": 10, "unit_price": 415.0, "total": 4150.0, "status": "completed"},
    {"ref": "OC-7706", "customer": "CL-105", "qty": 6, "unit_price": 240.0, "total": 1440.0, "status": "completed"},
    {"ref": "OC-7707", "customer": "CL-102", "qty": 15, "unit_price": 96.0, "total": 1440.0, "status": "completed"},
    {"ref": "OC-7708", "customer": "CL-103", "qty": 9, "unit_price": 520.0, "total": 4680.0, "status": "completed"},
    {"ref": "OC-7709", "customer": "CL-106", "qty": 4, "unit_price": 610.0, "total": 2440.0, "status": "completed"},
    {"ref": "OC-7710", "customer": "CL-104", "qty": 7, "unit_price": 350.0, "total": 2450.0, "status": "completed"},
    {"ref": "OC-7711", "customer": "CL-105", "qty": 11, "unit_price": 128.0, "total": 1408.0, "status": "completed"},
    {"ref": "OC-7712", "customer": "CL-101", "qty": 2, "unit_price": 990.0, "total": 1980.0, "status": "completed"},
]

_SHIPMENTS = [
    {"ref": "SH-301", "order": "OC-7701", "qty": 8, "carrier": "Transmaroc"},
    {"ref": "SH-302", "order": "OC-7703", "qty": 12, "carrier": "Transmaroc"},
    {"ref": "SH-303", "order": "OC-7704", "qty": 3, "carrier": "Rapidex"},
    {"ref": "SH-304", "order": "OC-7706", "qty": 6, "carrier": "Rapidex"},
    {"ref": "SH-305", "order": "OC-7707", "qty": 15, "carrier": "Transmaroc"},
    {"ref": "SH-306", "order": "OC-7709", "qty": 4, "carrier": "Speedline"},
    {"ref": "SH-307", "order": "OC-7711", "qty": 11, "carrier": "Rapidex"},
    {"ref": "SH-308", "order": "OC-7712", "qty": 2, "carrier": "Speedline"},
    {"ref": "SH-309", "order": "OC-7705", "qty": 6, "carrier": "Transmaroc"},
    {"ref": "SH-310", "order": "OC-7705", "qty": 7, "carrier": "Transmaroc"},
]

_INVOICES = [
    {"ref": "FA-901", "order": "OC-7701", "customer": "CL-101", "amount": 2560.0, "status": "paid"},
    {"ref": "FA-903", "order": "OC-7703", "customer": "CL-103", "amount": 2226.0, "status": "paid"},
    {"ref": "FA-904", "order": "OC-7704", "customer": "CL-101", "amount": 2670.0, "status": "paid"},
    {"ref": "FA-905", "order": "OC-7705", "customer": "CL-104", "amount": 4150.0, "status": "paid"},
    {"ref": "FA-906", "order": "OC-7706", "customer": "CL-105", "amount": 1440.0, "status": "paid"},
    {"ref": "FA-907", "order": "OC-7707", "customer": "CL-102", "amount": 1440.0, "status": "paid"},
    {"ref": "FA-908", "order": "OC-7708", "customer": "CL-103", "amount": 4680.0, "status": "paid"},
    {"ref": "FA-909", "order": "OC-7709", "customer": "CL-106", "amount": 2440.0, "status": "paid"},
    {"ref": "FA-911", "order": "OC-7710", "customer": "CL-104", "amount": 2450.0, "status": "paid"},
    {"ref": "FA-912", "order": "OC-7711", "customer": "CL-105", "amount": 1408.0, "status": "paid"},
    {"ref": "FA-913", "order": "OC-7712", "customer": "CL-101", "amount": 1980.0, "status": "paid"},
]

_PAYMENTS = [
    {"ref": "PM-501", "invoice": "FA-901", "payer": "CL-101", "amount": 2560.0, "method": "virement"},
    {"ref": "PM-503", "invoice": "FA-903", "payer": "CL-103", "amount": 2226.0, "method": "cheque"},
    {"ref": "PM-504", "invoice": "FA-907", "payer": "CL-104", "amount": 1250.0, "method": "virement"},
    {"ref": "PM-505", "invoice": "FA-905", "payer": "CL-104", "amount": 4150.0, "method": "virement"},
    {"ref": "PM-506", "invoice": "FA-906", "payer": "CL-105", "amount": 1440.0, "method": "cheque"},
    {"ref": "PM-507", "invoice": "FA-907", "payer": "CL-102", "amount": 1440.0, "method": "virement"},
    {"ref": "PM-508", "invoice": "FA-908", "payer": "CL-103", "amount": 2880.0, "method": "virement"},
    {"ref": "PM-509", "invoice": "FA-909", "payer": "CL-106", "amount": 890.5, "method": "virement"},
    {"ref": "PM-510", "invoice": "FA-912", "payer": "CL-105", "amount": 1408.0, "method": "cheque"},
    {"ref": "PM-511", "invoice": "FA-913", "payer": "CL-101", "amount": 1980.0, "method": "virement"},
]

_CREDIT_NOTES = [
    # Avoir lié à un retour : transaction inhabituelle mais LÉGITIME (l'agent doit le reconnaître)
    {"ref": "AV-902", "order": "OC-7708", "customer": "CL-103", "amount": -1800.0,
     "reason": "return", "linked_shipment": "SH-306B"},
    {"ref": "AV-910", "order": "OC-7701", "customer": "CL-101", "amount": -320.0,
     "reason": "discount", "linked_shipment": None},
]

_FLAKY_STATE = {"count": 0}


@app.post("/__reset_transient", include_in_schema=False)
def reset_transient():
    _FLAKY_STATE["count"] = 0
    return {"ok": True}


@app.get("/contract.json", include_in_schema=False)
def contract():
    import json

    num = {"type": "number"}
    order_schema = {
        "type": "object", "required": ["ref", "customer", "qty", "unit_price", "total", "status"],
        "properties": {"ref": {"type": "string"}, "customer": {"type": "string"},
                        "qty": {"type": "integer"}, "unit_price": num, "total": num,
                        "status": {"type": "string", "enum": ["completed", "cancelled", "draft"]}},
    }
    c = {
        "openapi": "3.0.3",
        "info": {"title": "Plateforme Order-to-Cash (défi AuditLens)", "version": "2.0.0"},
        "paths": {
            "/orders": {"get": {"operationId": "list_orders", "parameters": [
                {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                {"name": "size", "in": "query", "schema": {"type": "integer", "default": 10}},
            ], "responses": {"200": {"description": "Commandes paginées",
                "content": {"application/json": {"schema": {"type": "object",
                    "required": ["items", "page", "total"],
                    "properties": {"items": {"type": "array", "items": {"$ref": "#/components/schemas/Order"}},
                                    "page": {"type": "integer"}, "total": {"type": "integer"}}}}}}}}},
            "/orders/{ref}": {"get": {"operationId": "get_order", "parameters": [
                {"name": "ref", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Commande",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Order"}}}},
                    "404": {"description": "Inconnue", "content": {"application/json": {"schema": {
                        "type": "object", "required": ["error"],
                        "properties": {"error": {"type": "string"}}}}}}}}},
            "/shipments": {"get": {"operationId": "list_shipments", "responses": {"200": {
                "description": "Expéditions", "content": {"application/json": {"schema": {"type": "object",
                    "required": ["items", "count"],
                    "properties": {"items": {"type": "array", "items": {"$ref": "#/components/schemas/Shipment"}},
                                    "count": {"type": "integer"}}}}}}}}},
            "/invoices": {"get": {"operationId": "list_invoices", "responses": {"200": {
                "description": "Factures", "content": {"application/json": {"schema": {"type": "object",
                    "required": ["items", "count"],
                    "properties": {"items": {"type": "array", "items": {"$ref": "#/components/schemas/Invoice"}},
                                    "count": {"type": "integer"}}}}}}}}},
            "/payments": {"get": {"operationId": "list_payments", "responses": {"200": {
                "description": "Paiements", "content": {"application/json": {"schema": {"type": "object",
                    "required": ["items", "count"],
                    "properties": {"items": {"type": "array", "items": {"$ref": "#/components/schemas/Payment"}},
                                    "count": {"type": "integer"}}}}}}}}},
            "/credit-notes": {"get": {"operationId": "list_credit_notes", "responses": {"200": {
                "description": "Avoirs", "content": {"application/json": {"schema": {"type": "object",
                    "required": ["items", "count"],
                    "properties": {"items": {"type": "array", "items": {"type": "object"}},
                                    "count": {"type": "integer"}}}}}}}}},
            "/audit-trail": {"get": {"operationId": "audit_trail", "responses": {"200": {
                "description": "Journal d'audit", "content": {"application/json": {"schema": {"type": "object",
                    "required": ["entries"],
                    "properties": {"entries": {"type": "array", "items": {"type": "object"}}}}}}}}}},
        },
        "components": {"schemas": {
            "Order": order_schema,
            "Shipment": {"type": "object", "required": ["ref", "order", "qty", "carrier"],
                          "properties": {"ref": {"type": "string"}, "order": {"type": "string"},
                                          "qty": {"type": "integer"}, "carrier": {"type": "string"}}},
            "Invoice": {"type": "object", "required": ["ref", "order", "customer", "amount", "status"],
                         "properties": {"ref": {"type": "string"}, "order": {"type": "string"},
                                         "customer": {"type": "string"}, "amount": num,
                                         "status": {"type": "string", "enum": ["paid", "open", "draft"]}}},
            "Payment": {"type": "object", "required": ["ref", "invoice", "payer", "amount", "method"],
                         "properties": {"ref": {"type": "string"}, "invoice": {"type": "string"},
                                         "payer": {"type": "string"}, "amount": num,
                                         "method": {"type": "string"}}},
        }},
    }
    return Response(content=json.dumps(c), media_type="application/json")


def _paged(items, page: int, size: int):
    start = (page - 1) * size
    return {"items": items[start:start + size], "page": page, "total": len(items)}


@app.get("/orders", operation_id="list_orders")
def list_orders(page: int = 1, size: int = 10):
    # Pagination EFFECTIVE (saine — ne doit pas être signalée)
    return _paged(_ORDERS, page, size)


@app.get("/orders/{ref}", operation_id="get_order")
def get_order(ref: str):
    for o in _ORDERS:
        if o["ref"] == ref:
            return o
    raise HTTPException(status_code=404, detail={"error": "not_found", "ref": ref})


@app.get("/shipments", operation_id="list_shipments")
def list_shipments():
    return {"items": _SHIPMENTS, "count": len(_SHIPMENTS)}


@app.get("/invoices", operation_id="list_invoices")
def list_invoices():
    return {"items": _INVOICES, "count": len(_INVOICES)}


@app.get("/payments", operation_id="list_payments")
def list_payments():
    return {"items": _PAYMENTS, "count": len(_PAYMENTS)}


@app.get("/credit-notes", operation_id="list_credit_notes")
def list_credit_notes():
    return {"items": _CREDIT_NOTES, "count": len(_CREDIT_NOTES)}


@app.get("/audit-trail", operation_id="audit_trail")
def audit_trail():
    # Service instable : indisponible au premier appel, opérationnel ensuite.
    _FLAKY_STATE["count"] += 1
    if _FLAKY_STATE["count"] == 1:
        return JSONResponse(status_code=503, content={"error": "temporarily_unavailable"})
    return {"entries": [
        {"at": "2026-11-12T09:14:00Z", "actor": "svc-billing", "action": "invoice_generated", "object": "FA-911"},
        {"at": "2026-11-12T10:02:00Z", "actor": "svc-cash", "action": "payment_recorded", "object": "PM-504"},
    ]}
