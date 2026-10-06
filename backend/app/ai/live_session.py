"""Live, in-meeting transcription and rolling summary.

Meeting BaaS streams the call's audio to a WebSocket on our server
(`/ws/live/{meeting_id}`) while the meeting is happening. This module turns that
stream into a live transcript and a periodically-refreshed "live summary" the UI
can show mid-call — instead of waiting for the meeting to end.

Pipeline per meeting:

    PCM audio frames (16 kHz mono s16le)
        └─► rolling buffer (LIVE_CHUNK_SECONDS)
              └─► faster-whisper on the buffer  ──► append to live transcript
                    └─► every LIVE_SUMMARY_INTERVAL seconds:
                          Ollama "live notes" pass ──► Meeting.live_summary

Design notes
------------
* Whisper runs on a **worker thread**, never on the asyncio event loop, so
  receiving audio is never blocked by transcription.
* Only one transcription and one summary run at a time per meeting; if audio
  arrives faster than we can process it we drop the oldest buffered audio rather
  than growing memory without bound.
* Everything is best-effort: a failure here must never disturb the recording or
  the final (authoritative) post-meeting summary.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from ..config import settings
from ..database import SessionLocal
from .. import models

# ── stream authorisation ─────────────────────────────────────────────────
#
# The live audio socket is reachable from the public internet (the hosted bot
# has to be able to dial in), so the meeting id in the path cannot be trusted on
# its own — without a check, anyone could stream audio into any meeting's
# transcript. We therefore hand the provider a URL carrying a short-lived token
# bound to that one meeting, signed with the app SECRET_KEY. Same approach the
# Google OAuth `state` already uses.

_LIVE_TOKEN_ALG = "HS256"
_LIVE_TOKEN_PURPOSE = "live_ws"


def _live_token_ttl_minutes() -> int:
    """Long enough to outlast the meeting the token was minted for."""
    longest = max(
        settings.MEETINGBAAS_MAX_MINUTES,
        settings.BOT_MAX_MEETING_MINUTES,
    )
    return longest + 30  # slack for queueing, waiting rooms and reconnects


def mint_live_token(meeting_id: int) -> str:
    """Signed token authorising an audio stream for exactly one meeting."""
    from jose import jwt

    payload = {
        "purpose": _LIVE_TOKEN_PURPOSE,
        "mid": int(meeting_id),
        "exp": datetime.now(timezone.utc)
        + timedelta(minutes=_live_token_ttl_minutes()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_LIVE_TOKEN_ALG)


def verify_live_token(meeting_id: int, token: str | None) -> tuple[bool, str]:
    """Validate a live-stream token. Returns ``(ok, reason)``."""
    if not token:
        return False, "missing token"

    from jose import JWTError, jwt

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[_LIVE_TOKEN_ALG])
    except JWTError as exc:
        return False, f"invalid token ({exc})"

    if payload.get("purpose") != _LIVE_TOKEN_PURPOSE:
        return False, "token was not issued for audio streaming"
    if int(payload.get("mid", -1)) != int(meeting_id):
        return False, "token does not match this meeting"
    return True, "ok"

# Bytes per second of 16-bit mono PCM at the configured rate.
def _bytes_per_second() -> int:
    return settings.LIVE_SAMPLE_RATE * 2


class LiveSession:
    """Accumulates streamed audio for one meeting and produces live output."""

    def __init__(self, meeting_id: int):
        self.meeting_id = meeting_id
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self.transcript_parts: list[str] = []
        self.started_at = time.time()
        self.last_summary_at = 0.0
        self.bytes_received = 0
        self._busy = False
        self._closed = False

    # ── audio & captions intake ──────────────────────────────────────────

    def add_caption(self, speaker: str, text: str) -> None:
        """Feed live captions directly into the live transcript and refresh summary."""
        if self._closed or not text:
            return
        speaker_clean = (speaker or "").strip() or "Speaker"
        text_clean = (text or "").strip()
        if not text_clean:
            return
        line = f"{speaker_clean}: {text_clean}"
        with self._lock:
            if self.transcript_parts and self.transcript_parts[-1] == line:
                return
            self.transcript_parts.append(line)
        self._persist_transcript()
        self._maybe_summarise()

    def add_audio(self, data: bytes) -> None:
        if self._closed or not data:
            return
        with self._lock:
            self._buffer.extend(data)
            self.bytes_received += len(data)
            # Cap the buffer at ~4 chunks so a slow machine can't balloon memory.
            cap = _bytes_per_second() * settings.LIVE_CHUNK_SECONDS * 4
            if len(self._buffer) > cap:
                del self._buffer[: len(self._buffer) - cap]

    def _take_chunk(self) -> bytes | None:
        """Pop a full chunk of audio if one is ready."""
        need = _bytes_per_second() * settings.LIVE_CHUNK_SECONDS
        with self._lock:
            if len(self._buffer) < need:
                return None
            chunk = bytes(self._buffer[:need])
            del self._buffer[:need]
            return chunk

    def flush_remaining(self) -> bytes | None:
        """Return whatever audio is left (used when the stream closes)."""
        with self._lock:
            if len(self._buffer) < _bytes_per_second():  # < 1s is not worth it
                return None
            chunk = bytes(self._buffer)
            self._buffer.clear()
            return chunk

    # ── processing ───────────────────────────────────────────────────────

    def maybe_process(self) -> None:
        """Transcribe a ready chunk and refresh the summary, on a worker thread."""
        if self._busy or self._closed:
            return
        need = _bytes_per_second() * settings.LIVE_CHUNK_SECONDS
        with self._lock:
            if len(self._buffer) < need:
                return
        self._busy = True
        threading.Thread(target=self._process_loop, daemon=True,
                         name=f"live-{self.meeting_id}").start()

    def _process_loop(self) -> None:
        try:
            while not self._closed:
                chunk = self._take_chunk()
                if chunk is None:
                    break
                text = self._transcribe(chunk)
                if text:
                    self.transcript_parts.append(text)
                    self._persist_transcript()
                self._maybe_summarise()
        except Exception as exc:  # never let a live failure escape
            print(f"[live {self.meeting_id}] processing error: {exc}")
        finally:
            self._busy = False

    def _transcribe(self, pcm: bytes) -> str:
        """Transcribe one raw-PCM window, honouring the configured STT backend."""
        if settings.use_openai_stt:
            try:
                from .openai_stt import transcribe_pcm

                return transcribe_pcm(pcm, settings.LIVE_SAMPLE_RATE)
            except Exception as exc:
                # Live output is best-effort; fall through to the local model
                # rather than losing the window entirely.
                print(
                    f"[live {self.meeting_id}] OpenAI live transcribe failed "
                    f"({exc}); using local Whisper for this window."
                )

        return self._transcribe_local(pcm)

    def _transcribe_local(self, pcm: bytes) -> str:
        """Whisper on raw PCM (no ffmpeg needed — we hand it a float32 array)."""
        try:
            import numpy as np

            from .transcription import get_model

            audio = np.frombuffer(pcm, dtype=np.int16).astype("float32") / 32768.0
            if audio.size == 0:
                return ""
            model = get_model()
            segments, _info = model.transcribe(
                audio,
                beam_size=settings.WHISPER_BEAM_SIZE,  # use configured beam size for better accuracy
                vad_filter=True,
                condition_on_previous_text=False,
                language=settings.WHISPER_LANGUAGE or None,
            )
            return " ".join((s.text or "").strip() for s in segments).strip()
        except Exception as exc:
            print(f"[live {self.meeting_id}] transcribe failed: {exc}")
            return ""

    def live_text(self) -> str:
        return " ".join(self.transcript_parts).strip()

    def _persist_transcript(self) -> None:
        db = SessionLocal()
        try:
            meeting = db.query(models.Meeting).filter(
                models.Meeting.id == self.meeting_id
            ).first()
            if meeting:
                meeting.live_transcript = self.live_text()[-20000:]
                meeting.live_updated_at = datetime.utcnow()
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def _maybe_summarise(self) -> None:
        now = time.time()
        if now - self.last_summary_at < settings.LIVE_SUMMARY_INTERVAL:
            return
        text = self.live_text()
        if len(text) < 60:  # Start generating live summaries once initial words are spoken
            return
        self.last_summary_at = now

        summary = None
        # 1. Try local Ollama if available
        try:
            from .ollama_service import summarise_live
            summary = summarise_live(text)
        except Exception as exc:
            pass

        # 2. Fall back to free built-in extractive live summarizer
        if not summary:
            summary = _generate_heuristic_live_summary(self.transcript_parts)

        if not summary:
            return

        summary = _clean_live_summary_speakers(summary)

        db = SessionLocal()
        try:
            meeting = db.query(models.Meeting).filter(
                models.Meeting.id == self.meeting_id
            ).first()
            if meeting:
                meeting.live_summary = summary
                meeting.live_updated_at = datetime.utcnow()
                db.commit()
                print(f"[live {self.meeting_id}] live summary updated "
                      f"({len(text)} chars of transcript)")
        except Exception:
            db.rollback()
        finally:
            db.close()

    # ── shutdown ─────────────────────────────────────────────────────────

    def close(self) -> None:
        """Stream ended: transcribe the tail and do a final live summary."""
        tail = self.flush_remaining()
        if tail:
            text = self._transcribe(tail)
            if text:
                self.transcript_parts.append(text)
                self._persist_transcript()
        # Force one last summary regardless of the interval.
        self.last_summary_at = 0.0
        try:
            self._maybe_summarise()
        except Exception:
            pass
        self._closed = True


class LiveManager:
    """Registry of active live sessions, keyed by meeting id."""

    def __init__(self) -> None:
        self._sessions: dict[int, LiveSession] = {}
        self._lock = threading.Lock()

    def get_or_create(self, meeting_id: int) -> LiveSession:
        with self._lock:
            session = self._sessions.get(meeting_id)
            if session is None or session._closed:
                session = LiveSession(meeting_id)
                self._sessions[meeting_id] = session
            return session

    def get(self, meeting_id: int) -> LiveSession | None:
        with self._lock:
            return self._sessions.get(meeting_id)

    def close(self, meeting_id: int) -> None:
        with self._lock:
            session = self._sessions.pop(meeting_id, None)
        if session:
            try:
                session.close()
            except Exception:
                pass


def _strip_speaker_prefix(text: str) -> str:
    """Remove speaker attribution prefix from a text string if present.

    e.g. 'Alice: We need to update the plan.' -> 'We need to update the plan.'
    """
    text = text.strip()
    if ":" in text:
        parts = text.split(":", 1)
        prefix = parts[0].strip()
        remainder = parts[1].strip()
        # Ensure prefix looks like a speaker name (reasonable length, not a URL)
        if remainder and len(prefix) < 50 and not prefix.startswith("http"):
            return remainder
    return text


def _clean_live_summary_speakers(summary: str) -> str:
    """Ensure speaker names are only shown in Overview, and removed from Key and Discussion."""
    if not summary:
        return ""

    import re

    # Handle legacy "So far: Active discussion involving Alice, Bob."
    match_so_far = re.search(r"So far:\s*Active discussion(?: involving ([^\.\n]+))?\.", summary, re.IGNORECASE)
    if match_so_far:
        speakers = match_so_far.group(1)
        overview_line = f"Overview: {speakers.strip()}" if speakers else "Overview: Participants"
        summary = summary.replace(match_so_far.group(0), f"{overview_line}\n\nDiscussion:\nActive discussion.")

    lines = summary.split("\n")
    cleaned_lines = []
    current_section = ""

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("overview:"):
            current_section = "overview"
            cleaned_lines.append(line)
            continue
        elif lower.startswith("key points:") or lower.startswith("key highlights:"):
            current_section = "key"
            cleaned_lines.append(line)
            continue
        elif lower.startswith("recent discussion:") or lower.startswith("discussion:"):
            current_section = "discussion"
            cleaned_lines.append(line)
            continue
        elif any(lower.startswith(sec) for sec in ["decisions:", "action items:", "next topics"]):
            current_section = ""

        if current_section in ("key", "discussion") and stripped.startswith(("•", "-", "*")):
            # Remove speaker prefix like "• Alice: ..." or "- [Bob]: ..."
            cleaned_bullet = re.sub(
                r"^([•\-\*]\s*)(?:\[?[A-Za-z0-9_\s]{1,35}\]?:\s*)(.+)$",
                r"\1\2",
                stripped
            )
            cleaned_lines.append(cleaned_bullet)
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def _generate_heuristic_live_summary(parts: list[str]) -> str:
    """Fast, 100% free extractive live summary when no local LLM is active."""
    if not parts:
        return ""

    # Extract unique speakers for Overview
    speakers = []
    for p in parts:
        if ":" in p:
            s = p.split(":", 1)[0].strip()
            if s and s not in speakers:
                speakers.append(s)

    speakers_str = ", ".join(speakers) if speakers else "Participants"

    # Detect action items
    action_keywords = ["will", "need to", "action", "task", "follow up", "deadline", "by tomorrow", "by next", "todo", "assigned to", "please send"]
    actions = []
    # Detect decisions or agreements
    decision_keywords = ["agreed", "decided", "let's go with", "approved", "finalized", "resolved", "plan is"]
    decisions = []
    # Key points (substantive sentences without speaker prefixes)
    key_points = []

    for p in parts:
        clean_p = _strip_speaker_prefix(p)
        lower = clean_p.lower()
        if any(k in lower for k in action_keywords):
            if len(clean_p) > 15 and clean_p not in actions:
                actions.append(clean_p)
        elif any(k in lower for k in decision_keywords):
            if len(clean_p) > 15 and clean_p not in decisions:
                decisions.append(clean_p)
        elif len(clean_p) > 25 and "?" not in clean_p:
            if len(key_points) < 5 and clean_p not in key_points:
                key_points.append(clean_p)

    lines = [
        f"Overview: {speakers_str}",
        "\nDiscussion:\nActive discussion.",
    ]
    if key_points:
        lines.append("\nKey Highlights:")
        for kp in key_points[-3:]:
            lines.append(f"• {kp}")
    if decisions:
        lines.append("\nDecisions:")
        for d in decisions[-3:]:
            lines.append(f"• {d}")
    if actions:
        lines.append("\nAction Items:")
        for a in actions[-3:]:
            lines.append(f"• {a}")
    elif not key_points and not decisions:
        lines.append("\nRecent discussion:")
        for p in parts[-3:]:
            lines.append(f"• {_strip_speaker_prefix(p)}")

    raw = "\n".join(lines).strip()
    return _clean_live_summary_speakers(raw)


live_manager = LiveManager()

