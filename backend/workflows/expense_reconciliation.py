"""Gold-free deterministic reconciliation of receipt category evidence.

This production helper reads only the extracted receipt fields and the current mock
workspace.  It deliberately has no dependency on evaluation datasets or scorers.
"""
from __future__ import annotations

import difflib
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..agent.normalise import clean, clean_number
from . import policy


_ITEM_TERMS: dict[str, tuple[str, ...]] = {
    "meals": (
        "breakfast", "coffee", "dinner", "lunch", "meal", "salad", "sandwich",
        "soup",
    ),
    "travel": (
        "airline", "bus", "fare", "flight", "fuel", "parking", "rail", "taxi",
        "train",
    ),
    "accommodation": ("b&b", "city tax", "hotel", "lodging", "room"),
    "supplies": (
        "electronics", "notebook", "paper", "pens", "stapler", "stationery",
    ),
    "software": ("api credits", "cloud storage", "license", "saas", "subscription"),
    "other": ("misc", "service", "sundry"),
}

_CATEGORY_ORDER = (
    "meals", "accommodation", "travel", "software", "supplies",
    "entertainment", "training", "other",
)

_AUTO_PURPOSE_BY_CATEGORY = {
    "meals": "Business meal",
    "travel": "Business travel",
    "accommodation": "Business accommodation",
    "supplies": "Office supplies",
    "software": "Software / tools",
    "entertainment": "Client entertainment",
    "training": "Training / development",
}

CRITICAL_READ_SELECTOR_VERSION = "receipt-critical-risk-v1"


def critical_read_triggers(
    extraction: dict[str, Any], *, now: date | datetime | None = None,
) -> tuple[str, ...]:
    """Return source-only reasons for requesting an independent critical-field read."""
    if extraction.get("not_a_receipt"):
        return ()
    today = (
        now.date() if isinstance(now, datetime)
        else now if isinstance(now, date)
        else datetime.now(timezone.utc).date()
    )
    reasons: list[str] = []
    for field in ("vendor", "date", "amount", "currency"):
        value = extraction.get(field)
        if value in (None, ""):
            reasons.append(f"missing:{field}")
        elif _has_ocr_damage(value):
            reasons.append(f"ocr_damage:{field}")

    confidence = extraction.get("field_confidence")
    if not isinstance(confidence, dict) or not confidence:
        reasons.append("missing:field_confidence")
    else:
        for field in ("vendor", "date", "amount"):
            if field not in confidence:
                continue
            try:
                if float(confidence[field]) < 0.8:
                    reasons.append(f"low_confidence:{field}")
            except (TypeError, ValueError):
                reasons.append(f"invalid_confidence:{field}")

    raw_date = extraction.get("date")
    if raw_date not in (None, ""):
        try:
            receipt_date = date.fromisoformat(str(raw_date))
            if receipt_date < today - timedelta(days=730):
                reasons.append("date_outlier:stale")
            elif receipt_date > today + timedelta(days=1):
                reasons.append("date_outlier:future")
        except ValueError:
            reasons.append("date_outlier:invalid")
    return tuple(dict.fromkeys(reasons))


def _category_candidates(line_items: Any) -> tuple[str, ...]:
    candidates: set[str] = set()
    for item in line_items or []:
        if not isinstance(item, dict):
            continue
        description = str(item.get("desc") or "").strip().casefold()
        for category, terms in _ITEM_TERMS.items():
            if any(term in description for term in terms):
                candidates.add(category)
    # Generic descriptions must not outweigh any specific purchased item.
    specific = candidates - {"other"}
    selected = specific or candidates
    return tuple(category for category in _CATEGORY_ORDER if category in selected)


def _text_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().casefold())
    return "".join(char for char in text if char.isalnum())


