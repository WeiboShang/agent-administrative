"""Date-resolution accuracy against HAND-AUTHORED gold (WF2).

Why this exists: the scheduling generator builds its gold with
``resolve_relative_date(f"next {weekday}", GEN_NOW)`` — the very function under test — and
the scorer then compares the system's date to it. That makes `date_correct` **circular**: it
can only fail if the LLM mangles the phrase it was told to copy verbatim, so it measures
*transcription fidelity*, not whether the resolver's reading of English is right. It cannot,
even in principle, detect a wrong convention.

Every ``expected`` below is written by hand from the English meaning, with ``now`` fixed and
stated. Nothing here calls the function to decide what the answer should be. No LLM, no
quota — this is a pure-code capability measure that can be re-run instantly.

Reference points: relative expressions are a known LLM/parser failure surface (TRAVELER,
DateLogicQA), and the standard mitigation — pin an explicit reference date and do the
arithmetic in code rather than in the model — is the design WF2 already follows. What was
never checked is whether the *code's* convention matches what a speaker means.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..workflows.scheduling import date_ambiguity, resolve_relative_date

AMBIGUOUS = "AMBIGUOUS"          # sentinel: a correct system flags rather than silently picks

# (expression, now, expected, note)
#   expected = ISO date        → must resolve to exactly this
#            = None            → must NOT resolve (never-invent: the human fills it)
#            = AMBIGUOUS       → legacy sentinel retained for old result readers
# 2026-07-01 is a Wednesday; 2026-07-03 a Friday; 2026-06-29 a Monday.
CASES: list[tuple[str, str, Optional[str], str]] = [
    # ── explicit: no interpretation required ──
    ("2026-07-03", "2026-07-01T09:00", "2026-07-03", "ISO passes through"),
    ("2026-02-29", "2026-07-01T09:00", None, "2026 is not a leap year — must not invent"),

    # ── anchored to now ──
    ("today", "2026-07-01T09:00", "2026-07-01", ""),
    ("tomorrow", "2026-07-01T09:00", "2026-07-02", ""),
    ("tomorrow", "2026-12-31T09:00", "2027-01-01", "year boundary"),

    # ── bare weekday: the soonest future one; standard and unambiguous ──
    ("Friday", "2026-07-01T09:00", "2026-07-03", "Wed → this Fri"),
    ("Monday", "2026-07-01T09:00", "2026-07-06", "Wed → the coming Mon"),
    ("Wednesday", "2026-07-01T09:00", "2026-07-08", "on a Wed, a bare Wed rolls a week"),

    # ── explicit V5 calendar-week convention ──
    ("this Friday", "2026-07-01T09:00", "2026-07-03", "this = current calendar week"),
    ("this Monday", "2026-07-01T09:00", None, "current-week Monday has passed"),
    ("next Friday", "2026-07-01T09:00", "2026-07-10", "next = following calendar week"),
    ("next Friday", "2026-07-02T09:00", "2026-07-10", "Thu: never silently means tomorrow"),
    ("next Monday", "2026-07-01T09:00", "2026-07-06", "Wed: Mon has passed, readings agree"),
    ("next Wednesday", "2026-06-29T09:00", "2026-07-08", "following-week Wednesday"),
    ("next Friday", "2026-07-04T09:00", "2026-07-10", "Sat: Fri has passed, both readings agree"),
    ("next Friday", "2026-07-03T09:00", "2026-07-10", "on a Fri, both readings agree"),

    # ── richer phrasing (dateparser path) ──
    ("3 August 2026", "2026-07-01T09:00", "2026-08-03", ""),
    ("the day after tomorrow", "2026-07-01T09:00", "2026-07-03", ""),

    # ── genuinely vague: the never-invent rule says leave it to the human ──
    ("sometime next week", "2026-07-01T09:00", None, "no resolvable day"),
    ("in the near future", "2026-07-01T09:00", None, ""),
    ("ASAP", "2026-07-01T09:00", None, ""),
    ("", "2026-07-01T09:00", None, "empty"),
]


def evaluate_date_resolution() -> dict[str, Any]:
    """Score the resolver against hand-authored gold. Deterministic; costs nothing."""
    rows: list[dict[str, Any]] = []
    for expr, now_iso, expected, note in CASES:
        now = datetime.fromisoformat(now_iso)
        got = resolve_relative_date(expr, now)
        flagged = date_ambiguity(expr, now) is not None
        if expected is AMBIGUOUS:
            ok = flagged                       # must be surfaced, not silently chosen
            kind = "ambiguous"
        elif expected is None:
            ok = got is None                   # never-invent
            kind = "must_not_resolve"
        else:
            ok = got == expected and not flagged
            kind = "exact"
        rows.append({"expr": expr, "now": now_iso, "expected": expected, "got": got,
                     "flagged_ambiguous": flagged, "ok": ok, "kind": kind, "note": note})

    def rate(kind: str) -> Optional[float]:
        sel = [r["ok"] for r in rows if r["kind"] == kind]
        return round(sum(sel) / len(sel), 3) if sel else None

    return {"date_resolution": {
        "n": len(rows),
        "accuracy": round(sum(r["ok"] for r in rows) / len(rows), 3),
        "exact": rate("exact"),
        "must_not_resolve": rate("must_not_resolve"),
        "ambiguity_flagged": rate("ambiguous"),
        "failures": [r for r in rows if not r["ok"]],
    }}
