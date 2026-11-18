"""Phase 3/10 — corrélation cross-système générique (tool correlate_records).

Statuts explicites : matched (clé exacte), uncertain (clé normalisée),
unmatched (sans contrepartie), conflicting (lien mais valeurs comparées en écart).
Aucune relation inventée : clés ambiguës signalées, liens tracés vers evidences+row_index.
"""

from __future__ import annotations

from app.audit.correlation import correlate

ORDERS = [
    {"order_id": "SO-1", "amount": "602.50"},
    {"order_id": "SO-2", "amount": "240.00"},
    {"order_id": "SO-3", "amount": "99.99"},  # sans facture
]
INVOICES = [
    {"invoice_ref": "so-1 ", "invoiced_amount": "602.50"},   # même clé, normalisée
    {"invoice_ref": "SO-2", "invoiced_amount": "999.00"},    # conflit de montant
    {"invoice_ref": "INV-X", "invoiced_amount": "10.00"},    # sans commande
]


def _correlate(normalize: bool):
    return correlate(
        ORDERS, INVOICES, "order_id", "invoice_ref",
        left_label="Commandes", right_label="Factures",
        left_evidence_id="ev_ord", right_evidence_id="ev_inv",
        compare_fields=[{"left": "amount", "right": "invoiced_amount"}],
        normalize=normalize,
    )


def test_exact_matching_and_statuses():
    out = _correlate(normalize=False)
    assert out["stats"]["matched"] == 1  # SO-2 only
    assert out["stats"]["uncertain"] == 0
    unmatched_left = {u["key_value"] for u in out["unmatched_left"]}
    assert unmatched_left == {"SO-1", "SO-3"}  # SO-1 ne matche que normalisé
    unmatched_right = {u["key_value"] for u in out["unmatched_right"]}
    assert unmatched_right == {"so-1 ", "INV-X"}


def test_normalized_matching_is_uncertain_not_matched():
    out = _correlate(normalize=True)
    assert out["stats"]["matched"] == 1          # SO-2 (déjà exact)
    assert out["stats"]["uncertain"] == 1        # SO-1 via normalisation
    link_so1 = next(l for l in out["links"] if l["key"] == "so-1")
    assert link_so1["status"] == "uncertain"


def test_conflicting_values_detected_with_traceability():
    out = _correlate(normalize=False)
    assert out["stats"]["conflicts"] == 1
    conflict = out["conflicts"][0]
    assert conflict["key"] == "SO-2"
    assert conflict["left"]["evidence_id"] == "ev_ord" and conflict["left"]["row_index"] == 1
    assert conflict["right"]["evidence_id"] == "ev_inv" and conflict["right"]["row_index"] == 1
    assert conflict["difference"] == "-759.00"


def test_links_cite_both_evidences_and_rows():
    out = _correlate(normalize=False)
    for link in out["links"]:
        assert link["left"]["evidence_id"] == "ev_ord"
        assert link["right"]["evidence_id"] == "ev_inv"
        assert isinstance(link["left"]["row_index"], int)


def test_no_invented_links_when_ambiguous():
    orders = [{"order_id": "SO-DUP", "amount": "1"}, {"order_id": "SO-DUP", "amount": "2"}]
    invoices = [{"invoice_ref": "SO-DUP", "invoiced_amount": "1"}]
    out = correlate(
        orders, invoices, "order_id", "invoice_ref",
        left_label="L", right_label="R", left_evidence_id="e1", right_evidence_id="e2",
    )
    assert "SO-DUP" in out["ambiguous_keys"]
    assert all(l["ambiguous"] for l in out["links"])
    # les deux lignes gauches pointent la MÊME contrepartie droite (row_index 0) :
    # corrélées mais signalées ambiguës — aucune relation 1-pour-1 inventée
    assert len(out["links"]) == 2
    assert len({l["right"]["row_index"] for l in out["links"]}) == 1
    assert out["stats"]["ambiguous_keys"] == 1
