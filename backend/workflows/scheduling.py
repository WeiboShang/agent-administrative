"""WF2 (meeting scheduling) — deterministic core on the stateful events store.

Implements the CODE half of the workflow (docs/wf2_scheduling_design.md): relative-date
resolution (native rules + dateparser fallback), participant resolution, conflict/policy
checks against everything already booked, gate-checked execution, and ``.ics`` export.
The LLM only produces the raw ``extraction`` dict fed in here; everything in this module
is deterministic so it is reproducible and testable (CLAUDE.md §4.4).
"""
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from ..agent.normalise import clean as _clean
from ..backends.records import RecordStore
from ..fixtures import org
from . import policy

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value.strip(), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def resolve_relative_date(expr: object, now: datetime) -> Optional[str]:
    """Resolve a date expression to ``YYYY-MM-DD`` against ``now``, or ``None``.

    V5 convention (shared by the product and Human Evaluation):

    * a bare weekday is the nearest *strictly future* occurrence;
    * ``this <weekday>`` is that day in the current calendar week, when it has not passed;
    * ``next <weekday>`` is that day in the following calendar week.

    The three forms are deliberately distinct.  In particular, with ``now`` on Tuesday,
    ``Wednesday`` and ``this Wednesday`` resolve to tomorrow while ``next Wednesday``
    resolves eight days ahead.  Handles ISO dates, ``today`` and ``tomorrow`` natively,
    then falls back to ``dateparser`` for richer unambiguous phrases.

    ``REQUIRE_PARTS=['day']`` keeps the fallback conservative: vague phrasing with no
    resolvable day ("sometime early next week") stays ``None`` — the never-invent rule
    (a missing date is the human's call, not a guess).
    """
    if not isinstance(expr, str):
        return None
    e = expr.strip().lower()
    if not e:
        return None
    if _is_iso_date(e):
        return datetime.strptime(e, "%Y-%m-%d").date().isoformat()
    if e == "today":
        return now.date().isoformat()
    if e == "tomorrow":
        return (now.date() + timedelta(days=1)).isoformat()
    if e.startswith("next "):
        name = e[5:].strip()
        if name in _WEEKDAYS:
            monday = now.date() - timedelta(days=now.weekday())
            return (monday + timedelta(days=7 + _WEEKDAYS[name])).isoformat()
    if e.startswith("this "):
        name = e[5:].strip()
        if name in _WEEKDAYS:
            monday = now.date() - timedelta(days=now.weekday())
            resolved = monday + timedelta(days=_WEEKDAYS[name])
            return resolved.isoformat() if resolved >= now.date() else None
    if e in _WEEKDAYS:
        name = e
        days_ahead = (_WEEKDAYS[name] - now.weekday()) % 7 or 7
        return (now.date() + timedelta(days=days_ahead)).isoformat()
    try:
        import dateparser
    except ImportError:                                   # keep the core dependency-light
        return None
    parsed = dateparser.parse(expr, settings={
        "RELATIVE_BASE": now, "PREFER_DATES_FROM": "future", "REQUIRE_PARTS": ["day"],
    })
    return parsed.date().isoformat() if parsed else None


def date_ambiguity(expr: object, now: datetime) -> Optional[str]:
    """Return no ambiguity under the explicit V5 weekday convention.

    The parameters remain for API compatibility.  Genuinely vague expressions still
    resolve to ``None`` and are handled as missing information by the deterministic gate.
    """
    del expr, now
    return None


def resolve_relative_date_v4(expr: object, now: datetime) -> Optional[str]:
    """Frozen V4 resolver: bare and ``next`` weekday both mean nearest future day.

    Kept only so archived V4 sessions remain reproducible after the V5 protocol fixes the
    temporal contract.  New product/evaluation code must use ``resolve_relative_date``.
    """
    if not isinstance(expr, str):
        return None
    e = expr.strip().lower()
    if not e:
        return None
    if _is_iso_date(e):
        return datetime.strptime(e, "%Y-%m-%d").date().isoformat()
    if e == "today":
        return now.date().isoformat()
    if e == "tomorrow":
        return (now.date() + timedelta(days=1)).isoformat()
    name = e[5:].strip() if e.startswith("next ") else e
    if name not in _WEEKDAYS:
        try:
            import dateparser
        except ImportError:
            return None
        parsed = dateparser.parse(expr, settings={
            "RELATIVE_BASE": now, "PREFER_DATES_FROM": "future", "REQUIRE_PARTS": ["day"],
        })
        return parsed.date().isoformat() if parsed else None
    days_ahead = (_WEEKDAYS[name] - now.weekday()) % 7 or 7
    return (now.date() + timedelta(days=days_ahead)).isoformat()


