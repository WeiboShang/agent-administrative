"""Tests for the policy / checks engine (offline — no LLM)."""
from datetime import date

from backend.backends.records import RecordStore
from backend.fixtures import org
from backend.workflows import policy


def _seeded() -> RecordStore:
    s = RecordStore(":memory:")
    org.seed_from_org(s)
    return s


# ── WF3 expense ──
def test_clean_expense_no_flags():
    s = _seeded()
    fields = {"employee_name": "Alice Tan", "vendor": "Café Aurora", "date": "2026-06-28",
              "amount": 30.0, "currency": "GBP", "category": "meals"}
    assert policy.check_expense(fields, s) == []


def test_expense_date_treats_history_as_normal_and_future_as_suspicious():
    s = _seeded()
    base = {"employee_name": "Alice Tan", "vendor": "Café Aurora",
            "amount": 30.0, "currency": "GBP", "category": "meals"}
    today = date(2026, 8, 13)

    assert "future_date" not in [
        f.rule for f in policy.check_expense({**base, "date": "2026-07-16"}, s, today=today)
    ]
    assert "future_date" not in [
        f.rule for f in policy.check_expense({**base, "date": "2026-08-13"}, s, today=today)
    ]
    future = policy.check_expense({**base, "date": "2026-08-14"}, s, today=today)
    assert any(f.rule == "future_date" and f.severity == "soft" for f in future)


def test_over_category_limit_hard():
    s = _seeded()
    fields = {"employee_name": "Alice Tan", "vendor": "Café Aurora", "date": "2026-06-28",
              "amount": 85.0, "category": "meals"}
    flags = policy.check_expense(fields, s)
    assert [f.rule for f in flags] == ["over_limit"]
    assert flags[0].severity == "hard"


def test_duplicate_hard():
    s = _seeded()
    # matches the seeded bob/CityCab/2026-06-22/24.0 approved claim
    fields = {"employee_name": "Bob Rivera", "vendor": "CityCab", "date": "2026-06-22",
              "amount": 24.0, "category": "travel"}
    flags = policy.check_expense(fields, s)
    assert any(f.rule == "duplicate" and f.severity == "hard" for f in flags)
    assert policy.has_hard(flags)


def test_duplicate_vendor_identity_ignores_accents_case_and_punctuation():
    s = RecordStore(":memory:")
    s.create("submissions", "expense_claim", {
        "employee_name": "Alice Tan", "vendor": "Café-Aurora",
        "date": "2026-06-05", "amount": 85.0, "currency": "GBP",
        "category": "meals",
    }, status="approved")
    flags = policy.check_expense({
        "employee_name": "Bob Rivera", "vendor": "CAFE AURORA",
        "date": "2026-06-05", "amount": 85.0, "currency": "GBP",
        "category": "meals",
    }, s)
    duplicate = next(flag for flag in flags if flag.rule == "duplicate")
    assert duplicate.severity == "hard"
    assert "Café-Aurora" in duplicate.message


def test_budget_exhausted_hard():
    s = _seeded()
    # Engineering total 5000, spent 344 (bob software 320 + travel 24) -> remaining 4656
    fields = {"employee_name": "Bob Rivera", "vendor": "BigCo", "date": "2026-06-29",
              "amount": 4800.0, "category": "travel"}
    flags = policy.check_expense(fields, s)
    assert any(f.rule == "budget_exhausted" and f.severity == "hard" for f in flags)


def test_quota_exhausted_hard():
    s = _seeded()
    # bob annual quota 3000, spent 344 -> remaining 2656; a 2800 claim exceeds quota
    # (still within Engineering budget, so this isolates the quota rule)
    fields = {"employee_name": "Bob Rivera", "vendor": "BigCo", "date": "2026-06-29",
              "amount": 2800.0, "category": "travel"}
    flags = policy.check_expense(fields, s)
    assert any(f.rule == "quota_exhausted" and f.severity == "hard" for f in flags)


