"""Authenticated loopback HTTP API for the desktop shell."""

from __future__ import annotations

import hmac
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .resources import ResourceManager
from .store import TaskStore


MAX_BODY_BYTES = 8 * 1024


class WorkPilotHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_handler(store: TaskStore, token: str, resources: ResourceManager):
    class Handler(BaseHTTPRequestHandler):
        server_version = "WorkPilotAgent/0.1"
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

        def _require_access(self) -> bool:
            if not self._valid_host():
                self._send(403, {"error": "invalid_host"})
                return False
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return False
            return True

        def _read_json(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send(400, {"error": "invalid_content_length"})
                return None
            if length <= 0 or length > MAX_BODY_BYTES:
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
                self._send(200, {"status": "ok", "service": "workpilot-agent", "version": "0.1.0"})
                return
            if not self._require_access():
                return

            if parsed.path == "/v1/resources":
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
                task = store.create_task(title.strip(), description)
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


def serve(host: str, port: int, store: TaskStore, token: str) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("WorkPilot API may only bind to loopback")
    server = WorkPilotHTTPServer((host, port), make_handler(store, token, ResourceManager()))
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
