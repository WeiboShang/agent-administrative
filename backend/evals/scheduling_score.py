"""Scoring + harness for WF2 against gold (docs/evaluation.md §3, §8).

``evaluate`` runs each case's extraction through the **stateful** validator
(``validate_scheduling`` against a fresh seeded RecordStore — the same code path the API
serves) and scores the result against the gold, aggregated **per difficulty tier**. The
``stateful_conflict`` tier pre-books an overlapping meeting into the store first, so the
eval also exercises "today's approval affects tomorrow's validation".

The extraction step is a pluggable ``extract_fn(case) -> dict``:

- default ``gold_as_extraction`` (offline, no LLM) feeds the validator a perfect reading of
  the message, so it measures the **deterministic half** — date resolution, conflict
  detection, missing-field detection, abstention — verifiable without a key. Slot metrics
  (time/participants) are trivially 1.0 under it.
- pass the LLM-backed extractor (``backend/evals/run_scheduling_eval.py``) to also measure
  **slot-extraction accuracy** (the LLM reading ``case.input_text``) for the full RQ2 run.
"""
from collections import defaultdict
from datetime import datetime
from typing import Callable

from ..backends.mock import MockDirectoryBackend
from ..backends.records import RecordStore
from ..fixtures import org
from ..workflows.scheduling import add_minutes, validate_scheduling
from .scheduling_data import TIERS, Case

ExtractFn = Callable[[Case], dict]

_directory = MockDirectoryBackend()

_COLUMNS = [
    ("date_correct", "date"),
    ("time_correct", "time"),
    ("participants_correct", "participants"),
    ("missing_detected", "missing"),
    ("conflict_correct", "conflict"),
    ("correct_abstain", "abstain"),
]


def gold_as_extraction(case: Case) -> dict:
    """The raw extraction an ideal LLM would emit: the date *as the text stated it*
    (``meta.date_phrase``), participant names (not ids). For out-of-scope messages an ideal
    agent extracts no meeting. Reads the gold — used to measure the deterministic half."""
    gold, meta = case.gold, case.meta
    if gold["intent"] == "none":
        return {"participants": [], "date": None, "time": None}
    names = [p.name for p in (_directory.lookup(uid) for uid in gold["participants"]) if p]
    return {
        "title": gold["title"],
        "participants": names,
        "date": meta.get("date_phrase"),
        "time": gold["time"],
        "duration_minutes": gold["duration_minutes"],
        "mode": gold["mode"],
    }


def _expected_conflict(case: Case):
    """Oracle: should the validator flag a participant conflict? ``None`` = not checkable.

    True when the tier pre-books an overlapping meeting (``meta.expect_conflict``) or when
    a gold participant has a seeded busy slot overlapping the gold window.
    """
    gold = case.gold
    if case.meta.get("expect_conflict"):
        return True
    if not gold["time"] or not gold["date"]:
        return None
    end = add_minutes(gold["time"], gold["duration_minutes"] or 30)
    for uid in gold["participants"]:
        for b in org.BUSY_SLOTS:
            if b.user_id == uid and b.date == gold["date"] and gold["time"] < b.end and b.start < end:
                return True
    return False


def score_case(case: Case, event: dict, missing: list[str], flags: list) -> dict:
    """Per-case metric flags (docs/evaluation.md §3). A metric is only included when it is
    meaningful for that case, so aggregation averages over the right denominator."""
    gold = case.gold
    row: dict = {"tier": case.meta["tier"]}

    if gold["intent"] == "none":
        # Abstention: an ideal agent schedules nothing (docs/evaluation.md §5).
        row["correct_abstain"] = event.get("date") is None and not event.get("participants")
        return row

    row["date_correct"] = event.get("date") == gold["date"]
    row["participants_correct"] = set(event.get("participants") or []) == set(gold["participants"])
    if gold["time"] is not None:
        row["time_correct"] = event.get("start") == gold["time"]

    expected_missing = case.meta.get("missing")
    if expected_missing is not None:
        row["missing_detected"] = all(f in missing for f in expected_missing)

    expected_conflict = _expected_conflict(case)
    if expected_conflict is not None:
        has_conflict = any(f.rule == "conflict" for f in flags)
        row["conflict_correct"] = has_conflict == expected_conflict

    return row


def aggregate(rows: list[dict]) -> dict:
    """Group rows by tier and average each boolean metric (per-tier reporting, §8)."""
    by_tier: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_tier[r["tier"]].append(r)
    report: dict = {}
    for tier, rs in by_tier.items():
        keys = {k for r in rs for k in r if k != "tier"}
        metrics = {k: round(sum(r[k] for r in rs if k in r) / sum(k in r for r in rs), 3)
                   for k in sorted(keys)}
        metrics["n"] = len(rs)
        report[tier] = metrics
    return report


def evaluate(cases: list[Case], extract_fn: ExtractFn = gold_as_extraction) -> dict:
    """Run the (extract → validate-stateful → score) loop; return the per-tier report.

    Each case gets a **fresh seeded store** (isolation: one case's pre-booking can't leak
    into another's conflict oracle), mirroring the API's reproducible world.
    """
    rows: list[dict] = []
    for case in cases:
        store = RecordStore(":memory:")
        org.seed_from_org(store)
        pb = case.meta.get("pre_book")
        if pb:
            store.create("events", "event", pb, status="booked")
        extraction = extract_fn(case)
        now = datetime.fromisoformat(case.meta["now"])
        event, missing, flags = validate_scheduling(extraction, store, now=now)
        rows.append(score_case(case, event, missing, flags))
    return aggregate(rows)


def format_report(report: dict) -> str:
    header = "tier                 n   " + "  ".join(f"{h:>12}" for _, h in _COLUMNS)
    lines = [header]
    for tier in TIERS:
        m = report.get(tier, {})
        cells = "  ".join(f"{m.get(k, ''):>12}" for k, _ in _COLUMNS)
        lines.append(f"{tier:<19} {m.get('n', 0):>3}   {cells}")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    from .scheduling_data import make_dataset

    report = evaluate(make_dataset(n_per_tier=20))
    print("WF2 deterministic eval (offline, gold-as-extraction, stateful validator):\n")
    print(format_report(report))
