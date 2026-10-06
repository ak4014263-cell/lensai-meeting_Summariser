"""Multi-platform bot orchestrator .

Manages active bot threads, auto-dispatches by platform (Google Meet, Zoom, MS Teams),
and coordinates the post-call transcription + intelligence pipeline.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from .meet_bot import MeetBotRunner

logger = logging.getLogger("lensai_bot.runner.orchestrator")


@dataclass
class ActiveSession:
    session_id: str
    platform: str
    url: str
    runner: Any
    thread: threading.Thread
    status: str = "running"


class BotOrchestrator:
    """Singleton manager for active meeting bots."""

    def __init__(self):
        self._sessions: Dict[str, ActiveSession] = {}
        self._lock = threading.Lock()

    def detect_platform(self, url: str) -> str:
        url_lower = url.lower()
        if "meet.google.com" in url_lower:
            return "google_meet"
        elif "zoom.us" in url_lower:
            return "zoom"
        elif "teams.microsoft.com" in url_lower or "teams.live.com" in url_lower:
            return "teams"
        return "generic_web"

    def launch(
        self,
        session_id: str,
        meeting_url: str,
        bot_name: Optional[str] = None,
        on_event: Optional[Callable[[str, str], None]] = None,
        on_complete: Optional[Callable[[str, str], None]] = None,
    ) -> ActiveSession:
        """Launch a bot into a meeting asynchronously in its own thread."""
        with self._lock:
            if session_id in self._sessions and self._sessions[session_id].status == "running":
                raise RuntimeError(f"Bot session {session_id} is already running.")

            platform = self.detect_platform(meeting_url)

            # Currently Google Meet has full browser automation; Zoom/Teams interface routes similarly
            runner = MeetBotRunner(
                meet_url=meeting_url,
                bot_name=bot_name,
                event_callback=on_event,
            )

            def _target():
                try:
                    audio_path = runner.run()
                    if on_complete:
                        on_complete(session_id, audio_path)
                finally:
                    with self._lock:
                        if session_id in self._sessions:
                            self._sessions[session_id].status = "completed"

            thread = threading.Thread(
                target=_target,
                name=f"LensAIBot-{session_id}",
                daemon=True,
            )
            session = ActiveSession(
                session_id=session_id,
                platform=platform,
                url=meeting_url,
                runner=runner,
                thread=thread,
            )
            self._sessions[session_id] = session
            thread.start()
            return session

    def stop(self, session_id: str) -> bool:
        """Stop an active bot session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.status != "running":
                return False
            session.runner.stop()
            session.status = "stopping"
            return True

    def get_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            return {
                "session_id": session.session_id,
                "platform": session.platform,
                "url": session.url,
                "status": session.status,
                "peak_participants": getattr(session.runner, "peak_participants", 0),
                "end_reason": getattr(session.runner, "end_reason", None),
            }


orchestrator = BotOrchestrator()
