"""The hand-authored date suite must itself be sound, and must stay non-circular."""
import inspect
from datetime import datetime

from backend.evals import date_resolution as dr


def test_every_case_is_internally_consistent():
    """Guards against a typo'd expectation: `now` parses, and an ISO expectation is a date."""
    for expr, now_iso, expected, _note in dr.CASES:
        datetime.fromisoformat(now_iso)
        assert isinstance(expr, str)
        if expected not in (None, dr.AMBIGUOUS):
            datetime.strptime(expected, "%Y-%m-%d")


def test_gold_is_not_computed_by_the_function_under_test():
    """The whole point: no call to the resolver may appear in the CASES table's source."""
    src = inspect.getsource(dr)
    table = src[src.index("CASES:"):src.index("def evaluate_date_resolution")]
    assert "resolve_relative_date" not in table
    assert "date_ambiguity" not in table


def test_suite_covers_exact_and_never_invent_behaviours():
    kinds = {"exact": 0, "must_not_resolve": 0, "ambiguous": 0}
    for _e, _n, expected, _note in dr.CASES:
        kinds["ambiguous" if expected is dr.AMBIGUOUS
              else "must_not_resolve" if expected is None else "exact"] += 1
    assert kinds["exact"] >= 3 and kinds["must_not_resolve"] >= 3, kinds
    assert kinds["ambiguous"] == 0  # V5 freezes one explicit calendar-week convention.


def test_current_resolver_passes_the_suite():
    """If this fails, either the resolver regressed or a hand-authored expectation is wrong —
    both are worth stopping for."""
    r = dr.evaluate_date_resolution()["date_resolution"]
    assert r["accuracy"] == 1.0, r["failures"]
    assert r["exact"] == 1.0 and r["must_not_resolve"] == 1.0
    assert r["ambiguity_flagged"] is None


def test_report_shape():
    r = dr.evaluate_date_resolution()["date_resolution"]
    assert r["n"] == len(dr.CASES)
    assert isinstance(r["failures"], list)
