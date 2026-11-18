"""App web de test pour auditer AuditLens (docs/08) — parcours avec anomalie contrôlée.

Anomalie PLANTÉE (l'audit doit la détecter) :
  W1. Le parcours "paiement" échoue : le bouton Payer appelle /pay qui renvoie 500
      → étape expect_status en échec dans le journey.
  W2. /checkout génère une erreur JavaScript console (capturée par le connecteur).
Parcours nominal qui passe :
  - goto / → expect_selector "Boutique"
  - goto /checkout → expect_text "Panier"

Lancer : uv run uvicorn test_services.web_app:app --port 8081
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Boutique de test (AuditLens)")


@app.get("/", response_class=HTMLResponse)
def home():
    return """<!doctype html><html><head><title>Boutique de test</title></head>
<body><h1>Boutique de démonstration</h1>
<p>Catalogue minimal pour parcours d'audit.</p>
<a href="/checkout"><button id="commander">Commander</button></a>
</body></html>"""


@app.get("/checkout", response_class=HTMLResponse)
def checkout():
    return """<!doctype html><html><head><title>Panier</title></head>
<body><h1>Panier</h1><p id="panier">1 x Clavier mécanique — 49,90 MAD</p>
<form action="/pay" method="get">
  <input name="card" placeholder="Numéro de carte" value="4242424242424242"/>
  <button id="payer" type="submit">Payer</button>
</form>
<script>
  // W2 : erreur JS console volontaire (capturée comme console_errors par le connecteur)
  console.error("Erreur JS plantée: window.analytics est undefined (anomalie W2)");
</script>
</body></html>"""


@app.get("/pay", response_class=HTMLResponse)
def pay(card: str = ""):
    # W1 : le paiement échoue systématiquement avec une erreur serveur
    return HTMLResponse("<h1>Erreur interne du paiement</h1><p>gateway_timeout</p>", status_code=500)


@app.get("/orders", response_class=HTMLResponse)
def orders():
    # W3 : la page « Vos commandes » plante systématiquement (erreur serveur)
    # — visible uniquement si l'auditeur déclare/étend le parcours vers /orders
    return HTMLResponse("<h1>Erreur interne</h1><p>orders_page_error (anomalie W3)</p>", status_code=500)
