"""LensAI Bot — Complete meeting intelligence suite."""

from __future__ import annotations

from .analytics.sentiment_analyzer import analyze_sentiment
from .analytics.soundbites import extract_soundbites
from .analytics.speaker_metrics import calculate_speaker_metrics
from .assistant.ask_ai import ask_meeting_ai
from .assistant.email_drafter import draft_followup_email
from .calendar.google_calendar import GoogleCalendarClient
from .calendar.rules import CalendarEventRule
from .calendar.scheduler import CalendarScheduler
from .config import LensAIBotConfig, config
from .export.csv_export import export_action_items_csv
from .export.markdown_export import export_meeting_markdown
from .intelligence.action_extractor import extract_action_items
from .intelligence.decision_extractor import extract_decisions
from .intelligence.questions_extractor import extract_questions_and_answers
from .intelligence.risk_detector import detect_risks_and_blockers
from .intelligence.summarizer import generate_executive_summary
from .runner.bot_orchestrator import orchestrator
from .runner.meet_bot import MeetBotRunner
from .transcription.diarization import attribute_speakers
from .transcription.whisper_engine import WhisperEngine

__all__ = [
    "config",
    "LensAIBotConfig",
    "MeetBotRunner",
    "orchestrator",
    "WhisperEngine",
    "attribute_speakers",
    "generate_executive_summary",
    "extract_action_items",
    "extract_decisions",
    "extract_questions_and_answers",
    "detect_risks_and_blockers",
    "calculate_speaker_metrics",
    "analyze_sentiment",
    "extract_soundbites",
    "ask_meeting_ai",
    "draft_followup_email",
    "export_meeting_markdown",
    "export_action_items_csv",
    "GoogleCalendarClient",
    "CalendarEventRule",
    "CalendarScheduler",
]
