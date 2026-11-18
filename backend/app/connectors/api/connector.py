"""Connecteur REST API — HTTPX, allowlist stricte, OpenAPI (docs/08).

- Endpoints déclarés et approuvés dans la config source ; pas de fetch arbitraire.
- Auth côté backend uniquement ; jamais dans les evidences (headers redactés).
- SSRF : validate_url sur chaque requête et chaque redirection.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ...core.redact import redact_headers
from ..ssrf import assert_redirect_allowed, validate_url

MAX_BODY_BYTES = 20_000  # extrait de réponse, pas de dump brut (docs/06)
MAX_ENDPOINTS = 20


class RestApiConnector:
    def __init__(self, config: dict[str, Any], secrets: dict[str, Any]):
        self.base_url = str(config.get("base_url", "")).rstrip("/")
        self.endpoints: list[dict[str, Any]] = list(config.get("endpoints", []))[:MAX_ENDPOINTS]
        self.openapi_url = config.get("openapi_url")
        self.timeout = float(config.get("timeout_s", 10))
        self.allow_private = bool(config.get("allow_private_host", False))
        self._headers = dict(config.get("headers", {}))
        auth = secrets.get("auth") or {}
        if auth.get("type") == "bearer":
            self._headers["Authorization"] = f"Bearer {auth.get('token', '')}"
        elif auth.get("type") == "header" and auth.get("name"):
            self._headers[str(auth["name"])] = str(auth.get("value", ""))

    @property
    def allowed_hosts(self) -> set[str]:
        from urllib.parse import urlparse

        hosts = {urlparse(self.base_url).hostname or ""}
        if self.openapi_url:
            hosts.add(urlparse(self.openapi_url).hostname or "")
        return hosts

    def _endpoint(self, endpoint_id: str) -> dict[str, Any] | None:
        return next((e for e in self.endpoints if e.get("id") == endpoint_id), None)

    def _full_url(self, endpoint: dict[str, Any], filters: dict | None = None) -> str:
        path = str(endpoint.get("path", "")).strip()
        if not path.startswith("/"):
            path = "/" + path
        # Substitution bornée des paramètres de path déclarés (ex. /orders/{order_id}) :
        # seule la valeur fournie dans filters est insérée, encodée — jamais de path arbitraire.
        for key, value in (filters or {}).items():
            token = "{" + str(key) + "}"
            if token in path:
                from urllib.parse import quote

                path = path.replace(token, quote(str(value), safe=""))
        return self.base_url + path

    async def test_connection(self) -> tuple[bool, str]:
        try:
            validate_url(self.base_url, self.allowed_hosts, allow_private=self.allow_private)
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                resp = await client.get(self.base_url)
            return True, f"base joignable — HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            return False, f"connection_failed: {type(exc).__name__}: {exc}"

    async def discover(self) -> dict[str, Any]:
        caps: dict[str, Any] = {
            "connector": "api",
            "base_url": self.base_url,
            "endpoints": [
                {"id": e.get("id"), "method": e.get("method", "GET"), "path": e.get("path")}
                for e in self.endpoints
            ],
            "openapi_available": bool(self.openapi_url),
        }
        if self.openapi_url:
            try:
                validate_url(str(self.openapi_url), self.allowed_hosts, allow_private=self.allow_private)
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                    resp = await client.get(self.openapi_url)
                if resp.status_code == 200 and "json" in resp.headers.get("content-type", ""):
                    spec = resp.json()
                    caps["openapi"] = {
                        "title": spec.get("info", {}).get("title"),
                        "version": spec.get("info", {}).get("version"),
                        "paths_count": len(spec.get("paths", {})),
                    }
                else:
                    caps["openapi"] = {"error": f"HTTP {resp.status_code}"}
            except Exception as exc:  # noqa: BLE001
                caps["openapi"] = {"error": f"{type(exc).__name__}: {exc}"}
        return caps

    async def fetch(self, endpoint_id: str, filters: dict | None = None, method: str | None = None) -> dict[str, Any]:
        """Requête vérifiable → trace complète (statut, durée, extrait redacté).

        Les filters dont la clé correspond à un `{param}` du path sont substitués dans
        le path ; les autres partent en query string (comportement historique conservé).
        """
        endpoint = self._endpoint(endpoint_id)
        if endpoint is None:
            raise ValueError(f"endpoint non approuvé ou inconnu: {endpoint_id}")
        method = (method or endpoint.get("method", "GET")).upper()
        url = self._full_url(endpoint, filters)
        import re as _re

        path_tokens = _re.findall(r"\{([^}]+)\}", str(endpoint.get("path", "")))
        query_filters = {k: v for k, v in (filters or {}).items() if k not in path_tokens}
        if "{" in url:
            # Paramètre obligatoire non fourni : erreur explicite plutôt qu'un fetch du template.
            missing = _re.findall(r"\{([^}]+)\}", url)
            raise ValueError(f"endpoint paramétré {endpoint_id!r}: fournir filters pour {missing}")

        validate_url(url, self.allowed_hosts, allow_private=self.allow_private, method=method)
        started = time.monotonic()
        redirects_blocked: list[str] = []
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            resp = await client.request(
                method, url, params=query_filters or None, headers=self._headers, json=endpoint.get("json_body"),
            )
            # Bloquer toute redirection non autorisée (anti-SSRF docs/08)
            while 300 <= resp.status_code < 400 and "location" in resp.headers:
                location = resp.headers["location"]
                try:
                    assert_redirect_allowed(location, self.allowed_hosts, allow_private=self.allow_private)
                    validate_url(location, self.allowed_hosts, allow_private=self.allow_private, method=method)
                    resp = await client.request(method, location, headers=self._headers)
                except Exception as exc:
                    redirects_blocked.append(f"{location}: {exc}")
                    break
        latency_ms = int((time.monotonic() - started) * 1000)

        body = resp.text[:MAX_BODY_BYTES]
        content_type = resp.headers.get("content-type", "")
        parsed: Any = None
        if "json" in content_type:
            try:
                parsed = resp.json()
            except ValueError:
                parsed = None

        return {
            "endpoint_id": endpoint_id,
            "request": {"method": method, "url": url, "params": filters or {}, "headers": redact_headers(self._headers)},
            "response": {
                "status": resp.status_code,
                "content_type": content_type,
                "latency_ms": latency_ms,
                "body_bytes": len(resp.content),
                "body_excerpt": body,
                "json": parsed if isinstance(parsed, (dict, list)) else None,
                "headers": redact_headers(dict(resp.headers)),
            },
            "redirects_blocked": redirects_blocked,
            "observed_at_latency": latency_ms,
        }

    async def close(self) -> None:
        return None
