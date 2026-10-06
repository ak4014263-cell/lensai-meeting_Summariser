"""Configuration settings for LensAI Bot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class LensAIBotConfig:
    # ── Bot Identity & In-Meeting Behavior ──
    bot_name: str = os.getenv("LENSAI_BOT_NAME", "LensAI Notetaker")
    bot_avatar_url: str = os.getenv("LENSAI_BOT_AVATAR_URL", "")
    send_greeting_chat: bool = os.getenv("LENSAI_SEND_GREETING", "true").lower() in ("1", "true", "yes")
    greeting_message: str = os.getenv(
        "LENSAI_GREETING_MESSAGE",
        "👋 Hello! LensAI Notetaker is recording and transcribing this meeting. Summary and action items will be generated automatically.",
    )
    
    # ── Auto-Leave & Timing Thresholds ──
    auto_leave_on_empty: bool = True
    empty_room_grace_seconds: int = 30
    max_meeting_duration_minutes: int = int(os.getenv("LENSAI_MAX_DURATION_MINS", "180"))
    join_ahead_seconds: int = int(os.getenv("LENSAI_JOIN_AHEAD_SECONDS", "120"))  # 2 mins ahead
    
    # ── AI & LLM Settings (Ollama) ──
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2")
    ollama_temperature: float = 0.2
    
    # ── Whisper & Transcription ──
    whisper_model_size: str = os.getenv("WHISPER_MODEL", "base")
    whisper_device: str = os.getenv("WHISPER_DEVICE", "cpu")
    whisper_compute_type: str = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    whisper_beam_size: int = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
    # Advanced quality settings
    whisper_vad_filter: bool = os.getenv("WHISPER_VAD_FILTER", "true").lower() in ("1", "true", "yes")
    whisper_condition_on_previous_text: bool = os.getenv("WHISPER_CONDITION_ON_PREVIOUS_TEXT", "true").lower() in ("1", "true", "yes")
    whisper_patience: float = float(os.getenv("WHISPER_PATIENCE", "1.0"))
    whisper_length_penalty: float = float(os.getenv("WHISPER_LENGTH_PENALTY", "1.0"))
    whisper_temperature: float = float(os.getenv("WHISPER_TEMPERATURE", "0.0"))
    whisper_compression_ratio_threshold: float = float(os.getenv("WHISPER_COMPRESSION_RATIO_THRESHOLD", "2.4"))
    whisper_log_prob_threshold: float = float(os.getenv("WHISPER_LOG_PROB_THRESHOLD", "-1.0"))
    whisper_no_speech_threshold: float = float(os.getenv("WHISPER_NO_SPEECH_THRESHOLD", "0.6"))
    
    # ── Calendar & Auto-Join Rules ──
    calendar_sync_interval_seconds: int = 60
    auto_record_default: bool = True
    record_only_with_links: bool = True
    record_only_confirmed: bool = False
    
    # ── Storage ──
    storage_dir: Path = field(
        default_factory=lambda: Path(os.getenv("LENSAI_STORAGE_DIR", str(Path(__file__).resolve().parent / "storage")))
    )

    def __post_init__(self):
        self.storage_dir.mkdir(parents=True, exist_ok=True)


config = LensAIBotConfig()
