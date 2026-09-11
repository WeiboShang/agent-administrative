"""Additional synthetic activity for the persistent demo workspace only.

These records make WF2 availability ranking and WF3 budget utilisation visible in the
live UI. Evaluation continues to call ``org.seed_from_org`` alone, so its pinned world
and published gold data remain unchanged.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .. import money
from . import org

DEMO_SEED_VERSION = "live-activity-v1"

_MEETINGS = (
    ("product-standup", 0, "09:00", "09:30", "Product delivery stand-up", "alice",
     ("alice", "bob"), "Lyra"),
    ("engineering-plan", 0, "10:00", "11:00", "Engineering capacity planning", "bob",
     ("bob", "evan"), "Orion"),
    ("finance-forecast", 0, "14:00", "15:00", "Finance forecast review", "chen",
     ("chen", "fiona"), "Orion"),
    ("hiring-sync", 0, "15:00", "15:30", "Hiring pipeline sync", "dana",
     ("dana", "bob"), "Vega"),
    ("it-operations", 1, "09:00", "10:00", "IT operations review", "evan",
     ("evan", "fiona"), "Orion"),
    ("customer-update", 1, "10:30", "11:00", "Customer programme update", "alice",
     ("alice", "fiona"), "Vega"),
    ("people-training", 1, "14:00", "15:00", "Manager training workshop", "dana",
     ("dana", "evan"), "Lyra"),
    ("quarterly-plan", 2, "09:30", "10:30", "Quarterly operating plan", "alice",
     ("alice", "bob", "chen", "fiona"), "Orion"),
    ("security-review", 2, "13:30", "14:00", "Security controls review", "evan",
     ("bob", "evan"), "Vega"),
)

_EXPENSES = (
    ("eng-cloud", "Bob Rivera", "CloudForge", 540.00, "GBP", "software",
     "Cloud test environment renewal", 18),
    ("product-research", "Alice Tan", "NorthRail", 210.00, "GBP", "travel",
     "Customer research visit", 16),
    ("product-design", "Alice Tan", "DesignHub", 180.00, "GBP", "software",
     "Design collaboration subscription", 13),
    ("finance-data", "Chen Wei", "FinData Labs", 420.00, "GBP", "software",
     "Financial market data licence", 15),
    ("finance-training", "Chen Wei", "LedgerWorks", 175.00, "GBP", "training",
     "Accounting standards workshop", 11),
    ("people-learning", "Dana Okoro", "LearnWell", 360.00, "GBP", "training",
     "Manager development programme", 14),
    ("people-supplies", "Dana Okoro", "OfficeSource", 145.00, "GBP", "supplies",
     "New starter welcome materials", 9),
    ("it-security", "Evan Schmidt", "SecureStack", 620.00, "GBP", "software",
     "Endpoint security renewal", 12),
    ("it-hardware", "Evan Schmidt", "CableWorks", 135.00, "GBP", "supplies",
     "Network installation supplies", 7),
    ("ops-hotel", "Fiona Reyes", "NorthStar Hotels", 480.00, "GBP", "accommodation",
     "Regional operations workshop", 10),
    ("ops-travel", "Fiona Reyes", "CityRail", 92.00, "GBP", "travel",
     "Supplier governance meeting", 6),
)


def _next_tuesday(today: date) -> date:
    return today + timedelta(days=(1 - today.weekday()) % 7 or 7)


def seed_live_demo_activity(store: Any, *, today: date) -> dict[str, int]:
    """Idempotently add richer live-only demo records to ``store``."""
    existing = {
        record.data.get("demo_seed_id")
        for store_name in ("events", "submissions")
        for record in store.list(store_name)
        if record.data.get("demo_seed_id")
    }
    created = {"events": 0, "submissions": 0}
    anchor = _next_tuesday(today)

    for seed_id, offset, start, end, title, organizer, participants, location in _MEETINGS:
        key = f"{DEMO_SEED_VERSION}:{seed_id}"
        if key in existing:
            continue
        details = [
            {"name": org.find_person(user_id).name, "resolved": True}
            for user_id in participants
        ]
        store.create("events", "event", {
            "title": title,
            "organizer": organizer,
            "participants": list(participants),
            "participant_details": details,
            "date": (anchor + timedelta(days=offset)).isoformat(),
            "start": start,
            "end": end,
            "duration_minutes": (
                int(end[:2]) * 60 + int(end[3:])
                - int(start[:2]) * 60 - int(start[3:])
            ),
            "location": location,
            "mode": "in_person",
            "agenda": "Synthetic demo calendar activity",
            "entry_mode": "demo_seed",
            "operation": "CREATE",
            "version": 1,
            "demo_seed_id": key,
        }, status="booked")
        created["events"] += 1

    for seed_id, employee, vendor, amount, currency, category, purpose, days_ago in _EXPENSES:
        key = f"{DEMO_SEED_VERSION}:{seed_id}"
        if key in existing:
            continue
        person = org.find_person(employee)
        claim_date = today - timedelta(days=days_ago)
        reviewer = "fiona" if person and person.user_id == "chen" else "chen"
        store.create("submissions", "expense_claim", {
            "employee_name": employee,
            "department": person.department if person else None,
            "vendor": vendor,
            "date": claim_date.isoformat(),
            "amount": amount,
            "currency": currency,
            "category": category,
            "business_purpose": purpose,
            "payment_method": "card",
            "submitted_by": person.user_id if person else None,
            "submitted_at": f"{claim_date.isoformat()}T09:00:00+00:00",
            "reviewed_by": reviewer,
            "decided_at": f"{(claim_date + timedelta(days=1)).isoformat()}T15:00:00+00:00",
            "decision_reason": "Approved synthetic demo expense",
            "policy_flags": [],
            "changed_fields": [],
            "demo_seed_id": key,
            **money.convert(amount, currency),
        }, status="approved")
        created["submissions"] += 1

    return created
