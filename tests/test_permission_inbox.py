import socket
import tempfile
import unittest
from pathlib import Path

from malenia.permission_inbox import PermissionInbox
from malenia.permissions import PermissionGate
from malenia.server import create_server
from malenia.store import TaskStore


class PermissionInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name) / "inbox.sqlite3")
        self.gate = PermissionGate(self.store)
        self.inbox = PermissionInbox(self.gate)

    def request(self, parameters=None):
        return self.inbox.request("browser.read_text", 7, "doc", parameters or {})

    def test_request_and_list_snapshots_are_defensive_copies(self):
        parameters = {"nested": ["original"]}
        self.request(parameters)
        parameters["nested"].append("mutated")
        snapshot = self.inbox.list_requests()
        snapshot[0]["parameters"]["nested"].append("display mutation")
        self.assertEqual(self.inbox.list_requests()[0]["parameters"], {"nested": ["original"]})

    def test_new_inbox_cannot_approve_previous_session(self):
        item = self.request()
        state = self.inbox.list_requests()[0]
        new = PermissionInbox(self.gate)
        self.assertNotEqual(new.session_id, self.inbox.session_id)
        self.assertEqual(new.list_requests(), [])
        self.assertFalse(new.decide(item, state["binding"], "allow"))

    def test_successful_server_bind_revokes_old_grants(self):
        self.request()
        server = create_server("127.0.0.1", 0, self.store, "fixture-token")
        self.addCleanup(server.server_close)
        self.assertEqual(self.inbox.list_requests()[0]["status"], "revoked")

    def test_failed_server_bind_does_not_revoke_active_grants(self):
        self.request()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            with self.assertRaises(OSError):
                create_server("127.0.0.1", listener.getsockname()[1], self.store, "fixture-token")
        self.assertEqual(self.inbox.list_requests()[0]["status"], "pending")

    def test_open_request_limit_fails_closed(self):
        for _ in range(100):
            self.request()
        with self.assertRaises(ValueError):
            self.request()
        self.assertEqual(len(self.inbox.list_requests()), 100)
        state = self.inbox.list_requests()[0]
        self.assertTrue(self.inbox.decide(state["id"], state["binding"], "deny"))
        self.request()
        self.assertEqual(len(self.inbox.list_requests()), 100)


if __name__ == "__main__":
    unittest.main()
