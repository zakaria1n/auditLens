"""Portail client web du DÉFI D'AUDIT INDÉPENDANT AuditLens (port 8091).

Affiche le statut des commandes du portail — qui peut diverger de la plateforme API.
Identifiants frais, données synthétiques isolées.

Lancer : uv run uvicorn test_services.challenge_portal:app --port 8091
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Portail client (défi AuditLens)")

# Statuts affichés par le portail (dérivent volontairement de l'API pour OC-7702)
_PORTAL_STATUS = {
    "OC-7701": "Livré", "OC-7702": "Livré", "OC-7703": "Livré", "OC-7704": "Livré",
    "OC-7705": "Livré", "OC-7706": "Livré", "OC-7707": "Livré", "OC-7708": "Livré",
    "OC-7709": "Livré", "OC-7710": "En cours", "OC-7711": "Livré", "OC-7712": "Livré",
}


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html><head><title>{title}</title></head>
<body><h1>{title}</h1>{body}
<p><a href="/">← Portail</a></p></body></html>"""


@app.get("/", response_class=HTMLResponse)
def portal():
    rows = "".join(
        f'<tr><td><a href="/order/{ref}">{ref}</a></td><td>{status}</td></tr>'
        for ref, status in _PORTAL_STATUS.items()
    )
    return _page("Portail client", f"<p>Portail de suivi des commandes clients.</p>"
                                  f"<table>{rows}</table>")


@app.get("/order/{ref}", response_class=HTMLResponse)
def order_detail(ref: str):
    status = _PORTAL_STATUS.get(ref)
    if status is None:
        return HTMLResponse(_page("Commande inconnue", "<p>Aucune commande avec cette référence.</p>"), status_code=404)
    return _page(f"Commande {ref}", f"<p>Référence : <strong>{ref}</strong></p>"
                                     f"<p>Statut de livraison : <strong>{status}</strong></p>")
