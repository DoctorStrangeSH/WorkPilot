"""Trusted browser-lifecycle adapter contract. No real transport or executor."""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Any

from .permission_inbox import PermissionInbox
from .permissions import BrowserAction


@dataclass(frozen=True)
class PreparedBrowserAction:
    permission_id: str
    binding: str
    connection_id: str
    sequence: int
    action: BrowserAction


class BrowserPermissionSession:
    """Events must come from authenticated browser APIs, never page/model content.

    Each selected-document event carries an increasing sequence within a fresh
    connection UUID. A transport must deliver lifecycle events in order and
    reject dispatch on the browser side if the document/connection has changed.
    """

    def __init__(self, inbox: PermissionInbox):
        self.inbox = inbox
        self._lock = threading.RLock()
        self._connection_id: str | None = None
        self._sequence = -1
        self._document: tuple[int, str] | None = None

    def connect(self) -> str:
        with self._lock:
            # Clear authority first: a storage failure must leave dispatch disabled.
            self._connection_id = None
            self._document = None
            self._sequence = -1
            self.inbox.invalidate(rotate_session=True)
            self._connection_id = str(uuid.uuid4())
            return self._connection_id

    def disconnect(self, connection_id: str) -> bool:
        with self._lock:
            if self._connection_id is None or connection_id != self._connection_id:
                return False
            self._connection_id = None
            self._document = None
            self._sequence = -1
            self.inbox.invalidate(rotate_session=True)
            return True

    def select_document(self, connection_id: str, sequence: int,
                        tab_id: int | None, document_id: str | None) -> bool:
        if type(sequence) is not int or sequence < 0:
            raise ValueError("Invalid browser event sequence")
        if tab_id is None and document_id is None:
            document = None
        else:
            if type(tab_id) is not int or tab_id < 0:
                raise ValueError("Invalid selected tab")
            if (not isinstance(document_id, str) or not document_id.strip()
                    or len(document_id) > 256):
                raise ValueError("Invalid selected document")
            document = (tab_id, document_id)
        with self._lock:
            if (self._connection_id is None or connection_id != self._connection_id
                    or sequence <= self._sequence):
                return False
            # Conservative invalidation even when a fresh event repeats the IDs:
            # never carry approval through an unobserved intermediate navigation.
            self._sequence = sequence
            self._document = None
            self.inbox.invalidate()
            self._document = document
            return True

    def request(self, capability: str, parameters: dict[str, Any], ttl: int = 60) -> str:
        with self._lock:
            if self._connection_id is None or self._document is None:
                raise RuntimeError("No selected browser document")
            tab_id, document_id = self._document
            return self.inbox.request(capability, tab_id, document_id, parameters, ttl)

    def cancel(self, permission_id: str) -> bool:
        with self._lock:
            for item in self.inbox.list_requests():
                if item["id"] == permission_id:
                    return self.inbox.decide(permission_id, item["binding"], "revoke")
            return False

    def prepare(self, permission_id: str) -> PreparedBrowserAction | None:
        """Consume locally before handing an envelope to a future dispatcher.

        No send or retry occurs here. Receiver-side identity checking and replay
        protection are required; local consumption cannot close a transport race.
        """
        with self._lock:
            if self._connection_id is None or self._document is None:
                return None
            tab_id, document_id = self._document
            action = self.inbox.take_for_dispatch(permission_id, tab_id, document_id)
            if action is None:
                return None
            return PreparedBrowserAction(permission_id, action.fingerprint(),
                                         self._connection_id, self._sequence, action)
