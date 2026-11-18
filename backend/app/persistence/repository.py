"""Repository : sérialisation JSON <-> modèles, scoping workspace (docs/13)."""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel

from ..models import (
    Assessment,
    ChatMessage,
    ChatRole,
    ConversationStatus,
    ConversationThread,
    AuditMission,
    AuditRun,
    InvestigationCheckpoint,
    Evidence,
    FindingCandidate,
    MissionLimits,
    ReportSnapshot,
    RunEvent,
    SourceConnection,
    ToolCallRecord,
)
from ..models.schemas import utcnow
from .database import Database

T = TypeVar("T", bound=BaseModel)


def _dump(model: BaseModel) -> str:
    return model.model_dump_json()


def _loads(data: str | None, cls: type[T], default: T | None = None) -> T | None:
    if data is None:
        return default
    return cls.model_validate_json(data)


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # ---------- Sources ----------
    async def create_source(self, s: SourceConnection) -> None:
        await self.db.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?)",
            (s.id, s.workspace_id, s.name, s.type.value, json.dumps(s.config), s.secrets_ref,
             s.status.value, s.last_test_at, s.last_test_message, s.created_at),
        )

    async def get_source(self, source_id: str, workspace_id: str = "ws_default") -> SourceConnection | None:
        row = await self.db.query_one(
            "SELECT * FROM sources WHERE id=? AND workspace_id=?", (source_id, workspace_id)
        )
        if not row:
            return None
        return SourceConnection(
            id=row["id"], workspace_id=row["workspace_id"], name=row["name"],
            type=row["type"], config=json.loads(row["config"]), secrets_ref=row["secrets_ref"],
            status=row["status"], last_test_at=row["last_test_at"],
            last_test_message=row["last_test_message"], created_at=row["created_at"],
        )

    async def list_sources(self, workspace_id: str = "ws_default") -> list[SourceConnection]:
        rows = await self.db.query_all(
            "SELECT * FROM sources WHERE workspace_id=? ORDER BY created_at DESC", (workspace_id,)
        )
        return [
            SourceConnection(
                id=r["id"], workspace_id=r["workspace_id"], name=r["name"], type=r["type"],
                config=json.loads(r["config"]), secrets_ref=r["secrets_ref"], status=r["status"],
                last_test_at=r["last_test_at"], last_test_message=r["last_test_message"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def update_source_status(
        self, source_id: str, status: str, message: str | None, at: str
    ) -> None:
        await self.db.execute(
            "UPDATE sources SET status=?, last_test_at=?, last_test_message=? WHERE id=?",
            (status, at, message, source_id),
        )

    async def delete_source(self, source_id: str) -> None:
        await self.db.execute("DELETE FROM sources WHERE id=?", (source_id,))

    # ---------- Missions ----------
    async def create_mission(self, m: AuditMission) -> None:
        await self.db.execute(
            "INSERT INTO missions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (m.id, m.workspace_id, m.title, m.objective, json.dumps(m.source_ids),
             json.dumps(m.control_ids), json.dumps(m.time_range), m.limits.model_dump_json(),
             m.status.value, json.dumps(m.approved_plan) if m.approved_plan else None, m.created_at),
        )

    async def get_mission(self, mission_id: str, workspace_id: str = "ws_default") -> AuditMission | None:
        row = await self.db.query_one(
            "SELECT * FROM missions WHERE id=? AND workspace_id=?", (mission_id, workspace_id)
        )
        if not row:
            return None
        return AuditMission(
            id=row["id"], workspace_id=row["workspace_id"], title=row["title"],
            objective=row["objective"], source_ids=json.loads(row["source_ids"]),
            control_ids=json.loads(row["control_ids"]), time_range=json.loads(row["time_range"]),
            limits=MissionLimits.model_validate_json(row["limits"]),
            status=row["status"],
            approved_plan=json.loads(row["approved_plan"]) if row["approved_plan"] else None,
            created_at=row["created_at"],
        )

    async def list_missions(self, workspace_id: str = "ws_default") -> list[AuditMission]:
        rows = await self.db.query_all(
            "SELECT * FROM missions WHERE workspace_id=? ORDER BY created_at DESC", (workspace_id,)
        )
        out = []
        for r in rows:
            out.append(AuditMission(
                id=r["id"], workspace_id=r["workspace_id"], title=r["title"], objective=r["objective"],
                source_ids=json.loads(r["source_ids"]), control_ids=json.loads(r["control_ids"]),
                time_range=json.loads(r["time_range"]),
                limits=MissionLimits.model_validate_json(r["limits"]),
                status=r["status"],
                approved_plan=json.loads(r["approved_plan"]) if r["approved_plan"] else None,
                created_at=r["created_at"],
            ))
        return out

    async def update_mission(self, m: AuditMission) -> None:
        await self.db.execute(
            "UPDATE missions SET status=?, approved_plan=?, control_ids=?, source_ids=?, time_range=?, limits=? WHERE id=?",
            (m.status.value,
             json.dumps(m.approved_plan) if m.approved_plan else None,
             json.dumps(m.control_ids), json.dumps(m.source_ids), json.dumps(m.time_range),
             m.limits.model_dump_json(), m.id),
        )

    # ---------- Runs ----------
    async def create_run(self, r: AuditRun) -> None:
        await self.db.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (r.id, r.mission_id, r.status.value, r.provider_id, r.model_id, r.prompt_version,
             r.tool_calls_used, r.input_chars_used, r.started_at, r.finished_at, r.stop_reason, r.error),
        )

    async def update_run(self, r: AuditRun) -> None:
        await self.db.execute(
            "UPDATE runs SET status=?, tool_calls_used=?, input_chars_used=?, started_at=?, finished_at=?, stop_reason=?, error=? WHERE id=?",
            (r.status.value, r.tool_calls_used, r.input_chars_used, r.started_at, r.finished_at,
             r.stop_reason, r.error, r.id),
        )

    async def get_run(self, run_id: str) -> AuditRun | None:
        row = await self.db.query_one("SELECT * FROM runs WHERE id=?", (run_id,))
        if not row:
            return None
        return AuditRun(
            id=row["id"], mission_id=row["mission_id"], status=row["status"],
            provider_id=row["provider_id"], model_id=row["model_id"],
            prompt_version=row["prompt_version"], tool_calls_used=row["tool_calls_used"],
            input_chars_used=row["input_chars_used"], started_at=row["started_at"],
            finished_at=row["finished_at"], stop_reason=row["stop_reason"], error=row["error"],
        )

    async def list_runs(self, mission_id: str | None = None) -> list[AuditRun]:
        if mission_id:
            rows = await self.db.query_all(
                "SELECT * FROM runs WHERE mission_id=? ORDER BY started_at DESC", (mission_id,)
            )
        else:
            rows = await self.db.query_all("SELECT * FROM runs ORDER BY started_at DESC")
        return [
            AuditRun(
                id=r["id"], mission_id=r["mission_id"], status=r["status"],
                provider_id=r["provider_id"], model_id=r["model_id"], prompt_version=r["prompt_version"],
                tool_calls_used=r["tool_calls_used"], input_chars_used=r["input_chars_used"],
                started_at=r["started_at"], finished_at=r["finished_at"],
                stop_reason=r["stop_reason"], error=r["error"],
            )
            for r in rows
        ]

    # ---------- Tool calls ----------
    async def create_tool_call(self, t: ToolCallRecord) -> None:
        await self.db.execute(
            "INSERT INTO tool_calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (t.id, t.run_id, t.mission_id, t.name, t.source_id, json.dumps(t.args), t.status,
             t.latency_ms, t.observed_at, json.dumps(t.evidence_ids), json.dumps(t.warnings), t.error),
        )

    async def list_tool_calls(self, run_id: str) -> list[ToolCallRecord]:
        rows = await self.db.query_all(
            "SELECT * FROM tool_calls WHERE run_id=? ORDER BY observed_at, id", (run_id,)
        )
        return [
            ToolCallRecord(
                id=r["id"], run_id=r["run_id"], mission_id=r["mission_id"], name=r["name"],
                source_id=r["source_id"], args=json.loads(r["args"]), status=r["status"],
                latency_ms=r["latency_ms"], observed_at=r["observed_at"],
                evidence_ids=json.loads(r["evidence_ids"]), warnings=json.loads(r["warnings"]),
                error=r["error"],
            )
            for r in rows
        ]

    # ---------- Evidence (métadonnées ; payload dans le Evidence Store) ----------
    async def create_evidence_meta(self, e: Evidence) -> None:
        await self.db.execute(
            "INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (e.id, e.mission_id, e.run_id, e.source_id, e.type, e.title, e.observed_at,
             json.dumps(e.provenance), e.checksum, e.storage_ref, e.record_count,
             json.dumps(e.summary) if e.summary else None),
        )

    async def get_evidence_meta(self, evidence_id: str, mission_id: str) -> Evidence | None:
        row = await self.db.query_one(
            "SELECT * FROM evidence WHERE id=? AND mission_id=?", (evidence_id, mission_id)
        )
        if not row:
            return None
        return Evidence(
            id=row["id"], mission_id=row["mission_id"], run_id=row["run_id"],
            source_id=row["source_id"], type=row["type"], title=row["title"],
            observed_at=row["observed_at"], provenance=json.loads(row["provenance"]),
            checksum=row["checksum"], storage_ref=row["storage_ref"],
            record_count=row["record_count"],
            summary=json.loads(row["summary"]) if row["summary"] else None,
        )

    async def list_evidence(self, run_id: str | None = None, mission_id: str | None = None) -> list[Evidence]:
        if run_id:
            rows = await self.db.query_all(
                "SELECT * FROM evidence WHERE run_id=? ORDER BY observed_at, id", (run_id,)
            )
        elif mission_id:
            rows = await self.db.query_all(
                "SELECT * FROM evidence WHERE mission_id=? ORDER BY observed_at, id", (mission_id,)
            )
        else:
            rows = await self.db.query_all("SELECT * FROM evidence ORDER BY observed_at, id")
        return [
            Evidence(
                id=r["id"], mission_id=r["mission_id"], run_id=r["run_id"], source_id=r["source_id"],
                type=r["type"], title=r["title"], observed_at=r["observed_at"],
                provenance=json.loads(r["provenance"]), checksum=r["checksum"],
                storage_ref=r["storage_ref"], record_count=r["record_count"],
                summary=json.loads(r["summary"]) if r["summary"] else None,
            )
            for r in rows
        ]

    # ---------- Assessments ----------
    async def create_assessment(self, a: Assessment) -> None:
        await self.db.execute(
            "INSERT INTO assessments VALUES (?,?,?,?,?,?,?,?,?,?)",
            (a.id, a.run_id, a.mission_id, a.control_id, a.criterion_version, a.result.value,
             json.dumps(a.evidence_refs), json.dumps(a.observations), a.method,
             json.dumps(a.limitations)),
        )

    async def list_assessments(self, run_id: str) -> list[Assessment]:
        rows = await self.db.query_all(
            "SELECT * FROM assessments WHERE run_id=? ORDER BY control_id", (run_id,)
        )
        return [
            Assessment(
                id=r["id"], run_id=r["run_id"], mission_id=r["mission_id"], control_id=r["control_id"],
                criterion_version=r["criterion_version"], result=r["result"],
                evidence_refs=json.loads(r["evidence_refs"]), observations=json.loads(r["observations"]),
                method=r["method"], limitations=json.loads(r["limitations"]),
            )
            for r in rows
        ]

    # ---------- Findings ----------
    async def create_finding(self, f: FindingCandidate) -> None:
        await self.db.execute(
            "INSERT INTO findings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f.id, f.run_id, f.mission_id, f.control_id, f.title, f.statement,
             f.severity_proposed.value, json.dumps(f.evidence_refs), json.dumps(f.observations),
             f.method, json.dumps(f.limitations), json.dumps(f.recommendations),
             json.dumps(f.uncertainties), f.status.value,
             f.review.model_dump_json() if f.review else None, f.rejection_reason, f.created_at),
        )

    async def update_finding(self, f: FindingCandidate) -> None:
        await self.db.execute(
            "UPDATE findings SET status=?, review=?, rejection_reason=? WHERE id=?",
            (f.status.value, f.review.model_dump_json() if f.review else None,
             f.rejection_reason, f.id),
        )

    async def get_finding(self, finding_id: str) -> FindingCandidate | None:
        row = await self.db.query_one("SELECT * FROM findings WHERE id=?", (finding_id,))
        return _row_to_finding(row) if row else None

    async def list_findings(self, run_id: str | None = None, mission_id: str | None = None) -> list[FindingCandidate]:
        if run_id:
            rows = await self.db.query_all("SELECT * FROM findings WHERE run_id=?", (run_id,))
        elif mission_id:
            rows = await self.db.query_all("SELECT * FROM findings WHERE mission_id=?", (mission_id,))
        else:
            rows = await self.db.query_all("SELECT * FROM findings")
        return [_row_to_finding(r) for r in rows]

    # ---------- Reports ----------
    async def list_reports(self) -> list[ReportSnapshot]:
        rows = await self.db.query_all("SELECT * FROM reports ORDER BY created_at DESC, version DESC")
        return [ReportSnapshot.model_validate_json(r["payload"]) for r in rows]

    async def find_thread_by_run(self, run_id: str) -> ConversationThread | None:
        like = f"%{run_id}%"
        rows = await self.db.query_all(
            "SELECT * FROM conversation_threads WHERE run_ids LIKE ? AND status!='deleted' LIMIT 1",
            (like,),
        )
        if not rows:
            return None
        return self._row_to_thread(rows[0])

    async def create_report(self, r: ReportSnapshot) -> None:
        await self.db.execute(
            "INSERT INTO reports VALUES (?,?,?,?,?,?)",
            (r.id, r.run_id, r.mission_id, r.version, r.created_at, r.model_dump_json()),
        )

    async def get_report(self, report_id: str) -> ReportSnapshot | None:
        row = await self.db.query_one("SELECT * FROM reports WHERE id=?", (report_id,))
        return _loads(row["payload"], ReportSnapshot) if row else None

    async def get_latest_report(self, run_id: str) -> ReportSnapshot | None:
        row = await self.db.query_one(
            "SELECT * FROM reports WHERE run_id=? ORDER BY version DESC LIMIT 1", (run_id,)
        )
        return _loads(row["payload"], ReportSnapshot) if row else None

    # ---------- Events ----------
    async def append_event(self, e: RunEvent) -> int:
        cur = await self.db.conn.execute(
            "INSERT INTO run_events (run_id, type, at, data) VALUES (?,?,?,?)",
            (e.run_id, e.type, e.at, json.dumps(e.data)),
        )
        await self.db.conn.commit()
        return cur.lastrowid or 0

    async def list_events(self, run_id: str, after_seq: int = 0) -> list[RunEvent]:
        rows = await self.db.query_all(
            "SELECT * FROM run_events WHERE run_id=? AND seq>? ORDER BY seq", (run_id, after_seq)
        )
        return [
            RunEvent(seq=r["seq"], run_id=r["run_id"], type=r["type"], at=r["at"],
                     data=json.loads(r["data"]))
            for r in rows
        ]

    # ---------------- Checkpoints d'investigation (ADR-15) ----------------

    async def create_checkpoint(self, cp: InvestigationCheckpoint) -> None:
        await self.db.conn.execute(
            "INSERT INTO investigation_checkpoints (id, run_id, mission_id, reason, state, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (cp.id, cp.run_id, cp.mission_id, cp.reason,
             json.dumps(cp.state, ensure_ascii=False), cp.created_at),
        )
        await self.db.conn.commit()

    async def latest_checkpoint(self, run_id: str) -> InvestigationCheckpoint | None:
        rows = await self.db.query_all(
            "SELECT * FROM investigation_checkpoints WHERE run_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (run_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return InvestigationCheckpoint(
            id=r["id"], run_id=r["run_id"], mission_id=r["mission_id"],
            reason=r["reason"], state=json.loads(r["state"]), created_at=r["created_at"],
        )

    # ---------------- Conversations (ADR-16, couche 1) ----------------

    async def create_thread(self, t: ConversationThread) -> None:
        await self.db.execute(
            "INSERT INTO conversation_threads (id, workspace_id, title, head_message_id, mission_ids, "
            "run_ids, context_summary, summary_upto_message_id, compacted_message_count, status, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (t.id, t.workspace_id, t.title, t.head_message_id, json.dumps(t.mission_ids),
             json.dumps(t.run_ids), t.context_summary, t.summary_upto_message_id,
             t.compacted_message_count, t.status.value, t.created_at, t.updated_at),
        )

    async def get_thread(self, thread_id: str, workspace_id: str = "ws_default") -> ConversationThread | None:
        rows = await self.db.query_all(
            "SELECT * FROM conversation_threads WHERE id=? AND workspace_id=?", (thread_id, workspace_id),
        )
        if not rows:
            return None
        return self._row_to_thread(rows[0])

    async def list_threads(self, workspace_id: str = "ws_default", include_archived: bool = True) -> list[ConversationThread]:
        sql = "SELECT * FROM conversation_threads WHERE workspace_id=? AND status!='deleted' ORDER BY updated_at DESC"
        rows = await self.db.query_all(sql, (workspace_id,))
        threads = [self._row_to_thread(r) for r in rows]
        if not include_archived:
            threads = [t for t in threads if t.status.value == "active"]
        return threads

    async def update_thread(self, t: ConversationThread) -> None:
        await self.db.execute(
            "UPDATE conversation_threads SET title=?, head_message_id=?, mission_ids=?, run_ids=?, "
            "context_summary=?, summary_upto_message_id=?, compacted_message_count=?, status=?, updated_at=? "
            "WHERE id=?",
            (t.title, t.head_message_id, json.dumps(t.mission_ids), json.dumps(t.run_ids),
             t.context_summary, t.summary_upto_message_id, t.compacted_message_count,
             t.status.value, utcnow(), t.id),
        )

    def _row_to_thread(self, r: Any) -> ConversationThread:
        return ConversationThread(
            id=r["id"], workspace_id=r["workspace_id"], title=r["title"], pinned=bool(r["pinned"]),
            head_message_id=r["head_message_id"], mission_ids=json.loads(r["mission_ids"]),
            run_ids=json.loads(r["run_ids"]), context_summary=r["context_summary"],
            summary_upto_message_id=r["summary_upto_message_id"],
            compacted_message_count=int(r["compacted_message_count"] or 0),
            status=ConversationStatus(r["status"]), created_at=r["created_at"], updated_at=r["updated_at"],
        )

    async def create_chat_message(self, m: ChatMessage) -> None:
        await self.db.execute(
            "INSERT INTO chat_messages (id, thread_id, parent_id, role, parts, status, run_id, "
            "provider_id, model_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (m.id, m.thread_id, m.parent_id, m.role.value, json.dumps(m.parts, ensure_ascii=False),
             m.status, m.run_id, m.provider_id, m.model_id, m.created_at),
        )

    async def get_chat_message(self, message_id: str) -> ChatMessage | None:
        rows = await self.db.query_all("SELECT * FROM chat_messages WHERE id=?", (message_id,))
        if not rows:
            return None
        return self._row_to_chat_message(rows[0])

    async def update_chat_message(self, m: ChatMessage) -> None:
        await self.db.execute(
            "UPDATE chat_messages SET parts=?, status=?, run_id=?, provider_id=?, model_id=? WHERE id=?",
            (json.dumps(m.parts, ensure_ascii=False), m.status, m.run_id, m.provider_id, m.model_id, m.id),
        )

    async def list_thread_messages(self, thread_id: str) -> list[ChatMessage]:
        rows = await self.db.query_all(
            "SELECT * FROM chat_messages WHERE thread_id=? ORDER BY created_at, rowid", (thread_id,),
        )
        return [self._row_to_chat_message(r) for r in rows]

    async def search_thread_messages(self, thread_id: str, query: str, limit: int = 10) -> list[ChatMessage]:
        like = f"%{query}%"
        rows = await self.db.query_all(
            "SELECT * FROM chat_messages WHERE thread_id=? AND parts LIKE ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (thread_id, like, limit),
        )
        return [self._row_to_chat_message(r) for r in rows]

    def _row_to_chat_message(self, r: Any) -> ChatMessage:
        return ChatMessage(
            id=r["id"], thread_id=r["thread_id"], parent_id=r["parent_id"],
            role=ChatRole(r["role"]), parts=json.loads(r["parts"]), status=r["status"],
            run_id=r["run_id"], provider_id=r["provider_id"], model_id=r["model_id"],
            created_at=r["created_at"],
        )


def _row_to_finding(r: Any) -> FindingCandidate:
    review = None
    if r["review"]:
        from ..models import AuditorReview

        review = AuditorReview.model_validate_json(r["review"])
    return FindingCandidate(
        id=r["id"], run_id=r["run_id"], mission_id=r["mission_id"], control_id=r["control_id"],
        title=r["title"], statement=r["statement"], severity_proposed=r["severity_proposed"],
        evidence_refs=json.loads(r["evidence_refs"]), observations=json.loads(r["observations"]),
        method=r["method"], limitations=json.loads(r["limitations"]),
        recommendations=json.loads(r["recommendations"]), uncertainties=json.loads(r["uncertainties"]),
        status=r["status"], review=review, rejection_reason=r["rejection_reason"],
        created_at=r["created_at"],
    )
