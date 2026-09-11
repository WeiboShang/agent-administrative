"""Deterministic policy / checks engine (docs/workflow_design.md).

Flags with a reason; **never auto-rejects** — the human decides (docs/workflow_design.md). Each flag
is ``soft`` (surface it; the human may override) or ``hard`` (blocks the write even on
approve). All logic is CODE, not the LLM (docs/workflow_design.md). Budget/quota *consumption* is
derived from approved records in the store, so the store is the single source of truth.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date as _date
from typing import Any, Optional

from ..agent.image_hash import hamming
from ..backends.records import RecordStore
from ..fixtures import org
from ..money import gbp_of, to_gbp

# ── config (tunable; see docs/workflow_design.md) ──
# All GBP-denominated: a foreign-currency claim is converted (backend/money.py) before any
# comparison against these.
PER_DIEM: dict[str, float] = {
    "meals": 50.0, "accommodation": 150.0, "supplies": 200.0, "software": 500.0,
    "other": 100.0,
}  # "travel" has no cap
WORKING_HOURS = ("09:00", "18:00")

# Arithmetic self-consistency (see docs/workflow_design.md). Tolerances absorb rounding;
# a real dropped/duplicated line moves the sum well past them.
ARITHMETIC_TOLERANCE = 0.02          # absolute floor (pennies of rounding)
ARITHMETIC_REL_TOLERANCE = 0.005     # or 0.5% of the total, whichever is larger
TAX_MAX_SHARE = 0.40                 # tax above this share of the total is implausible

# Perceptual-hash near-duplicate (docs §L.2). Hamming distance (of 64 bits) at or below this
# to an approved claim's image fingerprint → probable re-photograph / one-field edit.
PHASH_SIMILAR_THRESHOLD = 6

# Categories of spend the org never reimburses (word-boundary match over vendor,
# business_purpose and — when available at review time — receipt line items).
_NON_REIMBURSABLE_RE = re.compile(
    r"\b(alcohol|beers?|wine|spirits|whisky|vodka|gin|cigarettes?|tobacco|vape|"
    r"lottery|casino|gift ?cards?|parking fine|penalt(?:y|ies)|fines?)\b", re.IGNORECASE)


def _normalise_vendor(value: Any) -> str:
    """Canonical vendor identity for policy comparisons."""
    decomposed = unicodedata.normalize("NFKD", str(value or "")).casefold()
    unaccented = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", unaccented).strip()


@dataclass
class Flag:
    rule: str
    severity: str  # "soft" | "hard"
    message: str


def has_hard(flags: list[Flag]) -> bool:
    """True if any flag hard-blocks the write (approve must be gated)."""
    return any(f.severity == "hard" for f in flags)


# ── helpers ──
def _uid(name_or_id: str) -> Optional[str]:
    p = org.find_person(name_or_id or "")
    return p.user_id if p else None


def _dept(name_or_id: str) -> Optional[str]:
    p = org.find_person(name_or_id or "")
    return p.department if p else None


def _approved_expenses(store: RecordStore) -> list[dict[str, Any]]:
    return [r.data for r in
            store.list("submissions", record_type="expense_claim", status="approved")]


def _record_dept(e: dict[str, Any]) -> Optional[str]:
    """Which budget a claim is charged to: its explicit department, else the employee's."""
    return e.get("department") or _dept(e.get("employee_name", ""))


def _spent_gbp(e: dict[str, Any]) -> float:
    """An approved claim's GBP value, for budget/quota consumption.

    Uses the rate frozen onto the record at submit time when present, so editing the FX
    table never restates what a department has already spent (backend/money.py).

    New claims with an unknown currency cannot be approved. A historical unresolved record
    contributes zero here rather than mixing currency scales; migration exposes it as an
    unresolved conversion for remediation.
    """
    value = gbp_of(e)
    return value if value is not None else 0.0


def budget_remaining(department: str, store: RecordStore) -> Optional[float]:
    total = org.get_budget_total(department)
    if total is None:
        return None
    spent = sum(_spent_gbp(e) for e in _approved_expenses(store)
                if _record_dept(e) == department)
    return total - spent


def expense_quota_remaining(user_id: str, store: RecordStore) -> Optional[float]:
    q = org.get_quota(user_id)
    if q is None:
        return None
    spent = sum(_spent_gbp(e) for e in _approved_expenses(store)
                if _uid(e.get("employee_name", "")) == user_id)
    return q["expense_annual"] - spent


