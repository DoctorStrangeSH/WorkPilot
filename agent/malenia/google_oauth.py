"""Small, testable helpers for Google's installed-app OAuth PKCE flow.

No network calls, browser launches, tokens, or credentials are handled here.
The eventual desktop integration must use a loopback listener and the
Windows Credential Manager backend; it must not add broader scopes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit


GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
GOOGLE_CALLBACK_PATH = "/oauth2/callback"

_VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_STATE_RE = re.compile(r"^[A-Za-z0-9._~-]{32,256}$")
_CLIENT_ID_RE = re.compile(r"^[0-9]+-[A-Za-z0-9-]+\.apps\.googleusercontent\.com$")
_MAX_AUTH_CODE_LENGTH = 4096


class GoogleOAuthError(ValueError):
    """Raised when OAuth inputs or responses fail strict validation."""


def validate_client_id(client_id: str) -> str:
    if not isinstance(client_id, str) or _CLIENT_ID_RE.fullmatch(client_id) is None:
        raise GoogleOAuthError("A valid Google OAuth Desktop client ID is required")
    return client_id


def create_pkce_verifier() -> str:
    """Create an RFC 7636 verifier using only unreserved URL-safe characters."""
    verifier = secrets.token_urlsafe(64)
    if _VERIFIER_RE.fullmatch(verifier) is None:
        raise GoogleOAuthError("Could not create a valid PKCE verifier")
    return verifier


def create_oauth_state() -> str:
    state = secrets.token_urlsafe(32)
    if _STATE_RE.fullmatch(state) is None:
        raise GoogleOAuthError("Could not create a valid OAuth state")
    return state


def create_pkce_challenge(verifier: str) -> str:
    if not isinstance(verifier, str) or _VERIFIER_RE.fullmatch(verifier) is None:
        raise GoogleOAuthError("Invalid PKCE verifier")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def validate_loopback_redirect_uri(redirect_uri: str) -> str:
    if not isinstance(redirect_uri, str) or len(redirect_uri) > 200:
        raise GoogleOAuthError("Invalid OAuth redirect URI")
    parsed = urlsplit(redirect_uri)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or not 1 <= parsed.port <= 65535
        or parsed.path != GOOGLE_CALLBACK_PATH
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise GoogleOAuthError("OAuth redirect must use the local 127.0.0.1 callback")
    return redirect_uri


def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    verifier: str,
) -> str:
    """Build an explicit offline, PKCE-S256 request for the single read-only scope."""
    validate_client_id(client_id)
    validate_loopback_redirect_uri(redirect_uri)
    if not isinstance(state, str) or _STATE_RE.fullmatch(state) is None:
        raise GoogleOAuthError("Invalid OAuth state")
    challenge = create_pkce_challenge(verifier)
    query = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SHEETS_READONLY_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return GOOGLE_AUTHORIZATION_ENDPOINT + "?" + query


def parse_callback_target(target: str, expected_state: str) -> str:
    """Validate the local callback path, one-use state and authorization code."""
    if not isinstance(expected_state, str) or _STATE_RE.fullmatch(expected_state) is None:
        raise GoogleOAuthError("Invalid expected OAuth state")
    if not isinstance(target, str) or len(target) > 8192:
        raise GoogleOAuthError("Invalid OAuth callback")
    parsed = urlsplit(target)
    if parsed.path != GOOGLE_CALLBACK_PATH:
        raise GoogleOAuthError("Unexpected OAuth callback path")
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    states = query.get("state", [])
    if len(states) != 1 or not hmac.compare_digest(states[0], expected_state):
        raise GoogleOAuthError("OAuth state mismatch")
    errors = query.get("error", [])
    if errors:
        if len(errors) != 1 or not re.fullmatch(r"[a-z_]{1,64}", errors[0]):
            raise GoogleOAuthError("Google OAuth authorization failed")
        raise GoogleOAuthError("Google OAuth authorization was not granted")
    codes = query.get("code", [])
    if len(codes) != 1 or not codes[0] or len(codes[0]) > _MAX_AUTH_CODE_LENGTH:
        raise GoogleOAuthError("Missing or invalid OAuth authorization code")
    if any(ord(char) < 0x21 or ord(char) > 0x7E for char in codes[0]):
        raise GoogleOAuthError("Invalid OAuth authorization code")
    return codes[0]


def validate_granted_scope(scope_value: str) -> None:
    """Reject broader or missing scopes; only the exact read-only scope is accepted."""
    if not isinstance(scope_value, str):
        raise GoogleOAuthError("Google did not confirm the granted scope")
    granted = set(scope_value.split())
    if granted != {GOOGLE_SHEETS_READONLY_SCOPE}:
        raise GoogleOAuthError("Google granted unexpected or incomplete access scopes")


def validate_token_response(payload: object) -> dict[str, object]:
    """Validate initial token response before any token is persisted."""
    if not isinstance(payload, dict):
        raise GoogleOAuthError("Invalid Google token response")
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    token_type = payload.get("token_type")
    expires_in = payload.get("expires_in")
    scope = payload.get("scope")
    if not isinstance(access_token, str) or not access_token or len(access_token) > 8192:
        raise GoogleOAuthError("Google access token is missing or invalid")
    if not isinstance(refresh_token, str) or not refresh_token or len(refresh_token) > 8192:
        raise GoogleOAuthError("Google refresh token is missing or invalid")
    if token_type != "Bearer":
        raise GoogleOAuthError("Unsupported Google token type")
    if isinstance(expires_in, bool) or not isinstance(expires_in, int) or not 60 <= expires_in <= 86400:
        raise GoogleOAuthError("Invalid Google access-token lifetime")
    validate_granted_scope(scope)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "scope": GOOGLE_SHEETS_READONLY_SCOPE,
    }


def validate_refresh_response(payload: object) -> dict[str, object]:
    """Validate a refresh response; Google normally omits refresh_token here."""
    if not isinstance(payload, dict):
        raise GoogleOAuthError("Invalid Google token refresh response")
    access_token = payload.get("access_token")
    token_type = payload.get("token_type")
    expires_in = payload.get("expires_in")
    scope = payload.get("scope")
    if not isinstance(access_token, str) or not access_token or len(access_token) > 8192:
        raise GoogleOAuthError("Google access token is missing or invalid")
    if token_type != "Bearer":
        raise GoogleOAuthError("Unsupported Google token type")
    if isinstance(expires_in, bool) or not isinstance(expires_in, int) or not 60 <= expires_in <= 86400:
        raise GoogleOAuthError("Invalid Google access-token lifetime")
    # A refresh response may omit scope when the original grant is unchanged.
    if scope is not None:
        validate_granted_scope(scope)
    return {
        "access_token": access_token,
        "expires_in": expires_in,
        "scope": GOOGLE_SHEETS_READONLY_SCOPE,
    }
