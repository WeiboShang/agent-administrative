"""Tests for the M2 task-success harness (offline — perfect-extractor stubs, no LLM)."""
import inspect

from backend.evals import task_success
from backend.evals.receipt_data import make_receipt_case
from backend.evals.receipt_score import gold_as_extraction
from backend.evals.scheduling_data import make_dataset
from backend.evals.scheduling_score import gold_as_extraction as sched_gold
from backend.evals.task_success import evaluate_expense_task, evaluate_scheduling_task


# ── the reproducibility invariant (docs/workflow_design.md) ──

def test_harness_injects_a_mock_calendar_and_never_uses_the_factory():
    """This harness DOES call execute_scheduling (the booking path), so — unlike the WF2
    scorer — it cannot rely on simply never getting there. It must pass a mock backend
    explicitly, or a live CALENDAR_BACKEND=google would write eval data to a real calendar."""
    src = inspect.getsource(task_success)
    assert "get_calendar_backend" not in src, "must not let the env var choose the backend"
    assert "calendar_backend=mock_calendar" in src, "must inject the mock explicitly"


def test_booking_with_an_injected_mock_does_not_touch_the_configured_backend(monkeypatch):
    """Even with the Google demo switched on, an injected backend wins."""
    from backend import config
    from backend.backends.records import RecordStore
    from backend.fixtures import org
    from backend.workflows.scheduling import execute_scheduling

    monkeypatch.setattr(config, "CALENDAR_BACKEND", "google")   # the risky configuration

    calls = []

    class Spy:
        def book(self, event, participant_ids):
            calls.append(event)
            return {"status": "skipped"}

    s = RecordStore(":memory:")
    org.seed_from_org(s)
    out = execute_scheduling(
        {"title": "T", "date": "2026-07-09", "time": "10:00", "duration_minutes": 30,
         "participants": ["bob"]},
        s, decision="approve", calendar_backend=Spy())
    assert out["status"] == "booked"
    assert len(calls) == 1        # the spy was used; the google factory was never consulted


# ── WF2 ──

def test_perfect_extractor_books_the_right_meeting():
    rep = evaluate_scheduling_task(make_dataset(n_per_tier=2), sched_gold)
    assert rep["task_success"] == 1.0
    assert rep["harmful_record_rate"] == 0.0
    # out_of_scope gold expects no record at all
    assert rep["by_tier"]["out_of_scope"]["correct_abstain"] == 2
    # `missing` (no gold time) and `ambiguous` (no gold date) must NOT be booked — the gate
    # declining is the right answer, so they count as correct abstention, not task failure
    assert rep["by_tier"]["missing"]["correct_abstain"] == 2
    assert rep["by_tier"]["ambiguous"]["correct_abstain"] == 2


def test_a_shifted_date_is_a_wrong_record_not_a_blocked_one():
    """The distinction M2 exists to make: the system acted, and acted wrongly."""
    cases = [c for c in make_dataset(n_per_tier=2) if c.meta["tier"] == "clean"]

    def wrong_date(case):
        x = dict(sched_gold(case))
        x["date"] = "2026-12-25"                 # resolvable, but not what was asked
        return x

    rep = evaluate_scheduling_task(cases, wrong_date)
    assert rep["by_tier"]["clean"]["wrong"] == len(cases)
    assert rep["task_success"] == 0.0
    assert rep["harmful_record_rate"] == 1.0


def test_dropping_the_time_blocks_instead_of_booking():
    """A missing required slot must fail SAFE — no record, not a wrong one."""
    cases = [c for c in make_dataset(n_per_tier=2) if c.meta["tier"] == "clean"]

    def no_time(case):
        x = dict(sched_gold(case))
        x["time"] = None
        return x

    rep = evaluate_scheduling_task(cases, no_time)
    assert rep["by_tier"]["clean"]["blocked"] == len(cases)
    assert rep["harmful_record_rate"] == 0.0     # blocked is a safe failure


def test_an_unresolvable_participant_fails_the_task_despite_a_clean_read():
    """M1 would score this extraction fine; M2 is what notices nobody real was invited."""
    cases = [c for c in make_dataset(n_per_tier=1) if c.meta["tier"] == "clean"]

    def ghost(case):
        x = dict(sched_gold(case))
        x["participants"] = ["Nobody Here"]
        return x

    rep = evaluate_scheduling_task(cases, ghost)
    assert rep["task_success"] == 0.0


# ── WF3 ──

def _entries(tier: str, n: int) -> list[dict]:
    out = []
    for i in range(n):
        _img, gold, meta = make_receipt_case(tier, seed=i)
        out.append({"image": f"{tier}_{i}.png", "gold": gold, "meta": meta})
    return out


def vision_gold(entry: dict) -> dict:
    """Perfect extractor in the *vision* output shape.

    `receipt_score.gold_as_extraction` emits `category` (the form field), but the mapper
    under test reads `category_guess` (what the model actually returns), so that stub would
    leave every claim missing its category and block the submit. M2 runs the real mapper, so
    the stub has to speak the real vision schema.
    """
    x = dict(gold_as_extraction(entry))
    if "category" in x:
        x["category_guess"] = x.pop("category")
    return x


def test_perfect_extractor_files_the_right_claim():
    rep = evaluate_expense_task(_entries("clean", 3), vision_gold)
    assert rep["task_success"] == 1.0
    assert rep["harmful_record_rate"] == 0.0


def test_a_non_receipt_must_not_produce_a_claim():
    rep = evaluate_expense_task(_entries("non_receipt", 2), vision_gold)
    assert rep["by_tier"]["non_receipt"]["correct_abstain"] == 2
    assert rep["harmful_record_rate"] == 0.0


def test_a_misread_amount_files_a_wrong_claim():
    entries = _entries("clean", 2)

    def inflated(entry):
        x = dict(vision_gold(entry))
        x["amount"] = float(x["amount"]) * 10        # the CORD separator failure mode
        return x

    rep = evaluate_expense_task(entries, inflated)
    assert rep["by_tier"]["clean"]["wrong"] == 2
    assert rep["harmful_record_rate"] == 1.0


def test_an_accent_transliteration_is_not_a_wrong_claim():
    """"Cafe Aurora" for "Café Aurora" is a correct read (results.md §2.4) — M2 must use the
    same normalisation as M1, or it would report a wrong record where M1 reports a hit."""
    entries = [e for e in _entries("over_limit", 2)]      # vendor is always "Café Aurora"

    def transliterated(entry):
        x = dict(vision_gold(entry))
        x["vendor"] = "Cafe Aurora"
        return x

    rep = evaluate_expense_task(entries, transliterated)
    assert rep["by_tier"]["over_limit"]["success"] == 2
    assert rep["harmful_record_rate"] == 0.0
