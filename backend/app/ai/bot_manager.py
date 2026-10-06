"""Lifecycle manager for running meeting bots.

A bot occupies a browser for the entire length of a call, which can be hours.
FastAPI's `BackgroundTasks` would pin one of the (small) threadpool workers for
that whole time and starves the rest of the API, so each bot instead gets a
dedicated daemon thread with its own asyncio event loop.

The registry lets the API report on and cancel in-flight bots. It is per
process, which is the right scope for the single-process dev/MVP deployment.
Moving to multiple API workers means moving this to Redis + a worker service —
the call sites would not have to change.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from ..config import settings


@dataclass
class BotHandle:
    meeting_id: int
    meet_url: str
    thread: threading.Thread
    stop_event: threading.Event
    started_at: float = field(default_factory=time.time)

    @property
    def running(self) -> bool:
        return self.thread.is_alive()

    @property
    def uptime_seconds(self) -> int:
        return int(time.time() - self.started_at)


class BotManager:
    def __init__(self) -> None:
        self._bots: dict[int, BotHandle] = {}
        self._lock = threading.Lock()

    # ── internal ─────────────────────────────────────────────────────────

    def _reap(self) -> None:
        """Drop handles whose threads have finished."""
        for meeting_id in [mid for mid, h in self._bots.items() if not h.running]:
            self._bots.pop(meeting_id, None)

    # ── public API ───────────────────────────────────────────────────────

    def start(self, meeting_id: int, meet_url: str) -> tuple[bool, str]:
        """Launch a bot for a meeting. Returns ``(started, message)``."""
        from .bot import run_bot_task

        with self._lock:
            self._reap()

            existing = self._bots.get(meeting_id)
            if existing and existing.running:
                return False, "A bot is already running for this meeting."

            active = sum(1 for h in self._bots.values() if h.running)
            if active >= settings.BOT_MAX_CONCURRENT:
                return False, (
                    f"The bot limit is reached ({active}/{settings.BOT_MAX_CONCURRENT} "
                    "meetings in progress). Try again once one finishes."
                )

            stop_event = threading.Event()
            thread = threading.Thread(
                target=run_bot_task,
                args=(meeting_id, meet_url, stop_event),
                name=f"meeting-bot-{meeting_id}",
                daemon=True,
            )
            self._bots[meeting_id] = BotHandle(
                meeting_id=meeting_id,
                meet_url=meet_url,
                thread=thread,
                stop_event=stop_event,
            )
            thread.start()
            return True, "Bot dispatched."

    def stop(self, meeting_id: int) -> tuple[bool, str]:
        """Ask a bot to leave the call early and process what it captured."""
        with self._lock:
            handle = self._bots.get(meeting_id)
            if not handle or not handle.running:
                return False, "No bot is currently running for this meeting."
            handle.stop_event.set()
            return True, (
                "Stopping the bot. It will leave the call and process the recording."
            )

    def get(self, meeting_id: int) -> Optional[BotHandle]:
        with self._lock:
            handle = self._bots.get(meeting_id)
            return handle if handle and handle.running else None

    def is_running(self, meeting_id: int) -> bool:
        return self.get(meeting_id) is not None

    def active(self) -> list[BotHandle]:
        with self._lock:
            self._reap()
            return [h for h in self._bots.values() if h.running]

    def stop_all(self) -> None:
        """Signal every bot to wind down (used on application shutdown)."""
        with self._lock:
            for handle in self._bots.values():
                handle.stop_event.set()


bot_manager = BotManager()
