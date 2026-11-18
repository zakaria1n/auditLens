"""Boucle d'investigation agentique (docs/04 v2, ADR-14).

Contrairement à la passe « supplémentaire » historique (un seul appel, à aveugle),
cette boucle redonne la main au LLM après CHAQUE observation : il voit les preuves
réellement collectées (résumés bornés), les observations d'outils récentes (y compris
les refus Policy Gate), ses hypothèses courantes et le budget restant, puis choisit :

- call_tool          : exécuter une tool autorisée (le Policy Gate reste l'autorité) ;
- update_hypotheses  : créer/réviser/rejeter des hypothèses avec evidence_refs réels ;
- request_human_input: demander une information à l'auditeur (événement visible, non bloquant) ;
- stop               : terminer avec un rationale explicite.

Le LLM ne décide NI permissions NI calculs : chaque call_tool traverse le même
executor/gate que le plan, et les calculs restent déterministes (docs/03 ADR-01).
L'état vit en mémoire du run et est JOURNALISÉ via des événements réels (UI docs/19) —
pas de nouvelle infrastructure de persistance.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any

DECISION_SCHEMA = {
    "decision": "call_tool|update_hypotheses|request_human_input|stop",
    "tool": "str|null (si call_tool — copié mot pour mot depuis capabilities)",
    "source_id": "str|null",
    "args": {},
    "rationale": "str — pourquoi cette action maintenant",
    "hypotheses": [{"id": "str", "statement": "str", "status": "open|supported|rejected|inconclusive",
                    "evidence_refs": ["ev_..."],
                    "alternatives": [{"id": "str", "statement": "str", "evidence_refs": ["ev_..."]}],
                    "contradicted_by": ["ev_..."], "revision_note": "str"}],
    "stop_rationale": "str|null (si stop)",
    "info_request": "str|null (si request_human_input)",
}

HYPOTHESIS_STATUSES = ("open", "supported", "rejected", "inconclusive")
DECISION_KINDS = ("call_tool", "update_hypotheses", "request_human_input", "stop")

CHALLENGER_CONSIGNES = (
    "CHALLENGER (obligatoire avant toute conclusion 'supported') : "
    "Genere au moins UNE explication alternative plausible (alternatives) ; "
    "cherche des preuves CONTRAIRES et liste-les (contradicted_by) ; "
    "si une alternative est mieux etayee, revise l'hypothese (status) et documente "
    "le changement via revision_note ; distingue suspect (inconclusive) de confirme (supported)."
)

MAX_OBSERVATIONS = 8  # observations récentes renvoyées au LLM (borné, docs/06)
MAX_HYPOTHESES = 8
MAX_OBS_TEXT = 400  # taille max du résumé textuel d'une observation
MAX_DECISION_LOG = 12  # historique de décisions conservé dans l'état (contexte borné)

# Stagnation (ADR-15) : la répétition n'est pas automatiquement improductive
# (vérification délibérée, nouvelle donnée) — on tolère UNE répétition consécutive
# identique ; au-delà, signale ; trop d'erreurs consécutives sans adaptation → arrêt.
STAGNATION_REPEAT_WARN = 2   # 2ᵉ appel identique consécutif → signal au LLM
STAGNATION_ERROR_WARN = 3    # 3 erreurs consécutives → signal
STAGNATION_ERROR_STOP = 5    # 5 erreurs consécutives sans succès → arrêt forcé explicite


@dataclass
class HypothesisRevision:
    """Revision horodatee d'une hypothese (Phase 4/10 - Hypothesis Challenger)."""

    turn: int
    status: str
    statement: str
    evidence_refs: list[str]
    note: str = ""  # pourquoi cette revision (rationale de la decision)

    def to_dict(self) -> dict:
        return {"turn": self.turn, "status": self.status, "statement": self.statement,
                "evidence_refs": list(self.evidence_refs), "note": self.note}


@dataclass
class Hypothesis:
    id: str
    statement: str
    status: str = "open"  # open | supported | rejected | inconclusive
    evidence_refs: list[str] = field(default_factory=list)
    # Phase 4/10 - Challenger : explications alternatives et contradictions cherchees
    alternatives: list[dict] = field(default_factory=list)   # [{id, statement, evidence_refs}]
    contradicted_by: list[str] = field(default_factory=list)  # evidence_refs contraires
    revisions: list[HypothesisRevision] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "statement": self.statement, "status": self.status,
            "evidence_refs": list(self.evidence_refs),
            "alternatives": list(self.alternatives),
            "contradicted_by": list(self.contradicted_by),
            "revisions": [r.to_dict() for r in self.revisions],
        }


