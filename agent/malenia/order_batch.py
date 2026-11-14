"""Deterministic bulk preview of manually supplied order snapshots.

The caller supplies data already copied from authorized sources. No network
requests, browser access, filesystem writes, or database persistence occur.
"""
from __future__ import annotations

from typing import Any

from .order_check import evaluate_order


MAX_BATCH_ROWS = 100
MAX_SCANS_PER_ORDER = 100


class OrderBatchError(ValueError):
    """Rejected input; no partial batch result is committed or stored."""


def preview_batch(rows: Any) -> dict[str, Any]:
    """Evaluate a bounded batch, preserving input order and source row labels.

    Every row must provide order.cargo_place and order.inventory_date, optional
    datalens_scans and asgard_record. Duplicated cargo_place + inventory_date
    pairs are marked for manual review; we never silently collapse rows.
    """
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_BATCH_ROWS:
        raise OrderBatchError("invalid_batch_size")

    keys: list[tuple[str, str]] = []
    results: list[dict[str, Any]] = []
    summary = {"found": 0, "in_progress": 0, "manual_review": 0}
    for index, item in enumerate(rows):
        if not isinstance(item, dict) or set(item) - {"order", "datalens_scans", "asgard_record", "source_row"}:
            raise OrderBatchError("invalid_batch_row")
        order = item.get("order")
        if not isinstance(order, dict) or set(order) != {"cargo_place", "inventory_date"}:
            raise OrderBatchError("invalid_batch_order")
        scans = item.get("datalens_scans", [])
        if not isinstance(scans, list) or len(scans) > MAX_SCANS_PER_ORDER:
            raise OrderBatchError("invalid_batch_scans")
        asgard = item.get("asgard_record")
        if asgard is not None and not isinstance(asgard, dict):
            raise OrderBatchError("invalid_batch_asgard")
        label = item.get("source_row")
        if label is not None and (isinstance(label, bool) or not isinstance(label, int) or label < 1 or label > 1_000_000):
            raise OrderBatchError("invalid_batch_source_row")

        try:
            proposal = evaluate_order(order, scans, asgard)
        except ValueError as error:
            raise OrderBatchError("invalid_batch_order_data") from error

        key = (order["cargo_place"].strip(), str(order["inventory_date"]))
        keys.append(key)
        results.append({
            "index": index + 1, "source_row": label,
            "cargo_place": order["cargo_place"].strip(),
            "inventory_date": str(order["inventory_date"]),
            "proposal": proposal,
        })

    duplicates = {key for key in keys if keys.count(key) > 1}
    for row, key in zip(results, keys):
        if key in duplicates:
            row["proposal"] = {
                "decision": "manual_review", "proposed_status": None,
                "comment": None, "color": "neutral",
                "reason_code": "duplicate_cargo_place_and_date",
                "evidence": {}, "write_enabled": False,
            }
        proposal = row["proposal"]
        category = "found" if proposal["decision"] == "found" else (
            "in_progress" if proposal["decision"] == "asgard" else "manual_review"
        )
        summary[category] += 1

    return {"results": results, "summary": summary,
            "total": len(results), "read_only": True,
            "source": "manual_input", "write_enabled": False}
