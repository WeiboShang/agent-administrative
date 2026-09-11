"""Tests for the deterministic statistical helpers. Offline."""
from backend.evals.stats import fmt_prop, mcnemar_exact, wilson_ci


def test_wilson_known_values():
    lo, hi = wilson_ci(8, 10)          # 0.8 at n=10 → wide interval
    assert 0.4 < lo < 0.6 and 0.9 < hi <= 1.0
    lo, hi = wilson_ci(80, 100)        # same p̂ at n=100 → tighter
    assert 0.70 < lo < 0.75 and 0.85 < hi < 0.90


def test_wilson_edges():
    assert wilson_ci(0, 0) == (0.0, 1.0)
    lo, hi = wilson_ci(10, 10)
    assert hi == 1.0 and lo > 0.6      # perfect score still has a floor < 1
    lo, hi = wilson_ci(0, 10)
    assert lo == 0.0 and hi < 0.35


def test_fmt_prop_shape():
    s = fmt_prop(0.67, 9)
    assert s.startswith("0.67 [") and s.endswith("(n=9)")


def test_mcnemar_exact():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(12, 0) == 0.00048828
    assert mcnemar_exact(3, 1) == 0.625