@dataclass
class Observation:
    """Résultat compact d'une action exécutée pendant la boucle (succès, refus ou erreur).

    `turn` horodate l'observation DANS la boucle : permet au LLM de COMPARER des
    observations du même objectif prises à des moments différents (vérification
    transitoire vs persistante, ADR-15bis) sans rien inventer.
    """

    kind: str  # tool | blocked | error
    tool: str
    status: str
    text: str  # déjà redacté en amont (preview minimisé)
    evidence_ids: list[str] = field(default_factory=list)
    turn: int = 0

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "tool": self.tool, "status": self.status,
            "text": self.text[:MAX_OBS_TEXT], "evidence_ids": list(self.evidence_ids),
            "turn": self.turn,
        }


class InvestigationState:
    """État d'investigation du run : hypothèses, observations récentes, décisions,
    détection de stagnation. Sérialisable (checkpoint ADR-15) et restaurable."""

    def __init__(self) -> None:
        self.hypotheses: list[Hypothesis] = []
        self.observations: deque[Observation] = deque(maxlen=MAX_OBSERVATIONS)
        self.decisions = 0
        self.info_requests: list[str] = []
        self.stop_rationale: str | None = None
        self.decision_log: list[dict] = []          # historique borné (contexte docs/06)
        self._last_signature: str | None = None     # signature du dernier call_tool
        self._repeat_count: int = 0                 # répétitions consécutives identiques
        self.consecutive_errors: int = 0            # échecs consécutifs sans succès
        self.stagnation_notice: str | None = None   # signal transmis au LLM au tour suivant
        self.stagnation_forced: bool = False        # True → arrêt forcé explicite

    def add_observation(self, obs: Observation) -> None:
        self.observations.append(obs)

    def record_decision(self, kind: str, tool: str | None = None, args: dict | None = None,
                        rationale: str = "") -> None:
        """Journalise la décision et met à jour les compteurs de stagnation."""
        self.decisions += 1
        entry = {"turn": self.decisions, "decision": kind, "tool": tool,
                 "rationale": rationale[:200]}
        self.decision_log.append(entry)
        if len(self.decision_log) > MAX_DECISION_LOG:
            self.decision_log = self.decision_log[-MAX_DECISION_LOG:]

        if kind == "call_tool" and tool:
            try:
                signature = f"{tool}::{json.dumps(args or {}, ensure_ascii=False, sort_keys=True, default=str)}"
            except (TypeError, ValueError):
                signature = f"{tool}::{args}"
            if signature == self._last_signature:
                self._repeat_count += 1
                if self._repeat_count >= STAGNATION_REPEAT_WARN:
                    self.stagnation_notice = (
                        f"Appel identique répété {self._repeat_count} fois consécutives ({tool}). "
                        "Une vérification délibérée est légitime une fois ; au-delà, change d'approche, "
                        "propose une autre tool, mets à jour tes hypothèses ou stop."
                    )
            else:
                self._repeat_count = 0
                self.stagnation_notice = None
            self._last_signature = signature
        else:
            # toute autre action réinitialise la répétition (nouvelle information produite)
            self._repeat_count = 0
            self._last_signature = None

    def note_outcome(self, obs: Observation) -> None:
        """Compte les échecs consécutifs sans adaptation (succès → reset)."""
        if obs.status in ("success", "partial"):
            self.consecutive_errors = 0
            return
        self.consecutive_errors += 1
        if self.consecutive_errors >= STAGNATION_ERROR_WARN:
            self.stagnation_notice = (
                f"{self.consecutive_errors} échecs d'outils consécutifs sans succès. "
                "Diagnostique la cause (mauvais arguments ? source hors périmètre ?) : corrige, "
                "change d'approche ou stop avec un rationale explicite."
            )
        if self.consecutive_errors >= STAGNATION_ERROR_STOP:
            self.stagnation_forced = True
            self.stop_rationale = (
                f"stagnation détectée : {self.consecutive_errors} échecs consécutifs d'outils "
                "sans adaptation — investigation arrêtée par sécurité (ADR-15)."
            )

    def apply_hypotheses(self, proposed: list[dict], evidence_index: dict[str, Any]) -> list[str]:
        """Applique les hypothèses proposées. Retourne les notes de rejet (refs invalides)."""
        notes: list[str] = []
        by_id = {h.id: h for h in self.hypotheses}
        kept: list[Hypothesis] = []
        for raw in proposed[:MAX_HYPOTHESES]:
            if not isinstance(raw, dict):
                continue
            hid = str(raw.get("id") or f"h{len(kept) + 1}")[:40]
            status = str(raw.get("status") or "open")
            if status not in HYPOTHESIS_STATUSES:
                status = "open"
            refs = [str(r) for r in (raw.get("evidence_refs") or []) if str(r) in evidence_index]
            invalid = [str(r) for r in (raw.get("evidence_refs") or []) if str(r) not in evidence_index]
            if invalid:
                notes.append(f"hypothèse {hid}: evidence_refs ignorées (inexistantes/hors mission): {invalid}")
            statement = str(raw.get("statement") or "")[:500]
            alternatives = [
                {
                    "id": str(a.get("id") or f"alt_{i + 1}"),
                    "statement": str(a.get("statement") or "")[:500],
                    "evidence_refs": [str(r) for r in (a.get("evidence_refs") or []) if str(r) in evidence_index],
                }
                for i, a in enumerate(raw.get("alternatives") or []) if isinstance(a, dict)
            ][:5]
            contradicted_by = [str(r) for r in (raw.get("contradicted_by") or []) if str(r) in evidence_index]
            existing = by_id.get(hid)
            if existing is not None:
                changed = (
                    existing.statement != statement or existing.status != status
                    or existing.evidence_refs != refs
                )
                if changed:
                    existing.revisions.append(HypothesisRevision(
                        turn=self.decisions, status=existing.status,
                        statement=existing.statement,
                        evidence_refs=list(existing.evidence_refs),
                        note=str(raw.get("revision_note") or "")[:300],
                    ))
                existing.statement, existing.status, existing.evidence_refs = statement, status, refs
                existing.alternatives = alternatives
                existing.contradicted_by = contradicted_by
                kept.append(existing)
            else:
                kept.append(Hypothesis(
                    id=hid, statement=statement, status=status, evidence_refs=refs,
                    alternatives=alternatives, contradicted_by=contradicted_by,
                ))
        self.hypotheses = kept
        return notes

    def to_payload(self) -> dict:
        return {
            "decisions_used": self.decisions,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "recent_observations": [o.to_dict() for o in self.observations],
            "info_requests": list(self.info_requests),
            "stop_rationale": self.stop_rationale,
            "decision_log": list(self.decision_log),
            "consecutive_errors": self.consecutive_errors,
            "stagnation_notice": self.stagnation_notice,
        }

    def to_checkpoint(self) -> dict:
        """Snapshot complet pour persistance (ADR-15) — restauration exacte."""
        return {
            "decisions_used": self.decisions,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "recent_observations": [o.to_dict() for o in self.observations],
            "info_requests": list(self.info_requests),
            "stop_rationale": self.stop_rationale,
            "decision_log": list(self.decision_log),
            "consecutive_errors": self.consecutive_errors,
        }

    @classmethod
    def from_checkpoint(cls, state: dict) -> "InvestigationState":
        st = cls()
        st.decisions = int(state.get("decisions_used") or 0)
        st.hypotheses = [
            Hypothesis(id=h.get("id", "?"), statement=h.get("statement", ""),
                       status=h.get("status", "open"), evidence_refs=list(h.get("evidence_refs", [])))
            for h in state.get("hypotheses", []) if isinstance(h, dict)
        ]
        for o in state.get("recent_observations", []):
            if isinstance(o, dict):
                st.observations.append(Observation(
                    kind=o.get("kind", "tool"), tool=o.get("tool", "?"),
                    status=o.get("status", "?"), text=o.get("text", ""),
                    evidence_ids=list(o.get("evidence_ids", [])),
                ))
        st.info_requests = list(state.get("info_requests", []))
        st.stop_rationale = state.get("stop_rationale")
        st.decision_log = list(state.get("decision_log", []))
        st.consecutive_errors = int(state.get("consecutive_errors") or 0)
        return st


