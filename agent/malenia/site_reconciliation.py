"""Fail-closed read-only reconciliation of structured browser table snapshots.

Only exact documented column names are recognized. This module never reads a
browser, stores source data or changes site records.
"""
from __future__ import annotations

from datetime import datetime, date
import re
from typing import Any

from .order_batch import preview_batch, OrderBatchError

FIELDS = {
    "inventory": ("cargo_place", "inventory_date"),
    "datalens": ("main_partner_code_original", "sc_id", "result", "scanned_at"),
    "asgard": ("cargo_place", "status", "box_id", "extended_history_statuses"),
}
MAX_ROWS = 100
MAX_COLUMNS = 20
MAX_CELL = 256


class SiteSnapshotError(ValueError):
    pass


def _table(raw: Any, role: str) -> list[dict[str, str]]:
    if not isinstance(raw, dict) or set(raw) != {"columns", "rows"}:
        raise SiteSnapshotError("invalid_snapshot")
    columns, rows = raw["columns"], raw["rows"]
    # Reviewed against the user's DataLens scan-history headers (2026-11-14).
    if role == "datalens" and isinstance(columns, list):
        columns = ["main_partner_code_original" if c == "place_external_id" else c
                   for c in columns]
    if (not isinstance(columns, list) or not 1 <= len(columns) <= MAX_COLUMNS
            or not all(isinstance(c, str) and 0 < len(c) <= MAX_CELL for c in columns)
            or len(columns) != len(set(columns))
            or not isinstance(rows, list) or len(rows) > MAX_ROWS):
        raise SiteSnapshotError("invalid_table")
    # Do not guess site-specific column synonyms: mappings must be reviewed.
    if any(c not in columns for c in FIELDS[role][:2]):
        raise SiteSnapshotError("unmapped_columns")
    if role == "datalens" and any(c not in columns for c in FIELDS[role]):
        raise SiteSnapshotError("unmapped_columns")
    if role == "asgard" and "status" not in columns:
        raise SiteSnapshotError("unmapped_columns")
    output = []
    for values in rows:
        if (not isinstance(values, list) or len(values) != len(columns)
                or not all(isinstance(v, str) and len(v) <= MAX_CELL
                           and "\x00" not in v for v in values)):
            raise SiteSnapshotError("invalid_row")
        output.append(dict(zip(columns, values)))
    return output


def _date(raw: str, *, timestamp: bool = False) -> str:
    value = raw.strip()
    try:
        if timestamp:
            # Timestamp must contain time; never infer a successful scan time.
            if "T" not in value and " " not in value:
                raise ValueError("missing scan time")
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00").replace("/", "-"))
            return parsed.isoformat()
        if len(value) != 10:
            raise ValueError("inventory must be ISO date")
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise SiteSnapshotError("invalid_date") from exc


def reconcile_tables(snapshots: Any) -> dict[str, Any]:
    """Return aggregate status suggestions without returning identifiable rows.

    An incomplete or unknown site schema yields manual-review for known inventory
    rows, and never a positive status. One matching DataLens row may be used only
    if the complete table exposes the exact required columns. Duplicate Asgard
    or inventory records are treated as ambiguous.
    """
    if not isinstance(snapshots, dict) or set(snapshots) != set(FIELDS):
        raise SiteSnapshotError("invalid_roles")
    inventory = _table(snapshots["inventory"], "inventory")
    datalens = _table(snapshots["datalens"], "datalens")
    asgard = _table(snapshots["asgard"], "asgard")
    if not inventory:
        return {"total": 0, "summary": {"found": 0, "in_progress": 0,
                                        "manual_review": 0},
                "read_only": True, "write_enabled": False, "source": "browser_tables"}

    scans_by_code: dict[str, list[dict[str, str]]] = {}
    for row in datalens:
        code = row["main_partner_code_original"].strip()
        if not code:
            continue
        # Invalid matching scan timestamps are passed to evaluate_order,
        # which fails closed; do not silently drop them.
        scans_by_code.setdefault(code, []).append({
            "main_partner_code_original": code,
            "sc_id": re.sub(r"\s+", "", row["sc_id"]),
            "result": row["result"].strip(),
            "scanned_at": row["scanned_at"].strip().replace("/", "-"),
        })

    asgard_by_code: dict[str, list[dict[str, str]]] = {}
    for row in asgard:
        code = row["cargo_place"].strip()
        if code:
            asgard_by_code.setdefault(code, []).append(row)
    rows = []
    ambiguous = set()
    for index, item in enumerate(inventory, start=1):
        code = item["cargo_place"].strip()
        if not code or len(code) > 128:
            raise SiteSnapshotError("invalid_cargo_place")
        inv = _date(item["inventory_date"])
        matches = asgard_by_code.get(code, [])
        if len(matches) > 1:
            ambiguous.add(code)
        record = None
        if len(matches) == 1:
            match = matches[0]
            status = match["status"].strip()
            record = {"status": status}
            if status == "В пути":
                # The box history must come from a verified dedicated
                # history adapter, not from a generic cell's free text.
                record["box_id"] = match.get("box_id", "").strip()
                # Deliberately do not accept extended history from a page
                # snapshot as proof that the linked box was inspected.
        rows.append({
            "source_row": index,
            "order": {"cargo_place": code, "inventory_date": inv},
            "datalens_scans": scans_by_code.get(code, []),
            "asgard_record": record,
        })
    try:
        result = preview_batch(rows)
    except (OrderBatchError, ValueError) as exc:
        raise SiteSnapshotError("cannot_reconcile") from exc

    # Ambiguous Asgard records cannot contribute even if DataLens suggests found.
    # Conservative all-manual aggregate when duplicate source identities exist.
    duplicates = {r["order"]["cargo_place"] for r in rows
                  if sum(x["order"]["cargo_place"] == r["order"]["cargo_place"]
                         for x in rows) > 1}
    manual_codes = ambiguous | duplicates
    if manual_codes:
        for row, outcome in zip(rows, result["results"]):
            if row["order"]["cargo_place"] in manual_codes:
                outcome["proposal"] = {"decision": "manual_review"}
    summary = {"found": 0, "in_progress": 0, "manual_review": 0}
    for outcome in result["results"]:
        decision = outcome["proposal"]["decision"]
        summary["found" if decision == "found" else
                "in_progress" if decision == "asgard" else "manual_review"] += 1
    return {"total": len(rows), "summary": summary,
            "read_only": True, "write_enabled": False, "source": "browser_tables"}
