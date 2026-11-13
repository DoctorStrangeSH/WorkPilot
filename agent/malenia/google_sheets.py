"""Google Sheets editor connector for the local Malenia agent.

The connector uses an installed-app OAuth flow with PKCE and a one-use loopback
callback. Refresh tokens are stored only in Windows Credential Manager.
Reads are available directly; writes are bounded literal-value operations behind an approval API gate.
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
from urllib.parse import parse_qs, quote, urlencode, urlsplit
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
_MAX_SHEETS_CELLS = 100_000
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
    """Local OAuth and bounded Google Sheets API client."""

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
        self._reauthorization_required = False

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

    @staticmethod
    def _callback_bridge(handler: BaseHTTPRequestHandler) -> None:
        # Google documents state in the redirect fragment. Fragments are not
        # sent in HTTP requests, so this tiny same-origin page forwards only
        # the query+fragment parameters back to the loopback listener.
        body = """<!doctype html><html><head><meta charset="utf-8"><meta name="referrer" content="no-referrer"><title>Malenia OAuth</title></head><body><p id="message">Проверяем ответ Google…</p><script>
const params = new URLSearchParams(window.location.search);
const fragment = new URLSearchParams(window.location.hash.slice(1));
for (const [key, value] of fragment) { if (!params.has(key)) params.append(key, value); }
fetch("/", {method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"}, body:params.toString()})
  .then(response => { document.getElementById("message").textContent = response.ok ? "Ответ получен. Вернитесь в Malenia." : "Не удалось проверить ответ. Вернитесь в Malenia."; })
  .catch(() => { document.getElementById("message").textContent = "Не удалось связаться с Malenia. Вернитесь в приложение."; });
</script></body></html>""".encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Referrer-Policy", "no-referrer")
        handler.send_header("X-Frame-Options", "DENY")
        handler.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; connect-src 'self'")
        handler.end_headers()
        handler.wfile.write(body)

    def start_connect(self, client_id: str, client_secret: str | None = None) -> dict[str, str]:
        try:
            client_id = validate_client_id(client_id)
            client_secret = validate_client_secret(client_secret)
        except GoogleOAuthError as error:
            raise GoogleSheetsError("invalid_google_oauth_client_id") from error
        store = self._credential_store()
        if client_secret is None and store.get(_CLIENT_ID_KEY) == client_id:
            # Reuse an optional secret already stored for this same public client.
            client_secret = store.get(_CLIENT_SECRET_KEY)

        with self._lock:
            old = self._attempt
            if old is not None and old.status == "authorizing":
                old.cancelled = True
                old.status = "cancelled"
                old.event.set()

            state = create_oauth_state()
            verifier = create_pkce_verifier()
            session: dict[str, _ConnectAttempt] = {}

            class CallbackHandler(BaseHTTPRequestHandler):
                server_version = "MaleniaOAuth/1"
                sys_version = ""

                def log_message(self, format: str, *args: object) -> None:
                    return

                def _valid_local_request(self, attempt: _ConnectAttempt) -> bool:
                    expected_host = f"127.0.0.1:{attempt.server.server_port}"
                    return self.client_address[0] == "127.0.0.1" and self.headers.get("Host") == expected_host

                def _accept_callback(self, attempt: _ConnectAttempt, target: str) -> None:
                    try:
                        code = parse_callback_target(target, attempt.state)
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

                def do_GET(self) -> None:
                    attempt = session["attempt"]
                    if not self._valid_local_request(attempt):
                        GoogleSheetsConnector._response(self, 403, "Недопустимый локальный запрос. Вернитесь в Malenia.")
                        return
                    parsed = urlsplit(self.path)
                    if parsed.path != "/":
                        GoogleSheetsConnector._response(self, 404, "Неизвестный адрес.")
                        return
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    if "state" not in query or ("code" not in query and "error" not in query):
                        GoogleSheetsConnector._callback_bridge(self)
                        return
                    self._accept_callback(attempt, self.path)

                def do_POST(self) -> None:
                    attempt = session["attempt"]
                    if not self._valid_local_request(attempt):
                        GoogleSheetsConnector._response(self, 403, "Недопустимый локальный запрос. Вернитесь в Malenia.")
                        return
                    if self.headers.get_content_type() != "application/x-www-form-urlencoded":
                        GoogleSheetsConnector._response(self, 415, "Недопустимый формат OAuth-ответа.")
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except ValueError:
                        length = 0
                    if length < 1 or length > 8192:
                        GoogleSheetsConnector._response(self, 413, "Слишком большой OAuth-ответ.")
                        return
                    try:
                        form = self.rfile.read(length).decode("ascii")
                    except UnicodeDecodeError:
                        GoogleSheetsConnector._response(self, 400, "Некорректный OAuth-ответ.")
                        return
                    self._accept_callback(attempt, "/?" + form)

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
            with self._lock:
                if attempt.cancelled:
                    attempt.status = "cancelled"
                    return
                # Serialize persistence with disconnect so a late OAuth callback
                # cannot recreate credentials after the user disconnects.
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
                self._access_token = str(validated["access_token"])
                self._access_expires_at = self._clock() + int(validated["expires_in"]) - 60
                self._reauthorization_required = False
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
            # Do not retain one-use authorization material after completion.
            attempt.code = None
            attempt.verifier = ""
            attempt.state = ""
            attempt.client_secret = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            attempt = self._attempt
            if attempt is not None and attempt.status == "authorizing":
                return {"connected": False, "status": "authorizing", "error": None}
            reauthorization_required = self._reauthorization_required
        try:
            store = self._credential_store()
            client_id = store.get(_CLIENT_ID_KEY)
            connected = bool(store.get(_REFRESH_TOKEN_KEY) and client_id)
        except GoogleSheetsError:
            return {"connected": False, "status": "unavailable", "error": "windows_credential_store_unavailable"}
        if reauthorization_required:
            return {
                "connected": False,
                "status": "reauthorization_required",
                "error": "google_reauthorization_required",
                "client_id": client_id,
            }
        if connected:
            # A stored OAuth grant is not yet a verified source connection.
            # The UI marks a selected spreadsheet as connected only after a
            # successful read of its explicitly selected range.
            return {"connected": False, "status": "authorized", "error": None, "client_id": client_id}
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
            self._attempt = None
            self._access_token = None
            self._access_expires_at = 0.0
            self._reauthorization_required = False
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
                raw_error = error.read(_MAX_TOKEN_RESPONSE_BYTES + 1)
            except Exception:
                raw_error = b""
            try:
                error.close()
            except Exception:
                pass
            error_code = None
            try:
                parsed_error = json.loads(raw_error.decode("utf-8"))
                if isinstance(parsed_error, dict):
                    error_code = parsed_error.get("error")
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            if error_code == "invalid_grant":
                raise GoogleSheetsError("google_reauthorization_required", status) from error
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
        try:
            payload = self._post_form(GOOGLE_TOKEN_ENDPOINT, refresh_fields, _MAX_TOKEN_RESPONSE_BYTES)
        except GoogleSheetsError as error:
            if error.code == "google_reauthorization_required":
                with self._lock:
                    self._reauthorization_required = True
                    self._access_token = None
                    self._access_expires_at = 0.0
            raise
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

    def read_active_sheet(self, spreadsheet_url: str, gid: str | None = None) -> dict[str, Any]:
        """Resolve an explicitly shared Google Sheets tab and read its used grid."""
        from urllib.parse import parse_qs, urlsplit
        try:
            parsed = urlsplit(spreadsheet_url)
            match = re.fullmatch(r"/spreadsheets/d/([A-Za-z0-9_-]{10,256})/edit/?", parsed.path)
            query = parse_qs(parsed.query)
            spreadsheet_id = match.group(1) if match else ""
            selected_gid = gid or (query.get("gid", [None])[0])
            if (parsed.scheme != "https" or parsed.hostname != "docs.google.com"
                    or parsed.username or parsed.password or parsed.fragment
                    or (selected_gid is not None and not re.fullmatch(r"\d{1,16}", selected_gid))):
                raise ValueError
        except (ValueError, TypeError):
            raise GoogleSheetsError("invalid_google_sheets_url") from None
        if not spreadsheet_id:
            raise GoogleSheetsError("invalid_google_sheets_url")
        token = self._get_access_token()
        metadata_url = (f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
                        "?fields=properties.title,sheets.properties")
        request = Request(metadata_url, headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/json"}, method="GET")
        metadata = self._request_json(request, _MAX_SHEETS_RESPONSE_BYTES)
        sheets = metadata.get("sheets")
        if not isinstance(sheets, list) or not sheets or len(sheets) > 100:
            raise GoogleSheetsError("google_sheets_metadata_invalid")
        selected = None
        for item in sheets:
            properties = item.get("properties", {}) if isinstance(item, dict) else {}
            if selected_gid is not None and str(properties.get("sheetId")) == selected_gid:
                selected = properties
                break
        if selected_gid is None:
            # If the browser did not provide a gid, select only a tab with a
            # recognizable INVenta header signature; prefer non-archive tabs.
            from .inventa import detect_header
            candidates = sorted(
                [item.get("properties", {}) for item in sheets if isinstance(item, dict)],
                key=lambda p: ("архив" in str(p.get("title", "")).casefold(),
                               int(p.get("index", 9999))),
            )
            for properties in candidates[:20]:
                title = properties.get("title")
                if not isinstance(title, str) or not title:
                    continue
                sample = self.read_values(spreadsheet_id, f"'{title.replace(chr(39), chr(39)*2)}'!A1:Z12")
                try:
                    detect_header(sample["values"])
                    selected = properties
                    break
                except ValueError:
                    continue
        if not isinstance(selected, dict):
            raise GoogleSheetsError("google_sheets_tab_not_detected")
        title = selected.get("title")
        sheet_id = selected.get("sheetId")
        if not isinstance(title, str) or not isinstance(sheet_id, int):
            raise GoogleSheetsError("google_sheets_metadata_invalid")
        escaped_title = title.replace("'", "''")
        values = self.read_values(spreadsheet_id, f"'{escaped_title}'!A:Z")
        return {"spreadsheet_id": spreadsheet_id, "spreadsheet_title": metadata.get("properties", {}).get("title", ""),
                "sheet_title": title, "sheet_id": sheet_id, "range": values["range"],
                "values": values["values"], "read_only": False,
                "source": "explicit_browser_tab", "gid_selected": selected_gid is not None}

    def write_values(self, spreadsheet_id: str, range_a1: str, values: list[list[Any]]) -> dict[str, Any]:
        """Write literal values to an exact range; callers must enforce approval."""
        if not isinstance(spreadsheet_id, str) or _SPREADSHEET_ID_RE.fullmatch(spreadsheet_id) is None:
            raise GoogleSheetsError("invalid_spreadsheet_id")
        if (not isinstance(range_a1, str) or not range_a1.strip()
                or len(range_a1) > _MAX_RANGE_LENGTH
                or any(ord(char) < 0x20 or ord(char) == 0x7F for char in range_a1)):
            raise GoogleSheetsError("invalid_spreadsheet_range")
        if (not isinstance(values, list) or not values or len(values) > 100
                or any(not isinstance(row, list) or not row or len(row) > 20 for row in values)
                or sum(len(row) for row in values) > 1000):
            raise GoogleSheetsError("invalid_google_sheets_values")
        for row in values:
            for value in row:
                if value is not None and not isinstance(value, (str, int, float, bool)):
                    raise GoogleSheetsError("invalid_google_sheets_values")
                if isinstance(value, str) and (len(value) > 2000 or value.startswith("=")):
                    raise GoogleSheetsError("formula_or_oversized_value_not_allowed")
        encoded_range = quote(range_a1.strip(), safe="!:$'")
        url = (f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/"
               f"{encoded_range}?valueInputOption=RAW")
        body = json.dumps({"majorDimension": "ROWS", "values": values},
                          ensure_ascii=False).encode("utf-8")
        token = self._get_access_token()
        request = Request(url, data=body, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json",
            "Accept": "application/json"}, method="PUT")
        try:
            payload = self._request_json(request, _MAX_TOKEN_RESPONSE_BYTES)
        except GoogleSheetsError as error:
            if error.status != 401:
                raise
            token = self._refresh_access_token()
            retry = Request(url, data=body, headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json",
                "Accept": "application/json"}, method="PUT")
            payload = self._request_json(retry, _MAX_TOKEN_RESPONSE_BYTES)
        if payload.get("updatedRange") != range_a1.strip():
            raise GoogleSheetsError("google_sheets_write_unverified")
        return {"updatedRange": payload["updatedRange"],
                "updatedRows": payload.get("updatedRows", 0),
                "updatedColumns": payload.get("updatedColumns", 0),
                "updatedCells": payload.get("updatedCells", 0),
                "write_enabled": True}

    def read_values(self, spreadsheet_id: str, range_a1: str, value_render_option: str = "UNFORMATTED_VALUE") -> dict[str, Any]:
        """Read an exact A1 range, optionally returning formulas for write protection."""
        if not isinstance(spreadsheet_id, str) or _SPREADSHEET_ID_RE.fullmatch(spreadsheet_id) is None:
            raise GoogleSheetsError("invalid_spreadsheet_id")
        if (not isinstance(range_a1, str) or not range_a1.strip()
                or len(range_a1) > _MAX_RANGE_LENGTH
                or any(ord(char) < 0x20 or ord(char) == 0x7F for char in range_a1)):
            raise GoogleSheetsError("invalid_spreadsheet_range")
        if value_render_option not in {"UNFORMATTED_VALUE", "FORMULA"}:
            raise GoogleSheetsError("invalid_value_render_option")
        encoded_range = quote(range_a1.strip(), safe="!:$'")
        url = (f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{encoded_range}"
               f"?majorDimension=ROWS&valueRenderOption={value_render_option}")
        token = self._get_access_token()
        request = Request(url, headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/json"}, method="GET")
        try:
            payload = self._request_json(request, _MAX_SHEETS_RESPONSE_BYTES)
        except GoogleSheetsError as error:
            if error.status != 401:
                raise
            token = self._refresh_access_token()
            retry = Request(url, headers={"Authorization": f"Bearer {token}",
                              "Accept": "application/json"}, method="GET")
            payload = self._request_json(retry, _MAX_SHEETS_RESPONSE_BYTES)
        values = payload.get("values", [])
        if not isinstance(values, list) or any(not isinstance(row, list) for row in values):
            raise GoogleSheetsError("google_sheets_values_invalid")
        cell_count = sum(len(row) for row in values)
        if len(values) > 5000 or cell_count > _MAX_SHEETS_CELLS:
            raise GoogleSheetsError("google_sheets_range_too_large")
        return {"range": payload.get("range", range_a1.strip()),
                "majorDimension": payload.get("majorDimension", "ROWS"),
                "values": values, "read_only": False}
