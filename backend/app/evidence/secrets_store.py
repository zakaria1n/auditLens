"""Store de secrets : hors DB, hors repo, hors logs (docs/13).

V1 mono-utilisateur : fichier JSON local (gitignored) référencé par `secrets_ref`.
Ne jamais renvoyer les valeurs par l'API — seules les références sortent.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path


class SecretsStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, dict]) -> None:
        # Écriture atomique simple + permissions restreintes quand supporté
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass  # Windows/POSIX différences acceptées pour la démo locale

    def put(self, secrets: dict) -> str:
        ref = f"sec_{uuid.uuid4().hex[:8]}"
        data = self._read()
        data[ref] = dict(secrets)
        self._write(data)
        return ref

    def get(self, ref: str | None) -> dict:
        if not ref:
            return {}
        return dict(self._read().get(ref, {}))

    def delete(self, ref: str) -> None:
        data = self._read()
        data.pop(ref, None)
        self._write(data)
