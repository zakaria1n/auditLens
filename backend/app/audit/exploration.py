"""Exploration de données bornée (Phase 2/10) : requêtes TYPÉES et DÉTERMINISTES
sur les preuves d'enregistrements d'une mission.

Le LLM décide QUOI explorer (spéc JSON validée par schéma) ; tous les calculs
(filtre, tri, groupe, agrégats, comparaison) sont exécutés ici, de façon
déterministe — jamais par le modèle. Aucun SQL, aucune exécution arbitraire.

Bornes : lignes d'entrée bornées au chargement (MAX_EXPLORE_ROWS), résultats
bornés (max_results), valeurs manquantes gérées explicitement (exclues des
agrégats numériques mais comptées dans `nulls`), champs ambigus => erreur claire.
La preuve source n'est JAMAIS modifiée : le résultat devient une nouvelle
evidence `exploration` avec provenance complète.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

MAX_EXPLORE_ROWS = 5000
MAX_RESULTS = 50


def _to_number(value: Any) -> Decimal | None:
    """Conversion numérique déterministe ; None si non numérique (géré par l'appelant)."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        return Decimal(str(value).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def apply_exploration(records: list[dict], spec: dict) -> dict[str, Any]:
    """Exécute une spéc d'exploration TYPÉE sur des enregistrements.

    spec = {
      "fields": [str] (optionnel, projection),
      "filter": [{"field", "op": eq|ne|gt|gte|lt|lte|contains|in|not_null, "value"}],
      "sort": [{"field", "dir": asc|desc}],
      "group_by": str, "aggregate": {"op": count|sum|avg|min|max, "field": str|None},
      "compare": {"left_field", "right_field", "op": eq|gt|lt|gte|lte},
      "limit": int<=50,
    }
    Retourne un dict sérialisable (table, groupes, comparaison, stats) — jamais d'exception
    métier : les champs inconnus/non numériques produisent des résultats EXPLICITES.
    """
    rows = records[:MAX_EXPLORE_ROWS]
    truncated_input = len(records) > MAX_EXPLORE_ROWS
    fields = spec.get("fields") or []
    unknown_fields: set[str] = set()

    def project(rec: dict) -> dict:
        if not fields:
            return rec
        return {f: rec.get(f) for f in fields}

    # --- filtres (chaînes ou numériques ; opérateurs bornés) ---
    for f in spec.get("filter") or []:
        field, op = str(f.get("field")), str(f.get("op"))
        value = f.get("value")
        if rows and field not in rows[0] and field != "*":
            unknown_fields.add(field)
            continue
        if op == "not_null":
            rows = [r for r in rows if r.get(field) is not None and r.get(field) != ""]
            continue
        if op == "in":
            allowed = value if isinstance(value, list) else [value]
            rows = [r for r in rows if str(r.get(field)) in {str(v) for v in allowed}]
            continue
        left_num, right_num = _to_number(rows[0].get(field)) if rows else None, _to_number(value)
        numeric = op in ("gt", "gte", "lt", "lte") or (op in ("eq", "ne") and right_num is not None)
        if numeric and right_num is not None:
            def keep(r: dict) -> bool:
                ln = _to_number(r.get(field))
                if ln is None:
                    return False
                return {
                    "eq": ln == right_num, "ne": ln != right_num, "gt": ln > right_num,
                    "gte": ln >= right_num, "lt": ln < right_num, "lte": ln <= right_num,
                }[op]
        else:
            def keep(r: dict) -> bool:
                haystack = str(r.get(field) or "")
                needle = str(value or "")
                return {"eq": haystack == needle, "ne": haystack != needle,
                        "contains": needle.lower() in haystack.lower(),
                        "gt": haystack > needle, "gte": haystack >= needle,
                        "lt": haystack < needle, "lte": haystack <= needle}[op]
        rows = [r for r in rows if keep(r)]

    # --- comparaison de champs (déterministe, par ligne) ---
    comparison: dict[str, Any] | None = None
    cmp_spec = spec.get("compare")
    if isinstance(cmp_spec, dict) and cmp_spec.get("left_field") and cmp_spec.get("right_field"):
        lf, rf, cop = str(cmp_spec["left_field"]), str(cmp_spec["right_field"]), str(cmp_spec.get("op", "ne"))
        mismatches: list[dict] = []
        match_count = 0
        for i, r in enumerate(rows):
            ln, rn = _to_number(r.get(lf)), _to_number(r.get(rf))
            if ln is None or rn is None:
                continue  # valeurs non numériques/non présentes : non comparables, explicites
            ok = {"eq": ln == rn, "ne": ln != rn, "gt": ln > rn,
                  "gte": ln >= rn, "lt": ln < rn, "lte": ln <= rn}[cop]
            if ok:
                match_count += 1
            elif len(mismatches) < MAX_RESULTS:
                mismatches.append({
                    "row_index": i, "left": str(r.get(lf)), "right": str(r.get(rf)),
                    "difference": str(ln - rn),
                })
        comparison = {
            "left_field": lf, "right_field": rf, "op": cop,
            "rows_compared": match_count + len(mismatches),
            "matches": match_count, "mismatches": mismatches,
            "mismatch_total": len(mismatches) + max(
                0, sum(
                    1 for r in rows
                    if _to_number(r.get(lf)) is not None and _to_number(r.get(rf)) is not None
                ) - match_count - len(mismatches),
            ),
        }

    # --- group_by + agrégat ---
    groups: list[dict] | None = None
    group_field = spec.get("group_by")
    agg = spec.get("aggregate") or {}
    if group_field:
        buckets: dict[str, list[dict]] = {}
        for r in rows:
            key = str(r.get(str(group_field)) if r.get(str(group_field)) is not None else "(vide)")
            buckets.setdefault(key, []).append(r)
        op = str(agg.get("op", "count"))
        agg_field = agg.get("field")
        groups = []
        for key, bucket in sorted(buckets.items(), key=lambda kv: -len(kv[1]))[:MAX_RESULTS]:
            entry: dict[str, Any] = {"value": key, "count": len(bucket)}
            if op != "count":
                if not agg_field:
                    entry["error"] = "aggregate.field requis pour sum/avg/min/max"
                else:
                    nums = [n for n in (_to_number(r.get(str(agg_field))) for r in bucket) if n is not None]
                    nulls = len(bucket) - len(nums)
                    if not nums:
                        entry["error"] = f"aucune valeur numérique dans {agg_field}"
                        entry["nulls"] = nulls
                    else:
                        entry.update({
                            "field": str(agg_field), "nulls": nulls,
                            "sum": str(sum(nums)), "avg": str((sum(nums) / len(nums)).quantize(Decimal("0.0001"))),
                            "min": str(min(nums)), "max": str(max(nums)),
                        })
                        entry = {k: entry[k] for k in (
                            "value", "count", "field", "sum", "avg", "min", "max", "nulls", "error") if k in entry}
            groups.append(entry)

    # --- tri (stable, numérique si la colonne est numérique sinon lexical) ---
    for s in reversed(spec.get("sort") or []):
        field, direction = str(s.get("field")), str(s.get("dir", "asc"))
        numeric = bool(rows) and _to_number(rows[0].get(field)) is not None
        rows.sort(
            key=(lambda r: (_to_number(r.get(field)) is None, _to_number(r.get(field)) or Decimal(0)))
            if numeric else (lambda r: (r.get(field) is None, str(r.get(field) or ""))),
            reverse=(direction == "desc"),
        )

    limit = min(int(spec.get("limit") or MAX_RESULTS), MAX_RESULTS)
    total_after = len(rows)
    table = [project(r) for r in rows[:limit]]

    return {
        "table": table,
        "total_input_rows": len(records),
        "explored_rows": len(rows),
        "input_truncated": truncated_input,
        "total_after_filters": total_after,
        "returned_rows": len(table),
        "limit": limit,
        "groups": groups,
        "comparison": comparison,
        "unknown_fields": sorted(unknown_fields),
    }
