# AuditLens V1 — Guide d'exécution (implémentation)

> Les docs `01..20` sont les spécifications. Ce guide décrit l'application **implémentée** :
> backend FastAPI (tests verts, flux démo vérifié) + frontend React.

## Prérequis
- Python 3.11 + [uv](https://docs.astral.sh/uv/)
- Node 20+ / npm 11

## 1. Backend

```bash
cd backend
uv sync
uv run pytest                       # 130+ tests (mock LLM, aucun réseau)
uv run python demo_data/generate_demo.py all   # jeux de données démo
uv run uvicorn app.main:app --port 8000 --reload
```

### Redémarrer le backend sans confusion de version (anti-serveur-stale)

Un backend lancé avant des modifications de code sert une version périmée (routes
récentes en 404, bugs corrigés toujours présents). Procédure fiable :

```bash
# 1. libérer le port si un uvicorn orphelin y survit (Windows) — ne jamais tuer
#    un PID qui n'est PAS celui du port 8000
netstat -ano | grep ":8000" | grep LISTENING     # => PID (colonne 5)
taskkill //F //PID <PID>

# 2. démarrer depuis backend/ (venv uv du projet)
cd backend && uv run uvicorn app.main:app --port 8000

# 3. VÉRIFIER L'IDENTITÉ DE BUILD : le commit affiché doit être le HEAD git
curl -s http://localhost:8000/api/health
# {"status":"ok","version":"0.1.0","git_commit":"<12 hex>","started_at":"…","pid":<PID>}
git -C .. rev-parse --short=12 HEAD        # doit correspondre à git_commit

# 4. vérifier les routes récentes
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/reports   # 200
```

Détection d'un serveur stale :
- `git_commit` null ou ≠ HEAD → le process sert un ancien code : tuer le PID du
  port 8000 et relancer (le `pid` de /api/health doit être celui de netstat).
- 404 sur /api/reports → même cause.

Données locales (conversations, evidences, missions) : tout est dans
`backend/data/` (SQLite + fichiers evidence + uploads) — un redémarrage du
processus ne perd RIEN ; ne jamais supprimer `backend/data/` pour « réparer »
un serveur stale.

- API : http://localhost:8000 — docs interactives : http://localhost:8000/docs
- Contrat d'API exact : [docs/CONTRAT_API_IMPL.md](docs/CONTRAT_API_IMPL.md)

## 2. Frontend

```bash
cd frontend
npm install
npm run dev                         # http://localhost:5173 (CORS déjà autorisé)
```

## 3. Démo complète sans clé API (MockLLM)

1. Frontend → **Connections** → *Ajouter une source* → **Fichier** →
   importer `backend/data/demo/faulty/orders.csv`, contrat de données `rs_orders_v1`.
2. **Nouvelle mission** → titre, objectif, sélectionner la source, contrôle `DATA-01`,
   période 2026-09-01 → 2026-12-31.
3. **Proposer le plan IA** (3 tools) → **Approuver** → **Lancer l'audit**.
4. **Live Audit** : timeline SSE réelle (discover → profile → validate), preuves sourcées.
5. **Findings** : constat fondé sur la preuve de validation → *Accept* avec justification.
6. **Report** : rapport versionné (v2 après revue) avec le constat accepté.
7. Jeu propre : `backend/data/demo/clean/orders.csv` → assessment `pass`, aucun constat.

## 4. Providers LLM réels (BYOK)

Settings → **AI Model** : provider (`mock|opencode|openai|gemini|anthropic|deepseek|compatible`),
model, clé (mémoire backend uniquement), bouton *Tester*.
Ou variables d'environnement : voir `backend/README.md`.

### OpenCode Zen — GLM-5.3-Flash Free (gratuit, testé)

Référence locale : `D:\ZKR\Z_API_FREE` (endpoint public documenté, distinct du
Console OpenCode bloqué HTTP 403 — voir docs/10).

- Provider : `opencode` · Model : `glm-5.3-flash-free` · Clé : laisser vide (valeur `public` utilisée automatiquement)
- Base URL : `https://opencode.ai/zen/v1` (par défaut)
- Contexte 200k / sortie 32k — suffisant pour nos prompts JSON (pas de tool-calling natif requis)
- **Limites constatées le 12/11/2026** : ~200 requêtes/jour par IP ; à l'épuisement l'API
  renvoie `429 Free usage limit reached` — AuditLens l'affiche honnêtement (test + run_failed),
  sans jamais simuler un succès. La liste des modèles `-free` évolue : voir `free_models.json`.
- ⚠️ Vie privée (docs/13) : les extraits audités partent vers un service externe — ne pas
  auditer des données confidentielles avec les modèles gratuits.

### GLM-5.3-Flash via Z.AI Coding Plan — ✅ chemin validé de bout en bout (13/11/2026)

C'est la configuration qui fonctionne **sans limite quotidienne** et correspond au
modèle réellement utilisé dans votre client OpenCode (clé stockée dans son auth.json) :

| Champ Settings → AI Model | Valeur |
|---|---|
| Provider | `compatible` |
| Model | `glm-5.3-flash` |
| Base URL | `https://api.z.ai/api/coding/paas/v4` |
| API key | clé Z.AI Coding Plan (celle d'OpenCode) |
| Désactiver le raisonnement | ✔ recommandé (réponse directe ~3× plus rapide) |

Run réel vérifié : plan → `data_profile` + `data_validate` en succès → 5 violations →
assessment `DATA-01: fail` → 3 findings fondés sur preuves (sévérité high/low/info,
dont un qui déclare honnêtement une limite) → revue → rapport v2. Les tools inventées
par le modèle (`fetch_bank_statements`…) sont refusées et journalisées sans casser le run.

Notes :
- La clé reste **en mémoire backend uniquement** (jamais persistée) — la ressaisir après redémarrage,
  ou passer par les variables d'env (voir `backend/README.md`).
- Le client OpenCode fonctionne « sans erreur » car il utilise sa **session interne** ;
  la clé `opencode-go` stockée est expirée (401) — à renouveler dans
  https://opencode.ai/console/account#api-keys si vous voulez le chemin Zen authentifié.

⚠️ Rappel docs/10 : les modèles gratuits du **Console OpenCode** ne sont pas appelables
via API (HTTP 403 hors OpenCode) ; chaque couple provider/modèle doit passer les tests
avant usage.

## 5. Odoo / Web (extras)

- Odoo local : source `odoo` (url, db, username + mot de passe read-only) — le backend
  parle XML-RPC lecture seule ; compte **read-only** obligatoire.
- Parcours Web : installer Playwright :
  ```bash
  cd backend && uv sync --extra web && uv run playwright install chromium
  ```
  puis source `web` avec `journeys` déclarés (tests actifs ⇒ approbation du plan requise).

## État de l'implémentation (honnête)

| Périmètre | État |
|---|---|
| Cœur evidence + harness + policy gate | ✅ implémenté, testé |
| Connecteur Fichiers + contrôles DATA-01 | ✅ implémenté, testé bout-en-bout |
| Connecteur Odoo (XML-RPC read-only) + réconciliation déterministe (odoo_cross_check) | ✅ implémenté, validé sur instance réelle |
| Connecteur API REST + validation contrat OpenAPI (types, required, pagination) | ✅ implémenté, validé sur service de test |
| Connecteur Web (Playwright, parcours) | ✅ implémenté, validé (W1/W2 détectées) |
| Agent MockLLM + GLM-5.3-Flash (Z.AI) | ✅ implémentés et testés |
| Boucle d'investigation agentique (ADR-14) : décisions LLM sur observations réelles | ✅ implémentée, testée (mock + GLM), interrupteur `AUDITLENS_INVESTIGATION_LOOP=off` |
| Providers réels (OpenAI/Anthropic/Gemini/DeepSeek) | ✅ implémentés — **non testés contre API réelle** (clé requise) |
| Évaluation quantitative (Baseline A vs B vs System C) | ✅ pipeline reproductible `eval/` — cas agentiques où la boucle détecte ce que le déterminisme manque |
| Limites connues | variance de planification LLM (budget tools parfois épuisé avant la boucle) ; UoM multiples non converties ; providers OpenAI/Anthropic/Gemini non testés contre API réelle |

Conformément à la politique de livraison : ce qui est annoncé est ce qui est testé.

## 7. Évaluation quantitative (Baseline A vs Baseline B vs System C)

```bash
cd backend
# services de test nécessaires pour api/web : ports 8080/8081 ; Odoo pour odoo_tp / agent_odoo_ambiguous
uv run python -m eval --cases files_dev,files_eval --provider mock                       # CI-sûr, sans réseau
uv run python -m eval --cases agent_multistep,agent_undocumented --provider mock         # boucle vs pipeline (déterministe)
uv run python -m eval --cases agent_multistep,agent_undocumented,agent_odoo_ambiguous --provider glm --trials 3
# rapport + métriques : backend/data/eval/report.md
```

Trois systèmes comparés :
- **baseline_a** — déterministe pur (aucun LLM) ;
- **system_b** — pipeline historique reproduit (`AUDITLENS_INVESTIGATION_LOOP=off`) ;
- **system_c** — boucle d'investigation agentique à ressources (ADR-14/15, défaut applicatif).

Cas agentiques (docs/17 v4 — comptabilité inclusive, critères déclaratifs) :
- `agent_multistep` — A4 (500 en détail, appel dépendant liste→détail requis) ;
- `agent_undocumented` — /health sain non documenté (discipline FP) ;
- `agent_odoo_ambiguous` — orphelin P00001 suspicious réel (qualification prudente) ;
- `agent_odoo_rootcause` — EXPLIQUER le stock négatif HP 250 G8 (investigation, ≥2 preuves) ;
- `agent_web_orders` — W3 (page /orders → 500), parcours j2 déclaré ;
- `agent_cross_source` — Odoo + API : flux « partenaire » planté (S00002 → 999999.0), jointure inter-sources requise ;
- `agent_missing_evidence` — avoirs absents des données : l'insuffisance EXPLICITE est la bonne réponse ;
- `agent_contradiction` — A5 (commande 7 : confirmed en liste, cancelled en détail) ;
- `agent_flaky` — A6 (/reports : 503 ×2 puis 200 ; adaptation/réessai attendus).

Métriques (aucune exécution exclue — erreurs, timeouts, budget épuisé et runs
silencieux comptent) : succès complet, runs silencieux, inconclusifs corrects
(distincts des anomalies manquées), precision/recall, claims non supportés, findings
rejetés, appels redondants, constats multi-preuves, reprises après pause, **critères
déclaratifs** (`no_silence`, `multi_evidence>=N`, `reverification` — même endpoint
observé ≥2 fois avec statuts HTTP différents) évalués sur les données structurées du
run, pas seulement par mots-clés. Deux cas sont TENUS HORS DÉVELOPPEMENT
(`agent_transient_persistent`, `agent_legit_credit`) : jamais utilisés pour ajuster
prompts ou règles — mesure de généralisation.

Contrôle runtime (ADR-15) sur serveur réel :
```bash
curl -X POST http://localhost:8000/api/runs/{run_id}/pause        # pause entre deux tours
curl http://localhost:8000/api/runs/{run_id}/checkpoint           # checkpoint persistant
curl -X POST http://localhost:8000/api/missions/{id}/extend-budget      -H "Content-Type: application/json" -d '{"add_tool_calls":12,"add_seconds":120}'
curl -X POST http://localhost:8000/api/runs/{run_id}/resume       # nouveau run depuis checkpoint
curl -X POST http://localhost:8000/api/runs/{run_id}/stop         # annulation gracieuse
```

Détail méthodologique : `eval/ground_truth.py` (vérité jamais exposée à l'agent),
`eval/runner.py` (approbation simulée notée comme telle), matching par mots-clés
documenté comme approximatif (docs/17).

## 6. Évaluation quantitative (historique Baseline A vs Système B — 13/11 matin)

Les 5 cas de détection (files_dev, files_eval, api_test, web_test, odoo_tp) ont été
exécutés avec GLM-5.3-Flash réel : recall 1.0 / precision 1.0 Système B, Baseline A
recall 1.0 — résultat et limites documentés dans docs/22 §7-8.
