"""Deterministic, read-only analysis helpers for the user's INVenta Google Sheet.

The module never accesses the network or writes source data. It accepts rows
returned by the Google Sheets API and reports evidence by sheet row number.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import re
from typing import Any

ALIASES = {
    "order_id": {"id заказа", "номер заказа", "заказ", "order id", "order_id"},
    "date": {"дата", "дата заказа", "дата выгрузки", "inventory date", "date"},
    "partner": {"main_partner_code_original", "main_partner", "партнер", "партнёр"},
    "cost": {"стоимость", "сумма", "цена", "cost", "amount"},
    "name": {"наименование", "товар", "название", "name", "product"},
    "comment": {"комментарий", "comment", "примечание"},
    "ticket": {"тикет", "ticket", "ссылка на тикет"},
    "status": {"статус", "status"},
    "group": {"группировка заказов", "группировка заказа", "группировка", "group", "grouping"},
}
REQUIRED = ("order_id", "date", "cost", "status")
ANOMALY_WORDS = ("аномал", "потер", "ошиб", "не найден", "проблем")


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", ("" if value is None else str(value)).strip().casefold().replace("ё", "е"))


_STATUS_MARKERS = (
    "в скк", "исключение", "найден", "в работе", "аномал", "потер",
    "отгрузили после", "подана на иск", "ретеншн", "ожидает", "не найден",
)


def _infer_status_column(rows: list[list[Any]], header_index: int, mapping: dict[str, int]) -> int | None:
    """Infer an unlabeled status column from repeated, recognizable status values."""
    if "status" in mapping:
        return mapping["status"]
    width = max((len(row) for row in rows[header_index + 1:header_index + 51]), default=0)
    candidates: list[tuple[float, int]] = []
    for column in range(width):
        if column in mapping.values():
            continue
        values = [
            _norm(row[column]) for row in rows[header_index + 1:header_index + 51]
            if column < len(row) and not _blank(row[column])
        ]
        if len(values) < 2:
            continue
        matches = sum(any(marker in value for marker in _STATUS_MARKERS) for value in values)
        ratio = matches / len(values)
        if matches >= 2 and ratio >= 0.5:
            candidates.append((ratio + min(matches, 10) / 100, column))
    return max(candidates)[1] if candidates else None


def detect_header(rows: list[list[Any]], scan_rows: int = 12) -> tuple[int, dict[str, int]]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("empty_sheet")
    best: tuple[int, dict[str, int]] | None = None
    for row_index, row in enumerate(rows[:scan_rows]):
        mapping: dict[str, int] = {}
        for col_index, value in enumerate(row):
            label = _norm(value)
            for field, aliases in ALIASES.items():
                if label in {_norm(alias) for alias in aliases} and field not in mapping:
                    mapping[field] = col_index
        status_column = _infer_status_column(rows, row_index, mapping)
        if status_column is not None:
            mapping["status"] = status_column
        score = len(mapping)
        if set(REQUIRED).issubset(mapping) and (best is None or score > len(best[1])):
            best = (row_index, mapping)
    if best is None:
        raise ValueError("inventa_headers_not_recognized")
    return best


def _date_ok(value: Any) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Google Sheets serial date (1899-12-30), bounded to plausible dates.
        return 1 <= value <= 100000
    raw = str(value or "").strip()
    if not raw:
        return False
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            datetime.strptime(raw[:10], fmt)
            return True
        except ValueError:
            pass
    return False


def _number_ok(value: Any) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    raw = str(value or "").strip().replace(" ", "").replace(",", ".")
    if not raw:
        return False
    try:
        return float(raw) >= 0
    except ValueError:
        return False


def analyze_inventa(rows: list[list[Any]], sheet_title: str = "") -> dict[str, Any]:
    """Summarize an auto-read sheet; never invent statuses or repair source cells."""
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("inventa_row_limit")
    header_index, columns = detect_header(rows)
    data = rows[header_index + 1:]
    records: list[dict[str, Any]] = []
    ids: dict[str, list[int]] = defaultdict(list)
    statuses: Counter[str] = Counter()
    groups: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    invalid_dates: list[int] = []
    invalid_costs: list[int] = []
    no_ticket: list[int] = []
    anomaly_rows: list[int] = []

    def cell(row: list[Any], key: str) -> Any:
        index = columns.get(key)
        return row[index] if index is not None and index < len(row) else None

    for offset, row in enumerate(data, start=header_index + 2):
        if all(_blank(value) for value in row):
            continue
        order_id = ("" if _blank(cell(row, "order_id")) else str(cell(row, "order_id"))).strip()
        status = ("" if _blank(cell(row, "status")) else str(cell(row, "status"))).strip()
        group = ("" if _blank(cell(row, "group")) else str(cell(row, "group"))).strip()
        if order_id:
            ids[order_id].append(offset)
        else:
            missing["order_id"] += 1
        if not status:
            missing["status"] += 1
        else:
            statuses[status] += 1
            if any(word in _norm(status) for word in ANOMALY_WORDS):
                anomaly_rows.append(offset)
        if _blank(cell(row, "date")) or not _date_ok(cell(row, "date")):
            invalid_dates.append(offset)
        if _blank(cell(row, "cost")):
            missing["cost"] += 1
        elif not _number_ok(cell(row, "cost")):
            invalid_costs.append(offset)
        if _blank(cell(row, "name")):
            missing["name"] += 1
        if _blank(cell(row, "ticket")):
            no_ticket.append(offset)
        if group:
            groups[group] += 1
        records.append({
            "row": offset,
            "order_id": order_id,
            "partner_code": "" if _blank(cell(row, "partner")) else str(cell(row, "partner")).strip(),
            "date": "" if _blank(cell(row, "date")) else str(cell(row, "date")).strip(),
            "cost": "" if _blank(cell(row, "cost")) else str(cell(row, "cost")).strip(),
            "name": "" if _blank(cell(row, "name")) else str(cell(row, "name")).strip(),
            "ticket": "" if _blank(cell(row, "ticket")) else str(cell(row, "ticket")).strip(),
            "status": status,
            "group": group,
        })

    duplicates = [{"order_id": key, "rows": positions}
                  for key, positions in ids.items() if len(positions) > 1]
    return {
        "sheet_title": str(sheet_title)[:200],
        "header_row": header_index + 1,
        "columns": {key: index + 1 for key, index in columns.items()},
        "rows_analyzed": len(records),
        # Bounded read-only preview; not a verified cross-system decision.
        "first_order_preview": records[0] if records else None,
        "first_order_cross_check": {
            "state": "needs_external_sources",
            "verified": False,
            "missing_sources": ["DataLens", "Asgard"],
            "write_enabled": False,
        } if records else None,
        "status_counts": dict(statuses),
        "top_groups": [{"name": name, "count": count} for name, count in groups.most_common(10)],
        "missing_required": dict(missing),
        "duplicate_order_ids": duplicates[:200],
        "invalid_date_rows": invalid_dates[:200],
        "invalid_cost_rows": invalid_costs[:200],
        "missing_ticket_rows": no_ticket[:200],
        "anomaly_status_rows": anomaly_rows[:200],
        "read_only": True,
        "source_rows_are_evidence_not_edits": True,
    }
