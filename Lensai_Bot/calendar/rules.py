"""Calendar auto-join rules engine .

Determines whether an upcoming calendar event should be automatically joined:
- Record all meetings with a video call link (default)
- Record only meetings organized by the user
- Record only external meetings (with attendees outside user's domain)
- Record only meetings explicitly toggled 'ON'
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class CalendarEventRule:
    auto_record_all: bool = True
    only_with_video_link: bool = True
    only_if_organizer: bool = False
    only_external: bool = False
    ignored_titles: List[str] = None

    def is_eligible(
        self,
        event: Dict[str, Any],
        user_email: Optional[str] = None
    ) -> tuple[bool, str]:
        """Check if an event matches the auto-join criteria.
        
        Returns (eligible: bool, reason: str).
        """
        title = event.get("summary") or event.get("title") or "Untitled Meeting"
        meet_url = event.get("meeting_url") or event.get("hangoutLink")

        # 1. Ignored titles (e.g. Focus time, Out of office, Lunch)
        ignored = self.ignored_titles or ["focus time", "out of office", "lunch", "busy", "ooo"]
        if any(ign in title.lower() for ign in ignored):
            return False, f"Title matched ignored keyword list: '{title}'"

        # 2. Video link requirement
        if self.only_with_video_link and not meet_url:
            return False, "No video conference link found in event."

        # 3. Organizer check
        if self.only_if_organizer and user_email:
            organizer = event.get("organizer", {}).get("email")
            if organizer and organizer.lower() != user_email.lower():
                return False, f"User is not the organizer (organizer: {organizer})"

        # 4. External check
        if self.only_external and user_email and "@" in user_email:
            user_domain = user_email.split("@")[-1].lower()
            attendees = event.get("attendees", [])
            has_external = False
            for att in attendees:
                att_email = att.get("email", "").lower()
                if att_email and "@" in att_email:
                    if att_email.split("@")[-1] != user_domain:
                        has_external = True
                        break
            if not has_external:
                return False, "All attendees are internal to domain."

        return True, "Eligible for auto-recording."
