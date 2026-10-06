from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from datetime import datetime

from .database import Base


class MeetingStatus:
    """Canonical processing states for a meeting.

    Bot lifecycle:
        bot_queued -> bot_launching -> bot_joining -> bot_waiting_for_host
        -> bot_in_call -> bot_recording -> bot_left
    Processing (shared with uploads):
        uploaded -> processing_audio -> transcribing -> generating_summary
        -> completed
    Terminal failures: bot_failed, failed
    """

    # Bot lifecycle
    BOT_QUEUED = "bot_queued"
    BOT_LAUNCHING = "bot_launching"
    BOT_JOINING = "bot_joining"
    BOT_WAITING_FOR_HOST = "bot_waiting_for_host"
    BOT_IN_CALL = "bot_in_call"
    BOT_RECORDING = "bot_recording"
    BOT_LEFT = "bot_left"
    BOT_FAILED = "bot_failed"

    # Shared processing pipeline
    CREATED = "created"
    UPLOADED = "uploaded"
    PROCESSING_AUDIO = "processing_audio"
    TRANSCRIBING = "transcribing"
    GENERATING_SUMMARY = "generating_summary"
    COMPLETED = "completed"
    FAILED = "failed"

    ACTIVE_BOT_STATES = {
        BOT_QUEUED,
        BOT_LAUNCHING,
        BOT_JOINING,
        BOT_WAITING_FOR_HOST,
        BOT_IN_CALL,
        BOT_RECORDING,
    }
    TERMINAL = {COMPLETED, FAILED, BOT_FAILED}


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    meetings = relationship("Meeting", back_populates="owner")


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    meeting_title = Column(String, nullable=True)  # AI-generated meeting title
    date = Column(DateTime, default=datetime.utcnow)
    owner_id = Column(Integer, ForeignKey("users.id"))
    audio_file_path = Column(String, nullable=True)
    status = Column(String, default=MeetingStatus.CREATED)

    # ── Bot / source metadata ────────────────────────────────────────────
    source = Column(String, default="upload")  # upload | bot | meetingbaas | meet_api
    meet_url = Column(String, nullable=True)
    platform = Column(String, nullable=True)  # google_meet | zoom | teams
    # Provider-side bot id (e.g. Meeting BaaS bot_id) for status polling / stop.
    external_bot_id = Column(String, nullable=True)

    # ── Live (in-meeting) results, updated while the call is running ──────
    live_transcript = Column(Text, nullable=True)
    live_summary = Column(Text, nullable=True)
    live_updated_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    # Highest number of human participants observed while recording.
    peak_participants = Column(Integer, nullable=True)
    # Why the bot stopped: all_participants_left | max_duration | removed |
    # manual_stop | never_admitted | no_participants
    end_reason = Column(String, nullable=True)

    owner = relationship("User", back_populates="meetings")
    transcript_segments = relationship(
        "TranscriptSegment",
        back_populates="meeting",
        cascade="all, delete-orphan",
    )
    summary = relationship(
        "Summary",
        uselist=False,
        back_populates="meeting",
        cascade="all, delete-orphan",
    )
    decisions = relationship(
        "Decision", back_populates="meeting", cascade="all, delete-orphan"
    )
    action_items = relationship(
        "ActionItem", back_populates="meeting", cascade="all, delete-orphan"
    )
    participants = relationship(
        "Participant", back_populates="meeting", cascade="all, delete-orphan"
    )
    events = relationship(
        "MeetingEvent",
        back_populates="meeting",
        cascade="all, delete-orphan",
        order_by="MeetingEvent.created_at",
    )


class Summary(Base):
    __tablename__ = "summaries"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    executive_summary = Column(Text)
    # The following are newline-delimited lists (one item per line).
    key_points = Column(Text, nullable=True)
    topics = Column(Text, nullable=True)
    risks = Column(Text, nullable=True)
    questions = Column(Text, nullable=True)
    next_steps = Column(Text, nullable=True)
    model = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    meeting = relationship("Meeting", back_populates="summary")


class Decision(Base):
    __tablename__ = "decisions"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    text = Column(Text)

    meeting = relationship("Meeting", back_populates="decisions")


class ActionItem(Base):
    __tablename__ = "action_items"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    text = Column(Text)
    owner = Column(String, nullable=True)
    deadline = Column(String, nullable=True)
    # Transcript offset (ms) the item was derived from, when known.
    source_ms = Column(Integer, nullable=True)

    meeting = relationship("Meeting", back_populates="action_items")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    start_time = Column(Integer)  # milliseconds from start of recording
    end_time = Column(Integer)  # milliseconds from start of recording
    text = Column(Text)
    speaker = Column(String, nullable=True)
    # "whisper" | "captions" — useful when debugging transcript quality.
    source = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)

    meeting = relationship("Meeting", back_populates="transcript_segments")


class Participant(Base):
    __tablename__ = "meeting_participants"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    name = Column(String)
    first_seen_ms = Column(Integer, nullable=True)
    last_seen_ms = Column(Integer, nullable=True)

    meeting = relationship("Meeting", back_populates="participants")


class GoogleCredential(Base):
    """A user's stored Google OAuth token for the Meet REST API.

    One row per user. The refresh token is what keeps the connection alive; the
    access token is refreshed transparently. Storing client id/secret alongside
    lets us rebuild a google.oauth2 Credentials object without re-reading config.
    """

    __tablename__ = "google_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)
    google_email = Column(String, nullable=True)
    token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_uri = Column(String, nullable=True)
    client_id = Column(String, nullable=True)
    client_secret = Column(String, nullable=True)
    scopes = Column(Text, nullable=True)  # space-delimited
    expiry = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class MeetingEvent(Base):
    """Append-only bot/pipeline activity log, surfaced live in the UI."""

    __tablename__ = "meeting_events"

    id = Column(Integer, primary_key=True, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    level = Column(String, default="info")  # info | warning | error
    message = Column(Text)

    meeting = relationship("Meeting", back_populates="events")



