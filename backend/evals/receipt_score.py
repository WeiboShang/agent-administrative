"""Scorer for the synthetic receipt eval — M1 (extraction × tier), M6 (refusal), M3 (flags).

Reference-based against the generator's gold (label-by-construction). The extractor is
pluggable — ``extract_fn(entry) -> dict`` — so the same harness runs offline (gold stub,
no key) or live (vision model). Offline tests use ``gold_as_extraction``.
"""
import json
import unicodedata
from collections import defaultdict
from typing import Any, Callable, Optional

from ..workflows.expense import validate_and_complete_expense

HARD_FIELDS = ("vendor", "date", "amount", "currency")
Entry = dict[str, Any]
ExtractFn = Callable[[Entry], dict]


def load_manifest(path: str) -> list[Entry]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def gold_as_extraction(entry: Entry) -> dict:
    """Ideal extractor: returns the receipt fields exactly (offline harness stub)."""
    gold, meta = entry["gold"], entry["meta"]
    if not meta.get("is_receipt", True):
        return {"not_a_receipt": True, "vendor": None, "amount": None}
    return {k: gold.get(k) for k in ("vendor", "date", "amount", "currency", "category")}


def _norm(v: Any) -> Optional[str]:
    """Case- and accent-insensitive ("Café"=="Cafe"): vision models legitimately
    transliterate accents, and exact-match on diacritics would score correct reads
    as extraction errors."""
    if v is None:
        return None
    s = unicodedata.normalize("NFKD", str(v).strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def score_extraction(entry: Entry, extracted: dict) -> dict:
    """Per-field exact match (M1); for non-receipts, correct-refusal (M6)."""
    meta = entry["meta"]
    row: dict[str, Any] = {"tier": meta["tier"]}
    if not meta.get("is_receipt", True):
        row["correct_refusal"] = bool(extracted.get("not_a_receipt")) or (
            extracted.get("vendor") is None and extracted.get("amount") is None)
        return row
    gold = entry["gold"]
    for fld in HARD_FIELDS:
        row[f"{fld}_ok"] = _norm(extracted.get(fld)) == _norm(gold.get(fld))
    return row


def score_policy(entry: Entry, store: Any) -> Optional[dict]:
    """M3: does the policy engine flag exactly the expected rules for this case?"""
    exp = set(entry["meta"].get("expected_flags", []))
    if not exp:
        return None
    gold = entry["gold"]
    # line_items (+ tax) are the evidence check_arithmetic reconciles — the `inconsistent`
    # tier needs them present; for every other tier the items sum to the total, so passing
    # them adds no spurious arithmetic flag.
    fields = {"employee_name": "Alice Tan", "business_purpose": "x",
              **{k: gold.get(k) for k in
                 ("vendor", "date", "amount", "currency", "category", "line_items", "tax")}}
    got = {f.rule for f in validate_and_complete_expense(fields, store).flags}
    return {"tier": entry["meta"]["tier"], "policy_ok": exp <= got,
            "expected": sorted(exp), "got": sorted(got)}


def aggregate(rows: list[dict]) -> dict:
    by_tier: dict[str, list] = defaultdict(list)
    for r in rows:
        by_tier[r["tier"]].append(r)
    report = {}
    for tier, rs in by_tier.items():
        m: dict[str, Any] = {"n": len(rs)}
        for fld in HARD_FIELDS:
            vals = [r[f"{fld}_ok"] for r in rs if f"{fld}_ok" in r]
            if vals:
                m[fld] = round(sum(vals) / len(vals), 3)
        ref = [r["correct_refusal"] for r in rs if "correct_refusal" in r]
        if ref:
            m["refusal"] = round(sum(ref) / len(ref), 3)
        report[tier] = m
    return report


def evaluate(entries: list[Entry], extract_fn: ExtractFn, store: Any) -> dict:
    ext_rows = [score_extraction(e, extract_fn(e)) for e in entries]
    pol_rows = [p for e in entries if (p := score_policy(e, store)) is not None]
    # auto-approve error rate: receipts where >=1 hard field would be wrong if
    # blindly approved — the errors human review exists to catch (RQ3 / M4 motivation).
    receipts = [r for r in ext_rows if "correct_refusal" not in r]
    errs = sum(1 for r in receipts if not all(r.get(f"{f}_ok", True) for f in HARD_FIELDS))
    # M7 — reasoning-consistency detection rate: of the `inconsistent` receipts (printed total
    # ≠ Σ line items), the fraction check_arithmetic flags. This is CODE detection, so it
    # approaches 1.0 — the write-up point is the CONTRAST with M1: the vision model reads the
    # fields accurately yet is blind to their mutual inconsistency; the reasoning layer recovers it.
    incon = [p for p in pol_rows if p["tier"] == "inconsistent"]
    reasoning = round(sum(p["policy_ok"] for p in incon) / len(incon), 3) if incon else None
    return {
        "extraction": aggregate(ext_rows),
        "policy": pol_rows,
        "auto_approve_error_rate": round(errs / len(receipts), 3) if receipts else 0.0,
        "reasoning_consistency": reasoning,
    }


def _cell(m: dict, k: str) -> str:
    return f"{m[k]:.2f}" if k in m else "  –  "


def format_report(report: dict) -> str:
    lines = ["tier           n   vendor  date   amount  curr   refusal"]
    for tier, m in report["extraction"].items():
        cells = "  ".join(_cell(m, k) for k in ("vendor", "date", "amount", "currency", "refusal"))
        lines.append(f"{tier:<13} {m['n']:<3} {cells}")
    if report["policy"]:
        lines.append("")
        lines.append("policy (M3): " + ", ".join(
            f"{p['tier']}={'OK' if p['policy_ok'] else 'MISS'}" for p in report["policy"]))
    return "\n".join(lines)
