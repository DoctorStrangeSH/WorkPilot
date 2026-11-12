"""Bounded signed lifecycle-event protocol prototype; no real transport is wired."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading

from .browser_permissions import BrowserPermissionSession
from .native_messaging import validate_origin

MAX_EVENT_BYTES = 8192
MAX_SAFE_INTEGER = 2**53 - 1


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate event key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite JSON constant")


class BrowserEventChannel:
    """Future transport must provision a fresh 32-byte key via a trusted path.

    Origin is transport-supplied metadata, never a JSON field. A signature proves
    possession of the channel key, not browser identity or truthful document IDs.
    This class does not provision keys, accept sockets or expose an HTTP endpoint.
    """
    def __init__(self, browser: BrowserPermissionSession, extension_id: str, key: bytes):
        if not isinstance(extension_id, str) or re.fullmatch(r"[a-p]{32}", extension_id) is None:
            raise ValueError("Invalid extension identity")
        if type(key) is not bytes or len(key) != 32:
            raise ValueError("Channel key must contain 32 bytes")
        self.browser = browser
        self.extension_id = extension_id
        self._key = key
        self._lock = threading.RLock()
        self._last_sequence = -1
        self._closed = True
        self.connection_id = browser.connect()
        self._closed = False

    def close(self):
        with self._lock:
            self._closed = True
            return self.browser.disconnect(self.connection_id)

    def receive(self, payload: bytes, signature: str, origin: str) -> bool:
        # Reject unauthenticated input without parsing or changing runtime state.
        if (type(payload) is not bytes or not 2 <= len(payload) <= MAX_EVENT_BYTES
                or not isinstance(signature, str)
                or re.fullmatch(r"[0-9a-f]{64}", signature) is None
                or not validate_origin(origin, self.extension_id)):
            return False
        expected = hmac.new(self._key, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return False
        with self._lock:
            if self._closed:
                return False
            try:
                event = json.loads(payload.decode("utf-8"), object_pairs_hook=_object,
                                   parse_constant=_reject_constant)
                if not isinstance(event, dict) or event.get("version") != 1 or type(event.get("version")) is not int:
                    raise ValueError("Invalid protocol version")
                connection_id = event.get("connection_id")
                if (not isinstance(connection_id, str) or re.fullmatch(
                        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                        connection_id) is None):
                    raise ValueError("Invalid connection identity")
                if connection_id != self.connection_id:
                    return False
                sequence = event.get("sequence")
                if type(sequence) is not int or not 0 <= sequence <= MAX_SAFE_INTEGER:
                    raise ValueError("Invalid sequence")
                if sequence <= self._last_sequence:
                    return False
                if sequence != self._last_sequence + 1:
                    raise ValueError("Missing lifecycle event")
                kind = event.get("type")
                common = {"version", "connection_id", "sequence", "type"}
                if kind == "selected_document" and set(event) == common | {"tab_id", "document_id"}:
                    tab = event["tab_id"]
                    if tab is not None and (type(tab) is not int or not 0 <= tab <= MAX_SAFE_INTEGER):
                        raise ValueError("Invalid tab ID")
                    accepted = self.browser.select_document(self.connection_id, sequence,
                                                           tab, event["document_id"])
                elif kind == "disconnect" and set(event) == common:
                    accepted = self.close()
                else:
                    raise ValueError("Invalid lifecycle event schema")
                if accepted:
                    self._last_sequence = sequence
                return accepted
            except (ValueError, UnicodeError, RecursionError):
                # Authenticated malformed/gapped input loses document authority.
                self.close()
                return False
            except Exception:
                self.close()
                raise
