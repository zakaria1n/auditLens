"""Minimisation / redaction — aucun secret dans les résultats de tools (docs/05, docs/13)."""

from __future__ import annotations

from typing import Any

SENSITIVE_KEYS = {
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "token",
    "access_token",
    "refresh_token",
    "cookie",
    "cookies",
    "session",
    "session_id",
    "private_key",
    "credentials",
    "proxy_authorization",
    "set_cookie",
    "x_api_key",
}

SENSITIVE_SUBSTRINGS = ("password", "secret", "token", "apikey", "api_key", "cookie", "authorization")

REDACTED = "[REDACTED]"


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    if k in SENSITIVE_KEYS:
        return True
    return any(s in k for s in SENSITIVE_SUBSTRINGS)


def redact(obj: Any, _depth: int = 0) -> Any:
    """Supprime récursivement les valeurs sensibles d'une structure sérialisable."""
    if _depth > 20:
        return obj
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and _is_sensitive(k):
                out[k] = REDACTED
            else:
                out[k] = redact(v, _depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(v, _depth + 1) for v in obj]
    return obj


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: (REDACTED if _is_sensitive(k) else str(v)) for k, v in headers.items()}
