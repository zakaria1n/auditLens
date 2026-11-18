"""Réconciliation Odoo déterministe (docs/11 ERP-01/ERP-02, CROSS-01) — fonctions pures.

Entrées : enregistrements collectés par les tools (evidence payloads), JAMAIS un accès
direct à Odoo ici. Aucune valeur codée en dur : tout vient des preuves du run.

Classification :
- `confirmed`   : contradiction interne dans une même source (ex. mouvements vs lignes)
- `suspicious`  : situation à investiguer (livraison partielle, avoir possible, ordre chronologique)

Champs Odoo utilisés (vérifiés par fields_get côté connecteur) :
- sale.order.line : product_uom_qty (commandé), qty_delivered, qty_invoiced, display_type
- account.move : move_type (out_invoice / out_refund), ref, invoice_date
- account.move.line : move_id, quantity
- stock.move : picking_id, product_id, quantity, state, date ; stock.picking : origin, name
- stock.quant : quantity (on-hand par emplacement)

Limites assumées : UoM multiples non converties (comparaison à unité produit égale),
multi-société non filtré, réservations ignorées.
"""

from __future__ import annotations

from typing import Any

EPSILON = 1e-6


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _m2o_name(v: Any) -> str:
    """Champ many2one Odoo : [id, 'nom'] → nom ; sinon ''."""
    if isinstance(v, list) and len(v) >= 2:
        return str(v[1])
    if isinstance(v, str):
        return v
    return ""


def _is_product_line(line: dict) -> bool:
    """Odoo 17+ : display_type False/None = ligne produit (les sections/notes sont textuelles)."""
    return not line.get("display_type")


