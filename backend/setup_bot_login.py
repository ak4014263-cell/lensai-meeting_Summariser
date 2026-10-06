"""One-time: sign the meeting bot into a Google account.

Most Google Meet calls reject anonymous guests ("You can't join this video
call — no one can join unless invited or admitted by the host"). To get past
that, the bot must join as a real, signed-in Google account.

This opens a real Chrome window using a dedicated, persistent profile. You log
into a Google account once; the session cookies are saved into that profile
folder. From then on the bot reuses the profile and joins signed in, so the
host can admit it from the waiting room like any other participant.

Run it from the backend/ directory:

    venv\\Scripts\\python setup_bot_login.py

Then make sure backend/.env points the bot at the same profile:

    BOT_USER_DATA_DIR=<the path this script prints>
    BOT_BROWSER_CHANNEL=chrome

Use a dedicated Google account for the bot, not your personal one.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings  # noqa: E402

PROFILE_DIR = settings.BOT_USER_DATA_DIR or str(
    Path(__file__).resolve().parent / ".bot_profile"
)
CHANNEL = settings.BOT_BROWSER_CHANNEL or "chrome"


async def main() -> None:
    from playwright.async_api import async_playwright

    Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Bot Google sign-in")
    print("=" * 70)
    print(f"Profile folder : {PROFILE_DIR}")
    print(f"Browser        : {CHANNEL}")
    print()
    print("A Chrome window will open. Do this:")
    print("  1. Sign in to the Google account the bot should use.")
    print("  2. Complete any 2FA / 'is it you' prompts.")
    print("  3. When you see your Google account home, come back here and")
    print("     press Enter. The window closes and the login is saved.")
    print()

    launch_kwargs = {
        "headless": False,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    }

    async with async_playwright() as p:
        context = None
        for channel in ([CHANNEL, None] if CHANNEL else [None]):
            try:
                kwargs = dict(launch_kwargs)
                if channel:
                    kwargs["channel"] = channel
                context = await p.chromium.launch_persistent_context(PROFILE_DIR, **kwargs)
                if channel:
                    print(f"Launched using channel '{channel}'.")
                else:
                    print("Launched using Playwright's bundled Chromium.")
                break
            except Exception as exc:
                print(f"  could not launch with channel={channel!r}: {exc}")
        if context is None:
            print("\nFailed to launch any browser. Is Chrome installed?")
            return

        # Reduce the "this browser may not be secure" friction.
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://accounts.google.com/", wait_until="domcontentloaded")

        # Block until the operator confirms, in a thread so the event loop and
        # the browser stay responsive during login.
        await asyncio.get_event_loop().run_in_executor(
            None, input, "\n>>> Press Enter here AFTER you have finished signing in... "
        )

        # Best-effort confirmation of the signed-in email.
        email = None
        try:
            await page.goto("https://myaccount.google.com/", wait_until="domcontentloaded", timeout=15000)
            body = (await page.inner_text("body"))[:5000]
            import re

            match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", body)
            email = match.group(0) if match else None
        except Exception:
            pass

        await context.close()

    print()
    print("=" * 70)
    if email:
        print(f"Saved sign-in for: {email}")
    else:
        print("Sign-in saved (could not read the account email, that's fine).")
    print("=" * 70)
    print("\nNow set these in backend/.env (create the file if needed):")
    print(f"  BOT_USER_DATA_DIR={PROFILE_DIR}")
    print(f"  BOT_BROWSER_CHANNEL={CHANNEL}")
    print("\nRestart the backend, then send the bot to a meeting again.")


if __name__ == "__main__":
    asyncio.run(main())
