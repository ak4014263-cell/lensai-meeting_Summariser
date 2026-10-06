"""Google account connection + Google Meet REST API import endpoints.

Two groups of routes:

  /integrations/google/...        connect / status / disconnect (OAuth)
  /integrations/google/meet/...   list conference records, import a transcript

The import path reuses the same summarisation pipeline the bot uses, so a
meeting imported from Google looks identical in the UI to a bot-recorded one.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import database, models
from ..ai import google_oauth
from ..auth.router import get_current_user
from ..config import settings
from ..models import MeetingStatus

import logging
logger = logging.getLogger("app.integrations")

router = APIRouter(prefix="/integrations/google", tags=["integrations"])


# ─────────────────────────────── OAuth ───────────────────────────────────

@router.get("/status")
def google_status(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    return google_oauth.connection_status(db, current_user.id)


@router.get("/authorize")
def google_authorize(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Return the Google consent URL for the frontend to redirect to."""
    if not settings.google_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "Google OAuth is not configured on the server. Add a Google "
                "Cloud OAuth client (see docs/GOOGLE_MEET_API.md)."
            ),
        )
    try:
        return {"authorization_url": google_oauth.authorization_url(current_user.id)}
    except google_oauth.OAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/callback")
def google_callback(
    request: Request,
    state: str = Query(...),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(database.get_db),
):
    """Google redirects the browser here. Exchange the code, then bounce back
    to the frontend settings page with a status flag.
    """
    settings_url = f"{settings.FRONTEND_BASE_URL}/dashboard/settings"

    if error:
        return RedirectResponse(f"{settings_url}?google=error&reason={error}")

    try:
        cred = google_oauth.handle_callback(db, str(request.url), state)
        
        # Auto-schedule bots for all upcoming meetings when user first connects calendar
        try:
            from ..ai.calendar_worker import calendar_worker
            scheduled = calendar_worker.schedule_all_upcoming_meetings(cred.user_id, hours_ahead=168)
            print(f"[google_callback] Auto-scheduled {len(scheduled)} upcoming meetings for user {cred.user_id}")
        except Exception as schedule_exc:
            print(f"[google_callback] Warning: Failed to auto-schedule meetings: {schedule_exc}")
            # Don't fail the OAuth flow if scheduling fails
            
    except google_oauth.OAuthError as exc:
        return RedirectResponse(f"{settings_url}?google=error&reason={exc}")
    except Exception as exc:  # pragma: no cover - surface any exchange failure
        return RedirectResponse(f"{settings_url}?google=error&reason={exc}")

    email = cred.google_email or "google"
    return RedirectResponse(f"{settings_url}?google=connected&email={email}")


