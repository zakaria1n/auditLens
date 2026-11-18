# AGENTS.md — Instructions pour Codex / OpenCode / assistants de code

## Mission
Construire **AuditLens V1**, portfolio étudiant sérieux : agent d'audit **LLM API + Tool Harness**, preuves vérifiables, connecteurs Odoo local/Web/API/Fichiers, UX React professionnelle, review humaine.

## Lisez d'abord
`README.md` → `docs/01_VISION_PERIMETRE.md` → `docs/03_ARCHITECTURE.md` → `docs/04_ALGORITHME_AGENT.md` → `docs/05_HARNESS_TOOLS.md` → `docs/10_LLM_FOURNISSEURS_BYOK.md` → `docs/13_SECURITE.md`.

## Règles impératives
1. **Aucune assertion de conformité sans critère + evidence**. `Insufficient evidence` est un résultat valide.
2. **LLM central** mais pas seul exécutant des calculs ; tools sûres pour observations.
3. **Odoo Local V1 obligatoire**, sans faire du système une plateforme exclusivement Odoo.
4. Web, API, files (CSV/XLSX/JSON) **aussi dans V1**.
5. **Providers** : OpenAI, Gemini, Anthropic Claude, DeepSeek, compatible selon tests ; `BYOK` ; secrets hors frontend/repo/logs.
6. **NE PAS** supposer que OpenCode free models sont utilisables par notre backend via API ; docs officielles indiquent HTTP 403 hors OpenCode.
7. **Read-only** par défaut, URL/permission allowlists, pas d'arbitrary shell, SQL ou HTTP.
8. `Evidence ID`, `source_id`, `scope`, `timestamp`, `tool_run_id`, versions de contrôle/model obligatoires.
9. React/TS & FastAPI/Python ; architecture modular monolith ; un seul framework agent en V1.
10. Les animations de la UI reflètent **les événements backend**, et jamais des contrôles fictifs.
11. Pas de composants, libs ou microservices supplémentaires sans preuve de bénéfice et justification ADR.
12. **Tests d'acceptation** sur cas positifs, erreurs, autorisations, données inédites et comparaison baseline.

## Ordre de construction
Provider compatibility spike → core evidence and mission → 1 tool & 1 finding → Odoo → API → Web → Files → cross-source evaluation → UX avancée / 3D si capacité.

## Politique de livraison
Pour chaque changement : expliquer files modifiés, dépendances, hypothèses, tests exécutés et résultats réels. Si un test échoue, ne jamais présenter la feature comme finie. Les fichiers ici sont des spécifications, pas du code déjà opérationnel.
