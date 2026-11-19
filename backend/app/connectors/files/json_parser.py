"""Parsing JSON robuste (Phase 2A) : structures imbriquées, bornes explicites.

- Racines acceptées : tableau d'objets, objet contenant un tableau dominant,
  objet seul (enregistrement unique), primitif (une ligne, une colonne `value`),
  JSONL si le JSON standard échoue (extension .json/.jsonl).
- Imbrication : objets aplatis en chemins pointés (`a.b.c`) ; tableaux d'objets
  imbriqués sérialisés en chaîne JSON compacte (cellule explicite, jamais perdu) ;
  profondeur bornée (MAX_DEPTH), taille fichier bornée (MAX_BYTES).
- Retourne (records, structure) : `structure` décrit la racine, les champs avec
  types/chemins, candidats identifiants, tableau source — rien d'inventé.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_BYTES = 10 * 1024 * 1024   # 10 Mo
MAX_DEPTH = 12
MAX_RECORDS = 100_000

ID_HINTS = ("_id", "id", "ref", "code", "number", "key")


def load_json_file(path: Path) -> tuple[Any, str]:
    """Charge le fichier. Retourne (données, kind) où kind ∈ json|jsonl.
    Lève ValueError avec message clair si malformé/trop grand."""
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise ValueError(f"fichier trop grand ({size} octets > {MAX_BYTES})")
    raw = path.read_bytes().decode("utf-8", errors="replace")
    try:
        return json.loads(raw), "json"
    except json.JSONDecodeError:
        # JSONL : un objet par ligne non vide
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        if len(lines) >= 1:
            try:
                records = [json.loads(ln) for ln in lines]
                return records, "jsonl"
            except json.JSONDecodeError:
                pass
        raise ValueError("JSON malformé (syntaxe invalide)")


def _flatten(obj: Any, prefix: str, depth: int, out: dict[str, Any]) -> None:
    if depth > MAX_DEPTH:
        out[prefix] = json.dumps(obj, ensure_ascii=False)
        return
    if isinstance(obj, dict):
        if not obj:
            return
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                _flatten(v, key, depth + 1, out)
            else:
                out[key] = v
    elif isinstance(obj, list):
        # tableau de scalaires : cellule JSON compacte ; tableau d'objets : idem
        # (l'exploration des tableaux imbriqués reste possible via la cellule)
        out[prefix] = json.dumps(obj, ensure_ascii=False)
    else:
        out[prefix] = obj


def _scalar_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "object"


def normalize_records(data: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Normalise en liste d'enregistrements aplatis + métadonnées de structure."""
    structure: dict[str, Any] = {}

    if isinstance(data, list):
        records_raw = data[:MAX_RECORDS]
        structure["root"] = "array"
        structure["root_length"] = len(data)
        structure["truncated_records"] = len(data) > MAX_RECORDS
    elif isinstance(data, dict):
        # objet contenant un tableau dominant => ce tableau devient la liste
        array_fields = [(k, v) for k, v in data.items() if isinstance(v, list)]
        if array_fields:
            k, v = max(array_fields, key=lambda kv: len(kv[1]))
            records_raw = v[:MAX_RECORDS]
            structure["root"] = "object_with_array"
            structure["root_array_field"] = k
            structure["root_length"] = len(v)
            structure["truncated_records"] = len(v) > MAX_RECORDS
            structure["sibling_fields"] = [
                key for key in data.keys() if key != k and not isinstance(data[key], list)
            ]
        else:
            records_raw = [data]
            structure["root"] = "object"
            structure["root_length"] = 1
    else:
        records_raw = [{"value": data}]
        structure["root"] = "primitive"
        structure["root_length"] = 1

    records: list[dict[str, Any]] = []
    for rec in records_raw:
        if not isinstance(rec, dict):
            rec = {"value": rec}
        flat: dict[str, Any] = {}
        _flatten(rec, "", 0, flat)
        records.append(flat)

    # --- champs : chemins, types observés, valeurs manquantes ---
    field_info: dict[str, dict[str, Any]] = {}
    for rec in records:
        for k, v in rec.items():
            info = field_info.setdefault(k, {"types": set(), "missing": 0, "count": 0})
            if v is None or v == "":
                info["missing"] += 1
            else:
                info["count"] += 1
                info["types"].add(_scalar_type(v))
    structure["fields"] = [
        {
            "path": path,
            "types": sorted(info["types"]),
            "missing": len(records) - info["count"],
            "filled": info["count"],
        }
        for path, info in sorted(field_info.items())
    ]
    structure["field_count"] = len(structure["fields"])

    # candidats identifiants : champ terminal se terminant par un hint, rempli partout
    structure["candidate_identifiers"] = [
        f["path"] for f in structure["fields"]
        if any(f["path"].split(".")[-1].lower().endswith(h) or f["path"].split(".")[-1].lower() == h
               for h in ID_HINTS)
        and all(f["path"] in r for r in records)
    ][:5]

    # tableaux imbriqués détectés (cellules JSON compactes commençant par '[')
    structure["nested_arrays"] = sorted({
        k for rec in records for k, v in rec.items()
        if isinstance(v, str) and v.startswith("[")
    })[:10]
    return records, structure


def load_json_records(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data, kind = load_json_file(path)
    records, structure = normalize_records(data)
    structure["kind"] = kind
    return records, structure
