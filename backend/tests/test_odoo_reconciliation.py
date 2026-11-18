"""Tests de régression — réconciliation Odoo déterministe (problèmes B de la mission).

Scénarios synthétiques (aucune valeur codée en dur côté production : le module ne voit
que les preuves passées en argument) :
- contradiction mouvements ↔ qty_delivered (10 faits vs 1 déclaré)
- référence de picking orpheline (achat non collecté / inexistant)
- stock on-hand négatif (stock.quant)
- avoir (out_refund) neutralisant une sur-facturation
- facturation anticipée (facturé > livré, dans le volume commandé)
- chronologie facture avant commande
"""

from __future__ import annotations

from app.audit.odoo_reconciliation import reconcile


def _m2o(id_: int, name: str) -> list:
    return [id_, name]


def test_move_vs_delivered_mismatch_is_confirmed():
    """La contradiction détectée sur TP_zakaria : 10 sorties physiques vs qty_delivered=1."""
    result = reconcile(
        orders=[{"name": "S00002", "state": "sale", "date_order": "2026-10-05 20:33:00"}],
        order_lines=[{
            "order_id": _m2o(2, "S00002"), "product_id": _m2o(1, "HP"),
            "product_uom_qty": 1.0, "qty_delivered": 1.0, "qty_invoiced": 1.0,
            "display_type": False,
        }],
        invoices=[{"name": "FAC/00001", "move_type": "out_invoice", "ref": "S00002",
                   "invoice_date": "2026-10-05"}],
        invoice_lines=[{"move_id": _m2o(1, "FAC/00001"), "product_id": _m2o(1, "HP"),
                        "quantity": 1.0, "display_type": False}],
        stock_moves=[{"picking_id": _m2o(3, "WH/OUT/00001"), "product_id": _m2o(1, "HP"),
                      "quantity": 10.0, "state": "done", "reference": "WH/OUT/00001"}],
        pickings=[{"name": "WH/OUT/00001", "origin": "S00002", "state": "done"}],
    )
    v = next(v for v in result["violations"] if v["rule_id"] == "ERP-02-R1-move_vs_delivered_mismatch")
    assert v["kind"] == "confirmed"
    assert v["severity_hint"] == "high"
    assert v["values"]["moves_qty"] == 10.0 and v["values"]["qty_delivered"] == 1.0


def test_orphan_picking_origin_flagged_and_purchase_close():
    result = reconcile(
        orders=[{"name": "S00002", "state": "sale", "date_order": "2026-10-05"}],
        order_lines=[{"order_id": _m2o(2, "S00002"), "product_id": _m2o(1, "HP"),
                      "product_uom_qty": 1.0, "qty_delivered": 1.0, "qty_invoiced": 1.0,
                      "display_type": False}],
        invoices=[], invoice_lines=[],
        stock_moves=[
            {"picking_id": _m2o(1, "WH/IN/00001"), "product_id": _m2o(1, "HP"),
             "quantity": 50.0, "state": "done", "reference": "WH/IN/00001"},
            {"picking_id": _m2o(2, "WH/IN/00002"), "product_id": _m2o(1, "HP"),
             "quantity": 50.0, "state": "done", "reference": "WH/IN/00002"},
        ],
        pickings=[
            {"name": "WH/IN/00001", "origin": "P00001", "state": "done"},  # P00001 n'existe pas
            {"name": "WH/IN/00002", "origin": "P00003", "state": "done"},  # P00003 collecté
        ],
        purchases=[{"name": "P00003", "state": "purchase"}],
    )
    orphan = next(v for v in result["violations"] if v["rule_id"] == "CROSS-01-R7-orphan_picking_origin")
    assert orphan["values"]["origin"] == "P00001"
    assert all("P00003" not in (v["values"].get("origin") or "") for v in result["violations"])
    # limitation présente quand achats manquants ; ici achats fournis → pas de limitation orphan
    assert not any(l["scope"] == "orphan_check" for l in result["limitations"])


def test_negative_on_hand_quant_is_confirmed():
    result = reconcile(
        orders=[], order_lines=[], invoices=[], invoice_lines=[],
        stock_moves=[], pickings=[],
        quants=[{"product_id": _m2o(1, "HP"), "location_id": _m2o(12, "WH/Stock"),
                 "quantity": -100.0, "reserved_quantity": 0.0}],
    )
    v = next(v for v in result["violations"] if v["rule_id"] == "STOCK-01-R8-negative_on_hand")
    assert v["kind"] == "confirmed" and v["values"]["on_hand"] == -100.0


