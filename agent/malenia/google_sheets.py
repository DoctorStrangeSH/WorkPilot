"""Read-only Google Sheets connector for the local Malenia agent.

The connector uses an installed-app OAuth flow with PKCE and a one-use loopback
callback. Refresh tokens are stored only in Windows Credential Manager.
Only GET requests to the Sheets values API are implemented.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

from .google_oauth import (
    GOOGLE_SHEETS_READONLY_SCOPE,
    GOOGLE_TOKEN_ENDPOINT,
    GoogleOAuthError,
    build_authorization_url,
    create_oauth_state,
    create_pkce_verifier,
    parse_callback_target,
    validate_client_id,
    validate_client_secret,
    validate_refresh_response,
    validate_token_response,
)
from .secret_store import SecretStoreError, WindowsCredentialStore


_MAX_TOKEN_RESPONSE_BYTES = 64 * 1024
_MAX_SHEETS_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_SHEETS_CELLS = 50_000
_MAX_RANGE_LENGTH = 200
_SPREADSHEET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,256}$")
_REFRESH_TOKEN_KEY = "google-sheets-refresh-token"
_CLIENT_ID_KEY = "google-sheets-client-id"
_CLIENT_SECRET_KEY = "google-sheets-client-secret"


class GoogleSheetsError(RuntimeError):
    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class _ConnectAttempt:
    client_id: str
    client_secret: str | None
    state: str
    verifier: str
    redirect_uri: str
    server: HTTPServer
    event: threading.Event = field(default_factory=threading.Event)
    cancelled: bool = False
    code: str | None = None
    error: str | None = None
    status: str = "authorizing"
    thread: threading.Thread | None = None


class GoogleSheetsConnector:
    """Local OAuth and read-only Sheets API client; no write methods exist."""

    def __init__(
        self,
        credential_store=None,
        opener=None,
        callback_timeout: int = 300,
        clock=time.monotonic,
    ):
        self._store = credential_store
        self._opener = opener if opener is not None else build_opener(_NoRedirect())
        self._callback_timeout = max(30, min(int(callback_timeout), 600))
        self._clock = clock
        self._lock = threading.RLock()
        self._attempt: _ConnectAttempt | None = None
        self._access_token: str | None = None
        self._access_expires_at = 0.0

    def _credential_store(self):
        if self._store is None:
            try:
                self._store = WindowsCredentialStore()
            except SecretStoreError as error:
                raise GoogleSheetsError("windows_credential_store_unavailable") from error
        return self._store

    @staticmethod
    def _response(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
        body = message.encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "text/plain; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()
        handler.wfile.write(body)

    def start_connect(self, client_id: str, client_secret: str | None = None) -> dict[str, str]:
        try:
            client_id = validate_client_id(client_id)
            client_secret = validate_client_secret(client_secret)
        except GoogleOAuthError as error:
            raise GoogleSheetsError("invalid_google_oauth_client_id") from error
        self._credential_store()

        with self._lock:
            old = self._attempt
            if old is not None and old.status == "authorizing":
                old.cancelled = True
                old.status = "cancelled"
                old.event.set()
                old.server.server_close()

            state = create_oauth_state()
            verifier = create_pkce_verifier()
            session: dict[str, _ConnectAttempt] = {}

            class CallbackHandler(BaseHTTPRequestHandler):
                server_version = "MaleniaOAuth/1"
                sys_version = ""

                def log_message(self, format: str, *args: object) -> None:
                    return

                def do_GET(self) -> None:
                    attempt = session["attempt"]
                    expected_host = f"127.0.0.1:{attempt.server.server_port}"
                    if self.client_address[0] != "127.0.0.1" or self.headers.get("Host") != expected_host:
                        GoogleSheetsConnector._response(self, 403, "Недопустимый локальный запрос. Вернитесь в Malenia.")
                        return
                    try:
                        code = parse_callback_target(self.path, attempt.state)
                    except GoogleOAuthError as error:
                        if "authorization was not granted" in str(error):
                            attempt.error = "authorization_denied"
                            attempt.status = "denied"
                            attempt.event.set()
                            GoogleSheetsConnector._response(self, 200, "Доступ не предоставлен. Можно вернуться в Malenia.")
                        else:
                            GoogleSheetsConnector._response(self, 400, "Не удалось проверить ответ OAuth. Вернитесь в Malenia.")
                        return
                    attempt.code = code
                    attempt.event.set()
                    GoogleSheetsConnector._response(self, 200, "Malenia получила ответ Google. Можно закрыть эту вкладку и вернуться в приложение.")

            server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
            server.timeout = 1.0
            redirect_uri = f"http://127.0.0.1:{server.server_port}"
            try:
                auth_url = build_authorization_url(client_id, redirect_uri, state, verifier)
            except GoogleOAuthError as error:
                server.server_close()
                raise GoogleSheetsError("oauth_request_invalid") from error

            attempt = _ConnectAttempt(client_id, client_secret, state, verifier, redirect_uri, server)
            session["attempt"] = attempt
            self._attempt = attempt
            attempt.thread = threading.Thread(
                target=self._complete_connect,
                args=(attempt,),
                name="MaleniaGoogleOAuth",
                daemon=True,
            )
            attempt.thread.start()
            return {"status": "authorizing", "authorization_url": auth_url}

    def _complete_connect(self, attempt: _ConnectAttempt) -> None:
        deadline = self._clock() + self._callback_timeout
        try:
            while not attempt.event.is_set() and not attempt.cancelled and self._clock() < deadline:
                attempt.server.handle_request()
            attempt.server.server_close()
            if attempt.cancelled:
                attempt.status = "cancelled"
                return
            if attempt.error:
                attempt.status = "denied"
                return
            if not attempt.code:
                attempt.status = "expired"
                attempt.error = "authorization_timeout"
                return

            token_fields = {
                "client_id": attempt.client_id,
                "code": attempt.code,
                "code_verifier": attempt.verifier,
                "grant_type": "authorization_code",
                "redirect_uri": attempt.redirect_uri,
            }
            if attempt.client_secret:
                token_fields["client_secret"] = attempt.client_secret
            payload = self._post_form(GOOGLE_TOKEN_ENDPOINT, token_fields, _MAX_TOKEN_RESPONSE_BYTES)
            validated = validate_token_response(payload)
            store = self._credential_store()
            # Store the refresh token first. If storing the public client ID fails,
            # remove the token so the pair cannot be left half-configured.
            store.set(_REFRESH_TOKEN_KEY, str(validated["refresh_token"]))
            try:
                store.set(_CLIENT_ID_KEY, attempt.client_id)
                if attempt.client_secret:
                    store.set(_CLIENT_SECRET_KEY, attempt.client_secret)
                else:
                    store.delete(_CLIENT_SECRET_KEY)
            except Exception:
                store.delete(_REFRESH_TOKEN_KEY)
                store.delete(_CLIENT_ID_KEY)
                store.delete(_CLIENT_SECRET_KEY)
                raise
            with self._lock:
                self._access_token = str(validated["access_token"])
                self._access_expires_at = self._clock() + int(validated["expires_in"]) - 60
            attempt.status = "connected"
            attempt.error = None
        except GoogleOAuthError:
            attempt.status = "error"
            attempt.error = "oauth_response_invalid"
        except GoogleSheetsError as error:
            attempt.status = "error"
            attempt.error = error.code
        except Exception:
            attempt.status = "error"
            attempt.error = "oauth_connection_failed"
        finally:
            try:
                attempt.server.server_close()
            except OSError:
                pass

    def status(self) -> dict[str, Any]:
        with self._lock:
            attempt = self._attempt
            if attempt is not None and attempt.status == "authorizing":
                return {"connected": False, "status": "authorizing", "error": None}
        try:
            store = self._credential_store()
            connected = bool(
                store.get(_REFRESH_TOKEN_KEY)
                and store.get(_CLIENT_ID_KEY)
            )
        except GoogleSheetsError:
            return {"connected": False, "status": "unavailable", "error": "windows_credential_store_unavailable"}
        if connected:
            # A stored OAuth grant is not yet a verified source connection.
            # The UI marks a selected spreadsheet as connected only after a
            # successful read of its explicitly selected range.
            return {"connected": False, "status": "authorized", "error": None}
        with self._lock:
            attempt = self._attempt
            if attempt is not None and attempt.status in {"denied", "expired", "error"}:
                return {"connected": False, "status": attempt.status, "error": attempt.error}
        return {"connected": False, "status": "not_connected", "error": None}

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            attempt = self._attempt
            if attempt is not None and attempt.status == "authorizing":
                attempt.cancelled = True
                attempt.status = "cancelled"
                attempt.event.set()
                attempt.server.server_close()
            self._access_token = None
            self._access_expires_at = 0.0
        store = self._credential_store()
        refresh_deleted = store.delete(_REFRESH_TOKEN_KEY)
        client_deleted = store.delete(_CLIENT_ID_KEY)
        secret_deleted = store.delete(_CLIENT_SECRET_KEY)
        return {
            "connected": False,
            "status": "not_connected",
            "local_credentials_deleted": bool(refresh_deleted or client_deleted or secret_deleted),
            "note": "Локальные токены удалены. Если нужно отозвать доступ полностью, сделайте это в настройках Google Account.",
        }

    def _post_form(self, url: str, fields: dict[str, str], max_bytes: int) -> dict[str, Any]:
        body = urlencode(fields).encode("ascii")
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        return self._request_json(request, max_bytes)

    def _request_json(self, request: Request, max_bytes: int) -> dict[str, Any]:
        try:
            with self._opener.open(request, timeout=20) as response:
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise GoogleSheetsError("google_response_too_large")
                if response.status < 200 or response.status >= 300:
                    raise GoogleSheetsError("google_request_failed", response.status)
        except HTTPError as error:
            status = int(error.code)
            try:
                error.close()
            except Exception:
                pass
            raise GoogleSheetsError("google_request_failed", status) from error
        except URLError as error:
            raise GoogleSheetsError("google_network_unavailable") from error
        except TimeoutError as error:
            raise GoogleSheetsError("google_request_timeout") from error
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GoogleSheetsError("google_response_invalid") from error
        if not isinstance(payload, dict):
            raise GoogleSheetsError("google_response_invalid")
        return payload

    def _refresh_access_token(self) -> str:
        store = self._credential_store()
        refresh_token = store.get(_REFRESH_TOKEN_KEY)
        client_id = store.get(_CLIENT_ID_KEY)
        if not refresh_token or not client_id:
            raise GoogleSheetsError("google_sheets_not_connected")
        refresh_fields = {
            "client_id": client_id,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        client_secret = store.get(_CLIENT_SECRET_KEY)
        if client_secret:
            refresh_fields["client_secret"] = client_secret
        payload = self._post_form(GOOGLE_TOKEN_ENDPOINT, refresh_fields, _MAX_TOKEN_RESPONSE_BYTES)
        try:
            validated = validate_refresh_response(payload)
        except GoogleOAuthError as error:
            raise GoogleSheetsError("google_refresh_response_invalid") from error
        with self._lock:
            self._access_token = str(validated["access_token"])
            self._access_expires_at = self._clock() + int(validated["expires_in"]) - 60
            return self._access_token

    def _get_access_token(self) -> str:
        with self._lock:
            if self._access_token and self._clock() < self._access_expires_at:
                return self._access_token
        return self._refresh_access_token()

    def read_values(self, spreadsheet_id: str, range_a1: str) -> dict[str, Any]:
        """Read one explicitly selected A1 range. No mutation endpoints exist."""
        if not isinstance(spreadsheet_id, str) or _SPREADSHEET_ID_RE.fullmatch(spreadsheet_id) is None:
            raise GoogleSheetsError("invalid_spreadsheet_id")
        if (
            not isinstance(range_a1, str)
            or not range_a1.strip()
            or len(range_a1) > _MAX_RANGE_LENGTH
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in range_a1)
        ):
            raise GoogleSheetsError("invalid_spreadsheet_range")
        encoded_range = quote(range_a1.strip(), safe="!:$'")
        url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{encoded_range}"
            "?majorDimension=ROWS&valueRenderOption=UNFORMATTED_VALUE"
        )
        token = self._get_access_token()
        request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, method="GET")
        try:
            payload = self._request_json(request, _MAX_SHEETS_RESPONSE_BYTES)
        except GoogleSheetsError as error:
            if error.status != 401:
                raise
            token = self._refresh_access_token()
            retry = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, method="GET")
            payload = self._request_json(retry, _MAX_SHEETS_RESPONSE_BYTES)

        values = payload.get("values", [])
        if not isinstance(values, list) or any(not isinstance(row, list) for row in values):
            raise GoogleSheetsError("google_sheets_values_invalid")
        cell_count = sum(len(row) for row in values)
        if len(values) > 1000 or cell_count > _MAX_SHEETS_CELLS:
            raise GoogleSheetsError("google_sheets_range_too_large")
        return {
            "range": payload.get("range", range_a1.strip()),
            "majorDimension": payload.get("majorDimension", "ROWS"),
            "values": values,
            "read_only": True,
        }
