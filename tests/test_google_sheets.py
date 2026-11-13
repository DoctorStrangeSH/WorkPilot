import io
import json
import time
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from malenia.google_oauth import GOOGLE_SHEETS_READONLY_SCOPE, GOOGLE_TOKEN_ENDPOINT
from malenia.google_sheets import GoogleSheetsConnector, GoogleSheetsError


CLIENT_ID = "123456789012-testclient.apps.googleusercontent.com"
SPREADSHEET_ID = "a" * 24


class FakeCredentialStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def set(self, name, secret):
        self.values[name] = secret

    def get(self, name):
        return self.values.get(name)

    def delete(self, name):
        return self.values.pop(name, None) is not None


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self, limit=-1):
        return self.payload if limit < 0 else self.payload[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class FakeOpener:
    def __init__(self):
        self.requests = []
        self.sheet_payload = {
            "range": "Orders!A1:B2",
            "majorDimension": "ROWS",
            "values": [["cargo-place", "status"], ["CP-001", "Найден"]],
        }

    def open(self, request, timeout=0):
        self.requests.append(request)
        if request.full_url == GOOGLE_TOKEN_ENDPOINT:
            form = parse_qs(request.data.decode("ascii"))
            if form.get("grant_type") == ["authorization_code"]:
                return FakeResponse({
                    "access_token": "access-token-fixture",
                    "refresh_token": "refresh-token-fixture",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": GOOGLE_SHEETS_READONLY_SCOPE,
                })
            if form.get("grant_type") == ["refresh_token"]:
                return FakeResponse({
                    "access_token": "refreshed-access-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                })
        if request.full_url.startswith("https://sheets.googleapis.com/"):
            if request.get_header("Authorization") not in {
                "Bearer access-token-fixture",
                "Bearer refreshed-access-token",
            }:
                raise AssertionError("Missing bearer access token")
            if request.get_method() == "PUT":
                return FakeResponse({"updatedRange": "Orders!A1:B2", "updatedRows": 2, "updatedColumns": 2, "updatedCells": 4})
            if request.get_method() == "GET":
                return FakeResponse(self.sheet_payload)
            raise AssertionError("Unexpected Sheets method")
        raise AssertionError("Unexpected outbound request")


class BlockingTokenOpener(FakeOpener):
    def __init__(self):
        super().__init__()
        self.exchange_started = threading.Event()
        self.release_exchange = threading.Event()

    def open(self, request, timeout=0):
        if request.full_url == GOOGLE_TOKEN_ENDPOINT:
            form = parse_qs(request.data.decode("ascii"))
            if form.get("grant_type") == ["authorization_code"]:
                self.exchange_started.set()
                self.release_exchange.wait(3)
                return FakeResponse({
                    "access_token": "access-token-fixture",
                    "refresh_token": "refresh-token-fixture",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": GOOGLE_SHEETS_READONLY_SCOPE,
                })
        return super().open(request, timeout)


class InvalidGrantOpener(FakeOpener):
    def open(self, request, timeout=0):
        if request.full_url == GOOGLE_TOKEN_ENDPOINT:
            raise HTTPError(
                request.full_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(b'{"error":"invalid_grant"}'),
            )
        return super().open(request, timeout)


class UnauthorizedOnceOpener(FakeOpener):
    def __init__(self):
        super().__init__()
        self.unauthorized = True

    def open(self, request, timeout=0):
        if request.full_url.startswith("https://sheets.googleapis.com/") and self.unauthorized:
            self.requests.append(request)
            self.unauthorized = False
            raise HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b""))
        return super().open(request, timeout)


class GoogleSheetsConnectorTests(unittest.TestCase):
    def test_oauth_callback_stores_tokens_only_in_credential_store(self):
        store = FakeCredentialStore()
        opener = FakeOpener()
        connector = GoogleSheetsConnector(store, opener, callback_timeout=30)
        result = connector.start_connect(CLIENT_ID)
        self.assertEqual(result["status"], "authorizing")

        query = parse_qs(urlsplit(result["authorization_url"]).query)
        redirect_uri = query["redirect_uri"][0]
        callback = redirect_uri + "/?code=authorization-code-fixture&state=" + query["state"][0]
        with urlopen(callback, timeout=3) as response:
            self.assertEqual(response.status, 200)

        deadline = time.monotonic() + 3
        status = connector.status()
        while status["status"] == "authorizing" and time.monotonic() < deadline:
            time.sleep(0.02)
            status = connector.status()

        self.assertEqual(status, {"connected": False, "status": "authorized", "error": None, "client_id": CLIENT_ID})
        self.assertEqual(store.get("google-sheets-refresh-token"), "refresh-token-fixture")
        self.assertEqual(store.get("google-sheets-client-id"), CLIENT_ID)
        self.assertIsNone(store.get("google-sheets-client-secret"))
        self.assertNotIn("refresh_token", result)
        self.assertNotIn("access_token", result)

    def test_optional_client_secret_is_stored_and_used_for_refresh(self):
        store = FakeCredentialStore()
        opener = FakeOpener()
        connector = GoogleSheetsConnector(store, opener, callback_timeout=30)
        result = connector.start_connect(CLIENT_ID, "GOCSPX-client-secret-fixture")
        query = parse_qs(urlsplit(result["authorization_url"]).query)
        redirect_uri = query["redirect_uri"][0]
        callback = redirect_uri + "/?code=authorization-code-fixture&state=" + query["state"][0]
        with urlopen(callback, timeout=3):
            pass
        deadline = time.monotonic() + 3
        while connector.status()["status"] == "authorizing" and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(connector.status()["status"], "authorized")
        self.assertEqual(store.get("google-sheets-client-secret"), "GOCSPX-client-secret-fixture")

        code_exchange = next(r for r in opener.requests if r.full_url == GOOGLE_TOKEN_ENDPOINT)
        self.assertEqual(
            parse_qs(code_exchange.data.decode("ascii")).get("client_secret"),
            ["GOCSPX-client-secret-fixture"],
        )
        refresh_opener = FakeOpener()
        reloaded = GoogleSheetsConnector(store, refresh_opener)
        reloaded.read_values(SPREADSHEET_ID, "Orders!A1:B2")
        refresh_request = next(r for r in refresh_opener.requests if r.full_url == GOOGLE_TOKEN_ENDPOINT)
        self.assertEqual(
            parse_qs(refresh_request.data.decode("ascii")).get("client_secret"),
            ["GOCSPX-client-secret-fixture"],
        )

    def test_invalid_callback_state_does_not_complete_authorization(self):
        store = FakeCredentialStore()
        connector = GoogleSheetsConnector(store, FakeOpener(), callback_timeout=30)
        result = connector.start_connect(CLIENT_ID)
        query = parse_qs(urlsplit(result["authorization_url"]).query)
        redirect_uri = query["redirect_uri"][0]
        invalid_callback = redirect_uri + "/?code=attacker-code&state=wrong-state"
        with self.assertRaises(HTTPError):
            urlopen(invalid_callback, timeout=3)
        self.assertEqual(connector.status()["status"], "authorizing")
        self.assertIsNone(store.get("google-sheets-refresh-token"))

        valid_callback = redirect_uri + "/?code=good-code&state=" + query["state"][0]
        with urlopen(valid_callback, timeout=3) as response:
            self.assertEqual(response.status, 200)
        deadline = time.monotonic() + 3
        while connector.status()["status"] == "authorizing" and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(connector.status()["status"], "authorized")

    def test_loopback_callback_bridge_recovers_state_from_url_fragment(self):
        store = FakeCredentialStore()
        connector = GoogleSheetsConnector(store, FakeOpener(), callback_timeout=30)
        result = connector.start_connect(CLIENT_ID)
        query = parse_qs(urlsplit(result["authorization_url"]).query)
        redirect_uri = query["redirect_uri"][0]
        state = query["state"][0]

        # URL fragments are not sent in the HTTP request; the local static
        # bridge page forwards query + fragment parameters with same-origin POST.
        callback = redirect_uri + "/?code=fragment-state-code#state=" + state
        with urlopen(callback, timeout=3) as response:
            page = response.read().decode("utf-8")
            self.assertIn("URLSearchParams", page)
            self.assertIn('fetch("/",', page)

        body = urlencode({"code": "fragment-state-code", "state": state}).encode("ascii")
        request = Request(
            redirect_uri + "/",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 200)

        deadline = time.monotonic() + 3
        while connector.status()["status"] == "authorizing" and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(connector.status()["status"], "authorized")
        self.assertEqual(store.get("google-sheets-refresh-token"), "refresh-token-fixture")

    def test_disconnect_during_token_exchange_cannot_resurrect_credentials(self):
        store = FakeCredentialStore()
        opener = BlockingTokenOpener()
        connector = GoogleSheetsConnector(store, opener, callback_timeout=30)
        result = connector.start_connect(CLIENT_ID)
        attempt_thread = connector._attempt.thread
        query = parse_qs(urlsplit(result["authorization_url"]).query)
        redirect_uri = query["redirect_uri"][0]
        callback = redirect_uri + "/?code=authorization-code-fixture&state=" + query["state"][0]
        with urlopen(callback, timeout=3):
            pass
        self.assertTrue(opener.exchange_started.wait(3))

        connector.disconnect()
        opener.release_exchange.set()
        attempt_thread.join(timeout=3)
        self.assertFalse(attempt_thread.is_alive())
        self.assertEqual(store.values, {})
        self.assertEqual(connector.status()["status"], "not_connected")

    def test_user_denial_never_persists_tokens(self):
        store = FakeCredentialStore()
        connector = GoogleSheetsConnector(store, FakeOpener(), callback_timeout=30)
        result = connector.start_connect(CLIENT_ID)
        query = parse_qs(urlsplit(result["authorization_url"]).query)
        redirect_uri = query["redirect_uri"][0]
        denied = redirect_uri + "/?error=access_denied&state=" + query["state"][0]
        with urlopen(denied, timeout=3) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(connector.status()["status"], "denied")
        self.assertIsNone(store.get("google-sheets-refresh-token"))

    def test_read_values_uses_get_and_returns_bounded_rows(self):
        store = FakeCredentialStore({
            "google-sheets-refresh-token": "refresh-token-fixture",
            "google-sheets-client-id": CLIENT_ID,
        })
        opener = FakeOpener()
        connector = GoogleSheetsConnector(store, opener)
        connector._access_token = "access-token-fixture"
        connector._access_expires_at = time.monotonic() + 3600
        result = connector.read_values(SPREADSHEET_ID, "Orders!A1:B2")
        self.assertEqual(result["values"][1], ["CP-001", "Найден"])
        self.assertFalse(result["read_only"])
        sheets_request = next(r for r in opener.requests if r.full_url.startswith("https://sheets.googleapis.com/"))
        self.assertEqual(sheets_request.get_method(), "GET")
        self.assertIn("Bearer access-token-fixture", sheets_request.get_header("Authorization"))
        self.assertTrue(hasattr(connector, "write_values"))

    def test_write_values_uses_literal_put_and_rejects_formulas(self):
        store = FakeCredentialStore({
            "google-sheets-refresh-token": "refresh-token-fixture",
            "google-sheets-client-id": CLIENT_ID,
        })
        opener = FakeOpener()
        connector = GoogleSheetsConnector(store, opener)
        connector._access_token = "access-token-fixture"
        connector._access_expires_at = time.monotonic() + 3600
        result = connector.write_values(SPREADSHEET_ID, "Orders!A1:B2",
            [["ID", "Статус"], ["CP-001", "Найден"]])
        self.assertTrue(result["write_enabled"])
        request = next(r for r in opener.requests if r.get_method() == "PUT")
        self.assertIn("valueInputOption=RAW", request.full_url)
        self.assertEqual(json.loads(request.data.decode("utf-8"))["values"][1][1], "Найден")
        with self.assertRaises(GoogleSheetsError):
            connector.write_values(SPREADSHEET_ID, "Orders!A1", [["=1+1"]])

    def test_read_values_refreshes_after_unauthorized_response(self):
        store = FakeCredentialStore({
            "google-sheets-refresh-token": "refresh-token-fixture",
            "google-sheets-client-id": CLIENT_ID,
        })
        opener = UnauthorizedOnceOpener()
        connector = GoogleSheetsConnector(store, opener)
        result = connector.read_values(SPREADSHEET_ID, "Orders!A1:B2")
        self.assertEqual(result["values"][1][0], "CP-001")
        token_requests = [request for request in opener.requests if request.full_url == GOOGLE_TOKEN_ENDPOINT]
        self.assertEqual(len(token_requests), 2)
        for request in token_requests:
            self.assertEqual(
                parse_qs(request.data.decode("ascii")).get("grant_type"),
                ["refresh_token"],
            )
        sheets_requests = [r for r in opener.requests if r.full_url.startswith("https://sheets.googleapis.com/")]
        self.assertEqual(len(sheets_requests), 2)
        self.assertEqual(sheets_requests[1].get_header("Authorization"), "Bearer refreshed-access-token")

    def test_invalid_spreadsheet_or_range_fails_before_network(self):
        store = FakeCredentialStore({
            "google-sheets-refresh-token": "refresh-token-fixture",
            "google-sheets-client-id": CLIENT_ID,
        })
        opener = FakeOpener()
        connector = GoogleSheetsConnector(store, opener)
        for spreadsheet_id, range_a1 in (
            ("", "A1:B2"),
            ("https://evil.test", "A1:B2"),
            (SPREADSHEET_ID, ""),
            (SPREADSHEET_ID, "A1\nB2"),
            (SPREADSHEET_ID, "A1" * 201),
        ):
            with self.subTest(spreadsheet_id=spreadsheet_id, range_a1=range_a1):
                with self.assertRaises(GoogleSheetsError):
                    connector.read_values(spreadsheet_id, range_a1)
        self.assertEqual(opener.requests, [])

    def test_invalid_grant_requires_reauthorization_and_preserves_client_id(self):
        store = FakeCredentialStore({
            "google-sheets-refresh-token": "refresh-token-fixture",
            "google-sheets-client-id": CLIENT_ID,
            "google-sheets-client-secret": "client-secret-fixture",
        })
        connector = GoogleSheetsConnector(store, InvalidGrantOpener())
        with self.assertRaises(GoogleSheetsError) as raised:
            connector.read_values(SPREADSHEET_ID, "Orders!A1:B2")
        self.assertEqual(raised.exception.code, "google_reauthorization_required")
        self.assertEqual(
            connector.status(),
            {
                "connected": False,
                "status": "reauthorization_required",
                "error": "google_reauthorization_required",
                "client_id": CLIENT_ID,
            },
        )
        self.assertEqual(store.get("google-sheets-refresh-token"), "refresh-token-fixture")

    def test_disconnect_deletes_local_credentials(self):
        store = FakeCredentialStore({
            "google-sheets-refresh-token": "refresh-token-fixture",
            "google-sheets-client-id": CLIENT_ID,
            "google-sheets-client-secret": "client-secret-fixture",
        })
        connector = GoogleSheetsConnector(store, FakeOpener())
        result = connector.disconnect()
        self.assertFalse(result["connected"])
        self.assertIsNone(store.get("google-sheets-refresh-token"))
        self.assertIsNone(store.get("google-sheets-client-id"))
        self.assertIsNone(store.get("google-sheets-client-secret"))

    def test_no_plaintext_fallback_or_unexpected_scope(self):
        connector = GoogleSheetsConnector(credential_store=None, opener=FakeOpener())
        if __import__("os").name != "nt":
            with self.assertRaises(GoogleSheetsError):
                connector.start_connect(CLIENT_ID)

    def test_scope_expansion_is_rejected_before_token_storage(self):
        class ExpandedScopeOpener(FakeOpener):
            def open(self, request, timeout=0):
                if request.full_url == GOOGLE_TOKEN_ENDPOINT:
                    return FakeResponse({
                        "access_token": "access-token-fixture",
                        "refresh_token": "refresh-token-fixture",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "scope": GOOGLE_SHEETS_READONLY_SCOPE + " https://www.googleapis.com/auth/drive",
                    })
                return super().open(request, timeout)

        store = FakeCredentialStore()
        connector = GoogleSheetsConnector(store, ExpandedScopeOpener(), callback_timeout=30)
        result = connector.start_connect(CLIENT_ID)
        query = parse_qs(urlsplit(result["authorization_url"]).query)
        redirect_uri = query["redirect_uri"][0]
        callback = redirect_uri + "/?code=authorization-code-fixture&state=" + query["state"][0]
        with urlopen(callback, timeout=3):
            pass
        deadline = time.monotonic() + 3
        while connector.status()["status"] == "authorizing" and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(connector.status()["status"], "error")
        self.assertIsNone(store.get("google-sheets-refresh-token"))


if __name__ == "__main__":
    unittest.main()
