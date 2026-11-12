import tempfile
import unittest
from pathlib import Path

from malenia.store import TaskStore


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp_dir.name) / "test.sqlite3")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_task_persists_task_and_event(self):
        task = self.store.create_task("Check an order", "Read-only test")
        self.assertEqual(task["title"], "Check an order")
        self.assertEqual(task["status"], "pending")
        self.assertEqual(len(self.store.list_tasks()), 1)
        events = self.store.list_events()
        self.assertEqual(events[0]["event_type"], "task.created")

    def test_pending_task_can_be_cancelled(self):
        task = self.store.create_task("Cancel me")
        cancelled = self.store.cancel_task(task["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(self.store.list_events()[0]["event_type"], "task.cancelled")

    def test_unknown_task_returns_none(self):
        self.assertIsNone(self.store.get_task("not-a-real-id"))
        self.assertIsNone(self.store.cancel_task("not-a-real-id"))


if __name__ == "__main__":
    unittest.main()
