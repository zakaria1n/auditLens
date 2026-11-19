"""Phase 4A fiabilité — identité de build sur /api/health (détection serveur stale).

Le commit git est lu dans le checkout au démarrage (jamais fabriqué) ; le PID
permet de vérifier que le port 8000 sert bien le processus attendu (RUNBOOK).
"""

from __future__ import annotations

import os


async def test_health_reports_build_identity(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["started_at"]  # horodatage de démarrage
    assert body["environment"] == os.environ.get("AUDITLENS_ENV", "development")
    assert isinstance(body["pid"], int) and body["pid"] > 0
    # commit : présent dans ce checkout git (12 hex) ou None hors repo — jamais inventé
    commit = body["git_commit"]
    assert commit is None or (len(commit) == 12 and all(c in "0123456789abcdef" for c in commit))
