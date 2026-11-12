import json
import tempfile
import threading
import unittest
from unittest.mock import Mock
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from malenia.ai import OllamaClient
from malenia.browser_permissions import BrowserPermissionSession
from malenia.permission_inbox import PermissionInbox
from malenia.permissions import PermissionGate
from malenia.resources import ResourceManager
from malenia.server import MaleniaHTTPServer, make_handler
from malenia.store import TaskStore


class FakeGoogleSheets:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"connected": False, "status": "not_connected", "error": None}

    def start_connect(self, client_id, client_secret=None):
        self.calls.append(("connect", client_id, client_secret))
        return {"status": "authorizing", "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?fixture"}

    def read_values(self, spreadsheet_id, range_a1):
        self.calls.append(("read", spreadsheet_id, range_a1))
        return {"range": range_a1, "values": [["fixture"]], "read_only": True}

    def disconnect(self):
        self.calls.append(("disconnect",))
        return {"connected": False, "status": "not_connected", "local_credentials_deleted": True}


class LocalApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp_dir.name) / "api.sqlite3")
        self.token = "test-only-token"
        self.now = 1000.0
        self.gate = PermissionGate(self.store, lambda: self.now, lambda: self.now)
        self.inbox = PermissionInbox(self.gate)
        self.ai = OllamaClient()
        self.google_sheets = FakeGoogleSheets()
        self.server = MaleniaHTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.store, self.token, ResourceManager(), self.inbox, self.ai, self.google_sheets),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def api(self, path, body=None, authenticated=True, host=None):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.token}"
        if host:
            headers["Host"] = host
        request = Request(self.base_url + path, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        try:
            response = urlopen(request, timeout=2)
        except HTTPError as error:
            response = error
        with response:
            return response.code, json.loads(response.read())

    def permission(self):
        item = self.inbox.request("browser.read_text", 7, "doc-test", {"selector": "main"})
        state = self.api("/v1/permissions")[1]["permissions"][0]
        self.assertEqual(state["id"], item)
        return f"/v1/permissions/{item}/decision", state["binding"]

    def test_browser_audit_summary_requires_auth_and_contains_only_counts(self):
        code, initial = self.api("/v1/browser/audit-summary")
        self.assertEqual(code, 200)
        self.assertIsNone(initial["audit"])
        self.assertFalse(initial["source_records_persisted"])
        self.assertEqual(self.api("/v1/browser/audit-summary",
                                  authenticated=False)[0], 401)
        self.store.record_browser_audit_summary(
            2, {"found": 1, "in_progress": 1, "manual_review": 0})
        code, report = self.api("/v1/browser/audit-summary")
        self.assertEqual(code, 200)
        self.assertEqual(report["audit"]["total"], 2)
        self.assertEqual(report["audit"]["summary"]["found"], 1)
        self.assertNotIn("cargo_place", json.dumps(report))
        self.assertNotIn("rows", json.dumps(report))

    def test_internal_browser_request_http_approval_and_local_preparation(self):
        browser = BrowserPermissionSession(self.inbox)
        connection = browser.connect()
        browser.select_document(connection, 0, 7, "document-fixture")
        item = browser.request("browser.read_text", {"selector": "main"})
        state = self.api("/v1/permissions")[1]["permissions"][0]
        self.assertEqual(self.api(f"/v1/permissions/{item}/decision",
            {"binding": state["binding"], "decision": "allow"})[0], 200)
        prepared = browser.prepare(item)
        self.assertEqual(prepared.action.document_id, "document-fixture")
        self.assertEqual(prepared.action.parameters, {"selector": "main"})
        self.assertIsNone(browser.prepare(item))
        self.assertEqual(self.api("/v1/permissions")[1]["permissions"][0]["status"], "consumed")

    def test_permission_request_decision_and_replay_path(self):
        path, binding = self.permission()
        code, payload = self.api("/v1/permissions")
        self.assertEqual(code, 200)
        self.assertFalse(payload["execution_enabled"])
        self.assertEqual(payload["permissions"][0]["parameters"], {"selector": "main"})
        self.assertEqual(self.api(path, {"binding": binding, "decision": "allow"})[0], 200)
        self.assertEqual(self.api(path, {"binding": binding, "decision": "allow"})[0], 409)
        self.assertEqual(self.api(path, {"binding": binding, "decision": "revoke"})[0], 200)
        self.assertEqual(self.api("/v1/permissions")[1]["permissions"][0]["status"], "revoked")

    def test_permission_authentication_and_host_are_required(self):
        path, binding = self.permission()
        body = {"binding": binding, "decision": "allow"}
        self.assertEqual(self.api("/v1/permissions", authenticated=False)[0], 401)
        self.assertEqual(self.api(path, body, authenticated=False)[0], 401)
        self.assertEqual(self.api(path, body, host="foreign.example:8765")[0], 403)
        self.assertEqual(self.inbox.list_requests()[0]["status"], "pending")

    def test_permission_expiry_is_visible_without_a_decision(self):
        path, binding = self.permission()
        self.now += 60
        self.assertEqual(self.api("/v1/permissions")[1]["permissions"][0]["status"], "expired")
        self.assertEqual(self.api(path, {"binding": binding, "decision": "allow"})[0], 409)

    def test_permission_rejects_changed_binding_and_invalid_decisions(self):
        path, binding = self.permission()
        self.assertEqual(self.api(path, {"binding": "0" * 64, "decision": "allow"})[0], 409)
        for body in ({"binding": binding, "decision": True},
                     {"binding": binding, "decision": "consume"},
                     {"binding": binding, "decision": "allow", "tab_id": 99},
                     {"binding": "x", "decision": "allow"}):
            with self.subTest(body=body):
                self.assertEqual(self.api(path, body)[0], 422)
        self.assertEqual(self.inbox.list_requests()[0]["status"], "pending")

    def test_no_public_request_creation_or_consumption(self):
        self.assertEqual(self.api("/v1/permissions", {"capability": "browser.read_text"})[0], 404)
        path, _ = self.permission()
        self.assertEqual(self.api(path.replace("decision", "consume"), {})[0], 404)

    def test_chat_requires_authentication_and_uses_only_explicit_messages(self):
        self.ai._request = Mock(side_effect=[{"models":[{"name":"qwen2.5:0.5b"}]},
            {"done":True,"message":{"role":"assistant","content":"fixture reply"}}])
        body={"model":"qwen2.5:0.5b","messages":[{"role":"user","content":"fixture"}]}
        self.assertEqual(self.api("/v1/ai/chat",body,authenticated=False)[0],401)
        self.ai._request.assert_not_called()
        code,result=self.api("/v1/ai/chat",body)
        self.assertEqual(code,200)
        self.assertFalse(result["tools_enabled"])
        self.assertEqual(self.store.list_events(),[])
        self.assertEqual(self.store.list_tasks(),[])

    def test_ai_status_is_private_and_invalid_chat_is_rejected(self):
        self.assertEqual(self.api("/v1/ai/status",authenticated=False)[0],401)
        self.ai._request=Mock()
        self.assertEqual(self.api("/v1/ai/chat",{"model":"remote","messages":[]})[0],422)
        self.ai._request.assert_not_called()

    def test_batch_order_preview_requires_auth_and_never_writes(self):
        path = "/v1/orders/batch-preview"
        rows = [{
            "source_row": 10,
            "order": {"cargo_place": "TEST-BOX-001", "inventory_date": "2026-09-12"},
            "datalens_scans": [{
                "main_partner_code_original": "TEST-BOX-001",
                "sc_id": "101366", "result": "OK", "scanned_at": "2026-09-26"
            }],
            "asgard_record": None
        }, {
            "source_row": 11,
            "order": {"cargo_place": "TEST-BOX-002", "inventory_date": "2026-09-12"},
            "datalens_scans": [],
            "asgard_record": {"status": "Выдан"}
        }]
        body = {"rows": rows}
        self.assertEqual(self.api(path, body, authenticated=False)[0], 401)
        self.assertEqual(self.api(path, body, host="foreign.example:8765")[0], 403)
        code, data = self.api(path, body)
        self.assertEqual(code, 200)
        self.assertEqual(data["summary"], {"found": 1, "in_progress": 1, "manual_review": 0})
        self.assertEqual(data["results"][0]["source_row"], 10)
        self.assertEqual(data["results"][1]["proposal"]["comment"], "Выдан")
        self.assertTrue(data["read_only"])
        self.assertFalse(data["write_enabled"])
        self.assertEqual(self.store.list_tasks(), [])
        self.assertEqual(self.store.list_events(), [])

    def test_batch_order_preview_rejects_unknown_or_excessive_payloads(self):
        path = "/v1/orders/batch-preview"
        for payload in (
            {}, {"rows": []}, {"rows": "wrong"},
            {"rows": [{}] * 101}, {"rows": [], "extra": True},
            {"rows": [{"order": {"cargo_place": "", "inventory_date": "x"}}]},
        ):
            with self.subTest(payload=str(payload)[:60]):
                self.assertEqual(self.api(path, payload)[0], 422)

    def test_manual_order_preview_is_authenticated_and_never_persists(self):
        path = "/v1/orders/preview"
        order = {"cargo_place": "BOX-TEST-1", "inventory_date": "2026-09-26"}
        scans = [{
            "main_partner_code_original": "BOX-TEST-1",
            "sc_id": 101366,
            "result": "OK",
            "scanned_at": "2026-10-01T08:10:00"
        }]
        body = {"order": order, "datalens_scans": scans}
        self.assertEqual(self.api(path, body, authenticated=False)[0], 401)
        self.assertEqual(self.api(path, body, host="foreign.example:8765")[0], 403)
        status, response = self.api(path, body)
        self.assertEqual(status, 200)
        self.assertEqual(response["source"], "manual_input")
        self.assertTrue(response["read_only"])
        self.assertEqual(response["proposal"]["proposed_status"], "Найден")
        self.assertFalse(response["proposal"]["write_enabled"])
        self.assertEqual(self.store.list_tasks(), [])
        self.assertEqual(self.store.list_events(), [])

    def test_order_preview_fails_closed_on_invalid_or_excessive_input(self):
        path = "/v1/orders/preview"
        valid = {"order": {"cargo_place": "BOX-TEST", "inventory_date": "2026-09-26"}}
        for payload in (
            {},
            {"order": "invalid"},
            {**valid, "datalens_scans": "invalid"},
            {**valid, "datalens_scans": [{}] * 101},
            {**valid, "asgard_record": []},
            {**valid, "not_allowed": True},
            {"order": {"cargo_place": "BOX-TEST", "inventory_date": "not-a-date"}},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.api(path, payload)[0], 422)

    def test_manual_order_preview_uses_asgard_rules_without_data_writes(self):
        path = "/v1/orders/preview"
        body = {
            "order": {"cargo_place": "BOX-TEST-2", "inventory_date": "2026-09-26"},
            "datalens_scans": [],
            "asgard_record": {
                "status": "В пути",
                "box_id": "BOX-TEST-2",
                "extended_history_statuses": ["В пути", "Выдан"],
            },
        }
        status, response = self.api(path, body)
        self.assertEqual(status, 200)
        self.assertEqual(response["proposal"]["comment"], "2 ШК Выдан")
        self.assertEqual(response["proposal"]["proposed_status"], "В работе")
        self.assertFalse(response["proposal"]["write_enabled"])
        self.assertEqual(self.store.list_tasks(), [])

    def test_google_sheets_routes_are_authenticated_and_read_only(self):
        status_path = "/v1/integrations/google-sheets/status"
        connect_path = "/v1/integrations/google-sheets/connect"
        read_path = "/v1/integrations/google-sheets/read"
        disconnect_path = "/v1/integrations/google-sheets/disconnect"

        self.assertEqual(self.api(status_path, authenticated=False)[0], 401)
        self.assertEqual(self.api(connect_path, {"client_id": "fixture"}, authenticated=False)[0], 401)
        self.assertEqual(self.api(status_path)[1]["status"], "not_connected")
        self.assertEqual(self.api(connect_path, {"client_id": "fixture", "extra": "no"})[0], 422)

        code, auth = self.api(connect_path, {"client_id": "fixture"})
        self.assertEqual(code, 200)
        self.assertEqual(auth["status"], "authorizing")
        self.assertTrue(auth["authorization_url"].startswith("https://accounts.google.com/"))
        self.assertIn(("connect", "fixture", None), self.google_sheets.calls)
        self.assertEqual(self.api(connect_path, {"client_id": "fixture", "client_secret": "optional"})[0], 200)
        self.assertIn(("connect", "fixture", "optional"), self.google_sheets.calls)

        self.assertEqual(self.api(read_path, {"spreadsheet_id": "fixture"})[0], 422)
        code, read = self.api(read_path, {"spreadsheet_id": "sheet-id-fixture", "range": "Orders!A1:B2"})
        self.assertEqual(code, 200)
        self.assertTrue(read["read_only"])
        self.assertEqual(read["values"], [["fixture"]])
        self.assertIn(("read", "sheet-id-fixture", "Orders!A1:B2"), self.google_sheets.calls)

        self.assertEqual(self.api("/v1/integrations/google-sheets/write", {})[0], 404)
        self.assertEqual(self.api(disconnect_path, {"unexpected": True})[0], 422)
        self.assertEqual(self.api(disconnect_path, {})[0], 200)
        self.assertIn(("disconnect",), self.google_sheets.calls)

    def test_google_sheets_routes_reject_foreign_hosts(self):
        self.assertEqual(
            self.api("/v1/integrations/google-sheets/status", host="foreign.example:8765")[0],
            403,
        )

    def test_runtime_descriptor_requires_authentication(self):
        self.assertEqual(self.api("/v1/runtime", authenticated=False)[0], 401)
        code, runtime = self.api("/v1/runtime")
        self.assertEqual(code, 200)
        self.assertEqual(runtime["release"], "0.6.0")
        self.assertEqual(runtime["protocol"], 1)
        self.assertIn("task_idempotency", runtime["capabilities"])
        self.assertIn("google_sheets_readonly", runtime["capabilities"])
        self.assertIn("order_preview", runtime["capabilities"])
        self.assertIn("order_batch_preview", runtime["capabilities"])

    def test_task_retry_conflict_validation_and_legacy_compatibility(self):
        body = {"title": "Reviewed", "description": "Text",
                "request_id": "a1234567-1234-1234-1234-123456789abc"}
        self.assertEqual(self.api("/v1/tasks", body, authenticated=False)[0], 401)
        first = self.api("/v1/tasks", body)
        retry = self.api("/v1/tasks", body)
        self.assertEqual(first[0], 201)
        self.assertEqual(first[1]["task"]["id"], retry[1]["task"]["id"])
        self.assertEqual(self.api("/v1/tasks", {**body, "title": "Changed"})[0], 409)
        for invalid in ("", "not-a-uuid", 42, True, [], {}, body["request_id"].upper()):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.api("/v1/tasks", {**body, "request_id": invalid})[0], 422)
        self.assertEqual(len(self.store.list_tasks()), 1)
        self.assertEqual(len(self.store.list_events()), 1)
        self.assertEqual(self.api("/v1/tasks", {"title": "Legacy"})[0], 201)
        self.assertEqual(self.api("/v1/tasks", {"title": "Null", "request_id": None})[0], 201)

    def test_knowledge_api_auth_save_retrieve_delete_and_no_implicit_chat_learning(self):
        body={"request_id":"b1234567-1234-1234-1234-123456789abc","title":"Проверка заказа",
              "content":"Не выдумывать адрес доставки","kind":"memory"}
        self.assertEqual(self.api("/v1/knowledge",authenticated=False)[0],401)
        self.assertEqual(self.api("/v1/knowledge",body,authenticated=False)[0],401)
        self.assertEqual(self.api("/v1/knowledge",body)[0],200)
        self.assertEqual(self.api("/v1/knowledge",body)[0],200)
        self.assertEqual(len(self.api("/v1/knowledge")[1]["records"]),1)
        self.ai._request=Mock(side_effect=[{"models":[{"name":"qwen2.5:0.5b"}]},
            {"done":True,"message":{"role":"assistant","content":"fixture"}}])
        result=self.api("/v1/ai/chat",{"model":"qwen2.5:0.5b","messages":[{"role":"user","content":"Проверь заказ"}]})
        self.assertEqual(result[0],200)
        self.assertEqual(len(result[1]["sources"]),1)
        self.assertEqual(len(self.api("/v1/knowledge")[1]["records"]),1)
        self.assertEqual(self.api("/v1/knowledge/delete",{"id":body["request_id"]})[0],200)
        self.assertEqual(self.api("/v1/knowledge")[1]["records"],[])
        self.assertEqual(self.api("/v1/knowledge/import",{"folder":"relative"})[0],422)

    def test_knowledge_search_and_empty_strict_chat_are_private_and_do_not_generate(self):
        self.assertEqual(self.api("/v1/knowledge/search",{"query":"AB-17"},authenticated=False)[0],401)
        for query in (None,[],"", "x"*2001):
            self.assertEqual(self.api("/v1/knowledge/search",{"query":query})[0],422)
        self.assertEqual(self.api("/v1/knowledge/search",{"query":"AB-17"})[1]["sources"],[])
        self.ai._request=Mock()
        code,result=self.api("/v1/ai/chat",{"model":"qwen3:8b","messages":[{"role":"user","content":"Адрес AB-17"}],"knowledge_only":True})
        self.assertEqual(code,200)
        self.assertFalse(result["generated"])
        self.ai._request.assert_not_called()
        self.assertEqual(self.api("/v1/knowledge")[1]["records"],[])

    def test_health_is_available_without_token(self):
        with urlopen(f"{self.base_url}/health", timeout=2) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "malenia-agent")
        self.assertEqual(payload["version"], "0.2.0")

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
