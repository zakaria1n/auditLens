"""Vérité de terrain de l'évaluation (docs/12, docs/17).

- Les jeux `files_*` sont GÉNÉRÉS avec des seeds distincts (dev ≠ eval) ; les anomalies
  injectées proviennent du générateur prouvé (demo_data.generate_demo).
- Les cas api/web/odoo portent sur des anomalies plantées dans les services de test ou
  **inspectées directement** dans l'instance Odoo réelle (jamais devinées).

La vérité de terrain n'est JAMAIS transmise à l'agent : elle sert uniquement au scoring
après exécution. Le matching par mots-clés est volontairement documenté comme approximatif.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo_data.generate_demo import generate_invoices, generate_orders  # noqa: E402


@dataclass
class EvalCase:
    case_id: str
    source_kind: str  # file | api | web | odoo | multi
    objective: str
    # catégories attendues : id de catégorie → mots-clés de détection (approximatifs, documentés)
    expected: dict[str, list[str]]
    # mapping Baseline A : fait déterministe (rule_id / violation) → catégorie
    baseline_map: dict[str, str] = field(default_factory=dict)
    # mots-clés INTERDITS dans les constats (affirmations non supportées → FP, docs/17)
    forbidden: dict[str, list[str]] = field(default_factory=dict)
    # catégorie attendue qui est une conclusion d'INCERTITUDE CORRECTE (distincte d'une
    # anomalie manquée — docs/17 v4 : l'inconclusif correct n'est pas un FN)
    inconclusive_category: str | None = None
    # critères de succès DÉCLARATIFS évalués sur les données structurées du run
    # (au-delà des mots-clés) — voir runner.eval_criteria
    criteria: list[str] = field(default_factory=list)
    notes: str = ""


def generate_files_dataset(out_dir: Path, seed: int) -> Path:
    """Génère un jeu de données fichiers avec anomalies injectées (générateur proué)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    orders = generate_orders(out_dir / "orders.csv", faulty=True, seed=seed)
    invoices = generate_invoices(out_dir / "invoices.csv", faulty=True, seed=seed)
    return orders | invoices  # type: ignore[operator]


FILES_DEV = EvalCase(
    case_id="files_dev",
    source_kind="file",
    objective="Vérifier la conformité du fichier commandes au Data Contract rs_orders_v1 (colonnes requises, typage, unicité de order_id, valeurs non négatives).",
    expected={
        "duplicate_order_id": ["dupliquée", "duplicate", "r7"],
        "negative_quantity": ["négative", "negative", "r8"],
        "invalid_date": ["date invalide", "invalide", "r5"],
        "missing_unit_price": ["nulle dans unit_price", "valeur nulle", "r4"],
    },
    baseline_map={
        "R7": "duplicate_order_id",
        "R8": "negative_quantity",
        "R5": "invalid_date",
        "R4": "missing_unit_price",
    },
    notes="seed 9831 — jeu de développement (visible, prompts ajustables)",
)

FILES_EVAL = EvalCase(
    case_id="files_eval",
    source_kind="file",
    objective="Vérifier la conformité du fichier commandes au Data Contract rs_orders_v1 (colonnes requises, typage, unicité de order_id, valeurs non négatives).",
    expected={
        "duplicate_order_id": ["dupliquée", "duplicate", "r7"],
        "negative_quantity": ["négative", "negative", "r8"],
        "invalid_date": ["date invalide", "invalide", "r5"],
        "missing_unit_price": ["nulle dans unit_price", "valeur nulle", "r4"],
    },
    baseline_map=FILES_DEV.baseline_map,
    notes="seed 5521 — jeu held-out (n'a jamais servi à ajuster prompts ou règles)",
)

API_TEST = EvalCase(
    case_id="api_test",
    source_kind="api",
    objective="Vérifier que les endpoints approuvés répondent selon le contrat documenté (statuts, schéma de réponse, pagination effective).",
    expected={
        "endpoint_error_status": ["status_not_in_contract", "500"],
        "schema_type_mismatch": ["schema:type", "type mismatch", "attendu number"],
        "pagination_broken": ["pagination_not_implemented", "pagination"],
    },
    baseline_map={
        "status_not_in_contract": "endpoint_error_status",
        "schema:type": "schema_type_mismatch",
        "pagination_not_implemented": "pagination_broken",
    },
    notes="anomalies A1/A2/A3 plantées dans backend/test_services/api_service.py",
)

