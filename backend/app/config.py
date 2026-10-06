"""Central, environment-driven configuration for the AI Meeting Assistant.

Every knob the meeting bot / AI pipeline needs lives here so behaviour can be
tuned without touching code. Values are read from the process environment and
from a `.env` file next to the `backend/` folder if one exists.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv is optional; config still works without it.
    from dotenv import dotenv_values, load_dotenv

    # Real environment variables intentionally win over .env (12-factor), but a
    # stale exported variable shadowing .env is very hard to debug, so warn when
    # the two disagree on a credential.
    _dotenv_file = Path(__file__).resolve().parent.parent / ".env"
    _file_values = dotenv_values(_dotenv_file) if _dotenv_file.exists() else {}
    load_dotenv()
    for _name in ("OPENAI_API_KEY", "MEETINGBAAS_API_KEY", "SECRET_KEY"):
        _from_file = (_file_values.get(_name) or "").strip()
        _from_env = (os.environ.get(_name) or "").strip()
        if _from_file and _from_env and _from_file != _from_env:
            print(
                f"[config] WARNING: {_name} is set in both the OS environment and "
                f".env, with different values. The OS environment wins, so the "
                f".env value is being ignored. Unset the OS variable "
                f'(Windows: `Remove-Item Env:{_name}`) to use .env.'
            )
except Exception:  # pragma: no cover
    pass


import sys

BACKEND_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BACKEND_DIR.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))


def _str(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_str(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_str(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return _str(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


class Settings:
    # ── Storage ──────────────────────────────────────────────────────────
    # Absolute so background threads are not affected by the process CWD.
    STORAGE_DIR: Path = Path(_str("STORAGE_DIR", str(BACKEND_DIR / "storage")))

    # ── Ollama (LLM) ─────────────────────────────────────────────────────
    OLLAMA_HOST: str = _str("OLLAMA_HOST", "http://127.0.0.1:11434")
    OLLAMA_MODEL: str = _str("OLLAMA_MODEL", "llama3.2")
    OLLAMA_NUM_CTX: int = _int("OLLAMA_NUM_CTX", 8192)  # Increased for longer summaries
    OLLAMA_TEMPERATURE: float = _float("OLLAMA_TEMPERATURE", 0.3)  # Slightly higher for more detailed output
    OLLAMA_TIMEOUT: int = _int("OLLAMA_TIMEOUT", 600)  # Increased timeout for longer generation
    # Characters of transcript per map-reduce chunk (long meetings).
    LLM_CHUNK_CHARS: int = _int("LLM_CHUNK_CHARS", 16000)  # Larger chunks for more context
    LLM_CHUNK_OVERLAP_CHARS: int = _int("LLM_CHUNK_OVERLAP_CHARS", 800)  # More overlap
    LLM_MAX_CHUNKS: int = _int("LLM_MAX_CHUNKS", 50)  # Allow more chunks

    # ── Speech to text backend selection ─────────────────────────────────
    # "local"       → faster-whisper on this machine (nothing leaves the host)
    # "openai"      → OpenAI /v1/audio/transcriptions
    # "huggingface" → Hugging Face Transformers (best quality with HF token)
    STT_BACKEND: str = _str("STT_BACKEND", "local").lower()
    
    # ── Hugging Face (speech to text) ────────────────────────────────────
    HUGGINGFACE_TOKEN: str = _str("HUGGINGFACE_TOKEN", "")
    # Model options:
    #   openai/whisper-large-v3 (best quality, slower)
    #   distil-whisper/distil-large-v3 (6x faster, 98% quality)
    #   openai/whisper-large-v3-turbo (balanced)
    HUGGINGFACE_MODEL: str = _str("HUGGINGFACE_MODEL", "openai/whisper-large-v3")

    # ── OpenAI (speech to text) ──────────────────────────────────────────
    OPENAI_API_KEY: str = _str("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = _str("OPENAI_BASE_URL", "https://api.openai.com/v1")
    # whisper-1 is the only OpenAI STT model that returns segment timestamps.
    # The gpt-4o-transcribe family rejects response_format=verbose_json, and
    # pipeline.label_speakers() needs per-segment start/end to attribute
    # speakers against the meeting's caption timeline.
    OPENAI_STT_MODEL: str = _str("OPENAI_STT_MODEL", "whisper-1")
    OPENAI_STT_TIMEOUT: int = _int("OPENAI_STT_TIMEOUT", 600)
    # The API rejects uploads over 25 MB; stay under it with a safety margin.
    OPENAI_MAX_UPLOAD_MB: float = _float("OPENAI_MAX_UPLOAD_MB", 24.0)
    # Oversized or unsupported audio is re-encoded and split into windows of
    # this many seconds (16 kHz mono WAV ≈ 1.9 MB/minute, so 600s ≈ 19 MB).
    OPENAI_CHUNK_SECONDS: int = _int("OPENAI_CHUNK_SECONDS", 600)

    # ── Whisper (speech to text) ─────────────────────────────────────────
    # Models: tiny, base, small, medium, large-v2, large-v3
    # Recommended: large-v3 for maximum accuracy, medium for speed
    WHISPER_MODEL: str = _str("WHISPER_MODEL", "large-v3")
    WHISPER_DEVICE: str = _str("WHISPER_DEVICE", "cpu")
    WHISPER_COMPUTE_TYPE: str = _str("WHISPER_COMPUTE_TYPE", "int8")
    # Increase beam size for better accuracy (1-5, higher = more accurate but slower)
    WHISPER_BEAM_SIZE: int = _int("WHISPER_BEAM_SIZE", 5)
    # Leave None for automatic language detection
    WHISPER_LANGUAGE: str | None = os.getenv("WHISPER_LANGUAGE") or None
    # VAD (Voice Activity Detection) filters silence for better accuracy
    WHISPER_VAD: bool = _bool("WHISPER_VAD", True)

    # ── Speaker Identification ───────────────────────────────────────────
    # Enhanced speaker mapping from Google Meet participant list
    ENABLE_SPEAKER_MAPPING: bool = _bool("ENABLE_SPEAKER_MAPPING", True)

    # ── Meeting bot ──────────────────────────────────────────────────────
    BOT_DISPLAY_NAME: str = _str("BOT_DISPLAY_NAME", "AI Notetaker")
    # Google Meet is hostile to headless Chrome. Keep headed on desktop; on a
    # Linux server run under Xvfb, or flip this to 1 and accept the risk.
    BOT_HEADLESS: bool = _bool("BOT_HEADLESS", False)
    # Delay (seconds) after bot leaves before starting transcription/summary.
    # Allows audio buffers to flush and browser to clean up properly.
    BOT_POST_CALL_DELAY: int = _int("BOT_POST_CALL_DELAY", 5)
    # "chrome" / "msedge" use a locally installed browser (best Meet
    # compatibility). Empty string uses Playwright's bundled Chromium.
    BOT_BROWSER_CHANNEL: str = _str("BOT_BROWSER_CHANNEL", "")
    # Point at a Chrome profile dir to have the bot join as a signed-in Google
    # account (often skips the waiting room entirely).
    BOT_USER_DATA_DIR: str = _str("BOT_USER_DATA_DIR", "")
    # Mute the browser's speakers. The WebAudio capture graph keeps working.
    BOT_MUTE_AUDIO: bool = _bool("BOT_MUTE_AUDIO", True)

    # How long to wait for the host to admit the bot from the waiting room.
    BOT_ADMISSION_TIMEOUT: int = _int("BOT_ADMISSION_TIMEOUT", 300)
    # How long to wait, after being admitted, for at least one human to appear.
    BOT_WAIT_FOR_PEOPLE: int = _int("BOT_WAIT_FOR_PEOPLE", 60)
    # Once humans have been seen, how long they must all be gone before the
    # bot decides the meeting is over.
    BOT_ALONE_GRACE_SECONDS: int = _int("BOT_ALONE_GRACE_SECONDS", 5)
    # Absolute safety cap on a single recording.
    BOT_MAX_MEETING_MINUTES: int = _int("BOT_MAX_MEETING_MINUTES", 180)
    # Participant/health poll interval.
    BOT_POLL_SECONDS: int = _int("BOT_POLL_SECONDS", 5)
    # MediaRecorder flush interval, milliseconds.
    BOT_AUDIO_CHUNK_MS: int = _int("BOT_AUDIO_CHUNK_MS", 4000)
    BOT_AUDIO_BITRATE: int = _int("BOT_AUDIO_BITRATE", 96000)
    # Save debug screenshots of each stage into STORAGE_DIR.
    BOT_DEBUG_SCREENSHOTS: bool = _bool("BOT_DEBUG_SCREENSHOTS", True)
    # Meetings the bot may join at the same time.
    BOT_MAX_CONCURRENT: int = _int("BOT_MAX_CONCURRENT", 3)

    # ── Auth ─────────────────────────────────────────────────────────────
    # Keeps existing dev tokens valid. Override via the environment in any
    # deployment that is reachable by anyone other than you.
    SECRET_KEY: str = _str("SECRET_KEY", "supersecretkey_change_in_production")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = _int("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24)

    # ── Frontend ─────────────────────────────────────────────────────────
    # Where the OAuth callback sends the user's browser back to.
    FRONTEND_BASE_URL: str = _str("FRONTEND_BASE_URL", "http://localhost:3000")
    # Also used as FRONTEND_URL for email links
    FRONTEND_URL: str = _str("FRONTEND_URL", FRONTEND_BASE_URL)

    # ── Email / SMTP ─────────────────────────────────────────────────────
    # Send meeting recap emails similar to Fireflies.ai
    SMTP_HOST: str = _str("SMTP_HOST", "")
    SMTP_PORT: int = _int("SMTP_PORT", 587)
    SMTP_TLS: bool = _bool("SMTP_TLS", True)
    SMTP_USERNAME: str = _str("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = _str("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL: str = _str("SMTP_FROM_EMAIL", "noreply@aimeetingassistant.com")
    SMTP_FROM_NAME: str = _str("SMTP_FROM_NAME", "AI Meeting Assistant")
    # Enable/disable email notifications
    SEND_EMAIL_NOTIFICATIONS: bool = _bool("SEND_EMAIL_NOTIFICATIONS", True)

    # ── Google OAuth / Meet REST API ─────────────────────────────────────
    # Fill these from a Google Cloud OAuth 2.0 client (see docs/GOOGLE_MEET_API.md).
    # Either set the two vars below, or drop a client_secret.json next to the
    # backend/ folder and leave them blank.
    GOOGLE_CLIENT_ID: str = _str("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = _str("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_CLIENT_SECRET_FILE: str = _str(
        "GOOGLE_CLIENT_SECRET_FILE", str(BACKEND_DIR / "client_secret.json")
    )
    # Must be added verbatim to the OAuth client's "Authorized redirect URIs".
    GOOGLE_REDIRECT_URI: str = _str(
        "GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/integrations/google/callback"
    )
    # Space-scoped read of Meet conference records + transcripts and calendar events.
    GOOGLE_SCOPES: list[str] = [
        s
        for s in _str(
            "GOOGLE_SCOPES",
            "openid "
            "https://www.googleapis.com/auth/userinfo.email "
            "https://www.googleapis.com/auth/calendar.events "
            "https://www.googleapis.com/auth/calendar.events.readonly "
            # created: create/configure meeting spaces. readonly: read
            # conference records + transcripts afterwards.
            "https://www.googleapis.com/auth/meetings.space.created "
            "https://www.googleapis.com/auth/meetings.space.readonly",
        ).split()
        if s
    ]
    BOT_EMAIL: str = _str("BOT_EMAIL", "daddy202028@gmail.com")

    # Whether creating a meeting from the portal makes Google email the guests.
    # Maps to the Calendar API's sendUpdates: all | externalOnly | none.
    # The API itself defaults to "none", so this must be sent explicitly.
    CALENDAR_SEND_INVITES: str = _str("CALENDAR_SEND_INVITES", "all").lower()

    # ── Meeting BaaS (hosted bot service) ────────────────────────────────
    MEETINGBAAS_API_KEY: str = _str("MEETINGBAAS_API_KEY", "")
    MEETINGBAAS_BASE_URL: str = _str("MEETINGBAAS_BASE_URL", "https://api.meetingbaas.com")
    MEETINGBAAS_BOT_NAME: str = _str("MEETINGBAAS_BOT_NAME", "AI Notetaker")
    # Public https URL of the bot's avatar shown in the meeting. Meeting BaaS
    # fetches it server-side, so it must be publicly reachable (not localhost).
    # A PNG/JPG is safest. Leave blank for no avatar.
    MEETINGBAAS_BOT_IMAGE_URL: str = _str("MEETINGBAAS_BOT_IMAGE_URL", "")
    # Public https URL Meeting BaaS should POST webhooks to. Blank = poll instead.
    MEETINGBAAS_WEBHOOK_URL: str = _str("MEETINGBAAS_WEBHOOK_URL", "")
    # Secret used to verify incoming webhook signatures. For Standard-Webhooks /
    # svix style secrets use the `whsec_...` value. Leave blank to fall back to
    # matching the API key header.
    MEETINGBAAS_WEBHOOK_SECRET: str = _str("MEETINGBAAS_WEBHOOK_SECRET", "")
    MEETINGBAAS_POLL_SECONDS: int = _int("MEETINGBAAS_POLL_SECONDS", 15)
    MEETINGBAAS_MAX_MINUTES: int = _int("MEETINGBAAS_MAX_MINUTES", 240)
    # When a webhook URL is set, keep a slow background poll as a safety net in
    # case a delivery is missed. Set false for pure-webhook production.
    MEETINGBAAS_POLL_FALLBACK: bool = _bool("MEETINGBAAS_POLL_FALLBACK", True)

    @property
    def meetingbaas_webhook_enabled(self) -> bool:
        return bool(self.MEETINGBAAS_WEBHOOK_URL)

    # ── Live (in-meeting) transcription & summary ─────────────────────────
    # Meeting BaaS streams the call audio to a WebSocket on OUR server, so this
    # must be a PUBLIC wss:// base URL (use ngrok/cloudflared in dev), e.g.
    #   PUBLIC_WS_BASE_URL=wss://abc123.ngrok-free.app
    PUBLIC_WS_BASE_URL: str = _str("PUBLIC_WS_BASE_URL", "")
    LIVE_ENABLED: bool = _bool("LIVE_ENABLED", True)
    # Audio is transcribed in rolling windows of this many seconds.
    LIVE_CHUNK_SECONDS: int = _int("LIVE_CHUNK_SECONDS", 15)
    # Regenerate the live summary at most this often (seconds).
    LIVE_SUMMARY_INTERVAL: int = _int("LIVE_SUMMARY_INTERVAL", 45)
    # Meeting BaaS streams PCM at this sample rate (mono, s16le).
    LIVE_SAMPLE_RATE: int = _int("LIVE_SAMPLE_RATE", 16000)

    @property
    def live_streaming_enabled(self) -> bool:
        return bool(self.LIVE_ENABLED and self.PUBLIC_WS_BASE_URL)

    def live_ws_url(self, meeting_id: int, token: str | None = None) -> str:
        """Public URL the hosted bot streams audio to.

        The endpoint is internet-facing, so pass the signed token from
        `ai.live_session.mint_live_token()`; without it the server refuses the
        connection.
        """
        base = self.PUBLIC_WS_BASE_URL.rstrip("/")
        url = f"{base}/ws/live/{meeting_id}"
        return f"{url}?token={token}" if token else url

    @property
    def openai_stt_configured(self) -> bool:
        return bool(self.OPENAI_API_KEY)

    @property
    def use_openai_stt(self) -> bool:
        """True when transcription should go to OpenAI rather than local Whisper."""
        return self.STT_BACKEND == "openai" and self.openai_stt_configured

    @property
    def meetingbaas_configured(self) -> bool:
        return bool(self.MEETINGBAAS_API_KEY)

    @property
    def google_configured(self) -> bool:
        if self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET:
            return True
        return os.path.exists(self.GOOGLE_CLIENT_SECRET_FILE)

    @property
    def max_meeting_seconds(self) -> int:
        return self.BOT_MAX_MEETING_MINUTES * 60


settings = Settings()
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def storage_path(*parts: str) -> str:
    """Absolute path inside the storage directory."""
    return str(settings.STORAGE_DIR.joinpath(*parts))
