"""Sources : enregistrement, test de connexion, upload de fichiers (docs/14)."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from ...core.ids import new_id
from ..deps import deps
from ...models import Evidence, SourceConnection, SourceStatus, SourceType, utcnow

router = APIRouter(prefix="/api/sources", tags=["sources"])

ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".json", ".jsonl")  # .jsonl : JSON Lines supporté par le parser
MAX_UPLOAD_MB = 25


class SourceCreate(BaseModel):
    name: str
    type: SourceType
    config: dict = Field(default_factory=dict)
    secrets: dict | None = None  # mot de passe Odoo / tokens API — jamais en DB ni dans les logs
    rule_set_id: str | None = None  # data contract choisi pour les fichiers (docs/09)


async def _create_initial_file_evidence(d, source: SourceConnection) -> Evidence | None:
    """L'import crée la première preuve (raw_file) : chemin + métadonnées, sans interprétation."""
    path = Path(str(source.config.get("path", "")))
    if not path.exists():
        return None
    ev = d.store.save(
        mission_id="_imports", run_id=None, source_id=source.id,
        type_="raw_file", title=f"Fichier importé — {source.name}",
        payload={
            "path": str(path),
            "original_name": source.config.get("original_name", path.name),
            "size_bytes": path.stat().st_size,
            "format": path.suffix.lower().lstrip("."),
        },
        provenance={"origin": "upload", "observed_at": utcnow()},
        evidence_id=new_id("evidence"),
    )
    await d.repo.create_evidence_meta(ev)
    return ev


@router.post("")
async def create_source(body: SourceCreate, request: Request):
    d = deps(request)
    if body.type == SourceType.file:
        raise HTTPException(400, "les sources fichier passent par POST /api/sources/file (upload)")
    if body.type == SourceType.odoo and not body.config.get("url"):
        raise HTTPException(400, "config.url requis pour une source Odoo")
    if body.type == SourceType.api and not body.config.get("base_url"):
        raise HTTPException(400, "config.base_url requis pour une source API")
    if body.type == SourceType.web and not body.config.get("base_url"):
        raise HTTPException(400, "config.base_url requis pour une source Web")

    source_id = new_id("source")
    config = dict(body.config)
    if body.rule_set_id:
        config["rule_set_id"] = body.rule_set_id
    secrets_ref = d.secrets.put(body.secrets) if body.secrets else None
    source = SourceConnection(id=source_id, name=body.name, type=body.type, config=config, secrets_ref=secrets_ref)
    await d.repo.create_source(source)
    return {"source": source.model_dump(), "evidence_id": None}


@router.post("/file")
async def upload_file_source(request: Request, file: UploadFile, name: str | None = None, rule_set_id: str | None = None):
    """Upload CSV/XLSX/JSON → source + première evidence (docs/09 workflow)."""
    d = deps(request)
    original_name = (file.filename or "fichier").replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"extension non autorisée {suffix} (autorisées: {ALLOWED_EXTENSIONS})")
    content = await file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"fichier trop gros (max {MAX_UPLOAD_MB} Mo)")

    d.settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    dest = d.settings.uploads_dir / f"{new_id('source')}{suffix}"
    dest.write_bytes(content)

    source_id = new_id("source")
    config = {"path": str(dest), "original_name": original_name}
    if rule_set_id:
        config["rule_set_id"] = rule_set_id
    source = SourceConnection(id=source_id, name=name or original_name, type=SourceType.file, config=config)
    await d.repo.create_source(source)
    ev = await _create_initial_file_evidence(d, source)
    return {"source": source.model_dump(), "evidence_id": ev.id if ev else None}


@router.post("/{source_id}/test")
async def test_source(source_id: str, request: Request):
    d = deps(request)
    source = await d.repo.get_source(source_id)
    if source is None:
        raise HTTPException(404, "source inconnue")
    try:
        connector = d.connectors.build(source)
    except Exception as exc:  # noqa: BLE001
        ok, message = False, f"connection_failed: {type(exc).__name__}: {exc}"
    else:
        try:
            ok, message = await connector.test_connection()
            await connector.close()
        except Exception as exc:  # noqa: BLE001
            ok, message = False, f"connection_failed: {type(exc).__name__}: {exc}"
    await d.repo.update_source_status(source_id, "connected" if ok else "failed", message, utcnow())
    updated = await d.repo.get_source(source_id)
    return {"ok": ok, "message": message, "source": updated.model_dump() if updated else None}


@router.get("")
async def list_sources(request: Request):
    d = deps(request)
    return {"sources": [s.model_dump() for s in await d.repo.list_sources()]}


@router.get("/{source_id}")
async def get_source(source_id: str, request: Request):
    d = deps(request)
    source = await d.repo.get_source(source_id)
    if source is None:
        raise HTTPException(404, "source inconnue")
    return {"source": source.model_dump()}


@router.delete("/{source_id}")
async def delete_source(source_id: str, request: Request):
    d = deps(request)
    source = await d.repo.get_source(source_id)
    if source is None:
        raise HTTPException(404, "source inconnue")
    if source.secrets_ref:
        d.secrets.delete(source.secrets_ref)
    await d.repo.delete_source(source_id)
    return {"deleted": source_id}
