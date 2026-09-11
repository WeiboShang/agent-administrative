"""Tests for the O4 content eval (offline — injected generator, no LLM/key)."""
from backend.evals.content_score import evaluate_content, fact_coverage, make_content_cases


def _good_generate(source: str) -> dict:
    """Fake generator that echoes the facts (perfectly grounded note)."""
    facts = dict(line.split(": ", 1) for line in source.splitlines() if ": " in line)
    body = (f"Your claim for {facts.get('vendor')} on {facts.get('date')} of "
            f"{facts.get('amount')} {facts.get('currency')} was {facts.get('decision')}.")
    if "decision_reason" in facts:
        body += f" Reason: {facts['decision_reason']}."
    return {"subject": f"Expense claim {facts.get('decision')}", "body": body}


def test_cases_alternate_decisions_with_reasons():
    cases = make_content_cases(6, seed=1)
    assert [c["decision"] for c in cases] == ["approved", "rejected"] * 3
    assert all(c["reason"] for c in cases if c["decision"] == "rejected")


def test_fact_coverage_full_on_grounded_note():
    case = make_content_cases(2, seed=2)[1]          # a rejected case
    from backend.workflows.content import draft_decision_note
    note = draft_decision_note(case["fields"], case["decision"], reason=case["reason"],
                               flags=case["flags"], generate=_good_generate)
    assert fact_coverage(note, case) == 1.0


def test_fact_coverage_penalises_missing_amount():
    case = make_content_cases(1, seed=3)[0]
    note = {"subject": "Approved", "body":
            f"Your claim for {case['fields']['vendor']} on {case['fields']['date']} was approved."}
    assert fact_coverage(note, case) < 1.0


def test_evaluate_content_offline():
    r = evaluate_content(4, generate=_good_generate)
    assert r["n"] == 4 and r["generation_failures"] == 0
    assert r["fact_coverage"] == 1.0
    assert "faithfulness" not in r                    # no judge passed
