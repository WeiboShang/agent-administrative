"""M2 — task success: did the right RECORD get created, end to end?

M1 scores what the model *read*. M2 scores what the system *did*: the draft is pushed through
the deterministic layer (date resolution, participant lookup, window arithmetic) and the
approval gate, and the record that actually lands in the store is compared to gold. The two
can disagree in both directions, which is the point:

- perfect extraction, failed task — a participant name that resolves to nobody, or a gate
  that blocks on a missing slot;
- imperfect extraction, successful task — the deterministic layer repairs what the model
  read loosely (a relative date, a first name).

**Four outcomes, not a rate**, because "no record" and "wrong record" are not the same
failure. A blocked draft is the system declining to act; a wrong record is a wrong meeting on
someone's calendar. Collapsing them into one number would hide exactly the distinction this
project is about.

    success          record created, task-defining fields match gold
    wrong            record created, fields do NOT match gold      ← the harmful outcome
    blocked          gold expected a record, the gate created none ← the safe failure
    correct_abstain  gold expected nothing, nothing was created
    spurious         gold expected nothing, a record was created   ← the harmful outcome

Auto-approve at the gate: M2 measures the system *unassisted*, so the proposal is executed
as-is with no human edits. What the human adds on top is M4's question, not this one.

**Calendar safety.** The booking path is the only place WF2 can reach a real calendar, so
this harness injects ``MockCalendarBackend()`` explicitly rather than letting the
``config.CALENDAR_BACKEND`` factory decide. Evaluation therefore stays on the mock path
(CLAUDE.md §3.4) even when the interactive app is pointed at the Google demo — enforced by
construction, and asserted in test_task_success.py.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Optional

from ..agent.vision_extract import receipt_to_fields
from ..backends.calendar_backend import MockCalendarBackend
from ..backends.records import RecordStore
from ..fixtures import org
from .legacy_expense import submit_expense_baseline
from ..workflows.scheduling import execute_scheduling, validate_scheduling
from .receipt_score import _norm
from .scheduling_data import Case

OUTCOMES = ("success", "wrong", "blocked", "correct_abstain", "spurious")

# The fields that decide whether the RIGHT thing was created. Deliberately not everything on
# the record: a title or agenda is prose the human is free to reword, but a meeting on the
# wrong day, at the wrong time, or with the wrong people is a different meeting.
SCHED_IDENTITY = ("date", "start", "duration_minutes")
EXPENSE_IDENTITY = ("vendor", "date", "amount", "currency")


def _tally(rows: list[dict]) -> dict[str, Any]:
    """Per-tier outcome counts + the two headline rates."""
    by_tier: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_tier[r["tier"]].append(r)

    report: dict[str, Any] = {}
    for tier, rs in sorted(by_tier.items()):
        counts = {o: sum(1 for r in rs if r["outcome"] == o) for o in OUTCOMES}
        actionable = [r for r in rs if r["gold_actionable"]]
        report[tier] = {
            "n": len(rs),
            **{o: c for o, c in counts.items() if c},
            # task success among the cases that should produce a record
            "task_success": (round(sum(1 for r in actionable if r["outcome"] == "success")
                                   / len(actionable), 3) if actionable else None),
        }

    total = len(rows)
    actionable = [r for r in rows if r["gold_actionable"]]
    harmful = sum(1 for r in rows if r["outcome"] in ("wrong", "spurious"))
    return {
        "by_tier": report,
        "n": total,
        "task_success": (round(sum(1 for r in actionable if r["outcome"] == "success")
                               / len(actionable), 3) if actionable else None),
        # a record that exists but is wrong, or exists when nothing was asked for — the
        # failures an unattended pipeline would commit to the workspace
        "harmful_record_rate": round(harmful / total, 3) if total else 0.0,
    }


def _classify(gold_actionable: bool, record: Optional[dict], matches: bool) -> str:
    if not gold_actionable:
        return "correct_abstain" if record is None else "spurious"
    if record is None:
        return "blocked"
    return "success" if matches else "wrong"


# ── WF2 scheduling ───────────────────────────────────────────────────────────────────

ExtractFn = Callable[[Case], dict]


def _sched_matches(data: dict, gold: dict) -> bool:
    if data.get("date") != gold.get("date"):
        return False
    if data.get("start") != gold.get("time"):
        return False
    if data.get("duration_minutes") != gold.get("duration_minutes"):
        return False
    return sorted(data.get("participants") or []) == sorted(gold.get("participants") or [])


def evaluate_scheduling_task(cases: list[Case], extract_fn: ExtractFn) -> dict:
    """Extract → validate → book → compare the stored event to gold.

    Each case gets a fresh seeded store, so one case's booking cannot occupy a slot another
    case is judged against (the same isolation scheduling_score.evaluate uses).
    """
    mock_calendar = MockCalendarBackend()
    rows: list[dict] = []
    for case in cases:
        store = RecordStore(":memory:")
        org.seed_from_org(store)
        if (pb := case.meta.get("pre_book")):
            store.create("events", "event", pb, status="booked")
        before = {r.id for r in store.list("events")}

        now = datetime.fromisoformat(case.meta["now"])
        event, _missing, flags = validate_scheduling(extract_fn(case), store, now=now)
        execute_scheduling(
            event,
            store,
            decision="approve",
            now=now,
            calendar_backend=mock_calendar,
            override_soft_flags=bool(flags),
            override_reason="Scripted evaluator approved surfaced warnings" if flags else None,
        )

        created = [r for r in store.list("events") if r.id not in before]
        data = created[0].data if created else None
        gold = case.gold
        # "Should a record exist?" is not the same as "is there an intent?". The `missing`
        # tier's gold has no time and `ambiguous`'s has no date — for those, gold's answer is
        # *don't book, surface the gap* (data_strategy §3.3 / evaluation.md §5). Counting them
        # as task failures would score correct abstention as a miss and make M2 reward a
        # system that invents the absent slot.
        actionable = bool(gold["intent"] != "none" and gold.get("date") and gold.get("time"))
        rows.append({
            "tier": case.meta["tier"],
            "gold_actionable": actionable,
            "outcome": _classify(actionable, data,
                                 bool(data) and _sched_matches(data, gold)),
        })
    return _tally(rows)


# ── WF3 expense ──────────────────────────────────────────────────────────────────────

EntryExtractFn = Callable[[dict], dict]


def _expense_matches(data: dict, gold: dict) -> bool:
    """Field comparison must use the SAME normalisation M1 uses (`receipt_score._norm`):
    case- and accent-insensitive. A model that writes "Cafe Aurora" for "Café Aurora" has
    read the vendor correctly — results.md §2.4 records that treating that as an error once
    under-reported vendor accuracy to 0.33. Comparing M2 against M1 is only honest if a
    "correct read" means the same thing in both.
    """
    for k in EXPENSE_IDENTITY:
        got, want = data.get(k), gold.get(k)
        if isinstance(want, (int, float)) and isinstance(got, (int, float)):
            if abs(float(got) - float(want)) > 0.005:
                return False
        elif _norm(got) != _norm(want):
            return False
    return True


def evaluate_expense_task(entries: list[dict], extract_fn: EntryExtractFn) -> dict:
    """Vision extract → map to form → submit → compare the stored claim to gold.

    ``business_purpose`` is supplied because the receipt cannot: it is a required field the
    human always fills (§D), and withholding it would block every case on a missing field
    and measure the form contract rather than task success.
    """
    rows: list[dict] = []
    for entry in entries:
        store = RecordStore(":memory:")
        org.seed_from_org(store)
        before = {r.id for r in store.list("submissions")}

        fields = receipt_to_fields(extract_fn(entry), employee_name="Alice Tan",
                                   business_purpose="Business expense")
        submit_expense_baseline(fields, store, submitted_by="alice")

        created = [r for r in store.list("submissions") if r.id not in before]
        data = created[0].data if created else None
        meta, gold = entry["meta"], entry["gold"]
        actionable = meta.get("is_receipt", True)
        rows.append({
            "tier": meta["tier"],
            "gold_actionable": actionable,
            "outcome": _classify(actionable, data,
                                 bool(data) and _expense_matches(data, gold)),
        })
    return _tally(rows)


def format_report(report: dict, label: str) -> str:
    lines = [f"{label} — M2 task success",
             f"{'tier':<18}{'n':>4}  {'success':>8}  outcomes"]
    for tier, m in report["by_tier"].items():
        outs = " ".join(f"{o}={m[o]}" for o in OUTCOMES if o in m)
        ts = "—" if m["task_success"] is None else f"{m['task_success']:.2f}"
        lines.append(f"{tier:<18}{m['n']:>4}  {ts:>8}  {outs}")
    lines.append(f"\noverall task success   : {report['task_success']}")
    lines.append(f"harmful record rate    : {report['harmful_record_rate']}")
    return "\n".join(lines)
