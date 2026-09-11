"""Tests for the M4 scripted-reviewer simulation. Offline, deterministic."""
from backend.evals.reviewer_sim import (
    ERROR_TYPES,
    FIELD_KEYS,
    _inject_error,
    evaluate_m4,
    make_m4_cases,
)


def test_injection_actually_corrupts_a_field():
    base = {"vendor": "Café Aurora", "date": "2026-06-20", "amount": 24.5,
            "currency": "GBP"}
    for kind in ERROR_TYPES:
        bad = _inject_error(base, kind)
        assert any(bad[k] != base[k] for k in FIELD_KEYS), kind


def test_cases_are_deterministic_and_error_rate_respected():
    a = make_m4_cases(n=30, error_rate=0.5, seed=1)
    b = make_m4_cases(n=30, error_rate=0.5, seed=1)
    assert [c["draft"] for c in a] == [c["draft"] for c in b]
    n_wrong = sum(1 for c in a if c["injected"])
    assert 5 <= n_wrong <= 25          # stochastic but near half


def test_policy_ordering_holds():
    """blind must false-accept ≈ every injected error; ideal must catch all with edits;
    flag_following sits in between (only policy-visible errors get caught)."""
    rep = evaluate_m4(n=60, error_rate=0.5, seed=2)
    blind = rep["policies"]["blind"]
    flagf = rep["policies"]["flag_following"]
    ideal = rep["policies"]["ideal"]

    assert blind["false_accept_rate"] > 0
    assert blind["errors_caught"] == 0.0
    assert blind["edits_per_case"] == 0.0

    assert ideal["false_accept_rate"] == 0.0
    assert ideal["errors_caught"] == 1.0
    assert ideal["edits_per_case"] > 0
    assert ideal["false_reject_rate"] == 0.0

    assert 0.0 <= flagf["errors_caught"] <= 1.0
    assert flagf["false_accept_rate"] <= blind["false_accept_rate"]
