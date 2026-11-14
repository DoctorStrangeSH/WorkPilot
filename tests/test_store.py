import tempfile
import unittest
from pathlib import Path

from malenia.store import TaskStore, SubmissionConflict
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4


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

    def test_submission_survives_reopen_and_cancel_without_duplicate_event(self):
        request_id = str(uuid4())
        first = self.store.create_task("Reviewed title", "Reviewed text", request_id)
        self.store.cancel_task(first["id"])
        reopened = TaskStore(self.store.path)
        retry = reopened.create_task("Reviewed title", "Reviewed text", request_id)
        self.assertEqual(retry["id"], first["id"])
        self.assertEqual(retry["status"], "cancelled")
        self.assertEqual(len(reopened.list_tasks()), 1)
        self.assertEqual(len(reopened.list_events()), 2)
        with self.assertRaises(SubmissionConflict):
            reopened.create_task("Changed", "Reviewed text", request_id)
        self.assertEqual(len(reopened.list_tasks()), 1)

    def test_concurrent_submissions_create_one_task(self):
        request_id = str(uuid4())
        with ThreadPoolExecutor(max_workers=8) as pool:
            tasks = list(pool.map(lambda _: self.store.create_task("Same", "Text", request_id), range(16)))
        self.assertEqual(len({task["id"] for task in tasks}), 1)
        self.assertEqual(len(self.store.list_events()), 1)

    def test_legacy_submissions_still_create_independent_tasks(self):
        first = self.store.create_task("Same")
        second = self.store.create_task("Same")
        self.assertNotEqual(first["id"], second["id"])

    def test_browser_audit_claim_is_atomic_and_expired_jobs_are_not_replayed(self):
        first = self.store.request_browser_audit()
        with self.assertRaises(SubmissionConflict):
            self.store.request_browser_audit()
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda _: self.store.claim_browser_audit(), range(12)))
        claimed = [item for item in claims if item]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["job_id"], first["job_id"])
        self.assertFalse(self.store.finish_browser_audit("not-the-job", True))
        self.assertTrue(self.store.finish_browser_audit(first["job_id"], False))
        self.assertEqual(self.store.latest_browser_audit_job()["status"], "failed")
        second = self.store.request_browser_audit()
        self.assertNotEqual(first["job_id"], second["job_id"])
        with self.store._session() as db:
            db.execute("UPDATE browser_audit_job SET created_unix=0 WHERE id=1")
        self.assertEqual(self.store.latest_browser_audit_job()["status"], "expired")
        self.assertIsNone(self.store.claim_browser_audit())
        self.assertFalse(self.store.finish_browser_audit(second["job_id"], True))
        self.assertEqual(self.store.latest_browser_audit_job()["status"], "expired")

    def test_browser_audit_progress_is_coarse_monotone_and_job_bound(self):
        pending = self.store.request_browser_audit()
        job_id = pending["job_id"]
        self.assertFalse(self.store.update_browser_audit_progress(
            job_id, "inventory", 0, 0, None))
        self.assertIsNotNone(self.store.claim_browser_audit())
        self.assertTrue(self.store.update_browser_audit_progress(
            job_id, "inventory", 0, 0, None))
        self.assertTrue(self.store.update_browser_audit_progress(
            job_id, "datalens", 1, 0, None))
        self.assertTrue(self.store.update_browser_audit_progress(
            job_id, "asgard", 2, 1, "datalens"))
        report = self.store.latest_browser_audit_job()
        self.assertEqual(report["current_role"], "asgard")
        self.assertEqual(report["completed_sources"], 2)
        self.assertEqual(report["attention_sources"], 1)
        self.assertEqual(report["failed_role"], "datalens")
        for arguments in [
            (job_id, "asgard", 1, 1, "datalens"),
            (job_id, "asgard", 2, 0, "datalens"),
            (job_id, "untrusted", 2, 1, None),
            (job_id, "asgard", True, 1, None),
            ("different-job", "asgard", 2, 1, None),
        ]:
            self.assertFalse(self.store.update_browser_audit_progress(*arguments))
        self.assertTrue(self.store.finish_browser_audit(job_id, False))
        self.assertFalse(self.store.update_browser_audit_progress(
            job_id, "asgard", 3, 1, "datalens"))
        new_job = self.store.request_browser_audit()
        report = self.store.latest_browser_audit_job()
        self.assertEqual(report["job_id"], new_job["job_id"])
        self.assertEqual(report["completed_sources"], 0)
        self.assertIsNone(report["failed_role"])

    def test_delete_browser_tab_removes_only_shared_record(self):
        shared = self.store.record_browser_tab("https://example.com/orders", "Orders")
        self.assertEqual(len(self.store.list_browser_tabs()), 1)
        self.assertTrue(self.store.delete_browser_tab(shared["id"]))
        self.assertEqual(self.store.list_browser_tabs(), [])
        self.assertFalse(self.store.delete_browser_tab(shared["id"]))
        event = self.store.list_events(1)[0]
        self.assertEqual(event["event_type"], "browser.tab_unshared")

    def test_delete_browser_tab_rejects_invalid_id(self):
        self.assertFalse(self.store.delete_browser_tab(""))
        self.assertFalse(self.store.delete_browser_tab("../all"))

    def test_unknown_task_returns_none(self):
        self.assertIsNone(self.store.get_task("not-a-real-id"))
        self.assertIsNone(self.store.cancel_task("not-a-real-id"))


if __name__ == "__main__":
    unittest.main()