def test_doc_mismatch_soft():
    s = _seeded()
    fields = {"employee_name": "Alice Tan", "vendor": "Café Aurora", "date": "2026-06-28",
              "amount": 52.0, "category": "meals"}
    flags = policy.check_expense(fields, s, extracted_amount=42.0)
    assert any(f.rule == "doc_mismatch" and f.severity == "soft" for f in flags)


# ── WF3 reasoning layer: arithmetic self-consistency (§L.1) ──
def _base_arith(**over):
    return {"employee_name": "Alice Tan", "vendor": "DeskSupplies Co", "date": "2026-06-28",
            "currency": "GBP", "category": "supplies", **over}   # supplies cap £200


def test_arithmetic_line_item_mismatch_soft():
    s = _seeded()
    fields = _base_arith(amount=52.0,
                         line_items=[{"desc": "a", "amount": 20.0}, {"desc": "b", "amount": 22.0}])
    flags = policy.check_expense(fields, s)
    assert any(f.rule == "arithmetic_mismatch" and f.severity == "soft" for f in flags)


def test_arithmetic_tax_inclusive_reconciles():
    s = _seeded()
    fields = _base_arith(amount=42.0,
                         line_items=[{"desc": "a", "amount": 20.0}, {"desc": "b", "amount": 22.0}])
    assert "arithmetic_mismatch" not in [f.rule for f in policy.check_expense(fields, s)]


def test_arithmetic_tax_exclusive_reconciles():
    s = _seeded()
    # line items 40 + tax 8 == total 48 → consistent
    fields = _base_arith(amount=48.0, tax=8.0, line_items=[{"desc": "a", "amount": 40.0}])
    assert "arithmetic_mismatch" not in [f.rule for f in policy.check_expense(fields, s)]


def test_arithmetic_implausible_tax_share_soft():
    s = _seeded()
    fields = _base_arith(amount=100.0, tax=60.0)      # 60% tax — implausible
    assert any(f.rule == "arithmetic_mismatch" for f in policy.check_expense(fields, s))


def test_arithmetic_silent_without_evidence():
    s = _seeded()
    fields = _base_arith(amount=30.0)                 # no line_items, no tax → nothing to check
    assert "arithmetic_mismatch" not in [f.rule for f in policy.check_expense(fields, s)]


# ── WF3 reasoning layer: perceptual-hash near-duplicate (§L.2) ──
_PHASH = 0x0F0F0F0F0F0F0F0F


def _approve_with_phash(s, h):
    s.create("submissions", "expense_claim",
             {"employee_name": "Alice Tan", "vendor": "Prev Shop", "date": "2026-06-01",
              "amount": 10.0, "currency": "GBP", "category": "meals", "image_phash": h},
             status="approved")


def test_similar_receipt_soft_against_approved():
    s = _seeded()
    _approve_with_phash(s, _PHASH)
    fields = {"employee_name": "Alice Tan", "vendor": "New Shop", "date": "2026-06-28",
              "amount": 15.0, "currency": "GBP", "category": "meals", "image_phash": _PHASH}
    flags = policy.check_expense(fields, s)
    assert any(f.rule == "similar_receipt" and f.severity == "soft" for f in flags)


def test_dissimilar_image_no_flag():
    s = _seeded()
    _approve_with_phash(s, _PHASH)
    far = _PHASH ^ ((1 << 64) - 1)                    # every bit differs → Hamming 64
    fields = {"employee_name": "Alice Tan", "vendor": "New Shop", "date": "2026-06-28",
              "amount": 15.0, "currency": "GBP", "category": "meals", "image_phash": far}
    assert "similar_receipt" not in [f.rule for f in policy.check_expense(fields, s)]


# ── WF2 scheduling ──
def test_scheduling_conflict_soft():
    s = _seeded()
    # bob is seeded busy 2026-07-07 14:00–15:00
    event = {"date": "2026-07-07", "start": "14:30", "end": "15:00", "participants": ["bob"]}
    flags = policy.check_scheduling(event, s)
    assert any(f.rule == "conflict" for f in flags)


