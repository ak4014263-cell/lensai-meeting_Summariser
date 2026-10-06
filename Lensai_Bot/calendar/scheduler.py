"""Automated calendar bot dispatcher & scheduler daemon .

Monitors synced calendar events and automatically launches the bot when a meeting
is about to begin.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from dateutil import parser as dt_parser

from ..config import config
from ..runner.bot_orchestrator import orchestrator
from .rules import CalendarEventRule

logger = logging.getLogger("lensai_bot.calendar.scheduler")


class CalendarScheduler:
    """Daemon that periodically checks upcoming meetings and dispatches bots."""

    def __init__(
        self,
        event_fetcher: Optional[Callable[[], List[Dict[str, Any]]]] = None,
        rule: Optional[CalendarEventRule] = None,
        on_bot_dispatched: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.event_fetcher = event_fetcher
        self.rule = rule or CalendarEventRule()
        self.on_bot_dispatched = on_bot_dispatched
        self._stop_event = threading.Event()
        self._scheduled_event_ids: set[str] = set()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the calendar scheduler background daemon."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="LensAICalendarScheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("LensAI Calendar Scheduler started.")

    def stop(self) -> None:
        """Stop the background scheduler."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("LensAI Calendar Scheduler stopped.")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.check_and_dispatch()
            except Exception as exc:
                logger.error(f"Error in calendar check loop: {exc}")

            # Sleep interval
            for _ in range(config.calendar_sync_interval_seconds):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def check_and_dispatch(self) -> List[str]:
        """Check upcoming events and dispatch bots for meetings about to start."""
        if not self.event_fetcher:
            return []

        events = self.event_fetcher()
        dispatched_ids: List[str] = []
        now = datetime.now(timezone.utc)

        for event in events:
            event_id = str(event.get("id"))
            if event_id in self._scheduled_event_ids:
                continue

            meet_url = event.get("meeting_url")
            if not meet_url:
                continue

            start_raw = event.get("start")
            if not start_raw:
                continue

            try:
                start_dt = dt_parser.parse(start_raw)
                if not start_dt.tzinfo:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            # Check eligibility
            eligible, reason = self.rule.is_eligible(event)
            if not eligible:
                continue

            # Check timing: within join_ahead_seconds (e.g. 120s) of start
            diff_seconds = (start_dt - now).total_seconds()
            if -300 <= diff_seconds <= config.join_ahead_seconds:
                # Meeting is starting now or within 2 minutes! Dispatch bot
                logger.info(f"Auto-dispatching LensAI Bot to '{event.get('summary')}' ({meet_url})")
                self._scheduled_event_ids.add(event_id)
                dispatched_ids.append(event_id)

                session_id = f"cal_{event_id}_{int(time.time())}"
                orchestrator.launch(
                    session_id=session_id,
                    meeting_url=meet_url,
                    bot_name=config.bot_name,
                )

                if self.on_bot_dispatched:
                    try:
                        self.on_bot_dispatched(event)
                    except Exception:
                        pass

        return dispatched_ids
