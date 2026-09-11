"""Part A scripted review analysis — does the gate catch what the model got wrong?

This legacy M4 component now contributes to Scripted Review Analysis (Simulated
Upper-Bound). Instead of human subjects, three *scripted reviewer policies* decide at the
gate over drafts with **known injected
extraction errors** (rate and type controlled, so false-accept/false-reject are exact):

- ``blind``           approves everything as-extracted — the no-HITL baseline.
- ``flag_following``  trusts the policy engine only: rejects anything flagged or
                      incomplete, approves the rest unchanged. Catches *policy-visible*
                      errors; blind to field errors that break no rule.
- ``ideal``           verifies every field against the source (gold) and fixes it —
                      an oracle-assisted upper bound, not observed human behaviour.

Error types mirror the live failure modes found in evaluation (results.md §2.4):
year misread (low-res date), decimal/scale misread (CORD thousands separator), vendor
character noise, currency swap.
"""
import random
from typing import Any, Optional

from ..backends.records import RecordStore
from ..fixtures import org
from .receipt_data import make_receipt_case

POLICIES = ("blind", "flag_following", "ideal")
FIELD_KEYS = ("vendor", "date", "amount", "currency")     # verifiable receipt facts

_EMPLOYEES = ["Alice Tan", "Bob Rivera", "Dana Okoro", "Evan Schmidt"]


def _inject_error(fields: dict, kind: str) -> dict:
    f = dict(fields)
    if kind == "date_year" and f.get("date"):
        f["date"] = "2020" + f["date"][4:]                  # 2026 → 2020 (blur misread)
    elif kind == "amount_scale" and f.get("amount"):
        f["amount"] = round(float(f["amount"]) * 10, 2)     # decimal/separator misread
    elif kind == "vendor_typo" and f.get("vendor"):
        f["vendor"] = f["vendor"].replace("a", "o", 1) or f["vendor"] + "x"
    elif kind == "currency_swap":
        f["currency"] = "EUR" if f.get("currency") == "GBP" else "GBP"
    return f

ERROR_TYPES = ("date_year", "amount_scale", "vendor_typo", "currency_swap")


def make_m4_cases(n: int = 40, error_rate: float = 0.5, seed: int = 0) -> list[dict]:
    """``n`` gold claims; a controlled fraction gets 1 injected extraction error."""
    rng = random.Random(seed)
    cases = []
    for i in range(n):
        _, gold, _ = make_receipt_case("clean", seed=seed * 1000 + i)
        fields = {
            "employee_name": rng.choice(_EMPLOYEES),
            "vendor": gold["vendor"], "date": gold["date"],
            "amount": gold["amount"], "currency": gold["currency"],
            "category": gold["category"], "business_purpose": "Team business expense",
        }
        injected: Optional[str] = None
        draft = dict(fields)
        if rng.random() < error_rate:
            injected = rng.choice(ERROR_TYPES)
            draft = _inject_error(fields, injected)
        cases.append({"gold": fields, "draft": draft, "injected": injected})
    return cases


def _review(policy: str, draft: dict, gold: dict, flags: list, missing: list) -> dict:
    if policy == "blind":
        return {"decision": "approve", "final": draft, "edits": []}
    if policy == "flag_following":
        if flags or missing:
            return {"decision": "reject", "final": draft, "edits": []}
        return {"decision": "approve", "final": draft, "edits": []}
    # ideal: verify each fact against the source and fix it
    edits = [k for k in FIELD_KEYS if draft.get(k) != gold.get(k)]
    final = {**draft, **{k: gold[k] for k in edits}}
    return {"decision": "approve", "final": final, "edits": edits}


def evaluate_m4(n: int = 40, error_rate: float = 0.5, seed: int = 0) -> dict[str, Any]:
    """Run all policies over the same cases; exact M4 rates per policy (no LLM needed)."""
    cases = make_m4_cases(n=n, error_rate=error_rate, seed=seed)
    store = RecordStore(":memory:")
    org.seed_from_org(store)

    # validate once per case (the draft the reviewer sees is policy-independent)
    from ..workflows.expense import validate_and_complete_expense
    validated = [(c, validate_and_complete_expense(c["draft"], store)) for c in cases]

    def _is_wrong(c: dict) -> bool:
        return any(c["draft"].get(k) != c["gold"].get(k) for k in FIELD_KEYS)

    report: dict[str, Any] = {"n": n, "error_rate": error_rate,
                              "n_wrong": sum(1 for c in cases if _is_wrong(c)),
                              "policies": {}}
    for policy in POLICIES:
        fa = fr = caught = approved = edits = 0
        for c, d in validated:
            r = _review(policy, c["draft"], c["gold"], d.flags, d.missing_required)
            wrong = _is_wrong(c)
            fixed = all(r["final"].get(k) == c["gold"].get(k) for k in FIELD_KEYS)
            approved += r["decision"] == "approve"
            edits += len(r["edits"])
            if r["decision"] == "approve" and not fixed:
                fa += 1                                  # false accept: wrong record enters
            if r["decision"] == "reject" and not wrong:
                fr += 1                                  # false reject: needless intervention
            if wrong and (r["decision"] == "reject" or fixed):
                caught += 1
        n_wrong, n_right = report["n_wrong"], n - report["n_wrong"]
        report["policies"][policy] = {
            "approve_rate": round(approved / n, 3),
            "false_accept_rate": round(fa / n, 3),
            "false_reject_rate": round(fr / n_right, 3) if n_right else 0.0,
            "errors_caught": round(caught / n_wrong, 3) if n_wrong else 1.0,
            "edits_per_case": round(edits / n, 3),
        }
    return report
