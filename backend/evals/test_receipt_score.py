"""Tests for the receipt scorer (offline — perfect-extractor stub, no key/model)."""
from backend.backends.records import RecordStore
from backend.evals.receipt_data import make_receipt_case
from backend.evals.receipt_score import (
    evaluate,
    gold_as_extraction,
    score_extraction,
    score_policy,
)
from backend.fixtures import org


def _entry(tier: str, seed: int = 0) -> dict:
    _, gold, meta = make_receipt_case(tier, seed)
    return {"image": "x.png", "gold": gold, "meta": meta}


def _seeded() -> RecordStore:
    s = RecordStore(":memory:")
    org.seed_from_org(s)
    return s


def test_perfect_extractor_scores_clean_all_correct():
    e = _entry("clean")
    row = score_extraction(e, gold_as_extraction(e))
    assert all(row[f"{f}_ok"] for f in ("vendor", "date", "amount", "currency"))


def test_wrong_field_scored_false():
    e = _entry("clean")
    bad = gold_as_extraction(e)
    bad["amount"] = 999.0
    assert score_extraction(e, bad)["amount_ok"] is False


def test_non_receipt_refusal_scored():
    e = _entry("non_receipt")
    assert score_extraction(e, gold_as_extraction(e))["correct_refusal"] is True


def test_policy_over_limit_detected():
    p = score_policy(_entry("over_limit"), _seeded())
    assert p["policy_ok"] is True and "over_limit" in p["got"]


def test_policy_duplicate_detected():
    p = score_policy(_entry("duplicate"), _seeded())
    assert p["policy_ok"] is True and "duplicate" in p["got"]


def test_evaluate_aggregates_per_tier():
    entries = [_entry(t) for t in ("clean", "non_receipt", "over_limit")]
    rep = evaluate(entries, gold_as_extraction, _seeded())
    assert rep["extraction"]["clean"]["vendor"] == 1.0
    assert rep["extraction"]["non_receipt"]["refusal"] == 1.0
    assert any(p["tier"] == "over_limit" and p["policy_ok"] for p in rep["policy"])


def test_policy_inconsistent_arithmetic_detected():
    p = score_policy(_entry("inconsistent"), _seeded())
    assert p["policy_ok"] is True and "arithmetic_mismatch" in p["got"]


def test_evaluate_reports_reasoning_consistency_m7():
    entries = [_entry("inconsistent", s) for s in range(4)]
    rep = evaluate(entries, gold_as_extraction, _seeded())
    # M7 — code detection of injected arithmetic faults; approaches 1.0 by construction
    assert rep["reasoning_consistency"] == 1.0


def test_reasoning_consistency_none_without_inconsistent_cases():
    rep = evaluate([_entry("clean")], gold_as_extraction, _seeded())
    assert rep["reasoning_consistency"] is None


def test_norm_is_accent_insensitive():
    from backend.evals.receipt_score import _norm
    assert _norm("Café Aurora") == _norm("Cafe Aurora")
    assert _norm("Café Aurora") == "cafe aurora"
    assert _norm(None) is None
