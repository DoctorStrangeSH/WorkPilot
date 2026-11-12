import hashlib
import hmac
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from malenia.browser_channel import BrowserEventChannel
from malenia.browser_permissions import BrowserPermissionSession
from malenia.permission_inbox import PermissionInbox
from malenia.permissions import PermissionGate
from malenia.store import TaskStore


class BrowserEventChannelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name) / "channel.sqlite3")
        self.inbox = PermissionInbox(PermissionGate(self.store))
        self.browser = BrowserPermissionSession(self.inbox)
        self.key = b"fixture-" * 4
        self.extension = "a" * 32
        self.origin = f"chrome-extension://{self.extension}/"
        self.channel = BrowserEventChannel(self.browser, self.extension, self.key)

    def event(self, sequence=0, **changes):
        value = {"version": 1, "type": "selected_document", "sequence": sequence,
                 "connection_id": self.channel.connection_id, "tab_id": 7, "document_id": "document-a"}
        value.update(changes)
        return json.dumps(value, separators=(",", ":")).encode()

    def send(self, payload, channel=None, key=None, origin=None):
        signature = hmac.new(key or self.key, payload, hashlib.sha256).hexdigest()
        return (channel or self.channel).receive(payload, signature, origin or self.origin)

    def approve(self):
        item = self.browser.request("browser.read_text", {"selector": "main"})
        state = self.inbox.list_requests()[0]
        self.assertTrue(self.inbox.decide(item, state["binding"], "allow"))
        return item

    def test_valid_signed_selection_navigation_and_disconnect(self):
        self.assertTrue(self.send(self.event()))
        item = self.approve()
        self.assertTrue(self.send(self.event(1, document_id="document-b")))
        self.assertIsNone(self.browser.prepare(item))
        payload = json.dumps({"version": 1, "type": "disconnect", "sequence": 2,
                              "connection_id": self.channel.connection_id}).encode()
        self.assertTrue(self.send(payload))
        with self.assertRaises(RuntimeError):
            self.approve()

    def test_wrong_origin_key_or_tampered_bytes_do_not_change_authority(self):
        self.send(self.event())
        item = self.approve()
        payload = self.event(1, document_id="document-b")
        self.assertFalse(self.send(payload, origin="chrome-extension://" + "b" * 32 + "/"))
        self.assertFalse(self.send(payload, key=b"wrong-key"))
        signature = hmac.new(self.key, payload, hashlib.sha256).hexdigest()
        self.assertFalse(self.channel.receive(payload + b" ", signature, self.origin))
        prepared = self.browser.prepare(item)
        self.assertEqual(prepared.action.document_id, "document-a")

    def test_replayed_events_cannot_invalidate_new_permission(self):
        payload = self.event()
        self.assertTrue(self.send(payload))
        item = self.approve()
        self.assertFalse(self.send(payload))
        self.assertIsNotNone(self.browser.prepare(item))

    def test_authenticated_gap_closes_channel_and_revokes_authority(self):
        self.send(self.event())
        item = self.approve()
        self.assertFalse(self.send(self.event(2)))
        self.assertIsNone(self.browser.prepare(item))
        self.assertFalse(self.send(self.event(1)))
        with self.assertRaises(RuntimeError):
            self.approve()

    def test_authenticated_malformed_events_fail_closed(self):
        malformed = [b"[]", b"not json", b"\xff\xff", b'{"version":1,"version":1}',
                     self.event(version=True), self.event(version=1.0), self.event(sequence=True),
                     self.event(sequence=2**53), self.event(tab_id=True), self.event(tab_id=2**53),
                     self.event(document_id=""), self.event(type="approve"),
                     self.event(page_text="untrusted fixture"), self.event(extra=float("nan"))]
        for payload in malformed:
            with self.subTest(payload=payload):
                self.channel = BrowserEventChannel(self.browser, self.extension, self.key)
                # Refresh connection IDs for generated object fixtures.
                try:
                    data = json.loads(payload)
                    if isinstance(data, dict) and "connection_id" in data:
                        data["connection_id"] = self.channel.connection_id
                        payload = json.dumps(data).encode()
                except (ValueError, UnicodeError):
                    pass
                self.assertFalse(self.send(payload))
                self.assertFalse(self.send(self.event()))
                with self.assertRaises(RuntimeError):
                    self.approve()

    def test_invalid_connection_shape_closes_current_channel(self):
        self.send(self.event())
        item = self.approve()
        self.assertFalse(self.send(self.event(1, connection_id=None)))
        self.assertIsNone(self.browser.prepare(item))
        self.assertFalse(self.send(self.event(1)))

    def test_size_and_signature_shape_are_bounded_before_parsing(self):
        self.send(self.event())
        item = self.approve()
        self.assertFalse(self.send(b"x" * 8193))
        self.assertFalse(self.channel.receive(self.event(1), "not a signature", self.origin))
        self.assertFalse(self.channel.receive(self.event(1), "a" * 64 + "\u00ff", self.origin))
        self.assertIsNotNone(self.browser.prepare(item))

    def test_old_channel_cannot_disconnect_or_select_for_new_connection(self):
        old = self.channel
        payload = self.event()
        self.channel = BrowserEventChannel(self.browser, self.extension, b"b" * 32)
        self.assertFalse(self.send(payload, channel=old))
        self.assertFalse(old.close())
        self.assertTrue(self.send(self.event(), key=b"b" * 32))
        self.assertIsNotNone(self.browser.prepare(self.approve()))

    def test_concurrent_duplicate_event_has_one_winner(self):
        payload = self.event()
        barrier = Barrier(2)
        def send(_):
            barrier.wait(timeout=5)
            return self.send(payload)
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(send, range(2))), 1)

    def test_storage_error_closes_channel_without_silent_recovery(self):
        with patch.object(self.browser, "select_document", side_effect=OSError("fixture failure")):
            with self.assertRaises(OSError):
                self.send(self.event())
        self.assertFalse(self.send(self.event()))
        with self.assertRaises(RuntimeError):
            self.approve()

    def test_channel_identity_and_key_configuration_are_strict(self):
        for extension, key in (("invalid", self.key), (self.extension, b"short"),
                               (self.extension, bytearray(32))):
            with self.subTest(extension=extension), self.assertRaises(ValueError):
                BrowserEventChannel(self.browser, extension, key)


if __name__ == "__main__":
    unittest.main()
