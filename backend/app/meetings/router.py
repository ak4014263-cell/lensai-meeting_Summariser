from __future__ import annotations

import os
from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import database, models
from ..ai.bot import meeting_code, normalise_meet_url
from ..ai.bot_manager import bot_manager
from ..ai.meetingbaas_runner import baas_manager
from ..ai.pipeline import build_transcript_text, format_timestamp
from ..auth.router import get_current_user
from ..config import settings, storage_path
from ..models import MeetingStatus

router = APIRouter(prefix="/meetings", tags=["meetings"])

ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "m4a", "mp4", "webm", "ogg", "opus", "flac", "aac"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


# ─────────────────────────────── schemas ─────────────────────────────────

class MeetingCreate(BaseModel):
    title: str


class BotJoinRequest(BaseModel):
    meet_url: str
    title: str | None = None


class BaasJoinRequest(BaseModel):
    meeting_url: str
    title: str | None = None


def _detect_platform(url: str) -> str | None:
    low = url.lower()
    if "meet.google.com" in low:
        return "google_meet"
    if "zoom.us" in low or "zoom.com" in low:
        return "zoom"
    if "teams.microsoft.com" in low or "teams.live.com" in low:
        return "teams"
    return None


class AskRequest(BaseModel):
    question: str


class SummaryResponse(BaseModel):
    executive_summary: str
    key_points: List[str] = []
    topics: List[str] = []
    risks: List[str] = []
    questions: List[str] = []
    next_steps: List[str] = []
    model: str | None = None


class DecisionResponse(BaseModel):
    text: str

    class Config:
        from_attributes = True


class ActionItemResponse(BaseModel):
    text: str
    owner: str | None = None
    deadline: str | None = None

    class Config:
        from_attributes = True


class ParticipantResponse(BaseModel):
    name: str

    class Config:
        from_attributes = True


class MeetingEventResponse(BaseModel):
    created_at: datetime
    level: str
    message: str

    class Config:
        from_attributes = True


class MeetingResponse(BaseModel):
    id: int
    title: str
    date: datetime
    status: str
    source: str | None = None
    meet_url: str | None = None
    duration_ms: int | None = None
    end_reason: str | None = None
    error_message: str | None = None
    peak_participants: int | None = None
    has_audio: bool = False
    summary: SummaryResponse | None = None
    decisions: List[DecisionResponse] = []
    action_items: List[ActionItemResponse] = []
    participants: List[ParticipantResponse] = []
    # The platform account that owns this meeting (the organizer).
    host_email: str | None = None
    # The Google account the bot joins as — a different actor from the host.
    bot_email: str | None = None


class TranscriptSegmentResponse(BaseModel):
    id: int
    start_time: int
    end_time: int
    text: str
    speaker: str | None = None
    source: str | None = None

    class Config:
        from_attributes = True


# ─────────────────────────────── helpers ─────────────────────────────────

def _lines(value: str | None) -> List[str]:
    if not value:
        return []
    return [line.strip() for line in value.splitlines() if line.strip()]


def _summary_payload(summary: models.Summary | None) -> SummaryResponse | None:
    if not summary:
        return None
    return SummaryResponse(
        executive_summary=summary.executive_summary or "",
        key_points=_lines(summary.key_points),
        topics=_lines(summary.topics),
        risks=_lines(summary.risks),
        questions=_lines(summary.questions),
        next_steps=_lines(summary.next_steps),
        model=summary.model,
    )


def _meeting_payload(meeting: models.Meeting) -> MeetingResponse:
    owner_email = meeting.owner.email if meeting.owner else None
    return MeetingResponse(
        id=meeting.id,
        title=meeting.title,
        date=meeting.date,
        status=meeting.status,
        source=meeting.source,
        meet_url=meeting.meet_url,
        duration_ms=meeting.duration_ms,
        end_reason=meeting.end_reason,
        error_message=meeting.error_message,
        peak_participants=meeting.peak_participants,
        has_audio=bool(meeting.audio_file_path and os.path.exists(meeting.audio_file_path)),
        summary=_summary_payload(meeting.summary),
        decisions=[DecisionResponse.model_validate(d) for d in meeting.decisions],
        action_items=[ActionItemResponse.model_validate(a) for a in meeting.action_items],
        participants=[ParticipantResponse.model_validate(p) for p in meeting.participants],
        host_email=owner_email,
        bot_email=settings.BOT_EMAIL,
    )


