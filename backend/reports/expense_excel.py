"""Single-sheet WF3 expense register export.

The workbook is deliberately a business-facing register, not a dump of the JSON record.
Only claims that have entered the submission/approval lifecycle are included; evidence
hashes, model diagnostics and other technical audit fields remain available in the app.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from io import BytesIO
from typing import Iterable

from openpyxl import Workbook

from .. import money
from ..backends.records import Record
from ..fixtures import org

SHEET_NAME = "Receipts"
EXPORTABLE_STATUSES = {
    "submitted",
    "resubmitted",
    "needs_information",
    "approved",
    "rejected",
}

HEADERS = (
    "Claim ID",
    "Applicant",
    "Department",
    "Vendor",
    "Receipt Date",
    "Category",
    "Business Purpose",
    "Payment Method",
    "Amount",
    "Currency",
    "Amount GBP",
    "Submitted At",
    "Status",
    "Approver",
    "Decided At",
    "Decision Reason",
)

def _excel_text(value: object) -> str | None:
    """Keep user/model-provided text from being interpreted as an Excel formula."""
    if value is None:
        return None
    text = str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _person_name(user_id: object) -> str | None:
    if not user_id:
        return None
    person = org.find_person(str(user_id))
    return person.name if person else str(user_id)


def _department(data: dict) -> str | None:
    if data.get("department"):
        return str(data["department"])
    person = org.find_person(str(data.get("employee_name") or ""))
    return person.department if person else None


def _date_value(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    return None


def _datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    # Excel stores naive datetimes. Normalise aware values to naive UTC so sorting remains
    # deterministic and the displayed value represents the same instant.
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _row(record: Record) -> list[object]:
    data = record.data
    decided_at = data.get("decided_at")
    if not decided_at and record.status in {"approved", "rejected"}:
        decided_at = record.updated_at
    return [
        record.id,
        _excel_text(data.get("employee_name")),
        _excel_text(_department(data)),
        _excel_text(data.get("vendor")),
        _date_value(data.get("date")),
        _excel_text(data.get("category")),
        _excel_text(data.get("business_purpose")),
        _excel_text(data.get("payment_method")),
        float(data["amount"]) if data.get("amount") is not None else None,
        _excel_text(str(data.get("currency") or "").upper() or None),
        money.gbp_of({"status": record.status, **data}),
        _datetime_value(data.get("submitted_at") or record.created_at),
        _excel_text(record.status),
        _excel_text(_person_name(data.get("reviewed_by"))),
        _datetime_value(decided_at),
        _excel_text(data.get("decision_reason")),
    ]


def export_expense_workbook(records: Iterable[Record]) -> bytes:
    """Return a plain XLSX worksheet containing the exportable receipt fields."""
    claims = [
        record for record in records
        if record.type == "expense_claim" and record.status in EXPORTABLE_STATUSES
    ]
    claims.sort(
        key=lambda record: str(record.data.get("submitted_at") or record.created_at),
        reverse=True,
    )

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_NAME
    sheet.append(list(HEADERS))
    for record in claims:
        sheet.append(_row(record))

    for cell in sheet["E"][1:]:
        cell.number_format = "yyyy-mm-dd"
    for column in ("L", "O"):
        for cell in sheet[column][1:]:
            cell.number_format = "yyyy-mm-dd hh:mm"
    for cell in sheet["I"][1:]:
        cell.number_format = "#,##0.00"
    for cell in sheet["K"][1:]:
        cell.number_format = '£#,##0.00'

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
