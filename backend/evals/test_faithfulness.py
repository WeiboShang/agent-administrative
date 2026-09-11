"""Tests for the faithfulness judge core. Offline — uses stub judges, no model client."""
import json


from backend.evals.faithfulness import (
    cohens_kappa,
    compare_judges,
    judge_all,
    judge_batch,
    score_human_labels,
    to_labelling_rows,
    evaluate_faithfulness,
    judge_faithfulness,
)


def _stub(claims, rationale="ok"):
    """A judge_fn that ignores the prompt and returns fixed JSON (with surrounding prose)."""
    payload = json.dumps({"claims": claims, "rationale": rationale})
    return lambda _prompt: f"Here is my assessment:\n{payload}\nDone."


def test_partial_faithfulness():
    judge = _stub([
        {"claim": "meeting on Monday", "supported": True},
        {"claim": "with Alice", "supported": True},
        {"claim": "budget approved", "supported": False},  # invented
    ])
    r = judge_faithfulness("source", "output", judge)
    assert r.n_claims == 3
    assert r.faithfulness == round(2 / 3, 3)
    assert r.has_unsupported_claim is True


def test_fully_faithful():
    judge = _stub([{"claim": "a", "supported": True}, {"claim": "b", "supported": True}])
    r = judge_faithfulness("s", "o", judge)
    assert r.faithfulness == 1.0
    assert r.has_unsupported_claim is False


def test_no_claims_is_vacuously_faithful():
    r = judge_faithfulness("s", "o", lambda _p: '{"claims": [], "rationale": "none"}')
    assert r.faithfulness is None
    assert r.has_unsupported_claim is False
    assert r.n_claims == 0
    assert r.parse_status == "empty_claims"


def test_parse_error_is_handled():
    r = judge_faithfulness("s", "o", lambda _p: "the model rambled with no json")
    assert r.n_claims == 0
    assert r.rationale == "parse_error"
    assert r.faithfulness is None
    assert r.parse_status == "parse_error"


def test_evaluate_aggregates():
    judge = _stub([
        {"claim": "x", "supported": True},
        {"claim": "y", "supported": False},
    ])
    report = evaluate_faithfulness([("s1", "o1"), ("s2", "o2")], judge)
    assert report["n"] == 2
    assert report["mean_faithfulness"] == 0.5
    assert report["unsupported_rate"] == 1.0


def test_cohens_kappa():
    assert cohens_kappa([1, 0, 1], [1, 0, 1]) == 1.0          # perfect agreement
    assert cohens_kappa([1, 1, 0, 0], [1, 0, 0, 0]) == 0.5    # worked example


# ── batching: the lever that buys sample size under a per-DAY request cap ──

def _batch_reply(n: int, unsupported: set = frozenset()) -> str:
    items = [{"id": i + 1,
              "claims": [{"claim": f"c{i}", "supported": i not in unsupported}],
              "rationale": "r"}
             for i in range(n)]
    return json.dumps({"items": items})


def test_a_batch_costs_one_request_and_keeps_item_order():
    calls = []

    def judge(prompt):
        calls.append(prompt)
        return _batch_reply(3, unsupported={1})

    pairs = [("s0", "o0"), ("s1", "o1"), ("s2", "o2")]
    rs = judge_batch(pairs, judge)
    assert len(calls) == 1                                   # one request for three items
    assert [r.has_unsupported_claim for r in rs] == [False, True, False]


def test_a_malformed_batch_falls_back_to_one_request_per_pair():
    """A half-parsed batch must never be accepted: a shifted id would attach one item's
    claims to another item's source and silently corrupt the numbers."""
    calls = []

    def judge(prompt):
        calls.append(prompt)
        if "ITEM 1" in prompt and "ITEM 2" in prompt:        # the batch attempt
            return json.dumps({"items": [{"id": 1, "claims": []}]})   # wrong count
        return '{"claims": [{"claim": "c", "supported": true}], "rationale": "r"}'

    rs = judge_batch([("s0", "o0"), ("s1", "o1")], judge)
    assert len(rs) == 2
    assert len(calls) == 3                                   # 1 failed batch + 2 singles
    assert all(r.faithfulness == 1.0 for r in rs)


