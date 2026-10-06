"""Shared post-capture processing pipeline.

Both paths into the product converge here:

    bot recording  ─┐
                    ├─> transcribe -> label speakers -> persist -> AI report
    manual upload  ─┘

The pipeline owns the meeting `status` transitions and the `meeting_events`
activity log that the UI streams while work is in flight.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from .. import models
from ..database import SessionLocal
from ..models import MeetingStatus
from ..config import settings
from .speaker_identifier import SpeakerIdentifier
# Performance monitoring imports - temporarily disabled
# from ..utils.performance_monitor import get_monitor, calculate_transcription_quality
# from ..utils.retry_logic import retry_with_backoff


# ───────────────────────────── logging helpers ───────────────────────────

def log_event(db: Session, meeting_id: int, message: str, level: str = "info") -> None:
    """Append a line to the meeting activity log (best effort, never raises)."""
    try:
        encoding = sys.stdout.encoding or "utf-8"
        safe_msg = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(f"[meeting {meeting_id}] {level.upper()}: {safe_msg}")
    except Exception:
        try:
            print(f"[meeting {meeting_id}] {level.upper()}: {message.encode('ascii', errors='replace').decode('ascii')}")
        except Exception:
            pass

    try:
        db.add(
            models.MeetingEvent(meeting_id=meeting_id, message=message[:2000], level=level)
        )
        db.commit()
    except Exception as exc:  # pragma: no cover
        try:
            print(f"[meeting {meeting_id}] could not persist event: {exc}")
        except Exception:
            pass
        db.rollback()


def set_status(db: Session, meeting: models.Meeting, status: str) -> None:
    meeting.status = status
    db.commit()
    print(f"[meeting {meeting.id}] status -> {status}")


# ───────────────────────── caption post-processing ───────────────────────

def clean_captions(
    captions: Iterable[dict[str, Any]], 
    participant_names: list[str] | None = None
) -> list[dict[str, Any]]:
    """Normalise scraped caption entries into a speaker timeline.

    Live captions arrive as partially-overlapping fragments because the DOM row
    is rewritten while a person is speaking. Sort by time and collapse entries
    where one is contained in the other.
    
    NEW: Enhanced with speaker identification to map generic labels to real names.
    """
    # Initialize speaker identifier if we have participant names
    identifier = None
    if settings.ENABLE_SPEAKER_MAPPING and participant_names:
        identifier = SpeakerIdentifier()
        identifier.add_participants(participant_names)

    entries: list[dict[str, Any]] = []
    for raw in captions or []:
        text = (raw.get("text") or "").strip()
        if not text:
            continue
        start = int(raw.get("startMs") or 0)
        end = int(raw.get("endMs") or start)
        raw_speaker = (raw.get("speaker") or "").strip() or None
        
        # Map speaker label to real name
        speaker = identifier.map_speaker(raw_speaker) if (identifier and raw_speaker) else raw_speaker
        
        entries.append(
            {
                "start_ms": max(0, start),
                "end_ms": max(start, end),
                "text": text,
                "speaker": speaker,
            }
        )

    entries.sort(key=lambda e: (e["start_ms"], e["end_ms"]))

    collapsed: list[dict[str, Any]] = []
    for entry in entries:
        if collapsed:
            prev = collapsed[-1]
            same_speaker = prev["speaker"] == entry["speaker"]
            if same_speaker:
                a, b = prev["text"], entry["text"]
                if b in a:
                    prev["end_ms"] = max(prev["end_ms"], entry["end_ms"])
                    continue
                if a in b:
                    prev["text"] = b
                    prev["end_ms"] = max(prev["end_ms"], entry["end_ms"])
                    continue
        collapsed.append(entry)

    return collapsed


def label_speakers(
    segments: list[dict[str, Any]],
    caption_timeline: list[dict[str, Any]],
    default: str = "Speaker",
    participant_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Attach speaker names to Whisper segments using the caption timeline.

    Whisper gives accurate text but knows nothing about who spoke. Meet's live
    captions are the opposite: rough text, reliable speaker names. Overlapping
    the two timelines gives accurate, attributed transcript lines without
    needing a separate diarization model.
    
    NEW: Enhanced with Otter/Fireflies approach - maps generic speaker labels
    to actual participant names from Google Meet.
    """
    if not caption_timeline:
        for seg in segments:
            seg.setdefault("speaker", None)
        return segments

    # Initialize speaker identifier with participant names (Otter/Fireflies approach)
    identifier = None
    if settings.ENABLE_SPEAKER_MAPPING and participant_names:
        identifier = SpeakerIdentifier()
        identifier.add_participants(participant_names)

    for seg in segments:
        s, e = seg["start_ms"], seg["end_ms"]
        overlap_by_speaker: dict[str, int] = {}

        for cap in caption_timeline:
            if cap["end_ms"] < s:
                continue
            if cap["start_ms"] > e:
                break  # timeline is sorted
            speaker = cap["speaker"]
            if not speaker:
                continue
            overlap = min(e, cap["end_ms"]) - max(s, cap["start_ms"])
            if overlap > 0:
                overlap_by_speaker[speaker] = overlap_by_speaker.get(speaker, 0) + overlap

        if overlap_by_speaker:
            raw_speaker = max(overlap_by_speaker.items(), key=lambda kv: kv[1])[0]
            # Map generic labels to real names
            seg["speaker"] = identifier.map_speaker(raw_speaker) if identifier else raw_speaker
            continue

        # No overlap: fall back to the nearest caption within 4 seconds.
        best_speaker, best_gap = None, None
        for cap in caption_timeline:
            if not cap["speaker"]:
                continue
            gap = 0 if cap["start_ms"] <= s <= cap["end_ms"] else min(
                abs(cap["start_ms"] - e), abs(s - cap["end_ms"])
            )
            if best_gap is None or gap < best_gap:
                best_gap, best_speaker = gap, cap["speaker"]
        
        raw_speaker = best_speaker if (best_gap is not None and best_gap <= 4000) else default
        # Map generic labels to real names
        seg["speaker"] = identifier.map_speaker(raw_speaker) if identifier else raw_speaker

    return segments


