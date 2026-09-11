"""Synthetic organisation fixture — single source of truth for the fictional world.

Used by the mock backends (DirectoryBackend, conflict checks) AND the synthetic data
generators (docs/data_strategy.md §3), so a generated message mentioning "Bob" always
resolves to a real directory entry. Extended for the v2 re-scope
(docs/workflow_design.md §2.3): departments, budgets, quotas, and seed records.

All data is fictional (CLAUDE.md §3.1); emails are @example.com.

Design note: budget/quota *consumption* is DERIVED from approved records in the store,
not tracked here — these constants are only the allocations. The seed records below are
what make the initial consumption non-zero. Reset the store to reset the world.
"""
from dataclasses import dataclass
from datetime import date as _date
from datetime import timedelta
from typing import Any, Optional

from ..backends.base import Person
from ..money import convert as _fx_convert

PEOPLE: list[Person] = [
    Person("alice", "Alice Tan",    "alice@example.com", "Product Manager",     "Product"),
    Person("bob",   "Bob Rivera",   "bob@example.com",   "Engineering Lead",    "Engineering"),
    Person("chen",  "Chen Wei",     "chen@example.com",  "Finance Analyst",     "Finance"),
    Person("dana",  "Dana Okoro",   "dana@example.com",  "HR Coordinator",      "People"),
    Person("evan",  "Evan Schmidt", "evan@example.com",  "IT Support",          "IT"),
    Person("fiona", "Fiona Reyes",  "fiona@example.com", "Operations Director", "Operations"),
]


@dataclass(frozen=True)
class Room:
    room_id: str
    name: str
    capacity: int


ROOMS: list[Room] = [
    Room("room-orion", "Orion", 6),
    Room("room-lyra",  "Lyra",  12),
    Room("room-vega",  "Vega",  3),
]


@dataclass(frozen=True)
class BusySlot:
    user_id: str
    date: str   # YYYY-MM-DD
    start: str  # HH:MM
    end: str    # HH:MM
    title: str


# Pre-seeded calendar state so WF2 conflict detection has something to detect. The
# 2026-07-07 14:00–15:00 block on `bob` deliberately clashes with the flagship WF2
# example ("next Tuesday afternoon ... budget").
BUSY_SLOTS: list[BusySlot] = [
    BusySlot("bob",   "2026-07-07", "14:00", "15:00", "1:1 with Fiona"),
    BusySlot("alice", "2026-07-07", "11:00", "11:30", "Team standup"),
    BusySlot("chen",  "2026-07-08", "09:00", "10:00", "Month-end close"),
]

# Those dates are pinned to the EVALUATION epoch and must never float: scheduling_data.py
# builds its gold from GEN_NOW = 2026-06-30, and scheduling_score._expected_conflict compares
# that gold against these very slots. Moving them would make evaluation irreproducible
# (CLAUDE.md §3.4).
#
# The LIVE workspace needs the opposite. Once the app runs on a real clock, a clash pinned to
# July 2026 is just a past meeting, and the flagship demo ("next Tuesday at 14:00" clashing
# with Bob) silently stops demonstrating anything. So the live seed SHIFTS these by whole
# weeks onto the coming Tuesday — same weekday, same times, same story — while every eval and
# test keeps the fixed dates by taking the default.
_ANCHOR_TUESDAY = _date(2026, 7, 7)   # the Tuesday BUSY_SLOTS sit on


def _next_weekday(ref: _date, weekday: int) -> _date:
    """Soonest STRICTLY future date with ``weekday`` (Mon=0).

    Mirrors workflows.scheduling.resolve_relative_date's convention, so a seeded clash lands
    exactly where "next <weekday>" resolves to — including the roll-to-next-week when today
    already IS that weekday.
    """
    return ref + timedelta(days=(weekday - ref.weekday()) % 7 or 7)


def busy_slots_for(today: _date) -> list[BusySlot]:
    """:data:`BUSY_SLOTS` shifted by whole weeks so the clash sits on the coming Tuesday.

    The shift is a multiple of 7 days, so every slot keeps its weekday and relative spacing.
    """
    delta = (_next_weekday(today, _ANCHOR_TUESDAY.weekday()) - _ANCHOR_TUESDAY).days
    return [BusySlot(s.user_id,
                     (_date.fromisoformat(s.date) + timedelta(days=delta)).isoformat(),
                     s.start, s.end, s.title)
            for s in BUSY_SLOTS]

