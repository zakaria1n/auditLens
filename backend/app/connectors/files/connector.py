"""Connecteur Fichiers — CSV/XLSX/JSON via pandas (docs/09).

- Extensions et taille limitées ; parsing local ; pas de macros ; XML exclu en V1.
- Le connecteur retourne des DataFrames ; l'interprétation métier reste à l'agent + règles.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_ROWS = 100_000


class FileConnector:
    def __init__(self, config: dict[str, Any]):
        self.path = Path(str(config.get("path", "")))
        self.original_name = str(config.get("original_name", self.path.name))

    def _suffix(self) -> str:
        return self.path.suffix.lower()

    def _load_sync(self) -> "Any":  # pandas.DataFrame
        import pandas as pd

        suffix = self._suffix()
        if suffix == ".csv":
            return pd.read_csv(self.path)
        if suffix == ".xlsx":
            return pd.read_excel(self.path, engine="openpyxl")
        if suffix == ".json":
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                import pandas as pd

                return pd.DataFrame(data)
            if isinstance(data, dict) and isinstance(next(iter(data.values()), None), list):
                # {"records": [...]} — première liste trouvée
                for v in data.values():
                    if isinstance(v, list):
                        return pd.DataFrame(v)
                raise ValueError("JSON sans tableau d'enregistrements")
            raise ValueError("JSON doit être un tableau d'objets ou un objet contenant un tableau")
        raise ValueError(f"format non supporté en V1: {suffix} (CSV/XLSX/JSON uniquement)")

    async def load_dataframe(self):
        import asyncio

        return await asyncio.to_thread(self._load_sync)

    async def test_connection(self) -> tuple[bool, str]:
        if not self.path.exists():
            return False, f"connection_failed: fichier introuvable: {self.path.name}"
        if self._suffix() not in (".csv", ".xlsx", ".json"):
            return False, f"connection_failed: extension non supportée {self._suffix()}"
        try:
            df = await self.load_dataframe()
            return True, f"fichier lisible — {len(df)} lignes, {len(df.columns)} colonnes"
        except Exception as exc:  # noqa: BLE001
            return False, f"connection_failed: {type(exc).__name__}: {exc}"

    async def discover(self) -> dict[str, Any]:
        df = await self.load_dataframe()
        size_bytes = self.path.stat().st_size
        return {
            "connector": "file",
            "file": self.original_name,
            "format": self._suffix().lstrip("."),
            "rows": int(len(df)),
            "truncated": bool(len(df) > MAX_ROWS),
            "columns": [
                {
                    "name": str(c),
                    "dtype": str(df[c].dtype),
                    "nulls": int(df[c].isna().sum()),
                    "unique": int(df[c].nunique(dropna=True)),
                }
                for c in df.columns
            ],
            "size_bytes": size_bytes,
        }

    async def close(self) -> None:
        return None
