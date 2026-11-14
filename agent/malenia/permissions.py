"""One-shot permission gate; browser execution remains unimplemented."""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .store import TaskStore, _now

MAX_OPEN_PERMISSIONS = 100
MAX_TERMINAL_PERMISSIONS = 100


@dataclass(frozen=True)
class BrowserAction:
    capability: str
    session_id: str
    tab_id: int
    document_id: str
    parameters: dict[str, Any]

    def fingerprint(self) -> str:
        if self.capability not in {"browser.read_text", "browser.screenshot"}:
            raise ValueError("Unsupported capability")
        if not isinstance(self.session_id, str):
            raise ValueError("Invalid session")
        uuid.UUID(self.session_id)
        if type(self.tab_id) is not int or self.tab_id < 0:
            raise ValueError("Invalid tab")
        if not isinstance(self.document_id, str) or not self.document_id.strip() or len(self.document_id) > 256:
            raise ValueError("Invalid document")
        if not isinstance(self.parameters, dict):
            raise ValueError("Parameters must be an object")
        # JSON round trip excludes non-JSON types and non-string keys, avoiding
        # accidental collisions such as {1: value} and {"1": value}.
        try:
            encoded = json.dumps(self.parameters, sort_keys=True, allow_nan=False,
                                 separators=(",", ":"), ensure_ascii=True)
            if json.loads(encoded) != self.parameters:
                raise ValueError("Parameters must contain JSON values only")
            payload = json.dumps([self.capability, self.session_id, self.tab_id,
                                  self.document_id, encoded], separators=(",", ":"))
        except (TypeError, OverflowError, RecursionError) as exc:
            raise ValueError("Invalid parameters") from exc
        if len(payload.encode("utf-8")) > 8192:
            raise ValueError("Action too large")
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PermissionGate:
    def __init__(self, store: TaskStore, clock: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic):
        self.store = store
        self.clock = clock
        self.monotonic = monotonic

    def request(self, action: BrowserAction, ttl: int = 60) -> str:
        if type(ttl) is not int or not 1 <= ttl <= 300:
            raise ValueError("TTL must be between 1 and 300 seconds")
        binding = action.fingerprint()
        permission_id = str(uuid.uuid4())
        with self.store._session() as db:
            db.execute("BEGIN IMMEDIATE")
            now, elapsed = self._time()
            self._maintain(db, now, elapsed)
            count = db.execute("SELECT COUNT(*) FROM action_permissions "
                               "WHERE status IN ('pending', 'approved')").fetchone()[0]
            if count >= MAX_OPEN_PERMISSIONS:
                raise ValueError("Too many open permission requests")
            db.execute("""INSERT INTO action_permissions
                          (id, binding, capability, status, expires_at,
                           expires_monotonic, created_wall, created_monotonic)
                          VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)""",
                       (permission_id, binding, action.capability, now + ttl,
                        elapsed + ttl, now, elapsed))
            self._audit(db, "requested")
        return permission_id

    def decide(self, permission_id: str, action: BrowserAction, *, allow: bool) -> bool:
        if type(allow) is not bool:
            raise ValueError("Decision must be boolean")
        return self._transition(permission_id, action, ("pending",),
                                "approved" if allow else "denied")

    def revoke(self, permission_id: str, action: BrowserAction) -> bool:
        return self._transition(permission_id, action, ("pending", "approved"), "revoked")

    def consume(self, permission_id: str, action: BrowserAction) -> bool:
        """Commit permission use BEFORE dispatch; never retry uncertain delivery."""
        return self._transition(permission_id, action, ("approved",), "consumed")

    def _transition(self, permission_id, action, allowed, target):
        binding = action.fingerprint()
        with self.store._session() as db:
            # Serialize decisions/expiry/consumption across connections and processes.
            db.execute("BEGIN IMMEDIATE")
            now, elapsed = self._time()
            self._maintain(db, now, elapsed)
            row = db.execute("SELECT * FROM action_permissions WHERE id = ?",
                             (permission_id,)).fetchone()
            if row is None or row["binding"] != binding:
                return False
            if row["status"] not in allowed:
                return False
            db.execute("UPDATE action_permissions SET status = ? WHERE id = ?",
                       (target, permission_id))
            self._audit(db, target)
            self._maintain(db, now, elapsed)
            return True

    def inspect(self, permission_id: str, action: BrowserAction) -> dict | None:
        binding = action.fingerprint()
        with self.store._session() as db:
            db.execute("BEGIN IMMEDIATE")
            now, elapsed = self._time()
            self._maintain(db, now, elapsed)
            row = db.execute("SELECT * FROM action_permissions WHERE id = ?",
                             (permission_id,)).fetchone()
            if row is None or row["binding"] != binding:
                return None
            status = row["status"]
            return {"status": status, "expires_at": row["expires_at"],
                    "remaining_seconds": max(0, min(row["expires_at"] - now,
                        row["expires_monotonic"] - elapsed))
                        if status in {"pending", "approved"} else 0}

    def revoke_many(self, actions: list[tuple[str, BrowserAction]]) -> None:
        """Invalidate one inbox's open requests in a single committed transaction."""
        bindings = [(item, action.fingerprint()) for item, action in actions]
        with self.store._session() as db:
            db.execute("BEGIN IMMEDIATE")
            for permission_id, binding in bindings:
                changed = db.execute(
                    "UPDATE action_permissions SET status = 'revoked' "
                    "WHERE id = ? AND binding = ? AND status IN ('pending', 'approved')",
                    (permission_id, binding),
                ).rowcount
                if changed:
                    self._audit(db, "revoked")
            self._maintain(db, *self._time())

    def invalidate_open(self) -> None:
        """A newly owned runtime must never restore an old session's approvals."""
        with self.store._session() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("UPDATE action_permissions SET status = 'revoked' "
                                 "WHERE status IN ('pending', 'approved')").rowcount
            if changed:
                self._audit(db, "session_reset")
            self._maintain(db, *self._time())

    def _maintain(self, db, now, elapsed):
        expired = db.execute(
            "UPDATE action_permissions SET status = 'expired' "
            "WHERE status IN ('pending', 'approved') AND "
            "(expires_at <= ? OR expires_monotonic <= ? OR created_wall > ? "
            "OR created_monotonic > ?)", (now, elapsed, now, elapsed),
        ).rowcount
        if expired:
            self._audit(db, "expired")
        db.execute(
            "DELETE FROM action_permissions WHERE status NOT IN ('pending', 'approved') "
            "AND id NOT IN (SELECT id FROM action_permissions "
            "WHERE status NOT IN ('pending', 'approved') "
            "ORDER BY created_wall DESC, rowid DESC LIMIT ?)",
            (MAX_TERMINAL_PERMISSIONS,),
        )

    def _time(self):
        now = self.clock()
        elapsed = self.monotonic()
        if not math.isfinite(now) or not math.isfinite(elapsed):
            raise ValueError("Invalid clock")
        return now, elapsed

    @staticmethod
    def _audit(db, status):
        db.execute("INSERT INTO events (event_type, message, created_at) VALUES (?, ?, ?)",
                   ("permission." + status, "One-shot browser permission " + status, _now()))
