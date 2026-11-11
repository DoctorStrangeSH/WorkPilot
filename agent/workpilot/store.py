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

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );

                CREATE TABLE IF NOT EXISTS browser_tabs (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    shared_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_browser_tabs_shared
                    ON browser_tabs(shared_at DESC);

                CREATE INDEX IF NOT EXISTS idx_tasks_created
                    ON tasks(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_created
                    ON events(created_at DESC);
                """
            )

    def create_task(self, title: str, description: str = "") -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        now = _now()
        with self._session() as db:
            db.execute(
                """INSERT INTO tasks
                   (id, title, description, status, created_at, updated_at)
                   VALUES (?, ?, ?, 'pending', ?, ?)""",
                (task_id, title, description, now, now),
            )
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
