"""Erreurs métier AuditLens."""

from __future__ import annotations


class AuditLensError(Exception):
    """Erreur de base du domaine."""


class PolicyViolation(AuditLensError):
    """Demande refusée par le Policy Gate (docs/05)."""


class SourceUnavailable(AuditLensError):
    """Source injoignable : `connection_failed`, jamais `non_conforme` (docs/06)."""


class SchemaMismatch(AuditLensError):
    """Changement d'API / schéma inattendu (docs/06)."""


class EvidenceNotFound(AuditLensError):
    """Evidence ID inconnu ou hors mission."""


class ScopeViolation(AuditLensError):
    """Accès hors périmètre de mission (docs/13 — cross-project)."""


class ProviderError(AuditLensError):
    """Échec du fournisseur LLM."""
