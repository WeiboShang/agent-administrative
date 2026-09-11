"""Synthetic WF2 (scheduling) data generator — reverse generation (evaluation.md).

Sample a gold meeting in CODE, render it as a natural-ish message applying a difficulty
tier, and store ``(input_text, gold, meta)``. Because the gold is fixed *before* the text
exists, every case is labelled by construction (no annotation step).

Realisation here is **template-based and deterministic** (no LLM) so the generator runs
and is fully testable offline. An LLM realiser can be plugged in later for higher realism
(see docs/evaluation.md); the gold and metadata contract stays identical.

Dates are rendered only in forms the deterministic resolver handles (ISO, or
``next <weekday>``), so the round-trip back-check (§3.2 step 3) is exact. Richer date
phrasing would need a fuller parser (see resolve_relative_date's docstring).
"""
import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

from ..fixtures import org
from ..workflows.scheduling import add_minutes, resolve_relative_date

# Fixed reference "now" the data is generated against (a Tuesday; matches the org fixture).
GEN_NOW = datetime(2026, 6, 30, 9, 0)

TIERS = ("clean", "missing", "ambiguous", "noise", "revision",
         "stateful_conflict", "out_of_scope")

_TOPICS = [
    "the Q3 budget", "the launch plan", "the hiring pipeline",
    "the vendor contract", "the sprint review",
]
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
_TIMES = ["10:00", "11:30", "14:30", "15:00", "16:00"]

# Genuinely vague date phrases — the resolver (correctly) cannot resolve these, so the
# right behaviour is date=None + flag it missing, never invent (docs/evaluation.md §5).
_VAGUE_DATES = [
    "sometime early next week", "in the next couple of weeks",
    "once things calm down a bit", "later this month, whenever suits",
]

# Distractor sentences for the noise tier. Several deliberately carry OTHER days/times
# to stress slot confusion in the live LLM run (deterministic gold is unaffected).
_DISTRACTORS = [
    "Hope your week's going well — the team really enjoyed the offsite last Friday.",
    "Quick reminder that the fire drill is on Thursday at 10:00, don't be alarmed.",
    "The all-hands moved to the first Monday of the month, calendar invites updated.",
    "Also the expense deadline is Friday if you still have June receipts.",
    "The client demo yesterday went really well by the way, great feedback.",
    "Unrelated: the coffee machine on floor 2 is finally fixed.",
    "I'll be out at a conference on Wednesday, so email is best that day.",
    "PS the shared drive reshuffle is done, links from last quarter still work.",
]


@dataclass
class SchedulingGold:
    intent: str                      # "schedule_meeting" | "none" (out_of_scope)
    title: str
    participants: list[str]          # user_ids — the intended invitees
    date: Optional[str]              # absolute ISO YYYY-MM-DD — the intended answer
    time: Optional[str]
    duration_minutes: Optional[int]
    mode: str


@dataclass
class Case:
    input_text: str
    gold: dict
    meta: dict