def reconcile(
    *,
    orders: list[dict],
    order_lines: list[dict],
    invoices: list[dict],
    invoice_lines: list[dict],
    stock_moves: list[dict],
    pickings: list[dict],
    quants: list[dict] | None = None,
    purchases: list[dict] | None = None,
) -> dict[str, Any]:
    """Réconcilie quantités commandées / livrées / facturées / mouvements + références.

    Retourne {"violations": [...], "observations": [...], "limitations": [...],
              "stats": {...}} — chaque violation cite ses faits (noms, quantités).
    """
    violations: list[dict] = []
    observations: list[dict] = []
    limitations: list[dict] = []

    def add(kind: str, rule_id: str, severity_hint: str, subject: str, message: str, values: dict) -> None:
        violations.append({
            "kind": kind, "rule_id": rule_id, "severity_hint": severity_hint,
            "subject": subject, "message": message, "values": values,
        })

    # ---------- index ----------
    orders_by_name = {o.get("name"): o for o in orders if o.get("name")}
    order_lines_by_order = {}
    for line in order_lines:
        if not _is_product_line(line):
            continue
        parent = line.get("order_id")
        order_name = _m2o_name(parent) or (str(parent) if parent else "")
        order_lines_by_order.setdefault(order_name, []).append(line)

    invoice_names = {i.get("name") for i in invoices if i.get("name")}
    purchase_names = {p.get("name") for p in (purchases or []) if p.get("name")}

    # mouvements de stock "done" groupés par origine de picking
    picking_by_name = {p.get("name"): p for p in pickings if p.get("name")}
    done_moves_by_origin: dict[str, list[dict]] = {}
    for mv in stock_moves:
        if str(mv.get("state")) != "done":
            continue
        picking_name = _m2o_name(mv.get("picking_id")) or str(mv.get("reference") or "")
        picking = picking_by_name.get(picking_name, {})
        origin = picking.get("origin") or mv.get("reference") or ""
        mv = dict(mv)
        mv["_origin"] = origin
        done_moves_by_origin.setdefault(origin, []).append(mv)

    # ---------- 1. Réconciliation par ligne de commande ----------
    checked_lines = 0
    for order_name, lines in order_lines_by_order.items():
        order = orders_by_name.get(order_name, {})
        order_state = str(order.get("state") or "")
        order_date = str(order.get("date_order") or "")[:10]
        for line in lines:
            product = _m2o_name(line.get("product_id")) or "?"
            ordered = _num(line.get("product_uom_qty"))
            delivered = _num(line.get("qty_delivered"))
            invoiced = _num(line.get("qty_invoiced"))
            checked_lines += 1

            # R1 — contradiction mouvements ↔ qty_delivered (confirmée)
            moves = done_moves_by_origin.get(order_name, [])
            moves_qty = sum(_num(m.get("quantity")) for m in moves if _m2o_name(m.get("product_id")) == product)
            if moves and abs(moves_qty - delivered) > EPSILON and delivered > 0:
                add("confirmed", "ERP-02-R1-move_vs_delivered_mismatch", "high", order_name,
                    f"Mouvements de stock faits = {moves_qty:g} unités de {product} sur {order_name}, "
                    f"mais qty_delivered de la ligne = {delivered:g} — contradiction interne.",
                    {"order": order_name, "product": product, "moves_qty": moves_qty, "qty_delivered": delivered,
                     "picking": _m2o_name(moves[0].get("picking_id"))})
            elif delivered > ordered + EPSILON:
                # R2 — sur-livraison (confirmée au regard de la ligne)
                add("confirmed", "ERP-02-R2-over_delivery", "medium", order_name,
                    f"qty_delivered ({delivered:g}) > quantity ordered ({ordered:g}) pour {product}.",
                    {"order": order_name, "product": product, "ordered": ordered, "delivered": delivered})
            elif delivered + EPSILON < ordered and order_state in ("sale", "done"):
                # R3 — sous-livraison sur commande confirmée (partielle : à investiguer)
                add("suspicious", "ERP-02-R3-under_delivery_open_order", "low", order_name,
                    f"Commande confirmée partiellement livrée : {delivered:g}/{ordered:g} ({product}). "
                    "Livraison partielle légitime possible — à confirmer avec la logistique.",
                    {"order": order_name, "product": product, "ordered": ordered, "delivered": delivered})

            # R4 — sur-facturation nette d'avoirs (confirmée)
            net_invoiced = invoiced
            refunds = [i for i in invoices
                       if str(i.get("move_type")) == "out_refund" and str(i.get("ref") or "") == order_name]
            if refunds:
                refund_lines = [ln for ln in invoice_lines
                                if _m2o_name(ln.get("move_id")) in {r.get("name") for r in refunds}
                                and _is_product_line(ln)]
                refunded_qty = sum(_num(ln.get("quantity")) for ln in refund_lines
                                   if _m2o_name(ln.get("product_id")) == product)
                net_invoiced = invoiced - refunded_qty
                observations.append({
                    "rule_id": "ERP-01-OBS-refund_detected", "subject": order_name,
                    "message": f"Avoir(s) détecté(s) ({len(refunds)}) pour {product} : qté facturée brute "
                               f"{invoiced:g} − remboursée {refunded_qty:g} = net {net_invoiced:g}.",
                })
            if net_invoiced > ordered + EPSILON:
                add("confirmed", "ERP-01-R4-over_invoicing", "high", order_name,
                    f"Qté facturée nette ({net_invoiced:g}) > quantity ordered ({ordered:g}) pour {product}.",
                    {"order": order_name, "product": product, "ordered": ordered,
                     "invoiced": invoiced, "refunded": round(invoiced - net_invoiced, 2)})
            elif invoiced > delivered + EPSILON and net_invoiced <= ordered + EPSILON:
                # R5 — facturé > livré mais dans le volume commandé (politique de facturation anticipée possible)
                add("suspicious", "ERP-01-R5-invoiced_not_delivered", "medium", order_name,
                    f"Qté facturée ({invoiced:g}) > qté livrée ({delivered:g}) pour {product} — "
                    "facturation anticipée ou politique commerciale à confirmer.",
                    {"order": order_name, "product": product, "delivered": delivered, "invoiced": invoiced})

            # R6 — chronologie facture avant commande (suspect)
            for inv in invoices:
                if str(inv.get("ref") or "") == order_name and str(inv.get("move_type")) == "out_invoice":
                    inv_date = str(inv.get("invoice_date") or "")
                    if order_date and inv_date < order_date:
                        add("suspicious", "ERP-01-R6-invoice_before_order", "medium", order_name,
                            f"Facture {inv.get('name')} datée {inv_date}, antérieure à la commande "
                            f"({order_date}) — chronologie à justifier.",
                            {"order": order_name, "invoice": inv.get("name"),
                             "order_date": order_date, "invoice_date": inv_date})
                    break

    # ---------- 2. Références orphelines de pickings ----------
    known_refs = set(orders_by_name.keys()) | purchase_names | invoice_names
    if not purchases:
        limitations.append({
            "scope": "orphan_check",
            "message": "Commandes d'achat non collectées : les origins de type achat ne peuvent pas être vérifiées.",
        })
    for picking in pickings:
        origin = str(picking.get("origin") or "").strip()
        if not origin:
            continue
        if origin in known_refs:
            continue
        name = str(picking.get("name") or "?")
        add("suspicious", "CROSS-01-R7-orphan_picking_origin", "medium", name,
            f"Le picking {name} référence une origine '{origin}' absente des documents collectés "
            f"({len(known_refs)} références connues). Commande supprimée ou document externe — à investiguer.",
            {"picking": name, "origin": origin, "state": picking.get("state")})

    # ---------- 3. Quantités disponibles négatives ----------
    for q in quants or []:
        on_hand = _num(q.get("quantity"))
        if on_hand < -EPSILON:
            location = _m2o_name(q.get("location_id")) or "?"
            product = _m2o_name(q.get("product_id")) or "?"
            add("confirmed", "STOCK-01-R8-negative_on_hand", "high", product,
                f"Quantité disponible négative ({on_hand:g}) pour {product} à l'emplacement {location} "
                "— incohérence d'inventaire.",
                {"product": product, "location": location, "on_hand": on_hand,
                 "reserved": _num(q.get("reserved_quantity"))})

    return {
        "violations": violations,
        "observations": observations,
        "limitations": limitations,
        "stats": {
            "orders": len(orders), "order_lines_checked": checked_lines,
            "invoices": len(invoices), "stock_moves": len(stock_moves),
            "pickings": len(pickings), "quants": len(quants or []),
            "confirmed": sum(1 for v in violations if v["kind"] == "confirmed"),
            "suspicious": sum(1 for v in violations if v["kind"] == "suspicious"),
        },
    }
