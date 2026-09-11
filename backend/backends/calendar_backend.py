"""Calendar backend interface (CLAUDE.md §4.2 pattern, `wf2_scheduling_design.md §K`).

The current interactive WF2 deployment uses Google Calendar, but it is never part of the
evaluated core (CLAUDE.md §3.4: evaluation always injects a mock). `execute_scheduling`
calls whichever backend `config.CALENDAR_BACKEND` selects; ``mock`` remains the safe code
fallback for a checkout without local configuration.

Safety-by-construction, not by convention: ``book()`` never sets an ``attendees`` field, so
no real email address is ever notified — "Bob"/"Chen" are secondary calendars owned by one
throwaway account (see the setup script + `secrets/google_calendars.json`), not real invited
people. ``book()`` must never raise: a live-API hiccup must not affect the local booking the
human already approved, which is why every implementation returns a status dict instead of
propagating exceptions.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CalendarBackend(ABC):
    """Books a locally-approved event onto a calendar. Never raises."""

    @abstractmethod
    def book(self, event: dict[str, Any], participant_ids: list[str]) -> dict[str, Any]:
        """Returns ``{"status": "booked", "html_link": ...}``,
        ``{"status": "skipped"}`` (nothing to do), or ``{"status": "error", "error": ...}``."""
        ...

    def update(self, event: dict[str, Any], participant_ids: list[str]) -> dict[str, Any]:
        """Update a previously synced event. Backends without lifecycle support skip."""
        return {"status": "skipped"}

    def cancel(self, event: dict[str, Any], participant_ids: list[str]) -> dict[str, Any]:
        """Cancel a previously synced event. Backends without lifecycle support skip."""
        return {"status": "skipped"}


class MockCalendarBackend(CalendarBackend):
    """Offline/test behaviour: the local `RecordStore` write and `.ics` are the effect."""

    def book(self, event: dict[str, Any], participant_ids: list[str]) -> dict[str, Any]:
        return {"status": "skipped"}


class GoogleCalendarBackend(CalendarBackend):
    """Writes one event per mapped participant onto their (throwaway-account-owned)
    secondary calendar. Participants with no mapping are silently skipped — not every
    synthetic person needs a real counterpart calendar.
    """

    def __init__(self, *, token_path: str, client_secret_path: str, calendars_path: str):
        self._token_path = token_path
        self._client_secret_path = client_secret_path
        self._calendars_path = calendars_path
        self._service = None
        self._calendar_ids: dict[str, str] = {}

    def _ensure_loaded(self) -> None:
        if self._service is not None:
            return
        import json

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        with open(self._calendars_path, encoding="utf-8") as f:
            self._calendar_ids = json.load(f)

        creds = Credentials.from_authorized_user_file(self._token_path)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        self._service = build("calendar", "v3", credentials=creds)

    def book(self, event: dict[str, Any], participant_ids: list[str]) -> dict[str, Any]:
        try:
            self._ensure_loaded()
        except FileNotFoundError as e:
            return {"status": "error",
                    "error": f"missing credential file ({e.filename}) — run "
                             "`python -m backend.scripts.google_auth_setup`"}
        except Exception as e:  # noqa: BLE001 — surface any auth/token problem, never raise
            return {"status": "error",
                    "error": f"Google auth failed ({type(e).__name__}: {e}) — the token may "
                             "have expired (unverified-app tokens expire after 7 days); "
                             "re-run `python -m backend.scripts.google_auth_setup`"}

        date, start, end = event.get("date"), event.get("start"), event.get("end")
        if not (date and start and end):
            return {"status": "skipped"}  # nothing bookable yet (missing slot)

        body = self._event_body(event)
        targets = [
            (person_id, self._calendar_ids[person_id])
            for person_id in dict.fromkeys(participant_ids)
            if person_id in self._calendar_ids
        ]
        if not targets:
            return {"status": "skipped"}  # no participant has a mapped real calendar

        try:
            provider_events = {}
            for person_id, calendar_id in targets:
                created = self._service.events().insert(
                    calendarId=calendar_id, body=body).execute()
                provider_events[person_id] = {
                    "calendar_id": calendar_id,
                    "event_id": created.get("id"),
                    "html_link": created.get("htmlLink"),
                }
            first = next(iter(provider_events.values()))
            return {
                "status": "booked",
                "html_link": first.get("html_link"),
                "provider_events": provider_events,
            }
        except Exception as e:  # noqa: BLE001 — provider errors vary; never raise past here
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}

    @staticmethod
    def _event_body(event: dict[str, Any]) -> dict[str, Any]:
        date, start, end = event.get("date"), event.get("start"), event.get("end")
        return {
            "summary": event.get("title") or "Meeting",
            "location": event.get("location") or "",
            "description": event.get("agenda") or "",
            "start": {"dateTime": f"{date}T{start}:00", "timeZone": "Europe/London"},
            "end": {"dateTime": f"{date}T{end}:00", "timeZone": "Europe/London"},
            # deliberately NO "attendees" key: nobody outside the throwaway account is ever
            # emailed, real or fictional — see the module docstring.
        }

    def update(self, event: dict[str, Any], participant_ids: list[str]) -> dict[str, Any]:
        try:
            self._ensure_loaded()
            previous = ((event.get("calendar_sync") or {}).get("provider_events") or {})
            current_ids = [
                person_id for person_id in dict.fromkeys(participant_ids)
                if person_id in self._calendar_ids
            ]
            provider_events = {}
            body = self._event_body(event)

            # Remove calendars that are no longer participants.
            for person_id, remote in previous.items():
                if person_id not in current_ids and remote.get("event_id"):
                    self._service.events().delete(
                        calendarId=remote["calendar_id"], eventId=remote["event_id"]
                    ).execute()

            for person_id in current_ids:
                remote = previous.get(person_id) or {}
                calendar_id = self._calendar_ids[person_id]
                if remote.get("event_id"):
                    changed = self._service.events().update(
                        calendarId=calendar_id, eventId=remote["event_id"], body=body
                    ).execute()
                else:
                    changed = self._service.events().insert(
                        calendarId=calendar_id, body=body
                    ).execute()
                provider_events[person_id] = {
                    "calendar_id": calendar_id,
                    "event_id": changed.get("id"),
                    "html_link": changed.get("htmlLink"),
                }
            if not provider_events:
                return {"status": "skipped"}
            first = next(iter(provider_events.values()))
            return {
                "status": "updated",
                "html_link": first.get("html_link"),
                "provider_events": provider_events,
            }
        except Exception as e:  # noqa: BLE001 — provider errors vary; never raise past here
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}

    def cancel(self, event: dict[str, Any], participant_ids: list[str]) -> dict[str, Any]:
        try:
            self._ensure_loaded()
            previous = ((event.get("calendar_sync") or {}).get("provider_events") or {})
            if not previous:
                return {"status": "skipped"}
            for remote in previous.values():
                if remote.get("event_id"):
                    self._service.events().delete(
                        calendarId=remote["calendar_id"], eventId=remote["event_id"]
                    ).execute()
            return {"status": "cancelled", "provider_events": {}}
        except Exception as e:  # noqa: BLE001 — provider errors vary; never raise past here
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}


def get_calendar_backend() -> CalendarBackend:
    """Select the interactive backend named by ``config.CALENDAR_BACKEND``."""
    from .. import config

    if config.CALENDAR_BACKEND == "google":
        return GoogleCalendarBackend(
            token_path=config.GOOGLE_TOKEN_PATH,
            client_secret_path=config.GOOGLE_CLIENT_SECRET_PATH,
            calendars_path=config.GOOGLE_CALENDARS_PATH,
        )
    return MockCalendarBackend()
