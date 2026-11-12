"""SQLite persistence for tasks and an append-only activity log."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SubmissionConflict(ValueError):
    pass


class TaskStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        """Commit/rollback a database operation and always release its file handle.

        sqlite3.Connection's context manager does not close the connection. Explicit
        closure is essential on Windows, where an open handle prevents temporary
        database directories from being removed and can block app shutdown.
        """
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._session() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK(status IN ('pending', 'cancelled')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS task_submissions (
                    request_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id)
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );

                CREATE TABLE IF NOT EXISTS browser_audit_summary (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    checked_at TEXT NOT NULL,
                    total INTEGER NOT NULL,
                    found INTEGER NOT NULL,
                    in_progress INTEGER NOT NULL,
                    manual_review INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS browser_tabs (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    shared_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS action_permissions (
                    id TEXT PRIMARY KEY,
                    binding TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                        ('pending', 'approved', 'denied', 'revoked', 'consumed', 'expired')),
                    expires_at REAL NOT NULL,
                    expires_monotonic REAL NOT NULL,
                    created_wall REAL NOT NULL,
                    created_monotonic REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_permissions_status_created
                    ON action_permissions(status, created_wall DESC);

                CREATE INDEX IF NOT EXISTS idx_browser_tabs_shared
                    ON browser_tabs(shared_at DESC);

                CREATE INDEX IF NOT EXISTS idx_tasks_created
                    ON tasks(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_created
                    ON events(created_at DESC);
                """
            )

    def create_task(self, title: str, description: str = "", request_id: str | None = None) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        now = _now()
        with self._session() as db:
            db.execute("BEGIN IMMEDIATE")
            if request_id is not None:
                uuid.UUID(request_id)
                existing = db.execute("SELECT tasks.* FROM task_submissions "
                    "JOIN tasks ON tasks.id = task_submissions.task_id WHERE request_id = ?",
                    (request_id,)).fetchone()
                if existing is not None:
                    if existing["title"] != title or existing["description"] != description:
                        raise SubmissionConflict("Request already submitted with different content")
                    return dict(existing)
            db.execute(
                """INSERT INTO tasks
                   (id, title, description, status, created_at, updated_at)
                   VALUES (?, ?, ?, 'pending', ?, ?)""",
                (task_id, title, description, now, now),
            )
            if request_id is not None:
                db.execute("INSERT INTO task_submissions VALUES (?, ?)", (request_id, task_id))
            db.execute(
                """INSERT INTO events
                   (task_id, event_type, message, created_at)
                   VALUES (?, 'task.created', 'Task added to the local queue', ?)""",
                (task_id, now),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._session() as db:
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self._session() as db:
            rows = db.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def cancel_task(self, task_id: str) -> dict[str, Any] | None:
        now = _now()
        with self._session() as db:
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            if row["status"] == "pending":
                db.execute(
                    "UPDATE tasks SET status = 'cancelled', updated_at = ? WHERE id = ?",
                    (now, task_id),
                )
                db.execute(
                    """INSERT INTO events
                       (task_id, event_type, message, created_at)
                       VALUES (?, 'task.cancelled', 'Pending task cancelled', ?)""",
                    (task_id, now),
                )
        return self.get_task(task_id)

    def list_events(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self._session() as db:
            rows = db.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (safe_limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def record_browser_tab(self, url: str, title: str) -> dict[str, Any]:
        """Persist a tab explicitly shared by the user through the browser extension."""
        tab_id = str(uuid.uuid4())
        now = _now()
        with self._session() as db:
            db.execute(
                "INSERT INTO browser_tabs (id, url, title, shared_at) VALUES (?, ?, ?, ?)",
                (tab_id, url, title, now),
            )
            db.execute(
                "DELETE FROM browser_tabs WHERE id NOT IN "
                "(SELECT id FROM browser_tabs ORDER BY shared_at DESC LIMIT 100)"
            )
            db.execute(
                """INSERT INTO events (task_id, event_type, message, created_at)
                   VALUES (NULL, 'browser.tab_shared',
                           'Пользователь поделился активной вкладкой', ?)""",
                (now,),
            )
        return {"id": tab_id, "url": url, "title": title, "shared_at": now}

    def list_browser_tabs(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self._session() as db:
            rows = db.execute(
                "SELECT * FROM browser_tabs ORDER BY shared_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_browser_audit_summary(self, total: int, summary: dict[str, int]) -> dict[str, Any]:
        """Persist only bounded aggregate counts, never cargo IDs or site contents."""
        keys = {"found", "in_progress", "manual_review"}
        if (type(total) is not int or not 0 <= total <= 100
                or type(summary) is not dict or set(summary) != keys
                or any(type(summary[k]) is not int or not 0 <= summary[k] <= total for k in keys)
                or sum(summary.values()) != total):
            raise ValueError("invalid_audit_summary")
        checked_at = _now()
        with self._session() as db:
            db.execute(
                """INSERT INTO browser_audit_summary
                   (id, checked_at, total, found, in_progress, manual_review)
                   VALUES (1, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                   checked_at=excluded.checked_at, total=excluded.total,
                   found=excluded.found, in_progress=excluded.in_progress,
                   manual_review=excluded.manual_review""",
                (checked_at, total, summary["found"], summary["in_progress"],
                 summary["manual_review"]),
            )
        return {"checked_at": checked_at, "total": total,
                "summary": dict(summary), "read_only": True, "source": "browser_tables"}

    def latest_browser_audit_summary(self) -> dict[str, Any] | None:
        with self._session() as db:
            row = db.execute(
                "SELECT checked_at, total, found, in_progress, manual_review "
                "FROM browser_audit_summary WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        return {"checked_at": row["checked_at"], "total": row["total"],
                "summary": {"found": row["found"], "in_progress": row["in_progress"],
                            "manual_review": row["manual_review"]},
                "read_only": True, "source": "browser_tables"}
