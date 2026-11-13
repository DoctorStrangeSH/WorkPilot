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
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

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
    # Keep only the non-secret active worksheet gid for Google Sheets. Every
    # other query parameter and every fragment is discarded.
    safe_query = ""
    if parsed.scheme == "https" and parsed.hostname == "docs.google.com" and re.fullmatch(
        r"/spreadsheets/d/[A-Za-z0-9_-]{10,256}/edit/?", parsed.path
    ):
        query = parse_qs(parsed.query, keep_blank_values=True)
        gids = query.get("gid", [])
        if len(gids) == 1 and re.fullmatch(r"\d{1,16}", gids[0]):
            safe_query = urlencode({"gid": gids[0]})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", safe_query, ""))


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
            "capabilities": ["share_active_tab", "inspect_active_page", "inspect_capabilities", "reconcile_site_tables",
                             "claim_browser_audit", "finish_browser_audit",
                             "update_browser_audit_progress"],
        }

    if message_type == "claim_browser_audit":
        try:
            job = store.claim_browser_audit()
        except sqlite3.Error:
            return {**response, "ok": False, "error": "audit_job_unavailable"}
        return {**response, "ok": True, "type": "browser_audit_claim", "job": job}

    if message_type == "update_browser_audit_progress":
        if set(payload) != {"type", "request_id", "job_id", "current_role",
                            "completed_sources", "attention_sources", "failed_role"}:
            return {**response, "ok": False, "error": "invalid_audit_progress"}
        try:
            updated = store.update_browser_audit_progress(
                payload["job_id"], payload["current_role"],
                payload["completed_sources"], payload["attention_sources"],
                payload["failed_role"])
        except sqlite3.Error:
            return {**response, "ok": False, "error": "audit_job_unavailable"}
        return {**response, "ok": updated, "type": "browser_audit_progress_updated"}

    if message_type == "finish_browser_audit":
        if set(payload) - {"type", "request_id", "job_id", "succeeded"}:
            return {**response, "ok": False, "error": "invalid_audit_job"}
        try:
            updated = store.finish_browser_audit(
                payload.get("job_id"), payload.get("succeeded"))
        except sqlite3.Error:
            return {**response, "ok": False, "error": "audit_job_unavailable"}
        return {**response, "ok": updated, "type": "browser_audit_finished"}

    if message_type == "reconcile_site_tables":
        # The authenticated native channel carries bounded structured table data.
        # Never write source rows or identifiers to disk, logs, or extension UI.
        try:
            result = reconcile_tables(payload.get("snapshots"))
        except (SiteSnapshotError, ValueError, TypeError):
            return {**response, "ok": False, "error": "unmapped_or_invalid_site_tables"}
        # Source snapshots stay ephemeral. Save only aggregate counts so the
        # desktop dashboard can show the latest completed audit.
        try:
            store.record_browser_audit_summary(result["total"], result["summary"])
        except (sqlite3.Error, OSError, ValueError):
            return {**response, "ok": False, "error": "audit_summary_unavailable"}
        return {**response, "ok": True, "type": "site_tables_reconciled",
                **result, "persisted": False, "aggregate_persisted": True}

    if message_type == "inspect_capabilities":
        # Accept only bounded structural metadata, never raw page text or credentials.
        page = payload.get("page")
        required = {"url", "title", "table_headers", "tables", "search_labels",
                    "has_aria_grid", "virtualized", "login_required"}
        if not isinstance(page, dict) or set(page) != required:
            return {**response, "ok": False, "error": "invalid_capability_snapshot"}
        try:
            url = _clean_tab_url(page["url"])
            title = page["title"]
            headers = page["table_headers"]
            labels = page["search_labels"]
            if (not isinstance(title, str) or len(title) > 300
                    or not isinstance(headers, list) or len(headers) > 40
                    or not isinstance(labels, list) or len(labels) > 30
                    or any(not isinstance(v, str) or len(v) > 120 for v in headers + labels)
                    or not isinstance(page["tables"], list) or len(page["tables"]) > 12
                    or any(not isinstance(table, dict) or set(table) !=
                           {"kind", "columns", "visible_rows", "declared_rows"}
                           or table["kind"] not in {"html-table", "aria-grid"}
                           or not isinstance(table["columns"], list)
                           or not 1 <= len(table["columns"]) <= 20
                           or not all(isinstance(v, str) and 0 < len(v) <= 120 for v in table["columns"])
                           or type(table["visible_rows"]) is not int or not 0 <= table["visible_rows"] <= 1000
                           or (table["declared_rows"] is not None and
                               (type(table["declared_rows"]) is not int or not 0 <= table["declared_rows"] <= 1000000))
                           for table in page["tables"])
                    or any(not isinstance(page[k], bool) for k in
                           ("has_aria_grid", "virtualized", "login_required"))):
                raise ValueError("invalid capability fields")
        except (ValueError, TypeError, KeyError):
            return {**response, "ok": False, "error": "invalid_capability_snapshot"}
        # Opening the extension and pressing the structure-check button is an
        # explicit user action. For Google Sheets, remember only the sanitized
        # document URL/title so the desktop can start the API read without a
        # second "Share tab" action. No grid values or browser session data are saved.
        registered_sheet = False
        parsed_url = urlsplit(url)
        if (parsed_url.hostname == "docs.google.com" and
                re.fullmatch(r"/spreadsheets/d/[A-Za-z0-9_-]{10,256}/edit/?", parsed_url.path)):
            try:
                store.record_browser_tab(url, title or "Google Sheets")
                registered_sheet = True
            except sqlite3.Error:
                return {**response, "ok": False, "error": "local_storage_unavailable"}
        return {**response, "ok": True, "type": "capabilities_inspected",
                "page": {"url": url, "title": title, "table_headers": headers,
                         "tables": page["tables"], "search_labels": labels, "has_aria_grid": page["has_aria_grid"],
                         "virtualized": page["virtualized"],
                         "login_required": page["login_required"]},
                "persisted": False, "tab_registered": registered_sheet}

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
