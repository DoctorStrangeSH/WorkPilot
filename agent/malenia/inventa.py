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
    "date": {"дата", "дата заказа", "inventory date", "date"},
    "partner": {"main_partner_code_original", "main_partner", "партнер", "партнёр", "грузоместо", "грузо место"},
    "cost": {"стоимость", "сумма", "цена", "cost", "amount"},
    "name": {"наименование", "товар", "название", "name", "product"},
    "comment": {"комментарий", "comment", "примечание"},
    "ticket": {"тикет", "ticket", "ссылка на тикет"},
    "status": {"статус", "status"},
    "group": {"группировка заказов", "группировка", "group", "grouping"},
}
REQUIRED = ("order_id", "date", "cost", "status")
ANOMALY_WORDS = ("аномал", "потер", "ошиб", "не найден", "проблем")
MONTH_NAMES = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4,
               "мая": 5, "июня": 6, "июля": 7, "августа": 8,
               "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", ("" if value is None else str(value)).strip().casefold().replace("ё", "е"))


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
        score = len(mapping)
        if score >= 4 and (best is None or score > len(best[1])):
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


def _iso_inventory_date(value: Any) -> str | None:
    """Normalize a sheet calendar day, never invent an inventory time."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not 1 <= value <= 100000 or int(value) != value:
            return None
        return (date(1899, 12, 30) + timedelta(days=int(value))).isoformat()
    raw = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _inventory_day_from_title(title: str, rows: list[list[Any]], date_col: int | None) -> str | None:
    """Sheet name determines day/month; row dates may only disambiguate its year."""
    name = title.strip().casefold()
    numeric = re.search(r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}))?(?!\d)", name)
    named = re.search(r"(?<!\d)(\d{1,2})\s+(" + "|".join(MONTH_NAMES) + r")(?:\s+(\d{4}))?(?!\d)", name)
    if numeric:
        day, month = int(numeric[1]), int(numeric[2])
        year = int(numeric[3]) if numeric[3] else None
    elif named:
        day, month = int(named[1]), MONTH_NAMES[named[2]]
        year = int(named[3]) if named[3] else None
    else:
        return None
    if year is None:
        # Never silently apply the current year to an archival inventory tab.
        # A matching cell date may *only* establish the year, not override
        # the day/month supplied by the sheet name.
        matches = set()
        if date_col is not None:
            for row in rows:
                parsed = _iso_inventory_date(row[date_col]) if date_col < len(row) else None
                if parsed and parsed[5:10] == f"{month:02d}-{day:02d}":
                    matches.add(int(parsed[:4]))
        if len(matches) != 1:
            return None
        year = matches.pop()
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def analyze_inventa(rows: list[list[Any]], sheet_title: str = "", *,
                   audit_batch_limit: int = 0) -> dict[str, Any]:
    """Summarize an auto-read sheet; never invent statuses or repair source cells."""
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("inventa_row_limit")
    header_index, columns = detect_header(rows)
    data = rows[header_index + 1:]
    sheet_inventory_date = _inventory_day_from_title(sheet_title, data, columns.get("date"))
    records: list[dict[str, Any]] = []
    ids: dict[str, list[int]] = defaultdict(list)
    statuses: Counter[str] = Counter()
    groups: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    invalid_dates: list[int] = []
    invalid_costs: list[int] = []
    no_ticket: list[int] = []
    anomaly_rows: list[int] = []
    first_order: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = []

    def cell(row: list[Any], key: str) -> Any:
        index = columns.get(key)
        return row[index] if index is not None and index < len(row) else None

    for offset, row in enumerate(data, start=header_index + 2):
        if all(_blank(value) for value in row):
            continue
        order_id = ("" if _blank(cell(row, "order_id")) else str(cell(row, "order_id"))).strip()
        cargo_place = ("" if _blank(cell(row, "partner")) else str(cell(row, "partner"))).strip()
        inventory_date = sheet_inventory_date
        if order_id and cargo_place and inventory_date:
            candidates.append({"source_row": offset, "order_id": order_id,
                           "cargo_place": cargo_place, "inventory_date": inventory_date,
                           "status": ("" if _blank(cell(row, "status")) else str(cell(row, "status"))).strip(),
                           "ticket": ("" if _blank(cell(row, "ticket")) else str(cell(row, "ticket"))).strip()})
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
        records.append({"row": offset, "order_id": order_id, "status": status})

    cargo_counts = Counter(item["cargo_place"] for item in candidates)
    unique_candidates = [item for item in candidates if len(ids[item["order_id"]]) == 1
                         and cargo_counts[item["cargo_place"]] == 1]
    first_order = next(iter(unique_candidates), None)
    duplicates = [{"order_id": key, "rows": positions}
                  for key, positions in ids.items() if len(positions) > 1]
    report = {
        "sheet_title": str(sheet_title)[:200],
        "sheet_inventory_date": sheet_inventory_date,
        "header_row": header_index + 1,
        "columns": {key: index + 1 for key, index in columns.items()},
        "rows_analyzed": len(records),
        "status_counts": dict(statuses),
        "top_groups": [{"name": name, "count": count} for name, count in groups.most_common(10)],
        "missing_required": dict(missing),
        "duplicate_order_ids": duplicates[:200],
        "invalid_date_rows": invalid_dates[:200],
        "invalid_cost_rows": invalid_costs[:200],
        "missing_ticket_rows": no_ticket[:200],
        "anomaly_status_rows": anomaly_rows[:200],
        "first_order": first_order,
        "first_order_blocker": None if first_order else (
            "sheet_date_not_verified" if sheet_inventory_date is None else
            "cargo_column_not_mapped" if "partner" not in columns else "no_unambiguous_order_with_cargo_and_date"),
        "read_only": True,
        "source_rows_are_evidence_not_edits": True,
    }
    # Explicitly opt in: the normal report must not include bulk cargo identifiers.
    # The local agent uses this transient list only to seed a bounded browser job.
    if audit_batch_limit:
        if not 1 <= audit_batch_limit <= 20:
            raise ValueError("invalid_audit_batch_limit")
        safe_candidates = [item for item in unique_candidates
                           if re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", item["cargo_place"])]
        report["audit_candidates"] = safe_candidates[:audit_batch_limit]
        report["eligible_audit_candidates"] = len(safe_candidates)
    return report
