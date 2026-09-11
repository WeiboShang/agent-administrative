from datetime import date

from backend.backends.records import RecordStore
from backend.fixtures import org
from backend.fixtures.live_demo import seed_live_demo_activity
from backend.workflows import policy


def test_live_demo_activity_is_rich_idempotent_and_separate_from_base_seed():
    store = RecordStore(":memory:")
    org.seed_from_org(store)
    assert len(store.list("events")) == 3
    assert len(store.list("submissions", record_type="expense_claim")) == 3

    created = seed_live_demo_activity(store, today=date(2026, 8, 11))
    assert created == {"events": 9, "submissions": 11}
    assert len(store.list("events", status="booked")) == 12
    assert len(store.list("submissions", record_type="expense_claim")) == 14

    departments_with_spend = {
        person.department
        for person in org.PEOPLE
        if policy.budget_remaining(person.department, store) < org.BUDGETS[person.department]
    }
    assert departments_with_spend == set(org.BUDGETS)
    assert seed_live_demo_activity(store, today=date(2026, 8, 11)) == {
        "events": 0, "submissions": 0,
    }
