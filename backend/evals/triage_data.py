"""Synthetic thread generator for the WF1 triage eval (reverse generation, template-based).

Sample the gold action(s) + a difficulty tier, then realise a short thread. Gold = the
action types that SHOULD be detected. Offline (no LLM/key); an LLM realiser can replace the
templates later for realism (docs/data_strategy.md §3.2).
"""
import random
from dataclasses import dataclass

TIERS = ("meeting", "expense", "multi", "noise", "out_of_scope", "ambiguous")

# Borderline social lines the agent should NOT turn into a booking (gold = none). These
# stress abstention: an over-eager model wrongly detects a schedule_meeting. A vague social
# invitation with no day/time and no admin action is not a routable request. Pool widened to
# 16 so the tier carries real variety at raised n (was 4 → each repeated ~4× at n=15); every
# line holds a social cue in realiser._TRIAGE_SOCIAL_CUES so it realises rather than falling
# back to template.
_AMBIGUOUS = [
    "Alice: We should really catch up properly sometime soon!",
    "Bob: Let's grab a coffee next week if you're around.",
    "Chen: Someone ought to organise a team social at some point.",
    "Dana: We must do lunch again, it's been ages!",
    "Evan: We should all get together for drinks after work sometime.",
    "Bob: I keep meaning to grab lunch with you — let's sort it out one of these days.",
    "Chen: We really need a proper team lunch soon, it's overdue.",
    "Dana: Fancy catching up over coffee when things quieten down?",
    "Alice: Ah, we should hang out outside work more, honestly.",
    "Evan: Let's get together for drinks to celebrate shipping — no rush on when.",
    "Bob: We ought to meet up for lunch one of these weeks.",
    "Chen: Someone should really plan a team night out at some point.",
    "Dana: Been meaning to say we should get coffee and properly chat sometime.",
    "Alice: We keep saying we'll grab a bite together and never actually do!",
    "Evan: It'd be nice to meet up over lunch when you're free.",
    "Bob: We should organise something social for the team soon-ish.",
]

_TOPICS = ["the Q3 budget", "the launch plan", "the vendor contract", "the sprint review"]
_NAMES = ["Bob", "Chen", "Dana", "Evan"]
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
_TIMES = ["10:00", "11:30", "14:00", "15:00"]

# Realistic multi-party chit-chat / distractors — no administrative action to route. Some
# look action-ish ("someone should…", deadlines) to stress the model's abstention.
_CHITCHAT = [
    "Bob: Morning all — hope everyone had a good weekend!",
    "Chen: Did anyone catch the match last night? Cracking game.",
    "Dana: The coffee machine on floor 2 is broken again, sigh.",
    "Evan: Deploy went out fine last night, no issues so far.",
    "Bob: Oh and the fire drill is apparently Thursday, just a heads up.",
    "Dana: Someone left a laptop in room Vega btw, it's at reception now.",
    "Chen: The canteen actually has decent options today for once.",
    "Evan: Reminder there's VPN maintenance this weekend, expect a blip.",
    "Bob: Great work on the demo yesterday everyone, client seemed happy.",
    "Dana: We really should tidy the shared drive at some point 😅",
]


@dataclass
class ThreadCase:
    raw_text: str
    gold: dict          # {"action_types": [...]}  ("none" = nothing to route)
    meta: dict


def _meeting_line(rng: random.Random) -> str:
    who = ", ".join(rng.sample(_NAMES, rng.choice([1, 2])))
    return (f"Alice: Can we sync on {rng.choice(_TOPICS)} next {rng.choice(_WEEKDAYS)} "
            f"at {rng.choice(_TIMES)}? {who} too.")


def _expense_line(rng: random.Random) -> str:
    return ("Alice: I paid GBP 48.20 for the train to the client workshop yesterday. "
            "Please reimburse it; the receipt is attached.")


def _wrap(rng: random.Random, action_lines: list[str], n_noise: int) -> str:
    """Bury the action line(s) among ``n_noise`` chit-chat turns (multi-party thread)."""
    turns = rng.sample(_CHITCHAT, min(n_noise, len(_CHITCHAT)))
    for line in action_lines:
        turns.insert(rng.randint(0, len(turns)), line)
    return "\n".join(turns)


