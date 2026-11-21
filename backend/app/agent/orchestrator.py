"""Audit Orchestrator (docs/04) : impose le processus et le budget.

Boucle bornée : plan → gate → tool → evidence → BOUCLE D'INVESTIGATION agentique
(décisions LLM sur observations réelles, ADR-14/15) → réconciliation déterministe
automatique → assessments déterministes → findings proposés → validation
structurelle → review humaine. Le LLM ne décide ni permissions ni calculs ;
chaque étape est journalisée et diffusée en événements réels.

ADR-15 : la boucle n'est plus bornée par un compteur de décisions mais par les
RESSOURCES (tools, temps, entrée LLM, garde-fous d'urgence), avec détection de
stagnation, avertissements budget, CHECKPOINTS persistants (pause/reprise après
restart) et accounting d'usage provider quand disponible.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from ..api.events import EventBus
from ..audit.assessment import evaluate_assessment
from ..audit.controls import control_to_dict, get_control
from ..connectors.base import ConnectorFactory
from ..core.errors import ProviderError
from ..privacy import classify_exposure, sanitize_context
from ..core.ids import new_id
from ..core.redact import redact
from ..evidence.store import EvidenceStore
from ..findings.validator import validate_findings
from ..harness.contracts import ToolContext
from ..harness.executor import ToolExecutor
from ..models import (
    Assessment,
    AuditMission,
    AuditPlan,
    AuditRun,
    Evidence,
    FindingCandidate,
    FindingStatus,
    InvestigationCheckpoint,
    MissionStatus,
    ReportSnapshot,
    RunStatus,
    SourceConnection,
)
from .investigation import (
    InvestigationState,
    Observation,
    investigation_request,
    parse_decision,
)
from .prompts import (
    SYSTEM_PROMPT,
    findings_request,
    plan_request,
    summarize_evidence_for_llm,
)
from .providers.base import LLMProvider

BUDGET_WARN_RATIO = 0.8  # avertissement à 80 % de consommation d'une ressource


def _sanitize_evidence_summaries(evidence: list[Evidence]) -> tuple[list[dict], dict, dict]:
    """Keep repository-owned references intact while masking all evidence content."""
    summaries = summarize_evidence_for_llm(evidence)
    content = [{k: v for k, v in item.items() if k not in ("id", "source_id")} for item in summaries]
    exposure = classify_exposure(content)
    cleaned, counts = sanitize_context(content)
    for item, original in zip(cleaned, summaries, strict=True):
        item["id"] = original["id"]
        item["source_id"] = original["source_id"]
    return cleaned, counts, exposure


def _investigation_enabled() -> bool:
    """Interrupteur de la boucle agentique (défaut : activée).

    Désactivable pour reproduire Baseline B (pipeline historique) en évaluation —
    voir docs/17 et eval/runner.py. La sécurité est inchangée dans les deux modes.
    """
    return os.environ.get("AUDITLENS_INVESTIGATION_LOOP", "on").strip().lower() not in ("off", "0", "false")


class Budget:
    """Arrêts explicites (docs/04, ADR-15) : tools, durée, entrée LLM + accounting usage.

    Les garde-fous d'urgence (décisions/appels LLM) ne sont PAS la cause d'arrêt normale :
    la boucle s'arrête par les ressources, la décision de l'agent ou la stagnation.
    """

    def __init__(self, limits):
        self.max_tool_calls = limits.max_tool_calls
        self.max_seconds = limits.max_seconds
        self.max_input_chars = limits.max_input_chars
        # Garde-fous d'urgence dérivés (jamais la cause d'arrêt normale) :
        self.max_decisions = getattr(limits, "max_decisions", None) or max(12, 2 * self.max_tool_calls + 8)
        self.max_llm_calls = getattr(limits, "max_llm_calls", None) or self.max_decisions + 4
        self.used_calls = 0
        self.used_input_chars = 0
        self.used_llm_calls = 0
        self.used_tokens = 0  # usage provider réel quand exposé (sinon 0 = indisponible)
        self.t0 = time.monotonic()

    def can_call(self) -> bool:
        return self.used_calls < self.max_tool_calls and self.elapsed() < self.max_seconds

    def can_prompt(self, chars: int) -> bool:
        return self.used_input_chars + chars <= self.max_input_chars

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    def record_llm(self, resp) -> None:
        self.used_llm_calls += 1
        if resp.usage and resp.usage.get("total_tokens"):
            self.used_tokens += int(resp.usage.get("total_tokens") or 0)

    def warnings(self) -> list[str]:
        """Avertissements à ~80 % d'une ressource (ADR-15) — journalisés + envoyés au LLM."""
        out: list[str] = []
        if self.max_tool_calls and self.used_calls >= BUDGET_WARN_RATIO * self.max_tool_calls:
            out.append(f"outils: {self.used_calls}/{self.max_tool_calls}")
        if self.max_seconds and self.elapsed() >= BUDGET_WARN_RATIO * self.max_seconds:
            out.append(f"temps: {int(self.elapsed())}/{self.max_seconds}s")
        if self.used_input_chars >= BUDGET_WARN_RATIO * self.max_input_chars:
            out.append(f"entrée LLM: {self.used_input_chars}/{self.max_input_chars} caractères")
        return out

    def snapshot(self) -> dict:
        return {
            "tool_calls_used": self.used_calls,
            "max_tool_calls": self.max_tool_calls,
            "input_chars_used": self.used_input_chars,
            "llm_calls_used": self.used_llm_calls,
            "tokens_used": self.used_tokens,
            "seconds_elapsed": round(self.elapsed(), 1),
            "decisions_emergency_cap": self.max_decisions,
        }

    def stop_reason_if_exceeded(self) -> str | None:
        if self.used_calls >= self.max_tool_calls:
            return "budget_exhausted:max_tool_calls"
        if self.elapsed() >= self.max_seconds:
            return "budget_exhausted:max_seconds"
        if self.used_input_chars >= self.max_input_chars:
            return "budget_exhausted:input_tokens"
        return None