# ───────────────────────────── transcript text ───────────────────────────

def format_timestamp(ms: int) -> str:
    total = max(0, int(ms)) // 1000
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def build_transcript_text(segments: Iterable[Any]) -> str:
    """Render segments as "[mm:ss] Speaker: text" lines for the LLM."""
    lines: list[str] = []
    for seg in segments:
        if isinstance(seg, dict):
            start, text, speaker = seg.get("start_ms", 0), seg.get("text", ""), seg.get("speaker")
        else:
            start, text, speaker = seg.start_time or 0, seg.text or "", seg.speaker
        text = (text or "").strip()
        if not text:
            continue
        lines.append(f"[{format_timestamp(start)}] {speaker or 'Speaker'}: {text}")
    return "\n".join(lines)


# ──────────────────────────── persistence ────────────────────────────────

def persist_transcript(
    db: Session,
    meeting_id: int,
    segments: list[dict[str, Any]],
    source: str,
) -> None:
    """Replace the stored transcript for a meeting."""
    db.query(models.TranscriptSegment).filter(
        models.TranscriptSegment.meeting_id == meeting_id
    ).delete(synchronize_session=False)

    for seg in segments:
        db.add(
            models.TranscriptSegment(
                meeting_id=meeting_id,
                start_time=int(seg.get("start_ms") or 0),
                end_time=int(seg.get("end_ms") or 0),
                text=(seg.get("text") or "").strip(),
                speaker=seg.get("speaker"),
                source=source,
                confidence=seg.get("confidence"),
            )
        )
    db.commit()


def persist_participants(
    db: Session, meeting_id: int, names: dict[str, dict[str, Any]] | None
) -> None:
    if not names:
        return
    db.query(models.Participant).filter(
        models.Participant.meeting_id == meeting_id
    ).delete(synchronize_session=False)
    for name, info in names.items():
        clean = (name or "").strip()
        if not clean or clean.lower() == "you":
            continue
        db.add(
            models.Participant(
                meeting_id=meeting_id,
                name=clean[:200],
                first_seen_ms=int((info or {}).get("firstMs") or 0),
                last_seen_ms=int((info or {}).get("lastMs") or 0),
            )
        )
    db.commit()


