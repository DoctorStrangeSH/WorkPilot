"""Windows Credential Manager adapter for local integration secrets.

Secrets are never stored in SQLite, config files, logs, or frontend state.
On non-Windows platforms this backend fails closed instead of falling back
to plaintext storage.
"""

from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes


_CREDENTIAL_PREFIX = "Malenia/"
_CREDENTIAL_TYPE_GENERIC = 1
_CREDENTIAL_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168
_MAX_SECRET_BYTES = 2048


class SecretStoreError(RuntimeError):
    """Raised when the operating-system secret store is unavailable."""


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class _WindowsCredentialApi:
    def __init__(self) -> None:
        if os.name != "nt":
            raise SecretStoreError("Windows Credential Manager is available only on Windows")
        self._advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._advapi.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
        self._advapi.CredWriteW.restype = wintypes.BOOL
        self._advapi.CredReadW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
        ]
        self._advapi.CredReadW.restype = wintypes.BOOL
        self._advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._advapi.CredDeleteW.restype = wintypes.BOOL
        self._advapi.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi.CredFree.restype = None

    def write(self, target: str, secret: bytes) -> None:
        blob = (ctypes.c_ubyte * len(secret)).from_buffer_copy(secret)
        credential = _CREDENTIALW(
            0,
            _CREDENTIAL_TYPE_GENERIC,
            target,
            "Malenia integration credential",
            _FILETIME(0, 0),
            len(secret),
            ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte)),
            _CREDENTIAL_PERSIST_LOCAL_MACHINE,
            0,
            None,
            None,
            "Malenia",
        )
        try:
            if not self._advapi.CredWriteW(ctypes.byref(credential), 0):
                raise SecretStoreError(f"Windows Credential Manager write failed ({ctypes.get_last_error()})")
        finally:
            ctypes.memset(blob, 0, len(secret))

    def read(self, target: str) -> bytes | None:
        pointer = ctypes.POINTER(_CREDENTIALW)()
        if not self._advapi.CredReadW(
            target, _CREDENTIAL_TYPE_GENERIC, 0, ctypes.byref(pointer)
        ):
            error = ctypes.get_last_error()
            if error == _ERROR_NOT_FOUND:
                return None
            raise SecretStoreError(f"Windows Credential Manager read failed ({error})")
        try:
            credential = pointer.contents
            if credential.CredentialBlobSize > _MAX_SECRET_BYTES:
                raise SecretStoreError("Stored credential exceeds the allowed size")
            if credential.CredentialBlobSize and not credential.CredentialBlob:
                raise SecretStoreError("Stored credential is malformed")
            return ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        finally:
            self._advapi.CredFree(pointer)

    def delete(self, target: str) -> bool:
        if self._advapi.CredDeleteW(target, _CREDENTIAL_TYPE_GENERIC, 0):
            return True
        error = ctypes.get_last_error()
        if error == _ERROR_NOT_FOUND:
            return False
        raise SecretStoreError(f"Windows Credential Manager delete failed ({error})")


class WindowsCredentialStore:
    """Store named UTF-8 secrets in the current Windows user's Credential Manager."""

    def __init__(self, api=None):
        # api injection is used only for deterministic unit tests.
        self._api = api if api is not None else _WindowsCredentialApi()

    @staticmethod
    def _target(name: str) -> str:
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9._-]{1,80}", name) is None:
            raise ValueError("Credential name must be 1–80 ASCII letters, digits, dots, underscores or hyphens")
        return _CREDENTIAL_PREFIX + name

    def set(self, name: str, secret: str) -> None:
        target = self._target(name)
        if not isinstance(secret, str) or not secret:
            raise ValueError("Secret must not be empty")
        encoded = secret.encode("utf-8")
        if len(encoded) > _MAX_SECRET_BYTES:
            raise ValueError("Secret exceeds the 2048-byte limit")
        self._api.write(target, encoded)

    def get(self, name: str) -> str | None:
        target = self._target(name)
        value = self._api.read(target)
        if value is None:
            return None
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SecretStoreError("Stored credential is not valid UTF-8") from error

    def delete(self, name: str) -> bool:
        return self._api.delete(self._target(name))
