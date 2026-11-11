import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

from workpilot.native_messaging import (
    HOST_NAME,
    configured_extension_id,
    handle_message,
    read_message,
    validate_origin,
    write_message,
)
from workpilot.store import TaskStore


class NativeMessagingProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp_dir.name) / "workpilot.sqlite3")

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
        self.assertEqual(response["capabilities"], ["share_active_tab"])
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

    def test_unknown_messages_are_rejected(self):
        response = handle_message({"type": "execute_script"}, self.store)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], "unsupported_message")


if __name__ == "__main__":
    unittest.main()
