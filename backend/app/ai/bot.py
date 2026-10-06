"""The meeting bot.

Drives a real Chromium instance into a Google Meet call, sits there as a silent
participant, captures every remote audio track plus the speaker-attributed live
captions, and leaves by itself once every human has gone. The recording is then
handed to the shared processing pipeline which transcribes it and produces the
meeting report.

Why a browser and not an API: Google Meet has no public recording API. Joining
as a guest in a real browser is the only route that works for arbitrary meeting
links, which is exactly what "give the bot a link and it shows up" requires.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import struct
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..config import settings, storage_path
from ..database import SessionLocal
from ..models import MeetingStatus
from .pipeline import finalise_meeting_timing, log_event, process_meeting_audio, set_status

CAPTURE_SCRIPT = (Path(__file__).parent / "meet_capture.js").read_text(encoding="utf-8")

# Removes the automation fingerprints Meet checks for before letting a guest in.
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

MEET_URL_RE = re.compile(r"^https?://meet\.google\.com/[A-Za-z0-9\-_/?=&%.+]+$")


def normalise_meet_url(raw: str) -> tuple[str | None, str | None]:
    """Validate and canonicalise a meeting URL.

    Returns ``(url, error)``. Accepts a bare meeting code like ``abc-defg-hij``.
    """
    value = (raw or "").strip()
    if not value:
        return None, "No meeting link was provided."

    if re.fullmatch(r"[a-z]{3}-[a-z]{4}-[a-z]{3}", value, re.I):
        return f"https://meet.google.com/{value.lower()}", None

    if not value.startswith(("http://", "https://")):
        value = "https://" + value

    if "meet.google.com" not in value.lower():
        for name, label in (
            ("zoom.us", "Zoom"),
            ("teams.microsoft.com", "Microsoft Teams"),
            ("teams.live.com", "Microsoft Teams"),
        ):
            if name in value.lower():
                return None, (
                    f"{label} links are not supported yet. The bot currently joins "
                    "Google Meet calls only."
                )
        return None, "That does not look like a Google Meet link."

    if not MEET_URL_RE.match(value):
        return None, "That Google Meet link looks malformed."

    return value, None


def meeting_code(url: str) -> str:
    match = re.search(r"meet\.google\.com/([a-z0-9\-]+)", url or "", re.I)
    return match.group(1) if match else "meeting"


def _silent_wav_path() -> str:
    """A looping silent WAV for Chrome's fake microphone.

    Chrome's built-in fake capture device emits a beep tone. Feeding it silence
    instead guarantees the bot never makes a sound in the call, even if muting
    itself through the Meet UI fails.
    """
    path = storage_path("_bot_silence.wav")
    if not os.path.exists(path):
        with wave.open(path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(48000)
            handle.writeframes(struct.pack("<h", 0) * 48000)  # 1 second of silence
    return path


def _browser_args() -> list[str]:
    args = [
        "--use-fake-ui-for-media-stream",  # auto-accept mic/camera prompts
        "--use-fake-device-for-media-stream",  # no physical devices required
        f"--use-file-for-fake-audio-capture={_silent_wav_path()}",
        "--autoplay-policy=no-user-gesture-required",  # let WebAudio start
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--window-size=1280,900",
    ]
    if settings.BOT_MUTE_AUDIO:
        # Silences the speakers only; the WebAudio capture graph keeps running.
        args.append("--mute-audio")
    return args


class MeetingBot:
    def __init__(self, meeting_id: int, meet_url: str, stop_event: threading.Event):
        self.meeting_id = meeting_id
        self.meet_url = meet_url
        self.stop_event = stop_event

        self.db: Session | None = None
        self.meeting: models.Meeting | None = None
        self.audio_path = storage_path(f"{meeting_id}_bot_audio.webm")
        self._audio_file = None
        self._audio_bytes = 0
        # Live (in-meeting) transcription session, when LIVE_ENABLED.
        self._live = None

        self.captions: dict[int, dict[str, Any]] = {}
        self._caption_watermark = 0
        self.participant_names: dict[str, dict[str, Any]] = {}
        self.peak_participants = 0
        self.end_reason: str | None = None
        self.failure: str | None = None

    # ── small helpers ────────────────────────────────────────────────────

    def log(self, message: str, level: str = "info") -> None:
        try:
            if self.db:
                log_event(self.db, self.meeting_id, message, level)
            else:
                encoding = sys.stdout.encoding or "utf-8"
                safe_msg = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
                print(f"[bot {self.meeting_id}] {safe_msg}")
        except Exception:
            pass

    def status(self, status: str) -> None:
        if self.db and self.meeting:
            set_status(self.db, self.meeting, status)

    async def _shot(self, page, tag: str) -> None:
        if not settings.BOT_DEBUG_SCREENSHOTS:
            return
        try:
            await page.screenshot(path=storage_path(f"{self.meeting_id}_bot_{tag}.png"))
        except Exception:
            pass

    async def _js(self, page, expression: str, *args) -> Any:
        """Evaluate in-page, tolerating a page that navigated or closed."""
        try:
            return await page.evaluate(expression, *args)
        except Exception:
            return None

    # ── audio sink ───────────────────────────────────────────────────────

    def _open_audio_file(self) -> None:
        if self._audio_file is None:
            # Fresh file per run so a retry never appends to stale audio.
            self._audio_file = open(self.audio_path, "wb")

    def _write_audio_chunk(self, b64: str) -> None:
        try:
            data = base64.b64decode(b64)
        except Exception as exc:
            print(f"[bot {self.meeting_id}] bad audio chunk: {exc}")
            return
        self._open_audio_file()
        self._audio_file.write(data)
        self._audio_file.flush()
        self._audio_bytes += len(data)

    def _close_audio_file(self) -> None:
        if self._audio_file is not None:
            try:
                self._audio_file.flush()
                self._audio_file.close()
            except Exception:
                pass
            self._audio_file = None

    # ── live transcription ───────────────────────────────────────────────

    def _feed_live_audio(self, b64: str) -> None:
        """Hand a raw-PCM window from the page to the live session.

        Runs on the bot's Playwright event loop, so it must not block: the
        LiveSession buffers and does the actual Whisper work on its own thread.
        """
        if self._live is None:
            return
        try:
            data = base64.b64decode(b64)
        except Exception as exc:
            print(f"[bot {self.meeting_id}] bad PCM chunk: {exc}")
            return
        try:
            self._live.add_audio(data)
            self._live.maybe_process()
        except Exception as exc:
            # Live output must never take the recording down with it.
            print(f"[bot {self.meeting_id}] live audio error: {exc}")

    def _start_live_session(self) -> None:
        """Open a live session and start the page-side PCM tap."""
        if not settings.LIVE_ENABLED:
            return
        try:
            from .live_session import live_manager

            self._live = live_manager.get_or_create(self.meeting_id)
        except Exception as exc:
            self._live = None
            self.log(
                f"Live transcription could not start: {exc}",
                level="warning",
            )

    def _close_live_session(self) -> None:
        """Flush and tear down the live session."""
        if self._live is None:
            return
        self._live = None
        try:
            from .live_session import live_manager

            live_manager.close(self.meeting_id)
        except Exception as exc:
            print(f"[bot {self.meeting_id}] closing live session failed: {exc}")

    # ── join flow ────────────────────────────────────────────────────────

    async def _fill_guest_name(self, page) -> bool:
        selectors = [
            'input[aria-label="Your name"]',
            'input[placeholder="Your name"]',
            'input[aria-label*="name" i]',
            'input[placeholder*="name" i]',
            'input[type="text"][jsname]',
        ]
        for selector in selectors:
            try:
                field = page.locator(selector).first
                await field.wait_for(state="visible", timeout=4000)
                await field.click()
                await field.fill(settings.BOT_DISPLAY_NAME)
                self.log(f'Joining as "{settings.BOT_DISPLAY_NAME}".')
                return True
            except Exception:
                continue
        # A signed-in bot profile has no name prompt, so this is not fatal.
        return False

    async def _click_join(self, page) -> str | None:
        """Click whichever join affordance Meet is showing. Returns its label."""
        labels = [
            "Ask to join",
            "Join now",
            "Switch here",
            "Join anyway",
            "Join",
        ]
        
        self.log(f"Looking for join button from {len(labels)} options...")
        
        for label in labels:
            for locator in (
                page.get_by_role("button", name=label, exact=True),
                page.locator(f'button:has-text("{label}")'),
                page.locator(f'[role="button"]:has-text("{label}")'),
            ):
                try:
                    target = locator.first
                    await target.wait_for(state="visible", timeout=3000)
                    self.log(f"Found '{label}' button, attempting to click...")
                    await target.click()
                    self.log(f"Successfully clicked '{label}'")
                    # Wait a moment for the click to register
                    await asyncio.sleep(1)
                    return label
                except Exception as e:
                    # Log specific errors for debugging
                    if "Timeout" in str(e):
                        continue  # Button not found, try next
                    else:
                        self.log(f"Error clicking '{label}': {str(e)[:100]}", level="warning")
                    continue
        
        self.log("No join button found with any selector", level="warning")
        return None

    async def _blocked_reason(self, page) -> str | None:
        """Detect the terminal 'you cannot join' screens."""
        try:
            body = (await page.inner_text("body"))[:3000].lower()
        except Exception:
            return None
        checks = {
            "you can't join this video call": "This meeting does not accept the bot (link may be invalid or restricted).",
            "no one responded to your request": "Nobody admitted the bot from the waiting room.",
            "you were denied": "The host denied the bot's request to join.",
            "someone in the call denied": "Someone in the call denied the bot's request to join.",
            "invalid video call name": "The meeting link is not valid.",
            "check your meeting code": "The meeting code is not valid.",
            "this meeting hasn't started": "The meeting has not started yet.",
            "sign in to join": "This meeting requires a signed-in Google account (set BOT_USER_DATA_DIR).",
            "not allowed to join": "The bot is not allowed to join this meeting.",
        }
        for needle, reason in checks.items():
            if needle in body:
                return reason
        return None

    async def _wait_for_admission(self, page) -> bool:
        deadline = time.monotonic() + settings.BOT_ADMISSION_TIMEOUT
        announced = False

        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                self.end_reason = "manual_stop"
                return False

            state = await self._js(page, "() => window.__aiBotStatus()")
            if state and state.get("inCall"):
                return True

            blocked = await self._blocked_reason(page)
            if blocked:
                self.failure = blocked
                return False

            await self._js(page, "() => window.__aiBotDismissDialogs()")

            if not announced:
                announced = True
                self.log(
                    "In the waiting room. Admit "
                    f'"{settings.BOT_DISPLAY_NAME}" from Google Meet to start recording.'
                )
            await asyncio.sleep(3)

        self.failure = (
            "The bot was not admitted within "
            f"{settings.BOT_ADMISSION_TIMEOUT // 60} minutes."
        )
        self.end_reason = "never_admitted"
        return False

    # ── monitoring ───────────────────────────────────────────────────────

    async def _drain_captions(self, page) -> None:
        entries = await self._js(
            page, "(since) => window.__aiBotDrainCaptions(since)", self._caption_watermark
        )
        if not entries:
            return
        for entry in entries:
            self.captions[entry["id"]] = entry
            if self._live and entry.get("text") and entry.get("done"):
                self._live.add_caption(entry.get("speaker") or "Speaker", entry["text"])

        open_ids = [cid for cid, e in self.captions.items() if not e.get("done")]
        if open_ids:
            # Never advance past an entry whose text can still grow.
            self._caption_watermark = min(open_ids) - 1
        elif self.captions:
            self._caption_watermark = max(self.captions)

    async def _collect_names(self, page, state: dict[str, Any]) -> None:
        elapsed = state.get("recordedMs") or 0
        
        # Bot name variations to filter out (current bot name + common variations)
        bot_names = {
            "you",
            settings.BOT_DISPLAY_NAME.lower(),
            "reframe",  # Legacy bot account name
            "ai notetaker",
            "lensai notetaker",
            "lensai bot",
            "notetaker",
        }
        
        # Method 1: Names from participant info in state
        for name in (state.get("participants") or {}).get("names") or []:
            clean = (name or "").strip()
            if not clean or clean.lower() in bot_names:
                continue
            record = self.participant_names.setdefault(
                clean, {"firstMs": elapsed, "lastMs": elapsed}
            )
            record["lastMs"] = elapsed

        # Method 2: Names from caption speaker tracking
        names = await self._js(page, "() => window.__aiBotNames()")
        for name, info in (names or {}).items():
            clean = (name or "").strip()
            if not clean or clean.lower() in bot_names:
                continue
            record = self.participant_names.setdefault(clean, {"firstMs": 0, "lastMs": 0})
            record["firstMs"] = min(record["firstMs"] or 0, info.get("firstMs") or 0)
            record["lastMs"] = max(record["lastMs"] or 0, info.get("lastMs") or 0)

        # Method 3: Extract full participant list from Google Meet DOM (NEW - Otter/Fireflies approach)
        try:
            participants = await self._js(page, "() => window.__aiBotGetParticipants()")
            if participants:
                for name in participants:
                    clean = (name or "").strip()
                    if not clean or clean.lower() in bot_names:
                        continue
                    if clean not in self.participant_names:
                        self.participant_names[clean] = {"firstMs": elapsed, "lastMs": elapsed}
                        self.log(f"Discovered participant: {clean}")
                    else:
                        self.participant_names[clean]["lastMs"] = elapsed
        except Exception as e:
            pass  # Don't let participant extraction crash the bot

    async def _monitor(self, page) -> None:
        """Sit in the call until everyone else leaves (or a limit is hit)."""
        poll = max(2, settings.BOT_POLL_SECONDS)
        started = time.monotonic()
        max_seconds = settings.max_meeting_seconds
        wait_for_people_until = started + settings.BOT_WAIT_FOR_PEOPLE

        humans_seen = False
        alone_since: float | None = None
        last_report = 0.0
        silence_warned = False

        while True:
            if self.stop_event.is_set():
                self.end_reason = "manual_stop"
                self.log("Stop requested -- leaving the meeting.")
                return

            elapsed = time.monotonic() - started
            if elapsed >= max_seconds:
                self.end_reason = "max_duration"
                self.log(
                    f"Reached the {settings.BOT_MAX_MEETING_MINUTES} minute recording cap.",
                    level="warning",
                )
                return

            state = await self._js(page, "() => window.__aiBotStatus()")
            if state is None:
                self.end_reason = "removed"
                self.log("Lost the meeting page -- assuming the call ended.", level="warning")
                return

            if state.get("ended"):
                reason = (state.get("endedReason") or "").lower()
                if any(w in reason for w in ("left", "only one", "ready", "just you", "ended", "everyone")):
                    self.end_reason = "all_participants_left"
                else:
                    self.end_reason = "removed"
                self.log(
                    f"Google Meet reports the call has ended ({reason or 'all participants left'}). Wrapping up and generating summary.",
                )
                return

            if not state.get("inCall"):
                self.end_reason = "removed"
                self.log("The bot is no longer in the call. Wrapping up and generating summary.", level="warning")
                return

            await self._drain_captions(page)
            await self._collect_names(page, state)

            participants_info = state.get("participants") or {}
            others = int(participants_info.get("others") or 0)
            alone_detected = bool(participants_info.get("aloneDetected"))

            self.peak_participants = max(self.peak_participants, others)
            if others > 0 and not alone_detected:
                if not humans_seen:
                    humans_seen = True
                    self.log(f"{others} human participant(s) in the call. Recording.")
                alone_since = None
            else:
                # Bot is alone: either others=0 or alone banner detected
                if humans_seen or alone_detected:
                    if alone_since is None:
                        alone_since = time.monotonic()
                        grace = settings.BOT_ALONE_GRACE_SECONDS
                        self.log(
                            f"Everyone else has left the call. Confirming for {grace}s before generating summary...",
                        )
                    elif time.monotonic() - alone_since >= settings.BOT_ALONE_GRACE_SECONDS:
                        self.end_reason = "all_participants_left"
                        self.log("Confirmed all participants have left. Leaving call and generating summary.")
                        return
                elif time.monotonic() > wait_for_people_until:
                    self.end_reason = "no_participants"
                    self.log(
                        "Nobody joined the call. Leaving without a recording.",
                        level="warning",
                    )
                    return
                elif elapsed > 60 and others == 0:
                    # Fallback: If meeting has been running > 1min and now shows 0 participants, leave
                    if alone_since is None:
                        alone_since = time.monotonic()
                        self.log(f"Participant count dropped to zero. Confirming for {settings.BOT_ALONE_GRACE_SECONDS}s...")
                    elif time.monotonic() - alone_since >= settings.BOT_ALONE_GRACE_SECONDS:
                        self.end_reason = "all_participants_left"
                        self.log("Confirmed meeting is empty. Leaving and generating summary.")
                        return

            # Periodic heartbeat, plus a one-time warning if the capture graph
            # is running but has never seen any signal.
            if time.monotonic() - last_report >= 60:
                last_report = time.monotonic()
                self.log(
                    f"Recording -- {int(elapsed // 60)}m elapsed, {others} participant(s), "
                    f"{state.get('captionCount') or 0} caption lines, "
                    f"{self._audio_bytes / 1024:.0f} KB audio."
                )
            if (
                not silence_warned
                and elapsed > 120
                and float(state.get("audioLevelPeak") or 0) < 1e-4
            ):
                silence_warned = True
                self.log(
                    "No audio signal detected yet. If this persists the summary "
                    "will fall back to Google Meet's live captions.",
                    level="warning",
                )

            # Periodically verify captions are still enabled (every ~30 seconds)
            if int(elapsed) % 30 == 0 and int(elapsed) > 0:
                try:
                    caption_check = await self._js(page, "() => window.__aiBotCheckCaptionsEnabled()")
                    if not caption_check:
                        self.log("Captions appear disabled. Re-enabling...")
                        # Try keyboard shortcut first
                        try:
                            await page.keyboard.press("c")
                        except Exception:
                            pass
                        # Force enable via JavaScript
                        await self._js(page, "() => window.__aiBotForceEnableCaptions()")
                except Exception as e:
                    pass  # Don't let caption check crash the monitoring loop

            await asyncio.sleep(poll)

    # ── main ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        from playwright.async_api import async_playwright

        self.db = SessionLocal()
        self.meeting = (
            self.db.query(models.Meeting)
            .filter(models.Meeting.id == self.meeting_id)
            .first()
        )
        if not self.meeting:
            print(f"[bot] meeting {self.meeting_id} not found; aborting.")
            self.db.close()
            return

        browser = None
        context = None
        recording_started = False
        live_tap_started = False

        try:
            self.status(MeetingStatus.BOT_LAUNCHING)
            self.log("Launching the browser...")

            async with async_playwright() as p:
                launch_kwargs: dict[str, Any] = {
                    "headless": settings.BOT_HEADLESS,
                    "args": _browser_args(),
                }
                if settings.BOT_BROWSER_CHANNEL:
                    launch_kwargs["channel"] = settings.BOT_BROWSER_CHANNEL

                context_kwargs: dict[str, Any] = {
                    "permissions": ["microphone", "camera"],
                    "user_agent": USER_AGENT,
                    "viewport": {"width": 1280, "height": 820},
                    "locale": "en-US",
                }

                if settings.BOT_USER_DATA_DIR:
                    # Signed-in profile: joins as a real Google account so it
                    # can enter meetings that block anonymous guests.
                    self.log(
                        f"Using signed-in browser profile at {settings.BOT_USER_DATA_DIR}."
                    )
                    try:
                        context = await p.chromium.launch_persistent_context(
                            settings.BOT_USER_DATA_DIR, **launch_kwargs, **context_kwargs
                        )
                    except Exception as exc:
                        if settings.BOT_BROWSER_CHANNEL:
                            self.log(
                                f"Channel '{settings.BOT_BROWSER_CHANNEL}' unavailable "
                                f"({exc}); using bundled Chromium.",
                                level="warning",
                            )
                            launch_kwargs.pop("channel", None)
                            context = await p.chromium.launch_persistent_context(
                                settings.BOT_USER_DATA_DIR, **launch_kwargs, **context_kwargs
                            )
                        else:
                            raise
                else:
                    try:
                        browser = await p.chromium.launch(**launch_kwargs)
                    except Exception as exc:
                        if settings.BOT_BROWSER_CHANNEL:
                            self.log(
                                f"Channel '{settings.BOT_BROWSER_CHANNEL}' unavailable "
                                f"({exc}); using bundled Chromium.",
                                level="warning",
                            )
                            launch_kwargs.pop("channel", None)
                            browser = await p.chromium.launch(**launch_kwargs)
                        else:
                            raise
                    context = await browser.new_context(**context_kwargs)

                context.set_default_timeout(20000)
                await context.grant_permissions(
                    ["microphone", "camera"], origin="https://meet.google.com"
                )

                # Bind the audio sink before injecting the capture script.
                async def on_audio_chunk(source, b64: str):  # noqa: ARG001
                    self._write_audio_chunk(b64)

                async def on_pcm_chunk(source, b64: str):  # noqa: ARG001
                    self._feed_live_audio(b64)

                await context.expose_binding("__aiBotAudioChunk", on_audio_chunk)
                await context.expose_binding("__aiBotPcmChunk", on_pcm_chunk)
                await context.add_init_script(STEALTH_SCRIPT)
                await context.add_init_script(CAPTURE_SCRIPT)

                page = context.pages[0] if context.pages else await context.new_page()
                page.on("console", lambda msg: None)  # keep Meet's noise out of stdout

                self.status(MeetingStatus.BOT_JOINING)
                self.log(f"Opening {self.meet_url}")
                await page.goto(self.meet_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(4000)
                await self._shot(page, "1_landed")

                blocked = await self._blocked_reason(page)
                if blocked:
                    raise RuntimeError(blocked)

                await self._js(page, "() => window.__aiBotDismissDialogs()")
                await self._fill_guest_name(page)

                muted = await self._js(page, "() => window.__aiBotMuteSelf()")
                if muted:
                    self.log(f"Turned off the bot's own {', '.join(muted)}.")

                # Check if already in call (signed-in host or pre-admitted)
                state = await self._js(page, "() => window.__aiBotStatus()")
                leave_btn = page.locator("button[aria-label*='Leave call'], button[data-call-ended], [aria-label*='Leave meeting']")
                already_in_call = bool(
                    (state and state.get("inCall"))
                    or (await leave_btn.count() > 0 and await leave_btn.first.is_visible())
                )

                if not already_in_call:
                    clicked = await self._click_join(page)
                    if not clicked:
                        # Try JavaScript fallback to find and click join button
                        self.log("Standard click failed, trying JavaScript fallback...")
                        js_result = await page.evaluate("""
                            () => {
                                const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
                                const joinTexts = ['Join now', 'Ask to join', 'Join', 'Switch here', 'Join anyway'];
                                
                                for (const btn of buttons) {
                                    const text = btn.textContent || btn.innerText || '';
                                    for (const joinText of joinTexts) {
                                        if (text.trim() === joinText) {
                                            btn.click();
                                            return joinText;
                                        }
                                    }
                                }
                                return null;
                            }
                        """)
                        
                        if js_result:
                            self.log(f'JavaScript fallback clicked "{js_result}".')
                            clicked = js_result
                            await asyncio.sleep(2)  # Wait for click to process
                    
                    if not clicked:
                        # Recheck if in-call state was reached
                        state = await self._js(page, "() => window.__aiBotStatus()")
                        if not (state and state.get("inCall")):
                            await self._shot(page, "2_join_failed")
                            # Get page content for debugging
                            body_text = await page.evaluate("() => document.body.innerText")
                            self.log(f"Page content sample: {body_text[:500]}", level="error")
                            raise RuntimeError(
                                "Could not find a join button on the Meet page. A debug "
                                f"screenshot was saved to storage/{self.meeting_id}_bot_2_join_failed.png"
                            )
                    else:
                        self.log(f'Clicked "{clicked}".')

                    self.status(MeetingStatus.BOT_WAITING_FOR_HOST)
                    admitted = await self._wait_for_admission(page)
                    await self._shot(page, "3_post_admit")

                    if not admitted:
                        raise RuntimeError(
                            self.failure or "The bot could not get into the meeting."
                        )

                self.status(MeetingStatus.BOT_IN_CALL)
                self.log("Bot is in the call. Recording started.")
                self.meeting.started_at = datetime.utcnow()
                self.db.commit()

                # Silence self again: Meet re-enables devices on entry.
                await self._js(page, "() => window.__aiBotMuteSelf()")
                await self._js(page, "() => window.__aiBotDismissDialogs()")

                # Live captions are the speaker-name source. Try multiple methods:
                # 1. Keyboard shortcut 'c' (Google Meet's native shortcut)
                # 2. Click the captions button with multiple selector strategies
                # 3. Use JavaScript to force-enable if available
                self.log("Attempting to enable captions...")
                caption_enabled = False
                
                # Method 1: Keyboard shortcut
                try:
                    await page.keyboard.press("c")
                    await asyncio.sleep(1)
                    caption_enabled = True
                    self.log("Captions enabled via keyboard shortcut")
                except Exception as e:
                    self.log(f"Keyboard shortcut failed: {e}")
                
                # Method 2: Click button with comprehensive selectors
                caption_selectors = [
                    '[aria-label*="Turn on captions" i]',
                    '[aria-label*="captions" i]',
                    'button[aria-label*="Turn on captions" i]',
                    'button[aria-label*="captions" i]',
                    '[jsname][aria-label*="caption" i]',
                    'div[role="button"][aria-label*="caption" i]',
                    '[data-tooltip*="caption" i]',
                    'button[data-tooltip*="caption" i]',
                ]
                
                for selector in caption_selectors:
                    try:
                        btn = page.locator(selector).first
                        if await btn.count() > 0:
                            await btn.click(timeout=3000)
                            await asyncio.sleep(1)
                            caption_enabled = True
                            self.log(f"Captions enabled via selector: {selector}")
                            break
                    except Exception as e:
                        continue
                
                # Method 3: Try alternative JavaScript method
                if not caption_enabled:
                    try:
                        # Look for the more menu and click captions from there
                        await page.locator('[aria-label*="More options" i]').first.click(timeout=2000)
                        await asyncio.sleep(0.5)
                        await page.locator('[aria-label*="Turn on captions" i]').first.click(timeout=2000)
                        caption_enabled = True
                        self.log("Captions enabled via More menu")
                    except Exception as e:
                        self.log(f"More menu method failed: {e}")
                
                # Start the caption polling regardless
                await self._js(page, "() => window.__aiBotStartCaptions()")
                
                if caption_enabled:
                    self.log("[OK] Captions successfully enabled")
                else:
                    self.log("[!] Could not auto-enable captions. Please enable manually with 'c' key or CC button.", level="warning")

                self._open_audio_file()
                result = await self._js(
                    page,
                    "([ms, br]) => window.__aiBotStartRecording(ms, br)",
                    [settings.BOT_AUDIO_CHUNK_MS, settings.BOT_AUDIO_BITRATE],
                )
                if not (result and result.get("ok")):
                    self.log(
                        "Audio recording could not start "
                        f"({(result or {}).get('error')}). Continuing with captions only.",
                        level="warning",
                    )
                else:
                    recording_started = True
                    self.log("Recording started. Capturing audio and captions.")

                # Live transcription runs off a second tap on the same audio
                # graph, so it is independent of the file recording above.
                self._start_live_session()
                if self._live is not None:
                    tap = await self._js(
                        page,
                        "([rate, size]) => window.__aiBotStartPcmTap(rate, size)",
                        [settings.LIVE_SAMPLE_RATE, 4096],
                    )
                    if tap and tap.get("ok"):
                        live_tap_started = True
                        self.log(
                            "Live transcription started "
                            f"({tap.get('rate')} Hz from a {tap.get('contextRate')} Hz graph)."
                        )
                    else:
                        self._close_live_session()
                        self.log(
                            "Live transcription could not start "
                            f"({(tap or {}).get('error')}). The post-meeting "
                            "transcript is unaffected.",
                            level="warning",
                        )

                self.status(MeetingStatus.BOT_RECORDING)
                await self._monitor(page)

                # ── wrap up inside the call ──
                self.log("Flushing the recording...")
                if live_tap_started:
                    try:
                        await self._js(page, "() => window.__aiBotStopPcmTap()")
                    except Exception:
                        pass
                if recording_started:
                    await self._js(page, "() => window.__aiBotStopRecording()")
                    await asyncio.sleep(1.5)  # let the final chunk arrive

                await self._drain_captions(page)
                final = await self._js(page, "() => window.__aiBotAllCaptions()")
                for entry in final or []:
                    existing = self.captions.get(entry["id"])
                    if not existing or len(entry.get("text") or "") >= len(
                        existing.get("text") or ""
                    ):
                        self.captions[entry["id"]] = entry

                await self._shot(page, "4_before_leave")
                await self._js(page, "() => window.__aiBotLeave()")
                await asyncio.sleep(1)

                await context.close()
                if browser:
                    await browser.close()
                context = None
                browser = None

            self._close_audio_file()
            # Flush the live transcript before the authoritative pipeline runs,
            # so the final live summary is not left half-written.
            self._close_live_session()
            self.status(MeetingStatus.BOT_LEFT)
            finalise_meeting_timing(self.db, self.meeting, self.end_reason)
            self.meeting.peak_participants = self.peak_participants
            self.db.commit()

            self.log(
                f"Left the meeting ({self.end_reason or 'finished'}). "
                f"Captured {self._audio_bytes / 1024:.0f} KB of audio and "
                f"{len(self.captions)} caption lines."
            )

            # Wait for audio buffers to flush and browser cleanup to complete
            if settings.BOT_POST_CALL_DELAY > 0:
                self.log(
                    f"Waiting {settings.BOT_POST_CALL_DELAY} seconds for "
                    "audio buffers to flush before processing..."
                )
                time.sleep(settings.BOT_POST_CALL_DELAY)

            self.status(MeetingStatus.PROCESSING_AUDIO)
            if self._audio_bytes > 2048:
                self.meeting.audio_file_path = self.audio_path
                self.db.commit()

            process_meeting_audio(
                self.meeting_id,
                self.audio_path if self._audio_bytes > 2048 else None,
                captions=sorted(self.captions.values(), key=lambda c: c["id"]),
                participant_names=self.participant_names,
                db=self.db,
            )

        except Exception as exc:
            import traceback

            traceback.print_exc()
            self._close_audio_file()
            message = str(exc) or exc.__class__.__name__
            try:
                if self.meeting:
                    self.meeting.error_message = message[:2000]
                    if not self.meeting.end_reason:
                        self.meeting.end_reason = self.end_reason or "error"
                    self.db.commit()
                self.log(f"Bot failed: {message}", level="error")

                # A failed join can still have captured usable material.
                if self._audio_bytes > 2048 or self.captions:
                    self.log("Salvaging what was captured before the failure.")
                    self.status(MeetingStatus.PROCESSING_AUDIO)
                    process_meeting_audio(
                        self.meeting_id,
                        self.audio_path if self._audio_bytes > 2048 else None,
                        captions=sorted(self.captions.values(), key=lambda c: c["id"]),
                        participant_names=self.participant_names,
                        db=self.db,
                    )
                else:
                    self.status(MeetingStatus.BOT_FAILED)
            except Exception:
                pass
        finally:
            self._close_audio_file()
            self._close_live_session()  # no-op when already closed
            for closeable in (context, browser):
                if closeable is not None:
                    try:
                        await closeable.close()
                    except Exception:
                        pass
            if self.db:
                self.db.close()


async def join_meet_and_record(
    meeting_id: int, meet_url: str, stop_event: threading.Event | None = None
) -> None:
    """Async entry point: join, record, leave, process."""
    await MeetingBot(meeting_id, meet_url, stop_event or threading.Event()).run()


def run_bot_task(
    meeting_id: int, meet_url: str, stop_event: threading.Event | None = None
) -> None:
    """Blocking entry point used by the bot manager's worker thread."""
    asyncio.run(join_meet_and_record(meeting_id, meet_url, stop_event))
