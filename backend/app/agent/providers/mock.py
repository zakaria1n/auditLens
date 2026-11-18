"""MockLLMProvider : échanges Agent→tool mock→Agent scriptés, sans réseau (docs/10, docs/18 étape 0).

Scénarios déterministes pour tester le harness et la boucle bornée :
- `data_audit`      : plan standard fichier → profil → validation → findings fondés.
- `insufficient`    : l'agent déclare ne pas avoir assez de preuves (pas de findings).
- `unauthorized`    : le plan tente une tool hors périmètre → le Policy Gate doit bloquer.
- `hallucinated`    : findings avec une evidence inexistante → le validateur doit rejeter.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .base import LLMProvider, LLMResponse, ProviderToolCall


def _extract_task(messages: list[dict]) -> tuple[str, dict[str, Any]]:
    """Les prompts d'orchestrateur commencent par `TASK: <nom>` puis un payload JSON."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = str(msg.get("content", ""))
            match = re.match(r"\s*TASK:\s*(\w+)\s*\n(.*)", content, re.DOTALL)
            if match:
                task = match.group(1)
                payload = _extract_json(match.group(2))
                return task, payload
            return "unknown", {}
    return "unknown", {}


def _extract_json(content: str | None) -> dict:
    """Extrait le premier objet JSON valide du texte (tolère préambule/postambule)."""
    if not content:
        return {}
    idx = content.find("{")
    if idx == -1:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(content[idx:])
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