# Per-department budget allocations for the current period (£). Remaining = total − sum of
# approved expense amounts for the department (computed from the submissions store).
BUDGETS: dict[str, float] = {
    "Engineering": 5000.0,
    "Product":     3000.0,
    "Finance":     2000.0,
    "People":      2000.0,
    "IT":          2000.0,
    "Operations":  2000.0,
}

# Per-person allocations. Used amounts are derived from approved records in the store.
QUOTAS: dict[str, dict[str, float]] = {
    p.user_id: {"expense_annual": 3000.0} for p in PEOPLE
}

# Pre-approved expense claims → seed the submissions store (consume budget/quota and give
# duplicate detection something to catch). The bob/CityCab/2026-06-22/24.0 record is a
# deliberate duplicate-test target.
SEED_EXPENSES: list[dict[str, Any]] = [
    {"employee_name": "Bob Rivera",  "vendor": "TechMart Ltd", "date": "2026-06-15",
     "amount": 320.0, "currency": "GBP", "category": "software",
     "business_purpose": "Team license renewal"},
    {"employee_name": "Alice Tan",   "vendor": "CityCab",      "date": "2026-06-20",
     "amount": 18.5,  "currency": "GBP", "category": "travel",
     "business_purpose": "Client site visit"},
    {"employee_name": "Bob Rivera",  "vendor": "CityCab",      "date": "2026-06-22",
     "amount": 24.0,  "currency": "GBP", "category": "travel",
     "business_purpose": "Airport transfer"},
]

# Seed inbox threads for the demo — multi-party, varied (triage runs on demand → actions
# empty until then). The three LONG threads (20–32 turns, topic drift, distractor lines,
# the action buried early/middle/late) exercise key-information extraction; the three
# SHORT ones (leave email, ambiguous social → dismiss, FYI → archive) keep the mix real.
_Q3_THREAD = "\n".join([
    "Alice: Morning all, hope everyone had a good weekend ⛅",
    "Bob: Morning! Spent most of it fixing my bike, but I'll count that as rest.",
    "Dana: The coffee machine on floor 2 is broken AGAIN, just so everyone knows.",
    "Evan: Third time this month. I'll log a facilities ticket later.",
    "Chen: Morning! Month-end close went smoothly by the way, numbers are all in.",
    "Alice: Nice work Chen. Did anyone see the client email about the pilot extension?",
    "Bob: Saw it — good news. They want the extension scoped by end of July.",
    "Evan: Heads up, VPN maintenance this weekend, expect a short blip Saturday night.",
    "Bob: Thanks Evan.",
    "Alice: OK, main thing from me — we need the Q3 budget reviewed before the board "
    "presentation.",
    "Alice: Can we get a meeting on the books next Tuesday at 14:00? Bob and Chen, "
    "you're the key people.",
    "Bob: Works for me.",
    "Chen: Fine by me, I'll bring the latest figures and the variance sheet.",
    "Dana: Do you need me there? I can send the headcount numbers instead.",
    "Alice: Numbers by email is fine, thanks Dana.",
    "Evan: While everyone's here — the fire drill is Thursday morning, don't be alarmed.",
    "Dana: Again? We just had one.",
    "Evan: Quarterly requirement, not my rules 😅",
    "Bob: Speaking of the budget, the cloud bill came in lower than forecast this month.",
    "Chen: Yes, I saw — about 8% under. I'll fold that into the Q3 numbers.",
    "Alice: Great. Anything else on the client pilot?",
    "Bob: I'll draft the extension scope this week and share it for comments.",
    "Dana: New starter question — do we have a desk sorted for the person joining Eng?",
    "Evan: Desk, monitor and accounts are all sorted, just waiting on the laptop.",
    "Bob: The laptop arrived this morning actually, it's in the storage room.",
    "Dana: Perfect, thanks both.",
    "Chen: One more thing — expense claims for June need to be in by Friday.",
    "Bob: Noted.",
    "Alice: Right, I think that's everything. Board minutes are on the shared drive.",
    "Dana: We really should tidy that shared drive at some point 😅",
    "Alice: Ha, one battle at a time. Thanks all!",
])

