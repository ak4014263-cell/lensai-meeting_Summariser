"""Background Google Calendar automated sync & bot auto-join daemon.

Continuously monitors connected Google Calendars:
- Detects upcoming meetings with Google Meet, Zoom, or Teams links.
- Evaluates meeting start times.
- Automatically launches the bot ~2 minutes before each meeting begins.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from dateutil import parser as dt_parser

from .. import database, models
from ..config import settings
from ..models import MeetingStatus
from .bot_manager import bot_manager
from .google_oauth import load_credentials

logger = logging.getLogger("app.calendar_worker")


class CalendarWorker:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._dispatched_event_ids: set[str] = set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="LensAICalendarWorker",
            daemon=True,
        )
        self._thread.start()
        print("[calendar_worker] Started Google Calendar automated bot scheduler daemon.")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        print("[calendar_worker] Stopped Google Calendar automated bot scheduler daemon.")

    def _run_loop(self) -> None:
        # Initial brief pause to let server startup settle
        time.sleep(5)
        while not self._stop_event.is_set():
            try:
                self.sync_and_dispatch()
            except Exception as exc:
                print(f"[calendar_worker] Error during sync sweep: {exc}")

            # Sleep 60 seconds between sweeps
            for _ in range(60):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def sync_and_dispatch(self) -> List[Dict[str, Any]]:
        """Sweep connected calendars, schedule upcoming meetings, and dispatch bots."""
        db = database.SessionLocal()
        dispatched: List[Dict[str, Any]] = []
        try:
            connected_creds = (
                db.query(models.GoogleCredential)
                .filter(models.GoogleCredential.refresh_token.isnot(None))
                .all()
            )

            now = datetime.now(timezone.utc)

            for cred_row in connected_creds:
                user_id = cred_row.user_id
                try:
                    creds = load_credentials(db, user_id)
                    if not creds:
                        continue

                    from Lensai_Bot.calendar.google_calendar import GoogleCalendarClient

                    client = GoogleCalendarClient(creds)
                    events = client.get_upcoming_events(hours_ahead=24)

                    for ev in events:
                        meet_url = ev.get("meeting_url")
                        if not meet_url:
                            continue

                        event_id = str(ev.get("id"))
                        start_raw = ev.get("start")
                        if not start_raw:
                            continue

                        try:
                            start_dt = dt_parser.parse(start_raw)
                            if not start_dt.tzinfo:
                                start_dt = start_dt.replace(tzinfo=timezone.utc)
                        except Exception:
                            continue

                        # Check if meeting is starting soon or currently in progress:
                        # (from 30 mins ago up to 5 mins in future)
                        diff_seconds = (start_dt - now).total_seconds()
                        is_due = -1800 <= diff_seconds <= 300

                        if not is_due:
                            continue

                        # Check if already dispatched in this worker run
                        if event_id in self._dispatched_event_ids:
                            continue

                        # Check if a meeting row already exists in DB for this meet_url
                        existing = (
                            db.query(models.Meeting)
                            .filter(
                                models.Meeting.owner_id == user_id,
                                models.Meeting.meet_url == meet_url,
                            )
                            .first()
                        )

                        if existing:
                            if existing.status == MeetingStatus.BOT_QUEUED:
                                # Meeting was scheduled ahead of time and is now due! Dispatch it!
                                print(f"[calendar_worker] Launching queued bot for meeting {existing.id} ({meet_url})")
                                started, msg = bot_manager.start(existing.id, meet_url)
                                if not started:
                                    existing.status = MeetingStatus.BOT_FAILED
                                    existing.error_message = msg
                                    db.commit()
                                else:
                                    self._dispatched_event_ids.add(event_id)
                                    dispatched.append({"meeting_id": existing.id, "title": existing.title, "url": meet_url})
                                    db.add(
                                        models.MeetingEvent(
                                            meeting_id=existing.id,
                                            message=f"Calendar Scheduler: Meeting time reached. Bot dispatched into {meet_url}.",
                                        )
                                    )
                                    db.commit()
                            else:
                                self._dispatched_event_ids.add(event_id)
                            continue

                        # Automatically create meeting & launch the bot!
                        title = ev.get("summary") or "Calendar Meeting"
                        print(
                            f"[calendar_worker] Auto-dispatching bot for calendar event '{title}' ({meet_url})"
                        )

                        meeting = models.Meeting(
                            title=title,
                            owner_id=user_id,
                            status=MeetingStatus.BOT_QUEUED,
                            source="calendar",
                            meet_url=meet_url,
                            platform=ev.get("platform", "google_meet"),
                        )
                        db.add(meeting)
                        db.commit()
                        db.refresh(meeting)

                        db.add(
                            models.MeetingEvent(
                                meeting_id=meeting.id,
                                message=f"Calendar Scheduler: Auto-detected upcoming meeting '{title}'. Launching bot...",
                            )
                        )
                        db.commit()

                        started, msg = bot_manager.start(meeting.id, meet_url)
                        if not started:
                            meeting.status = MeetingStatus.BOT_FAILED
                            meeting.error_message = msg
                            db.commit()
                        else:
                            self._dispatched_event_ids.add(event_id)
                            dispatched.append({"meeting_id": meeting.id, "title": title, "url": meet_url})
                            db.add(
                                models.MeetingEvent(
                                    meeting_id=meeting.id,
                                    message=f"Bot successfully dispatched into {meet_url}.",
                                )
                            )
                            db.commit()

                except Exception as user_exc:
                    logger.debug(f"Calendar check failed for user {user_id}: {user_exc}")

            # Also sweep any standalone BOT_QUEUED meetings in the DB that are now due
            queued_meetings = (
                db.query(models.Meeting)
                .filter(
                    models.Meeting.status == MeetingStatus.BOT_QUEUED,
                    models.Meeting.meet_url.isnot(None),
                )
                .all()
            )
            for qm in queued_meetings:
                m_date = qm.date
                if not m_date:
                    print(f"[calendar_worker] Launching queued bot without date for meeting {qm.id} ({qm.meet_url})")
                    started, msg = bot_manager.start(qm.id, qm.meet_url)
                    if not started:
                        qm.status = MeetingStatus.BOT_FAILED
                        qm.error_message = msg
                    else:
                        dispatched.append({"meeting_id": qm.id, "title": qm.title, "url": qm.meet_url})
                        db.add(
                            models.MeetingEvent(
                                meeting_id=qm.id,
                                message=f"Calendar Scheduler: Bot dispatched into {qm.meet_url}.",
                            )
                        )
                    db.commit()
                    continue

                if not m_date.tzinfo:
                    m_date = m_date.replace(tzinfo=timezone.utc)
                diff_sec = (m_date - now).total_seconds()
                if -1800 <= diff_sec <= 300:
                    print(f"[calendar_worker] Launching standalone queued bot for meeting {qm.id} ({qm.meet_url})")
                    started, msg = bot_manager.start(qm.id, qm.meet_url)
                    if not started:
                        qm.status = MeetingStatus.BOT_FAILED
                        qm.error_message = msg
                        db.commit()
                    else:
                        dispatched.append({"meeting_id": qm.id, "title": qm.title, "url": qm.meet_url})
                        db.add(
                            models.MeetingEvent(
                                meeting_id=qm.id,
                                message=f"Calendar Scheduler: Start time reached. Bot dispatched into {qm.meet_url}.",
                            )
                        )
                        db.commit()
        finally:
            db.close()

        return dispatched

    def schedule_all_upcoming_meetings(self, user_id: int, hours_ahead: int = 168) -> List[Dict[str, Any]]:
        """Schedule bots for ALL upcoming meetings (called when user first syncs calendar)."""
        db = database.SessionLocal()
        scheduled: List[Dict[str, Any]] = []
        
        try:
            creds = load_credentials(db, user_id)
            if not creds:
                return scheduled

            from Lensai_Bot.calendar.google_calendar import GoogleCalendarClient

            client = GoogleCalendarClient(creds)
            events = client.get_upcoming_events(hours_ahead=hours_ahead)  # Next 7 days by default

            now = datetime.now(timezone.utc)

            for ev in events:
                meet_url = ev.get("meeting_url")
                if not meet_url:
                    continue

                start_raw = ev.get("start")
                if not start_raw:
                    continue

                try:
                    start_dt = dt_parser.parse(start_raw)
                    if not start_dt.tzinfo:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                # Only schedule future meetings (skip past meetings)
                if start_dt < now:
                    continue

                # Check if a meeting already exists for this URL
                existing = (
                    db.query(models.Meeting)
                    .filter(
                        models.Meeting.owner_id == user_id,
                        models.Meeting.meet_url == meet_url,
                    )
                    .first()
                )

                if existing:
                    # Update existing meeting to BOT_QUEUED if not already running
                    if existing.status in [MeetingStatus.CREATED, MeetingStatus.BOT_FAILED]:
                        existing.status = MeetingStatus.BOT_QUEUED
                        existing.date = start_dt
                        db.commit()
                        scheduled.append({
                            "meeting_id": existing.id,
                            "title": existing.title,
                            "url": meet_url,
                            "start_time": start_dt.isoformat(),
                            "action": "updated"
                        })
                    continue

                # Create new meeting and queue the bot
                title = ev.get("summary") or "Calendar Meeting"
                print(f"[calendar_worker] Scheduling bot for upcoming meeting '{title}' at {start_dt}")

                meeting = models.Meeting(
                    title=title,
                    owner_id=user_id,
                    date=start_dt,
                    status=MeetingStatus.BOT_QUEUED,
                    source="calendar",
                    meet_url=meet_url,
                    platform=ev.get("platform", "google_meet"),
                )
                db.add(meeting)
                db.commit()
                db.refresh(meeting)

                db.add(
                    models.MeetingEvent(
                        meeting_id=meeting.id,
                        message=f"Auto-scheduled from calendar sync: '{title}' starting at {start_dt.strftime('%Y-%m-%d %H:%M')}",
                    )
                )
                db.commit()

                scheduled.append({
                    "meeting_id": meeting.id,
                    "title": title,
                    "url": meet_url,
                    "start_time": start_dt.isoformat(),
                    "action": "created"
                })

            print(f"[calendar_worker] Scheduled {len(scheduled)} upcoming meetings for user {user_id}")

        except Exception as exc:
            print(f"[calendar_worker] Error scheduling upcoming meetings for user {user_id}: {exc}")
        finally:
            db.close()

        return scheduled


calendar_worker = CalendarWorker()