class RunOrchestrator:
    def __init__(
        self,
        repo: Repository,
        store: EvidenceStore,
        connectors: ConnectorFactory,
        executor: ToolExecutor,
        bus: EventBus,
        input_models: dict,
        controls: dict[str, set[str]] | None = None,
        steering=None,
    ):
        self.repo = repo
        self.store = store
        self.connectors = connectors
        self.executor = executor
        self.bus = bus
        self.input_models = input_models
        # Registre de contrôle runtime (ADR-15) : {run_id: {"pause","stop"}} rempli par
        # les endpoints pause/stop ; consommé (discard) par la boucle entre deux tours.
        self.controls = controls if controls is not None else {}
        from .steering import SteeringQueue

        self.steering = steering if steering is not None else SteeringQueue()

    def _consume_control(self, run_id: str, action: str) -> bool:
        flags = self.controls.get(run_id)
        if flags and action in flags:
            flags.discard(action)
            return True
        return False

    def _drain_steering(self, run_id: str) -> list[dict]:
        """Frontière de tour (Phase 8/10) : consomme les instructions auditeur en
        attente — JAMAIS pendant un tool en vol. Statut applied + événement."""
        items = self.steering.drain(run_id)
        for item in items:
            self.bus.publish(run_id, "steering_applied", item.to_dict())
        return [item.to_dict() for item in items]

    async def execute_run(self, run: AuditRun, mission: AuditMission, provider: LLMProvider,
                          resume_state: dict | None = None) -> None:
        run.status = RunStatus.running
        run.started_at = run.started_at or __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds")
        await self.repo.update_run(run)
        await self.bus.publish(run.id, "run_started", {"mission_id": mission.id, "provider": provider.provider_id, "model": provider.model_id})

        budget = Budget(mission.limits)
        if resume_state:
            # Reprise (ADR-15) : on repart du checkpoint — budget déjà consommé, temps
            # d'exécution fraîchement borné (fenêtre d'exécution de ce segment).
            consumed = resume_state.get("budget") or {}
            budget.used_calls = int(consumed.get("tool_calls_used") or 0)
            budget.used_input_chars = int(consumed.get("input_chars_used") or 0)
            budget.used_tokens = int(consumed.get("tokens_used") or 0)
            run.tool_calls_used = budget.used_calls
        try:
            if resume_state:
                # ---- Reprise : pas de re-découverte ni de re-plan (idempotent, ADR-15) ----
                await self.bus.publish(run.id, "phase", {"phase": "resume"})
                sources = {s.id: s for s in [await self.connectors.get_source(sid) for sid in mission.source_ids] if s}
                source_types = {sid: s.type for sid, s in sources.items()}
                registry_capabilities = self.executor.registry.capabilities_for_mission(mission, source_types)
                controls_list = [control_to_dict(c) for c in map(get_control, mission.control_ids) if c]
                ctx = ToolContext(
                    mission=mission, run_id=run.id, source=None, secrets={},
                    store=self.store, repo=self.repo, connectors=self.connectors,
                    extra={"tool_input_models": self.input_models},
                )
            else:
                # ---- 1. Découverte des capacités réelles (docs/04 étape 2) ----
                await self.bus.publish(run.id, "phase", {"phase": "discover"})
                sources = {s.id: s for s in [await self.connectors.get_source(sid) for sid in mission.source_ids] if s}
                discovered = await self._discover_sources(run, mission, sources)
                source_types = {sid: s.type for sid, s in sources.items()}
                # Capacités du Tool Registry : la liste EXACTE des tools (nom + schéma) offerte au LLM.
                registry_capabilities = self.executor.registry.capabilities_for_mission(mission, source_types)
                initial_evidence = await self.repo.list_evidence(mission_id=mission.id)
                controls_list = [control_to_dict(c) for c in map(get_control, mission.control_ids) if c]
                source_intelligence = self._intelligence_payload(sources, discovered, mission, self.executor.registry)
                await self.bus.publish(run.id, "source_intelligence", {
                    "intelligence": source_intelligence,
                })

                # ---- 2. Plan proposé par l'agent ----
                await self.bus.publish(run.id, "phase", {"phase": "plan"})
                plan_payload = await self._chat_json(provider, run, budget, plan_request(
                    mission.model_dump(),
                    self._sources_payload(sources, initial_evidence, discovered),
                    registry_capabilities,
                    controls_list,
                    intelligence=source_intelligence,
                ))
                plan = self._parse_plan(run.id, mission.id, plan_payload, provider)
                await self.bus.publish(run.id, "plan", {"plan_id": plan.id, "steps": [s.model_dump() for s in plan.steps], "risks": plan.risks})

                # ---- 3. Couverture : exécution bornée des tools planifiés (docs/04 étapes 5-9) ----
                ctx = ToolContext(
                    mission=mission, run_id=run.id, source=None, secrets={},
                    store=self.store, repo=self.repo, connectors=self.connectors,
                    extra={"tool_input_models": self.input_models},
                )
                await self._execute_steps(run, mission, ctx, plan.steps, budget, provider)

                # ---- 4. Réconciliation déterministe automatique (calcul local sur preuves collectées) ----
                # Hybride docs/03 : la réconciliation est un CALCUL, pas une décision de modèle —
                # elle s'exécute dès que les preuves Odoo nécessaires existent, sans dépendre
                # de la variance de planification du modèle (aucun accès supplémentaire).
                await self._auto_odoo_reconciliation(run, mission, ctx, budget)

            # ---- 5. Boucle d'investigation agentique (ADR-14/15) ----
            # Bornée par les RESSOURCES (tools, temps, entrée LLM, garde-fous d'urgence),
            # avec stagnation, avertissements budget, checkpoints et pause/reprise.
            await self.bus.publish(run.id, "phase", {"phase": "investigation"})
            investigation_payload: dict | None = None
            if _investigation_enabled():
                sources_payload = self._sources_payload(sources, [])
                investigation_payload = await self._investigation_loop(
                    run, mission, ctx, budget, provider, sources_payload,
                    registry_capabilities, controls_list,
                    resume_state=(resume_state or {}).get("investigation"),
                )

            if run.status == RunStatus.paused:
                # Travail préservé dans le checkpoint — constats différés à la reprise (ADR-15).
                await self.bus.publish(run.id, "run_paused", {
                    "stop_reason": run.stop_reason,
                    "budget": budget.snapshot(),
                })
                return
            if run.status == RunStatus.cancelled:
                await self.bus.publish(run.id, "run_cancelled", {
                    "reason": run.stop_reason,
                    "budget": budget.snapshot(),
                })
                return

            # ---- 6. Findings proposés par l'agent ----
            await self.bus.publish(run.id, "phase", {"phase": "findings"})
            # Index complet de la mission : un constat peut citer une preuve initiale (import)
            # comme une preuve du run — l'appartenance mission est l'invariant docs/14.
            final_evidence = await self.repo.list_evidence(mission_id=mission.id)
            evidence_summaries_final, findings_redactions, detected = _sanitize_evidence_summaries(final_evidence)
            await self.bus.publish(run.id, "privacy_preview", {
                "provider": provider.provider_id, "model": provider.model_id,
                "categories": detected["categories"],
                "total_redactions": sum(findings_redactions.values()),
                "note": detected["note"],
                "phase": "findings",
            })
            findings_raw = await self._chat_json(provider, run, budget, findings_request(
                evidence_summaries_final,
                controls_list,
                mission.objective,
                investigation_state=investigation_payload,
            ))
            proposed = findings_raw.get("findings", []) if isinstance(findings_raw, dict) else []

            evidence_index = {e.id: e for e in final_evidence}
            findings, rejections = await validate_findings(
                proposed, run_id=run.id, mission_id=mission.id, evidence_index=evidence_index
            )
            for f in findings:
                await self.repo.create_finding(f)
                await self.bus.publish(run.id, "finding", f.model_dump())
            for reason in rejections:
                await self.bus.publish(run.id, "finding_rejected", {"reason": reason})

            # ---- 7. Assessments déterministes (docs/11) ----
            for control_id in mission.control_ids:
                control = get_control(control_id)
                if control is None:
                    continue
                assessment = evaluate_assessment(control, final_evidence, findings, run.id, mission.id)
                await self.repo.create_assessment(assessment)
                await self.bus.publish(run.id, "assessment", assessment.model_dump())

            # ---- 8. Statut final ----
            stop = budget.stop_reason_if_exceeded()
            run.tool_calls_used = budget.used_calls
            run.input_chars_used = budget.used_input_chars
            if stop:
                run.status = RunStatus.partial
                run.stop_reason = stop
            elif any(f.status == FindingStatus.needs_review for f in findings):
                run.status = RunStatus.review_required
                run.stop_reason = "completed"
            else:
                run.status = RunStatus.completed
                run.stop_reason = "completed"
            run.finished_at = run.finished_at or _now()
            await self.repo.update_run(run)
            await self._snapshot_report(run, mission, final_evidence, findings)
            await self.bus.publish(run.id, "run_completed", {
                "status": run.status.value, "stop_reason": run.stop_reason,
                "tool_calls": budget.used_calls, "findings": len(findings),
                "rejections": len(rejections),
                "llm_calls": budget.used_llm_calls,
                "tokens_used": budget.used_tokens,
                "decisions": investigation_payload.get("decisions_used") if investigation_payload else 0,
            })

        except ProviderError as exc:
            await self._fail(run, f"provider_error: {exc}")
        except asyncio.TimeoutError:
            run.status = RunStatus.partial
            run.stop_reason = "budget_exhausted:max_seconds"
            run.finished_at = _now()
            await self.repo.update_run(run)
            await self.bus.publish(run.id, "run_completed", {"status": run.status.value, "stop_reason": run.stop_reason})
        except Exception as exc:  # noqa: BLE001
            await self._fail(run, f"{type(exc).__name__}: {exc}")
        finally:
            await provider.close()

    # ---------- sous-étapes ----------

    async def _discover_sources(self, run: AuditRun, mission: AuditMission, sources: dict[str, SourceConnection]) -> list[dict]:
        capabilities: list[dict] = []
        for source in sources.values():
            try:
                connector = self.connectors.build(source)
                try:
                    caps = await connector.discover()
                finally:
                    await connector.close()
            except Exception as exc:  # noqa: BLE001
                caps = {"discover_error": f"{type(exc).__name__}: {exc}"}
                await self.bus.publish(run.id, "warning", {"source_id": source.id, "message": caps["discover_error"]})
            capabilities.append({"source_id": source.id, "source_type": source.type.value, "capabilities": redact(caps)})
        return capabilities

    def _sources_payload(
        self, sources: dict[str, SourceConnection], evidence: list[Evidence],
        discovered: list[dict] | None = None,
    ) -> list[dict]:
        out = []
        initial_by_source: dict[str, list[str]] = {}
        for e in evidence:
            if e.type == "raw_file" and e.source_id:
                initial_by_source.setdefault(e.source_id, []).append(e.id)
        discovered_by_source = {d["source_id"]: d.get("capabilities") for d in discovered or []}
        for s in sources.values():
            cfg = s.config or {}
            out.append({
                "source_id": s.id,
                "type": s.type.value,
                "name": s.name,
                "initial_evidence_ids": initial_by_source.get(s.id, []),
                "rule_set_id": cfg.get("rule_set_id"),
                "endpoints": cfg.get("endpoints", []) if s.type == "api" else [],
                "journeys": cfg.get("journeys", []) if s.type == "web" else [],
                "discovered": redact(discovered_by_source.get(s.id)) if s.id in discovered_by_source else None,
            })
        return out

    def _intelligence_payload(
        self, sources: dict[str, SourceConnection], discovered: list[dict],
        mission: AuditMission, registry: ToolRegistry,
    ) -> dict[str, dict[str, Any]]:
        """Intelligence structurée par source (Phase 1) : capacités réelles, opérations
        supportées/manquantes — le LLM de plan choisit ses tools sans rien inventer."""
        from ..audit.discovery import build_source_intelligence

        out: dict[str, dict[str, Any]] = {}
        for d in discovered:
            sid = d.get("source_id")
            src = sources.get(sid)
            if src is None:
                continue
            out[sid] = build_source_intelligence(src, d.get("capabilities") or {}, registry, mission)
        return out

    async def _chat_json(self, provider: LLMProvider, run: AuditRun, budget: Budget, prompt: str) -> dict:
        resp = await provider.chat(SYSTEM_PROMPT, [{"role": "user", "content": prompt}])
        # budget d'entrée cumulé (approximation par caractères — docs/04) + usage provider réel
        budget.record_llm(resp)
        run.input_chars_used += resp.input_chars
        await self.repo.update_run(run)
        content = resp.content or "{}"
        try:
            return json.loads(_extract_json_block(content))
        except json.JSONDecodeError:
            return {}

    async def _execute_steps(
        self, run: AuditRun, mission: AuditMission, ctx: ToolContext,
        steps: list, budget: Budget, provider: LLMProvider,
    ) -> list:
        # steps peut contenir des AuditPlanStep (plan validé) ou des dicts (étapes de décision)
        normalized = [s.model_dump() if hasattr(s, "model_dump") else s for s in steps]
        results = []
        for step in normalized:
            if not budget.can_call():
                await self.bus.publish(run.id, "warning", {"message": "budget tool calls atteint — arrêt de la boucle"})
                break
            tool = step["tool"]
            args = step.get("args", {}) or {}
            source_id = args.get("source_id") or step.get("source_id")
            if source_id:
                args = {**args, "source_id": source_id}
            await self.bus.publish(run.id, "tool_started", {"tool": tool, "args": redact(args), "rationale": step.get("rationale", "")})
            ctx.source = await self.connectors.get_source(source_id) if source_id else None
            ctx.secrets = self.connectors.secrets_for(ctx.source)
            result = await self.executor.execute(tool, args, ctx)
            results.append(result)
            budget.used_calls += 1
            run.tool_calls_used = budget.used_calls
            await self.repo.update_run(run)
            for ev_id in result.evidence_ids:
                ev = await self.repo.get_evidence_meta(ev_id, mission.id)
                if ev:
                    await self.bus.publish(run.id, "evidence", ev.model_dump())
            await self.bus.publish(run.id, "tool_completed", {
                "tool": tool, "status": result.status, "record_count": result.record_count,
                "evidence_ids": result.evidence_ids, "warnings": result.warnings,
                "error": result.error, "preview_keys": sorted((result.preview or {}).keys()),
            })
        return results

    async def _investigation_loop(
        self, run: AuditRun, mission: AuditMission, ctx: ToolContext, budget: Budget,
        provider: LLMProvider, sources_payload: list[dict], capabilities: list[dict],
        controls: list[dict], resume_state: dict | None = None,
    ) -> dict | None:
        """Boucle agentique bornée par les RESSOURCES (ADR-14/15).

        Continuité : le LLM décide tour après tour tant que les ressources le permettent
        (tools, temps, entrée LLM ; `max_decisions`/`max_llm_calls` ne sont que des
        garde-fous d'urgence dérivés, jamais la cause d'arrêt normale). Progression
        surveillée : répétitions identiques et erreurs consécutives produisent un signal
        structuré au LLM puis, sans adaptation, un arrêt explicite. Chaque tour écrit un
        CHECKPOINT persistant ; pause/stop demandés par l'humain sont honorés entre deux
        tours (l'appel tool en cours, read-only et borné, se termine proprement).
        Pause sur épuisement budget : status `paused` + checkpoint (reprise possible).
        """
        state = (
            InvestigationState.from_checkpoint(resume_state)
            if resume_state else InvestigationState()
        )
        controls_payload = json.dumps(controls, ensure_ascii=False)
        llm_calls_at_loop_start = budget.used_llm_calls
        exit_kind = "stagnation"  # par défaut : arrêt pour cause de stagnation/garde-fou

        def remaining_decisions() -> int:
            return budget.max_decisions - state.decisions

        while True:
            # --- contrôle humain (pause/stop) consommé entre deux tours ---
            if self._consume_control(run.id, "pause"):
                run.status = RunStatus.paused
                run.stop_reason = "paused_by_auditor"
                await self.repo.update_run(run)
                await self._write_checkpoint(run, mission, budget, state, "paused")
                await self.bus.publish(run.id, "investigation_paused", {
                    "reason": "demande de l'auditeur", "turn": state.decisions,
                    "hypotheses": len(state.hypotheses), "budget": budget.snapshot(),
                })
                return state.to_checkpoint()

            if self._consume_control(run.id, "stop"):
                run.status = RunStatus.cancelled
                run.stop_reason = "cancelled_by_auditor"
                run.finished_at = _now()
                await self.repo.update_run(run)
                await self._write_checkpoint(run, mission, budget, state, "stopped")
                await self.bus.publish(run.id, "investigation_stop", {
                    "reason": "annulation demandée par l'auditeur", "turn": state.decisions,
                })
                return state.to_checkpoint()

            # --- limite de temps de cette fenêtre d'exécution → PAUSE reprenable ---
            if budget.elapsed() >= budget.max_seconds:
                await self._pause_on_exhaustion(run, mission, budget, state)
                await self.bus.publish(run.id, "investigation_stop", {
                    "reason": "temps épuisé — investigation en pause, reprise possible (ADR-15)",
                    "turn": state.decisions,
                })
                return state.to_checkpoint()

            # --- stagnation forcée (échecs consécutifs sans adaptation) ---
            if state.stagnation_forced:
                await self.bus.publish(run.id, "investigation_stop", {
                    "reason": state.stop_rationale, "turn": state.decisions,
                })
                break

            # --- outils épuisés : sortie gracieuse vers la phase de conclusion ---
            # Le constat reste produit sur les preuves collectées (findings ne requiert pas
            # de tool) ; pauser ici empêcherait inutilement la conclusion. Le temps et
            # l'entrée LLM restent des causes de pause (travail réellement interrompu).
            if not budget.can_call():
                state.stop_rationale = (
                    "budget tools épuisé — l'investigation passe à la conclusion sur les "
                    "preuves collectées (extension possible via /extend-budget + /resume)"
                )
                await self.bus.publish(run.id, "investigation_stop", {
                    "reason": state.stop_rationale, "turn": state.decisions,
                })
                await self._write_checkpoint(run, mission, budget, state, "completed")
                return state.to_checkpoint()

            # --- garde-fous d'urgence (jamais la cause d'arrêt normale) ---
            if state.decisions >= budget.max_decisions:
                state.stop_rationale = (
                    f"garde-fou d'urgence atteint ({budget.max_decisions} décisions) — "
                    "limite dérivée du budget tools, configurable via mission.limits.max_decisions"
                )
                exit_kind = "emergency"
                break
            if budget.used_llm_calls - llm_calls_at_loop_start >= budget.max_llm_calls:
                state.stop_rationale = f"garde-fou d'urgence LLM atteint ({budget.max_llm_calls} appels)"
                exit_kind = "emergency"
                break

            # Périmètre mission complet : inclut les preuves initiales (imports) ET celles du run.
            evidence_now = await self.repo.list_evidence(mission_id=mission.id)
            remaining_calls = budget.max_tool_calls - budget.used_calls
            budget_warnings = budget.warnings()
            # Phase 7/10 + stabilisation : détection AVANT masquage (categories), puis
            # masquage EFFECTIF du contexte parti au LLM (les preuves restent intactes)
            evidence_summaries_now, redaction_counts, detected = _sanitize_evidence_summaries(evidence_now)
            total_redactions = sum(redaction_counts.values())
            await self.bus.publish(run.id, "privacy_preview", {
                "provider": provider.provider_id, "model": provider.model_id,
                "categories": detected["categories"],
                "total_redactions": total_redactions,
                "note": detected["note"],
                "phase": "investigation",
            })
            steered = self._drain_steering(run.id)
            if steered:
                state.user_directives.extend(d["instruction"] for d in steered)
            prompt = investigation_request(
                mission.objective, controls, capabilities,
                evidence_summaries_now, state,
                remaining_calls, remaining_decisions(), sources=sources_payload,
            )
            if not budget.can_prompt(len(prompt) + len(controls_payload)):
                state.stop_rationale = "budget d'entrée LLM atteint — pause reprenable"
                exit_kind = "input"
                break
            decision = parse_decision(await self._chat_json(provider, run, budget, prompt))
            kind = decision["decision"]
            state.record_decision(kind, decision.get("tool"), decision.get("args"),
                                  decision.get("rationale", ""))
            await self.bus.publish(run.id, "investigation_decision", {
                "decision": kind, "rationale": decision.get("rationale", ""),
                "tool": decision.get("tool"), "args": redact(decision.get("args") or {}),
                "turn": state.decisions, "budget_warnings": budget_warnings,
                "stagnation_notice": state.stagnation_notice,
                "budget": budget.snapshot(),
            })
            if budget_warnings:
                await self.bus.publish(run.id, "budget_warning", {
                    "resources": budget_warnings, "budget": budget.snapshot(),
                })

            # Hypothèses : révision explicite, refs validées contre la mission (docs/14).
            if decision.get("hypotheses"):
                ev_index = {e.id: e for e in evidence_now}
                existing = {h.id for h in state.hypotheses}
                notes = state.apply_hypotheses(decision["hypotheses"], ev_index)
                for h in state.hypotheses:
                    if h.id in existing and h.status != "open":
                        await self.bus.publish(run.id, "hypothesis_updated", h.to_dict())
                    elif h.id not in existing:
                        await self.bus.publish(run.id, "hypothesis_created", h.to_dict())
                for note in notes:
                    await self.bus.publish(run.id, "hypothesis_rejected", {"reason": note})

            if kind == "call_tool":
                results = await self._execute_steps(run, mission, ctx, [{
                    "tool": decision["tool"], "source_id": decision.get("source_id"),
                    "args": decision.get("args") or {}, "rationale": decision.get("rationale", ""),
                }], budget, provider)
                for r in results:
                    blocked = (r.preview or {}).get("blocked_reason")
                    obs = Observation(
                        kind="blocked" if r.status == "unauthorized" else ("error" if r.status == "error" else "tool"),
                        tool=r.tool, status=r.status,
                        text=(
                            f"REFUS policy: {blocked}" if blocked
                            else (f"erreur: {r.error}" if r.error else f"statut={r.status}, enregistrements={r.record_count}")
                        ),
                        evidence_ids=list(r.evidence_ids),
                        turn=state.decisions,
                    )
                    state.add_observation(obs)
                    state.note_outcome(obs)
            elif kind == "request_human_input":
                info = decision.get("info_request", "")
                state.info_requests.append(info)
                await self.bus.publish(run.id, "info_request", {"message": info})
            elif kind == "stop":
                state.stop_rationale = decision.get("stop_rationale", "arrêt")
                await self.bus.publish(run.id, "investigation_stop", {
                    "reason": state.stop_rationale, "turn": state.decisions,
                })
                return state.to_checkpoint()

            # checkpoint par tour (survit à un crash/restart, ADR-15)
            await self._write_checkpoint(run, mission, budget, state, "turn")

        # Sorties de boucle hors décision de l'agent :
        # - limites de ressources (garde-fous, entrée LLM) → PAUSE reprenable (travail préservé,
        #   reprise après extension de budget approuvée par l'humain) ;
        # - stagnation forcée → investigation terminée par sécurité, constats possibles
        #   sur les preuves collectées (le modèle n'a pas réussi à progresser).
        if exit_kind in ("emergency", "input"):
            await self._pause_on_exhaustion(run, mission, budget, state)
            return state.to_checkpoint()
        await self._write_checkpoint(run, mission, budget, state, "completed")
        return state.to_checkpoint()

    async def _pause_on_exhaustion(
        self, run: AuditRun, mission: AuditMission, budget: Budget, state: InvestigationState | None,
    ) -> None:
        """Budget tools épuisé DURANT la boucle : pause préservée plutôt qu'arrêt sec.

        Le checkpoint permet à l'auditeur d'approuver une extension de budget puis de
        reprendre l'investigation (POST /api/missions/{id}/extend-budget + /resume).
        """
        if state is not None:
            await self._write_checkpoint(run, mission, budget, state, "budget_exhausted")
        run.status = RunStatus.paused
        run.stop_reason = "budget_exhausted:awaiting_extension"
        await self.repo.update_run(run)
        await self.bus.publish(run.id, "investigation_paused", {
            "reason": "budget tools épuisé — extension requise pour continuer",
            "budget": budget.snapshot(),
        })

    async def _write_checkpoint(
        self, run: AuditRun, mission: AuditMission, budget: Budget,
        state: InvestigationState, reason: str,
    ) -> None:
        """Persiste un checkpoint complet (survit au restart — ADR-15)."""
        evidence = await self.repo.list_evidence(mission_id=mission.id)
        cp = InvestigationCheckpoint(
            id=new_id("cp"), run_id=run.id, mission_id=mission.id, reason=reason,
            state={
                "objective": mission.objective,
                "source_ids": list(mission.source_ids),
                "investigation": state.to_checkpoint(),
                "evidence_refs": [e.id for e in evidence],
                "budget": budget.snapshot(),
                "last_meaningful_observation": (
                    state.observations[-1].to_dict() if state.observations else None
                ),
                "remaining_opportunities_note": "reprise via POST /api/runs/{id}/resume",
            },
        )
        await self.repo.create_checkpoint(cp)

    def _parse_plan(self, run_id: str, mission_id: str, payload: dict, provider: LLMProvider) -> AuditPlan:
        return AuditPlan(
            id=new_id("plan"), mission_id=mission_id, provider_id=provider.provider_id,
            model_id=provider.model_id,
            steps=self._parse_steps(payload.get("steps", [])),
            evidence_expected=[str(e) for e in payload.get("evidence_expected", [])],
            risks=[str(r) for r in payload.get("risks", [])],
        )

    @staticmethod
    def _parse_steps(raw_steps: list) -> list[dict]:
        steps = []
        for s in raw_steps[:32]:
            if not isinstance(s, dict) or not s.get("tool"):
                continue
            steps.append({
                "tool": str(s["tool"]),
                "source_id": s.get("source_id"),
                "args": s.get("args") if isinstance(s.get("args"), dict) else {},
                "rationale": str(s.get("rationale", "")),
            })
        return steps

    async def _auto_odoo_reconciliation(self, run: AuditRun, mission: AuditMission, ctx: ToolContext, budget: Budget) -> None:
        """Exécute odoo_cross_check automatiquement si les preuves Odoo requises existent
        et qu'aucune réconciliation n'a déjà été produite (calcul local, docs/03 ADR-01)."""
        evidence = await self.repo.list_evidence(run_id=run.id)
        if any(e.type == "odoo_cross_check" for e in evidence):
            return
        models: dict[str, str] = {}
        for e in evidence:
            if e.type == "record_set":
                model = (e.summary or {}).get("model")
                if model and model not in models:
                    models[model] = e.id
        required = ["sale.order", "account.move", "stock.move"]
        if not all(m in models for m in required):
            return
        if mission.limits.max_tool_calls - budget.used_calls < 1:
            await self.bus.publish(run.id, "warning", {"message": "budget tool calls atteint — réconciliation automatique non exécutée"})
            return
        ids = [models[m] for m in required]
        if "purchase.order" in models:
            ids.append(models["purchase.order"])
        await self._execute_steps(run, mission, ctx, [{
            "tool": "odoo_cross_check",
            "args": {"evidence_ids": ids},
            "rationale": "Réconciliation déterministe automatique des preuves Odoo collectées (hybride docs/03).",
        }], budget, self._noop_provider())

    def _noop_provider(self):
        """Provider factice pour l'exécution d'étapes automatiques (aucun appel LLM)."""
        class _N:
            provider_id = "auto"
            model_id = "deterministic"

            async def chat(self, *a, **k):  # jamais appelé par _execute_steps
                raise RuntimeError("auto step ne dialogue pas avec le LLM")

            async def close(self):
                return None
        return _N()

    async def _snapshot_report(self, run: AuditRun, mission: AuditMission, evidence: list[Evidence], findings: list[FindingCandidate]) -> None:
        from ..findings.reports import build_report

        assessments = await self.repo.list_assessments(run.id)
        report = build_report(run, mission, assessments, evidence, findings, version=1)
        await self.repo.create_report(report)

    async def _fail(self, run: AuditRun, message: str) -> None:
        run.status = RunStatus.failed
        run.error = message
        run.finished_at = _now()
        await self.repo.update_run(run)
        await self.bus.publish(run.id, "run_failed", {"error": message})


def _extract_json_block(content: str) -> str:
    """Retourne le premier objet JSON valide du contenu (tolère les fences ```json)."""
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
    idx = content.find("{")
    if idx == -1:
        return "{}"
    try:
        obj, _ = json.JSONDecoder().raw_decode(content[idx:])
        return json.dumps(obj)
    except json.JSONDecodeError:
        return "{}"


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
