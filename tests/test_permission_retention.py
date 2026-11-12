import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from malenia.permissions import BrowserAction, PermissionGate
from malenia.store import TaskStore


class PermissionRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name) / "retention.sqlite3")
        self.gate = PermissionGate(self.store, lambda: 1000, lambda: 1000)
        self.action = BrowserAction("browser.read_text", str(uuid.uuid4()), 7, "doc", {})

    def seed(self, count, status, expires=2000):
        with self.store._session() as db:
            db.executemany("INSERT INTO action_permissions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(f"seed-{i}", self.action.fingerprint(), self.action.capability,
                  status, expires, expires, i, i) for i in range(count)])

    def counts(self):
        with self.store._session() as db:
            return dict(db.execute("SELECT status, COUNT(*) FROM action_permissions GROUP BY status").fetchall())

    def test_cleanup_preserves_open_requests_and_existing_audit(self):
        item = self.gate.request(self.action)
        self.store.create_task("fixture task")
        events = self.store.list_events()
        self.seed(250, "consumed")
        self.assertEqual(self.gate.inspect(item, self.action)["status"], "pending")
        self.assertEqual(self.counts(), {"pending": 1, "consumed": 100})
        self.assertIsNone(self.gate.inspect("seed-0", self.action))
        self.assertIsNotNone(self.gate.inspect("seed-249", self.action))
        self.assertFalse(self.gate.consume("seed-0", self.action))
        self.assertEqual(self.store.list_events(), events)
        self.assertEqual(len(self.store.list_tasks()), 1)

    def test_expired_open_requests_free_capacity_without_approval(self):
        self.seed(100, "approved", expires=999)
        item = self.gate.request(self.action)
        self.assertEqual(self.counts(), {"pending": 1, "expired": 100})
        self.assertFalse(self.gate.consume("seed-0", self.action))
        self.assertEqual(self.gate.inspect(item, self.action)["status"], "pending")

    def test_terminal_transition_enforces_retention_immediately(self):
        self.seed(100, "denied")
        item = self.gate.request(self.action)
        self.assertTrue(self.gate.decide(item, self.action, allow=False))
        self.assertEqual(self.counts(), {"denied": 100})
        self.assertEqual(self.gate.inspect(item, self.action)["status"], "denied")

    def test_concurrent_requests_cannot_exceed_global_open_limit(self):
        self.seed(99, "pending")
        barrier = Barrier(2)
        def request(_):
            gate = PermissionGate(TaskStore(self.store.path), lambda: 1000, lambda: 1000)
            barrier.wait(timeout=5)
            try:
                return gate.request(self.action)
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(request, range(2)))
        self.assertEqual(sum(item is not None for item in results), 1)
        self.assertEqual(self.counts(), {"pending": 100})

    def test_startup_revocation_also_prunes_old_terminal_metadata(self):
        self.seed(250, "revoked")
        self.gate.invalidate_open()
        self.assertEqual(self.counts(), {"revoked": 100})


if __name__ == "__main__":
    unittest.main()
