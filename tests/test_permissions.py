import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

from malenia.permissions import BrowserAction, PermissionGate
from malenia.store import TaskStore


class PermissionGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TaskStore(Path(self.temp.name) / "permissions.sqlite3")
        self.now = 1000.0
        self.elapsed = 100.0
        self.gate = PermissionGate(self.store, lambda: self.now, lambda: self.elapsed)
        self.action = BrowserAction("browser.read_text", str(uuid.uuid4()), 7,
                                    "document-1", {"selector": "main"})

    def approved(self):
        grant = self.gate.request(self.action)
        self.assertTrue(self.gate.decide(grant, self.action, allow=True))
        return grant

    def test_pending_and_unknown_cannot_be_consumed(self):
        grant = self.gate.request(self.action)
        self.assertFalse(self.gate.consume(grant, self.action))
        self.assertFalse(self.gate.consume(str(uuid.uuid4()), self.action))

    def test_approved_is_consumed_once_even_after_reopening(self):
        grant = self.approved()
        self.assertTrue(self.gate.consume(grant, self.action))
        reopened = PermissionGate(TaskStore(self.store.path), lambda: self.now, lambda: self.elapsed)
        self.assertFalse(reopened.consume(grant, self.action))
        self.assertFalse(reopened.decide(grant, self.action, allow=True))

    def test_deny_and_revoke_are_terminal(self):
        grant = self.gate.request(self.action)
        self.assertTrue(self.gate.decide(grant, self.action, allow=False))
        self.assertFalse(self.gate.decide(grant, self.action, allow=True))
        self.assertFalse(self.gate.consume(grant, self.action))
        for approve in (False, True):
            with self.subTest(approve=approve):
                grant = self.approved() if approve else self.gate.request(self.action)
                self.assertTrue(self.gate.revoke(grant, self.action))
                self.assertFalse(self.gate.consume(grant, self.action))
                self.assertFalse(self.gate.decide(grant, self.action, allow=True))

    def test_expiration_at_boundary_for_decision_and_use(self):
        pending = self.gate.request(self.action)
        approved = self.approved()
        self.now += 60
        self.assertFalse(self.gate.decide(pending, self.action, allow=True))
        self.assertFalse(self.gate.consume(approved, self.action))
        self.now -= 1
        self.assertFalse(self.gate.consume(approved, self.action))

    def test_every_binding_field_is_enforced_without_consuming_original(self):
        grant = self.approved()
        for changed in (
            replace(self.action, capability="browser.screenshot"),
            replace(self.action, session_id=str(uuid.uuid4())),
            replace(self.action, tab_id=8),
            replace(self.action, document_id="document-2"),
            replace(self.action, parameters={"selector": "body"}),
        ):
            with self.subTest(action=changed):
                self.assertFalse(self.gate.consume(grant, changed))
        self.assertTrue(self.gate.consume(grant, self.action))

    def test_wall_clock_rollback_cannot_extend_monotonic_lifetime(self):
        grant = self.approved()
        self.now += 10
        self.elapsed += 60
        self.assertFalse(self.gate.consume(grant, self.action))

    def test_clock_reset_expires_permission_permanently(self):
        for clock in ("now", "elapsed"):
            with self.subTest(clock=clock):
                grant = self.approved()
                old = getattr(self, clock)
                setattr(self, clock, old - 1)
                self.assertFalse(self.gate.consume(grant, self.action))
                setattr(self, clock, old)
                self.assertFalse(self.gate.consume(grant, self.action))

    def test_invalid_clock_fails_closed(self):
        grant = self.approved()
        self.now = float("nan")
        with self.assertRaises(ValueError):
            self.gate.consume(grant, self.action)

    def test_mismatched_approval_fails(self):
        grant = self.gate.request(self.action)
        self.assertFalse(self.gate.decide(grant, replace(self.action, tab_id=8), allow=True))
        self.assertFalse(self.gate.consume(grant, self.action))

    def test_concurrent_consumers_have_exactly_one_winner(self):
        grant = self.approved()
        barrier = Barrier(8)
        def consume(_):
            gate = PermissionGate(TaskStore(self.store.path), lambda: self.now, lambda: self.elapsed)
            barrier.wait(timeout=10)
            return gate.consume(grant, self.action)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(consume, range(8)))
        self.assertEqual(sum(results), 1)
        consumed = [e for e in self.store.list_events() if e["event_type"] == "permission.consumed"]
        self.assertEqual(len(consumed), 1)

    def test_concurrent_decisions_have_exactly_one_winner(self):
        grant = self.gate.request(self.action)
        barrier = Barrier(2)
        def decide(allow):
            barrier.wait(timeout=10)
            return self.gate.decide(grant, self.action, allow=allow)
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(decide, [True, False])), 1)

    def test_invalid_requests_fail_without_persistence(self):
        for ttl in (0, 301, True, 1.5):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                self.gate.request(self.action, ttl=ttl)
        for action in (
            replace(self.action, capability="browser.cookies"),
            replace(self.action, tab_id=True),
            replace(self.action, document_id=""),
            replace(self.action, session_id="not-a-session"),
            replace(self.action, parameters={"x": float("nan")}),
            replace(self.action, parameters={1: "ambiguous"}),
            replace(self.action, parameters={"huge": "x" * 8192}),
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.gate.request(action)
        self.assertEqual(self.store.list_events(), [])

    def test_parameter_order_does_not_change_binding(self):
        one = replace(self.action, parameters={"a": 1, "b": 2})
        two = replace(self.action, parameters={"b": 2, "a": 1})
        self.assertEqual(one.fingerprint(), two.fingerprint())

    def test_audit_and_database_do_not_store_action_parameters(self):
        self.approved()
        self.assertNotIn("selector", str(self.store.list_events()))
        with self.store._session() as db:
            rows = db.execute("SELECT * FROM action_permissions").fetchall()
        self.assertNotIn("selector", str([dict(row) for row in rows]))


if __name__ == "__main__":
    unittest.main()
