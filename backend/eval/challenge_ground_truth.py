"""Vérité de terrain du DÉFI INDÉPENDANT — module de SCORING uniquement.

Séparation stricte (mission §3) : ce fichier n'est JAMAIS transmis à l'agent. Il n'est
lu que par challenge_report.py après exécution. Les situations sont décrites par
catégorie ; les mécanismes diffèrent des cas de développement (8080).
"""

from __future__ import annotations

# 6 catégories attendues (S3 = avoir légitime : mesuré en FP-interdit, pas en attendu)
EXPECTED: dict[str, list[str]] = {
    "over_shipment_oc7705": [
        r"oc-7705[^|]{0,160}(expédi|shipment|livraison|livré)",
        r"(sur-?livr|expéditions? (multiples|deux|doublon)|quantité expédiée[^|]{0,60}(dépasse|supérieure))",
    ],
    "payment_wrong_invoice_pm504": [
        r"pm-504",
        r"(pm-504[^|]{0,160}(fa-907|cl-102|autre client|mauvaise facture|ne correspond))",
    ],
    "invoice_without_shipment_oc7710": [
        r"(fa-911|oc-7710)[^|]{0,160}(sans expédition|aucune expédition|non expédiée?|pas d'expédition)",
        r"(facturée?[^|]{0,80}(mais|sans)[^|]{0,80}expédi)",
    ],
    "bank_vs_api_amount_pm509": [
        r"pm-509[^|]{0,160}(980[.,]?50|écart|diffère|diverge|ne correspond)",
        r"(980[.,]50[^|]{0,120}890[.,]50|bancaire[^|]{0,120}(écart|diffère))",
    ],
    "transient_audit_trail": [
        r"(audit-?trail[^|]{0,160}(503|indisponib|temporaire|transitoire|intermitt))",
        r"(503[^|]{0,120}audit-?trail)",
    ],
    "web_vs_api_status_oc7702": [
        r"oc-7702[^|]{0,160}(portail|web|livré[^|]{0,40}annulée?|annulée?[^|]{0,40}livré)",
        r"(portail[^|]{0,120}(annulée?|cancelled)[^|]{0,120}contradic)",
        r"(contradic[^|]{0,120}(portail|web))",
    ],
}

# Constats interdits (faux positifs) — situations saines à NE PAS signaler
FORBIDDEN: dict[str, list[str]] = {
    "false_pagination_flag": [r"pagination[^|]{0,80}(cassée|broken|non implémentée|identique)"],
    "false_av902_anomaly": [r"av-902[^|]{0,160}(anomalie|incohérence|écart suspect|fraude|doublon)"],
    "false_healthy_chain_flag": [r"oc-770[1369][^|]{0,160}(anomalie|incohérence confirmée|fraude)"],
}

# La reconnaissance explicite de l'avoir légitime AV-902 (raison=return) est un BONUS :
# noter sa présence sans la compter dans le rappel (le silence est acceptable si l'agent
# ne la signale pas comme anomalie).
LEGIT_BONUS: list[str] = [r"av-902[^|]{0,160}(retour|return|légitime|avoir)", r"avoir[^|]{0,120}retour"]

CRITERIA = ["no_silence", "multi_evidence>=1"]
INCONCLUSIVE_CATEGORY = None  # ce défi n'a pas de cas « preuves impossible » : tout est corrélable


def classify_facts(blob: str) -> tuple[list[str], list[str], bool]:
    """Retourne (détectés, interdits touchés, bonus légitime reconnu)."""
    import re

    detected = [cat for cat, kws in EXPECTED.items()
                if any(re.search(kw, blob, re.IGNORECASE) for kw in kws)]
    forbidden = [cat for cat, kws in FORBIDDEN.items()
                 if any(re.search(kw, blob, re.IGNORECASE) for kw in kws)]
    legit = any(re.search(kw, blob, re.IGNORECASE) for kw in LEGIT_BONUS)
    return detected, forbidden, legit