def persist_insights(db: Session, meeting_id: int, insights: dict[str, Any]) -> None:
    """Store the structured AI report, replacing anything already there."""
    db.query(models.Summary).filter(models.Summary.meeting_id == meeting_id).delete(
        synchronize_session=False
    )
    db.query(models.Decision).filter(models.Decision.meeting_id == meeting_id).delete(
        synchronize_session=False
    )
    db.query(models.ActionItem).filter(
        models.ActionItem.meeting_id == meeting_id
    ).delete(synchronize_session=False)
    db.commit()

    def joined(key: str) -> str | None:
        items = insights.get(key) or []
        return "\n".join(items) if items else None

    # Update meeting title if AI generated one
    meeting_title = insights.get("meeting_title")
    if meeting_title and meeting_title.strip():
        meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
        if meeting and not meeting.meeting_title:  # Only set if not already set
            meeting.meeting_title = meeting_title.strip()
            db.commit()

    db.add(
        models.Summary(
            meeting_id=meeting_id,
            executive_summary=insights.get("executive_summary") or "",
            key_points=joined("key_points"),
            topics=joined("topics"),
            risks=joined("risks"),
            questions=joined("questions"),
            next_steps=joined("next_steps"),
            model=insights.get("model"),
        )
    )
    for decision in insights.get("decisions") or []:
        db.add(models.Decision(meeting_id=meeting_id, text=decision))
    for item in insights.get("action_items") or []:
        db.add(
            models.ActionItem(
                meeting_id=meeting_id,
                text=item.get("text") or "",
                owner=item.get("owner"),
                deadline=item.get("deadline"),
            )
        )
    db.commit()


# ─────────────────────────── the pipeline itself ─────────────────────────

