"""Google Calendar API integration .

Syncs upcoming meetings, extracts Google Meet / Zoom / Teams links, and creates
calendar events with meeting URLs.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("lensai_bot.calendar.google")

MEETING_LINK_PATTERNS = [
    re.compile(r"https?://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}", re.I),
    re.compile(r"https?://[a-zA-Z0-9.\-_]*zoom\.us/j/[0-9]+[^\s\"'<>]*", re.I),
    re.compile(r"https?://teams\.microsoft\.com/l/meetup-join/[^\s\"'<>]+", re.I),
]


def extract_meeting_url(event: Dict[str, Any]) -> Optional[str]:
    """Extract meeting link from hangoutLink, conferenceData, location, or description."""
    # 1. Direct Google Meet link
    if event.get("hangoutLink"):
        return event["hangoutLink"]

    # 2. ConferenceData entryPoints
    conf = event.get("conferenceData") or {}
    for entry in conf.get("entryPoints", []):
        uri = entry.get("uri")
        if uri:
            return uri

    # 3. Scan location and description text
    text_to_scan = f"{event.get('location', '')} {event.get('description', '')}"
    for pat in MEETING_LINK_PATTERNS:
        match = pat.search(text_to_scan)
        if match:
            return match.group(0)

    return None


class GoogleCalendarClient:
    """Client for Google Calendar API."""

    def __init__(self, credentials: Any):
        self.credentials = credentials
        self._service = None

    @property
    def service(self):
        if self._service is None:
            from googleapiclient.discovery import build
            self._service = build("calendar", "v3", credentials=self.credentials)
        return self._service

    def get_upcoming_events(
        self,
        calendar_id: str = "primary",
        hours_ahead: int = 48,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """Fetch upcoming events and extract video call links."""
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(hours=hours_ahead)).isoformat()

        events_result = (
            self.service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=max_results,
            )
            .execute()
        )

        items = events_result.get("items", [])
        normalized = []

        for item in items:
            meet_url = extract_meeting_url(item)
            start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
            end = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")

            normalized.append({
                "id": item.get("id"),
                "summary": item.get("summary") or "Untitled Meeting",
                "description": item.get("description", ""),
                "start": start,
                "end": end,
                "meeting_url": meet_url,
                "organizer": item.get("organizer", {}),
                "attendees": item.get("attendees", []),
                "has_video_link": bool(meet_url),
                "platform": "google_meet" if meet_url and "meet.google.com" in meet_url else (
                    "zoom" if meet_url and "zoom.us" in meet_url else (
                        "teams" if meet_url and "teams" in meet_url else "other"
                    )
                ),
            })

        return normalized

    def create_meeting_event(
        self,
        summary: str,
        start_dt: datetime,
        duration_minutes: int = 30,
        description: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        send_updates: str = "all",
        auto_accept: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a Google Calendar event with auto-generated Google Meet link.

        ``send_updates`` maps to the API's ``sendUpdates`` parameter and controls
        whether Google emails the guests. It must be passed explicitly: the API
        default is ``"none"``, so omitting it creates the event silently and no
        invitation is ever delivered. Accepted values are ``"all"``,
        ``"externalOnly"`` and ``"none"``.

        ``auto_accept`` lists attendee addresses to RSVP as accepted on their
        behalf. Google only auto-adds an invitation to a guest's calendar when
        the sender is already known to them, so an unattended account such as
        the recorder bot would otherwise see "Unknown sender: not added to
        calendar yet" and the event would never appear. Presetting the RSVP is
        Google's documented way to put the event straight onto their calendar
        regardless of that setting, and it also helps Meet admit the bot instead
        of parking it in the waiting room.

        The event always lands on the organizer's own calendar, because it is
        inserted into their ``primary`` calendar.
        """
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        accept_set = {e.strip().lower() for e in (auto_accept or []) if e and e.strip()}
        attendee_entries: List[Dict[str, Any]] = []
        for raw in attendees or []:
            email = (raw or "").strip()
            if not email:
                continue
            entry: Dict[str, Any] = {"email": email}
            if email.lower() in accept_set:
                entry["responseStatus"] = "accepted"
            attendee_entries.append(entry)

        body: Dict[str, Any] = {
            "summary": summary,
            "description": description or "Scheduled via LensAI Meeting Assistant",
            "start": {"dateTime": start_dt.isoformat()},
            "end": {"dateTime": end_dt.isoformat()},
            "attendees": attendee_entries,
            "conferenceData": {
                "createRequest": {
                    "requestId": f"lensai-{int(datetime.now().timestamp())}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }

        if send_updates not in ("all", "externalOnly", "none"):
            send_updates = "all"

        created = (
            self.service.events()
            .insert(
                calendarId="primary",
                body=body,
                conferenceDataVersion=1,
                sendUpdates=send_updates,
            )
            .execute()
        )

        meet_url = created.get("hangoutLink") or extract_meeting_url(created)
        created_attendees = created.get("attendees", []) or []
        return {
            "id": created.get("id"),
            "summary": created.get("summary"),
            "meeting_url": meet_url,
            "start": created.get("start", {}).get("dateTime") or created.get("start", {}).get("date"),
            "html_link": created.get("htmlLink"),
            "organizer": created.get("organizer", {}),
            "attendees": created_attendees,
            # Who Google recorded as already attending, so callers can confirm
            # the event will show on that guest's calendar rather than sitting
            # unacknowledged in their inbox.
            "accepted_attendees": [
                a.get("email")
                for a in created_attendees
                if a.get("responseStatus") == "accepted" and a.get("email")
            ],
            "send_updates": send_updates,
        }