def date_ambiguity_v4(expr: object, now: datetime) -> Optional[str]:
    """Frozen V4 ambiguity flag for archived protocol replay."""
    if not isinstance(expr, str):
        return None
    e = expr.strip().lower()
    if not e.startswith("next "):
        return None
    name = e[5:].strip()
    if name not in _WEEKDAYS:
        return None
    if _WEEKDAYS[name] <= now.weekday():
        return None
    soonest = now.date() + timedelta(days=(_WEEKDAYS[name] - now.weekday()) % 7 or 7)
    return (f"{expr!r} is ambiguous: this coming {name.capitalize()} ({soonest.isoformat()}) "
            f"or the {name.capitalize()} after ({(soonest + timedelta(days=7)).isoformat()})?")


def add_minutes(time_str: str, minutes: int) -> str:
    """Add ``minutes`` to an ``HH:MM`` 24h time, returning ``HH:MM`` (same day)."""
    return (datetime.strptime(time_str, "%H:%M") + timedelta(minutes=minutes)).strftime("%H:%M")


# ── WF2 v2: stateful calendar (events store + policy engine, docs/wf2_scheduling_design.md) ──
def _flag_json(f: policy.Flag) -> dict[str, str]:
    return {"rule": f.rule, "severity": f.severity, "message": f.message}


_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


def validate_scheduling(extraction: dict, store: RecordStore, *,
                        now: datetime) -> tuple[dict, list[str], list[policy.Flag]]:
    """Validate a scheduling extraction against the **stateful** events store.

    Returns ``(event, missing_required, flags)``. Resolves dates + participants in CODE,
    computes the time window, and runs ``policy.check_scheduling`` (conflict / room /
    unknown-participant / out-of-hours) against everything already booked.
    """
    missing: list[str] = []
    provenance: dict[str, str] = {}
    title = _clean(extraction.get("title"))
    if not title:
        missing.append("title")

    raw_names = [n for n in ((_clean(x) for x in (extraction.get("participants") or [])))
                 if n]
    pdetails, pids = [], []
    for name in raw_names:
        p = org.find_person(name)
        if p:
            pdetails.append({"name": p.name, "email": p.email, "resolved": True})
            pids.append(p.user_id)
        else:
            pdetails.append({"name": name, "email": None, "resolved": False})
    if not raw_names:
        missing.append("participants")

    raw_date = _clean(extraction.get("date"))
    date = resolve_relative_date(raw_date, now)
    ambiguity = date_ambiguity(raw_date, now)
    if date is None:
        missing.append("date")
    elif ambiguity:
        provenance["date"] = "ambiguous"
    else:
        provenance["date"] = "explicit" if _is_iso_date(raw_date) else "inferred"

    # only a real HH:MM counts — anything else is a missing time for the human to fill,
    # never a value to hand to the parser
    time = _clean(extraction.get("time"))
    if time and not _TIME_RE.match(time):
        time = None
    if time:
        provenance["time"] = "explicit"
    else:
        missing.append("time")

    raw_dur = _clean(extraction.get("duration_minutes"))
    try:
        duration = int(float(raw_dur)) if raw_dur else 30
    except ValueError:
        raw_dur, duration = None, 30
    provenance["duration"] = "explicit" if raw_dur else "default"
    end = add_minutes(time, duration) if time else None

    event = {
        "title": title or "Untitled meeting",
        "organizer": extraction.get("organizer") or "coordinator",
        "participants": pids,               # resolved user_ids (the stored/canonical shape)
        "participant_names": raw_names,     # raw, for unknown-flagging + display
        "participant_details": pdetails,
        "date": date, "time": time, "start": time, "end": end,
        "duration_minutes": duration,
        "location": _clean(extraction.get("location")),
        "mode": _clean(extraction.get("mode")) or "virtual",
        "agenda": _clean(extraction.get("agenda")) or "",
        "slot_provenance": provenance,
    }
    # pass raw names so unknown participants are flagged; conflict resolves them internally
    flags = policy.check_scheduling({**event, "participants": raw_names}, store,
                                    now=now.date())
    if ambiguity:
        # soft by design: the code proposes its reading, the human confirms which was meant
        flags.append(policy.Flag("ambiguous_date", "soft", ambiguity))
    return event, missing, flags


