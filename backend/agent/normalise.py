"""Normalising the *shape* of LLM output before deterministic code trusts it.

A model asked for `"<value> or null"` does not reliably answer with a JSON null: it may
emit the **string** `"null"`, `"N/A"`, `"unknown"`, or an empty string. Both observed live
on real data — a real AMI transcript crashed WF2's time parser with `time="null"`
(docs/results.md §2.8), and the vision model returned an empty `vendor` on real CORD
receipts. The synthetic generators never produce these (their fields are always
well-typed), so this class of failure is invisible to the internal eval.

The rule everywhere: a stringy null is **absent**, which surfaces the field as *missing
for the human to fill* rather than as a value the code parses or stores.
"""
from __future__ import annotations

from typing import Optional

NULLISH = {"null", "none", "nil", "n/a", "na", "unknown", "undefined",
           "not stated", "not specified", "not available", "-", "--"}


def clean(value: object) -> Optional[str]:
    """A trimmed string, or None when the model effectively said nothing."""
    if value is None:
        return None
    s = str(value).strip()
    return None if not s or s.lower() in NULLISH else s


def clean_number(value: object) -> Optional[float]:
    """A finite float, or None — for money/quantity fields the model may fudge.

    Accepts a numeric type or a numeric-looking string; rejects stringy nulls, prose and
    non-finite values ("amount": "unknown" must not become a claim.)
    """
    s = clean(value)
    if s is None:
        return None
    try:
        f = float(s)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None      # drop NaN / ±inf
