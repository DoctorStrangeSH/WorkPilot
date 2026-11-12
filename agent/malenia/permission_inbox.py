"""Session-scoped trusted request presentation, with no public request producer."""
from __future__ import annotations

import copy
import hmac
import threading
import uuid

from .permissions import BrowserAction, PermissionGate


class PermissionInbox:
    def __init__(self, gate: PermissionGate):
        self.gate = gate
        self.session_id = str(uuid.uuid4())
        self._actions: dict[str, BrowserAction] = {}
        self._lock = threading.RLock()

    def request(self, capability, tab_id, document_id, parameters, ttl=60):
        # Internal adapter entry only: never expose creation to HTTP or page content.
        action = BrowserAction(capability, self.session_id, tab_id, document_id,
                               copy.deepcopy(parameters))
        action.fingerprint()
        with self._lock:
            if len(self._actions) >= 100:
                for item in self.list_requests():
                    if item["status"] not in {"pending", "approved"}:
                        self._actions.pop(item["id"], None)
            if len(self._actions) >= 100:
                raise ValueError("Too many open permission requests")
            permission_id = self.gate.request(action, ttl)
            self._actions[permission_id] = action
            return permission_id

    def list_requests(self):
        with self._lock:
            result = []
            for permission_id, action in reversed(self._actions.items()):
                state = self.gate.inspect(permission_id, action)
                if state is not None:
                    result.append({"id": permission_id, "binding": action.fingerprint(),
                                   "capability": action.capability, "tab_id": action.tab_id,
                                   "document_id": action.document_id,
                                   "parameters": copy.deepcopy(action.parameters), **state})
            return result

    def invalidate(self, *, rotate_session: bool = False) -> None:
        with self._lock:
            self.gate.revoke_many(list(self._actions.items()))
            if rotate_session:
                self.session_id = str(uuid.uuid4())

    def take_for_dispatch(self, permission_id: str, tab_id: int,
                          document_id: str) -> BrowserAction | None:
        """Internal only: consume the exact live target, never a caller's action body."""
        with self._lock:
            action = self._actions.get(permission_id)
            if (action is None or action.session_id != self.session_id
                    or action.tab_id != tab_id or action.document_id != document_id):
                return None
            # Copy before consuming, so a copy failure cannot lose a permission.
            snapshot = copy.deepcopy(action)
            if not self.gate.consume(permission_id, action):
                return None
            return snapshot

    def decide(self, permission_id, binding, decision):
        if decision not in {"allow", "deny", "revoke"}:
            raise ValueError("Invalid permission decision")
        with self._lock:
            action = self._actions.get(permission_id)
            if action is None or not hmac.compare_digest(action.fingerprint(), binding):
                return False
            if decision == "revoke":
                return self.gate.revoke(permission_id, action)
            return self.gate.decide(permission_id, action, allow=decision == "allow")