def suggest_free_slots(event: dict, store: RecordStore, *, now: datetime,
                       limit: int = 3, horizon_days: int = 7,
                       spacing_minutes: int = 120) -> list[dict[str, str]]:
    """Deterministically find slots where every participant and the room are free.

    Constraint satisfaction is the part LLMs are measurably weakest at — NATURAL PLAN reports
    accuracy collapsing as participants and days grow, and self-correction making it *worse* —
    so the search is done in CODE and the model is never asked to guess a slot. The human
    still chooses: these are proposals for the gate, exactly like every other draft here.

    Scans the requested day first, then forward to ``horizon_days``, on the half hour inside
    working hours. Suggestions are kept ``spacing_minutes`` apart within a day: three adjacent
    half-hour slots are one choice wearing three hats, and the point of offering options is
    that they are genuinely different. Returns ``[]`` when there is no date or nothing to place.
    """
    date, duration = event.get("date"), event.get("duration_minutes") or 30
    if not date:
        return []
    try:
        start_day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return []

    participants = set(event.get("participants") or [])
    room = event.get("location") or event.get("room")
    open_h, close_h = policy.WORKING_HOURS
    booked = [r.data for r in store.list("events", status="booked")]
    taken = {(event.get("date"), event.get("start"))}      # don't re-propose the clashing slot

    def free(day: str, start: str, end: str) -> bool:
        if end > close_h:                                   # must finish inside the day
            return False
        for d in booked:
            if d.get("date") != day:
                continue
            if not (start < d.get("end", "") and d.get("start", "") < end):
                continue
            if participants & set(d.get("participants", [])):
                return False
            if room and (d.get("location") or d.get("room")) == room:
                return False
        return True

    out: list[dict[str, str]] = []
    for offset in range(horizon_days):
        day = (start_day + timedelta(days=offset)).isoformat()
        slot = datetime.strptime(open_h, "%H:%M")
        last_taken: Optional[datetime] = None
        while slot.strftime("%H:%M") < close_h:
            start = slot.strftime("%H:%M")
            end = add_minutes(start, duration)
            spaced = last_taken is None or slot - last_taken >= timedelta(minutes=spacing_minutes)
            if spaced and (day, start) not in taken and free(day, start, end):
                out.append({"date": day, "start": start, "end": end})
                last_taken = slot
                if len(out) >= limit:
                    return out
            slot += timedelta(minutes=30)
    return out


def to_ics(event: dict) -> str:
    """Minimal RFC-5545 VEVENT for a booked meeting (opens in any real calendar app)."""
    d = (event.get("date") or "").replace("-", "")
    s = (event.get("start") or "").replace(":", "") + "00"
    e = (event.get("end") or "").replace(":", "") + "00"
    who = ", ".join(p.get("name", "") for p in event.get("participant_details", []))
    loc = event.get("location") or ("Online" if event.get("mode") == "virtual" else "")
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//admin-agent//WF2//EN", "BEGIN:VEVENT",
        f"SUMMARY:{event.get('title', '')}", f"DTSTART:{d}T{s}", f"DTEND:{d}T{e}",
        f"LOCATION:{loc}", f"DESCRIPTION:{event.get('agenda', '')} (with {who})",
        "END:VEVENT", "END:VCALENDAR",
    ]) + "\r\n"


