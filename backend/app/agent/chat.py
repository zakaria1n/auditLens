"""ChatService (ADR-16) : conversation chat-first au-dessus du moteur d'audit.

Le chat n'exécute JAMAIS de tool système directement : ses tools sont d'orchestration
(list_sources, create_audit, get_run_status, get_findings, get_evidence,
search_conversation). Toute action sur les systèmes cibles passe par l'orchestrator +
Tool Harness + Policy Gate (create_audit → mission SANS tests actifs approuvés → run).

Couches (docs/23) :
- 1 conversation persistante : chat_messages (arbre parent_id, head_message_id)
- 2 contexte actif : system + résumé de compaction + messages post-résumé, borné
- 3 état d'investigation & preuves : inchangé (runs, evidence SHA-256, findings, checkpoints)
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from ..api.deps import AppDeps
from ..audit.controls import control_to_dict, list_controls
from ..audit.discovery import build_source_intelligence
from ..privacy import sanitize_context
from ..agent.providers import build_provider, resolve_llm_config
from ..agent.providers.base import LLMResponse
from ..core.errors import ProviderError
from ..core.ids import new_id
from ..core.redact import redact
from ..models import AuditMission, ChatMessage, ChatRole, ConversationThread, MissionStatus, utcnow
from ..services.run_launcher import launch_run

CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "inspect_source",
        "description": (
            "Découvrir UNE source autorisée en profondeur : état de connexion, capacités "
            "réelles, domaines métier exposés, opérations supportées/non supportées, "
            "permissions manquantes. À utiliser avant de proposer un audit ou quand "
            "l'auditeur demande ce qu'une source permet."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "Identifiant de la source (issu de list_sources)."}
            },
            "required": ["source_id"],
        },
    },
    {
        "name": "list_sources",
        "description": "Lister les sources connectées accessibles (id, nom, type, statut). Aucun secret n'est retourné.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_audit",
        "description": (
            "Créer une mission d'audit et lancer immédiatement son investigation via le moteur "
            "AuditLens (tools d'audit, Policy Gate). Les tests actifs (API/Web) ne sont PAS approuvés : "
            "l'auditeur devra les approuver explicitement sur la page mission si nécessaire."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source_ids": {"type": "array", "items": {"type": "string"},
                                "description": "Identifiants de sources à auditer (issus de list_sources)."},
                "objective": {"type": "string", "description": "Objectif d'audit formulé par l'auditeur."},
                "title": {"type": "string", "description": "Titre optionnel de la mission."},
                "control_ids": {"type": "array", "items": {"type": "string"},
                                 "description": "Contrôles optionnels ; défaut = catalogue complet."},
            },
            "required": ["source_ids", "objective"],
        },
    },
    {
        "name": "get_run_status",
        "description": "Statut d'un run d'investigation lié à cette conversation (budget, arrêt).",
        "parameters": {
            "type": "object",
            "properties": {"run_id": {"type": "string", "description": "Optionnel : dernier run lié par défaut."}},
            "required": [],
        },
    },
    {
        "name": "get_findings",
        "description": "Constats (findings) de la mission liée à cette conversation, avec leur statut de revue.",
        "parameters": {
            "type": "object",
            "properties": {"mission_id": {"type": "string", "description": "Optionnel : mission liée par défaut."}},
            "required": [],
        },
    },
    {
        "name": "get_evidence",
        "description": "Métadonnées et résumé d'une preuve de la mission liée (périmètre vérifié ; jamais hors thread).",
        "parameters": {
            "type": "object",
            "properties": {"evidence_id": {"type": "string", "description": "Identifiant de preuve (ex. ev_...)."}},
            "required": ["evidence_id"],
        },
    },
    {
        "name": "search_investigations",
        "description": (
            "MÉMOIRE D'AUDIT : rechercher dans les investigations ANTÉRIEURES (findings "
            "de toutes les missions) par mot-clé. Retourne des références horodatées avec "
            "statut de revue et liens preuve/conversation. Résultats = mémoire non vérifiée : "
            "toute conclusion factuelle exige get_evidence sur la preuve d'origine."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Mot-clé (titre/énoncé/contrôle du constat)."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_conversation",
        "description": (
            "Rechercher dans l'historique COMPLET de cette conversation (y compris la partie "
            "compactée hors contexte actif). Retourne des extraits avec leurs identifiants."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texte à rechercher (correspondance littérale)."},
                "limit": {"type": "integer", "description": "Nombre max de résultats (défaut 8, max 20)."},
            },
            "required": ["query"],
        },
    },
]

CHAT_SYSTEM = """Tu es l'assistant d'audit d'AuditLens. Tu aides un auditeur IT professionnel à piloter des investigations réelles sur ses systèmes.

