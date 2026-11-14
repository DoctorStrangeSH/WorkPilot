"""SQLite persistence for tasks and an append-only activity log."""

from __future__ import annotations

import sqlite3
import time
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

                CREATE TABLE IF NOT EXISTS browser_audit_job (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    job_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed','expired')),
                    created_at TEXT NOT NULL,
                    created_unix REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS browser_audit_progress (
                    id INTEGER PRIMARY KEY CHECK (id=1),
                    job_id TEXT NOT NULL,
                    current_role TEXT,
                    completed_sources INTEGER NOT NULL DEFAULT 0,
                    attention_sources INTEGER NOT NULL DEFAULT 0,
                    failed_role TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS browser_audit_seed (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    job_id TEXT NOT NULL,
                    cargo_place TEXT NOT NULL,
                    inventory_date TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS browser_audit_seed_items (
                    job_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    cargo_place TEXT NOT NULL,
                    inventory_date TEXT NOT NULL,
                    PRIMARY KEY(job_id, position),
                    UNIQUE(job_id, cargo_place)
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

    def delete_browser_tab(self, tab_id: str) -> bool:
        """Remove a user-shared tab record without closing the real browser tab."""
        if not isinstance(tab_id, str) or not tab_id or len(tab_id) > 64:
            return False
        with self._session() as db:
            cursor = db.execute("DELETE FROM browser_tabs WHERE id = ?", (tab_id,))
            if cursor.rowcount:
                db.execute(
                    """INSERT INTO events (task_id, event_type, message, created_at)
                       VALUES (NULL, 'browser.tab_unshared',
                               'Пользователь удалил переданную вкладку из Malenia', ?)""",
                    (_now(),),
                )
                return True
        return False

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

    def _expire_browser_audit(self, db: sqlite3.Connection) -> None:
        # Never leave a job indefinitely stuck after the extension crashes.
        now = time.time()
        db.execute(
            """UPDATE browser_audit_job SET status='expired', updated_at=?
               WHERE id=1 AND ((status='pending' AND created_unix < ?)
                  OR (status='running' AND created_unix < ?))""",
            (_now(), now - 900, now - 1800),
        )
        db.execute("DELETE FROM browser_audit_seed WHERE job_id NOT IN "
                   "(SELECT job_id FROM browser_audit_job WHERE status='pending')")
        db.execute("DELETE FROM browser_audit_seed_items WHERE job_id NOT IN "
                   "(SELECT job_id FROM browser_audit_job WHERE status='pending')")

    def latest_browser_audit_job(self) -> dict[str, Any] | None:
        with self._session() as db:
            self._expire_browser_audit(db)
            row = db.execute(
                """SELECT j.job_id,j.status,j.created_at,j.updated_at,
                          p.current_role,p.completed_sources,p.attention_sources,p.failed_role
                   FROM browser_audit_job j LEFT JOIN browser_audit_progress p
                   ON p.id=1 AND p.job_id=j.job_id WHERE j.id=1"""
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["completed_sources"] = result["completed_sources"] or 0
        result["attention_sources"] = result["attention_sources"] or 0
        return result

    def request_browser_audit(self, first_order: dict[str, str] | None = None,
                              batch: list[dict[str, str]] | None = None) -> dict[str, Any]:
        """Single bounded browser audit requested through the authenticated desktop API."""
        if first_order is not None and batch is not None:
            raise ValueError("invalid_audit_batch")
        selected = batch if batch is not None else ([first_order] if first_order is not None else [])
        if batch is not None and not 1 <= len(batch) <= 20:
            raise ValueError("invalid_audit_batch")
        seen = set()
        for order in selected:
            import re
            from datetime import date
            cargo = order.get("cargo_place") if isinstance(order, dict) else None
            cutoff = order.get("inventory_date") if isinstance(order, dict) else None
            if (not isinstance(cargo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", cargo)
                    or cargo in seen or not isinstance(cutoff, str) or len(cutoff) != 10):
                raise ValueError("invalid_audit_batch")
            seen.add(cargo)
            try:
                if date.fromisoformat(cutoff).isoformat() != cutoff:
                    raise ValueError("invalid_audit_batch")
            except ValueError as exc:
                raise ValueError("invalid_audit_batch") from exc
        with self._session() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire_browser_audit(db)
            active = db.execute(
                "SELECT status FROM browser_audit_job WHERE id=1"
            ).fetchone()
            if active and active["status"] in {"pending", "running"}:
                raise SubmissionConflict("browser_audit_already_active")
            now = _now()
            job_id = str(uuid.uuid4())
            db.execute("DELETE FROM browser_audit_seed WHERE id=1")
            db.execute("DELETE FROM browser_audit_seed_items")
            db.execute(
                """INSERT INTO browser_audit_job
                   (id,job_id,status,created_at,created_unix,updated_at)
                   VALUES (1,?,'pending',?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                   job_id=excluded.job_id,status=excluded.status,
                   created_at=excluded.created_at,created_unix=excluded.created_unix,
                   updated_at=excluded.updated_at""",
                (job_id, now, time.time(), now),
            )
            db.execute(
                """INSERT INTO browser_audit_progress
                   (id,job_id,current_role,completed_sources,attention_sources,failed_role,updated_at)
                   VALUES (1,?,NULL,0,0,NULL,?)
                   ON CONFLICT(id) DO UPDATE SET
                   job_id=excluded.job_id,current_role=NULL,
                   completed_sources=0,attention_sources=0,failed_role=NULL,
                   updated_at=excluded.updated_at""",
                (job_id, now),
            )
            if first_order is not None:
                db.execute("INSERT INTO browser_audit_seed "
                           "(id,job_id,cargo_place,inventory_date) VALUES (1,?,?,?)",
                           (job_id, first_order["cargo_place"], first_order["inventory_date"]))
            elif batch is not None:
                db.executemany(
                    "INSERT INTO browser_audit_seed_items "
                    "(job_id,position,cargo_place,inventory_date) VALUES (?,?,?,?)",
                    [(job_id, position, item["cargo_place"], item["inventory_date"])
                     for position, item in enumerate(batch)])
        return {"job_id": job_id, "status": "pending", "created_at": now,
                "updated_at": now}

    def claim_browser_audit(self) -> dict[str, Any] | None:
        """Native host may atomically claim a pending desktop-requested job once."""
        with self._session() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire_browser_audit(db)
            row = db.execute(
                "SELECT job_id,created_at FROM browser_audit_job "
                "WHERE id=1 AND status='pending'"
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE browser_audit_job SET status='running',updated_at=? WHERE id=1",
                (_now(),),
            )
            seed = db.execute("SELECT cargo_place,inventory_date FROM browser_audit_seed "
                              "WHERE id=1 AND job_id=?", (row["job_id"],)).fetchone()
            items = db.execute("SELECT cargo_place,inventory_date FROM browser_audit_seed_items "
                               "WHERE job_id=? ORDER BY position", (row["job_id"],)).fetchall()
            db.execute("DELETE FROM browser_audit_seed WHERE id=1")
            db.execute("DELETE FROM browser_audit_seed_items WHERE job_id=?", (row["job_id"],))
        result = {"job_id": row["job_id"], "status": "running"}
        if items:
            result["inventory"] = {"columns": ["cargo_place", "inventory_date"],
                                   "rows": [[item["cargo_place"], item["inventory_date"]]
                                            for item in items]}
        elif seed:
            result["inventory"] = {"columns": ["cargo_place", "inventory_date"],
                                   "rows": [[seed["cargo_place"], seed["inventory_date"]]]}
        return result

    def finish_browser_audit(self, job_id: str, succeeded: bool) -> bool:
        if (not isinstance(job_id, str) or len(job_id) != 36
                or not isinstance(succeeded, bool)):
            return False
        with self._session() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire_browser_audit(db)
            cursor = db.execute(
                """UPDATE browser_audit_job SET status=?,updated_at=?
                   WHERE id=1 AND job_id=? AND status='running'""",
                ("completed" if succeeded else "failed", _now(), job_id),
            )
            return cursor.rowcount == 1

    def update_browser_audit_progress(
        self, job_id: str, current_role: str | None, completed_sources: int,
        attention_sources: int, failed_role: str | None,
    ) -> bool:
        """Accept only coarse progress from the active claimed job.

        No URLs, codes, source rows, snippets or browser exceptions are stored.
        """
        roles = {"inventory", "datalens", "asgard"}
        if (not isinstance(job_id, str) or len(job_id) != 36
                or current_role not in roles | {None}
                or failed_role not in roles | {None}
                or type(completed_sources) is not int or
                type(attention_sources) is not int or
                not 0 <= attention_sources <= completed_sources <= 3):
            return False
        with self._session() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire_browser_audit(db)
            active = db.execute(
                "SELECT job_id,status FROM browser_audit_job WHERE id=1"
            ).fetchone()
            if active is None or active["job_id"] != job_id or active["status"] != "running":
                return False
            prior = db.execute(
                "SELECT completed_sources,attention_sources FROM browser_audit_progress "
                "WHERE id=1 AND job_id=?", (job_id,),
            ).fetchone()
            if prior is None or completed_sources < prior["completed_sources"] or (
                attention_sources < prior["attention_sources"]):
                return False
            db.execute(
                """UPDATE browser_audit_progress
                   SET current_role=?,completed_sources=?,attention_sources=?,
                       failed_role=?,updated_at=?
                   WHERE id=1 AND job_id=?""",
                (current_role, completed_sources, attention_sources,
                 failed_role, _now(), job_id),
            )
        return True
