import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from workpilot.resources import ResourceManager
from workpilot.server import WorkPilotHTTPServer, make_handler
from workpilot.store import TaskStore


class LocalApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp_dir.name) / "api.sqlite3")
        self.token = "test-only-token"
        self.server = WorkPilotHTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.store, self.token, ResourceManager()),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def test_health_is_available_without_token(self):
        with urlopen(f"{self.base_url}/health", timeout=2) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["status"], "ok")

    def test_private_endpoint_rejects_missing_token(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(f"{self.base_url}/v1/tasks", timeout=2)
        self.assertEqual(error.exception.code, 401)

    def test_authenticated_browser_tabs_endpoint_lists_shared_tabs(self):
        self.store.record_browser_tab("https://example.com/path", "Example")
        request = Request(
            f"{self.base_url}/v1/browser/tabs?limit=10",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["tabs"][0]["title"], "Example")
        self.assertEqual(payload["tabs"][0]["url"], "https://example.com/path")

    def test_authenticated_request_can_queue_task(self):
        body = json.dumps({"title": "Read-only check", "description": "Test"}).encode()
        request = Request(
            f"{self.base_url}/v1/tasks",
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read())
        self.assertEqual(response.status, 201)
        self.assertEqual(payload["task"]["title"], "Read-only check")
        self.assertIn("not implemented yet", payload["note"])


if __name__ == "__main__":
    unittest.main()
