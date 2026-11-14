import unittest
from urllib.parse import parse_qs, urlsplit

from malenia.google_oauth import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_SHEETS_SCOPE,
    GoogleOAuthError,
    build_authorization_url,
    create_oauth_state,
    create_pkce_challenge,
    create_pkce_verifier,
    parse_callback_target,
    validate_client_id,
    validate_client_secret,
    validate_granted_scope,
    validate_refresh_response,
    validate_token_response,
)


CLIENT_ID = "123456789012-testclient.apps.googleusercontent.com"
REDIRECT = "http://127.0.0.1:49152"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
STATE = "one-time-state-fixture-0123456789"


class GoogleOAuthProtocolTests(unittest.TestCase):
    def test_pkce_s256_matches_rfc7636_test_vector(self):
        self.assertEqual(
            create_pkce_challenge(VERIFIER),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        )
        generated = create_pkce_verifier()
        self.assertGreaterEqual(len(generated), 43)
        self.assertLessEqual(len(generated), 128)
        self.assertEqual(create_pkce_challenge(generated), create_pkce_challenge(generated))

    def test_optional_client_secret_validation(self):
        self.assertIsNone(validate_client_secret(None))
        self.assertIsNone(validate_client_secret(""))
        self.assertEqual(validate_client_secret("GOCSPX-fixture-secret"), "GOCSPX-fixture-secret")
        for value in ("contains space", "bad" + chr(10) + "secret", "x" * 513):
            with self.subTest(value=value), self.assertRaises(GoogleOAuthError):
                validate_client_secret(value)

    def test_state_is_high_entropy_and_url_safe(self):
        state = create_oauth_state()
        self.assertGreaterEqual(len(state), 32)
        self.assertEqual(parse_callback_target(
            "/?code=abc123&state=" + state, state
        ), "abc123")

    def test_authorization_url_requests_sheets_editor_with_pkce(self):
        url = build_authorization_url(CLIENT_ID, REDIRECT, STATE, VERIFIER)
        self.assertTrue(url.startswith(GOOGLE_AUTHORIZATION_ENDPOINT + "?"))
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["client_id"], [CLIENT_ID])
        self.assertEqual(query["redirect_uri"], [REDIRECT])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], [GOOGLE_SHEETS_SCOPE])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertEqual(query["state"], [STATE])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["code_challenge"], [create_pkce_challenge(VERIFIER)])
        self.assertNotIn("client_secret", query)

    def test_invalid_client_ids_and_non_loopback_redirects_are_rejected(self):
        for client_id in ("", "not-a-client-id", "123.apps.googleusercontent.com", None):
            with self.subTest(client_id=client_id), self.assertRaises(GoogleOAuthError):
                validate_client_id(client_id)
        for redirect in (
            "https://127.0.0.1:49152/oauth2/callback",
            "http://localhost:49152/oauth2/callback",
            "http://127.0.0.1.evil.test:49152/oauth2/callback",
            "http://127.0.0.1:49152/other",
            "http://127.0.0.1:0/oauth2/callback",
            "http://user@127.0.0.1:49152/oauth2/callback",
            "http://127.0.0.1:bad/oauth2/callback",
        ):
            with self.subTest(redirect=redirect), self.assertRaises(GoogleOAuthError):
                build_authorization_url(CLIENT_ID, redirect, STATE, VERIFIER)

    def test_invalid_pkce_verifier_and_state_are_rejected(self):
        for verifier in ("short", "x" * 129, "contains space" + "x" * 40):
            with self.subTest(verifier=verifier), self.assertRaises(GoogleOAuthError):
                create_pkce_challenge(verifier)
        with self.assertRaises(GoogleOAuthError):
            build_authorization_url(CLIENT_ID, REDIRECT, "short", VERIFIER)

    def test_callback_requires_exact_path_one_state_and_one_code(self):
        self.assertEqual(
            parse_callback_target("/?code=abc123&state=" + STATE, STATE),
            "abc123",
        )
        invalid_targets = (
            "/wrong?code=abc123&state=" + STATE,
            "/?code=abc123&state=wrong",
            "/?code=abc123&state=" + STATE + "&state=" + STATE,
            "/?state=" + STATE,
            "/?code=a&code=b&state=" + STATE,
            "/?code=a%0Ab&state=" + STATE,
            "/?code=%ZZ&state=" + STATE,
            "/?code=a&state",
        )
        for target in invalid_targets:
            with self.subTest(target=target), self.assertRaises(GoogleOAuthError):
                parse_callback_target(target, STATE)

    def test_user_denial_is_not_mistaken_for_authorization(self):
        with self.assertRaises(GoogleOAuthError):
            parse_callback_target(
                "/?error=access_denied&state=" + STATE, STATE
            )

    def test_only_the_exact_editor_scope_is_accepted(self):
        validate_granted_scope(GOOGLE_SHEETS_SCOPE)
        for scope in (
            "",
            None,
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            GOOGLE_SHEETS_SCOPE + " https://www.googleapis.com/auth/drive",
        ):
            with self.subTest(scope=scope), self.assertRaises(GoogleOAuthError):
                validate_granted_scope(scope)

    def test_initial_token_response_requires_refresh_token_and_exact_scope(self):
        payload = {
            "access_token": "access-token-fixture",
            "refresh_token": "refresh-token-fixture",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": GOOGLE_SHEETS_SCOPE,
        }
        result = validate_token_response(payload)
        self.assertEqual(result["refresh_token"], "refresh-token-fixture")
        self.assertEqual(result["scope"], GOOGLE_SHEETS_SCOPE)
        for patch in (
            {"refresh_token": None},
            {"token_type": "MAC"},
            {"expires_in": True},
            {"expires_in": 10},
            {"scope": GOOGLE_SHEETS_SCOPE + " https://www.googleapis.com/auth/drive"},
            {"access_token": "bad\nheader"},
        ):
            with self.subTest(patch=patch), self.assertRaises(GoogleOAuthError):
                validate_token_response({**payload, **patch})

    def test_refresh_response_may_omit_unchanged_scope_but_not_expand_it(self):
        payload = {"access_token": "new-access-token", "token_type": "Bearer", "expires_in": 3600}
        self.assertEqual(validate_refresh_response(payload)["access_token"], "new-access-token")
        with self.assertRaises(GoogleOAuthError):
            validate_refresh_response({**payload, "scope": "https://www.googleapis.com/auth/drive"})


if __name__ == "__main__":
    unittest.main()
