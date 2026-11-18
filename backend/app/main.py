"""AuditLens Backend — FastAPI modular monolith (docs/03)."""

from __future__ import annotations

from contextlib import asynccontextmanager

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
from .persistence.database import Database
from .persistence.repository import Repository
from .tools import register_all_tools


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
    return {"status": "ok", "service": "auditlens-backend", "version": "0.1.0"}