def test_batched_and_unbatched_agree():
    def judge(prompt):
        if "ITEM 1" in prompt:
            n = prompt.count("--- ITEM ")
            return _batch_reply(n, unsupported={0})
        return '{"claims": [{"claim": "c", "supported": false}], "rationale": "r"}'

    pairs = [("s", "o")] * 4
    assert judge_all(pairs, judge, batch_size=1)[0].has_unsupported_claim
    assert judge_all(pairs, judge, batch_size=4)[0].has_unsupported_claim


def test_batch_size_one_never_uses_the_batch_prompt():
    seen = []
    judge_all([("s", "o")], lambda p: seen.append(p) or
              '{"claims": [], "rationale": "r"}', batch_size=1)
    assert "ITEM 1" not in seen[0]


# ── judge validation ──

def test_compare_judges_reports_each_judge_and_their_agreement():
    strict = lambda _p: '{"claims": [{"claim": "c", "supported": false}]}'   # noqa: E731
    lax = lambda _p: '{"claims": [{"claim": "c", "supported": true}]}'       # noqa: E731
    rep = compare_judges([("s", "o")] * 3, {"strict": strict, "lax": lax}, batch_size=1)
    assert rep["judges"]["strict"]["unsupported_rate"] == 1.0
    assert rep["judges"]["lax"]["unsupported_rate"] == 0.0
    pair = rep["agreement"]["lax vs strict"]
    assert pair["raw_agreement"] == 0.0
    assert pair["disagreed_on"] == [0, 1, 2]        # every item — the shortlist to label


def test_labelling_rows_leave_the_human_column_empty():
    pairs = [("s0", "o0"), ("s1", "o1")]
    rs = judge_all(pairs, lambda _p: '{"claims": [{"claim": "c", "supported": false}]}',
                   batch_size=1)
    rows = to_labelling_rows(pairs, {"g": rs})
    assert [r["human_supported"] for r in rows] == [None, None]
    assert all(r["judge_g"] is True for r in rows)
    assert rows[0]["source"] == "s0"


def test_score_human_labels_needs_labels_then_computes_kappa():
    rows = [{"i": 0, "judge_g": True, "human_supported": None}]
    assert score_human_labels(rows, ["g"])["n_labelled"] == 0

    rows = [{"i": 0, "judge_g": True, "human_supported": True},
            {"i": 1, "judge_g": False, "human_supported": False},
            {"i": 2, "judge_g": True, "human_supported": True},
            {"i": 3, "judge_g": False, "human_supported": False}]
    out = score_human_labels(rows, ["g"])
    assert out["n_labelled"] == 4
    assert out["g"]["cohens_kappa"] == 1.0
    assert out["g"]["raw_agreement"] == 1.0


def test_partially_labelled_files_score_only_what_is_labelled():
    rows = [{"i": 0, "judge_g": True, "human_supported": True},
            {"i": 1, "judge_g": False, "human_supported": False},
            {"i": 2, "judge_g": True, "human_supported": None}]     # not yet labelled
    out = score_human_labels(rows, ["g"])
    assert out["n_labelled"] == 2 and out["n_total"] == 3


def test_batching_is_opt_in_not_the_default():
    """A quota saving that silently halves the safety-relevant rate is not a saving:
    measured 0.25 batched vs 0.50 unbatched on the same pairs (results.md §2.2b)."""
    import inspect

    from backend.evals import faithfulness as f
    for fn in (f.judge_all, f.evaluate_faithfulness, f.run_judges, f.compare_judges):
        assert inspect.signature(fn).parameters["batch_size"].default == 1, fn.__name__


def test_a_judge_that_runs_out_of_quota_is_dropped_not_fatal():
    """Losing the second opinion must not throw away the first judge's completed work."""
    from backend.evals.faithfulness import run_judges

    def dead(_p):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    seen = []
    out = run_judges([("s", "o")] * 2,
                     {"ok": lambda _p: '{"claims": [{"claim": "c", "supported": true}]}',
                      "dead": dead},
                     on_error=lambda n, e: seen.append(n))
    assert list(out) == ["ok"] and len(out["ok"]) == 2
    assert seen == ["dead"]
