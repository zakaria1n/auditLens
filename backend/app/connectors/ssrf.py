"""Garde SSRF (docs/08, docs/13) : allowlist de hosts, blocage plages privées, rebinding DNS.

- Les destinations sont limitées aux hosts explicitement configurés par la source.
- Chaque URL est résolue : toutes les IP doivent être autorisées (pas de DNS rebinding).
- Loopback / réseaux privés : refusés SAUF host local explicitement autorisé
  (ex. Odoo local — cas scellé docs/05 ; app de test locale déclarée par l'utilisateur).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from ..core.errors import PolicyViolation

BLOCKED_HOSTNAMES = {"169.254.169.254"}  # metadata cloud


def is_private_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved


def validate_url(
    url: str,
    allowed_hosts: set[str],
    *,
    allow_private: bool = False,
    allowed_methods: tuple[str, ...] = ("GET", "POST", "HEAD"),
    method: str = "GET",
) -> str:
    """Valide une URL sortante. Retourne l'URL normalisée ou lève PolicyViolation."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise PolicyViolation(f"scheme non autorisé: {parsed.scheme or '(absent)'}")
    host = parsed.hostname
    if not host:
        raise PolicyViolation("URL sans host")
    if host.lower() in BLOCKED_HOSTNAMES:
        raise PolicyViolation("host bloqué (metadata service)")
    if method.upper() not in allowed_methods:
        raise PolicyViolation(f"méthode HTTP non autorisée: {method}")

    host_ok = host.lower() in {h.lower() for h in allowed_hosts}
    if not host_ok:
        raise PolicyViolation(f"host hors allowlist: {host}")

    # Résolution DNS : toutes les IP doivent être acceptables (anti-rebinding).
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        raise PolicyViolation(f"résolution DNS impossible pour {host}: {exc}") from exc
    for info in infos:
        ip = info[4][0]
        if not allow_private and is_private_ip(ip):
            raise PolicyViolation(f"adresse privée/loopback refusée pour {host}: {ip}")
    return url


def assert_redirect_allowed(location: str, allowed_hosts: set[str], *, allow_private: bool = False) -> None:
    """Une redirection vers un host non autorisé doit être bloquée (docs/08)."""
    parsed = urlparse(location)
    host = parsed.hostname or ""
    if host.lower() not in {h.lower() for h in allowed_hosts}:
        raise PolicyViolation(f"redirection hors allowlist refusée: {location}")
    validate_url(location, allowed_hosts, allow_private=allow_private, method="GET")
