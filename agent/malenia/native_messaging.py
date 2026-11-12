"""Restricted Chrome-compatible Native Messaging host for Malenia.

The host accepts only messages from the extension ID explicitly registered by the
user. It stores only a tab title and a URL with query/fragment removed, and only
after the user presses the extension's Share button.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import struct
import sys
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlsplit, urlunsplit

from .config import data_directory
from .store import TaskStore
from .site_reconciliation import reconcile_tables, SiteSnapshotError


HOST_NAME = "com.malenia.browser"
MAX_MESSAGE_BYTES = 1024 * 1024
_EXTENSION_ID_RE = re.compile(r"^[a-p]{32}$")


def _read_exact(stream: BinaryIO, length: int, *, allow_eof: bool = False) -> bytes | None:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = stream.read(length - len(chunks))
        if not chunk:
            if allow_eof and not chunks:
                return None
            raise ValueError("incomplete native messaging frame")
        chunks.extend(chunk)
    return bytes(chunks)


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """Read one length-prefixed UTF-8 JSON object from a native messaging stream."""
    header = _read_exact(stream, 4, allow_eof=True)
    if header is None:
        return None

    (length,) = struct.unpack("<I", header)
    if length < 2 or length > MAX_MESSAGE_BYTES:
        raise ValueError("native messaging frame size is not allowed")

    payload = _read_exact(stream, length)
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("native messaging payload must be a JSON object")
    return value


def write_message(stream: BinaryIO, payload: dict[str, Any]) -> None:
    """Write one length-prefixed UTF-8 JSON object to a native messaging stream."""
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ValueError("native messaging response is too large")
    stream.write(struct.pack("<I", len(encoded)))
    stream.write(encoded)
    stream.flush()


def configured_extension_id(config_path: Path | None = None) -> str:
    path = config_path or (data_directory() / "browser_bridge.json")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Browser Bridge is not registered for an extension yet") from error

    extension_id = config.get("extension_id") if isinstance(config, dict) else None
    if not isinstance(extension_id, str) or not _EXTENSION_ID_RE.fullmatch(extension_id):
        raise ValueError("Browser Bridge extension ID is missing or invalid")
    return extension_id


def validate_origin(origin: str, extension_id: str) -> bool:
    return origin == f"chrome-extension://{extension_id}/"


def _clean_tab_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("tab URL is missing or too long")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only ordinary HTTP(S) pages can be shared")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing credentials cannot be shared")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("tab URL has an invalid port") from error
    # Query strings and fragments may contain private or session-like data.
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))


def handle_message(payload: dict[str, Any], store: TaskStore) -> dict[str, Any]:
    """Handle the deliberately small, user-initiated Browser Bridge protocol."""
    request_id = payload.get("request_id")
    response: dict[str, Any] = {"request_id": request_id}

    message_type = payload.get("type")
    if message_type == "hello":
        return {
            **response,
            "ok": True,
            "type": "hello",
            "host": HOST_NAME,
            "version": "0.1.0",
            "capabilities": ["share_active_tab", "inspect_active_page", "reconcile_site_tables"],
        }

    if message_type == "reconcile_site_tables":
        # The authenticated native channel carries bounded structured table data.
        # Never write source rows or identifiers to disk, logs, or extension UI.
        try:
            result = reconcile_tables(payload.get("snapshots"))
        except (SiteSnapshotError, ValueError, TypeError):
            return {**response, "ok": False, "error": "unmapped_or_invalid_site_tables"}
        return {**response, "ok": True, "type": "site_tables_reconciled",
                **result, "persisted": False}

    if message_type == "inspect_active_page":
        # Validate a user-initiated rendered-text snapshot without retaining it.
        page = payload.get("page")
        if not isinstance(page, dict) or set(page) != {"url", "text"}:
            return {**response, "ok": False, "error": "invalid_page"}
        try:
            _clean_tab_url(page["url"])
            visible_text = page["text"]
            if (not isinstance(visible_text, str) or not visible_text.strip()
                    or len(visible_text) > 16000 or "\\x00" in visible_text):
                raise ValueError("invalid page text")
        except (ValueError, TypeError, KeyError):
            return {**response, "ok": False, "error": "invalid_page"}
        return {**response, "ok": True, "type": "page_inspected",
                "characters": len(visible_text), "persisted": False}

    if message_type != "share_active_tab":
        return {**response, "ok": False, "error": "unsupported_message"}

    tab = payload.get("tab")
    if not isinstance(tab, dict):
        return {**response, "ok": False, "error": "tab_object_required"}

    try:
        url = _clean_tab_url(tab.get("url"))
        raw_title = tab.get("title", "")
        if not isinstance(raw_title, str):
            raise ValueError("tab title must be text")
        title = "".join(
            char for char in raw_title if char >= " " and ord(char) != 127
        )[:300].strip()
        if not title:
            title = urlsplit(url).hostname or "Shared tab"
        saved = store.record_browser_tab(url, title)
    except ValueError as error:
        return {**response, "ok": False, "error": str(error)}
    except sqlite3.Error:
        return {**response, "ok": False, "error": "local_storage_unavailable"}

    return {**response, "ok": True, "type": "tab_shared", "tab": saved}


def run_native_messaging(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Native Messaging origin argument is missing.", file=sys.stderr)
        return 2

    try:
        extension_id = configured_extension_id()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    if not validate_origin(args[0], extension_id):
        print("Native Messaging caller is not the registered Malenia extension.", file=sys.stderr)
        return 3

    if os.name == "nt":
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

    store = TaskStore(data_directory() / "malenia.sqlite3")
    source = sys.stdin.buffer
    destination = sys.stdout.buffer

    while True:
        try:
            message = read_message(source)
            if message is None:
                return 0
            response = handle_message(message, store)
            write_message(destination, response)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            # Never write diagnostics to stdout: it is reserved for framed protocol data.
            print(f"Native Messaging protocol error: {error}", file=sys.stderr)
            return 4
        except (BrokenPipeError, OSError):
            return 0
