"""Independent reference checks for the WF2 V3.5 evaluation.

This module deliberately does not import either production scheduling module.  It uses
only Python date/time arithmetic and frozen case/state values, so production conflict or
ranking logic cannot grade itself.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable

WORKDAY_START = "09:00"
WORKDAY_END = "18:00"
SLOT_STEP_MINUTES = 30


def add_minutes(start: str, minutes: int) -> str:
    return (
        datetime.strptime(start, "%H:%M") + timedelta(minutes=int(minutes))
    ).strftime("%H:%M")


def canonical_room(value: Any) -> str | None:
    text = " ".join(str(value or "").strip().casefold().split())
    if not text or text in {"online", "zoom", "virtual"}:
        return None
    if text.startswith("room "):
        text = text[5:]
    if text.endswith(" room"):
        text = text[:-5]
    return text or None


def overlaps(start: str, end: str, other_start: str, other_end: str) -> bool:
    return start < other_end and other_start < end


def _event_data(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return event.get("data", event)
    data = getattr(event, "data", None)
    return data if isinstance(data, dict) else {}


def _resources(data: dict[str, Any], *, organizer: str | None = None) -> set[str]:
    values = {str(value) for value in data.get("participants") or [] if value}
    event_organizer = data.get("organizer") or organizer
    if event_organizer:
        values.add(str(event_organizer))
    return values


def conflict_types(
    *,
    participants: Iterable[str],
    organizer: str | None,
    day: str,
    start: str,
    end: str,
    location: str | None,
    existing_events: Iterable[Any],
) -> list[str]:
    requested_resources = {str(value) for value in participants if value}
    if organizer:
        requested_resources.add(str(organizer))
    room = canonical_room(location)
    conflicts: set[str] = set()
    for raw_event in existing_events:
        event = _event_data(raw_event)
        if str(event.get("date") or "") != day:
            continue
        other_start = str(event.get("start") or "")
        other_end = str(event.get("end") or "")
        if not other_start or not other_end or not overlaps(
            start, end, other_start, other_end
        ):
            continue
        if requested_resources & _resources(event):
            conflicts.add("participant_conflict")
        other_room = canonical_room(event.get("location") or event.get("room"))
        if room and other_room == room:
            conflicts.add("room_conflict")
    return sorted(conflicts)


def slot_is_feasible(
    *,
    participants: Iterable[str],
    organizer: str | None,
    day: str,
    start: str,
    duration_minutes: int,
    location: str | None,
    existing_events: Iterable[Any],
) -> bool:
    try:
        end = add_minutes(start, duration_minutes)
    except (TypeError, ValueError):
        return False
    if start < WORKDAY_START or end > WORKDAY_END:
        return False
    return not conflict_types(
        participants=participants,
        organizer=organizer,
        day=day,
        start=start,
        end=end,
        location=location,
        existing_events=existing_events,
    )


def _date_range(start: str, end: str) -> Iterable[str]:
    current = date.fromisoformat(start)
    final = date.fromisoformat(end)
    while current <= final:
        yield current.isoformat()
        current += timedelta(days=1)


def enumerate_feasible_slots(
    *,
    participants: Iterable[str],
    organizer: str | None,
    date_start: str,
    date_end: str | None,
    duration_minutes: int,
    location: str | None,
    existing_events: Iterable[Any],
    exact_time: str | None = None,
    relax_infeasible_exact: bool = False,
) -> list[dict[str, str]]:
    """Enumerate legal slots without using production availability or ranking code."""
    requested_end = date_end or date_start
    starts: list[str] = []
    cursor = datetime.strptime(WORKDAY_START, "%H:%M")
    while cursor.strftime("%H:%M") < WORKDAY_END:
        start = cursor.strftime("%H:%M")
        if add_minutes(start, duration_minutes) <= WORKDAY_END:
            starts.append(start)
        cursor += timedelta(minutes=SLOT_STEP_MINUTES)

    if exact_time:
        exact_available = any(
            slot_is_feasible(
                participants=participants,
                organizer=organizer,
                day=day,
                start=exact_time,
                duration_minutes=duration_minutes,
                location=location,
                existing_events=existing_events,
            )
            for day in _date_range(date_start, requested_end)
        )
        if exact_available or not relax_infeasible_exact:
            starts = [exact_time]

    output: list[dict[str, str]] = []
    for day in _date_range(date_start, requested_end):
        for start in starts:
            if slot_is_feasible(
                participants=participants,
                organizer=organizer,
                day=day,
                start=start,
                duration_minutes=duration_minutes,
                location=location,
                existing_events=existing_events,
            ):
                output.append(
                    {
                        "date": day,
                        "start": start,
                        "end": add_minutes(start, duration_minutes),
                    }
                )
    return output


def diverse_capacity(slots: Iterable[dict[str, str]]) -> int:
    """Count a deterministic maximum set under V3.5's declared diversity rule."""
    chosen: list[dict[str, str]] = []
    for slot in sorted(slots, key=lambda item: (item["date"], item["start"])):
        if any(
            slot["date"] == previous["date"]
            and abs(
                _minutes(slot["start"]) - _minutes(previous["start"])
            ) < 60
            for previous in chosen
        ):
            continue
        chosen.append(slot)
    return len(chosen)


def candidates_are_diverse(candidates: Iterable[dict[str, Any]]) -> bool:
    rows = list(candidates)
    return all(
        left.get("date") != right.get("date")
        or abs(_minutes(str(left.get("start"))) - _minutes(str(right.get("start"))))
        >= 60
        for index, left in enumerate(rows)
        for right in rows[index + 1 :]
    )


def _minutes(value: str) -> int:
    parsed = datetime.strptime(value, "%H:%M")
    return parsed.hour * 60 + parsed.minute