def make_thread_case(tier: str, seed: int) -> ThreadCase:
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    rng = random.Random(seed)
    meta = {"tier": tier}
    if tier == "meeting":
        return ThreadCase(_wrap(rng, [_meeting_line(rng)], 3),
                          {"action_types": ["schedule_meeting"]}, meta)
    if tier == "expense":
        return ThreadCase(_wrap(rng, [_expense_line(rng)], 3),
                          {"action_types": ["expense_claim"]}, meta)
    if tier == "multi":
        return ThreadCase(_wrap(rng, [_meeting_line(rng), _expense_line(rng)], 3),
                          {"action_types": ["schedule_meeting", "expense_claim"]}, meta)
    if tier == "noise":
        return ThreadCase(_wrap(rng, [_meeting_line(rng)], 6),   # action buried in heavy noise
                          {"action_types": ["schedule_meeting"]}, meta)
    if tier == "ambiguous":                                     # borderline social → none
        return ThreadCase(_wrap(rng, [rng.choice(_AMBIGUOUS)], rng.choice([2, 3])),
                          {"action_types": ["none"]}, meta)
    return ThreadCase(_wrap(rng, [], rng.choice([4, 5, 6])),     # out_of_scope: chit-chat only
                      {"action_types": ["none"]}, meta)


def make_dataset(n_per_tier: int = 4, seed: int = 0) -> list[ThreadCase]:
    cases = []
    for t_idx, tier in enumerate(TIERS):
        for i in range(n_per_tier):
            cases.append(make_thread_case(tier, seed=seed * 1000 + t_idx * 100 + i))
    return cases


# ── Position-sensitivity grid (needle-in-a-haystack) ─────────────────────────────────
# One meeting line buried in a thread of `length` turns at a controlled position.
# Recall per (length × position) cell = how detection degrades with depth/burial.

LENGTHS = (10, 25, 50)
POSITIONS = ("early", "middle", "late")
_POS_FRAC = {"early": 0.1, "middle": 0.5, "late": 0.9}

_NOISE_SPEAKERS = ["Bob", "Chen", "Dana", "Evan", "Fiona"]

# Speaker-agnostic office chatter — 52 distinct lines so a 50-turn thread never repeats.
_NOISE_LINES = [
    "Morning all, hope everyone had a good weekend!",
    "The coffee machine on floor 2 is broken again, sigh.",
    "Deploy went out clean last night, no alerts so far.",
    "Did anyone catch the match last night? Cracking game.",
    "The canteen actually has decent options today for once.",
    "Reminder there's VPN maintenance this weekend, expect a blip.",
    "Someone left a laptop in room Vega, it's at reception now.",
    "Great work on the demo yesterday everyone, client seemed happy.",
    "We really should tidy the shared drive at some point.",
    "The fire drill is apparently Thursday, just a heads up.",
    "Anyone else's badge reader acting up this morning?",
    "The plants in the corner office finally got watered, miracle.",
    "New coffee beans in the kitchen, big upgrade.",
    "Monthly all-hands slides are on the shared drive now.",
    "The lift on the east side is out again, use the stairs.",
    "Passwords expire Friday, don't get locked out like me.",
    "Lost property box is overflowing, claim your umbrellas people.",
    "The office plants survived the heatwave, unlike my inbox.",
    "Anyone have a phone charger at their desk I can borrow?",
    "The client logo files are in the brand folder now.",
    "Standup moved 15 minutes earlier just for today.",
    "Wiki search is back up, thanks to whoever fixed it.",
    "Printer on 3 has toner now, spread the word.",
    "The travel policy doc got a refresh, mostly formatting.",
    "Free bagels in the kitchen from the vendor visit.",
    "Parking garage level 2 is closed for cleaning tomorrow.",
    "My laptop fan sounds like a jet engine today.",
    "The onboarding video re-render finished overnight.",
    "Someone's alarm has been going off in a locker for an hour.",
    "Quarterly survey closes tonight, two minutes tops.",
    "The test environment is slow again, restarting the runners.",
    "Nice weather for once, lunch outside anyone?",
    "The stapler thief has struck again, watch your desks.",
    "Build times improved a lot after the cache fix.",
    "The kitchen tap drips unless you push it fully down.",
    "New starter swag arrived, mugs look great this year.",
    "Anyone using the standing desk in the corner? It's free.",
    "The meeting room booking screen on 2 is frozen again.",
    "Support ticket volume was unusually low this week, nice.",
    "The api docs page loads twice as fast now, good job.",
    "Recycling bins moved next to the kitchen door.",
    "My keyboard's spacebar is developing opinions.",
    "The window blinds on the south side are fixed.",
    "Company card statements are due to finance by Monday.",
    "The demo laptop needs charging before any client visit.",
    "Guest wifi password rotated, it's on the noticeboard.",
    "Whoever labelled the cables in the server room: thank you.",
    "The water cooler bottle needs changing, I always miss it.",
    "Team photos from the offsite are in the shared album.",
    "The dashboard dark mode shipped, easy on the eyes.",
    "Heads up, the street outside is closed for a fun run Sunday.",
    "The vending machine finally takes contactless.",
]


