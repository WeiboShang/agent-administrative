"""Scorer for the WF1 triage eval — action-detection + correct-refusal, per difficulty tier.

Reference-based against the generator's gold. Pluggable ``extract_fn(case) -> dict`` (a
triage result with ``detected_actions``) so the same harness runs offline (gold stub) or
live (LLM triage). Metrics per tier:
  - recall            : fraction of gold routable actions detected
  - exact             : detected exactly the gold routable actions (no spurious)
  - correct_refusal   : (out_of_scope) detected NO routable action
"""
from collections import defaultdict
from typing import Any, Callable

from ..workflows.triage import ROUTABLE, validate_triage
from .triage_data import ThreadCase

ExtractFn = Callable[[ThreadCase], dict]


def gold_as_triage(case: ThreadCase) -> dict:
    """Perfect extractor: emit the gold action types (offline harness stub)."""
    return {"detected_actions": [{"action_type": t} for t in case.gold["action_types"]]}


def score_case(case: ThreadCase, extracted: dict) -> dict:
    gold = {t for t in case.gold["action_types"] if t in ROUTABLE}
    got = {a.get("action_type") for a in extracted.get("detected_actions", [])
           if a.get("action_type") in ROUTABLE}
    row: dict[str, Any] = {"tier": case.meta["tier"]}
    if not gold:                                   # out_of_scope
        row["correct_refusal"] = (len(got) == 0)
    else:
        row["recall"] = len(gold & got) / len(gold)
        row["exact"] = (gold == got)
    cov = summary_coverage(case, extracted)
    if cov is not None:
        row["coverage"] = cov
    return row


def summary_coverage(case: ThreadCase, extracted: dict) -> Any:
    """Fraction of the case's gold facts present in summary+key_points (None if n/a).

    Code-side key-information metric: the generator knows exactly which facts the buried
    action line contained (topic / weekday / time / names), so coverage is reference-based
    — no judge needed. Faithfulness (no invented claims) is the LLM-judge's separate job.
    """
    facts = case.meta.get("facts") or {}
    terms = [facts.get("topic"), facts.get("weekday"), facts.get("time"),
             *(facts.get("names") or [])]
    terms = [t for t in terms if t]
    if not terms or "summary" not in extracted:
        return None
    text = (extracted.get("summary") or "") + " " + " ".join(extracted.get("key_points") or [])
    text = text.lower()
    return sum(1 for t in terms if t.lower() in text) / len(terms)


def aggregate(rows: list[dict]) -> dict:
    by_tier: dict[str, list] = defaultdict(list)
    for r in rows:
        by_tier[r["tier"]].append(r)
    report = {}
    for tier, rs in by_tier.items():
        m: dict[str, Any] = {"n": len(rs)}
        for key in ("recall", "exact", "correct_refusal"):
            vals = [float(r[key]) for r in rs if key in r]
            if vals:
                m[key] = round(sum(vals) / len(vals), 3)
        report[tier] = m
    return report


def evaluate(cases: list[ThreadCase], extract_fn: ExtractFn) -> dict:
    return {"triage": aggregate([score_case(c, extract_fn(c)) for c in cases])}


def evaluate_position(cases: list[ThreadCase], extract_fn: ExtractFn) -> dict:
    """Needle-in-a-haystack grid: mean recall (+ coverage) per (length × position) cell."""
    cells: dict[tuple, list[dict]] = defaultdict(list)
    for c in cases:
        cells[(c.meta["length"], c.meta["position"])].append(score_case(c, extract_fn(c)))
    grid: dict[str, dict[str, Any]] = {}
    for (length, pos), rows in sorted(cells.items()):
        cell: dict[str, Any] = {"n": len(rows),
                                "recall": round(sum(r["recall"] for r in rows) / len(rows), 3)}
        covs = [r["coverage"] for r in rows if "coverage" in r]
        if covs:
            cell["coverage"] = round(sum(covs) / len(covs), 3)
        grid.setdefault(str(length), {})[pos] = cell
    return {"position": grid}


def _detected_routable(extracted: dict) -> set:
    return {a.get("action_type") for a in extracted.get("detected_actions", [])
            if a.get("action_type") in ROUTABLE}


