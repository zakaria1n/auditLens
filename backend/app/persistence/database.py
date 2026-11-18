"""Base SQLite locale (démo mono-utilisateur, docs/03). Colonnes complexes en JSON."""

from __future__ import annotations

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    config TEXT NOT NULL,
    secrets_ref TEXT,
    status TEXT NOT NULL,
    last_test_at TEXT,
    last_test_message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    source_ids TEXT NOT NULL,
    control_ids TEXT NOT NULL,
    time_range TEXT NOT NULL,
    limits TEXT NOT NULL,
    status TEXT NOT NULL,
    approved_plan TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    status TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    tool_calls_used INTEGER DEFAULT 0,
    input_chars_used INTEGER DEFAULT 0,
    started_at TEXT,
    finished_at TEXT,
    stop_reason TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    name TEXT NOT NULL,
    source_id TEXT,
    args TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms INTEGER,
    observed_at TEXT NOT NULL,
    evidence_ids TEXT NOT NULL,
    warnings TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    run_id TEXT,
    source_id TEXT,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    provenance TEXT NOT NULL,
    checksum TEXT NOT NULL,
    storage_ref TEXT NOT NULL,
    record_count INTEGER,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    control_id TEXT NOT NULL,
    criterion_version TEXT NOT NULL,
    result TEXT NOT NULL,
    evidence_refs TEXT NOT NULL,
    observations TEXT NOT NULL,
    method TEXT NOT NULL,
    limitations TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    control_id TEXT,
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    severity_proposed TEXT NOT NULL,
    evidence_refs TEXT NOT NULL,
    observations TEXT NOT NULL,
    method TEXT NOT NULL,
    limitations TEXT NOT NULL,
    recommendations TEXT NOT NULL,
    uncertainties TEXT NOT NULL,
    status TEXT NOT NULL,
    review TEXT,
    rejection_reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    type TEXT NOT NULL,
    at TEXT NOT NULL,
    data TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id, seq);

CREATE TABLE IF NOT EXISTS investigation_checkpoints (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON investigation_checkpoints(run_id, created_at);

CREATE TABLE IF NOT EXISTS conversation_threads (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    title TEXT NOT NULL,
    head_message_id TEXT,
    mission_ids TEXT NOT NULL,
    run_ids TEXT NOT NULL,
    context_summary TEXT,
    summary_upto_message_id TEXT,
    compacted_message_count INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    parent_id TEXT,
    role TEXT NOT NULL,
    parts TEXT NOT NULL,
    status TEXT NOT NULL,
    run_id TEXT,
    provider_id TEXT,
    model_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_thread ON chat_messages(thread_id, created_at);
"""


class Database:
    """Une connexion aiosqlite partagée, initialisée au démarrage de l'app."""

    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database non connectée")
        return self._conn

    async def execute(self, sql: str, params: tuple = ()) -> None:
        await self.conn.execute(sql, params)
        await self.conn.commit()

    async def query_all(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()
        return rows

    async def query_one(self, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
        cur = await self.conn.execute(sql, params)
        row = await cur.fetchone()
        await cur.close()
        return row
