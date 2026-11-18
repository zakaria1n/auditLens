"""Corrélation cross-système GÉNÉRIQUE (Phase 3/10) : résolution d'entités entre
jeux d'enregistrements de systèmes différents, sans inventer de relations.

Principes :
- correspondance par clés explicites (exacte ou normalisée : casse/espaces) —
  AUCUNE correspondance floue silencieuse ;
- statuts explicites : `matched` (clé partagée), `unmatched` (aucune contrepartie),
  `conflicting` (clé liée mais valeurs de comparaison contradictoires) ;
- `uncertain` réservé aux clés normalisées (exacte après normalisation seulement) ;
- preuves préservées : chaque lien cite les evidence_id et row_index des deux côtés.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

MAX_CORRELATION_ROWS = 5000
MAX_LINKS = 200


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _num(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        return Decimal(str(value).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def correlate(
    left_records: list[dict],
    right_records: list[dict],
    left_key: str,
    right_key: str,
    *,
    left_label: str,
    right_label: str,
    left_evidence_id: str,
    right_evidence_id: str,
    compare_fields: list[dict[str, str]] | None = None,
    normalize: bool = False,
) -> dict[str, Any]:
    """Corrélation par clés explicites entre DEUX jeux d'enregistrements.

    compare_fields = [{left, right}] : champs comparés numériquement quand un lien existe
    (écart => `conflicting`). normalize=True : correspondance exacte après normalisation
    (casse/espaces) => statut `uncertain` au lieu de `matched`.
    """
    left_records = left_records[:MAX_CORRELATION_ROWS]
    right_records = right_records[:MAX_CORRELATION_ROWS]

    key_fn = _norm if normalize else (lambda v: str(v or ""))
    right_index: dict[str, list[tuple[int, dict]]] = {}
    for idx, rec in enumerate(right_records):
        k = key_fn(rec.get(right_key))
        if k:
            right_index.setdefault(k, []).append((idx, rec))

    links: list[dict] = []
    conflicts: list[dict] = []
    matched_left: set[int] = set()
    matched_right: set[int] = set()
    right_match_counts: dict[int, int] = {}
    ambiguous_keys: set[str] = set()

    for lidx, lrec in enumerate(left_records):
        k = key_fn(lrec.get(left_key))
        if not k:
            continue
        candidates = right_index.get(k)
        if not candidates:
            continue  # unmatched côté gauche, traité après
        if len(candidates) > 1:
            ambiguous_keys.add(k)
        matched_left.add(lidx)
        ridx, rrec = candidates[0]
        matched_right.add(ridx)
        right_match_counts[ridx] = right_match_counts.get(ridx, 0) + 1
        if right_match_counts[ridx] > 1:
            # plusieurs enregistrements gauches pointent la même contrepartie :
            # résolution ambiguë (risque de double comptage) — signalé, pas caché
            ambiguous_keys.add(k)
        # uncertain quand la correspondance n'est exacte qu'après normalisation
        raw_left = str(lrec.get(left_key) or "")
        raw_right = str(rrec.get(right_key) or "")
        status = "uncertain" if (normalize and raw_left != raw_right) else "matched"

        field_comparisons: list[dict] = []
        for cf in compare_fields or []:
            lf, rf = str(cf.get("left")), str(cf.get("right"))
            ln, rn = _num(lrec.get(lf)), _num(rrec.get(rf))
            if ln is None or rn is None:
                field_comparisons.append({
                    "left_field": lf, "right_field": rf,
                    "left_value": str(lrec.get(lf)), "right_value": str(rrec.get(rf)),
                    "status": "not_comparable",
                })
                continue
            difference = ln - rn
            ok = difference == 0
            field_comparisons.append({
                "left_field": lf, "right_field": rf,
                "left_value": str(ln), "right_value": str(rn),
                "difference": str(difference),
                "status": "ok" if ok else "conflict",
            })
            if not ok:
                conflicts.append({
                    "key": k,
                    "left": {"evidence_id": left_evidence_id, "label": left_label,
                             "row_index": lidx, "field": lf, "value": str(ln)},
                    "right": {"evidence_id": right_evidence_id, "label": right_label,
                              "row_index": ridx, "field": rf, "value": str(rn)},
                    "difference": str(difference),
                })

        if len(links) < MAX_LINKS:
            is_ambiguous = len(candidates) > 1 or right_match_counts[ridx] > 1
            links.append({
                "key": k,
                "status": status,
                "left": {"evidence_id": left_evidence_id, "label": left_label,
                         "row_index": lidx, "record": lrec},
                "right": {"evidence_id": right_evidence_id, "label": right_label,
                          "row_index": ridx, "record": rrec},
                "field_comparisons": field_comparisons,
                "ambiguous": is_ambiguous,
            })

    unmatched_left = [
        {"evidence_id": left_evidence_id, "label": left_label, "row_index": i,
         "key_value": str(lrec.get(left_key)),
         "record": {k: v for k, v in list(lrec.items())[:12]}}
        for i, lrec in enumerate(left_records)
        if i not in matched_left
    ][:MAX_LINKS]
    unmatched_right = [
        {"evidence_id": right_evidence_id, "label": right_label, "row_index": i,
         "key_value": str(rrec.get(right_key)),
         "record": {k: v for k, v in list(rrec.items())[:12]}}
        for i, rrec in enumerate(right_records)
        if i not in matched_right
    ][:MAX_LINKS]

    # passe finale : tout lien dont la contrepartie droite est partagée par plusieurs
    # liens gauches est ambigu (résolution non 1-pour-1) — cohérence sur le résultat complet
    right_use: dict[int, int] = {}
    for l in links:
        ri = l["right"]["row_index"]
        right_use[ri] = right_use.get(ri, 0) + 1
    for l in links:
        if right_use.get(l["right"]["row_index"], 0) > 1:
            l["ambiguous"] = True

    uncertain_count = sum(1 for l in links if l["status"] == "uncertain")
    return {
        "left": {"evidence_id": left_evidence_id, "label": left_label,
                 "key": left_key, "rows": len(left_records)},
        "right": {"evidence_id": right_evidence_id, "label": right_label,
                  "key": right_key, "rows": len(right_records)},
        "normalize": normalize,
        "links": links,
        "unmatched_left": unmatched_left,
        "unmatched_right": unmatched_right,
        "conflicts": conflicts,
        "ambiguous_keys": sorted(ambiguous_keys),
        "stats": {
            "matched": sum(1 for l in links if l["status"] == "matched"),
            "uncertain": uncertain_count,
            "unmatched_left": len(unmatched_left),
            "unmatched_right": len(unmatched_right),
            "conflicts": len(conflicts),
            "ambiguous_keys": len(ambiguous_keys),
        },
    }