def execute_scheduling(event: dict, store: RecordStore, *, decision: str,
                       reason: Optional[str] = None,
                       changed_fields: Optional[list[str]] = None,
                       now: Optional[datetime] = None,
                       calendar_backend: Optional[Any] = None,
                       override_soft_flags: bool = False,
                       override_reason: Optional[str] = None) -> dict[str, Any]:
    """Apply the human decision after a live policy recheck.

    Scheduling warnings are overridable, but a plain ``approve`` is not itself permission to
    override them.  The first attempt returns ``requires_override_confirmation`` without any
    local or provider write.  A second, explicit approval must carry both
    ``override_soft_flags=True`` and a non-empty audit reason.

    approve → book on the stateful local calendar (future validations see it) + ``.ics`` +
    in-app notifications + configured provider sync, recording any overridden soft flags.
    reject → log with its reason.

    The event arrives from the client (the human edited it), so the *time window* is
    recomputed here from ``time`` + ``duration_minutes`` rather than trusting the incoming
    ``start``/``end`` — code owns the arithmetic (CLAUDE.md §4.4), and a hand-edited time
    with a stale ``end`` would otherwise book a negative-length meeting.

    ``calendar_backend`` overrides the ``config.CALENDAR_BACKEND`` factory. It exists so a
    caller can be *structurally* barred from a real calendar rather than trusting an env var:
    the M2 task-success harness injects a mock, which is what keeps evaluation on the mock
    path (CLAUDE.md §3.4) even when the interactive app is configured for the Google demo.
    """
    changed = changed_fields or []
    names = event.get("participant_names") or event.get("participants") or []

    time = _clean(event.get("time")) or _clean(event.get("start"))
    if time and not _TIME_RE.match(time):
        time = None
    try:
        duration = int(float(_clean(event.get("duration_minutes")) or 30))
    except ValueError:
        duration = 30
    if duration <= 0:
        duration = 30
    end = add_minutes(time, duration) if time else None
    event = {**event, "time": time, "start": time, "end": end, "duration_minutes": duration}

    # Re-resolve participants from the (possibly human-edited) names before either the
    # conflict gate or provider sync.  CODE owns these canonical IDs; the client deliberately
    # clears stale IDs whenever the editable people list is submitted.
    pdetails, pids = [], []
    for name in names:
        p = org.find_person(name)
        if p:
            pdetails.append({"name": p.name, "email": p.email, "resolved": True})
            pids.append(p.user_id)
        else:
            pdetails.append({"name": name, "email": None, "resolved": False})

    live_flags = policy.check_scheduling(
        {**event, "participants": names}, store, now=now.date() if now else None
    )
    flags_json = [_flag_json(f) for f in live_flags]

    if decision == "approve":
        missing = [k for k in ("date", "time") if not event.get(k)]
        if not (event.get("participants") or event.get("participant_names")):
            missing.append("participants")
        if missing:
            return {"status": "blocked_missing_required", "missing": missing, "flags": flags_json}
        if flags_json and not override_soft_flags:
            alternatives = (
                suggest_free_slots(
                    {**event, "participants": pids},
                    store,
                    now=now or datetime.now(),
                )
                if any(f.rule in {"conflict", "room_double_booked"} for f in live_flags)
                else []
            )
            return {
                "status": "requires_override_confirmation",
                "message": "Resolve the warnings or explicitly confirm an override.",
                "flags": flags_json,
                "alternatives": alternatives,
            }
        if flags_json and not (override_reason or "").strip():
            return {
                "status": "override_reason_required",
                "message": "Explain why overriding the live calendar warnings is acceptable.",
                "flags": flags_json,
            }
        data = {
            "title": event.get("title"), "organizer": event.get("organizer"),
            "participants": pids,
            "participant_details": pdetails,
            "date": event.get("date"), "start": event.get("start"), "end": event.get("end"),
            "duration_minutes": event.get("duration_minutes"),
            "location": event.get("location"), "mode": event.get("mode"),
            "agenda": event.get("agenda"), "origin": event.get("origin"),
            "policy_flags": flags_json, "overridden_flags": flags_json,
            "override_reason": (override_reason or "").strip() or None,
            "changed_fields": changed,
        }
        rec = store.create("events", "event", data, status="booked")
        notifications = [
            {"to": p.get("name"),
             "message": f"Meeting '{event.get('title')}' on {event.get('date')} {event.get('start')}"}
            for p in pdetails
        ]
        # Provider calendar write. Additive and non-blocking: the local
        # record above IS the booking. Backends promise not to raise, but the approval must
        # survive even a misbehaving one — so the call site is defensive too (belt and
        # braces), and any failure downgrades to a status note (calendar_backend.py).
        try:
            from ..backends.calendar_backend import get_calendar_backend
            backend = calendar_backend if calendar_backend is not None else get_calendar_backend()
            # ``event.participants`` may intentionally be empty: the editable participant
            # picker sends names as the authority and we resolve those names above.  The
            # calendar backend must therefore receive the canonical record + resolved IDs,
            # otherwise a valid Chen booking is silently treated as having no mapped target.
            cal_result = backend.book(data, pids)
        except Exception as e:  # noqa: BLE001 — a demo-feature fault must never fail a booking
            cal_result = {"status": "error", "error": f"{type(e).__name__}: {e}"}
        # Provider identity is state, not just a toast message: Smart Schedule needs the
        # remote event IDs later to update/reschedule/cancel the same Google event instead
        # of creating a duplicate or leaving an orphan behind.
        data = {**data, "calendar_sync": cal_result}
        store.update(rec.id, data=data)
        return {"status": "booked", "record_id": rec.id, "ics": to_ics(data),
                "notifications": notifications, "overridden_flags": flags_json,
                "calendar_backend": cal_result}

    if decision == "reject":
        rec = store.create("events", "event", {
            "title": event.get("title"), "date": event.get("date"), "start": event.get("start"),
            "participants": event.get("participants", []), "policy_flags": flags_json,
            "decision_reason": reason, "changed_fields": changed,
        }, status="rejected")
        return {"status": "rejected", "record_id": rec.id}

    raise ValueError(f"unknown decision: {decision}")