def evaluate_pairs(pairs: list[tuple[ThreadCase, ThreadCase]], extract_fn: ExtractFn) -> dict:
    """Minimal-pair abstention: score each (T−, T+) twin jointly, per δ family.

    Reported per δ:
      - ``act_rate``        : T+ side detected the gold action
      - ``abstain_rate``    : T− side detected nothing routable
      - ``paired_accuracy`` : BOTH sides right — a constant policy scores 0 here, which is
                              the whole point of the twin design
      - ``car``             : calibrated abstention — abstain_rate *among the pairs whose
                              T+ side was right*. Without this conditioning, a model that is
                              simply too inert looks good at abstaining.
    """
    by_delta: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for minus, plus in pairs:
        gold_plus = {t for t in plus.gold["action_types"] if t in ROUTABLE}
        plus_ok = _detected_routable(extract_fn(plus)) == gold_plus
        minus_ok = len(_detected_routable(extract_fn(minus))) == 0
        by_delta[minus.meta["delta"]].append((minus_ok, plus_ok))

    def rate(vals: list[bool]) -> float:
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    report: dict[str, Any] = {}
    for delta, rows in by_delta.items():
        solved = [m for m, p in rows if p]          # T− outcomes where T+ was right
        report[delta] = {
            "n": len(rows),
            "act_rate": rate([p for _, p in rows]),
            "abstain_rate": rate([m for m, _ in rows]),
            "paired_accuracy": rate([m and p for m, p in rows]),
            "car": rate(solved) if solved else None,
        }
    return {"pairs": report}


def evaluate_underspecified(cases: list[ThreadCase], extract_fn: ExtractFn) -> dict:
    """A real request with no slot and no people: does the model INVENT the missing parts?

    Detection is the correct behaviour (the routing step's ``needs_input`` path is built for
    exactly this), so abstention is the wrong lens. What matters is whether ``seed_fields``
    stays honest: a fabricated "next Tuesday at 14:00" would hand the scheduler a slot nobody
    proposed. Values are read through ``normalise.clean`` so a stringy "null"/"N/A" counts as
    absent rather than as an invention.
    """
    from ..agent.normalise import clean

    detected: list[bool] = []
    fabricated: list[bool] = []
    per_field: dict[str, int] = defaultdict(int)
    for case in cases:
        acts = [a for a in extract_fn(case).get("detected_actions", [])
                if a.get("action_type") == "schedule_meeting"]
        detected.append(bool(acts))
        invented: set[str] = set()
        for a in acts:
            seed_fields = a.get("seed_fields") or {}
            for field in case.meta.get("expect_absent", []):
                v = seed_fields.get(field)
                if field == "participants":
                    if isinstance(v, list) and any(clean(str(p)) for p in v):
                        invented.add(field)
                elif clean(v) is not None:
                    invented.add(field)
        for field in invented:
            per_field[field] += 1
        fabricated.append(bool(invented))

    n = len(cases)
    return {"underspecified": {
        "n": n,
        "detection_rate": round(sum(detected) / n, 3) if n else 0.0,
        "fabrication_rate": round(sum(fabricated) / n, 3) if n else 0.0,
        "fabricated_by_field": {f: round(c / n, 3) for f, c in sorted(per_field.items())},
    }}


def evaluate_retraction(cases: list[ThreadCase], extract_fn: ExtractFn,
                        control_cases: list[ThreadCase] | None = None) -> dict:
    """Retracted plans: did the model abstain, and if not, did CODE recover the miss?

    The WF1 analogue of WF3's M1-vs-M7 contrast. Per distance tier:
      - ``model_abstained``  : the model itself declined to route the cancelled meeting
      - ``code_recovery``    : of the cases the model got WRONG, the fraction
                               ``check_retraction`` flagged
      - ``net_caught``       : caught by either layer — what the human actually sees

    ``control_cases`` (genuine, non-retracted meeting threads) give the flag's
    ``false_positive_rate``. Recovery without that number is meaningless: a check that fires
    on everything would score a perfect recovery rate.
    """
    from ..workflows.triage import check_retraction

    by_tier: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for case in cases:
        x = extract_fn(case)
        abstained = len(_detected_routable(x)) == 0
        recovered = bool(check_retraction(case.raw_text, x.get("detected_actions", []))) \
            if not abstained else False
        by_tier[case.meta["tier"]].append((abstained, recovered))

    def rate(vals: list[bool]) -> float:
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    report: dict[str, Any] = {}
    for tier, rows in by_tier.items():
        missed = [rec for ab, rec in rows if not ab]
        report[tier] = {
            "n": len(rows),
            "model_abstained": rate([ab for ab, _ in rows]),
            "code_recovery": rate(missed) if missed else None,
            "net_caught": rate([ab or rec for ab, rec in rows]),
        }

    out: dict[str, Any] = {"retraction": report}
    if control_cases:
        fp = [bool(check_retraction(c.raw_text, extract_fn(c).get("detected_actions", [])))
              for c in control_cases]
        out["retraction_false_positive_rate"] = rate(fp)
        out["retraction_control_n"] = len(fp)
    return out


def llm_triage_extract(case: ThreadCase, llm_extract) -> dict:
    """Live extractor: run the triage prompt over the thread and normalise it."""
    return validate_triage(llm_extract("triage", case.raw_text))
