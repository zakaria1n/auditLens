"""Privacy-aware AI context (Phase 7/10) : minimisation du contexte envoyé au LLM.

Étend la redaction existante (secrets) à la PII métier (emails, téléphones, IBAN,
numéros nationaux) SANS toucher aux preuves immuables : le sanitizer opère sur la
copie du contexte prompt, jamais sur l'evidence stockée.

- `sanitize_context(obj)` : copie avec valeurs PII masquées (préfixe conservé pour
  l'auditabilité : ex. \"j***@***.com\") ;
- `classify_exposure(obj)` : catégories de données détectées + compteurs — sert au
  preview d'exposition IA et aux événements `privacy_preview` ;
- bornes : la détection automatique ne prétend PAS capturer toute donnée sensible
  métier — la classification est une aide, pas une garantie (documenté côté UI).
"""

from __future__ import annotations

import re
from typing import Any

PATTERNS: dict[str, re.Pattern[str]] = {
    # identifiants structurés AVANT phone (sinon le pattern gourmand les consomme)
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?:[\s.]?[A-Z0-9]{3,4}){3,8}\b"),
    "national_id": re.compile(r"\b[12]\s?\d{2}\s?(?:0[1-9]|1[0-2])\s?(?:0[1-9]|[12]\d|3[01])\s?(?:\d\s?){4}\d\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?:\+\d{1,3}[\s.-])?(?:\(?\d{2,4}\)?[\s.-]?){2,4}\d{2,4}"),
}

# champs dont les valeurs sont masquées entièrement si une PII y est détectée
PII_FIELD_HINTS = ("email", "mail", "phone", "tel", "mobile", "iban", "iban_number",
                   "account_number", "ssn", "national_id", "customer_ref")

REDACTED_PII = "[PII_REDACTED]"


def mask_value(value: str) -> str:
    """Masque en conservant un préfixe court (auditabilité sans réidentification)."""
    head = value[:4]
    return f"{head}…{REDACTED_PII}"


def sanitize_context(obj: Any, _depth: int = 0) -> tuple[Any, dict[str, int]]:
    """Copie assainie : secrets (redact existant côté appelant) + PII par pattern.

    Retourne (copie, compteurs_par_catégorie). Ne modifie JAMAIS l'original.
    """
    if _depth > 20:
        return obj, {}
    counts: dict[str, int] = {}

    def merge(other: dict[str, int]) -> None:
        for k, v in other.items():
            counts[k] = counts.get(k, 0) + v

    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(v, str):
                masked, c = _mask_string_if_pii(v, str(k))
                merge(c)
                out[k] = masked
            else:
                cleaned, c = sanitize_context(v, _depth + 1)
                merge(c)
                out[k] = cleaned
        return out, counts
    if isinstance(obj, (list, tuple)):
        out_list = []
        for item in obj:
            cleaned, c = sanitize_context(item, _depth + 1)
            merge(c)
            out_list.append(cleaned)
        return out_list, counts
    if isinstance(obj, str):
        masked, c = _mask_string_if_pii(obj)
        merge(c)
        return masked, c
    return obj, counts


def _mask_string_if_pii(value: str, field_name: str = "") -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    out = value
    for category, pattern in PATTERNS.items():
        found = pattern.findall(out)
        if not found:
            continue
        # suppression des faux positifs pour phone (dates, ids courts)
        if category == "phone":
            found = [
                f for f in found
                if sum(ch.isdigit() for ch in f) >= 8 and not re.match(r"\d{4}-\d{2}-\d{2}", f)
            ]
            if not found:
                continue
        counts[category] = counts.get(category, 0) + len(found)
        for f in found:
            out = out.replace(f, mask_value(f))
    # champ à hint PII avec valeur non vide : masquage entier prudent
    hint_hit = any(h in field_name.lower() for h in PII_FIELD_HINTS)
    if hint_hit and out and out != REDACTED_PII and not counts:
        counts["field_hinted"] = 1
        return mask_value(out), counts
    return out, counts


def classify_exposure(obj: Any) -> dict[str, Any]:
    """Preview SANS mutation : catégories détectées, compteurs, provider-agnostique.

    Ne renvoie JAMAIS les valeurs — uniquement les catégories et leurs volumes.
    """
    _, counts = sanitize_context(obj)
    categories = [
        {"category": k, "count": v}
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
    return {
        "categories": categories,
        "total_redactions": sum(counts.values()),
        "note": (
            "détection automatique par patterns (email/téléphone/IBAN/identifiants) : "
            "aide à la minimisation, PAS une garantie d'exhaustivité — les secrets "
            "(clés, tokens) sont déjà masqués par la redaction existante."
        ),
    }
