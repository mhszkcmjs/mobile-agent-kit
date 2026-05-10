"""
SQLite 持久化层。PRD §10.1 四张表。

为简化 MVP,统一通过 Memory 类访问;不引 ORM。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from mobile_agent.config import cfg


_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts DATETIME DEFAULT CURRENT_TIMESTAMP,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    task_id TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    ts_start DATETIME NOT NULL,
    ts_end DATETIME,
    skill TEXT NOT NULL,
    args_json TEXT,
    status TEXT NOT NULL,            -- running / success / failed / cancelled
    summary TEXT,
    artifacts_dir TEXT
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts DATETIME DEFAULT CURRENT_TIMESTAMP,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL             -- user_explicit / agent_inferred
);

CREATE TABLE IF NOT EXISTS skills (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    args_schema_json TEXT,
    enabled INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_conv_ts ON conversations(ts);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, ts_start);
"""


class Memory:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or cfg.DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._mu = threading.RLock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        with self._mu:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    # ── conversations ────────────────────────────
    def append_message(self, role: str, content: str, task_id: str | None = None) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO conversations(role, content, task_id) VALUES (?, ?, ?)",
                (role, content, task_id),
            )

    def recent_messages(self, n: int = 20) -> list[dict[str, str]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, content FROM conversations ORDER BY id DESC LIMIT ?",
                (n,),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    # ── tasks ────────────────────────────────────
    def task_start(self, task_id: str, skill: str, args: dict, artifacts_dir: Path) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO tasks(id, ts_start, skill, args_json, status, artifacts_dir) "
                "VALUES (?, ?, ?, ?, 'running', ?)",
                (task_id, datetime.utcnow().isoformat(), skill,
                 json.dumps(args, ensure_ascii=False), str(artifacts_dir)),
            )

    def task_finish(self, task_id: str, status: str, summary: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE tasks SET ts_end=?, status=?, summary=? WHERE id=?",
                (datetime.utcnow().isoformat(), status, summary, task_id),
            )

    def last_success_task(self, skill: str | None = None) -> dict[str, Any] | None:
        with self._conn() as c:
            if skill:
                row = c.execute(
                    "SELECT * FROM tasks WHERE status='success' AND skill=? "
                    "ORDER BY ts_end DESC LIMIT 1",
                    (skill,),
                ).fetchone()
            else:
                row = c.execute(
                    "SELECT * FROM tasks WHERE status='success' ORDER BY ts_end DESC LIMIT 1"
                ).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("args_json"):
            try:
                d["args"] = json.loads(d["args_json"])
            except Exception:
                d["args"] = {}
        return d

    # ── facts ────────────────────────────────────
    def upsert_fact(self, key: str, value: str, source: str = "agent_inferred") -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO facts(key, value, source) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "source=excluded.source, ts=CURRENT_TIMESTAMP",
                (key, value, source),
            )

    def all_facts(self) -> dict[str, str]:
        with self._conn() as c:
            rows = c.execute("SELECT key, value FROM facts").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def delete_fact(self, key: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM facts WHERE key=?", (key,))

    # ── skills ───────────────────────────────────
    def sync_skills(self, items: list[dict]) -> None:
        with self._conn() as c:
            for s in items:
                c.execute(
                    "INSERT INTO skills(name, description, args_schema_json, enabled) "
                    "VALUES (?, ?, ?, 1) "
                    "ON CONFLICT(name) DO UPDATE SET "
                    "description=excluded.description, "
                    "args_schema_json=excluded.args_schema_json",
                    (s["name"], s["description"], json.dumps(s.get("args_schema", {}))),
                )


_singleton: Memory | None = None


def get_memory() -> Memory:
    global _singleton
    if _singleton is None:
        _singleton = Memory()
    return _singleton
