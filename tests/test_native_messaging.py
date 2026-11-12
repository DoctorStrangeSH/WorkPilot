import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

from malenia.native_messaging import (
    HOST_NAME,
    configured_extension_id,
    handle_message,
    read_message,
    validate_origin,
    write_message,
)
from malenia.store import TaskStore


class NativeMessagingProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp_dir.name) / "malenia.sqlite3")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_reads_and_writes_utf8_length_prefixed_json(self):
        payload = {"type": "hello", "title": "Привет"}
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        source = io.BytesIO(struct.pack("<I", len(encoded)) + encoded)
        self.assertEqual(read_message(source), payload)

        destination = io.BytesIO()
        write_message(destination, payload)
        self.assertEqual(read_message(io.BytesIO(destination.getvalue())), payload)

    def test_reads_frames_split_across_short_pipe_reads(self):
        class ChunkedReader(io.BytesIO):
            def read(self, size=-1):
                return super().read(min(size, 2) if size >= 0 else size)

        payload = {"type": "hello", "title": "Разделённый поток"}
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        source = ChunkedReader(struct.pack("<I", len(encoded)) + encoded)
        self.assertEqual(read_message(source), payload)

    def test_eof_returns_none(self):
        self.assertIsNone(read_message(io.BytesIO()))

    def test_rejects_incomplete_and_oversized_frames(self):
        with self.assertRaises(ValueError):
            read_message(io.BytesIO(b"\x01\x02"))
        with self.assertRaises(ValueError):
            read_message(io.BytesIO(struct.pack("<I", 1024 * 1024 + 1)))

    def test_extension_origin_must_match_exact_id(self):
        extension_id = "a" * 32
        self.assertTrue(validate_origin(f"chrome-extension://{extension_id}/", extension_id))
        self.assertFalse(validate_origin(f"chrome-extension://{'b' * 32}/", extension_id))
        self.assertFalse(validate_origin(f"chrome-extension://{extension_id}", extension_id))

    def test_reads_configured_extension_id(self):
        config_path = Path(self.temp_dir.name) / "browser_bridge.json"
        config_path.write_text(json.dumps({"extension_id": "a" * 32}), encoding="utf-8")
        self.assertEqual(configured_extension_id(config_path), "a" * 32)

    def test_hello_reports_only_explicit_capability(self):
        response = handle_message({"type": "hello", "request_id": "1"}, self.store)
        self.assertEqual(response["host"], HOST_NAME)
        self.assertEqual(response["capabilities"], ["share_active_tab", "inspect_active_page", "reconcile_site_tables"])
        self.assertTrue(response["ok"])

    def test_user_shared_tab_is_sanitized_and_persisted(self):
        response = handle_message(
            {
                "type": "share_active_tab",
                "request_id": "2",
                "tab": {
                    "title": "Example page",
                    "url": "https://example.com/orders/42?access_token=secret#details",
                },
            },
            self.store,
        )
        self.assertTrue(response["ok"])
        self.assertEqual(response["tab"]["url"], "https://example.com/orders/42")
        self.assertEqual(self.store.list_browser_tabs()[0]["title"], "Example page")
        self.assertEqual(self.store.list_events()[0]["event_type"], "browser.tab_shared")
        self.assertNotIn("secret", json.dumps(self.store.list_browser_tabs()))

    def test_rejects_non_http_urls_and_credentials(self):
        for url in (
            "file:///C:/private.txt",
            "javascript:alert(1)",
            "https://user:password@example.com/path",
        ):
            response = handle_message(
                {"type": "share_active_tab", "tab": {"url": url, "title": "Bad"}},
                self.store,
            )
            self.assertFalse(response["ok"])
        self.assertEqual(self.store.list_browser_tabs(), [])

    def test_inspection_is_ephemeral_and_bounded(self):
        before_tabs = self.store.list_browser_tabs()
        before_events = self.store.list_events()
        result = handle_message({"type": "inspect_active_page",
                                 "page": {"url": "https://example.com/orders?token=secret",
                                          "text": "Тестовая таблица заказов"}}, self.store)
        self.assertTrue(result["ok"])
        self.assertEqual(result["type"], "page_inspected")
        self.assertFalse(result["persisted"])
        self.assertEqual(self.store.list_browser_tabs(), before_tabs)
        self.assertEqual(self.store.list_events(), before_events)
        for payload in (
            {"page": {"url": "https://example.com/", "text": ""}},
            {"page": {"url": "https://example.com/", "text": "a" * 16001}},
            {"page": {"url": "file:///private", "text": "text"}},
            {"page": {"url": "https://example.com/", "text": "a", "extra": 1}},
        ):
            self.assertFalse(handle_message({"type": "inspect_active_page", **payload},
                                            self.store)["ok"])

    def test_reconcile_site_tables_remains_ephemeral(self):
        snapshots = {
            "inventory": {
                "columns": ["cargo_place", "inventory_date"],
                "rows": [["TEST-001", "2026-09-12"]],
            },
            "datalens": {
                "columns": ["main_partner_code_original", "sc_id", "result", "scanned_at"],
                "rows": [["TEST-001", "101366", "OK", "2026-09-19T11:00:00"]],
            },
            "asgard": {"columns": ["cargo_place", "status"], "rows": []},
        }
        before_tabs = self.store.list_browser_tabs()
        before_events = self.store.list_events()
        response = handle_message({
            "type": "reconcile_site_tables", "request_id": "safe", "snapshots": snapshots,
        }, self.store)
        self.assertTrue(response["ok"])
        self.assertEqual(response["summary"]["found"], 1)
        self.assertEqual(response["type"], "site_tables_reconciled")
        self.assertFalse(response["persisted"])
        self.assertTrue(response["aggregate_persisted"])
        self.assertFalse(response["write_enabled"])
        self.assertNotIn("TEST-001", json.dumps(response))
        report = self.store.latest_browser_audit_summary()
        self.assertEqual(report["summary"]["found"], 1)
        self.assertEqual(report["total"], 1)
        self.assertNotIn("TEST-001", json.dumps(report))
        with self.store._session() as db:
            raw = db.execute("SELECT * FROM browser_audit_summary").fetchone()
            self.assertEqual(set(dict(raw)), {"id", "checked_at", "total",
                                               "found", "in_progress", "manual_review"})
        self.assertEqual(self.store.list_browser_tabs(), before_tabs)
        self.assertEqual(self.store.list_events(), before_events)
        snapshots["inventory"]["columns"] = ["unknown", "inventory_date"]
        bad = handle_message({"type": "reconcile_site_tables",
                              "snapshots": snapshots}, self.store)
        self.assertFalse(bad["ok"])

    def test_unknown_messages_are_rejected(self):
        response = handle_message({"type": "execute_script"}, self.store)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], "unsupported_message")


if __name__ == "__main__":
    unittest.main()