RÈGLES NON NÉGOCIABLES :
- Tu n'accèdes JAMAIS directement aux systèmes : toute action passe par les tools fournies ou par le moteur d'investigation (missions/runs), qui applique le Policy Gate (lecture seule par défaut, tests actifs sur approbation humaine).
- Aucune assertion de conformité sans critère + preuve (evidence). « Preuves insuffisantes » est une réponse valide et préférable à une spéculation.
- Les preuves sont immuables et vérifiables (SHA-256) ; cite leurs identifiants (ev_...).
- Ne demande jamais de secret, mot de passe ou clé API dans la conversation ; les connexions se configurent dans la page Sources.
- Les tests actifs (API/Web) requièrent l'approbation humaine : create_audit crée une mission SANS tests actifs approuvés — indique à l'auditeur comment approuver sur la page mission si le run en a besoin.
- Si l'information manque, dis-le et propose l'étape suivante concrète.
- Réponds dans la langue de l'auditeur (français par défaut), de façon concise et professionnelle.

PRÉSENTATIONS VISUELLES (optionnel — uniquement quand une visualisation communique mieux que du texte) :
Tu peux inclure AU PLUS UNE présentation par réponse, dans un bloc de code fenced `viz` contenant UNIQUEMENT un JSON {"version": 1, ...}. Types autorisés : data_table (columns, rows <=200, row_ids alignés), bar_chart (bars [{label, value}] <=24, unit), line_chart (series [{name, points [{x, y}]}] <=6x200, x_label, y_label), comparison (items [{label, left, right}], left_label, right_label, unit), relationship_graph (nodes [{id, label, kind}] <=60, edges [{source, target, label, status: ok|missing|conflict}] <=120), process_diagram (steps [{id, label, detail}] 2..12, direction), timeline (events [{label, at, detail, kind: tool|evidence|hypothesis|decision|run|other, evidence_ref}] <=60), kpi_summary (metrics [{label, value, unit, hint, evidence_ref}] <=8). Chaque spéc porte title (obligatoire) et peut porter note, evidence_refs (identifiants ev_ réels de CETTE conversation). Toute valeur affichée doit provenir de données réellement observées via tools/preuves — jamais d'estimation inventée. L'application valide et refuse toute spécification non conforme ; le texte reste la référence. Ne génère PAS de bloc viz sans données concrètes à montrer.