WEB_TEST = EvalCase(
    case_id="web_test",
    source_kind="web",
    objective="Vérifier que le parcours de paiement déclaré s'exécute avec les assertions attendues et sans erreur JavaScript bloquante.",
    expected={
        "journey_fail_payment": ["étapes sur 5", "échec du parcours", "all_passed.*false"],
        "js_console_errors": ["erreur", "console"],
    },
    baseline_map={
        "journey_failed": "journey_fail_payment",
        "console_errors": "js_console_errors",
    },
    notes="anomalies W1 (paiement 500) et W2 (erreur JS) plantées dans web_app.py",
)

ODOO_TP = EvalCase(
    case_id="odoo_tp",
    source_kind="odoo",
    objective="Vérifier la concordance commande/facture et la cohérence livraison/stock (réconciliation déterministe) sur l'instance Odoo locale.",
    expected={
        "qty_move_vs_line": ["erp-02-r1", "move_vs_delivered", "mouvements de stock faits",
                             "contradiction interne", "écart quantité livrée", "écart de quantité"],
        "orphan_origin": ["p00001", "orphan_picking_origin", "orphelin", "absente des documents collectés"],
        "negative_quant": ["negative_on_hand", "quantité disponible négative"],
    },
    baseline_map={
        "ERP-02-R1-move_vs_delivered_mismatch": "qty_move_vs_line",
        "CROSS-01-R7-orphan_picking_origin": "orphan_origin",
        "STOCK-01-R8-negative_on_hand": "negative_quant",
    },
    notes="anomalies réelles inspectées directement dans TP_zakaria (non plantées par nous)",
)

# ---------------------------------------------------------------------------
# Cas AGENTIQUES (docs/17 v2) : mesures que le déterminisme seul ne peut pas produire.
# La vérité de terrain n'est JAMAIS exposée à l'agent — les objectifs sont neutres.
# ---------------------------------------------------------------------------

AGENT_MULTISTEP = EvalCase(
    case_id="agent_multistep",
    source_kind="api",
    objective=(
        "Vérifier que toutes les commandes publiées par l'API restent accessibles en détail "
        "et conformes au contrat documenté (liste et détail de chaque commande)."
    ),
    # A4 : seule une chaîne liste → détail (id découvert dans la liste) peut la détecter.
    expected={
        "order_detail_error": ["500", "status_not_in_contract", "shipping_address"],
    },
    # Baseline A : couverture fixe (liste + endpoints déclarés) → A4 hors de portée (rappel 0 attendu).
    baseline_map={},
    forbidden={
        "unsupported_conformity_claim": ["toutes les commandes sont conformes", "aucun écart détecté"],
    },
    notes=(
        "anomalie A4 plantée dans api_service.py (GET /orders/3 → 500) ; exige un appel DÉPENDANT "
        "sur l'endpoint paramétré /orders/{order_id} avec un id issu de la liste"
    ),
)

AGENT_UNDOCUMENTED = EvalCase(
    case_id="agent_undocumented",
    source_kind="api",
    objective=(
        "Vérifier que les endpoints approuvés répondent selon le contrat documenté ; "
        "signaler uniquement les violations de contrat réelles."
    ),
    # Aucune violation attendue : /health est vivant mais absent du contrat (docs/08 :
    # non documenté ≠ violation). La métrique clé est l'ABSENCE de fausse détection.
    expected={},
    forbidden={
        "false_violation_on_health": ["health.*violation", "violation.*health", "/health.*hors contrat", "health.*not_in_contract"],
    },
    notes="discipline de claims : ne pas transformer un endpoint non documenté mais sain en violation",
)

AGENT_ODOO_AMBIGUOUS = EvalCase(
    case_id="agent_odoo_ambiguous",
    source_kind="odoo",
    objective=(
        "Investiguer les situations inexpliquées de l'instance Odoo (références de picking, "
        "écarts de stock) et qualifier la situation avec prudence : des explications légitimes "
        "existent possiblement et doivent être distinguées des contradictions internes."
    ),
    expected={
        # Situation « suspicious » par construction : la référence P00001 est absente des
        # documents collectés (peut être une commande d'achat hors périmètre — à vérifier).
        "orphan_origin_suspicious": ["r7", "orphan", "orphelin", "suspicious", "absente des documents", "p00001"],
    },
    baseline_map={
        "CROSS-01-R7-orphan_picking_origin": "orphan_origin_suspicious",
    },
    forbidden={
        # Interdiction d'affirmer une fraude/non-conformité CERTAINE sur la situation suspicious.
        "unsupported_fraud_claim": ["fraude confirmée", "fraud confirmed", "preuve de fraude",
                                    "fraude avérée", "orphan.*fraude", "p00001.*fraude"],
    },
    criteria=["no_silence"],
    notes="qualification prudente : la situation suspicious (P00001) peut avoir une explication légitime (achat hors périmètre)",
)


