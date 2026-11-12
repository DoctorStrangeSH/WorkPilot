"""Authenticated loopback HTTP API for the desktop shell."""

from __future__ import annotations

import hmac
import json
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .ai import OllamaClient, AIError
from .knowledge import KnowledgeBase, KnowledgeError
from .google_sheets import GoogleSheetsConnector, GoogleSheetsError
from .order_check import evaluate_order
from .permission_inbox import PermissionInbox
from .permissions import PermissionGate
from .resources import ResourceManager
from .store import TaskStore, SubmissionConflict


MAX_BODY_BYTES = 8 * 1024


class MaleniaHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows SO_REUSEADDR can allow two listeners to bind the same endpoint.
    allow_reuse_address = not hasattr(socket, "SO_EXCLUSIVEADDRUSE")

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_handler(store: TaskStore, token: str, resources: ResourceManager,
                 permissions: PermissionInbox | None = None, ai: OllamaClient | None = None,
                 google_sheets: GoogleSheetsConnector | None = None):
    inbox = permissions if permissions is not None else PermissionInbox(PermissionGate(store))
    knowledge = KnowledgeBase(store)
    ai_client = ai if ai is not None else OllamaClient()
    ai_client.knowledge = knowledge
    sheets = google_sheets if google_sheets is not None else GoogleSheetsConnector()

    class Handler(BaseHTTPRequestHandler):
        server_version = "MaleniaAgent/0.2"
        sys_version = ""

        def log_message(self, format: str, *args: object) -> None:
            # Avoid logging URLs, request bodies, or authorization headers.
            return

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _valid_host(self) -> bool:
            host = self.headers.get("Host", "")
            hostname = host.rsplit(":", 1)[0].strip("[]").lower()
            return hostname in {"127.0.0.1", "localhost"}

        def _authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            prefix = "Bearer "
            if not supplied.startswith(prefix):
                return False
            return hmac.compare_digest(supplied[len(prefix):], token)

        def _reject_access(self, status: int, error: str) -> None:
            # Windows can reset a closing socket with unread request data,
            # hiding the denial response. Discard only a bounded body, never
            # parse it, and cap waiting for an incomplete/untrusted request.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if 0 < length <= 32 * 1024:
                    self.connection.settimeout(0.25)
                    self.rfile.read(length)
            except (ValueError, OSError):
                pass
            self._send(status, {"error": error})

        def _require_access(self) -> bool:
            if not self._valid_host():
                self._reject_access(403, "invalid_host")
                return False
            if not self._authorized():
                self._reject_access(401, "unauthorized")
                return False
            return True

        def _read_json(self, max_bytes: int = MAX_BODY_BYTES) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send(400, {"error": "invalid_content_length"})
                return None
            if length <= 0 or length > max_bytes:
                self._send(413, {"error": "body_size_not_allowed"})
                return None
            try:
                raw = self.rfile.read(length)
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(400, {"error": "invalid_json"})
                return None
            if not isinstance(value, dict):
                self._send(400, {"error": "json_object_required"})
                return None
            return value

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path == "/health":
                self._send(200, {"status": "ok", "service": "malenia-agent", "version": "0.2.0"})
                return
            if not self._require_access():
                return

            if parsed.path == "/v1/runtime":
                self._send(200, {"release": "0.6.0", "protocol": 1,
                    "capabilities": ["local_chat", "task_idempotency", "explicit_knowledge", "knowledge_only", "public_search", "google_sheets_readonly"]})
            elif parsed.path == "/v1/knowledge":
                self._send(200, {"records": knowledge.list()})
            elif parsed.path == "/v1/ai/status":
                self._send(200, ai_client.status())
            elif parsed.path == "/v1/permissions":
                self._send(200, {"permissions": inbox.list_requests(), "execution_enabled": False})
            elif parsed.path == "/v1/integrations/google-sheets/status":
                self._send(200, sheets.status())
            elif parsed.path == "/v1/resources":
                self._send(200, {"resources": resources.snapshot().to_dict()})
            elif parsed.path == "/v1/tasks":
                query = parse_qs(parsed.query)
                try:
                    limit = int(query.get("limit", ["50"])[0])
                except ValueError:
                    limit = 50
                self._send(200, {"tasks": store.list_tasks(limit)})
            elif parsed.path == "/v1/events":
                query = parse_qs(parsed.query)
                try:
                    limit = int(query.get("limit", ["50"])[0])
                except ValueError:
                    limit = 50
                self._send(200, {"events": store.list_events(limit)})
            elif parsed.path == "/v1/browser/tabs":
                query = parse_qs(parsed.query)
                try:
                    limit = int(query.get("limit", ["20"])[0])
                except ValueError:
                    limit = 20
                self._send(200, {"tabs": store.list_browser_tabs(limit)})
            else:
                self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:
            if not self._require_access():
                return
            parsed = urlsplit(self.path)

            if parsed.path == "/v1/orders/preview":
                payload = self._read_json(16 * 1024)
                if payload is None:
                    return
                if set(payload) - {"order", "datalens_scans", "asgard_record"}:
                    self._send(422, {"error": "invalid_order_preview_payload"})
                    return
                if not isinstance(payload.get("order"), dict):
                    self._send(422, {"error": "order_required"})
                    return
                scans = payload.get("datalens_scans", [])
                if not isinstance(scans, list) or len(scans) > 100:
                    self._send(422, {"error": "invalid_datalens_scans"})
                    return
                asgard = payload.get("asgard_record")
                if asgard is not None and not isinstance(asgard, dict):
                    self._send(422, {"error": "invalid_asgard_record"})
                    return
                try:
                    proposal = evaluate_order(payload["order"], scans, asgard)
                except ValueError:
                    self._send(422, {"error": "invalid_order_preview_data"})
                    return
                self._send(200, {"proposal": proposal, "read_only": True, "source": "manual_input"})
                return

            if parsed.path in {
                "/v1/integrations/google-sheets/connect",
                "/v1/integrations/google-sheets/disconnect",
                "/v1/integrations/google-sheets/read",
            }:
                payload = self._read_json(32 * 1024)
                if payload is None:
                    return
                try:
                    if parsed.path.endswith("/connect"):
                        if set(payload) not in ({"client_id"}, {"client_id", "client_secret"}):
                            self._send(422, {"error": "invalid_google_oauth_client_id"})
                            return
                        result = sheets.start_connect(payload.get("client_id"), payload.get("client_secret"))
                    elif parsed.path.endswith("/disconnect"):
                        if payload:
                            self._send(422, {"error": "invalid_disconnect_payload"})
                            return
                        result = sheets.disconnect()
                    else:
                        if set(payload) != {"spreadsheet_id", "range"}:
                            self._send(422, {"error": "invalid_google_sheets_read_payload"})
                            return
                        result = sheets.read_values(payload.get("spreadsheet_id"), payload.get("range"))
                    self._send(200, result)
                except GoogleSheetsError as error:
                    status = 503 if error.code == "windows_credential_store_unavailable" else (
                        422 if error.code.startswith("invalid_") else 502
                    )
                    self._send(status, {"error": error.code})
                return

            if parsed.path in {"/v1/knowledge", "/v1/knowledge/import", "/v1/knowledge/delete", "/v1/knowledge/search"}:
                payload = self._read_json(32 * 1024)
                if payload is None:
                    return
                try:
                    if parsed.path == "/v1/knowledge":
                        result = {"record": knowledge.save(payload.get("request_id"), payload.get("title"),
                            payload.get("content"), payload.get("kind", "memory"))}
                    elif parsed.path.endswith("/search"):
                        result = {"sources": knowledge.retrieve(payload.get("query"), matched_only=True)}
                    elif parsed.path.endswith("/import"):
                        result = knowledge.import_folder(payload.get("folder"))
                    else:
                        record_id = payload.get("id")
                        if not isinstance(record_id, str) or re.fullmatch(r"[0-9a-f-]{36}", record_id) is None:
                            raise KnowledgeError("Некорректный идентификатор записи")
                        result = {"deleted": knowledge.delete(record_id)}
                    self._send(200, result)
                except KnowledgeError as error:
                    self._send(422, {"error": str(error)})
                return

            if parsed.path == "/v1/ai/chat":
                payload = self._read_json(32 * 1024)
                if payload is None:
                    return
                try:
                    self._send(200, ai_client.chat(payload))
                except AIError as error:
                    self._send(error.status, {"error": error.code})
                return

            match = re.fullmatch(r"/v1/permissions/([0-9a-fA-F-]{36})/decision", parsed.path)
            if match:
                payload = self._read_json()
                if payload is None:
                    return
                binding = payload.get("binding")
                decision = payload.get("decision")
                if (set(payload) != {"binding", "decision"}
                        or not isinstance(binding, str)
                        or re.fullmatch(r"[0-9a-f]{64}", binding) is None
                        or not isinstance(decision, str)
                        or decision not in {"allow", "deny", "revoke"}):
                    self._send(422, {"error": "invalid_permission_decision"})
                    return
                if not inbox.decide(match.group(1), binding, decision):
                    self._send(409, {"error": "permission_unavailable_or_changed"})
                    return
                self._send(200, {"updated": True, "execution_enabled": False})
                return

            if parsed.path == "/v1/tasks":
                payload = self._read_json()
                if payload is None:
                    return
                title = payload.get("title")
                description = payload.get("description", "")
                if not isinstance(title, str) or not title.strip() or len(title) > 200:
                    self._send(422, {"error": "title_required", "max_length": 200})
                    return
                if not isinstance(description, str) or len(description) > 2000:
                    self._send(422, {"error": "invalid_description", "max_length": 2000})
                    return
                request_id = payload.get("request_id")
                if request_id is not None and (not isinstance(request_id, str) or
                        re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", request_id) is None):
                    self._send(422, {"error": "invalid_request_id"})
                    return
                try:
                    task = store.create_task(title.strip(), description, request_id)
                except SubmissionConflict:
                    self._send(409, {"error": "request_content_changed"})
                    return
                self._send(201, {"task": task, "note": "Queued only; task execution is not implemented yet."})
                return

            match = re.fullmatch(r"/v1/tasks/([0-9a-fA-F-]{36})/cancel", parsed.path)
            if match:
                task = store.cancel_task(match.group(1))
                if task is None:
                    self._send(404, {"error": "task_not_found"})
                else:
                    self._send(200, {"task": task})
                return

            self._send(404, {"error": "not_found"})

    return Handler


def create_server(host: str, port: int, store: TaskStore, token: str) -> MaleniaHTTPServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Malenia API may only bind to loopback")
    gate = PermissionGate(store)
    inbox = PermissionInbox(gate)
    server = MaleniaHTTPServer((host, port), make_handler(store, token, ResourceManager(), inbox))
    try:
        # Only the runtime that successfully owns the socket can invalidate grants.
        gate.invalidate_open()
    except Exception:
        server.server_close()
        raise
    return server


def run_server(server: MaleniaHTTPServer) -> None:
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def serve(host: str, port: int, store: TaskStore, token: str) -> None:
    run_server(create_server(host, port, store, token))