class MockLLMProvider(LLMProvider):
    provider_id = "mock"
    model_id = "mock-scripted-v1"

    def __init__(self, scenario: str = "data_audit"):
        self.scenario = scenario

    async def chat(self, system: str, messages: list[dict], tools=None) -> LLMResponse:
        if self.scenario == "chat":
            return self._chat_decide(system, messages, tools)
        task, payload = _extract_task(messages)
        total_chars = len(system) + sum(len(str(m.get("content", ""))) for m in messages)

        if task == "propose_plan":
            content = json.dumps(self._plan(payload))
        elif task == "decide_next_action":
            content = json.dumps(self._decide(payload))
        elif task == "propose_findings":
            content = json.dumps(self._findings(payload))
        else:
            content = json.dumps({"error": "tâche inconnue", "task": task})
        return LLMResponse(content=content, tool_calls=[], input_chars=total_chars)

    # ---------- conversation chat (scénario `chat`, ADR-16) ----------

    def _chat_decide(self, system: str, messages: list[dict], tools=None) -> LLMResponse:
        """Agent chat scripté, GÉNÉRIQUE : l'intention de la demande COURANTE décide ;
        le dernier résultat de tool ne sert qu'à formuler la réponse finale correspondante.
        Demande d'audit → list_sources puis create_audit (appel DÉPENDANT : ids issus du
        résultat réel de list_sources)."""
        total_chars = len(system) + sum(len(str(m.get("content", ""))) for m in messages)
        # le dernier tool ne compte que s'il appartient au tour COURANT (après la dernière
        # demande user) — sinon un 2e audit réutiliserait le résultat du tour précédent
        last_user_idx = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
        tool_msgs = [m for m in messages[last_user_idx + 1:] if m.get("role") == "tool"]
        last_tool = tool_msgs[-1] if tool_msgs else None
        user_texts = [str(m.get("content", "")) for m in messages if m.get("role") == "user"
                      and not str(m.get("content", "")).startswith("TASK:")]
        user_text = user_texts[-1] if user_texts else ""
        low = user_text.lower()
        n = len(tool_msgs) + 1

        def call(name: str, args: dict) -> LLMResponse:
            return LLMResponse(
                content=None,
                tool_calls=[ProviderToolCall(id=f"tc_chat_{n}", name=name, arguments=args)],
                input_chars=total_chars,
            )

        def tool_result() -> dict:
            if last_tool is None:
                return {}
            try:
                parsed = json.loads(str(last_tool.get("content", "")))
                return parsed if isinstance(parsed, dict) else {"raw": str(last_tool.get("content", ""))}
            except json.JSONDecodeError:
                return {"raw": str(last_tool.get("content", ""))}

        wants_audit = "audit" in low
        wants_status = "statut" in low or "run" in low
        wants_findings = "constat" in low or "finding" in low
        wants_sources = "source" in low

        if tools and wants_audit:
            if last_tool is not None and last_tool.get("name") == "list_sources":
                result = tool_result()
                sources = result.get("sources", [])
                if sources:
                    return call("create_audit", {
                        "source_ids": [s["id"] for s in sources if s.get("id")][:1],
                        "objective": user_text[:500],
                    })
                return LLMResponse(content="Aucune source connectée : configurez une source avant l'audit.",
                                   input_chars=total_chars)
            if last_tool is not None and last_tool.get("name") == "create_audit":
                result = tool_result()
                return LLMResponse(
                    content=(f"Audit lancé : mission {result.get('mission_id', '?')}, "
                             f"run {result.get('run_id', '?')}. L'exécution passe par le moteur "
                             "d'investigation existant (Policy Gate actif ; tests actifs non approuvés)."),
                    input_chars=total_chars,
                )
            return call("list_sources", {})

        if tools and wants_status:
            if last_tool is not None and last_tool.get("name") == "get_run_status":
                result = tool_result()
                stop = f", arrêt : {result.get('stop_reason')}" if result.get("stop_reason") else ""
                return LLMResponse(
                    content=(f"Run {result.get('run_id', '?')} : statut {result.get('status', '?')}{stop}, "
                             f"tools exécutées : {result.get('tool_calls_used', 0)}."),
                    input_chars=total_chars,
                )
            return call("get_run_status", {})

        if tools and wants_findings:
            if last_tool is not None and last_tool.get("name") == "get_findings":
                result = tool_result()
                findings = result.get("findings", [])
                titles = "; ".join(str(f.get("title", "?")) for f in findings[:3]) or "aucun constat"
                return LLMResponse(
                    content=(f"{len(findings)} constat(s) pour la mission {result.get('mission_id', '?')} : "
                             f"{titles}. Revue humaine requise avant toute conclusion publiée."),
                    input_chars=total_chars,
                )
            return call("get_findings", {})

        if tools and wants_sources:
            if last_tool is not None and last_tool.get("name") == "list_sources":
                result = tool_result()
                names = ", ".join(str(s.get("name", s.get("id", "?"))) for s in result.get("sources", [])) or "aucune"
                return LLMResponse(content=f"Sources connectées : {names}.", input_chars=total_chars)
            return call("list_sources", {})

        return LLMResponse(content=f"Réponse de l'assistant : {user_text[:300]}", input_chars=total_chars)

    # ---------- boucle d'investigation (décision par tour) ----------

    def _decide(self, payload: dict) -> dict:
        """Décision scriptée par tour, GÉNÉRIQUE (aucune réponse d'évaluation codée en dur).

        - scenarios de base (data_audit/insufficient/…): la couverture déterministe suffit
          → stop immédiat avec rationale (la boucle ne gaspille pas le budget).
        - scenario `investigate`: enquête générique — consigner une hypothèse, puis
          approfondir un enregistrement collecté (appel DÉPENDANT : endpoint paramétré
          trouvé dans les capabilities + identifiant issu des preuves réelles), réviser
          l'hypothèse selon l'observation, puis s'arrêter.
        - scenario `blocked`: tenter une tool hors périmètre (refus Policy Gate),
          consigner l'observation, puis s'arrêter (test de la boucle de feedback).
        """
        summaries = payload.get("evidence_summaries", [])
        state = payload.get("investigation_state") or {}
        capabilities = payload.get("capabilities", [])
        sources = payload.get("sources", [])
        used = int(state.get("decisions_used", 0))
        observations = state.get("recent_observations", [])
        hypotheses = state.get("hypotheses", [])
        remaining = int(payload.get("remaining_tool_calls", 0))

        if self.scenario in ("blocked",):
            if used == 0 and capabilities:
                cap = capabilities[0]
                return {
                    "decision": "call_tool",
                    "tool": "api_fetch_records",
                    "source_id": cap.get("source_id"),
                    "args": {"source_id": cap.get("source_id"), "endpoint_id": "hors_perimetre"},
                    "rationale": "Tenter une lecture hors périmètre (test de feedback sur refus Policy Gate).",
                    "hypotheses": [],
                }
            if used == 1:
                return {
                    "decision": "update_hypotheses",
                    "rationale": "Consigner le refus observé comme limitation.",
                    "hypotheses": [{
                        "id": "h_blocked",
                        "statement": "L'accès demandé est hors périmètre autorisé ; l'investigation se poursuit autrement.",
                        "status": "inconclusive",
                        "evidence_refs": [],
                    }],
                }
            return {"decision": "stop", "stop_rationale": "Refus Policy Gate observé et consigné — arrêt de l'investigation.", "hypotheses": []}

        if self.scenario == "long_investigate":
            # Investigation LONGUE (>6 décisions) : extraits à plages distinctes (aucune
            # répétition identique), révision, puis arrêt — prouve la continuité ADR-15.
            if used == 0:
                return {
                    "decision": "update_hypotheses",
                    "rationale": "Hypothèse de départ pour une investigation longue.",
                    "hypotheses": [{
                        "id": "h_long",
                        "statement": "Les preuves collectées doivent être examinées en détail avant conclusion.",
                        "status": "open",
                        "evidence_refs": [],
                    }],
                }
            if 1 <= used <= 7 and remaining > 0:
                for s in summaries:
                    if s.get("type") in ("record_set", "raw_file", "contract_check", "odoo_cross_check"):
                        return {
                            "decision": "call_tool",
                            "tool": "get_evidence_excerpt",
                            "source_id": None,
                            "args": {"evidence_id": s["id"], "row_start": used - 1, "row_end": used},
                            "rationale": f"Examen détaillé page {used} (plage distincte, investigation continue).",
                            "hypotheses": [],
                        }
            if used == 8:
                return {
                    "decision": "update_hypotheses",
                    "rationale": "Réviser après l'examen détaillé.",
                    "hypotheses": [{
                        "id": "h_long",
                        "statement": "Examen détaillé terminé : hypothèse révisée au vu des extraits.",
                        "status": "inconclusive",
                        "evidence_refs": [],
                    }],
                }
            return {
                "decision": "stop",
                "stop_rationale": "Investigation longue terminée volontairement : preuves suffisantes.",
                "hypotheses": [],
            }

        if self.scenario == "repeat_loop":
            # Répétition IDENTIQUE volontaire : doit déclencher le signal de stagnation
            # (ADR-15) puis, sans adaptation, la mise en pause par garde-fou.
            for s in summaries:
                if s.get("type") in ("record_set", "raw_file", "contract_check", "odoo_cross_check"):
                    return {
                        "decision": "call_tool",
                        "tool": "get_evidence_excerpt",
                        "source_id": None,
                        "args": {"evidence_id": s["id"], "row_start": 0, "row_end": 5},
                        "rationale": "Ré-examiner la même plage (test de stagnation).",
                        "hypotheses": [],
                    }
            return {"decision": "stop", "stop_rationale": "aucune preuve à répéter", "hypotheses": []}

        if self.scenario != "investigate":
            # Comportement historique : la couverture planifiée + réconciliation déterministe suffit.
            return {
                "decision": "stop",
                "stop_rationale": "Couverture déterministe planifiée suffisante ; aucune investigation supplémentaire nécessaire.",
                "hypotheses": [],
            }

        # ---- scenario `investigate` ----
        if used == 0:
            return {
                "decision": "update_hypotheses",
                "rationale": "Consigner l'hypothèse d'investigation de départ.",
                "hypotheses": [{
                    "id": "h_detail",
                    "statement": "Les enregistrements publiés par la source doivent être accessibles en détail et cohérents avec la liste.",
                    "status": "open",
                    "evidence_refs": [],
                }],
            }
        if used in (1, 2, 3) and remaining > 0:
            # Appels dépendants bornés : sonder jusqu'à 3 enregistrements échantillonnés
            # via un endpoint paramétré déclaré dans la source (jamais d'id deviné).
            probe_index = used - 1
            for src in sources:
                if src.get("type") != "api":
                    continue
                for ep in src.get("endpoints", []):
                    path = str(ep.get("path") or "")
                    if "{" not in path or "}" not in path:
                        continue
                    param = path[path.find("{") + 1:path.find("}")]
                    for s in summaries:
                        if s.get("type") != "record_set" or s.get("source_id") != src.get("source_id"):
                            continue
                        sample = (s.get("summary") or {}).get("sample") or []
                        values = []
                        for rec in sample:
                            if not isinstance(rec, dict):
                                continue
                            # Convention REST générique : param de path `x_id` → champ `x_id`
                            # ou, à défaut, champ `id` de l'enregistrement.
                            value = rec.get(param) if param in rec else (rec.get("id") if param.endswith("_id") else None)
                            if value is not None:
                                values.append(value)
                        if len(values) > probe_index:
                            value = values[probe_index]
                            return {
                                "decision": "call_tool",
                                "tool": "api_fetch_records",
                                "source_id": src.get("source_id"),
                                "args": {
                                    "source_id": src.get("source_id"),
                                    "endpoint_id": ep.get("id"),
                                    "filters": {param: str(value)},
                                },
                                "rationale": f"Sonder l'accessibilité du détail de l'enregistrement {value} (appel dépendant borné {probe_index + 1}/3).",
                                "hypotheses": [],
                            }
            # Pas d'endpoint paramétré : extrait de la première evidence d'enregistrements,
            # plage VARIEE à chaque tour (l'agent scripté n'est pas lui-même un cas de stagnation).
            for s in summaries:
                if s.get("type") in ("record_set", "raw_file", "contract_check", "odoo_cross_check"):
                    return {
                        "decision": "call_tool",
                        "tool": "get_evidence_excerpt",
                        "source_id": None,
                        "args": {"evidence_id": s["id"], "row_start": max(0, used - 2) * 5, "row_end": max(0, used - 2) * 5 + 5},
                        "rationale": f"Examiner une nouvelle plage de la preuve collectée (tour {used}).",
                        "hypotheses": [],
                    }
        if used == 4:
            last = observations[-1] if observations else None
            # Prudence docs/03 : « supported » seulement si l'observation montre du contenu
            # productif ; une erreur HTTP observée laisse l'hypothèse inconclusive (à signaler).
            productive = bool(last and last.get("status") == "success"
                              and "enregistrements=0" not in str(last.get("text", "")))
            status = "supported" if productive else "inconclusive"
            note = f"observation: {last.get('text', '')}" if last else "aucune observation"
            return {
                "decision": "update_hypotheses",
                "rationale": "Réviser l'hypothèse après l'observation recueillie.",
                "hypotheses": [{
                    "id": "h_detail",
                    "statement": f"Hypothèse révisée après investigation ({note}).",
                    "status": status,
                    "evidence_refs": [r for r in (last or {}).get("evidence_ids", []) if isinstance(r, str)] if last else [],
                }],
            }
        return {
            "decision": "stop",
            "stop_rationale": "Investigation bouclée : hypothèse testée et observations consignées.",
            "hypotheses": [],
        }

    # ---------- plan ----------
    def _plan(self, payload: dict) -> dict:
        sources = payload.get("sources", [])
        steps: list[dict] = []
        for src in sources:
            steps.append({
                "tool": "discover_source", "source_id": src["source_id"], "args": {"source_id": src["source_id"]},
                "rationale": "Vérifier la connexion et les capacités réelles avant toute collecte.",
            })
        if self.scenario == "unauthorized" and sources:
            # tentative délibérée : tool API sur une source fichier → doit être bloquée par le gate
            steps.append({
                "tool": "api_fetch_records", "source_id": sources[0]["source_id"],
                "args": {"source_id": sources[0]["source_id"], "endpoint_id": "orders"},
                "rationale": "Tenter une lecture hors type de source (test de policy).",
            })
        if self.scenario == "insufficient":
            return {"steps": steps, "evidence_expected": [], "risks": ["accès limité : l'agent s'arrêtera si les preuves manquent"]}
        for src in sources:
            if src.get("type") == "file":
                for ev_id in src.get("initial_evidence_ids", []):
                    steps.append({
                        "tool": "data_profile", "source_id": src["source_id"],
                        "args": {"evidence_id": ev_id},
                        "rationale": "Profiler le fichier importé (types, nulls, distributions).",
                    })
                    rule_set = src.get("rule_set_id") or "rs_orders_v1"
                    steps.append({
                        "tool": "data_validate", "source_id": src["source_id"],
                        "args": {"evidence_id": ev_id, "rule_set_id": rule_set},
                        "rationale": "Appliquer le Data Contract choisi par l'auditeur (règles déterministes).",
                    })
            elif src.get("type") == "odoo":
                dr = {"date_from": payload.get("time_range", {}).get("from"), "date_to": payload.get("time_range", {}).get("to")}
                for tool, label in [
                    ("odoo_read_orders", "commandes"),
                    ("odoo_read_invoices", "factures"),
                    ("odoo_read_stock", "stock"),
                    ("odoo_read_purchases", "achats"),
                ]:
                    args = {"source_id": src["source_id"], **{k: v for k, v in dr.items() if v}}
                    steps.append({"tool": tool, "source_id": src["source_id"], "args": args,
                                  "rationale": f"Collecter les {label} sur la période de mission (base de la réconciliation)."})
            elif src.get("type") == "api":
                for ep in src.get("endpoints", [])[:3]:
                    steps.append({"tool": "api_fetch_records", "source_id": src["source_id"],
                                  "args": {"source_id": src["source_id"], "endpoint_id": ep.get("id")},
                                  "rationale": "Lire les enregistrements d'un endpoint approuvé."})
            elif src.get("type") == "web":
                for j in src.get("journeys", [])[:2]:
                    steps.append({"tool": "web_run_journey", "source_id": src["source_id"],
                                  "args": {"source_id": src["source_id"], "journey_id": j.get("id")},
                                  "rationale": "Exécuter le parcours approuvé avec assertions."})
        return {
            "steps": steps,
            "evidence_expected": [f"preuves sourcées pour {c}" for c in payload.get("control_ids", [])],
            "risks": ["l'agent ne promet aucun résultat avant collecte"] if steps else ["aucune source: aucune collecte possible"],
        }

    # ---------- findings ----------
    def _findings(self, payload: dict) -> dict:
        summaries = payload.get("evidence_summaries", [])
        controls = payload.get("controls", [])
        findings: list[dict] = []

        validation_ev = next((s for s in summaries if s.get("type") == "validation"), None)
        contract_ev = next((s for s in summaries if s.get("type") == "contract_check"), None)
        web_ev = next((s for s in summaries if s.get("type") == "web_trace"), None)
        cross_ev = next((s for s in summaries if s.get("type") == "odoo_cross_check"), None)

        def control_for(prefix: str) -> str | None:
            for c in controls:
                if c.get("id", "").startswith(prefix):
                    return c["id"]
            return None

        if validation_ev and self.scenario != "insufficient":
            summary = validation_ev.get("summary", {})
            violations = summary.get("violation_count", 0)
            data_control = control_for("DATA-01")
            if violations and violations > 0:
                sample = (summary.get("violations_sample") or [])[:5]
                findings.append({
                    "control_id": data_control,
                    "title": "Violations du Data Contract détectées",
                    "statement": (
                        f"La validation déterministe du fichier a produit {violations} violation(s) "
                        f"sur {summary.get('rows')} lignes (jeu de règles {summary.get('rule_set_id')}). "
                        "Exemples: " + "; ".join(
                            f"{v.get('rule_type')}:{v.get('column')} ligne {v.get('row_index')}" for v in sample
                        )
                    ),
                    "severity_proposed": "medium" if violations < 10 else "high",
                    "evidence_refs": [validation_ev["id"]],
                    "observations": [
                        f"{v.get('rule_id')} ({v.get('rule_type')}) {v.get('column')}: {v.get('message')}"
                        for v in sample
                    ],
                    "method": "data_validate (règles déterministes) + lecture du profil",
                    "limitations": ["les violations déterministes n'établissent pas seules une non-conformité métier"],
                    "recommendations": ["vérifier les lignes concernées et le mapping du contrat de données"],
                    "uncertainties": ["plusieurs lignes par commande peuvent être légitimes selon le contrat (docs/09)"],
                })
            # données conformes : aucun finding — le déterminisme (assessment pass) suffit (docs/11)

        if self.scenario == "hallucinated":
            # finding supplémentaire avec evidence inexistante : le validateur doit le rejeter
            findings.append({
                "control_id": control_for("ERP-01"),
                "title": "Écart ERP détecté (constat halluciné de test)",
                "statement": "Écart facture/livraison constaté sur une écriture non collectée.",
                "severity_proposed": "high",
                "evidence_refs": ["ev_inexistant_9999"],
                "observations": [],
                "method": "corrélation non prouvée",
                "limitations": [],
                "recommendations": [],
                "uncertainties": [],
            })

        if cross_ev:
            summary = cross_ev.get("summary", {})
            confirmed = summary.get("confirmed", 0)
            suspicious = summary.get("suspicious", 0)
            refs = summary.get("source_evidence_ids", [])
            if confirmed > 0:
                violations = summary.get("violations", [])[:5]
                findings.append({
                    "control_id": control_for("ERP-02"),
                    "title": "Violations de réconciliation Odoo confirmées",
                    "statement": (
                        f"La réconciliation déterministe des preuves Odoo révèle {confirmed} violation(s) confirmée(s) "
                        f"(contradictions internes entre preuves collectées) et {suspicious} situation(s) à investiguer. "
                        + "Principales: " + "; ".join(
                            f"[{v.get('rule_id')}] {v.get('subject')}: {v.get('message')}" for v in violations[:3]
                        )
                    ),
                    "severity_proposed": "high" if any(v.get("severity_hint") == "high" for v in violations) else "medium",
                    "evidence_refs": refs,
                    "observations": [
                        f"{v.get('rule_id')} ({v.get('kind')}) {v.get('subject')}: {v.get('message')}"
                        for v in violations
                    ],
                    "method": "odoo_cross_check (réconciliation déterministe docs/11) + lectures Odoo",
                    "limitations": ["interprétation métier requise : distinguer erreur de saisie et fraude",
                                    "UoM multiples non converties dans la réconciliation"],
                    "recommendations": ["vérifier les mouvements cités dans Odoo et documenter l'écart"],
                    "uncertainties": ["les situations suspicious peuvent avoir des explications légitimes"],
                })
            elif suspicious > 0:
                findings.append({
                    "control_id": control_for("ERP-02"),
                    "title": "Situations Odoo à investiguer (aucune contradiction interne confirmée)",
                    "statement": f"{suspicious} situation(s) suspecte(s) détectée(s) par la réconciliation — livraisons partielles ou références à confirmer.",
                    "severity_proposed": "low",
                    "evidence_refs": refs,
                    "observations": [f"{v.get('rule_id')} {v.get('subject')}: {v.get('message')}"
                                     for v in summary.get("violations", [])[:5]],
                    "method": "odoo_cross_check",
                    "limitations": ["peut refléter des opérations légitimes (livraisons partielles, transferts)"],
                    "recommendations": [],
                    "uncertainties": [],
                })

        # Signal générique d'audit : toute trace HTTP en erreur (4xx/5xx) sur un endpoint
        # approuvé est un constat légitime, indépendamment de toute anomalie plantée.
        for s in summaries:
            if s.get("type") == "http_trace":
                http_status = (s.get("summary") or {}).get("http_status")
                if isinstance(http_status, int) and http_status >= 400:
                    findings.append({
                        "control_id": control_for("API-01"),
                        "title": "Endpoint approuvé en erreur HTTP",
                        "statement": f"Un endpoint approuvé répond HTTP {http_status} — comportement à confronter au contrat documenté.",
                        "severity_proposed": "medium",
                        "evidence_refs": [s["id"]],
                        "observations": [f"endpoint {s.get('summary', {}).get('endpoint_id')} → HTTP {http_status}"],
                        "method": "api_fetch_records (trace HTTP)",
                        "limitations": ["la qualification définitive requiert la comparaison au contrat"],
                        "recommendations": [],
                        "uncertainties": [],
                    })

        if contract_ev:
            summary = contract_ev.get("summary", {})
            checked, ok = summary.get("endpoints_checked", 0), summary.get("ok", 0)
            if checked > ok:
                findings.append({
                    "control_id": control_for("API-01"),
                    "title": "Endpoints API hors contrat",
                    "statement": f"{ok}/{checked} endpoints approuvés répondent conformément au contrat.",
                    "severity_proposed": "medium",
                    "evidence_refs": [contract_ev["id"]],
                    "observations": [f"{checked - ok} endpoint(s) en échec"],
                    "method": "api_inspect_contract",
                    "limitations": ["un test contractuel n'est pas un test de sécurité complet"],
                    "recommendations": ["vérifier les endpoints en échec et la version du schéma"],
                    "uncertainties": [],
                })

        # Parcours web : UN constat par parcours en échec (nom du parcours cité — docs/11).
        for s in summaries:
            if s.get("type") == "web_trace":
                summary = s.get("summary", {})
                if not summary.get("all_passed"):
                    findings.append({
                        "control_id": control_for("WEB-01"),
                        "title": "Parcours utilisateur en échec",
                        "statement": f"Le parcours « {s.get('title', '')} » échoue : "
                                     f"{summary.get('failed_steps')} étape(s) n'atteignent pas leurs assertions.",
                        "severity_proposed": "medium",
                        "evidence_refs": [s["id"]],
                        "observations": [
                            f"parcours {summary.get('journey_id')} : {summary.get('failed_steps')} étape(s) en échec",
                            f"{summary.get('console_errors')} erreur(s) console",
                        ],
                        "method": "web_run_journey (Playwright)",
                        "limitations": ["un test fonctionnel n'est pas un pentest"],
                        "recommendations": ["reproduire le parcours manuellement et vérifier l'environnement"],
                        "uncertainties": [],
                    })

        if self.scenario == "unauthorized":
            for f in findings:
                f["limitations"].append("tool api_fetch_records bloquée par le Policy Gate (hors type de source)")
            if not findings and validation_ev is None:
                findings.append({
                    "control_id": None,
                    "title": "Accès restreint — couverture partielle",
                    "statement": "Une tool demandée a été refusée par le backend (hors périmètre autorisé) ; l'investigation continue avec les tools autorisées.",
                    "severity_proposed": "low",
                    "evidence_refs": [],
                    "observations": ["api_fetch_records: unauthorized"],
                    "method": "refus Policy Gate journalisé",
                    "limitations": ["couverture partielle"],
                    "recommendations": ["étendre le périmètre si pertinent"],
                    "uncertainties": [],
                })

        return {"findings": findings}
