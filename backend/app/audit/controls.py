"""Catalogue de contrôles pragmatiques V1 (docs/11).

Un contrôle = objectif + critère versionné + procédure + preuves attendues + méthode.
`Test réussi ≠ Contrôle conforme ≠ Audit global conforme` — les statuts restent prudentiels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Control:
    id: str
    version: str
    title: str
    source_types: tuple[str, ...]
    criterion: str
    expected_evidence: list[str]
    method: str
    evaluator: Literal["data_rules", "api_contract", "web_journey", "agent_correlation"]


CONTROL_CATALOG: dict[str, Control] = {
    c.id: c
    for c in [
        Control(
            id="ERP-01",
            version="v1",
            title="Concordance commande / facture",
            source_types=("odoo",),
            criterion="Chaque facture (account.move out_invoice) référence une commande existante avec montants cohérents (remises, taxes, retours et avoirs gérés selon la politique commerciale en vigueur).",
            expected_evidence=["odoo_read_orders", "odoo_read_invoices"],
            method="lecture Odoo + jointure référence + interprétation agent",
            evaluator="agent_correlation",
        ),
        Control(
            id="ERP-02",
            version="v2",
            title="Livraison / quantité facturée",
            source_types=("odoo",),
            criterion="Quantité facturée cohérente avec quantité livrée et commandée ; écarts expliqués par livraison partielle, retour ou avoir documenté ; mouvements de stock cohérents avec qty_delivered ; stock on-hand non négatif ; références de picking rattachables.",
            expected_evidence=["odoo_read_orders", "odoo_read_invoices", "odoo_read_stock", "odoo_cross_check"],
            method="réconciliation déterministe (odoo_cross_check) + investigation agent sur les situations suspectes",
            evaluator="odoo_reconciliation",
        ),
        Control(
            id="API-01",
            version="v1",
            title="Contrat API & réponses d'erreur",
            source_types=("api",),
            criterion="Endpoints approuvés répondent selon le contrat (statut attendu, schéma conforme) ; les réponses d'erreur sont structurées.",
            expected_evidence=["api_inspect_contract", "api_fetch_records"],
            method="HTTPX + vérification contractuelle",
            evaluator="api_contract",
        ),
        Control(
            id="WEB-01",
            version="v1",
            title="Parcours utilisateur nominal",
            source_types=("web",),
            criterion="Le parcours déclaré s'exécute avec les assertions attendues (statut, textes, sélecteurs) sans erreur JavaScript bloquante.",
            expected_evidence=["web_run_journey"],
            method="Playwright parcours contraint + assertions",
            evaluator="web_journey",
        ),
        Control(
            id="DATA-01",
            version="v1",
            title="Structure & cohérence des données",
            source_types=("file",),
            criterion="Le fichier respecte le Data Contract : colonnes requises présentes, typage correct, unicité de la clé métier identifiée, valeurs dans les plages autorisées.",
            expected_evidence=["data_profile", "data_validate"],
            method="profiling + jeu de règles déterministes",
            evaluator="data_rules",
        ),
        Control(
            id="CROSS-01",
            version="v1",
            title="Corrélation multi-source",
            source_types=("file", "odoo", "api", "web"),
            criterion="Les enregistrements corrélés par une clé métier vérifiée sont cohérents entre sources ; les écarts sont documentés (clé, horodatage, compatibilité des champs).",
            expected_evidence=["evidence_join"],
            method="evidence_join + raisonnement agent",
            evaluator="agent_correlation",
        ),
    ]
}


def get_control(control_id: str) -> Control | None:
    return CONTROL_CATALOG.get(control_id)


def list_controls() -> list[Control]:
    return list(CONTROL_CATALOG.values())


def control_to_dict(c: Control) -> dict:
    return {
        "id": c.id,
        "version": c.version,
        "title": c.title,
        "source_types": list(c.source_types),
        "criterion": c.criterion,
        "expected_evidence": c.expected_evidence,
        "method": c.method,
    }
