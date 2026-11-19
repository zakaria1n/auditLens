"""AuditLens Backend — FastAPI modular monolith (docs/03)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent.orchestrator import RunOrchestrator
from .api.events import EventBus
from .api.routes import conversations, findings, missions, reports, runs, settings_llm, sources
from .connectors.base import ConnectorFactory
from .core.settings import get_settings
from .evidence.secrets_store import SecretsStore
from .evidence.store import EvidenceStore
from .harness.executor import ToolExecutor
from .harness.policy import PolicyGate
from .harness.registry import ToolRegistry
from .models import utcnow
from .persistence.database import Database
from .persistence.repository import Repository
from .tools import register_all_tools


def _resolve_build_commit(repo_root: Path) -> str | None:
    """Commit git lu dans le checkout au démarrage (diagnostic anti-serveur-stale).
    None si indisponible (hors repo git, archives) — jamais fabriqué."""
    try:
        head = (repo_root / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref:"):
            ref = head[5:]
            ref_file = repo_root / ".git" / ref
            if ref_file.exists():
                return ref_file.read_text().strip()[:12]
            packed = repo_root / ".git" / "packed-refs"
            if packed.exists():
                for line in packed.read_text().splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == ref:
                        return parts[0][:12]
            return None
        return head[:12] if len(head) >= 8 else None
    except OSError:
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    for d in (settings.data_dir, settings.evidence_dir, settings.uploads_dir, settings.demo_dir):
        d.mkdir(parents=True, exist_ok=True)

    db = Database(str(settings.db_path))
    await db.connect()
    repo = Repository(db)
    store = EvidenceStore(settings.evidence_dir)
    secrets = SecretsStore(settings.secrets_path)
    registry = ToolRegistry()
    input_models = register_all_tools(registry)
    gate = PolicyGate()
    executor = ToolExecutor(registry, gate)
    connectors = ConnectorFactory(repo, secrets)
    bus = EventBus(repo)
    run_controls: dict[str, set[str]] = {}  # ADR-15 : demandes pause/stop par run_id
    orchestrator = RunOrchestrator(repo, store, connectors, executor, bus, input_models, controls=run_controls)

    app.state.settings = settings
    app.state.build_commit = _resolve_build_commit(Path(__file__).resolve().parents[2])
    app.state.started_at = utcnow()
    app.state.environment = os.environ.get("AUDITLENS_ENV", "development")
    app.state.db = db
    app.state.repo = repo
    app.state.store = store
    app.state.secrets = secrets
    app.state.registry = registry
    app.state.executor = executor
    app.state.connectors = connectors
    app.state.bus = bus
    app.state.orchestrator = orchestrator
    app.state.steering_queue = orchestrator.steering
    app.state.input_models = input_models
    app.state.llm_runtime = {}  # BYOK en mémoire uniquement (docs/10)
    app.state.run_controls = run_controls  # pause/stop runtime (ADR-15)
    app.state.chat_controls = {}  # annulation tour chat (ADR-16)
    import asyncio

    app.state.run_semaphore = asyncio.Semaphore(2)  # worker local borné (docs/03)
    app.state.background_tasks = set()

    yield
    await db.close()


app = FastAPI(
    title="AuditLens API",
    version="0.1.0",
    description="Agent d'audit LLM + Tool Harness — preuves vérifiables, revue humaine.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sources.router)
app.include_router(missions.router)
app.include_router(runs.router)
app.include_router(findings.router)
app.include_router(settings_llm.router)
app.include_router(conversations.router)
app.include_router(reports.router)


@app.get("/api/health")
async def health():
    """Santé + identité de build (diagnostic dev) : détecter un serveur stale
    (code ancien servi après modifications) sans infrastructure supplémentaire."""
    return {
        "status": "ok",
        "service": "auditlens-backend",
        "version": app.version,
        "git_commit": getattr(app.state, "build_commit", None),
        "started_at": getattr(app.state, "started_at", None),
        "environment": getattr(app.state, "environment", "unknown"),
        "pid": os.getpid(),
    }