def investigation_request(
    objective: str,
    controls: list[dict],
    capabilities: list[dict],
    evidence_summaries: list[dict],
    state: InvestigationState,
    remaining_tool_calls: int,
    remaining_decisions: int,
    sources: list[dict] | None = None,
) -> str:
    """Requête de décision : le LLM choisit la prochaine action sur observations réelles."""
    exact_tools = sorted({c["tool"] for c in capabilities})
    payload = {
        "objective": objective,
        "controls": controls,
        "sources": sources or [],
        "capabilities": [
            {"tool": c["tool"], "source_id": c.get("source_id"), "schema": c.get("schema"),
             "permission": c.get("permission")}
            for c in capabilities
        ],
        "evidence_summaries": evidence_summaries,
        "investigation_state": state.to_payload(),
        "remaining_tool_calls": remaining_tool_calls,
        "remaining_decisions": remaining_decisions,
    }
    return (
        "TASK: decide_next_action\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n"
        "Tu es en BOUCLE D'INVESTIGATION : à chaque tour tu observes les preuves collectées et tu "
        "choisis UNE action. Utilise `call_tool` pour tester une hypothèse (tool copiée MOT POUR MOT "
        f"depuis: [{', '.join(exact_tools)}]; args conformes au `schema`, source_id exact). Pour les "
        "sources api, `sources` liste les endpoints APPROUVÉS (certains ont un path paramétré "
        "`{param}` : passe la valeur via filters). Une tool refusée ou en erreur est une observation "
        "normale — adapte-toi au lieu d'insister. Si remaining_tool_calls vaut 0 : consigne tes "
        "conclusions (update_hypotheses) puis stop — tout nouvel appel requiert une extension de "
        "budget approuvée par l'auditeur. Utilise `update_hypotheses` pour consigner une "
        "hypothèse ou la réviser (status open|supported|rejected|inconclusive, evidence_refs REELS "
        "seulement). " + CHALLENGER_CONSIGNES + " `stop` quand les preuves suffisantes sont collectées OU que le budget est "
        "presque épuisé OU qu'aucune investigation utile reste possible (stop_rationale obligatoire). "
        "Un constat s'appuiera sur ces preuves : si un détail précis manque (lignes d'un écart, "
        "enregistrement référencé par une liste, extrait d'une violation), préfère get_evidence_excerpt, "
        "evidence_search ou un appel api dépendant avant stop. `request_human_input` si une information "
        "hors de ta portée bloque l'investigation (non bloquant).\n"
        "Principe de vérification temporelle (général) : une observation d'échec ou d'anomalie peut "
        "être TRANSITOIRE. Si un endpoint ou une observation échoue (erreur HTTP 5xx, timeout) sans "
        "preuve d'une cause permanente, une RE-VÉRIFICATION bornée (UNE fois, en lecture seule, "
        "gate et budget inchangés) apporte une information réelle : même résultat plus tard → "
        "hypothèse « persistant » renforcée ; résultat différent → révise l'hypothèse (ex. "
        "« intermittent ») et cite les DEUX observations avec leurs tours. Si la re-vérification "
        "est impossible (budget, permission), conclue avec l'incertitude explicite au lieu d'affirmer.\n"
        f"Réponds en JSON strict: {json.dumps(DECISION_SCHEMA, ensure_ascii=False)}"
    )


