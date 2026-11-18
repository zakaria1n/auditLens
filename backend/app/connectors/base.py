"""Contrat de connecteur (docs/06) : test_connection, discover, close.

Les connecteurs retournent des FAITS, jamais un jugement de conformité.
Le collect est effectué par les tools via les connecteurs ; chaque résultat
est normalisé en Evidence par la couche tools.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..models import SourceConnection


class Connector(Protocol):
    async def test_connection(self) -> tuple[bool, str]:
        """(ok, message). message peut contenir une cause technique sans secret."""
        ...

    async def discover(self) -> dict[str, Any]:
        """CapabilityManifest : ce que cette source peut fournir dans le scope autorisé."""
        ...

    async def close(self) -> None:
        ...


class ConnectorFactory:
    """Construit les connecteurs selon le type de source ; charge les secrets par référence."""

    def __init__(self, repo, secrets_store):
        self.repo = repo
        self.secrets_store = secrets_store

    async def get_source(self, source_id: str) -> SourceConnection | None:
        return await self.repo.get_source(source_id)

    def secrets_for(self, source: SourceConnection | None) -> dict:
        if source is None:
            return {}
        return self.secrets_store.get(source.secrets_ref)

    def build(self, source: SourceConnection) -> Any:
        """Instancie le connecteur concret selon le type."""
        secrets = self.secrets_for(source)
        if source.type == "odoo":
            from .odoo.connector import OdooConnector

            return OdooConnector(source.config, secrets)
        if source.type == "api":
            from .api.connector import RestApiConnector

            return RestApiConnector(source.config, secrets)
        if source.type == "web":
            from .web.connector import WebConnector

            return WebConnector(source.config, secrets)
        if source.type == "file":
            from .files.connector import FileConnector

            return FileConnector(source.config)
        raise ValueError(f"Type de source inconnu: {source.type}")
