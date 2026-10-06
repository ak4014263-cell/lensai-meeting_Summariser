"""Google Meet automated bot runner .

Drives a real Playwright Chromium session:
- Enters Google Meet calls with configurable name & avatar
- Posts in-call greeting & consent announcement in the meeting chat
- Ingests remote WebRTC audio streams & closed captions
- Tracks participants & automatically leaves when the call ends
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..config import config

logger = logging.getLogger("lensai_bot.runner.meet")

CAPTURE_SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "backend" / "app" / "ai" / "meet_capture.js"

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
if (!navigator.languages || !navigator.languages.length) {
  Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
}
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = window.chrome || { runtime: {} };
"""

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class MeetBotRunner:
    """Manages an active Google Meet bot session."""

    def __init__(
        self,
        meet_url: str,
        bot_name: Optional[str] = None,
        event_callback: Optional[Callable[[str, str], None]] = None,
        audio_output_path: Optional[str] = None,
    ):
        self.meet_url = meet_url.strip()
        self.bot_name = bot_name or config.bot_name
        self.event_callback = event_callback
        self.audio_output_path = audio_output_path or str(config.storage_dir / f"meet_{int(time.time())}.wav")
        self.stop_event = threading.Event()
        self.caption_events: List[Dict[str, Any]] = []
        self.participants_seen: set[str] = set()
        self.peak_participants: int = 0
        self.end_reason: str = "completed"

    def emit(self, message: str, level: str = "info") -> None:
        logger.info(f"[{level.upper()}] {message}")
        if self.event_callback:
            try:
                self.event_callback(message, level)
            except Exception:
                pass

    def stop(self) -> None:
        """Signal the bot to leave the meeting."""
        self.stop_event.set()

    def run(self) -> str:
        """Run the bot synchronously in current thread."""
        return asyncio.run(self._run_async())

    async def _run_async(self) -> str:
        from playwright.async_api import async_playwright

        self.emit(f"Launching bot '{self.bot_name}' for {self.meet_url}...")

        async with async_playwright() as p:
            # Launch Chromium with dummy media devices
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--use-fake-ui-for-media-stream",
                    "--use-fake-device-for-media-stream",
                    "--disable-blink-features=AutomationControlled",
                    "--autoplay-policy=no-user-gesture-required",
                ],
            )

            context = await browser.new_context(
                user_agent=USER_AGENT,
                permissions=["microphone", "camera"],
                viewport={"width": 1280, "height": 720},
            )

            await context.add_init_script(STEALTH_SCRIPT)

            if CAPTURE_SCRIPT_PATH.exists():
                capture_js = CAPTURE_SCRIPT_PATH.read_text(encoding="utf-8")
                await context.add_init_script(capture_js)

            page = await context.new_page()

            try:
                await page.goto(self.meet_url, wait_until="domcontentloaded", timeout=45000)
                self.emit("Connected to Google Meet lobby. Entering credentials...")

                # Mute mic & cam on lobby screen
                await page.keyboard.press("Control+d")  # Mute mic
                await page.keyboard.press("Control+e")  # Turn off cam
                await asyncio.sleep(1)

                # Fill bot name if input exists
                name_input = page.locator("input[type='text']")
                if await name_input.count() > 0:
                    await name_input.first.fill(self.bot_name)
                    await asyncio.sleep(0.5)

                # Click Ask to Join / Join Now
                join_buttons = page.locator("button:has-text('Ask to join'), button:has-text('Join now')")
                if await join_buttons.count() > 0:
                    await join_buttons.first.click()
                    self.emit("Requested to join the call. Waiting in lobby for host admission...")

                # Wait for in-call state
                in_call = False
                wait_start = time.time()
                while time.time() - wait_start < 180 and not self.stop_event.is_set():
                    # Check if admitted
                    leave_btn = page.locator("button[aria-label*='Leave call'], button[data-call-ended]")
                    if await leave_btn.count() > 0:
                        in_call = True
                        break
                    await asyncio.sleep(2)

                if not in_call:
                    self.emit("Bot was not admitted to call or timed out.", "warning")
                    self.end_reason = "never_admitted"
                    await browser.close()
                    return self.audio_output_path

                self.emit("Bot admitted to call! Beginning recording.")

                # In-meeting greeting chat (consent notification)
                if config.send_greeting_chat:
                    try:
                        # Open chat panel if button exists
                        chat_btn = page.locator("button[aria-label*='Chat with everyone']")
                        if await chat_btn.count() > 0:
                            await chat_btn.first.click()
                            await asyncio.sleep(1)
                            chat_input = page.locator("textarea[aria-label*='Send a message']")
                            if await chat_input.count() > 0:
                                await chat_input.first.fill(config.greeting_message)
                                await page.keyboard.press("Enter")
                                self.emit("Posted in-call greeting and consent notice.")
                    except Exception as e:
                        logger.debug(f"Could not send in-call chat greeting: {e}")

                # Turn on live captions for speaker attribution
                try:
                    cc_btn = page.locator("button[aria-label*='Turn on captions']")
                    if await cc_btn.count() > 0:
                        await cc_btn.first.click()
                        self.emit("Turned on live captions for enhanced speaker attribution.")
                except Exception:
                    pass

                # Monitor call loop until everyone leaves or manual stop
                call_start = time.time()
                alone_since = None

                while not self.stop_event.is_set():
                    # Max duration cap
                    if (time.time() - call_start) > (config.max_meeting_duration_minutes * 60):
                        self.emit("Reached maximum meeting duration limit.", "warning")
                        self.end_reason = "max_duration"
                        break

                    # Check participants
                    # Sample participants elements
                    participant_els = page.locator("div[data-participant-id]")
                    count = await participant_els.count()
                    self.peak_participants = max(self.peak_participants, count)

                    if count <= 1:  # Only bot or nobody left
                        if alone_since is None:
                            alone_since = time.time()
                        elif time.time() - alone_since >= config.empty_room_grace_seconds:
                            self.emit("All participants have left. Leaving meeting.")
                            self.end_reason = "all_participants_left"
                            break
                    else:
                        alone_since = None

                    await asyncio.sleep(3)

                # Leave call
                leave_btn = page.locator("button[aria-label*='Leave call']")
                if await leave_btn.count() > 0:
                    await leave_btn.first.click()
                    await asyncio.sleep(1)

            except Exception as exc:
                self.emit(f"Bot error during call: {exc}", "error")
                self.end_reason = "error"
            finally:
                await browser.close()
                self.emit("Browser closed. Recording finalized.")

        return self.audio_output_path