def test_scheduling_no_conflict_when_adjacent():
    s = _seeded()
    event = {"date": "2026-07-07", "start": "15:00", "end": "15:30", "participants": ["bob"]}
    assert not any(f.rule == "conflict" for f in policy.check_scheduling(event, s))


def test_scheduling_unknown_participant_and_out_of_hours():
    s = _seeded()
    event = {"date": "2026-07-07", "start": "08:00", "end": "08:30",
             "participants": ["ghost"]}
    rules = {f.rule for f in policy.check_scheduling(event, s)}
    assert "unknown_participant" in rules and "out_of_hours" in rules


def test_scheduling_room_over_capacity():
    s = _seeded()
    event = {"date": "2026-07-09", "start": "10:00", "end": "11:00",
             "participants": ["alice", "bob", "chen", "dana"], "location": "Vega"}  # cap 3
    assert any(f.rule == "room_over_capacity" for f in policy.check_scheduling(event, s))


def test_scheduling_room_conflict_reads_current_location_field():
    s = _seeded()
    s.create(
        "events",
        "event",
        {
            "title": "Existing room booking",
            "date": "2026-07-09",
            "start": "10:00",
            "end": "11:00",
            "participants": ["alice"],
            "location": "Orion",
        },
        status="booked",
    )
    event = {
        "date": "2026-07-09",
        "start": "10:30",
        "end": "11:30",
        "participants": ["chen"],
        "location": "Orion",
    }
    flags = policy.check_scheduling(event, s)
    assert any(f.rule == "room_double_booked" for f in flags)


# ── FX conversion + non-reimbursable ──
def test_fx_over_limit_converts_before_comparing():
    s = _seeded()
    # 55 EUR ≈ £46.75 — raw 55 would exceed the £50 meals cap, converted it doesn't
    under = {"employee_name": "Alice Tan", "vendor": "Bistro", "date": "2026-06-28",
             "amount": 55.0, "currency": "EUR", "category": "meals"}
    assert "over_limit" not in [f.rule for f in policy.check_expense(under, s)]
    # 100 USD ≈ £79 > £50 → fires, message shows the converted value
    over = dict(under, amount=100.0, currency="USD")
    flags = policy.check_expense(over, s)
    assert [f.rule for f in flags] == ["over_limit"]
    assert "USD" in flags[0].message


def test_unknown_currency_flagged_not_crashing():
    s = _seeded()
    fields = {"employee_name": "Alice Tan", "vendor": "Shop", "date": "2026-06-28",
              "amount": 999.0, "currency": "XYZ", "category": "meals"}
    flags = policy.check_expense(fields, s)
    assert [f.rule for f in flags] == ["unknown_currency"]
    assert flags[0].severity == "hard"  # cannot approve against an unknown budget scale


def test_budget_consumption_converts_to_gbp():
    s = _seeded()
    # a large-number JPY approved claim must not wipe the department budget
    s.create("submissions", "expense_claim",
             {"employee_name": "Alice Tan", "vendor": "Tokyo Inn", "date": "2026-06-20",
              "amount": 10000.0, "currency": "JPY", "category": "meals"},
             status="approved")
    dept = org.find_person("Alice Tan").department
    rem = policy.budget_remaining(dept, s)
    total = org.get_budget_total(dept)
    spent = total - rem
    assert spent < 100  # 10000 JPY ≈ £52, not £10000


def test_non_reimbursable_purpose_and_line_items():
    s = _seeded()
    base = {"employee_name": "Alice Tan", "vendor": "The Green Kitchen",
            "date": "2026-06-28", "amount": 20.0, "currency": "GBP", "category": "meals"}
    beers = dict(base, business_purpose="Team beers after the release")
    assert "non_reimbursable" in [f.rule for f in policy.check_expense(beers, s)]
    items = policy.check_expense(base, s, line_items=[{"desc": "House wine 175ml"}])
    assert "non_reimbursable" in [f.rule for f in items]
    # word boundary: "barista"/"finesse" must not fire
    ok = dict(base, business_purpose="Coffee with the barista team, finesse workshop")
    assert "non_reimbursable" not in [f.rule for f in policy.check_expense(ok, s)]