ÉTAT DES MISSIONS/RUNS DE CETTE CONVERSATION :
{mission_context}"""


class ChatService:
    """Un tour de conversation = un appel `run_turn(...)` (générateur d'événements SSE).

    Budget chat borné : MAX_TOOL_ROUNDS étapes LLM par tour ; la compaction borne la
    taille du contexte (couche 2) sans jamais toucher aux messages (couche 1) ni aux
    preuves (couche 3).
    """

    MAX_TOOL_ROUNDS = 8
    CONTEXT_CHAR_BUDGET = 24_000
    COMPACTION_KEEP = 8  # messages récents conservés hors résumé

    # ---------- tour de conversation ----------

    async def run_turn(
        self, d: AppDeps, thread: ConversationThread, content: str | None,
        mode: str = "new", target_message_id: str | None = None,
    ) -> AsyncIterator[dict]:
        repo = d.repo
        controls = d.chat_controls
        self._bridge: dict | None = None  # thread mis à jour par create_audit (pont live)

        all_msgs = await repo.list_thread_messages(thread.id)
        by_id = {m.id: m for m in all_msgs}
        target = by_id.get(target_message_id) if target_message_id else None
        if mode in ("edit", "regenerate"):
            if target is None:
                raise ValueError("message cible introuvable dans cette conversation")
            if mode == "edit" and target.role != ChatRole.user:
                raise ValueError("édition possible uniquement sur un message auditeur")
            if mode == "regenerate" and target.role != ChatRole.assistant:
                raise ValueError("régénération possible uniquement sur un message assistant")

        # --- 1. branche sûre : nouveaux messages frères, historique jamais réécrit (docs/23 §3)
        user_msg: ChatMessage | None = None
        if mode == "regenerate":
            parent_for_assistant = target.parent_id
        else:
            if not (content or "").strip():
                raise ValueError("contenu vide")
            # édition : la nouvelle demande branche au MÊME parent que la cible (frère) ;
            # l'historique exécuté de la branche originale n'est jamais réécrit (docs/23 §3)
            base_parent = target.parent_id if mode == "edit" else thread.head_message_id
            user_msg = ChatMessage(
                id=new_id("msg"), thread_id=thread.id, parent_id=base_parent,
                role=ChatRole.user, parts=[{"type": "text", "text": content.strip()}],
            )
            await repo.create_chat_message(user_msg)
            parent_for_assistant = user_msg.id
            thread.head_message_id = user_msg.id
            thread.updated_at = utcnow()
            await repo.update_thread(thread)
            if mode == "new" and len(all_msgs) == 0 and thread.title == "Nouvelle conversation":
                title = content.strip().splitlines()[0][:80]
                await repo.db.execute(
                    "UPDATE conversation_threads SET title=? WHERE id=? AND workspace_id=? AND title=?",
                    (title, thread.id, thread.workspace_id, "Nouvelle conversation"),
                )
                thread = await repo.get_thread(thread.id) or thread
                yield {"type": "thread", "thread": thread.model_dump(mode="json")}
            yield {"type": "message", "message": user_msg.model_dump(mode="json")}
            yield {"type": "head", "head_message_id": thread.head_message_id}

        cfg = resolve_llm_config(d.llm_runtime)
        provider = build_provider(cfg, scenario="chat")

        assistant = ChatMessage(
            id=new_id("msg"), thread_id=thread.id, parent_id=parent_for_assistant,
            role=ChatRole.assistant, parts=[], status="running",
            provider_id=provider.provider_id, model_id=provider.model_id,
        )
        # persisté d'emblée (status running) : un refresh pendant le tour montre l'état réel,
        # et toute sortie (annulation, déconnexion, erreur) ne fait qu'UPDATE ce message.
        await repo.create_chat_message(assistant)
        yield {"type": "assistant_start", "message_id": assistant.id}

        try:
            # --- 2. couche 2 : chaîne active (root → parent) + compaction éventuelle
            by_id = {m.id: m for m in await repo.list_thread_messages(thread.id)}
            chain = self._chain(by_id, parent_for_assistant)
            active, total = self._assemble(thread, chain)
            if total > self.CONTEXT_CHAR_BUDGET:
                comp = await self._maybe_compact(provider, thread, chain)
                yield {"type": "compaction", **comp}
                active, total = self._assemble(thread, chain)
            active_ids = {m.id for m in active}
            system = CHAT_SYSTEM.replace(
                "{mission_context}", await self._mission_context(d, thread),
            )
            if thread.context_summary:
                system += f"\n\n[RÉSUMÉ DE LA PARTIE ANTÉRIEURE (compaction)]\n{thread.context_summary}"

            canon = self._to_canonical(chain)
            final_text: str | None = None
            error: str | None = None
            cancelled = False
            rounds = 0

            # --- 3. boucle LLM ↔ tools de chat (bornée)
            while rounds < self.MAX_TOOL_ROUNDS:
                if controls.get(thread.id) == "cancel":
                    cancelled = True
                    break
                # Phase 7/10 : contexte assaini (PII masquée) — l'original n'est jamais modifié
                sanitized_system, sys_counts = sanitize_context(system)
                sanitized_canon, canon_counts = sanitize_context(canon)
                all_counts = dict(sys_counts)
                for k, v in canon_counts.items():
                    all_counts[k] = all_counts.get(k, 0) + v
                if all_counts:
                    yield {"type": "privacy_preview", "categories": [
                        {"category": k, "count": v} for k, v in sorted(all_counts.items(), key=lambda kv: -kv[1])
                    ], "total_redactions": sum(all_counts.values())}
                resp: LLMResponse | None = None
                round_text: dict | None = None
                async for item in provider.stream_chat(sanitized_system, sanitized_canon, tools=CHAT_TOOLS):
                    if controls.get(thread.id) == "cancel":
                        cancelled = True
                        break
                    if isinstance(item, str):
                        if not item:
                            continue
                        if round_text is None:
                            round_text = {"type": "text", "text": ""}
                            assistant.parts.append(round_text)
                        round_text["text"] += item
                        yield {"type": "text_delta", "text": item}
                    else:
                        resp = item
                if cancelled:
                    break
                if resp is None:
                    raise ProviderError("Flux fournisseur interrompu avant la réponse finale")
                if resp.content and round_text is None:
                    round_text = {"type": "text", "text": resp.content}
                    assistant.parts.append(round_text)
                    yield {"type": "text_delta", "text": resp.content}
                rounds += 1
                if resp.tool_calls:
                    canon.append({
                        "role": "assistant", "content": resp.content,
                        "tool_calls": [
                            {"id": t.id, "name": t.name, "arguments": t.arguments} for t in resp.tool_calls
                        ],
                    })
                    for t in resp.tool_calls:
                        if controls.get(thread.id) == "cancel":
                            cancelled = True
                            break
                        yield {"type": "tool_call", "id": t.id, "tool": t.name,
                               "args": redact(t.arguments or {})}
                        t0 = time.monotonic()
                        outcome = await self._execute_chat_tool(d, thread, t, active_ids)
                        duration_ms = int((time.monotonic() - t0) * 1000)
                        part = {
                            "type": "tool_call", "id": t.id, "tool": t.name,
                            "args": redact(t.arguments or {}),
                            "status": "error" if outcome.get("status") == "error" else "complete",
                            "result": outcome, "error": outcome.get("error"),
                            "duration_ms": duration_ms,
                        }
                        assistant.parts.append(part)
                        yield {"type": "tool_result", "id": t.id, "tool": t.name,
                               "status": part["status"], "result": outcome}
                        if self._bridge:
                            # pont live : le panel Investigation voit le run pendant le tour
                            yield {"type": "thread", "thread": self._bridge["thread"]}
                            self._bridge = None
                        canon.append({
                            "role": "tool", "tool_call_id": t.id, "name": t.name,
                            "content": json.dumps(outcome, ensure_ascii=False)[:4000],
                        })
                    if cancelled:
                        break
                elif resp.content is not None:
                    final_text = resp.content
                    break
                else:
                    final_text = ""
                    break
            else:
                final_text = ("Nombre maximal d'étapes atteint pour ce tour ; "
                              "redemandez-moi de continuer si nécessaire.")

            # --- 4. persistance du message assistant + déplacement du head
            if final_text and (not assistant.parts or assistant.parts[-1].get("text") != final_text):
                assistant.parts.append({"type": "text", "text": final_text})
                yield {"type": "text_delta", "text": final_text}
            if error:
                assistant.parts.append({"type": "text", "text": f"Erreur provider : {error}"})
            assistant.status = "incomplete" if cancelled else ("error" if error else "complete")
            thread.head_message_id = assistant.id
            thread.updated_at = utcnow()
            await repo.update_chat_message(assistant)
            await repo.update_thread(thread)
            yield {"type": "message", "message": assistant.model_dump(mode="json")}
            yield {"type": "head", "head_message_id": thread.head_message_id}
            yield {"type": "done", "status": assistant.status, "rounds": rounds}
        except (GeneratorExit, asyncio.CancelledError):
            # Déconnexion client : persistance best-effort du partiel (aucune perte silencieuse)
            assistant.status = "incomplete"
            if assistant.parts:
                thread.head_message_id = assistant.id
                await d.repo.update_chat_message(assistant)
                await d.repo.update_thread(thread)
            await provider.close()
            controls.pop(thread.id, None)
            raise
        except ProviderError as exc:
            assistant.status = "error"
            assistant.parts.append({"type": "text", "text": f"Erreur provider : {exc}"})
            thread.head_message_id = assistant.id
            thread.updated_at = utcnow()
            await d.repo.update_chat_message(assistant)
            await d.repo.update_thread(thread)
            yield {"type": "message", "message": assistant.model_dump(mode="json")}
            yield {"type": "error", "message": str(exc)}
            yield {"type": "done", "status": "error"}
        finally:
            await provider.close()
            controls.pop(thread.id, None)

    # ---------- helpers de contexte (couche 2) ----------

    def _chain(self, by_id: dict[str, ChatMessage], head_id: str | None) -> list[ChatMessage]:
        """Chaîne root → head (branche active uniquement)."""
        chain: list[ChatMessage] = []
        cur = by_id.get(head_id) if head_id else None
        while cur is not None:
            chain.append(cur)
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
        chain.reverse()
        return chain

    def _assemble(self, thread: ConversationThread, chain: list[ChatMessage]) -> tuple[list[ChatMessage], int]:
        active = chain
        if thread.summary_upto_message_id:
            idx = next((i for i, m in enumerate(chain) if m.id == thread.summary_upto_message_id), -1)
            active = chain[idx + 1:]
        total = len(CHAT_SYSTEM) + len(thread.context_summary or "")
        total += sum(self._msg_len(m) for m in active)
        return active, total

    @staticmethod
    def _msg_len(m: ChatMessage) -> int:
        return sum(len(json.dumps(p, ensure_ascii=False)) for p in m.parts) + 16

    def _to_canonical(self, msgs: list[ChatMessage]) -> list[dict]:
        """Format canonique providers (base.py) reconstruit depuis la couche 1."""
        out: list[dict] = []
        for m in msgs:
            text = "\n".join(p.get("text", "") for p in m.parts if p.get("type") == "text")
            tool_parts = [p for p in m.parts if p.get("type") == "tool_call"]
            if m.role == ChatRole.user:
                if text:
                    out.append({"role": "user", "content": text})
            elif m.role == ChatRole.assistant:
                if tool_parts:
                    out.append({
                        "role": "assistant", "content": text or None,
                        "tool_calls": [
                            {"id": p["id"], "name": p["tool"], "arguments": p.get("args") or {}}
                            for p in tool_parts
                        ],
                    })
                    for p in tool_parts:
                        if p.get("status") in ("complete", "error"):
                            out.append({
                                "role": "tool", "tool_call_id": p["id"], "name": p["tool"],
                                "content": json.dumps(
                                    {"status": p.get("status"), "result": p.get("result"),
                                     "error": p.get("error")},
                                    ensure_ascii=False,
                                ),
                            })
                elif text:
                    out.append({"role": "assistant", "content": text})
        return out

    async def _maybe_compact(
        self, provider, thread: ConversationThread, chain: list[ChatMessage],
    ) -> dict:
        """Compaction par résumé (couche 2 uniquement) : les messages originaux et les
        preuves ne sont JAMAIS modifiés ; l'agent retrouve le contenu via search_conversation."""
        keep = min(self.COMPACTION_KEEP, max(2, len(chain) // 4))
        region = chain[:-keep] if len(chain) > keep else []
        if not region:
            return {"status": "skipped", "reason": "rien à compacter au-delà de la fenêtre récente"}
        transcript: list[str] = []
        for m in region:
            role = "Auditeur" if m.role == ChatRole.user else "Assistant"
            text = "\n".join(p.get("text", "") for p in m.parts if p.get("type") == "text")
            tools = [p.get("tool", "?") for p in m.parts if p.get("type") == "tool_call"]
            if tools:
                text = (text + f" [outils exécutés: {', '.join(tools)}]").strip()
            if text:
                transcript.append(f"{role}: {text[:800]}")
        prompt = (
            "Tu prépares la compaction du contexte d'une conversation d'audit. Produis un résumé "
            "FACTUEL borné (max 400 mots) conservant : l'objectif courant, les sources/missions/runs "
            "mentionnés (identifiants), les hypothèses, les résultats d'outils clés, les questions "
            "ouvertes. N'invente rien ; ne perds pas les identifiants.\n\nTRANSCRIPTION:\n"
            + "\n".join(transcript)
        )
        try:
            resp = await provider.chat(
                "Tu résumes une conversation d'audit de façon factuelle et concise.",
                [{"role": "user", "content": prompt}],
            )
        except ProviderError as exc:
            return {"status": "skipped", "reason": f"provider indisponible : {exc}"}
        if not resp.content:
            return {"status": "skipped", "reason": "résumé vide (provider)"}
        thread.context_summary = resp.content.strip()
        thread.summary_upto_message_id = region[-1].id
        thread.compacted_message_count = len(region)
        return {"status": "compacted", "summarized_messages": len(region)}

    async def _mission_context(self, d: AppDeps, thread: ConversationThread) -> str:
        lines: list[str] = []
        for mid in thread.mission_ids[-5:]:
            mission = await d.repo.get_mission(mid)
            if mission is None:
                continue
            runs_info: list[str] = []
            for rid in thread.run_ids:
                run = await d.repo.get_run(rid)
                if run and run.mission_id == mid:
                    suffix = f", arrêt : {run.stop_reason}" if run.stop_reason else ""
                    runs_info.append(f"{run.id} ({run.status.value}{suffix})")
            lines.append(
                f"- mission {mid} « {mission.title} » [{mission.status.value}] — "
                f"runs : {'; '.join(runs_info) or 'aucun'}"
            )
        return "\n".join(lines) or "aucune mission liée à cette conversation."

    # ---------- tools de chat (orchestration uniquement) ----------

    async def _execute_chat_tool(
        self, d: AppDeps, thread: ConversationThread, tc, active_ids: set[str],
    ) -> dict:
        name, args = tc.name, tc.arguments or {}
        repo = d.repo
        if name == "list_sources":
            sources = await repo.list_sources()
            return {"sources": [
                {"id": s.id, "name": s.name, "type": s.type.value, "status": s.status.value}
                for s in sources
            ]}

        if name == "inspect_source":
            source_id = str(args.get("source_id") or "")
            source = await repo.get_source(source_id)
            if source is None:
                return {"status": "error", "error": f"source inconnue : {source_id}"}
            # lecture seule via le même connecteur que le harness ; Policy Gate inchangé
            from ..audit.discovery import build_source_intelligence

            try:
                connector = d.connectors.build(source)
                try:
                    caps = await connector.discover()
                finally:
                    await connector.close()
            except Exception as exc:  # noqa: BLE001 — échec de découverte = état "error"
                caps = {"discover_error": f"{type(exc).__name__}: {exc}"}
            mission = None
            if thread.mission_ids:
                mission = await repo.get_mission(thread.mission_ids[-1])
            return build_source_intelligence(source, redact(caps), d.executor.registry, mission)

        if name == "create_audit":
            source_ids = [str(x) for x in args.get("source_ids", [])]
            objective = str(args.get("objective") or "").strip()
            if not source_ids or not objective:
                return {"status": "error", "error": "source_ids et objective sont requis"}
            known = {s.id: s for s in await repo.list_sources()}
            unknown = [x for x in source_ids if x not in known]
            if unknown:
                return {"status": "error", "error": f"sources inconnues : {unknown}"}
            control_ids = [str(c) for c in args.get("control_ids", [])] or [
                cdict["id"] for cdict in (control_to_dict(c) for c in list_controls()) if cdict.get("id")
            ]
            # approved_plan vide : les tests actifs restent refusés par le Policy Gate
            # jusqu'à approbation humaine explicite (docs/23 §4).
            mission = AuditMission(
                id=new_id("mission"),
                title=str(args.get("title") or f"Audit via conversation — {utcnow()[:10]}"),
                objective=objective[:2000], source_ids=source_ids, control_ids=control_ids,
                status=MissionStatus.approved,
                approved_plan={"approved_actions": [], "source": "chat", "approved_at": utcnow()},
            )
            await repo.create_mission(mission)
            # Même mécanisme que la route missions : rattacher la preuve d'import du
            # fichier au périmètre de la mission (invariant docs/14) — sinon le plan
            # ne verrait aucune preuve initiale à profiler/valider.
            from ..api.routes.missions import _link_import_evidence

            await _link_import_evidence(d, mission)
            cfg = resolve_llm_config(d.llm_runtime)
            provider = build_provider(cfg, scenario="data_audit")
            # le provider est clos par orchestrator.execute_run (propriétaire du worker)
            run = await launch_run(d, mission, provider)
            if mission.id not in thread.mission_ids:
                thread.mission_ids.append(mission.id)
            if run.id not in thread.run_ids:
                thread.run_ids.append(run.id)
            # titre utile : l'objectif d'audit, sauf si l'auditeur a renommé le fil
            if thread.title == "Nouvelle conversation":
                thread.title = objective.strip().splitlines()[0][:80]
            await repo.update_thread(thread)
            self._bridge = {"mission_id": mission.id, "run_id": run.id, "thread": thread.model_dump(mode="json")}
            return {
                "mission_id": mission.id, "run_id": run.id, "status": run.status.value,
                "approved_active_tests": False,
                "note": ("run lancé via le moteur existant ; tests actifs NON approuvés — "
                         "approbation humaine sur la page mission si le run en a besoin"),
            }

        if name == "get_run_status":
            run_id = str(args.get("run_id") or (thread.run_ids[-1] if thread.run_ids else ""))
            if not run_id or run_id not in thread.run_ids:
                return {"status": "error", "error": "aucun run lié à cette conversation"}
            run = await repo.get_run(run_id)
            if run is None:
                return {"status": "error", "error": f"run introuvable : {run_id}"}
            return {
                "run_id": run.id, "status": run.status.value, "stop_reason": run.stop_reason,
                "tool_calls_used": run.tool_calls_used, "started_at": run.started_at,
                "finished_at": run.finished_at, "provider": run.provider_id, "model": run.model_id,
            }

        if name == "get_findings":
            mission_id = str(args.get("mission_id") or (thread.mission_ids[-1] if thread.mission_ids else ""))
            if not mission_id or mission_id not in thread.mission_ids:
                return {"status": "error", "error": "mission hors périmètre de cette conversation"}
            findings = await repo.list_findings(mission_id=mission_id)
            return {"mission_id": mission_id, "findings": [
                {
                    "id": f.id, "title": f.title, "severity": f.severity_proposed.value,
                    "status": f.status.value, "evidence_refs": f.evidence_refs,
                    "statement": f.statement[:400],
                }
                for f in findings
            ]}

        if name == "get_evidence":
            evidence_id = str(args.get("evidence_id") or "")
            for mission_id in thread.mission_ids:
                meta = await repo.get_evidence_meta(evidence_id, mission_id)
                if meta is not None:
                    return {
                        "id": meta.id, "title": meta.title, "type": meta.type,
                        "record_count": meta.record_count, "checksum": meta.checksum[:16],
                        "summary": meta.summary, "observed_at": meta.observed_at,
                    }
            return {"status": "error",
                    "error": "preuve inconnue ou hors périmètre de cette conversation"}

        if name == "search_investigations":
            from ..audit.memory import build_memory_results

            query = str(args.get("query") or "").strip()
            if not query:
                return {"status": "error", "error": "query requise"}
            findings = await repo.list_findings()  # toutes missions (mono-utilisateur local)
            missions_by_id = {m.id: m for m in await repo.list_missions()}
            threads_by_run: dict[str, str] = {}
            for t in await repo.list_threads():
                for rid in t.run_ids:
                    threads_by_run[rid] = t.id
            results = build_memory_results(query, findings, missions_by_id, threads_by_run)
            return {
                "query": query,
                "results": results,
                "warning": ("mémoire non vérifiée : toute conclusion factuelle exige get_evidence "
                            "sur la preuve d'origine de l'investigation antérieure"),
            }

        if name == "search_conversation":
            query = str(args.get("query") or "").strip()
            if not query:
                return {"status": "error", "error": "query requise"}
            limit = max(1, min(int(args.get("limit") or 8), 20))
            hits = await repo.search_thread_messages(thread.id, query, limit)
            return {"query": query, "results": [
                {
                    "id": m.id, "role": m.role.value, "created_at": m.created_at,
                    "in_active_context": m.id in active_ids,
                    "snippet": self._snippet(m, query),
                }
                for m in hits
            ]}

        return {"status": "error", "error": f"tool chat inconnue : {name!r}"}

    @staticmethod
    def _snippet(m: ChatMessage, query: str, width: int = 240) -> str:
        text = "\n".join(p.get("text", "") for p in m.parts if p.get("type") == "text")
        idx = text.lower().find(query.lower())
        start = max(0, idx - width // 2) if idx >= 0 else 0
        return text[start:start + width].replace("\n", " ")