_ONBOARDING_THREAD = "\n".join([
    "Dana: Morning! Reminder that our new engineer starts next Monday.",
    "Evan: Accounts are provisioned, laptop is imaged and ready.",
    "Dana: You two are fast, thank you.",
    "Bob: We should do a welcome sync with them to walk through the codebase — maybe "
    "Monday at 11:00?",
    "Dana: 11:00 works, I'll block it in the onboarding plan.",
    "Bob: I'll prepare a quick architecture tour, nothing too heavy for day one.",
    "Evan: Do they need access to the staging environment from day one?",
    "Bob: Read access is enough for the first week.",
    "Evan: Noted, I'll set it up that way.",
    "Dana: Buddy system — Bob, are you okay being their buddy for the first month?",
    "Bob: Happy to.",
    "Dana: Great. HR paperwork is all done, just the equipment form left.",
    "Evan: The equipment form is in their onboarding pack already.",
    "Chen: Welcome pack question — do we still do the company mug? 😄",
    "Dana: We do, it's already on their desk.",
    "Evan: The mug is the real onboarding.",
    "Bob: 😂",
    "Dana: One more thing — their first payroll cut-off is the 25th, I'll handle it.",
    "Chen: Noted on my side too.",
    "Dana: That's everything from me. Thanks all!",
])

_DEBRIEF_THREAD = "\n".join([
    "Chen: The client meeting yesterday went really well, they loved the live demo.",
    "Alice: Fantastic. Which parts landed best?",
    "Chen: The approval-flow walkthrough — they said it maps exactly to their process.",
    "Bob: Great to hear. Any concerns raised?",
    "Chen: Some questions about data residency, nothing blocking.",
    "Dana: Well done everyone 👏",
    "Alice: Did pricing come up at all?",
    "Chen: Briefly. They asked about volume discounts, I said we'd follow up in the "
    "proposal.",
    "Bob: Sensible.",
    "Dana: Unrelated — someone left a laptop in room Vega, it's at reception now.",
    "Evan: That's probably the loaner from last week's workshop, I'll grab it.",
    "Alice: Back to the client — what's our timeline for the follow-up proposal?",
    "Chen: They want something in about two weeks, before their steering meeting.",
    "Bob: Tight but doable if we start this week.",
    "Alice: Agreed. We'll need input from finance on the pricing tiers.",
    "Chen: I can pull last quarter's usage stats as a baseline.",
    "Evan: If you need the demo environment kept alive, let me know — it's due for "
    "teardown Friday.",
    "Alice: Keep it up another two weeks please, we may need it for the proposal review.",
    "Evan: Done ✅",
    "Dana: The canteen has decent options today for once, if anyone hasn't had lunch.",
    "Bob: High praise.",
    "Alice: OK — to move the proposal forward, let's sync on Thursday at 15:00 to "
    "divide up the sections.",
    "Alice: Bob, can you join? Your architecture bits will be a big part of it.",
    "Bob: Sure, Thursday 15:00 works.",
    "Chen: Works for me too, I'll bring the usage stats.",
    "Dana: I'll skip unless you need HR input, just send me the notes.",
    "Alice: Will do, thanks Dana.",
    "Alice: Perfect. Nice work again on yesterday, team.",
])