def _equivalent(field: str, left: Any, right: Any) -> bool:
    if field == "amount":
        try:
            return abs(float(left) - float(right)) <= 0.005
        except (TypeError, ValueError):
            return False
    if field == "currency":
        return str(left or "").strip().upper() == str(right or "").strip().upper()
    if field == "vendor":
        return _text_key(left) == _text_key(right)
    return str(left or "").strip() == str(right or "").strip()


def _has_ocr_damage(value: Any) -> bool:
    return any(
        char == "\ufffd" or (not char.isalnum() and not char.isspace() and char not in "&'.-")
        for char in str(value or "")
    )


def _clean_second_value(field: str, value: Any) -> Any:
    if field == "amount":
        return clean_number(value)
    value = clean(value)
    return str(value).strip().upper() if field == "currency" and value else value


def _reconcile_critical_fields(
    fields: dict[str, Any], second_read: dict[str, Any] | None
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    reconciled = dict(fields)
    changed: list[str] = []
    conflicts: list[dict[str, Any]] = []
    if second_read is None:
        return reconciled, changed, conflicts
    for field in ("vendor", "date", "amount", "currency"):
        first = reconciled.get(field)
        second = _clean_second_value(field, second_read.get(field))
        if second in (None, ""):
            continue
        if first in (None, ""):
            reconciled[field] = second
            changed.append(field)
            continue
        if _equivalent(field, first, second):
            continue
        if field == "vendor":
            # A visibly damaged second transcription is weaker evidence than a clean
            # primary transcription and must not manufacture a review conflict.
            if _has_ocr_damage(second) and not _has_ocr_damage(first):
                continue
            if _has_ocr_damage(first):
                similarity = difflib.SequenceMatcher(
                    None, _text_key(first), _text_key(second)
                ).ratio()
                if similarity >= 0.88 and not _has_ocr_damage(second):
                    reconciled[field] = second
                    changed.append(field)
                    continue
        conflicts.append({"field": field, "primary": first, "critical": second})
    return reconciled, changed, conflicts


def reconcile_expense_evidence(
    fields: dict[str, Any], extraction: dict[str, Any], store: Any,
    *, second_read: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve category from visible line items when the policy outcome is unambiguous.

    The function never repairs vendor/date/amount by guessing.  If plausible categories
    disagree on whether a hard policy rule applies, it preserves the model value and marks
    the draft for human review instead of selecting the favourable outcome.
    """
    reconciled, critical_changes, critical_conflicts = _reconcile_critical_fields(
        fields, second_read
    )
    candidates = _category_candidates(
        extraction.get("line_items") or reconciled.get("line_items")
    )
    current = reconciled.get("category")
    report: dict[str, Any] = {
        "source": "line_item_evidence",
        "candidates": list(candidates),
        "original_category": current,
        "selected_category": current,
        "changed_fields": list(critical_changes),
        "critical_conflicts": critical_conflicts,
        "requires_review": bool(critical_conflicts),
    }
    if not candidates:
        report["status"] = "no_category_evidence"
        return reconciled, report

    hard_by_category: dict[str, bool] = {}
    for category in candidates:
        candidate = {**reconciled, "category": category}
        flags = policy.check_expense(
            candidate,
            store,
            extracted_amount=extraction.get("amount"),
            line_items=extraction.get("line_items") or reconciled.get("line_items") or [],
        )
        hard_by_category[category] = any(flag.severity == "hard" for flag in flags)
    report["hard_policy_by_category"] = hard_by_category
    if len(set(hard_by_category.values())) > 1:
        report.update(status="policy_sensitive_ambiguity", requires_review=True)
        return reconciled, report

    selected = candidates[0]
    reconciled["category"] = selected
    report.update(status="reconciled", selected_category=selected)
    if selected != current:
        report["changed_fields"].append("category")
        purpose = reconciled.get("business_purpose")
        if purpose in _AUTO_PURPOSE_BY_CATEGORY.values():
            reconciled["business_purpose"] = _AUTO_PURPOSE_BY_CATEGORY.get(
                selected, "Business expense"
            )
            report["changed_fields"].append("business_purpose")
    return reconciled, report