# ── WF3 reasoning layer: arithmetic self-consistency (docs §L.1) ──
def check_arithmetic(fields: dict[str, Any]) -> list[Flag]:
    """The LLM read the numbers; deterministic code proves they add up.

    Currency-agnostic (every value is in the receipt's own currency, so no FX). **Soft only**
    (docs/workflow_design.md): a mismatch is usually a model misread — a dropped line — which is exactly
    the case the human verifies against the image; occasionally a genuinely odd receipt.
    """
    flags: list[Flag] = []
    amount = fields.get("amount")
    if not (isinstance(amount, (int, float)) and not isinstance(amount, bool)) or amount <= 0:
        return flags

    items = [it.get("amount") for it in (fields.get("line_items") or [])
             if isinstance(it, dict)]
    items = [a for a in items if isinstance(a, (int, float)) and not isinstance(a, bool)]
    tax = fields.get("tax")
    has_tax = isinstance(tax, (int, float)) and not isinstance(tax, bool)
    tol = max(ARITHMETIC_TOLERANCE, amount * ARITHMETIC_REL_TOLERANCE)

    # line-item sum: reconcile as tax-inclusive (sum == total) or tax-exclusive (sum + tax)
    if items:
        s = round(sum(items), 2)
        incl = abs(s - amount) <= tol
        excl = has_tax and abs(s + tax - amount) <= tol
        if not (incl or excl):
            flags.append(Flag("arithmetic_mismatch", "soft",
                              f"line items total {s:g} but claim total is {amount:g}"))

    # tax plausibility
    if has_tax:
        if tax < 0 or tax > amount:
            flags.append(Flag("arithmetic_mismatch", "soft",
                              f"tax {tax:g} is not between 0 and the total {amount:g}"))
        elif tax / amount > TAX_MAX_SHARE:
            flags.append(Flag("arithmetic_mismatch", "soft",
                              f"tax {tax:g} is an implausible {tax / amount * 100:.0f}% of the total"))
    return flags


# ── WF3 reasoning layer: perceptual-hash near-duplicate (docs §L.2) ──
def check_similar_image(fields: dict[str, Any], store: RecordStore) -> list[Flag]:
    """Soft-flag a claim whose receipt image is visually near-identical to an approved one.

    Complements — does not replace — the exact ``vendor+date+amount`` `duplicate` rule: exact
    field-match stays **hard** (a certain duplicate, blocks the write); a small image Hamming
    distance is **soft** (probable re-photograph or one-field edit — the human confirms).
    Needs the fingerprint computed at extract time (`image_phash`, from the image bytes).
    """
    h = fields.get("image_phash")
    try:
        h = int(h, 16) if isinstance(h, str) else h
    except ValueError:
        return []
    if not isinstance(h, int) or isinstance(h, bool):
        return []
    for r in store.list("submissions", record_type="expense_claim", status="approved"):
        eh = r.data.get("image_phash")
        try:
            eh = int(eh, 16) if isinstance(eh, str) else eh
        except ValueError:
            continue
        if isinstance(eh, int) and not isinstance(eh, bool) and hamming(h, eh) <= PHASH_SIMILAR_THRESHOLD:
            sim = round((1 - hamming(h, eh) / 64) * 100)
            return [Flag("similar_receipt", "soft",
                         f"visually ~{sim}% identical to approved claim {r.id}")]
    return []


