"""Accès générique READ-ONLY aux modèles Odoo autorisés (Phase 2B/4).

Complète les tools spécialisés (commandes/factures/stock/achats) : découverte des
modèles installés accessibles au compte d'audit, inspection de métadonnées, lectures
bornées, relations (many2one/one2many/many2many), agrégats via read_group.

Sécurité (docs/07, Phase 2B) :
- READ-ONLY strict : seuls search / search_count / read / read_group / fields_get /
  ir.model / ir.model.fields sont autorisés — aucune méthode arbitraire, pas de sudo ;
- blacklist de modèles techniques/sensibles (config, tokens, logs, apikeys) ;
- champs binaires et champs à noms sensibles exclus des lectures ;
- bornes : limit <= MAX_LIMIT, domain sérialisé borné, profondeur relation bornée ;
- erreurs d'accès Odoo remontées comme refus explicites (jamais contournées).
"""

from __future__ import annotations

import json
from typing import Any

MAX_LIMIT = 200
MAX_DOMAIN_LEN = 2000
MAX_RELATION_DEPTH = 1
MAX_RELATION_RECORDS = 200

# namespaces techniques/sensibles interdits à la lecture générique
MODEL_BLACKLIST_PREFIXES = (
    "ir.", "base_", "res.users.log", "res.users.apikeys", "res.config",
    "res.groups", "res.groups.implied", "oauth_", "auth_",
)
MODEL_BLACKLIST_SUBSTRINGS = ("apikey", "token", "secret", "credential", "password")
SENSITIVE_FIELD_SUBSTRINGS = ("password", "secret", "token", "apikey", "credential", "signature")
EXCLUDED_FIELD_TYPES = ("binary",)


def model_is_allowed(model: str) -> bool:
    m = model.strip()
    if not m:
        return False
    if any(m.startswith(p) for p in MODEL_BLACKLIST_PREFIXES):
        return False
    lowered = m.lower()
    return not any(s in lowered for s in MODEL_BLACKLIST_SUBSTRINGS)


def sanitize_fields(fields_meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Filtre les champs : binaires et à noms sensibles exclus."""
    safe: dict[str, dict[str, Any]] = {}
    for name, meta in fields_meta.items():
        if meta.get("type") in EXCLUDED_FIELD_TYPES:
            continue
        if any(s in name.lower() for s in SENSITIVE_FIELD_SUBSTRINGS):
            continue
        safe[name] = meta
    return safe


RELATION_TYPES = {"many2one", "one2many", "many2many"}


def relations_from_fields(fields_meta: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for name, meta in fields_meta.items():
        if meta.get("type") in RELATION_TYPES:
            out.append({
                "field": name, "type": meta["type"],
                "comodel": meta.get("relation") or "?",
                "required": bool(meta.get("required")),
            })
    return out