def process_meeting_audio(
    meeting_id: int,
    file_path: str | None,
    captions: list[dict[str, Any]] | None = None,
    participant_names: dict[str, dict[str, Any]] | None = None,
    db: Session | None = None,
) -> bool:
    """Transcribe, attribute, summarise and persist. Returns True on success.

    `captions` is the bot's scraped speaker timeline. It is used for speaker
    attribution and, if the audio capture yielded nothing usable, as the
    transcript source of last resort.
    """
    owns_session = db is None
    if db is None:
        db = SessionLocal()

    try:
        meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
        if not meeting:
            print(f"[pipeline] meeting {meeting_id} not found")
            return False

        caption_timeline = clean_captions(
            captions or [], 
            participant_names=list(participant_names.keys()) if participant_names else None
        )
        if caption_timeline:
            log_event(
                db,
                meeting_id,
                f"Using {len(caption_timeline)} live-caption entries for speaker attribution.",
            )
        persist_participants(db, meeting_id, participant_names)

        segments: list[dict[str, Any]] = []
        transcript_source = "whisper"

        has_audio = bool(file_path) and os.path.exists(file_path) and os.path.getsize(file_path) > 2048
        if has_audio:
            set_status(db, meeting, MeetingStatus.TRANSCRIBING)
            log_event(db, meeting_id, "Transcribing the recording with Whisper...")
            try:
                result = transcribe_with_progress(db, meeting_id, file_path)
                segments = result["segments"]
                if result.get("duration_ms"):
                    meeting.duration_ms = result["duration_ms"]
                    db.commit()
                if segments:
                    log_event(
                        db,
                        meeting_id,
                        f"Transcribed {len(segments)} segments "
                        f"(detected language: {result.get('language') or 'unknown'}).",
                    )
                else:
                    log_event(
                        db,
                        meeting_id,
                        "Whisper found no speech in the recording.",
                        level="warning",
                    )
            except Exception as exc:
                log_event(db, meeting_id, f"Transcription failed: {exc}", level="error")
        elif file_path:
            log_event(
                db,
                meeting_id,
                "The captured audio file is empty or missing.",
                level="warning",
            )

        if segments:
            # Extract participant name list for speaker mapping
            participant_name_list = list(participant_names.keys()) if participant_names else []
            label_speakers(segments, caption_timeline, participant_names=participant_name_list)
        elif caption_timeline:
            # Audio capture produced nothing usable — the live captions are
            # still a real transcript, so use them rather than failing.
            log_event(
                db,
                meeting_id,
                "Falling back to the live-caption transcript.",
                level="warning",
            )
            transcript_source = "captions"
            segments = [
                {
                    "start_ms": cap["start_ms"],
                    "end_ms": cap["end_ms"],
                    "text": cap["text"],
                    "speaker": cap["speaker"] or "Speaker",
                }
                for cap in caption_timeline
            ]
            if not meeting.duration_ms and segments:
                meeting.duration_ms = segments[-1]["end_ms"]
                db.commit()

        if not segments:
            log_event(
                db,
                meeting_id,
                "No transcript could be produced: no speech was captured.",
                level="error",
            )
            persist_insights(
                db,
                meeting_id,
                {
                    "executive_summary": (
                        "No speech was captured for this meeting. If the bot was in "
                        "the call, check that participants were unmuted and that "
                        "live captions were available."
                    ),
                    "model": None,
                },
            )
            set_status(db, meeting, MeetingStatus.COMPLETED)
            return False

        persist_transcript(db, meeting_id, segments, transcript_source)
        transcript_text = build_transcript_text(segments)

        set_status(db, meeting, MeetingStatus.GENERATING_SUMMARY)
        log_event(db, meeting_id, "Generating the AI summary, decisions and action items...")

        from .ollama_service import generate_meeting_insights

        insights = generate_meeting_insights(
            transcript_text,
            progress=lambda msg: log_event(db, meeting_id, msg),
        )
        persist_insights(db, meeting_id, insights)

        log_event(
            db,
            meeting_id,
            "Report ready: "
            f"{len(insights.get('key_points') or [])} key points, "
            f"{len(insights.get('decisions') or [])} decisions, "
            f"{len(insights.get('action_items') or [])} action items.",
        )
        set_status(db, meeting, MeetingStatus.COMPLETED)
        
        # Send email notification after meeting completes
        try:
            from ..services.email_service import EmailService
            from ..config import settings
            
            if settings.SEND_EMAIL_NOTIFICATIONS and meeting.owner:
                # Get owner details
                owner_email = meeting.owner.email
                owner_name = owner_email.split('@')[0].title()  # Extract name from email
                
                # Send meeting recap email
                EmailService.send_meeting_recap(
                    recipient_email=owner_email,
                    recipient_name=owner_name,
                    meeting_title=meeting.title or "Meeting",
                    meeting_date=meeting.date or meeting.started_at or datetime.utcnow(),
                    meeting_id=meeting.id,
                    invited_by=None  # Could be expanded to track who invited the bot
                )
                log_event(db, meeting_id, f"Meeting recap email sent to {owner_email}")
        except Exception as email_exc:
            # Don't fail the whole pipeline if email fails
            log_event(
                db,
                meeting_id,
                f"Email notification failed: {email_exc}",
                level="warning"
            )
        
        return True

    except Exception as exc:
        import traceback

        traceback.print_exc()
        try:
            meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
            if meeting:
                meeting.error_message = str(exc)[:2000]
                set_status(db, meeting, MeetingStatus.FAILED)
            log_event(db, meeting_id, f"Processing failed: {exc}", level="error")
        except Exception:
            pass
        return False
    finally:
        if owns_session:
            db.close()


def transcribe_with_progress(db: Session, meeting_id: int, file_path: str) -> dict[str, Any]:
    from .transcription import transcribe_file

    last: list[str] = []

    def progress(message: str) -> None:
        # Only log milestones, not every segment batch, to keep the log usable.
        if message.startswith(("Transcribing", "Done")) or "segments transcribed" in message:
            if message not in last:
                last.append(message)
                log_event(db, meeting_id, message)

    return transcribe_file(file_path, progress=progress)


def finalise_meeting_timing(
    db: Session, meeting: models.Meeting, end_reason: str | None = None
) -> None:
    meeting.ended_at = datetime.utcnow()
    if end_reason:
        meeting.end_reason = end_reason
    if meeting.started_at and not meeting.duration_ms:
        delta = meeting.ended_at - meeting.started_at
        meeting.duration_ms = int(delta.total_seconds() * 1000)
    db.commit()