@router.post("/disconnect")
def google_disconnect(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    google_oauth.disconnect(db, current_user.id)
    return {"message": "Google account disconnected."}


# ─────────────────────────── Meet REST API ───────────────────────────────

class ConferenceSummary(BaseModel):
    conference_record: str
    space: str | None = None
    start_time: str | None = None
    end_time: str | None = None


class ImportRequest(BaseModel):
    conference_record: str
    title: str | None = None


class CreateMeetRequest(BaseModel):
    title: str | None = None
    # OPEN lets the bot (and anyone with the link) join without a waiting-room
    # admit. Use TRUSTED/RESTRICTED to require knocking.
    access_type: str = "OPEN"
    # Immediately dispatch the recording bot into the new meeting.
    send_bot: bool = True


def _require_credentials(db: Session, user_id: int):
    try:
        creds = google_oauth.load_credentials(db, user_id)
    except google_oauth.OAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    if creds is None:
        raise HTTPException(
            status_code=409,
            detail="Connect your Google account first.",
        )
    return creds


@router.post("/meet/create")
def create_meeting_space(
    payload: CreateMeetRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Create a Google Meet via the REST API and optionally send the bot in.

    Returns the meeting link so the user can join and talk. With access_type
    OPEN the bot joins directly, with no manual admit.
    """
    creds = _require_credentials(db, current_user.id)
    from ..ai import meet_api

    try:
        space = meet_api.create_space(creds, access_type=payload.access_type)
    except meet_api.MeetApiError as exc:
        # Almost always: the connected account lacks the create scope.
        raise HTTPException(
            status_code=502,
            detail=(
                f"{exc}. If this mentions scope/permission, disconnect and "
                "reconnect your Google account so the new 'create meeting' "
                "permission is granted."
            ),
        )

    meeting_uri = space.get("meeting_uri")
    if not meeting_uri:
        raise HTTPException(status_code=502, detail="Google did not return a meeting link.")

    # The hosted Meeting BaaS bot is the single capture layer, so a created
    # meeting is recorded the same reliable way as a pasted link.
    use_hosted = False

    meeting = models.Meeting(
        title=(payload.title or "").strip() or f"Meet {space.get('meeting_code') or ''}".strip(),
        owner_id=current_user.id,
        status=MeetingStatus.BOT_QUEUED if payload.send_bot else MeetingStatus.CREATED,
        source="bot" if payload.send_bot else "meet_api",
        platform="google_meet",
        meet_url=meeting_uri,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    db.add(
        models.MeetingEvent(
            meeting_id=meeting.id,
            message=(
                f"Created Google Meet {meeting_uri} "
                f"(access: {space.get('access_type')})."
            ),
        )
    )
    db.commit()

    dispatched = False
    if payload.send_bot:
        from ..ai.bot_manager import bot_manager

        started, message = bot_manager.start(meeting.id, meeting_uri)

        dispatched = started
        if not started:
            meeting.status = MeetingStatus.BOT_FAILED
            meeting.error_message = message
            db.commit()
        else:
            db.add(models.MeetingEvent(meeting_id=meeting.id, message="Bot dispatched to the new meeting."))
            db.commit()

    return {
        "id": meeting.id,
        "title": meeting.title,
        "status": meeting.status,
        "meeting_uri": meeting_uri,
        "meeting_code": space.get("meeting_code"),
        "space": space.get("name"),
        "access_type": space.get("access_type"),
        "bot_dispatched": dispatched,
    }


@router.get("/meet/conferences", response_model=list[ConferenceSummary])
def list_conferences(
    space: str | None = Query(default=None, description="Optional spaces/{id} filter"),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """List the caller's recent Google Meet conference records."""
    creds = _require_credentials(db, current_user.id)
    from ..ai import meet_api

    try:
        records = meet_api.list_conference_records(creds, space_name=space)
    except meet_api.MeetApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Google Meet API error: {exc}")

    return [
        ConferenceSummary(
            conference_record=r.get("name", ""),
            space=r.get("space"),
            start_time=r.get("startTime"),
            end_time=r.get("endTime"),
        )
        for r in records
        if r.get("name")
    ]


@router.post("/meet/import")
def import_conference(
    payload: ImportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Create a meeting from a finished Google Meet conference and summarise it."""
    _require_credentials(db, current_user.id)  # fail fast if not connected

    record = payload.conference_record.strip()
    if not record.startswith("conferenceRecords/"):
        raise HTTPException(
            status_code=400,
            detail="conference_record must look like 'conferenceRecords/...'",
        )

    meeting = models.Meeting(
        title=(payload.title or "").strip() or f"Google Meet {record.split('/')[-1][:12]}",
        owner_id=current_user.id,
        status=MeetingStatus.PROCESSING_AUDIO,
        source="meet_api",
        platform="google_meet",
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    db.add(
        models.MeetingEvent(
            meeting_id=meeting.id,
            message=f"Importing transcript from {record} via the Google Meet API.",
        )
    )
    db.commit()

    background_tasks.add_task(_run_import, current_user.id, meeting.id, record)

    return {"id": meeting.id, "status": meeting.status, "title": meeting.title}


# ─────────────────────────────── calendar integration ─────────────────────

class CalendarScheduleRequest(BaseModel):
    event_id: str
    title: str
    meeting_url: str
    start_time: str | None = None


class CreateCalendarMeetingRequest(BaseModel):
    title: str
    meeting_url: str | None = None
    start_time: str | None = None
    duration_minutes: int = 30
    description: str | None = None
    attendees: list[str] | None = None
    send_bot: bool = True
    sync_google_calendar: bool = True
    immediate: bool = False


@router.get("/calendar/events")
def list_calendar_events(
    hours_ahead: int = Query(default=48, ge=1, le=168),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """List the user's upcoming Google Calendar events with meeting links & bot status."""
    creds = _require_credentials(db, current_user.id)
    from Lensai_Bot.calendar.google_calendar import GoogleCalendarClient

    client = GoogleCalendarClient(creds)
    try:
        events = client.get_upcoming_events(hours_ahead=hours_ahead)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch calendar events: {exc}. Ensure calendar permissions are granted.",
        )

    # Cross-reference with existing meetings to show bot schedule status
    user_meetings = (
        db.query(models.Meeting)
        .filter(models.Meeting.owner_id == current_user.id)
        .all()
    )
    scheduled_urls = {
        m.meet_url: m
        for m in user_meetings
        if m.meet_url
    }

    enriched = []
    for ev in events:
        m_url = ev.get("meeting_url")
        match = scheduled_urls.get(m_url) if m_url else None
        ev_copy = dict(ev)
        ev_copy["host_email"] = (ev.get("organizer") or {}).get("email") or current_user.email
        ev_copy["bot_email"] = settings.BOT_EMAIL
        if match:
            ev_copy["bot_scheduled"] = True
            ev_copy["lensai_meeting_id"] = match.id
            ev_copy["bot_status"] = match.status
        else:
            ev_copy["bot_scheduled"] = False
            ev_copy["lensai_meeting_id"] = None
            ev_copy["bot_status"] = None
        enriched.append(ev_copy)

    return {
        "events": enriched,
        "host_email": current_user.email,
        "bot_email": settings.BOT_EMAIL,
    }


@router.post("/calendar/create")
def create_calendar_meeting(
    payload: CreateCalendarMeetingRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Create a new meeting, optionally sync it to Google Calendar, and schedule the bot."""
    from datetime import datetime, timezone
    from dateutil import parser as dt_parser

    start_dt = None
    if payload.start_time:
        try:
            start_dt = dt_parser.parse(payload.start_time)
            if not start_dt.tzinfo:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
        except Exception:
            start_dt = datetime.now(timezone.utc)
    else:
        start_dt = datetime.now(timezone.utc)

    title = (payload.title or "").strip() or "Scheduled Meeting"
    calendar_synced = False
    calendar_event_id = None
    calendar_html_link = None
    calendar_error = None
    calendar_needs_reconnect = False
    bot_on_calendar = False
    invites_sent_to: list[str] = []
    meet_url = (payload.meeting_url or "").strip() or None

    creds = google_oauth.load_credentials(db, current_user.id)

    # Guests the organizer asked for, excluding the bot (which is added below as
    # an attendee purely so Meet admits it, not as a human invitee).
    guest_emails = [
        e.strip()
        for e in (payload.attendees or [])
        if e and e.strip() and e.strip().lower() != (settings.BOT_EMAIL or "").lower()
    ]

    # 1. If syncing to Google Calendar and user has Google credentials:
    if payload.sync_google_calendar and creds:
        from Lensai_Bot.calendar.google_calendar import GoogleCalendarClient

        client = GoogleCalendarClient(creds)
        attendees = list(guest_emails)
        # Include the bot's email so Meet treats it as an invited guest
        if settings.BOT_EMAIL and settings.BOT_EMAIL not in attendees:
            attendees.append(settings.BOT_EMAIL)

        try:
            cal_res = client.create_meeting_event(
                summary=title,
                start_dt=start_dt,
                duration_minutes=payload.duration_minutes,
                description=payload.description,
                attendees=attendees,
                # Without this Google creates the event but emails nobody.
                send_updates=settings.CALENDAR_SEND_INVITES,
                # RSVP for the bot so the event lands on its calendar even
                # though it has never interacted with this organizer.
                auto_accept=[settings.BOT_EMAIL] if settings.BOT_EMAIL else None,
            )
            calendar_synced = True
            calendar_event_id = cal_res.get("id")
            calendar_html_link = cal_res.get("html_link")
            bot_on_calendar = settings.BOT_EMAIL in (cal_res.get("accepted_attendees") or [])
            if settings.CALENDAR_SEND_INVITES != "none":
                invites_sent_to = guest_emails
            if not meet_url:
                meet_url = cal_res.get("meeting_url")
        except Exception as exc:
            # Fallback if calendar write scope is missing or fails:
            # Create a Meet space directly via the Meet API
            raw = str(exc)
            if "insufficient" in raw.lower() or "insufficientPermissions" in raw:
                # The stored token predates the calendar.events write scope, so
                # a reconnect (which forces re-consent) is the only fix.
                calendar_error = (
                    "Your Google account is connected but has not granted "
                    "permission to create calendar events, so the meeting was "
                    "not added to Google Calendar and no invitations were "
                    "emailed. Reconnect Google in Settings and approve the "
                    "Calendar permission."
                )
                calendar_needs_reconnect = True
            else:
                calendar_error = raw[:500]
            logger.warning(f"Google Calendar event insert failed: {exc}. Falling back to Meet space API.")
    elif payload.sync_google_calendar and not creds:
        calendar_error = (
            "Google account is not connected, so no calendar event was created "
            "and no invitations were emailed."
        )

    # 2. If no meet_url yet, generate a Meet space via Meet API
    if not meet_url and creds:
        from ..ai import meet_api
        try:
            space = meet_api.create_space(creds, access_type="OPEN")
            meet_url = space.get("meeting_uri")
        except Exception as meet_exc:
            logger.warning(f"Google Meet create_space fallback failed: {meet_exc}")

    # If the user wants the bot to join but no meeting URL is known and cannot be generated:
    if payload.send_bot and not meet_url:
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not generate a meeting link because Google account is not connected. "
                "Please connect Google in Settings or provide a meeting URL directly."
            ),
        )

    # Create meeting record in SQLite
    meeting = models.Meeting(
        title=title,
        owner_id=current_user.id,
        date=start_dt,
        status=MeetingStatus.BOT_QUEUED if payload.send_bot else MeetingStatus.CREATED,
        source="bot" if payload.send_bot else ("calendar" if calendar_synced else "other"),
        meet_url=meet_url,
        platform="google_meet" if meet_url and "meet.google.com" in meet_url else "other",
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    db.add(
        models.MeetingEvent(
            meeting_id=meeting.id,
            message=(
                f"Generated meeting '{title}' scheduled for {start_dt.isoformat()}. "
                f"{'Synced to Google Calendar. ' if calendar_synced else ''}"
                f"{f'Link: {meet_url}. ' if meet_url else ''}"
                f"{'LensAI Bot auto-join scheduled.' if payload.send_bot else ''}"
            ),
        )
    )
    if calendar_synced:
        db.add(
            models.MeetingEvent(
                meeting_id=meeting.id,
                message=(
                    f"Calendar event created on {current_user.email}'s calendar"
                    + (
                        f" and RSVP'd on the bot's calendar ({settings.BOT_EMAIL})."
                        if bot_on_calendar
                        else f". The bot ({settings.BOT_EMAIL}) was invited but "
                        "Google did not confirm the RSVP, so it may only appear "
                        "once the invitation is accepted."
                    )
                ),
                level="info" if bot_on_calendar else "warning",
            )
        )
    if invites_sent_to:
        db.add(
            models.MeetingEvent(
                meeting_id=meeting.id,
                message=(
                    f"Google emailed calendar invitations to "
                    f"{len(invites_sent_to)} guest(s): {', '.join(invites_sent_to)}."
                ),
            )
        )
    elif calendar_synced and guest_emails and settings.CALENDAR_SEND_INVITES == "none":
        db.add(
            models.MeetingEvent(
                meeting_id=meeting.id,
                message=(
                    "Calendar event created but invitations were not emailed "
                    "(CALENDAR_SEND_INVITES=none)."
                ),
                level="warning",
            )
        )
    elif calendar_synced and not guest_emails:
        db.add(
            models.MeetingEvent(
                meeting_id=meeting.id,
                message=(
                    "Calendar event created with no guests, so no invitation "
                    "emails were sent. Add attendee addresses to invite people."
                ),
                level="warning",
            )
        )
    if calendar_error:
        db.add(
            models.MeetingEvent(
                meeting_id=meeting.id,
                message=f"Google Calendar sync failed: {calendar_error}",
                level="warning",
            )
        )
    db.commit()

    # 3. Check if meeting is due immediately or forced immediate
    dispatched_now = False
    now = datetime.now(timezone.utc)
    diff_sec = (start_dt - now).total_seconds()
    if payload.send_bot and meet_url and (payload.immediate or diff_sec <= 300):
        from ..ai.bot_manager import bot_manager
        started, msg = bot_manager.start(meeting.id, meet_url)
        if started:
            dispatched_now = True
            db.add(models.MeetingEvent(meeting_id=meeting.id, message="Bot dispatched immediately to meeting."))
            db.commit()
        else:
            meeting.status = MeetingStatus.BOT_FAILED
            meeting.error_message = msg
            db.commit()

    return {
        "id": meeting.id,
        "title": meeting.title,
        "status": meeting.status,
        "meet_url": meet_url,
        "start_time": start_dt.isoformat(),
        "calendar_synced": calendar_synced,
        "calendar_event_id": calendar_event_id,
        "calendar_html_link": calendar_html_link,
        "calendar_error": calendar_error,
        "calendar_needs_reconnect": calendar_needs_reconnect,
        # Which calendars the event was placed on.
        "on_host_calendar": calendar_synced,
        "on_bot_calendar": bot_on_calendar,
        "dispatched_now": dispatched_now,
        # Guests Google was asked to email (the bot is excluded).
        "invites_sent_to": invites_sent_to,
        "invites_sent": len(invites_sent_to),
        "host_email": current_user.email,
        "bot_email": settings.BOT_EMAIL,
    }


@router.post("/calendar/sync-now")
def sync_calendar_now(
    schedule_all: bool = False,
    current_user: models.User = Depends(get_current_user),
):
    """Trigger an immediate background sync and scheduler sweep.
    
    Args:
        schedule_all: If True, schedule bots for ALL upcoming meetings (not just immediate ones)
    """
    from ..ai.calendar_worker import calendar_worker

    if schedule_all:
        # Schedule bots for all upcoming meetings in the next 7 days
        scheduled = calendar_worker.schedule_all_upcoming_meetings(current_user.id, hours_ahead=168)
        return {
            "synced": True,
            "scheduled_count": len(scheduled),
            "scheduled": scheduled,
            "message": f"Scheduled {len(scheduled)} upcoming meetings for automatic bot recording"
        }
    else:
        # Normal dispatch - only meetings starting now
        dispatched = calendar_worker.sync_and_dispatch()
        return {"synced": True, "dispatched_count": len(dispatched), "dispatched": dispatched}


@router.post("/calendar/schedule")
def schedule_calendar_meeting(
    payload: CalendarScheduleRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Queue a bot to automatically record an existing calendar meeting."""
    url = (payload.meeting_url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="No video meeting URL provided.")

    from datetime import datetime, timezone
    from dateutil import parser as dt_parser

    start_dt = None
    if payload.start_time:
        try:
            start_dt = dt_parser.parse(payload.start_time)
            if not start_dt.tzinfo:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
        except Exception:
            start_dt = datetime.now(timezone.utc)
    else:
        start_dt = datetime.now(timezone.utc)

    # Check if a meeting with this URL already exists
    existing = (
        db.query(models.Meeting)
        .filter(
            models.Meeting.owner_id == current_user.id,
            models.Meeting.meet_url == url,
        )
        .first()
    )

    if existing:
        meeting = existing
        meeting.status = MeetingStatus.BOT_QUEUED
        meeting.date = start_dt
    else:
        meeting = models.Meeting(
            title=payload.title.strip() or "Calendar Meeting",
            owner_id=current_user.id,
            date=start_dt,
            status=MeetingStatus.BOT_QUEUED,
            source="bot",
            meet_url=url,
        )
        db.add(meeting)

    db.commit()
    db.refresh(meeting)

    db.add(
        models.MeetingEvent(
            meeting_id=meeting.id,
            message=f"Scheduled LensAI Bot for calendar meeting: {meeting.title} ({url})",
        )
    )
    db.commit()

    # If meeting starts soon (within 2 minutes), launch immediately
    now = datetime.now(timezone.utc)
    diff_sec = (start_dt - now).total_seconds()
    if diff_sec <= 120:
        from ..ai.bot_manager import bot_manager

        started, message = bot_manager.start(meeting.id, url)
        if not started:
            meeting.status = MeetingStatus.BOT_FAILED
            meeting.error_message = message
            db.commit()
        else:
            db.add(models.MeetingEvent(meeting_id=meeting.id, message="Bot dispatched to calendar meeting."))
            db.commit()

    return {"id": meeting.id, "status": meeting.status, "meet_url": url}


def _run_import(user_id: int, meeting_id: int, conference_record: str) -> None:
    """Background worker: load creds in a fresh session and run the pipeline."""
    from ..ai import meet_api
    from ..ai.pipeline import log_event, set_status

    db = database.SessionLocal()
    try:
        creds = google_oauth.load_credentials(db, user_id)
        if creds is None:
            meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
            if meeting:
                meeting.error_message = "Google account is no longer connected."
                set_status(db, meeting, MeetingStatus.FAILED)
            return
        meet_api.import_conference(creds, meeting_id, conference_record)
    except Exception as exc:
        import traceback

        traceback.print_exc()
        meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
        if meeting:
            meeting.error_message = str(exc)[:2000]
            set_status(db, meeting, MeetingStatus.FAILED)
        log_event(db, meeting_id, f"Import failed: {exc}", level="error")
    finally:
        db.close()