# `received_at` = when the thread arrived. Relative dates inside a thread ("next Tuesday")
# mean *relative to when it was written*, so routing resolves against this, not the
# reader's clock (a thread read a week late must not shift its meeting a week). All are
# at or before the demo NOW (2026-06-30T09:00); the Q3 thread sits on 06-30 so its
# "next Tuesday" still lands on 2026-07-07 and clashes with Bob's seeded 14:00 slot.
SEED_THREADS: list[dict[str, Any]] = [
    {"source": "chat", "subject": "Q3 budget review", "received_at": "2026-06-30T08:15",
     "raw_text": _Q3_THREAD,                      # action buried mid-thread + distractors
     "summary": "", "detected_actions": []},
    {"source": "chat", "subject": "New hire onboarding", "received_at": "2026-06-29T09:05",
     "raw_text": _ONBOARDING_THREAD,              # action near the top
     "summary": "", "detected_actions": []},
    {"source": "email", "subject": "Annual leave request", "received_at": "2026-06-29T16:40",
     "raw_text": ("Bob: Hi HR, I'd like to book annual leave from 3 August to 5 August 2026 "
                  "for a family trip. Let me know if you need anything else. Thanks."),
     "summary": "", "detected_actions": []},
    {"source": "chat", "subject": "Client visit debrief", "received_at": "2026-06-29T17:20",
     "raw_text": _DEBRIEF_THREAD,                 # action buried late in the thread
     "summary": "", "detected_actions": []},
    {"source": "chat", "subject": "Catch up soon?", "received_at": "2026-06-28T12:00",
     "raw_text": ("Dana: Hey, it's been ages! We should really grab a coffee sometime soon.\n"
                  "Alice: Totally, let's do it! It's been way too long."),
     "summary": "", "detected_actions": []},
    {"source": "email", "subject": "Printer fixed", "received_at": "2026-06-30T07:50",
     "raw_text": ("Evan: FYI the printer on floor 2 is back up and running — turned out to "
                  "be a driver issue. No action needed, just letting everyone know."),
     "summary": "", "detected_actions": []},
    {"source": "email", "subject": "Train receipt reimbursement",
     "received_at": "2026-06-30T08:35",
     "raw_text": ("Alice: Please reimburse my £48 CityRail fare from 29 June 2026. "
                  "It was travel to the Northwind client workshop; receipt attached."),
     "messages": [{
         "message_id": "msg-expense-001",
         "sender": "Alice",
         "body": ("Please reimburse my £48 CityRail fare from 29 June 2026. "
                  "It was travel to the Northwind client workshop; receipt attached."),
         "created_at": "2026-06-30T08:35",
         "attachment_ids": ["att-train-001"],
     }],
     "attachments": [{
         "attachment_id": "att-train-001",
         "filename": "cityrail-receipt.png",
         "mime_type": "image/png",
         "byte_size": 48321,
         "evidence_type": "receipt",
     }],
     "summary": "", "detected_actions": [], "memo_items": []},
    # A fully specified plan that is called off at the very end. The model tends to anchor
    # on the concrete plan and still propose the booking; `check_retraction` soft-flags it
    # at the gate. Seeded so the behaviour is demonstrable, not just measurable.
    {"source": "chat", "subject": "Vendor contract sync", "received_at": "2026-06-30T09:40",
     "raw_text": ("Alice: Booking us in for the vendor contract next Thursday at 11:30.\n"
                  "Alice: Room Lyra is free, should take about an hour.\n"
                  "Alice: Chen and Dana, please make sure you can attend.\n"
                  "Bob: Works for me.\n"
                  "Dana: The coffee machine on floor 2 is broken again, sigh.\n"
                  "Evan: Deploy went out clean last night, no alerts so far.\n"
                  "Chen: Did anyone catch the match last night? Cracking game.\n"
                  "Bob: Guest wifi password rotated, it's on the noticeboard.\n"
                  "Dana: Someone left a laptop in room Vega, it's at reception now.\n"
                  "Evan: Reminder there's VPN maintenance this weekend, expect a blip.\n"
                  "Chen: The canteen actually has decent options today for once.\n"
                  "Bob: Great work on the demo yesterday everyone, client seemed happy.\n"
                  "Alice: Actually, scrap that — legal came back already, so the meeting "
                  "is cancelled. I'll send a summary by email instead."),
     "summary": "", "detected_actions": []},
]


# Users who can approve expense claims (WF3 two-role model). Everyone else submits as an
# employee. Segregation of duties: an approver may not approve their own submission.
EXPENSE_APPROVERS = {"chen", "fiona"}   # Finance Analyst + Operations Director


def is_expense_approver(user_id: str) -> bool:
    return user_id in EXPENSE_APPROVERS


def find_person(name_or_id: str) -> Optional[Person]:
    """Case-insensitive match on user_id, full name, or first name."""
    q = name_or_id.strip().lower()
    for p in PEOPLE:
        if q in (p.user_id, p.name.lower(), p.name.split()[0].lower()):
            return p
    return None


def get_budget_total(department: str) -> Optional[float]:
    """The department's budget allocation, or None if the department is unknown."""
    return BUDGETS.get(department)


def get_quota(user_id: str) -> Optional[dict[str, float]]:
    """The person's expense allocation, or None if unknown."""
    return QUOTAS.get(user_id)


def seed_from_org(store: Any, *, today: Optional[_date] = None) -> None:
    """Populate a RecordStore with the initial world state. Idempotent after ``reset()``.

    ``store`` is any object with ``create(store, record_type, data, status)`` — kept
    duck-typed so this fixture module doesn't depend on the store implementation.

    ``today`` shifts the seeded calendar onto the coming week (see :func:`busy_slots_for`) so
    the live app's relative dates still land on a real clash. Omit it — as every eval and
    test does — to get the fixed dates the evaluation gold is pinned to.
    """
    for slot in (busy_slots_for(today) if today is not None else BUSY_SLOTS):
        store.create("events", "event", {
            "title": slot.title, "participants": [slot.user_id],
            "date": slot.date, "start": slot.start, "end": slot.end,
        }, status="booked")
    for exp in SEED_EXPENSES:
        # seeds carry the same frozen conversion a live submit would attach, so seeded and
        # submitted records are shaped identically for reporting (backend/money.py)
        store.create("submissions", "expense_claim",
                     {**exp, **_fx_convert(exp["amount"], exp["currency"])},
                     status="approved")
    for thr in SEED_THREADS:
        store.create("threads", "thread", thr, status="unread")
