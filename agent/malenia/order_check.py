"""Deterministic, read-only order verification rules.

This module evaluates already-authorized source snapshots. It never fetches data,
writes to Google Sheets, changes Asgard, or performs browser actions.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


DATALENS_SC_ID = "101366"
DATALENS_SUCCESS_RESULT = "OK"

DECISION_FOUND = "found"
DECISION_ASGARD = "asgard"
DECISION_MANUAL_REVIEW = "manual_review"


def _as_date(value: Any, field: str) -> date:
    """Parse an ISO calendar date or ISO datetime without guessing a locale."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be an ISO date or datetime")
    raw = value.strip()
    try:
        if len(raw) == 10:
            return date.fromisoformat(raw)
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO date or datetime") from error


def _manual(reason: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "decision": DECISION_MANUAL_REVIEW,
        "proposed_status": None,
        "comment": None,
        "color": "neutral",
        "reason_code": reason,
        "evidence": evidence or {},
        "write_enabled": False,
    }


def evaluate_order(
    order: dict[str, Any],
    datalens_scans: list[dict[str, Any]],
    asgard_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a proposed order outcome from supplied source snapshots only.

    Required order fields:
      - cargo_place: exact identifier searched as main_partner_code_original
      - inventory_date: ISO calendar date

    DataLens scan fields:
      - main_partner_code_original, sc_id, result, scanned_at

    Asgard fields:
      - status
      - for status "В пути": box_id and extended_history_statuses (list[str])

    Only the exact SC ID 101366 and result OK are considered. The newest
    successful matching scan is compared by calendar date with inventory_date.
    """
    if not isinstance(order, dict):
        raise ValueError("order must be an object")
    cargo_place = order.get("cargo_place")
    if not isinstance(cargo_place, str) or not cargo_place.strip():
        raise ValueError("cargo_place is required")
    cargo_place = cargo_place.strip()
    inventory_date = _as_date(order.get("inventory_date"), "inventory_date")

    if not isinstance(datalens_scans, list):
        raise ValueError("datalens_scans must be a list")

    matching_successful: list[tuple[date, dict[str, Any]]] = []
    for scan in datalens_scans:
        if not isinstance(scan, dict):
            continue
        if scan.get("main_partner_code_original") != cargo_place:
            continue
        if str(scan.get("sc_id", "")) != DATALENS_SC_ID:
            continue
        if scan.get("result") != DATALENS_SUCCESS_RESULT:
            continue
        try:
            scanned_date = _as_date(scan.get("scanned_at"), "scanned_at")
        except ValueError:
            # An eligible but malformed record may be the newest scan. Do not
            # silently ignore it and make a positive decision from stale data.
            return _manual("datalens_matching_scan_has_invalid_date", {
                "source": "datalens",
                "sc_id": DATALENS_SC_ID,
                "result": DATALENS_SUCCESS_RESULT,
            })
        matching_successful.append((scanned_date, scan))

    if matching_successful:
        latest_date, _latest_scan = max(matching_successful, key=lambda item: item[0])
        if latest_date > inventory_date:
            return {
                "decision": DECISION_FOUND,
                "proposed_status": "Найден",
                "comment": None,
                "color": "green",
                "reason_code": "successful_scan_after_inventory",
                "evidence": {
                    "source": "datalens",
                    "cargo_place": cargo_place,
                    "sc_id": DATALENS_SC_ID,
                    "result": DATALENS_SUCCESS_RESULT,
                    "scan_date": latest_date.isoformat(),
                    "inventory_date": inventory_date.isoformat(),
                },
                "write_enabled": False,
            }

    if not isinstance(asgard_record, dict):
        return _manual("asgard_record_required", {
            "source": "asgard",
            "cargo_place": cargo_place,
            "datalens_latest_successful_scan_date": (
                max(item[0] for item in matching_successful).isoformat()
                if matching_successful else None
            ),
        })

    asgard_status = asgard_record.get("status")
    base_evidence = {
        "source": "asgard",
        "cargo_place": cargo_place,
        "status": asgard_status if isinstance(asgard_status, str) else None,
    }

    if asgard_status == "Принят на ФФ":
        return {
            "decision": DECISION_ASGARD,
            "proposed_status": "В работе",
            "comment": "Принят на ФФ",
            "color": "orange",
            "reason_code": "asgard_accepted_at_fulfillment",
            "evidence": base_evidence,
            "write_enabled": False,
        }

    if asgard_status == "Выдан":
        return {
            "decision": DECISION_ASGARD,
            "proposed_status": "В работе",
            "comment": "Выдан",
            "color": "orange",
            "reason_code": "asgard_issued",
            "evidence": base_evidence,
            "write_enabled": False,
        }

    if asgard_status == "В пути":
        box_id = asgard_record.get("box_id")
        history = asgard_record.get("extended_history_statuses")
        if not isinstance(box_id, str) or not box_id.strip():
            return _manual("asgard_box_id_required_for_in_transit", base_evidence)
        if not isinstance(history, list) or not all(isinstance(item, str) for item in history):
            return _manual("asgard_extended_history_required_for_in_transit", base_evidence)
        if "Выдан" in history:
            return {
                "decision": DECISION_ASGARD,
                "proposed_status": "В работе",
                "comment": "2 ШК Выдан",
                "color": "orange",
                "reason_code": "asgard_in_transit_with_issued_box_history",
                "evidence": {**base_evidence, "box_id": box_id.strip(), "history_contains": "Выдан"},
                "write_enabled": False,
            }
        return _manual("asgard_in_transit_without_confirmed_issued_history", {
            **base_evidence, "box_id": box_id.strip(),
        })

    return _manual("unknown_asgard_status", base_evidence)
