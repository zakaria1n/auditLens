# AuditLens Backend (FastAPI)

Backend du modular monolith AuditLens V1 : agent d'audit LLM + Tool Harness,
preuves vérifiables (SHA-256), connecteurs Odoo/API/Web/Fichiers, revue humaine.

## Démarrage

```bash
cd backend
uv sync                      # installe les dépendances (Python 3.11)
uv run uvicorn app.main:app --port 8000 --reload
```

- Santé : http://localhost:8000/api/health
- Docs interactives : http://localhost:8000/docs
- CORS autorisé pour le frontend : http://localhost:5173

## Tests

```bash
uv run pytest            # 18 tests : unitaires + slice verticale (mock LLM)
```

Couverture d'acceptation (docs/17) : FAIL sur anomalies injectées, PASS sur données
conformes, `insufficient_evidence` jamais converti en pass, tool non autorisée
refusée par le Policy Gate et journalisée, evidence hallucinée rejetée par le
validateur, intégrité des preuves vérifiée par checksum.

## Données de démo

```bash
uv run python demo_data/generate_demo.py all
# data/demo/faulty/ (seed 9831, 6 anomalies injectées) et data/demo/clean/
# ground_truth.json caché à l'agent (visible_to_agent=false) — docs/12
```

Flux démo sans clé API (MockLLM) : upload `data/demo/faulty/orders.csv`
(règle `rs_orders_v1`) → mission avec contrôle `DATA-01` → `POST /run`
`{"provider":"mock"}` → preuves, assessment `fail`, finding en review,
rapport versionné.

## Configuration LLM (BYOK — docs/10)

Par défaut `mock` (aucune clé, déterministe). Pour un provider réel :

```bash
# variables d'environnement
AUDITLENS_LLM_PROVIDER=opencode    # opencode|openai|gemini|anthropic|deepseek|compatible|mock
AUDITLENS_LLM_MODEL=glm-5.3-flash-free
AUDITLENS_LLM_KEY=                 # opencode : vide => "public" (modèles -free Zen)
AUDITLENS_LLM_BASE_URL=            # optionnel (compatible / Gemini)
```

- **OpenCode Zen** (`opencode`) : `https://opencode.ai/zen/v1`, modèles `-free` anonymes
  (`glm-5.3-flash-free`, …) avec `api_key="public"` — ~200 req/jour/IP, erreur 429 explicite
  à l'épuisement. Nos prompts ne dépendent pas du tool-calling natif (JSON dans le prompt).
- Gemini passe par l'endpoint OpenAI-compatible ; DeepSeek par `https://api.deepseek.com/v1`.
- La clé n'est jamais persistée, loggée ni renvoyée par l'API.
- La compatibilité de chaque modèle doit être testée avant usage (matrice docs/10).

## Connecteurs

| Type | Config | Notes |
|---|---|---|
| `odoo` | `{"url":"http://localhost:8069","db":"...","username":"..."}` + secret `{"password":...}` | XML-RPC lecture seule ; compte read-only requis ; découverte `fields_get` avant collecte |
| `api` | `{"base_url":..., "endpoints":[{"id","method","path"}], "openapi_url"?}` + secret `{"auth":{"type":"bearer","token":...}}` | allowlist stricte, SSRF guard, redirections bloquées hors allowlist |
| `web` | `{"base_url":..., "journeys":[{"id","name","steps":[...]}]}` | Playwright en extra : `uv sync --extra web && uv run playwright install chromium` ; tests actifs ⇒ approbation obligatoire |
| `file` | upload multipart | CSV/XLSX/JSON ≤ 25 Mo ; parsing pandas local |

Odoo local : loopback autorisé **explicitement** pour ce connecteur uniquement ;
aucune tool `fetch_any_url` n'est exposée au modèle (docs/05, docs/08).

## Structure

```
app/
  api/        REST + SSE (runs, sources, missions, findings, settings)
  agent/      orchestrateur borné + providers LLM (mock, openai-compatible, anthropic)
  audit/      catalogue contrôles (ERP-01..CROSS-01), moteur de règles, assessments
  connectors/ odoo (xmlrpc), api (httpx), web (playwright lazy), files (pandas)
  evidence/   store immuable SHA-256 + secrets store
  findings/   validateur structurel + rapports versionnés
  harness/    registry, policy gate, executor
  models/     schémas Pydantic (docs/14)
  persistence/ SQLite (aiosqlite)
  tools/      12 tools du catalogue docs/05
data/         runtime (gitignored) : db, evidence/, uploads/, secrets, demo/
```

## Garde-fous implémentés (docs/13)

- Policy Gate : scope mission, type de source, permission (`read` / `approved-tests` / `local`),
  journalisation de chaque appel y compris refus.
- Redaction des secrets dans args tool calls, previews et traces HTTP.
- Preuves immuables : checksum SHA-256 vérifié à chaque lecture.
- Validateur findings : evidence_refs inexistants ou hors mission ⇒ rejet explicite ;
  finding sans preuve jamais confirmable.
- Budgets : max_tool_calls (12), max_seconds (180), budget d'entrée, timeouts.
