import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from malenia.browser_permissions import BrowserPermissionSession
from malenia.permission_inbox import PermissionInbox
from malenia.permissions import PermissionGate
from malenia.store import TaskStore


class FakeBrowserReceiver:
    """Test double only; no real page data or browser APIs are used."""
    def __init__(self, connection_id, sequence, tab_id, document_id):
        self.identity = (connection_id, sequence, tab_id, document_id)
        self.seen = set()

    def accept(self, prepared):
        identity = (prepared.connection_id, prepared.sequence,
                    prepared.action.tab_id, prepared.action.document_id)
        if (identity != self.identity or prepared.permission_id in self.seen
                or prepared.action.fingerprint() != prepared.binding):
            return False
        self.seen.add(prepared.permission_id)
        return True


class BrowserPermissionSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name) / "browser.sqlite3")
        self.now = 1000.0
        self.gate = PermissionGate(self.store, lambda: self.now, lambda: self.now)
        self.inbox = PermissionInbox(self.gate)
        self.browser = BrowserPermissionSession(self.inbox)
        self.connection = self.browser.connect()
        self.browser.select_document(self.connection, 0, 7, "document-a")

    def request(self, approve=True):
        item = self.browser.request("browser.read_text", {"selector": "main"})
        if approve:
            state = self.inbox.list_requests()[0]
            self.assertTrue(self.inbox.decide(item, state["binding"], "allow"))
        return item

    def status(self, item):
        return next(row["status"] for row in self.inbox.list_requests() if row["id"] == item)

    def test_selected_document_is_bound_and_consumed_once(self):
        item = self.request()
        prepared = self.browser.prepare(item)
        receiver = FakeBrowserReceiver(self.connection, 0, 7, "document-a")
        self.assertTrue(receiver.accept(prepared))
        self.assertFalse(receiver.accept(prepared))
        self.assertIsNone(self.browser.prepare(item))
        self.assertEqual(self.status(item), "consumed")

    def test_navigation_revokes_pending_and_approved_requests(self):
        for approved in (False, True):
            with self.subTest(approved=approved):
                item = self.request(approved)
                self.browser.select_document(self.connection, 1 if not approved else 2,
                                             7, "document-b")
                self.assertEqual(self.status(item), "revoked")
                self.assertIsNone(self.browser.prepare(item))

    def test_switching_tabs_and_returning_does_not_restore_approval(self):
        item = self.request()
        self.browser.select_document(self.connection, 1, 8, "other-tab-document")
        self.browser.select_document(self.connection, 2, 7, "document-a")
        self.assertIsNone(self.browser.prepare(item))
        self.assertEqual(self.status(item), "revoked")

    def test_fresh_event_with_reused_document_id_invalidates_permission(self):
        item = self.request()
        self.browser.select_document(self.connection, 1, 7, "document-a")
        self.assertIsNone(self.browser.prepare(item))
        self.assertEqual(self.status(item), "revoked")

    def test_disconnect_reconnect_rotates_session_and_rejects_old_events(self):
        old_session = self.inbox.session_id
        item = self.request()
        self.assertTrue(self.browser.disconnect(self.connection))
        new_connection = self.browser.connect()
        self.assertNotEqual(new_connection, self.connection)
        self.assertNotEqual(self.inbox.session_id, old_session)
        self.assertFalse(self.browser.select_document(self.connection, 99, 7, "document-a"))
        self.assertFalse(self.browser.disconnect(self.connection))
        self.assertTrue(self.browser.select_document(new_connection, 0, 7, "document-a"))
        self.assertIsNone(self.browser.prepare(item))
        self.assertIsNotNone(self.browser.prepare(self.request()))

    def test_old_or_duplicate_events_cannot_replace_current_document(self):
        self.assertFalse(self.browser.select_document(self.connection, 0, 99, "stale"))
        self.browser.select_document(self.connection, 2, 8, "document-b")
        self.assertFalse(self.browser.select_document(self.connection, 1, 7, "stale"))
        prepared = self.browser.prepare(self.request())
        self.assertEqual((prepared.action.tab_id, prepared.action.document_id), (8, "document-b"))

    def test_no_selection_or_disconnection_blocks_creation_and_preparation(self):
        item = self.request()
        self.browser.select_document(self.connection, 1, None, None)
        with self.assertRaises(RuntimeError):
            self.request()
        self.assertIsNone(self.browser.prepare(item))
        self.browser.disconnect(self.connection)
        with self.assertRaises(RuntimeError):
            self.request()

    def test_cancel_expiry_and_denial_block_preparation(self):
        item = self.request()
        self.assertTrue(self.browser.cancel(item))
        self.assertFalse(self.browser.cancel(item))
        self.assertIsNone(self.browser.prepare(item))
        item = self.request()
        self.now += 60
        self.assertIsNone(self.browser.prepare(item))
        self.assertEqual(self.status(item), "expired")
        item = self.request(False)
        state = self.inbox.list_requests()[0]
        self.assertTrue(self.inbox.decide(item, state["binding"], "deny"))
        self.assertIsNone(self.browser.prepare(item))

    def test_navigation_after_preparation_is_rejected_by_receiver_contract(self):
        prepared = self.browser.prepare(self.request())
        self.browser.select_document(self.connection, 1, 7, "document-b")
        receiver = FakeBrowserReceiver(self.connection, 1, 7, "document-b")
        self.assertFalse(receiver.accept(prepared))
        self.assertIsNone(self.browser.prepare(prepared.permission_id))

    def test_mutating_prepared_parameters_does_not_match_original_binding(self):
        prepared = self.browser.prepare(self.request())
        prepared.action.parameters["selector"] = "body"
        receiver = FakeBrowserReceiver(self.connection, 0, 7, "document-a")
        self.assertFalse(receiver.accept(prepared))

    def test_concurrent_navigation_and_preparation_cannot_authorize_new_document(self):
        item = self.request()
        barrier = Barrier(2)
        def prepare():
            barrier.wait(timeout=5)
            return self.browser.prepare(item)
        def navigate():
            barrier.wait(timeout=5)
            self.browser.select_document(self.connection, 1, 7, "document-b")
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(prepare)
            other = pool.submit(navigate)
            prepared = future.result(timeout=10)
            other.result(timeout=10)
        if prepared is not None:
            self.assertFalse(FakeBrowserReceiver(self.connection, 1, 7, "document-b").accept(prepared))
        self.assertIsNone(self.browser.prepare(item))

    def test_uncertain_delivery_never_restores_consumed_permission(self):
        item = self.request()
        prepared = self.browser.prepare(item)
        self.assertIsNotNone(prepared)
        # A timeout after this point is deliberately not retried by the adapter.
        self.assertIsNone(self.browser.prepare(item))
        self.assertEqual(self.status(item), "consumed")

    def test_invalidation_storage_failure_disables_dispatch(self):
        for operation in ("navigate", "disconnect", "connect"):
            with self.subTest(operation=operation):
                connection = self.browser.connect()
                self.browser.select_document(connection, 0, 7, "document-a")
                item = self.request()
                with patch.object(self.gate, "revoke_many", side_effect=OSError("fixture failure")):
                    with self.assertRaises(OSError):
                        if operation == "navigate":
                            self.browser.select_document(connection, 1, 7, "document-b")
                        elif operation == "disconnect":
                            self.browser.disconnect(connection)
                        else:
                            self.browser.connect()
                self.assertIsNone(self.browser.prepare(item))
                with self.assertRaises(RuntimeError):
                    self.request()

    def test_batch_revocation_rolls_back_and_disables_dispatch_on_database_failure(self):
        first = self.request()
        second = self.request(False)
        with self.store._session() as db:
            # UUID originates in this fixture, not external input.
            db.execute("CREATE TRIGGER fixture_abort BEFORE UPDATE ON action_permissions "
                       "WHEN OLD.id = '" + second + "' BEGIN "
                       "SELECT RAISE(ABORT, 'fixture failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.browser.select_document(self.connection, 1, 7, "document-b")
        self.assertEqual(self.status(first), "approved")
        self.assertEqual(self.status(second), "pending")
        self.assertIsNone(self.browser.prepare(first))
        self.assertNotIn("permission.revoked", [e["event_type"] for e in self.store.list_events()])

    def test_malformed_document_events_fail_without_mutating_current_target(self):
        for sequence, tab_id, document_id in (
            (True, 7, "doc"), (-1, 7, "doc"), (1, True, "doc"),
            (1, 7, ""), (1, None, "doc"), (1, 7, None),
        ):
            with self.subTest(event=(sequence, tab_id, document_id)), self.assertRaises(ValueError):
                self.browser.select_document(self.connection, sequence, tab_id, document_id)
        prepared = self.browser.prepare(self.request())
        self.assertEqual(prepared.action.document_id, "document-a")


if __name__ == "__main__":
    unittest.main()
