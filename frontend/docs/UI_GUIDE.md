# AuditLens — Guide UI frontend (Phase « Premium UI & Generative UI », 2026-11)

Ce document décrit l'implémentation RÉELLE (pas une spécification) : structure
des modules, design system, registre de visualisations, contrat agent/UI,
procédure pour ajouter une visualisation, limites connues et tests manuels.

## 1. Structure des modules

```
frontend/src/
  index.css                  # design tokens (@theme Tailwind 4) + classes al-*
  App.tsx / main.tsx         # routing + providers (ToastProvider)
  components/
    AppShell.tsx             # shell unique ADR-17 (sidebar / chat / panel)
    brand/AuditLensLogo.tsx  # marque (lentille + faisceau), aria-hidden
    chat/                    # ChatCenter, ChatMessages, ThreadSidebar/Row,
                             # InvestigationPanel, ToolCallCard
    ui/                      # primitives : Button, Card, Badge, Dialog, Field,
                             # Tabs, Toast (toasts), CopyButton
    MarkdownView.tsx         # markdown léger sans dépendance + canal ```viz
  features/
    chat/                    # ChatComposer (envoi, fichiers, dictée), useChatModel,
                             # components/WelcomeScreen (accueil conversation vide)
    intelligent-ui/
      schemas/viz.ts         # schéma TY PÉ VERSIONNÉ (v1) + validateur déterministe
      renderers/index.tsx    # 8 composants de rendu approuvés + VizFrame
      interactions/          # selection.ts (handoff structuré), SelectionChip
      VizBlock.tsx           # entrée unique : validate -> registre | repli
    data-exploration/ relationships/ hypotheses/ audit-coverage/
    differential-audit/ investigation-memory/ remediation/ source-discovery/
  lib/                       # api clients, SSE, hooks workspace (état chat)
  test/                      # setup vitest (+ *.test.tsx co-localisés)
```

## 2. Design system

- Tokens dans `index.css` (`@theme`) : échelle `brand-*` (violet-indigo, ancre
  `#5046c9`), encres `ink-*`, surfaces `surface-0/1/2`, ombres `card/raised/pop`,
  easing `--ease-out-soft`, focus ring global (`:focus-visible`).
- Aucune valeur hex dans les composants ; classes consommées via Tailwind
  (`bg-brand-600`, `text-ink-500`, `shadow-card`…) ou classes al-* CSS.
- Animations : déclenchées par des événements réels (`al-event-in`, `al-fade-up`,
  `al-pulse-dot` pour statut running) ; `prefers-reduced-motion` neutralise tout.

## 3. Registre de visualisations (Generative UI)

Principe : **le LLM propose la présentation, l'application valide et rend.**
Jamais de code généré exécuté (pas d'HTML/JS/CSS/SVG arbitraire).

Types v1 (allowlist) : `data_table`, `bar_chart`, `line_chart`, `comparison`,
`relationship_graph`, `process_diagram`, `timeline`, `kpi_summary`.

Canal : bloc fenced ` ```viz ` dans une réponse assistant, contenant UNIQUEMENT
un JSON `{"version": 1, "type": ..., "title": ..., ...}`. Le prompt système
backend (chat.py) documente le contrat ; au plus une présentation par réponse ;
le texte reste la référence.

Validation (`schemas/viz.ts`) : allowlist stricte des clés (toute clé inconnue
→ rejet), rejet des clés `on*` et contenus exécutables (`javascript:`,
`<script`), bornes par collection (200 lignes, 24 colonnes, 24 barres, 6 séries
× 200 points, 60 nœuds, 120 arêtes, 12 étapes, 60 événements, 8 métriques),
`evidence_refs` au format `ev_…`, arêtes vérifiées contre les nœuds.
Invalide → repli lisible avec la raison (jamais silencieux) + error boundary.

Chaque rendu porte : titre, note optionnelle, chips de preuve cliquables
(navigation `/evidence?run_id&focus`), alternative textuelle complète
(`sr-only` via `specToText`) pour les lecteurs d'écran.

## 4. Contrat agent/UI (Phase 4)

Sélection → handoff structuré : cliquer une ligne/barre/item/nœud/arête crée
une `VizSelection` affichée dans le chip compositeur (« Sélection jointe au
prochain message »). L'envoi insère AVANT l'instruction humaine un bloc
`[Contexte de sélection …]` (présentation, enregistrement + id, lien, preuve).
Aucune exécution d'outil côté UI : tout passe par le chat, donc par le Policy
Gate backend. Filtre/tri local du tableau : 100 % client, aucune requête LLM.

## 5. Ajouter une nouvelle visualisation

1. `schemas/viz.ts` : nouveau type + validateur (bornes + clés allowlistées).
2. `renderers/index.tsx` : composant approuvé enveloppé dans `VizFrame`
   (titre, note, preuves, `sr-only`).
3. `VizBlock.tsx` : entrée dans `renderViz`.
4. Prompt système backend : ajouter le type à la liste du contrat.
5. Tests : cas valide + cas de rejet (clé inconnue, bornes, contenu non sûr).

## 6. Limites connues

- MarkdownView : rendu volontairement minimal (pas de tableaux GFM, pas d'images) ;
  le rapport complet reste en .md téléchargeable.
- Le canal `viz` dépend de la discipline du modèle (1 bloc max par réponse) ;
  les spécifications doubles/malformées tombent en repli.
- Dictée vocale : Web Speech API (Chrome/Edge) ; fr-FR/en-US/ar-MA déclarés mais
  la reconnaissance arabe (darija) n'est PAS garantie — traitement par le service
  du navigateur, pas on-device.
- Pas de virtualisation des conversations très longues (bornées par la
  compaction backend) ; tables bornées à 200 lignes.

## 7. Tests

`npm test` (vitest + jsdom) : 32 tests — tokens, WelcomeScreen (interaction
brouillon), Button, Toast (succès/alerte/auto-dismiss), CopyButton, validation
viz (acceptation + sécurité + bornes), VizBlock (registre/replis/interactions),
handoff de sélection. `npm run lint` (oxlint, 0 erreur) + `npm run build`
(tsc -b + vite) doivent rester verts. UX navigateur : vérification MANUELLE
par l'utilisateur uniquement.