def parse_decision(raw: dict) -> dict:
    """Normalise la décision brute du modèle en action sûre (jamais d'exception)."""
    if not isinstance(raw, dict):
        return {"decision": "stop", "stop_rationale": "décision illisible (payload non-JSON)", "hypotheses": []}
    kind = str(raw.get("decision") or "").strip()
    if kind not in DECISION_KINDS:
        # Décision absente/incorrecte : interprétation prudente = arrêt explicite, pas d'action.
        return {
            "decision": "stop",
            "stop_rationale": f"décision illisible ({kind!r}) — arrêt prudent de la boucle",
            "rationale": str(raw.get("rationale") or ""),
            "hypotheses": raw.get("hypotheses") if isinstance(raw.get("hypotheses"), list) else [],
        }
    out = {
        "decision": kind,
        "rationale": str(raw.get("rationale") or ""),
        "hypotheses": [h for h in raw.get("hypotheses", []) if isinstance(h, dict)] if isinstance(raw.get("hypotheses"), list) else [],
    }
    if kind == "call_tool":
        out["tool"] = str(raw.get("tool") or "").strip()
        out["source_id"] = raw.get("source_id") or None
        out["args"] = raw.get("args") if isinstance(raw.get("args"), dict) else {}
        if not out["tool"]:
            out["decision"] = "stop"
            out["stop_rationale"] = "call_tool sans nom de tool — arrêt prudent"
    elif kind == "stop":
        out["stop_rationale"] = str(raw.get("stop_rationale") or "arrêt sans rationale explicite")
    elif kind == "request_human_input":
        out["info_request"] = str(raw.get("info_request") or "").strip()[:1000]
    return out