def _owned_meeting(
    meeting_id: int, db: Session, current_user: models.User
) -> models.Meeting:
    meeting = (
        db.query(models.Meeting)
        .filter(
            models.Meeting.id == meeting_id,
            models.Meeting.owner_id == current_user.id,
        )
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


# ──────────────────────────────── bot ────────────────────────────────────

@router.post("/bot", response_model=MeetingResponse)
def bot_join_meeting(
    request: BotJoinRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Send the AI bot into a Google Meet call to record and summarise it."""
    url, error = normalise_meet_url(request.meet_url)
    if error:
        raise HTTPException(status_code=400, detail=error)

    # 100% Self-Hosted Playwright Bot
    use_hosted = False

    title = (request.title or "").strip() or f"Meet {meeting_code(url)}"
    meeting = models.Meeting(
        title=title,
        owner_id=current_user.id,
        status=MeetingStatus.BOT_QUEUED,
        source="bot",
        platform="google_meet",
        meet_url=url,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    started, message = bot_manager.start(meeting.id, url)
    if not started:
        meeting.status = MeetingStatus.BOT_FAILED
        meeting.error_message = message
        db.commit()
        db.refresh(meeting)
        raise HTTPException(status_code=429, detail=message)

    db.add(
        models.MeetingEvent(
            meeting_id=meeting.id,
            message=f"Bot dispatched to {url}.",
            level="info",
        )
    )
    db.commit()
    db.refresh(meeting)
    return _meeting_payload(meeting)


@router.post("/baas", response_model=MeetingResponse)
def baas_join_meeting(
    request: BaasJoinRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Send a hosted Meeting BaaS bot into a Google Meet / Zoom / Teams call.

    More reliable than the built-in bot: the provider handles joining, waiting
    rooms, recording and transcription across all three platforms.
    """
    if not settings.meetingbaas_configured:
        raise HTTPException(
            status_code=503,
            detail="Meeting BaaS is not configured. Set MEETINGBAAS_API_KEY in backend/.env.",
        )

    url = (request.meeting_url or "").strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Provide a full meeting URL (https://...).")
    platform = _detect_platform(url)
    if not platform:
        raise HTTPException(
            status_code=400,
            detail="Unsupported link. Use a Google Meet, Zoom or Microsoft Teams URL.",
        )

    meeting = models.Meeting(
        title=(request.title or "").strip() or f"{platform.replace('_', ' ').title()} meeting",
        owner_id=current_user.id,
        status=MeetingStatus.BOT_QUEUED,
        source="meetingbaas",
        platform=platform,
        meet_url=url,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    started, message = baas_manager.start(meeting.id, url)
    if not started:
        meeting.status = MeetingStatus.BOT_FAILED
        meeting.error_message = message
        db.commit()
        db.refresh(meeting)
        raise HTTPException(status_code=409, detail=message)

    db.add(models.MeetingEvent(meeting_id=meeting.id, message=f"Hosted bot requested for {url}."))
    db.commit()
    db.refresh(meeting)
    return _meeting_payload(meeting)


@router.get("/bot/{meeting_id}/status")
def bot_status(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Poll the live state of a bot-recorded meeting."""
    meeting = _owned_meeting(meeting_id, db, current_user)
    handle = bot_manager.get(meeting_id) or baas_manager.get(meeting_id)

    events = (
        db.query(models.MeetingEvent)
        .filter(models.MeetingEvent.meeting_id == meeting_id)
        .order_by(models.MeetingEvent.id.desc())
        .limit(12)
        .all()
    )
    segment_count = (
        db.query(models.TranscriptSegment)
        .filter(models.TranscriptSegment.meeting_id == meeting_id)
        .count()
    )

    return {
        "id": meeting.id,
        "title": meeting.title,
        "status": meeting.status,
        "is_active": meeting.status in MeetingStatus.ACTIVE_BOT_STATES
        or meeting.status
        in (
            MeetingStatus.PROCESSING_AUDIO,
            MeetingStatus.TRANSCRIBING,
            MeetingStatus.GENERATING_SUMMARY,
        ),
        "bot_running": handle is not None,
        "uptime_seconds": handle.uptime_seconds if handle else None,
        "end_reason": meeting.end_reason,
        "error_message": meeting.error_message,
        "peak_participants": meeting.peak_participants,
        "duration_ms": meeting.duration_ms,
        "transcript_segments": segment_count,
        # Live, mid-meeting results (populated while the call is running).
        "live_summary": meeting.live_summary,
        "live_transcript": (meeting.live_transcript or "")[-4000:] or None,
        "live_updated_at": meeting.live_updated_at,
        "events": [
            {
                "created_at": e.created_at,
                "level": e.level,
                "message": e.message,
            }
            for e in reversed(events)
        ],
    }


@router.post("/bot/{meeting_id}/start")
@router.post("/{meeting_id}/dispatch-bot")
def bot_start(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Launch the bot into an existing meeting by id."""
    meeting = _owned_meeting(meeting_id, db, current_user)
    if not meeting.meet_url:
        raise HTTPException(status_code=400, detail="No meeting URL found for this meeting.")

    url, error = normalise_meet_url(meeting.meet_url)
    if error:
        raise HTTPException(status_code=400, detail=error)

    started, message = bot_manager.start(meeting.id, url)
    if not started:
        meeting.status = MeetingStatus.BOT_FAILED
        meeting.error_message = message
        db.commit()
        raise HTTPException(status_code=429, detail=message)

    meeting.status = MeetingStatus.BOT_QUEUED
    meeting.source = "bot"
    db.add(
        models.MeetingEvent(
            meeting_id=meeting.id,
            message=f"Bot dispatched to {url}.",
            level="info",
        )
    )
    db.commit()
    db.refresh(meeting)
    return {"message": "Bot dispatched successfully", "status": meeting.status, "meet_url": url}


@router.post("/bot/{meeting_id}/stop")
def bot_stop(
    meeting_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Pull the bot out of a call early and process whatever it captured."""
    meeting = _owned_meeting(meeting_id, db, current_user)
    stopped, message = bot_manager.stop(meeting_id)
    if stopped:
        return {"message": message, "status": "stopping"}

    # If the bot is not running in memory, check if audio or captions exist and process directly!
    from ..ai.pipeline import process_meeting_audio

    audio_file = meeting.audio_file_path or storage_path(f"{meeting_id}_bot_audio.webm")
    if os.path.exists(audio_file) and os.path.getsize(audio_file) > 2048:
        meeting.status = MeetingStatus.PROCESSING_AUDIO
        db.commit()
        background_tasks.add_task(process_meeting_audio, meeting_id, file_path=audio_file)
        return {"message": "Processing audio recording and generating summary...", "status": "processing"}

    raise HTTPException(status_code=409, detail=message)


@router.post("/{meeting_id}/generate-summary")
def generate_summary(
    meeting_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Force fast (re)generation of meeting summary and insights."""
    meeting = _owned_meeting(meeting_id, db, current_user)
    from ..ai.pipeline import process_meeting_audio

    audio_file = meeting.audio_file_path or storage_path(f"{meeting_id}_bot_audio.webm")
    if not (os.path.exists(audio_file) and os.path.getsize(audio_file) > 2048):
        audio_file = None

    meeting.status = MeetingStatus.PROCESSING_AUDIO
    db.commit()
    background_tasks.add_task(process_meeting_audio, meeting_id, file_path=audio_file)
    return {"message": "Generating summary in background...", "status": meeting.status}


@router.get("/bot/active")
def bot_active(current_user: models.User = Depends(get_current_user)):
    return {
        "count": len(bot_manager.active()),
        "limit": settings.BOT_MAX_CONCURRENT,
        "meetings": [h.meeting_id for h in bot_manager.active()],
    }


# ────────────────────────────── meetings ─────────────────────────────────

@router.post("", response_model=MeetingResponse)
@router.post("/", response_model=MeetingResponse)
def create_meeting(
    meeting: MeetingCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    new_meeting = models.Meeting(
        title=meeting.title,
        owner_id=current_user.id,
        status=MeetingStatus.CREATED,
        source="upload",
    )
    db.add(new_meeting)
    db.commit()
    db.refresh(new_meeting)
    return _meeting_payload(new_meeting)


@router.get("", response_model=List[MeetingResponse])
@router.get("/", response_model=List[MeetingResponse])
def get_meetings(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    meetings = (
        db.query(models.Meeting)
        .filter(models.Meeting.owner_id == current_user.id)
        .order_by(models.Meeting.id.desc())
        .all()
    )
    return [_meeting_payload(m) for m in meetings]


@router.get("/{meeting_id}", response_model=MeetingResponse)
def get_meeting(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    return _meeting_payload(_owned_meeting(meeting_id, db, current_user))


@router.get("/{meeting_id}/events", response_model=List[MeetingEventResponse])
def get_meeting_events(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    _owned_meeting(meeting_id, db, current_user)
    return (
        db.query(models.MeetingEvent)
        .filter(models.MeetingEvent.meeting_id == meeting_id)
        .order_by(models.MeetingEvent.id.asc())
        .all()
    )


@router.get("/{meeting_id}/transcript", response_model=List[TranscriptSegmentResponse])
def get_meeting_transcript(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    _owned_meeting(meeting_id, db, current_user)
    return (
        db.query(models.TranscriptSegment)
        .filter(models.TranscriptSegment.meeting_id == meeting_id)
        .order_by(models.TranscriptSegment.start_time)
        .all()
    )


@router.get("/{meeting_id}/audio")
def get_meeting_audio(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Stream the recording back for the transcript-synced audio player."""
    meeting = _owned_meeting(meeting_id, db, current_user)
    if not meeting.audio_file_path or not os.path.exists(meeting.audio_file_path):
        raise HTTPException(status_code=404, detail="No recording is stored for this meeting")

    extension = os.path.splitext(meeting.audio_file_path)[1].lower().lstrip(".")
    media_types = {
        "webm": "audio/webm",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "m4a": "audio/mp4",
        "mp4": "audio/mp4",
        "ogg": "audio/ogg",
        "opus": "audio/ogg",
    }
    return FileResponse(
        meeting.audio_file_path,
        media_type=media_types.get(extension, "application/octet-stream"),
        filename=f"meeting-{meeting_id}.{extension or 'webm'}",
    )


@router.get("/{meeting_id}/export", response_class=PlainTextResponse)
def export_meeting(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Markdown export of the report and full transcript."""
    meeting = _owned_meeting(meeting_id, db, current_user)
    summary = _summary_payload(meeting.summary)
    segments = (
        db.query(models.TranscriptSegment)
        .filter(models.TranscriptSegment.meeting_id == meeting_id)
        .order_by(models.TranscriptSegment.start_time)
        .all()
    )

    out: list[str] = [f"# {meeting.title}", ""]
    out.append(f"- Date: {meeting.date:%Y-%m-%d %H:%M} UTC")
    if meeting.duration_ms:
        out.append(f"- Duration: {format_timestamp(meeting.duration_ms)}")
    if meeting.meet_url:
        out.append(f"- Meeting link: {meeting.meet_url}")
    if meeting.participants:
        out.append(f"- Participants: {', '.join(p.name for p in meeting.participants)}")
    out.append("")

    def section(title: str, items: list[str]) -> None:
        if not items:
            return
        out.extend([f"## {title}", ""])
        out.extend(f"- {item}" for item in items)
        out.append("")

    if summary:
        out.extend(["## Executive summary", "", summary.executive_summary or "_None_", ""])
        section("Key points", summary.key_points)
        section("Decisions", [d.text for d in meeting.decisions])
        if meeting.action_items:
            out.extend(["## Action items", ""])
            for item in meeting.action_items:
                bits = [item.text]
                if item.owner:
                    bits.append(f"Owner: {item.owner}")
                if item.deadline:
                    bits.append(f"Due: {item.deadline}")
                out.append("- " + " | ".join(bits))
            out.append("")
        section("Risks and open topics", summary.risks)
        section("Questions", summary.questions)
        section("Next steps", summary.next_steps)
        section("Topics", summary.topics)

    out.extend(["## Transcript", ""])
    out.append(build_transcript_text(segments) or "_No transcript available._")

    return "\n".join(out)


# ─────────────────────────────── uploads ─────────────────────────────────

@router.post("/{meeting_id}/audio")
def upload_audio(
    meeting_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    meeting = _owned_meeting(meeting_id, db, current_user)

    extension = (
        file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "webm"
    )
    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '.{extension}'. Allowed: "
                + ", ".join(sorted(ALLOWED_AUDIO_EXTENSIONS))
            ),
        )

    file_path = storage_path(f"{meeting_id}_audio.{extension}")
    written = 0
    try:
        with open(file_path, "wb") as buffer:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
                    )
                buffer.write(chunk)
    except HTTPException:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise

    if written == 0:
        os.remove(file_path)
        raise HTTPException(status_code=400, detail="The uploaded file is empty")

    meeting.audio_file_path = file_path
    meeting.status = MeetingStatus.UPLOADED
    meeting.source = meeting.source or "upload"
    db.add(
        models.MeetingEvent(
            meeting_id=meeting.id,
            message=f"Uploaded {file.filename} ({written / 1_048_576:.1f} MB).",
        )
    )
    db.commit()

    from ..ai.pipeline import process_meeting_audio

    background_tasks.add_task(process_meeting_audio, meeting.id, file_path)

    return {
        "message": "Audio uploaded. Transcription started.",
        "status": meeting.status,
        "bytes": written,
    }


# ─────────────────────────────── ask ai ──────────────────────────────────

@router.post("/{meeting_id}/ask")
def ask_question(
    meeting_id: int,
    request: AskRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    _owned_meeting(meeting_id, db, current_user)

    question = (request.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="The question is empty")

    segments = (
        db.query(models.TranscriptSegment)
        .filter(models.TranscriptSegment.meeting_id == meeting_id)
        .order_by(models.TranscriptSegment.start_time)
        .all()
    )
    if not segments:
        raise HTTPException(
            status_code=409, detail="This meeting has no transcript to ask about yet"
        )

    context = build_transcript_text(segments)

    from ..ai.ollama_service import answer_question

    return {"answer": answer_question(context, question), "question": question}


# ─────────────────────────────── lensai bot intelligence ───────────────────

@router.get("/{meeting_id}/analytics")
def meeting_analytics(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Compute speaker talk-time metrics and conversation sentiment."""
    _owned_meeting(meeting_id, db, current_user)
    segments = (
        db.query(models.TranscriptSegment)
        .filter(models.TranscriptSegment.meeting_id == meeting_id)
        .order_by(models.TranscriptSegment.start_time)
        .all()
    )
    seg_dicts = [
        {
            "speaker": s.speaker or "Speaker",
            "text": s.text or "",
            "start_time": s.start_time or 0,
            "end_time": s.end_time or 0,
        }
        for s in segments
    ]
    context = build_transcript_text(segments)

    from Lensai_Bot.analytics.speaker_metrics import calculate_speaker_metrics
    from Lensai_Bot.analytics.sentiment_analyzer import analyze_sentiment

    speaker_metrics = calculate_speaker_metrics(seg_dicts).to_dict()
    sentiment = analyze_sentiment(context, seg_dicts, use_llm=False).to_dict()

    return {
        "speaker_analytics": speaker_metrics,
        "sentiment": sentiment,
    }


@router.get("/{meeting_id}/soundbites")
def meeting_soundbites(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Extract key quotes and soundbites."""
    _owned_meeting(meeting_id, db, current_user)
    segments = (
        db.query(models.TranscriptSegment)
        .filter(models.TranscriptSegment.meeting_id == meeting_id)
        .order_by(models.TranscriptSegment.start_time)
        .all()
    )
    seg_dicts = [
        {
            "speaker": s.speaker or "Speaker",
            "text": s.text or "",
            "start_time": s.start_time or 0,
            "end_time": s.end_time or 0,
        }
        for s in segments
    ]

    from Lensai_Bot.analytics.soundbites import extract_soundbites

    soundbites = extract_soundbites(seg_dicts, use_llm=False)
    return {"soundbites": [sb.to_dict() for sb in soundbites]}


@router.get("/{meeting_id}/email-draft")
def meeting_email_draft(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Generate a high-priority follow-up recap email."""
    meeting = _owned_meeting(meeting_id, db, current_user)
    summary_text = meeting.summary.executive_summary if meeting.summary else "Meeting notes."
    actions = [
        {"task": a.text, "assignee": a.owner, "deadline": a.deadline}
        for a in meeting.action_items
    ]
    decisions = [d.text for d in meeting.decisions]

    from Lensai_Bot.assistant.email_drafter import draft_followup_email

    draft = draft_followup_email(
        meeting_title=meeting.title,
        executive_summary=summary_text,
        action_items=actions,
        decisions=decisions,
        use_llm=False,
    )
    return draft


@router.get("/{meeting_id}/export/markdown")
def meeting_export_markdown(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Export complete meeting notes to Markdown."""
    meeting = _owned_meeting(meeting_id, db, current_user)
    segments = (
        db.query(models.TranscriptSegment)
        .filter(models.TranscriptSegment.meeting_id == meeting_id)
        .order_by(models.TranscriptSegment.start_time)
        .all()
    )
    seg_dicts = [
        {
            "speaker": s.speaker or "Speaker",
            "text": s.text or "",
            "start_time": s.start_time or 0,
            "end_time": s.end_time or 0,
        }
        for s in segments
    ]
    context = build_transcript_text(segments)

    from Lensai_Bot.analytics.speaker_metrics import calculate_speaker_metrics
    from Lensai_Bot.analytics.sentiment_analyzer import analyze_sentiment
    from Lensai_Bot.export.markdown_export import export_meeting_markdown

    spk_metrics = calculate_speaker_metrics(seg_dicts).to_dict()
    sentiment = analyze_sentiment(context, seg_dicts, use_llm=False).to_dict()
    actions = [
        {"task": a.text, "assignee": a.owner, "deadline": a.deadline}
        for a in meeting.action_items
    ]
    decisions = [d.text for d in meeting.decisions]
    key_points = (
        [kp for kp in meeting.summary.key_points.split("\n") if kp.strip()]
        if meeting.summary and meeting.summary.key_points
        else []
    )
    next_steps = (
        [ns for ns in meeting.summary.next_steps.split("\n") if ns.strip()]
        if meeting.summary and meeting.summary.next_steps
        else []
    )

    md = export_meeting_markdown(
        title=meeting.title,
        date_str=meeting.date.strftime("%Y-%m-%d") if meeting.date else "N/A",
        duration_str=f"{int((meeting.duration_ms or 0) / 60000)}m",
        executive_summary=meeting.summary.executive_summary if meeting.summary else "",
        key_points=key_points,
        action_items=actions,
        decisions=decisions,
        next_steps=next_steps,
        speaker_analytics=spk_metrics,
        sentiment_report=sentiment,
        transcript_segments=seg_dicts,
        include_transcript=False,  # Only summary, no full transcript
        include_analytics=False,   # No analytics tables
    )
    return PlainTextResponse(content=md, media_type="text/markdown")


@router.get("/{meeting_id}/export/csv")
def meeting_export_csv(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Export action items as CSV."""
    meeting = _owned_meeting(meeting_id, db, current_user)
    actions = [
        {"task": a.text, "assignee": a.owner, "deadline": a.deadline}
        for a in meeting.action_items
    ]
    from Lensai_Bot.export.csv_export import export_action_items_csv

    csv_data = export_action_items_csv(actions, meeting.title)
    return PlainTextResponse(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="action_items_{meeting_id}.csv"'},
    )


@router.get("/{meeting_id}/export/pdf")
def meeting_export_pdf(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Export consolidated meeting summary and participant discussion as a professional PDF."""
    from fastapi import Response

    meeting = _owned_meeting(meeting_id, db, current_user)

    segments = (
        db.query(models.TranscriptSegment)
        .filter(models.TranscriptSegment.meeting_id == meeting_id)
        .order_by(models.TranscriptSegment.start_time)
        .all()
    )
    seg_dicts = [
        {
            "start_time": s.start_time or 0,
            "end_time": s.end_time or 0,
            "text": s.text or "",
            "speaker": s.speaker or "Speaker",
        }
        for s in segments
    ]

    spk_metrics = None
    sentiment = None
    soundbites = None
    if seg_dicts:
        from Lensai_Bot.analytics.sentiment_analyzer import analyze_sentiment
        from Lensai_Bot.analytics.soundbites import extract_soundbites
        from Lensai_Bot.analytics.speaker_metrics import calculate_speaker_metrics

        context = build_transcript_text(segments)

        # These helpers return dataclasses; the PDF builder consumes plain dicts.
        # Keep use_llm=False so a report download never blocks on Ollama.
        spk_metrics = calculate_speaker_metrics(seg_dicts).to_dict()
        sentiment = analyze_sentiment(context, seg_dicts, use_llm=False).to_dict()
        soundbites = [
            sb.to_dict() for sb in extract_soundbites(seg_dicts, use_llm=False)
        ]

    actions = [
        {"task": a.text, "assignee": a.owner, "deadline": a.deadline}
        for a in meeting.action_items
    ]
    decisions = [d.text for d in meeting.decisions]
    key_points = (
        [kp for kp in meeting.summary.key_points.split("\n") if kp.strip()]
        if meeting.summary and meeting.summary.key_points
        else []
    )
    next_steps = (
        [ns for ns in meeting.summary.next_steps.split("\n") if ns.strip()]
        if meeting.summary and meeting.summary.next_steps
        else []
    )
    participants = [p.name for p in meeting.participants]

    from Lensai_Bot.export.pdf_export import generate_meeting_pdf

    pdf_bytes = generate_meeting_pdf(
        title=meeting.title,
        date_str=meeting.date.strftime("%Y-%m-%d %H:%M") if meeting.date else "N/A",
        duration_str=f"{int((meeting.duration_ms or 0) / 60000)}m",
        executive_summary=meeting.summary.executive_summary if meeting.summary else "",
        key_points=key_points,
        action_items=actions,
        decisions=decisions,
        next_steps=next_steps,
        speaker_analytics=spk_metrics,
        sentiment_report=sentiment,
        soundbites=soundbites,
        transcript_segments=seg_dicts,
        participants=participants,
        include_transcript=False,  # Only summary, no full transcript
        include_analytics=False,   # No analytics tables
    )

    filename = f"LensAi_Meeting_{meeting_id}_Report.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────── delete ──────────────────────────────────

@router.delete("/{meeting_id}")
def delete_meeting(
    meeting_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
):
    meeting = _owned_meeting(meeting_id, db, current_user)

    if bot_manager.is_running(meeting_id) or baas_manager.is_running(meeting_id):
        bot_manager.stop(meeting_id)
        baas_manager.stop(meeting_id)
        raise HTTPException(
            status_code=409,
            detail="A bot is still in this meeting. It is being stopped — retry shortly.",
        )

    audio_path = meeting.audio_file_path
    db.delete(meeting)
    db.commit()

    if audio_path and os.path.exists(audio_path):
        try:
            os.remove(audio_path)
        except OSError:
            pass
    return {"message": "Meeting deleted"}