def _meeting(rng: random.Random) -> tuple[str, dict]:
    """A meeting line + the gold facts it contains (for summary-coverage scoring)."""
    topic = rng.choice(_TOPICS)
    weekday = rng.choice(_WEEKDAYS)
    time = rng.choice(_TIMES)
    names = rng.sample(_NAMES, rng.choice([1, 2]))
    line = f"Alice: Can we sync on {topic} next {weekday} at {time}? {', '.join(names)} too."
    facts = {"topic": topic.removeprefix("the "), "weekday": weekday, "time": time,
             "names": names}
    return line, facts


def make_position_case(length: int, position: str, seed: int) -> ThreadCase:
    """A single meeting buried at a controlled depth in a `length`-turn thread."""
    if position not in POSITIONS:
        raise ValueError(f"unknown position: {position}")
    rng = random.Random(seed)
    line, facts = _meeting(rng)
    n_noise = min(length - 1, len(_NOISE_LINES))
    noise = [f"{rng.choice(_NOISE_SPEAKERS)}: {t}" for t in rng.sample(_NOISE_LINES, n_noise)]
    idx = round(_POS_FRAC[position] * len(noise))
    noise.insert(idx, line)
    return ThreadCase("\n".join(noise), {"action_types": ["schedule_meeting"]},
                      {"tier": f"len{length}", "length": length, "position": position,
                       "action_index": idx, "facts": facts})


def make_position_dataset(n_per_cell: int = 2, seed: int = 0) -> list[ThreadCase]:
    cases = []
    for li, length in enumerate(LENGTHS):
        for pi, pos in enumerate(POSITIONS):
            for i in range(n_per_cell):
                cases.append(make_position_case(
                    length, pos, seed=seed * 10000 + li * 1000 + pi * 100 + i))
    return cases


# ── Minimal pairs (abstention under a controlled δ) ──────────────────────────────────
# The `ambiguous` tier says the model over-detects, but its threads differ from the action
# threads in many ways at once, so the rate cannot be attributed to any one cue. Here each
# case ships a TWIN whose text is identical except for ONE contrast (δ): T− must be refused,
# T+ must be detected. Because a constant policy ("always act" / "always abstain") is right
# on exactly one side of every pair, paired accuracy floors it at 0.
#
# δ families are chosen so the gold is defensible without domain argument; `third_party`
# operationalises the error mode real AMI transcripts exposed (results.md §2.8) — the model
# mistaking a meeting it is *told about* for one being *requested of it*.
PAIR_DELTAS = ("time_specificity", "settled_vs_requested", "hypothetical_vs_actual",
               "third_party_vs_self")


# Vocabulary reserved for held-out feedback negatives. Kept disjoint from the test
# vocabulary so a negative can never coincide with a test item by chance — with only 4
# topics and 4 names, collisions are otherwise a matter of luck, and a negative that IS a
# test line would leak the answer. The δ *frame* is still shared (that is what in_family
# means); only the surface content differs, which also makes it a cleaner test of whether
# the model learned the pattern or memorised the string.
_HELDOUT_TOPICS = ["the pricing review", "the migration plan", "the support rota",
                   "the hiring loop"]