# ── WF3 expense: core rules (future-date · over-limit · budget/quota · duplicate ·
#    doc-mismatch · non-reimbursable · unknown-currency · arithmetic · similar-image) ──
def check_expense(fields: dict[str, Any], store: RecordStore, *,
                  extracted_amount: Optional[float] = None,
                  line_items: Optional[list[dict[str, Any]]] = None,
                  today: Optional[_date] = None) -> list[Flag]:
    flags: list[Flag] = []
    amount = fields.get("amount")
    currency = fields.get("currency")
    category = fields.get("category")
    name = fields.get("employee_name", "")
    numeric = isinstance(amount, (int, float)) and not isinstance(amount, bool)

    # Receipts document transactions that have already happened. Historical dates are the
    # normal case; a future date is likely a vision/typing error, but remains a soft flag for
    # human review rather than an automatic business decision.
    try:
        claim_date = _date.fromisoformat(fields.get("date", ""))
    except (TypeError, ValueError):
        claim_date = None
    if claim_date is not None and claim_date > (today or _date.today()):
        flags.append(Flag("future_date", "soft",
                          f"{claim_date.isoformat()} is in the future — verify the receipt date"))

    # convert to GBP for all limit comparisons; unknown currency → flag, skip comparisons
    amount_gbp: Optional[float] = to_gbp(amount, currency) if numeric else None
    if numeric and amount_gbp is None:
        flags.append(Flag("unknown_currency", "hard",
                          f"cannot convert {currency!r} to GBP — select a supported currency"))
    _fx = "" if (currency or "GBP").upper() == "GBP" else f" ({amount:g} {currency})"

    # 1. over category limit (hard). The configured per-diem is a mandatory
    # reimbursement constraint; a claimant-authored exception note is not independent
    # approval evidence and cannot override it.
    limit = PER_DIEM.get(category or "")
    if amount_gbp is not None and limit is not None and amount_gbp > limit:
        flags.append(Flag("over_limit", "hard",
                          f"£{amount_gbp:g}{_fx} exceeds {category} £{limit:g}/day limit"))

    # 2. budget / quota exhausted (hard)
    if amount_gbp is not None:
        dept = fields.get("department") or _dept(name)
        if dept is not None:
            rem = budget_remaining(dept, store)
            if rem is not None and amount_gbp > rem:
                flags.append(Flag("budget_exhausted", "hard",
                                  f"{dept} budget has £{rem:g} remaining "
                                  f"(claim £{amount_gbp:g}{_fx})"))
        uid = _uid(name)
        if uid is not None:
            qrem = expense_quota_remaining(uid, store)
            if qrem is not None and amount_gbp > qrem:
                flags.append(Flag("quota_exhausted", "hard",
                                  f"exceeds remaining annual quota (£{qrem:g} left)"))

    # 5. non-reimbursable spend (soft) — vendor / purpose / receipt line items
    texts = [fields.get("vendor"), fields.get("business_purpose"),
             *(li.get("desc") for li in (line_items or []))]
    for t in texts:
        m = _NON_REIMBURSABLE_RE.search(str(t or ""))
        if m:
            flags.append(Flag("non_reimbursable", "soft",
                              f"possibly non-reimbursable item: {m.group(0)!r}"))
            break

    # 3. duplicate (hard) — same canonical vendor + date + amount + currency as an
    # approved claim. Name the matching evidence so the reviewer is not left with a
    # generic ``blocked_policy`` response.
    for e in _approved_expenses(store):
        if (_normalise_vendor(e.get("vendor")) == _normalise_vendor(fields.get("vendor"))
                and e.get("date") == fields.get("date")
                and e.get("amount") == amount
                and str(e.get("currency") or "GBP").upper()
                == str(fields.get("currency") or "GBP").upper()):
            flags.append(Flag(
                "duplicate", "hard",
                "matches an approved claim: "
                f"{e.get('vendor')} · {e.get('date')} · "
                f"{str(e.get('currency') or 'GBP').upper()} {e.get('amount')}",
            ))
            break

    # 4. documentation mismatch (soft) — only when the raw extraction is supplied
    if (extracted_amount is not None and numeric and extracted_amount != amount):
        flags.append(Flag("doc_mismatch", "soft",
                          f"receipt shows £{extracted_amount:g} but claim says £{amount:g}"))

    # 6. arithmetic self-consistency (soft) — the reasoning layer (docs §L.1)
    flags += check_arithmetic(fields)

    # 7. visually near-identical to an approved claim (soft) — image fingerprint (docs §L.2)
    flags += check_similar_image(fields, store)
    return flags


# ── WF2 scheduling checks ──
def _overlaps(s1: str, e1: str, s2: str, e2: str) -> bool:
    return s1 < e2 and s2 < e1


def check_scheduling(event: dict[str, Any], store: RecordStore, *,
                     now: Optional[_date] = None) -> list[Flag]:
    flags: list[Flag] = []
    date, start, end = event.get("date"), event.get("start"), event.get("end")

    # booking into the past (soft) — reachable since relative dates resolve against the
    # *thread's* arrival time, so a thread handled late can legitimately resolve to a past
    # day. Flag it; the human decides whether it was meant retroactively.
    if now is not None and date:
        try:
            if _date.fromisoformat(str(date)) < now:
                flags.append(Flag("past_date", "soft",
                                  f"{date} is in the past — confirm the intended date"))
        except ValueError:
            pass
    participants = event.get("participants", [])
    room_name = event.get("location") or event.get("room")

    # unknown participants (soft) + resolve the rest for conflict checking
    uids: list[str] = []
    for name in participants:
        uid = _uid(name)
        if uid is None:
            flags.append(Flag("unknown_participant", "soft", f"unknown participant: {name}"))
        else:
            uids.append(uid)

    # conflicts + room double-booking (soft) — need a time window
    if date and start and end:
        for ev in store.list("events", status="booked"):
            d = ev.data
            if d.get("date") != date or not _overlaps(start, end,
                                                      d.get("start", ""), d.get("end", "")):
                continue
            for uid in set(uids) & set(d.get("participants", [])):
                flags.append(Flag("conflict", "soft",
                                  f"{uid} busy {d.get('start')}–{d.get('end')} "
                                  f"({d.get('title', '')})"))
            # Current event records persist the selected room as ``location``; older seeds
            # used ``room``.  Read both or two different meetings can silently occupy the
            # same room merely because they came through different entry paths.
            existing_room = d.get("location") or d.get("room")
            if room_name and existing_room == room_name:
                flags.append(Flag("room_double_booked", "soft",
                                  f"{room_name} already booked {d.get('start')}–{d.get('end')}"))

    # room over-capacity (soft)
    if room_name:
        room = next((r for r in org.ROOMS if r.name == room_name), None)
        if room is not None and len(participants) > room.capacity:
            flags.append(Flag("room_over_capacity", "soft",
                              f"{len(participants)} people > {room_name} capacity {room.capacity}"))

    # out of hours (soft)
    if start and (start < WORKING_HOURS[0] or (end and end > WORKING_HOURS[1])):
        flags.append(Flag("out_of_hours", "soft",
                          f"outside working hours {WORKING_HOURS[0]}–{WORKING_HOURS[1]}"))
    return flags
