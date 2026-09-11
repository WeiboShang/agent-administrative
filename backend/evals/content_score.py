"""O4 content-generation eval — decision-note grounding (coverage + faithfulness).

The note generator's *source* is the record fact sheet (workflows/content.py), so both
signals are directly measurable:
  - **fact coverage** (code-side): are the decision word, amount, vendor, date — and the
    reason, when rejecting — actually present in the note? (A note that omits the amount
    is useless even if faithful.)
  - **faithfulness** (LLM-as-judge, evals/faithfulness.py): does the note contain claims
    NOT supported by the fact sheet? (Judge ≠ generator.)

Cases are synthetic decided claims built from the receipt generator's gold (label-by-
construction, no store/LLM needed to build them).
"""
from __future__ import annotations

import random
from typing import Any, Callable, Optional

from ..workflows.content import draft_decision_note
from .faithfulness import evaluate_faithfulness
from .receipt_data import make_receipt_case

_REJECT_REASONS = [
    "No itemised receipt was attached",
    "Claim falls outside the current quarter",
    "Business purpose is too vague for audit",
]
_FLAG_POOL = [
    {"rule": "over_limit", "severity": "soft",
     "message": "amount exceeds the per-day category limit"},
    {"rule": "non_reimbursable", "severity": "soft",
     "message": "possibly non-reimbursable item"},
]


def make_content_cases(n: int = 10, seed: int = 0) -> list[dict[str, Any]]:
    """Synthetic decided claims: alternating approve/reject, some with flags."""
    rng = random.Random(seed)
    cases = []
    for i in range(n):
        _, gold, _ = make_receipt_case("clean", seed=seed * 1000 + i)
        fields = {"employee_name": rng.choice(["Alice Tan", "Bob Rivera", "Chen Wu"]),
                  "vendor": gold["vendor"], "date": gold["date"],
                  "amount": gold["amount"], "currency": gold["currency"],
                  "category": gold["category"],
                  "business_purpose": "Team business expense"}
        decision = "approved" if i % 2 == 0 else "rejected"
        cases.append({
            "fields": fields, "decision": decision,
            "reason": rng.choice(_REJECT_REASONS) if decision == "rejected" else None,
            "flags": [rng.choice(_FLAG_POOL)] if rng.random() < 0.5 else [],
        })
    return cases


def fact_coverage(note: dict[str, Any], case: dict[str, Any]) -> float:
    """Fraction of must-mention facts present in subject+body (code-side, no judge)."""
    text = ((note.get("subject") or "") + " " + (note.get("body") or "")).lower()
    f = case["fields"]
    amount = f["amount"]
    checks = [
        case["decision"] in text or ("approv" in text if case["decision"] == "approved"
                                     else "reject" in text or "declin" in text),
        str(f["vendor"]).lower() in text,
        str(f["date"]) in text,
        (f"{amount:g}" in text) or (f"{amount:.2f}" in text),
    ]
    if case["decision"] == "rejected" and case["reason"]:
        # the reason need not be verbatim; require a distinctive content word
        keyword = max(case["reason"].split(), key=len).lower().strip(".,")
        checks.append(keyword in text)
    return sum(checks) / len(checks)


def evaluate_content(n: int, generate: Optional[Callable[[str], dict]] = None,
                     judge_fn: Optional[Callable] = None, *,
                     model: Optional[str] = None, seed: int = 0) -> dict[str, Any]:
    """Generate notes for n synthetic decided claims; score coverage (+faithfulness)."""
    cases = make_content_cases(n, seed=seed)
    notes, covs, pairs, failures = [], [], [], 0
    for case in cases:
        note = draft_decision_note(case["fields"], case["decision"],
                                   reason=case["reason"], flags=case["flags"],
                                   generate=generate, model=model)
        if "error" in note:
            failures += 1
            continue
        notes.append(note)
        covs.append(fact_coverage(note, case))
        pairs.append((note["source"], note["subject"] + "\n" + note["body"]))

    out: dict[str, Any] = {
        "n": len(cases), "generation_failures": failures,
        "fact_coverage": round(sum(covs) / len(covs), 3) if covs else None,
    }
    if judge_fn is not None and pairs:
        out["faithfulness"] = evaluate_faithfulness(pairs, judge_fn)
    return out