_HELDOUT_NAMES = ["Priya", "Marco", "Ines", "Tomas"]


def _pair_lines(delta: str, rng: random.Random, *,
                topics: list[str] | None = None,
                names: list[str] | None = None) -> tuple[str, str]:
    """Return (T− line, T+ line) for one δ family, sharing every other surface feature."""
    topic = rng.choice(topics or _TOPICS)
    weekday = rng.choice(_WEEKDAYS)
    time = rng.choice(_TIMES)
    who = rng.choice(names or _NAMES)

    if delta == "time_specificity":
        # δ = a schedulable slot. Everything else (topic, speech act) held constant.
        return (f"Alice: We should sync on {topic} sometime.",
                f"Alice: We should sync on {topic} next {weekday} at {time}.")
    if delta == "settled_vs_requested":
        # δ = tense/aspect only. Slot and people are identical on both sides.
        return (f"Alice: {who} and I already sorted out {topic} on {weekday} at {time}.",
                f"Alice: {who} and I need to sort out {topic} on {weekday} at {time}.")
    if delta == "hypothetical_vs_actual":
        # δ = mood. A conditional is not a request, even with a concrete slot attached.
        return (f"Alice: If we ever need to, we could meet on {topic} "
                f"next {weekday} at {time}.",
                f"Alice: We need to meet on {topic} next {weekday} at {time}.")
    if delta == "third_party_vs_self":
        # δ = whose meeting it is. Reporting someone else's meeting is not a request.
        return (f"Alice: Heard the marketing team are meeting about {topic} "
                f"next {weekday} at {time}.",
                f"Alice: Can we meet about {topic} next {weekday} at {time}?")
    raise ValueError(f"unknown delta: {delta}")


def make_pair_case(delta: str, seed: int) -> tuple[ThreadCase, ThreadCase]:
    """Return the (T−, T+) twin for ``delta``: identical threads but for the δ line.

    Both sides are built from ONE rng draw — same noise turns, same insertion index — so
    the only difference between the two texts is the contrast under test.
    """
    if delta not in PAIR_DELTAS:
        raise ValueError(f"unknown delta: {delta}")
    rng = random.Random(seed)
    minus_line, plus_line = _pair_lines(delta, rng)
    n_noise = rng.choice([2, 3])
    turns = rng.sample(_CHITCHAT, n_noise)
    idx = rng.randint(0, len(turns))               # drawn ONCE, shared by both sides

    def build(line: str, side: str, gold: list[str]) -> ThreadCase:
        t = list(turns)
        t.insert(idx, line)
        return ThreadCase("\n".join(t), {"action_types": gold},
                          {"tier": f"pair_{delta}", "delta": delta, "side": side,
                           "pair_seed": seed})

    return (build(minus_line, "minus", ["none"]),
            build(plus_line, "plus", ["schedule_meeting"]))


def make_pair_dataset(n_per_delta: int = 4, seed: int = 0) -> list[tuple[ThreadCase, ThreadCase]]:
    return [make_pair_case(delta, seed=seed * 10000 + d_idx * 100 + i)
            for d_idx, delta in enumerate(PAIR_DELTAS)
            for i in range(n_per_delta)]


# ── Retraction (a plan that is called off later in the same thread) ───────────────────
# The hard, realistic case: a FULLY specified plan (topic · day · time · room · attendees)
# is announced, distractors follow, and only at the end is it called off. Gold = no action:
# booking a cancelled meeting is a real-world harm. `near` vs `far` varies how many turns
# separate the plan from its retraction, testing whether the rich, concrete plan out-anchors
# a single terminal line.
RETRACTION_DISTANCES = {"near": 1, "far": 8}

