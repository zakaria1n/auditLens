"""Accès aux dépendances de l'application (app.state)."""

from __future__ import annotations

from fastapi import Request

from ..agent.orchestrator import RunOrchestrator
from ..api.events import EventBus
from ..connectors.base import ConnectorFactory
from ..core.settings import Settings
from ..evidence.secrets_store import SecretsStore
from ..evidence.store import EvidenceStore
from ..harness.executor import ToolExecutor
from ..persistence.repository import Repository


class AppDeps:
    def __init__(self, request: Request):
        s = request.app.state
        self.settings: Settings = s.settings
        self.repo: Repository = s.repo
        self.store: EvidenceStore = s.store
        self.secrets: SecretsStore = s.secrets
        self.executor: ToolExecutor = s.executor
        self.connectors: ConnectorFactory = s.connectors
        self.bus: EventBus = s.bus
        self.orchestrator: RunOrchestrator = s.orchestrator
        self.input_models: dict = s.input_models
        self.llm_runtime: dict = s.llm_runtime
        self.run_controls: dict = s.run_controls  # ADR-15 : demandes pause/stop
        self.run_semaphore = s.run_semaphore
        self.tasks: set = s.background_tasks


def deps(request: Request) -> AppDeps:
    return AppDeps(request)