# ---------------------------------------------------------------------------
# Scénarios agentiques v2 (mission ADR-15 / docs/17 v3) : l'ÉVALUATION mesure le
# PROCESSUS d'investigation, pas seulement le constat final.
# ---------------------------------------------------------------------------

AGENT_ODOO_ROOTCAUSE = EvalCase(
    case_id="agent_odoo_rootcause",
    source_kind="odoo",
    objective=(
        "Sur l'instance Odoo, expliquer l'origine du stock disponible négatif du produit "
        "« Ordinateur portable HP 250 G8 » : relier les faits observés (livraisons, achats, "
        "ajustements d'inventaire) dans un constat étayé par au moins deux preuves distinctes."
    ),
    expected={
        # L'explication relie plusieurs faits (livraison sans réception suffisante,
        # ajustements) — mesurée par la corrélation multi-preuves, pas un mot unique.
        "root_cause_explanation": ["stock", "livraison", "ajustement", "réception", "achat", "inventaire"],
    },
    baseline_map={},  # le déterminisme produit les signaux (R1/R8), pas l'explication reliée
    forbidden={"unsupported_root_cause": ["fraude confirmée", "perte volontaire", "vol prouvé"]},
    criteria=["multi_evidence>=2"],
    notes="mesure l'INVESTIGATION (relier des faits via ≥2 preuves), pas seulement la détection",
)

AGENT_WEB_ORDERS = EvalCase(
    case_id="agent_web_orders",
    source_kind="web",
    objective="Vérifier que les parcours principaux de la boutique restent fonctionnels (paiement et consultation des commandes).",
    expected={
        "orders_page_error": ["commandes", "500", "échec"],
    },
    baseline_map={},
    notes="W3 plantée dans web_app.py (GET /orders → 500) ; le parcours j2 est déclaré dans la source",
)

AGENT_CROSS_SOURCE = EvalCase(
    case_id="agent_cross_source",
    source_kind="multi",
    objective=(
        "Recouper les commandes entre l'ERP Odoo et le flux externe de l'API partenaire : "
        "identifier tout écart de montant sur une référence de commande commune."
    ),
    expected={
        # Mots-clés spécifiques au flux externe planté (999999 / external_total) pour ne pas
        # matcher la violation R1 déterministe qui mentionne légitimement S00002.
        "cross_amount_mismatch": ["999999", "external_total", "flux externe", "montant externe"],
    },
    baseline_map={},
    forbidden={"false_cross_claim": ["montants identiques", "aucun écart de montant"]},
    notes=(
        "corrélation Odoo + API : endpoint /external_orders planté (ref S00002, montant 999999.0) "
        "— exige une jointure de preuves inter-sources"
    ),
)

AGENT_MISSING_EVIDENCE = EvalCase(
    case_id="agent_missing_evidence",
    source_kind="file",
    objective=(
        "Vérifier que tous les avoirs (remboursements clients) émis sont liés à une facture "
        "et correctement imputés, sur la base des données disponibles."
    ),
    expected={
        # Le fichier ne contient AUCUNE donnée d'avoirs → le résultat correct est une
        # insuffisance EXPLICITE (assessment insufficient_evidence / constat prudent).
        "explicit_insufficient": ["insuffisante", "insuffisant", "aucune", "absence", "impossible de conclure", "non disponible"],
    },
    baseline_map={},
    forbidden={
        "unsupported_refunds_claim": ["tous les avoirs sont conformes", "avoirs vérifiés sans écart",
                                      "les avoirs sont correctement imputés"],
    },
    inconclusive_category="explicit_insufficient",
    criteria=["no_silence"],
    notes="mesure la capacité à conclure à l'INCERTITUDE au lieu d'affirmer sans preuve (docs/03 règle 1)",
)

AGENT_CONTRADICTION = EvalCase(
    case_id="agent_contradiction",
    source_kind="api",
    objective="Vérifier la cohérence des commandes publiées par l'API (liste contre détail) et signaler toute contradiction interne.",
    expected={
        "list_detail_status_mismatch": ["cancelled", "annul", "incohérence", "contradiction", "diverge"],
    },
    baseline_map={},
    notes="A5 plantée dans api_service.py : commande 7 « confirmed » en liste, « cancelled » en détail",
)