def test_refund_neutralizes_over_invoicing():
    """Avoir documenté : la quantité remboursée neutralise la sur-facturation brute."""
    result = reconcile(
        orders=[{"name": "S00001", "state": "sale", "date_order": "2026-09-01"}],
        order_lines=[{"order_id": _m2o(1, "S00001"), "product_id": _m2o(1, "HP"),
                      "product_uom_qty": 2.0, "qty_delivered": 2.0, "qty_invoiced": 3.0,
                      "display_type": False}],  # 3 facturées > 2 commandées
        invoices=[
            {"name": "FAC/00001", "move_type": "out_invoice", "ref": "S00001", "invoice_date": "2026-09-02"},
            {"name": "AVR/00001", "move_type": "out_refund", "ref": "S00001", "invoice_date": "2026-09-05"},
        ],
        invoice_lines=[
            {"move_id": _m2o(1, "FAC/00001"), "product_id": _m2o(1, "HP"), "quantity": 3.0, "display_type": False},
            {"move_id": _m2o(2, "AVR/00001"), "product_id": _m2o(1, "HP"), "quantity": 1.0, "display_type": False},
        ],
        stock_moves=[], pickings=[],
    )
    assert not any(v["rule_id"] == "ERP-01-R4-over_invoicing" for v in result["violations"])
    assert any(o["rule_id"] == "ERP-01-OBS-refund_detected" for o in result["observations"])


def test_invoiced_not_delivered_is_suspicious_not_confirmed():
    """Facturation anticipée dans le volume commandé : situation à investiguer, pas une violation confirmée."""
    result = reconcile(
        orders=[{"name": "S00001", "state": "sale", "date_order": "2026-09-01"}],
        order_lines=[{"order_id": _m2o(1, "S00001"), "product_id": _m2o(1, "HP"),
                      "product_uom_qty": 5.0, "qty_delivered": 1.0, "qty_invoiced": 3.0,
                      "display_type": False}],
        invoices=[], invoice_lines=[],
        stock_moves=[], pickings=[],
    )
    v = next(v for v in result["violations"] if v["rule_id"] == "ERP-01-R5-invoiced_not_delivered")
    assert v["kind"] == "suspicious"


def test_invoice_before_order_is_suspicious():
    result = reconcile(
        orders=[{"name": "S00009", "state": "sale", "date_order": "2026-10-10"}],
        order_lines=[{"order_id": _m2o(9, "S00009"), "product_id": _m2o(1, "HP"),
                      "product_uom_qty": 1.0, "qty_delivered": 1.0, "qty_invoiced": 1.0,
                      "display_type": False}],
        invoices=[{"name": "FAC/00009", "move_type": "out_invoice", "ref": "S00009",
                   "invoice_date": "2026-10-01"}],  # avant la commande
        invoice_lines=[{"move_id": _m2o(9, "FAC/00009"), "product_id": _m2o(1, "HP"),
                        "quantity": 1.0, "display_type": False}],
        stock_moves=[], pickings=[],
    )
    v = next(v for v in result["violations"] if v["rule_id"] == "ERP-01-R6-invoice_before_order")
    assert v["kind"] == "suspicious"


def test_clean_dataset_produces_no_violations():
    result = reconcile(
        orders=[{"name": "S00001", "state": "sale", "date_order": "2026-09-01"}],
        order_lines=[{"order_id": _m2o(1, "S00001"), "product_id": _m2o(1, "HP"),
                      "product_uom_qty": 2.0, "qty_delivered": 2.0, "qty_invoiced": 2.0,
                      "display_type": False}],
        invoices=[{"name": "FAC/00001", "move_type": "out_invoice", "ref": "S00001",
                   "invoice_date": "2026-09-02"}],
        invoice_lines=[{"move_id": _m2o(1, "FAC/00001"), "product_id": _m2o(1, "HP"),
                        "quantity": 2.0, "display_type": False}],
        stock_moves=[{"picking_id": _m2o(1, "WH/OUT/00001"), "product_id": _m2o(1, "HP"),
                      "quantity": 2.0, "state": "done", "reference": "WH/OUT/00001"}],
        pickings=[{"name": "WH/OUT/00001", "origin": "S00001", "state": "done"}],
        purchases=[{"name": "P00001", "state": "purchase"}],
        quants=[{"product_id": _m2o(1, "HP"), "location_id": _m2o(12, "WH/Stock"),
                 "quantity": 42.0, "reserved_quantity": 2.0}],
    )
    assert result["violations"] == []
    assert result["stats"]["confirmed"] == 0 and result["stats"]["suspicious"] == 0
