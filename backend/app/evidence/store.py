"""Evidence Store : répertoire privé, checksum SHA-256, immuable pendant l'audit (docs/03, docs/05, docs/13).

- Les payloads sont écrits en JSON canonique ; le checksum porte sur ces octets.
- La relecture vérifie l'intégrité `depuis collecte`, pas la véracité initiale du contenu.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..models import Evidence
from ..models.schemas import utcnow


def canonical_bytes(obj: Any) -> bytes:
    """Sérialisation déterministe pour hashing stable."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class EvidenceStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _mission_dir(self, mission_id: str) -> Path:
        d = self.root / mission_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(
        self,
        *,
        mission_id: str,
        run_id: str | None,
        source_id: str | None,
        type_: str,
        title: str,
        payload: dict[str, Any],
        provenance: dict[str, Any],
        record_count: int | None = None,
        summary: dict[str, Any] | None = None,
        evidence_id: str,
        attachments: dict[str, bytes] | None = None,
    ) -> Evidence:
        """Écrit une preuve + pièces jointes binaires (captures, fichiers bruts)."""
        data = {
            "id": evidence_id,
            "mission_id": mission_id,
            "run_id": run_id,
            "source_id": source_id,
            "type": type_,
            "title": title,
            "observed_at": utcnow(),
            "provenance": provenance,
            "payload": payload,
        }
        payload_bytes = canonical_bytes(data)
        checksum = sha256_bytes(payload_bytes)
        storage_ref = str(Path(mission_id) / f"{evidence_id}.json")
        self._mission_dir(mission_id)  # garantit le répertoire
        (self.root / storage_ref).write_bytes(payload_bytes)

        if attachments:
            att_dir = self._mission_dir(mission_id) / f"{evidence_id}_files"
            att_dir.mkdir(exist_ok=True)
            for name, content in attachments.items():
                (att_dir / name).write_bytes(content)

        return Evidence(
            id=evidence_id,
            mission_id=mission_id,
            run_id=run_id,
            source_id=source_id,
            type=type_,
            title=title,
            observed_at=data["observed_at"],
            provenance=provenance,
            checksum=checksum,
            storage_ref=storage_ref,
            record_count=record_count,
            summary=summary,
        )

    def load(self, evidence: Evidence) -> dict[str, Any]:
        """Recharge le payload depuis le disque et vérifie le checksum (docs/13)."""
        path = self.root / evidence.storage_ref
        if not path.exists():
            raise FileNotFoundError(f"Evidence manquante: {evidence.storage_ref}")
        raw = path.read_bytes()
        actual = sha256_bytes(raw)
        if actual != evidence.checksum:
            raise ValueError(
                f"Intégrité evidence {evidence.id}: checksum inattendu (modifiée depuis collecte)"
            )
        return json.loads(raw.decode("utf-8"))

    def verify(self, evidence: Evidence) -> bool:
        try:
            self.load(evidence)
            return True
        except (FileNotFoundError, ValueError):
            return False