_RETRACTIONS = [
    "Alice: Actually, scrap that — we don't need the meeting, I'll send a summary by email.",
    "Alice: Update: that session is cancelled, we sorted it on the thread instead.",
    "Alice: Change of plan — calling that one off, no need to meet after all.",
    "Alice: Ignore the above, the meeting is off; I'll handle it over email.",
    "Alice: Cancel that — no meeting needed, legal already came back with an answer.",
    "Alice: Cancelling that one; we'll cover it in the regular standup instead.",
    "Alice: Scrap the meeting — turns out it's already resolved on the ticket.",
    "Alice: Let's call it off, email will be quicker for this one.",
]
_ROOMS = ["Orion", "Vega", "Lyra", "Draco"]


def make_retraction_case(distance: str, seed: int) -> ThreadCase:
    """A fully-specified meeting plan that is retracted ``distance`` turns later."""
    if distance not in RETRACTION_DISTANCES:
        raise ValueError(f"unknown distance: {distance}")
    rng = random.Random(seed)
    topic, weekday = rng.choice(_TOPICS), rng.choice(_WEEKDAYS)
    time, room = rng.choice(_TIMES), rng.choice(_ROOMS)
    names = rng.sample(_NAMES, 2)
    # the plan is deliberately detailed — every field a scheduler would want is present
    plan = [
        f"Alice: Booking us in for {topic} next {weekday} at {time}.",
        f"Alice: Room {room} is free, and it should take about an hour.",
        f"Alice: {names[0]} and {names[1]}, please make sure you can attend.",
    ]
    gap = RETRACTION_DISTANCES[distance]
    filler = rng.sample(_CHITCHAT, min(gap, len(_CHITCHAT)))
    turns = plan + filler + [rng.choice(_RETRACTIONS)]
    return ThreadCase("\n".join(turns), {"action_types": ["none"]},
                      {"tier": f"retracted_{distance}", "distance": distance,
                       "gap_turns": gap, "plan_turns": len(plan)})


# ── Underspecified requests (AgentAbstain S1: the ask is real, the parameters are not) ──
# A genuine request to meet that names NO day, NO time and NO participants. Detection is
# CORRECT here — the architecture's `needs_input` path exists precisely for this — so the
# risk is not over-detection but **fabrication**: inventing a slot nobody proposed would put
# a wrong meeting on a real calendar. Scored on seed_fields, not on abstention.
_UNDERSPECIFIED = [
    "Alice: We need to meet about {topic} — can someone set that up?",
    "Alice: Can we get a session in the diary for {topic}?",
    "Alice: Let's book time to go through {topic} properly.",
    "Alice: Could you organise a call about {topic}?",
]
UNDERSPECIFIED_EXPECT_ABSENT = ("date", "time", "participants")


def make_underspecified_case(seed: int) -> ThreadCase:
    """A clear meeting request with no slot and no attendees named."""
    rng = random.Random(seed)
    line = rng.choice(_UNDERSPECIFIED).format(topic=rng.choice(_TOPICS))
    return ThreadCase(_wrap(rng, [line], rng.choice([2, 3])),
                      {"action_types": ["schedule_meeting"]},
                      {"tier": "underspecified",
                       "expect_absent": list(UNDERSPECIFIED_EXPECT_ABSENT)})


def make_underspecified_dataset(n: int = 6, seed: int = 0) -> list[ThreadCase]:
    return [make_underspecified_case(seed=seed * 10000 + 700 + i) for i in range(n)]


def pair_minus_line(delta: str, seed: int, *, heldout: bool = True) -> str:
    """The T− (should-refuse) line for a δ — used to build held-out feedback negatives.

    ``heldout`` draws from the reserved vocabulary so the line cannot collide with any test
    case; pass False only to reproduce a test item verbatim.
    """
    rng = random.Random(seed)
    return _pair_lines(delta, rng,
                       topics=_HELDOUT_TOPICS if heldout else None,
                       names=_HELDOUT_NAMES if heldout else None)[0]


def make_retraction_dataset(n_per_distance: int = 4, seed: int = 0) -> list[ThreadCase]:
    return [make_retraction_case(d, seed=seed * 10000 + d_idx * 100 + i)
            for d_idx, d in enumerate(RETRACTION_DISTANCES)
            for i in range(n_per_distance)]