AGENT_FLAKY = EvalCase(
    case_id="agent_flaky",
    source_kind="api",
    objective="Étudier la stabilité du service de rapports (endpoint reports) et documenter son comportement réel.",
    expected={
        "flaky_documented": ["503", "instable", "indisponible", "intermitt", "réessai"],
    },
    baseline_map={},
    forbidden={"persistent_wrong_claim": ["reports.*indisponible de façon permanente", "reports.*en échec permanent"]},
    criteria=["reverification"],
    notes="A6 plantée dans api_service.py : /reports renvoie 503 aux 2 premiers appels puis 200",
)

# ---------------------------------------------------------------------------
# Cas TENUS HORS DÉVELOPPEMENT (généralisation docs/17 v4) : jamais utilisés pour
# ajuster prompts ou règles — testent la généralisation de la vérification temporelle
# et de la révision d'hypothèse sur des situations NON vues.
# ---------------------------------------------------------------------------

AGENT_TRANSIENT_PERSISTENT = EvalCase(
    case_id="agent_transient_persistent",
    source_kind="api",
    objective=(
        "Étudier la stabilité des services auxiliaires de l'API (reports et export) et "
        "qualifier chaque comportement observé avec prudence : distinguer ce qui est "
        "intermittent de ce qui est persistant, en vous appuyant sur des observations "
        "comparées dans le temps."
    ),
    expected={
        # /reports : 503 puis 200 (intermittent) ; /export : 500 systématique (persistant,
        # VIOLATION de contrat car 200 documenté — détectable aussi par le déterminisme).
        "intermittent_documented": ["503", "intermitt", "instable", "indisponib.*temporaire", "transitoire"],
        # "status_not_in_contract" volontairement ABSENT : le 500 de A1 (order_detail_999,
        # hors périmètre de ce cas) ne doit pas compter comme détection du cas export.
        "persistent_documented": ["export", "persistant", "échec permanent", "crashed"],
    },
    # Pas de mapping baseline : le 500 de A1 (order_detail_999, hors périmètre de ce cas)
    # ne doit PAS être compté comme détection du cas export (matching approximatif documenté).
    baseline_map={},
    forbidden={
        # Conclusions inverses. Regex bornées à UN constat ([^|]* : le blob sépare par " || ")
        # — qualifier l'intermittent de permanent, ou le persistant de transitoire = FP.
        "wrong_persistent_claim": ["reports[^|]{0,120}(permanent|persistant[^ ]* échec|échec permanent)"],
        "wrong_transient_claim": ["export[^|]{0,120}(transitoire|intermittent|temporaire)"],
    },
    criteria=["reverification", "no_silence"],
    notes=(
        "cas de GÉNÉRALISATION tenu hors développement : /export (500 permanent, contrat 200) + "
        "/reports (503×2 puis 200) — exige de distinguer intermittent vs persistant"
    ),
)

AGENT_LEGIT_CREDIT = EvalCase(
    case_id="agent_legit_credit",
    source_kind="api",
    objective=(
        "Vérifier la cohérence des montants des commandes publiées par l'API et signaler "
        "toute anomalie, en cherchant les explications légitimes possibles avant de conclure."
    ),
    expected={
        # La commande 9 a un total NÉGATIF (-50.0) : apparente anomalie, mais son détail
        # porte "type": "credit_note" (avoir) — explication légitime documentée dans la source.
        "legit_explanation_found": ["credit_note", "avoir", "remboursement", "note de crédit"],
    },
    baseline_map={},
    forbidden={
        # Affirmer une anomalie de montant sans mentionner l'explication légitime trouvée.
        "unsupported_anomaly_claim": ["montant négatif.*anomalie", "anomalie.*négatif.*sans explication"],
    },
    criteria=["no_silence"],
    notes="apparente anomalie (total négatif) avec explication légitime (credit_note) — révision d'hypothèse attendue",
)

ALL_CASES: dict[str, EvalCase] = {c.case_id: c for c in [
    FILES_DEV, FILES_EVAL, API_TEST, WEB_TEST, ODOO_TP,
    AGENT_MULTISTEP, AGENT_UNDOCUMENTED, AGENT_ODOO_AMBIGUOUS,
    AGENT_ODOO_ROOTCAUSE, AGENT_WEB_ORDERS, AGENT_CROSS_SOURCE,
    AGENT_MISSING_EVIDENCE, AGENT_CONTRADICTION, AGENT_FLAKY,
    AGENT_TRANSIENT_PERSISTENT, AGENT_LEGIT_CREDIT,
]}