def make_case(tier: str, seed: int) -> Case:
    """Generate one labelled case for ``tier`` (deterministic in ``seed``)."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    rng = random.Random(seed)

    topic = rng.choice(_TOPICS)
    people = rng.sample(org.PEOPLE, rng.choice([1, 2]))
    names = " and ".join(p.name for p in people)
    ids = [p.user_id for p in people]
    title = f"Sync on {topic}"
    virtual = rng.random() < 0.5
    mode = "virtual" if virtual else "in_person"
    mode_phrase = "Let's do it over Zoom." if virtual else "We can grab the Orion room."
    meta = {"workflow": "scheduling", "tier": tier, "now": GEN_NOW.isoformat()}

    if tier == "out_of_scope":
        # Not a meeting request at all — the agent should NOT fabricate one.
        gold = SchedulingGold("none", title, [], None, None, None, mode)
        text = rng.choice([
            f"Thanks {people[0].name}, the notes on {topic} look great — nothing needed from me.",
            f"Just confirming I saw your message about {topic}. All good on my end!",
        ])
        return Case(text, asdict(gold), meta)

    time = rng.choice(_TIMES)
    duration = rng.choice([30, 45, 60])
    weekday = rng.choice(_WEEKDAYS)
    abs_date = resolve_relative_date(f"next {weekday}", GEN_NOW)

    if tier == "ambiguous":
        # Genuinely vague date → the resolver can't (and shouldn't) produce a date.
        date_phrase = rng.choice(_VAGUE_DATES)
        meta["date_style"] = "vague"
    elif rng.random() < 0.5:                 # other tiers mix relative + explicit dates
        date_phrase = f"next {weekday}"
        meta["date_style"] = "relative"
    else:
        date_phrase = abs_date               # ISO — explicit, within resolver competence
        meta["date_style"] = "explicit"
    meta["date_phrase"] = date_phrase

    gold = SchedulingGold("schedule_meeting", title, ids, abs_date, time, duration, mode)

    if tier == "ambiguous":
        gold.date = None                     # never-invent-missing: no date IS the answer
        meta["missing"] = ["date"]
        text = (f"Hi {names}, can we meet about {topic} {date_phrase}, say at {time}? "
                f"About {duration} minutes. {mode_phrase}")
    elif tier == "missing":
        # The message omits the time → gold.time is null and the agent should flag it.
        gold.time = None
        meta["missing"] = ["time"]
        text = (f"Hi {names}, can we get together about {topic} on {date_phrase}? "
                f"Should be about {duration} minutes. {mode_phrase}")
    else:
        text = (f"Hi {names}, can we meet about {topic} on {date_phrase} at {time}? "
                f"About {duration} minutes. {mode_phrase}")

    if tier == "noise":
        # Bury the request among distractor sentences (some carry other days/times).
        around = rng.sample(_DISTRACTORS, rng.choice([3, 4, 5]))
        cut = rng.randint(1, len(around) - 1)
        text = " ".join(around[:cut] + [text] + around[cut:])
        meta["n_distractors"] = len(around)

    if tier == "revision":
        # A short negotiation: the FIRST proposed slot is superseded — gold = the FINAL
        # agreed one. Tests whether the extractor tracks the outcome, not the first mention.
        # Alice visibly organises ("can we meet") → she IS a participant here (gold
        # refinement found via error analysis: models correctly included her).
        gold.participants = sorted(set(ids) | {"alice"})
        other = rng.choice([w for w in _WEEKDAYS if w != weekday])
        other_time = rng.choice([t for t in _TIMES if t != time])
        first = rng.choice([p.name for p in people])
        if rng.random() < 0.5:   # day revised, time kept
            text = (f"Alice: Hi {names}, can we meet about {topic} next {other} at {time}? "
                    f"About {duration} minutes. {mode_phrase}\n"
                    f"{first}: {other} is tricky for me — could we do next {weekday} instead, "
                    f"same time?\n"
                    f"Alice: Next {weekday} at {time} works, let's lock that in.")
            meta["revised"] = "date"
        else:                     # time revised, day kept
            text = (f"Alice: Hi {names}, can we meet about {topic} next {weekday} at "
                    f"{other_time}? About {duration} minutes. {mode_phrase}\n"
                    f"{first}: I have a clash at {other_time} — could we do {time} instead?\n"
                    f"Alice: {time} it is, next {weekday} then.")
            meta["revised"] = "time"
        meta["date_phrase"] = f"next {weekday}"
        meta["date_style"] = "relative"
        meta["superseded"] = {"weekday": other, "time": other_time}

    if tier == "stateful_conflict":
        # The eval pre-books this event into the store; the request overlaps it, so the
        # stateful validator must flag a conflict against a *booked meeting* (not a seed).
        meta["pre_book"] = {
            "title": f"Existing sync with {people[0].name}",
            "participants": [ids[0]],
            "date": abs_date,
            "start": time, "end": add_minutes(time, duration),
        }
        meta["expect_conflict"] = True

    return Case(text, asdict(gold), meta)


def make_dataset(n_per_tier: int = 10, seed: int = 0) -> list[Case]:
    """Balanced set across all difficulty tiers (deterministic in ``seed``)."""
    cases: list[Case] = []
    for t_idx, tier in enumerate(TIERS):
        for i in range(n_per_tier):
            cases.append(make_case(tier, seed=seed * 1000 + t_idx * 100 + i))
    return cases


def back_check(case: Case) -> bool:
    """Self-consistency and round-trip check for a generated case.

    schedule_meeting: every gold participant resolves in the directory, the gold date is
    valid ISO, and the date phrase used in the text resolves (against the gold ``now``)
    back to the gold date. out_of_scope: no participants and no date.
    """
    gold, meta = case.gold, case.meta
    if gold["intent"] == "none":
        return gold["date"] is None and gold["participants"] == []
    if any(org.find_person(uid) is None for uid in gold["participants"]):
        return False
    pb = meta.get("pre_book")
    if pb:   # stateful_conflict: the pre-booked event must really overlap the request
        if not set(pb["participants"]) & set(gold["participants"]):
            return False
        end = add_minutes(gold["time"], gold["duration_minutes"] or 30)
        if pb["date"] != gold["date"] or not (gold["time"] < pb["end"] and pb["start"] < end):
            return False
    now = datetime.fromisoformat(meta["now"])
    return resolve_relative_date(meta.get("date_phrase"), now) == gold["date"]


def write_jsonl(cases: list[Case], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")


if __name__ == "__main__":  # pragma: no cover
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "scheduling_eval.jsonl"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    data = make_dataset(n_per_tier=n)
    assert all(back_check(c) for c in data), "back-check failed on a generated case"
    write_jsonl(data, out)
    print(f"wrote {len(data)} cases ({n}/tier × {len(TIERS)} tiers) to {out}")
