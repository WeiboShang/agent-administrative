"""Tests for the extended org fixture (offline — no LLM)."""
from backend.fixtures import org


def test_people_have_departments():
    for p in org.PEOPLE:
        assert p.department, f"{p.user_id} missing department"
    assert org.find_person("bob").department == "Engineering"


def test_every_department_has_a_budget():
    depts = {p.department for p in org.PEOPLE}
    assert depts <= set(org.BUDGETS)          # every dept is budgeted
    assert org.get_budget_total("Engineering") == 5000.0
    assert org.get_budget_total("Nowhere") is None


def test_every_person_has_a_quota():
    for p in org.PEOPLE:
        q = org.get_quota(p.user_id)
        assert q is not None
        assert q["expense_annual"] > 0
    assert org.get_quota("ghost") is None


def test_seed_expenses_include_a_duplicate_target():
    # the bob/CityCab/2026-06-22/24.0 record is the deliberate duplicate-test target
    match = [e for e in org.SEED_EXPENSES
             if e["employee_name"] == "Bob Rivera" and e["vendor"] == "CityCab"
             and e["date"] == "2026-06-22" and e["amount"] == 24.0]
    assert len(match) == 1


def test_seed_expenses_match_expense_schema_keys():
    from backend.workflows.forms.registry import FORM_SCHEMAS
    required = set(FORM_SCHEMAS["expense_claim"].required)
    for e in org.SEED_EXPENSES:
        assert required <= set(e), f"seed expense missing required keys: {required - set(e)}"


# ── today-relative demo seeding (live workspace) vs fixed slots (evaluation) ──

def test_busy_slots_constant_stays_pinned_to_the_eval_epoch():
    """evals/scheduling_data.py generates gold from GEN_NOW=2026-06-30 and
    scheduling_score compares it against these slots — they must never float."""
    assert [s.date for s in org.BUSY_SLOTS] == ["2026-07-07", "2026-07-07", "2026-07-08"]


def test_busy_slots_for_puts_the_clash_on_the_coming_tuesday():
    from datetime import date
    # a Friday → the coming Tuesday is the 28th
    slots = org.busy_slots_for(date(2026, 7, 24))
    bob = [s for s in slots if s.user_id == "bob"][0]
    assert bob.date == "2026-07-28" and bob.start == "14:00"


def test_busy_slots_for_rolls_forward_when_today_is_that_weekday():
    """Matches resolve_relative_date: on a Tuesday, 'next Tuesday' is a week away."""
    from datetime import date
    slots = org.busy_slots_for(date(2026, 7, 28))          # itself a Tuesday
    assert [s for s in slots if s.user_id == "bob"][0].date == "2026-08-04"


def test_busy_slots_for_preserves_weekdays_and_spacing():
    """The shift is a whole number of weeks, so the world keeps its shape."""
    from datetime import date, datetime
    for ref in (date(2026, 7, 24), date(2026, 9, 1), date(2027, 1, 15)):
        for fixed, moved in zip(org.BUSY_SLOTS, org.busy_slots_for(ref)):
            f = datetime.fromisoformat(fixed.date)
            m = datetime.fromisoformat(moved.date)
            assert f.weekday() == m.weekday()
            assert (m - f).days % 7 == 0
            assert m.date() > ref          # every seeded meeting is in the future


def test_seed_from_org_defaults_to_the_fixed_dates():
    """Every eval and test call omits `today`, so they keep reproducible dates."""
    from backend.backends.records import RecordStore
    s = RecordStore(":memory:")
    org.seed_from_org(s)
    assert {r.data["date"] for r in s.list("events")} == {"2026-07-07", "2026-07-08"}
