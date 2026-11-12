import os
import unittest
import uuid

from malenia.secret_store import (
    SecretStoreError,
    WindowsCredentialStore,
)


class FakeCredentialApi:
    def __init__(self):
        self.values = {}

    def write(self, target, secret):
        self.values[target] = bytes(secret)

    def read(self, target):
        return self.values.get(target)

    def delete(self, target):
        return self.values.pop(target, None) is not None


class WindowsCredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeCredentialApi()
        self.store = WindowsCredentialStore(api=self.api)

    def test_secret_round_trip_and_replacement(self):
        self.store.set("google-sheets-refresh-token", "refresh-token-fixture")
        self.assertEqual(
            self.store.get("google-sheets-refresh-token"),
            "refresh-token-fixture",
        )
        self.store.set("google-sheets-refresh-token", "replacement-token")
        self.assertEqual(
            self.store.get("google-sheets-refresh-token"),
            "replacement-token",
        )
        self.assertEqual(
            list(self.api.values),
            ["Malenia/google-sheets-refresh-token"],
        )

    def test_missing_secret_and_delete_are_idempotent(self):
        self.assertIsNone(self.store.get("missing"))
        self.assertFalse(self.store.delete("missing"))
        self.store.set("google-sheets-refresh-token", "fixture")
        self.assertTrue(self.store.delete("google-sheets-refresh-token"))
        self.assertFalse(self.store.delete("google-sheets-refresh-token"))
        self.assertIsNone(self.store.get("google-sheets-refresh-token"))

    def test_invalid_names_empty_and_oversized_secrets_are_rejected(self):
        for name in ("", "../token", "google/sheets", "x" * 81, None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.get(name)
        for secret in ("", None, "x" * 2049):
            with self.subTest(secret=secret), self.assertRaises(ValueError):
                self.store.set("token", secret)

    def test_non_utf8_credential_fails_closed(self):
        self.api.values["Malenia/token"] = b"\xff"
        with self.assertRaises(SecretStoreError):
            self.store.get("token")

    @unittest.skipUnless(os.name == "nt", "Windows Credential Manager integration test")
    def test_real_windows_credential_manager_round_trip(self):
        store = WindowsCredentialStore()
        name = "ci-test-" + uuid.uuid4().hex
        try:
            store.set(name, "temporary-ci-secret")
            self.assertEqual(store.get(name), "temporary-ci-secret")
        finally:
            store.delete(name)


if __name__ == "__main__":
    unittest.main()
