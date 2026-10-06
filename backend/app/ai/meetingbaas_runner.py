"""Dispatch + track a Meeting BaaS hosted bot for a meeting.

Meeting BaaS delivers results by webhook, but a local/dev backend usually has no
public URL for webhooks to reach. So this runner **polls** the bot until it
finishes, mirrors the lifecycle into our `meeting_events` log, then downloads
the transcript and runs the shared summarisation pipeline — the same output as
every other capture method.

Each job runs in its own daemon thread with a stop switch, tracked in a small
registry so the API can report status and cancel. (For multi-worker production,
prefer the real webhook + a queue; the webhook receiver already exists.)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from ..config import settings
from ..database import SessionLocal
from ..models import MeetingStatus
from . import meetingbaas
from .pipeline import finalise_meeting_timing, log_event, process_meeting_audio, set_status

# Meeting BaaS status -> (our status, human message)
_STATUS_MAP = {
    "joining": (MeetingStatus.BOT_JOINING, "Hosted bot is joining the meeting."),
    "waiting_room": (MeetingStatus.BOT_WAITING_FOR_HOST, "Hosted bot is in the waiting room."),
    "waiting": (MeetingStatus.BOT_WAITING_FOR_HOST, "Hosted bot is waiting to be admitted."),
    "in_call": (MeetingStatus.BOT_IN_CALL, "Hosted bot was admitted."),
    "in_waiting_room": (MeetingStatus.BOT_WAITING_FOR_HOST, "Hosted bot is in the waiting room."),
    "recording": (MeetingStatus.BOT_RECORDING, "Hosted bot is recording."),
    "in_progress": (MeetingStatus.BOT_RECORDING, "Hosted bot is recording."),
}


@dataclass
class BaasHandle:
    meeting_id: int
    thread: threading.Thread
    stop_event: threading.Event
    bot_id: str | None = None
    started_at: float = field(default_factory=time.time)

    @property
    def running(self) -> bool:
        return self.thread.is_alive()

    @property
    def uptime_seconds(self) -> int:
        return int(time.time() - self.started_at)


class BaasManager:
    def __init__(self) -> None:
        self._jobs: dict[int, BaasHandle] = {}
        self._lock = threading.Lock()

    def _reap(self) -> None:
        for mid in [m for m, h in self._jobs.items() if not h.running]:
            self._jobs.pop(mid, None)

    def start(self, meeting_id: int, meeting_url: str) -> tuple[bool, str]:
        with self._lock:
            self._reap()
            if meeting_id in self._jobs and self._jobs[meeting_id].running:
                return False, "A hosted bot is already running for this meeting."

            stop_event = threading.Event()
            thread = threading.Thread(
                target=_run_job,
                args=(meeting_id, meeting_url, stop_event, self),
                name=f"baas-bot-{meeting_id}",
                daemon=True,
            )
            handle = BaasHandle(meeting_id=meeting_id, thread=thread, stop_event=stop_event)
            self._jobs[meeting_id] = handle
            thread.start()
            return True, "Hosted bot dispatched."

    def set_bot_id(self, meeting_id: int, bot_id: str) -> None:
        with self._lock:
            if meeting_id in self._jobs:
                self._jobs[meeting_id].bot_id = bot_id

    def stop(self, meeting_id: int) -> tuple[bool, str]:
        with self._lock:
            handle = self._jobs.get(meeting_id)
        if not handle or not handle.running:
            return False, "No hosted bot is running for this meeting."
        handle.stop_event.set()
        return True, "Stopping the hosted bot; it will leave and process the recording."

    def get(self, meeting_id: int) -> BaasHandle | None:
        with self._lock:
            handle = self._jobs.get(meeting_id)
            return handle if handle and handle.running else None

    def is_running(self, meeting_id: int) -> bool:
        return self.get(meeting_id) is not None

    def stop_all(self) -> None:
        with self._lock:
            for handle in self._jobs.values():
                handle.stop_event.set()


baas_manager = BaasManager()


# ── idempotent finalisation (shared by poller + webhook) ──────────────────

_finalize_lock = threading.Lock()
_finalizing: set[int] = set()


def finalize(db, meeting_id: int, data: dict) -> bool:
    """Run _finish exactly once per meeting, whichever path arrives first.

    Both the background poller and the webhook receiver call this. The
    in-process guard plus a committed-status check keep them from
    double-processing the same completed meeting.
    """
    from .. import models

    with _finalize_lock:
        if meeting_id in _finalizing:
            return False
        meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
        if meeting and meeting.status == MeetingStatus.COMPLETED:
            return False
        _finalizing.add(meeting_id)
    try:
        _finish(db, meeting_id, data)
        return True
    finally:
        with _finalize_lock:
            _finalizing.discard(meeting_id)


def _run_job(
    meeting_id: int,
    meeting_url: str,
    stop_event: threading.Event,
    manager: BaasManager,
) -> None:
    db = SessionLocal()
    bot_id: str | None = None
    try:
        from .. import models

        meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
        if not meeting:
            return

        # 1. Dispatch the hosted bot.
        set_status(db, meeting, MeetingStatus.BOT_LAUNCHING)
        log_event(db, meeting_id, "Requesting a hosted bot from Meeting BaaS...")
        try:
            stream_url = None
            if settings.live_streaming_enabled:
                from .live_session import mint_live_token

                # The socket is public, so it only accepts a signed token bound
                # to this meeting.
                stream_url = settings.live_ws_url(
                    meeting_id, mint_live_token(meeting_id)
                )
            if stream_url:
                log_event(db, meeting_id, "Live in-meeting summary enabled.")
            created = meetingbaas.create_bot(
                meeting_url, transcription=True, stream_to_url=stream_url
            )
        except meetingbaas.MeetingBaasError as exc:
            meeting.error_message = str(exc)[:2000]
            set_status(db, meeting, MeetingStatus.BOT_FAILED)
            log_event(db, meeting_id, f"Could not start the hosted bot: {exc}", level="error")
            return

        bot_id = created.get("bot_id")
        meeting.external_bot_id = bot_id
        db.commit()
        manager.set_bot_id(meeting_id, bot_id)
        log_event(db, meeting_id, f"Hosted bot dispatched (id {bot_id}). Joining shortly...")
        set_status(db, meeting, MeetingStatus.BOT_JOINING)

        # 2a. Pure-webhook production mode: results arrive at the webhook
        # endpoint, so we don't poll at all — just dispatch and exit.
        if settings.meetingbaas_webhook_enabled and not settings.MEETINGBAAS_POLL_FALLBACK:
            log_event(
                db,
                meeting_id,
                "Awaiting completion via webhook (polling disabled).",
            )
            return

        # 2b. Poll until the bot finishes. When a webhook is also configured we
        # poll slowly, purely as a safety net for missed deliveries.
        poll = max(8, settings.MEETINGBAAS_POLL_SECONDS)
        if settings.meetingbaas_webhook_enabled:
            poll = max(poll, 45)
        deadline = time.time() + settings.MEETINGBAAS_MAX_MINUTES * 60
        last_status = None
        stop_requested = False

        while True:
            if stop_event.is_set() and not stop_requested:
                stop_requested = True
                log_event(db, meeting_id, "Stop requested; asking the hosted bot to leave.")
                try:
                    meetingbaas.leave_bot(bot_id)
                except Exception:
                    pass

            if time.time() > deadline:
                log_event(db, meeting_id, "Reached the hosted-bot time cap; leaving.", level="warning")
                try:
                    meetingbaas.leave_bot(bot_id)
                except Exception:
                    pass

            try:
                data = meetingbaas.get_bot(bot_id)
            except meetingbaas.MeetingBaasError as exc:
                log_event(db, meeting_id, f"Status check failed: {exc}", level="warning")
                time.sleep(poll)
                continue

            status = (data.get("status") or "").lower()

            if status in meetingbaas.TERMINAL_OK:
                log_event(db, meeting_id, "Hosted bot finished. Fetching the recording and transcript.")
                finalize(db, meeting_id, data)
                return
            if status in meetingbaas.TERMINAL_FAIL:
                msg = data.get("error_message") or data.get("error_code") or status
                # Even a failed bot may have partial artifacts.
                timeline = []
                try:
                    timeline = meetingbaas.download_transcript(data)
                except Exception:
                    pass
                if timeline:
                    log_event(db, meeting_id, f"Bot ended ({msg}) but a transcript exists; processing it.", level="warning")
                    finalize(db, meeting_id, data)
                else:
                    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
                    if meeting:
                        meeting.error_message = str(msg)[:2000]
                        set_status(db, meeting, MeetingStatus.BOT_FAILED)
                    log_event(db, meeting_id, f"Hosted bot failed: {msg}", level="error")
                return

            # In-progress: mirror the status and keep the event log fresh.
            if status and status != last_status:
                last_status = status
                mapped = _STATUS_MAP.get(status)
                meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
                if mapped and meeting:
                    set_status(db, meeting, mapped[0])
                    log_event(db, meeting_id, mapped[1])
                elif meeting:
                    log_event(db, meeting_id, f"Hosted bot status: {status}")

            time.sleep(poll)

    except Exception as exc:
        import traceback

        traceback.print_exc()
        try:
            from .. import models

            meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
            if meeting:
                meeting.error_message = str(exc)[:2000]
                set_status(db, meeting, MeetingStatus.BOT_FAILED)
            log_event(db, meeting_id, f"Hosted bot job crashed: {exc}", level="error")
        except Exception:
            pass
    finally:
        db.close()


def _finish(db, meeting_id: int, data: dict) -> None:
    """Download the transcript + recording and run the summarisation pipeline."""
    from .. import models

    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        return

    set_status(db, meeting, MeetingStatus.BOT_LEFT)
    if data.get("duration_seconds"):
        meeting.duration_ms = int(float(data["duration_seconds"]) * 1000)
    meeting.end_reason = "all_participants_left"
    db.commit()

    try:
        timeline = meetingbaas.download_transcript(data)
    except meetingbaas.MeetingBaasError as exc:
        log_event(db, meeting_id, f"Transcript download failed: {exc}", level="error")
        timeline = []

    names = meetingbaas.participant_names(data)

    # Download the recording to local storage, named after the meeting, so it
    # can be played back and re-analysed. Whisper then transcribes the actual
    # recording; the Meeting BaaS transcript supplies speaker names.
    set_status(db, meeting, MeetingStatus.PROCESSING_AUDIO)
    local_path = _download_recording(db, meeting, data)

    log_event(
        db,
        meeting_id,
        f"Recording {'saved locally; ' if local_path else ''}"
        f"transcript has {len(timeline)} segment(s), {len(names)} participant(s). "
        "Analysing the recording...",
    )

    if local_path:
        # Whisper transcribes the downloaded recording; the Meeting BaaS
        # transcript (timeline) is passed as captions for speaker attribution.
        process_meeting_audio(
            meeting_id,
            file_path=local_path,
            captions=timeline,
            participant_names=names,
            db=db,
        )
    else:
        # No recording available — fall back to the Meeting BaaS transcript.
        process_meeting_audio(
            meeting_id,
            file_path=None,
            captions=timeline,
            participant_names=names,
            db=db,
        )


def _safe_filename(name: str, fallback: str) -> str:
    """Turn a meeting title into a safe file name stem."""
    import re

    cleaned = re.sub(r"[^\w\-. ]+", "", name or "").strip().replace(" ", "_")
    cleaned = cleaned[:80].strip("._")
    return cleaned or fallback


def _download_recording(db, meeting, data: dict) -> str | None:
    """Fetch the Meeting BaaS recording into storage as '<id>_<title>.<ext>'."""
    from ..config import storage_path

    stem = f"{meeting.id}_{_safe_filename(meeting.title, f'meeting_{meeting.id}')}"
    dest_no_ext = storage_path(stem)
    try:
        path = meetingbaas.download_recording(data, dest_no_ext)
    except meetingbaas.MeetingBaasError as exc:
        log_event(db, meeting.id, f"Could not download the recording: {exc}", level="warning")
        return None

    if path:
        import os

        meeting.audio_file_path = path
        db.commit()
        size_mb = os.path.getsize(path) / 1_048_576
        log_event(
            db,
            meeting.id,
            f"Saved recording to {os.path.basename(path)} ({size_mb:.1f} MB).",
        )
    else:
        log_event(db, meeting.id, "No downloadable recording was returned.", level="warning")
    return path
