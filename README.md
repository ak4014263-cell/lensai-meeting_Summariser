# AI Meeting Assistant

A self-hosted AI meeting assistant that runs entirely on local AI 
(faster-whisper + Ollama). Its headline feature: **paste a Google Meet
link and a bot joins the call, records it, and once everyone else leaves it
writes a full summary automatically** — transcript, key points, decisions,
action items, risks, questions and next steps, plus an "Ask AI" chat grounded in
the transcript.

## How the bot works

```
You paste a Meet link
      │
      ▼
FastAPI creates a meeting  ──►  bot_manager spawns a dedicated thread
      │                                     │
      │                                     ▼
      │                         Playwright drives real Chromium into the call
      │                         (joins as "AI Notetaker", mutes its own mic/cam)
      │                                     │
      │            ┌────────────────────────┼────────────────────────┐
      │            ▼                         ▼                         ▼
      │   RTCPeerConnection is       Live captions are        Participant count
      │   patched → every remote     scraped for speaker       is polled; when
      │   audio track is mixed in    names + rough text        everyone else has
      │   WebAudio → MediaRecorder                             left, the bot
      │   → webm streamed to disk                              leaves by itself
      │            └────────────────────────┬────────────────────────┘
      ▼                                      ▼
   Meeting page polls status      Shared pipeline: Whisper transcribes the audio,
   & shows a live activity log    caption timeline supplies speaker names, Ollama
                                  writes the structured report (map-reduce for
                                  long meetings). Result saved to the DB.
```

The **same pipeline** also powers file uploads and browser recordings, so every
capture method produces an identical result.

## Architecture

- **Frontend** — Next.js 16 + React 19 + Tailwind + shadcn-style UI (`frontend/`).
- **Backend** — FastAPI (`backend/app/`).
  - `ai/bot.py` + `ai/meet_capture.js` — the Google Meet bot and its injected
    browser capture script.
  - `ai/bot_manager.py` — runs each bot in its own thread with a stop switch.
  - `ai/transcription.py` — faster-whisper speech-to-text.
  - `ai/pipeline.py` — transcribe → attribute speakers → summarise → persist.
  - `ai/ollama_service.py` — chunked map-reduce meeting report + grounded Q&A.
  - `ai/meet_api.py` — *optional* official Google Meet REST API source
    (see `docs/GOOGLE_MEET_API.md`).
  - `meetings/router.py` — REST endpoints.
- **DB** — SQLite for dev (`sql_app.db`); schema auto-migrates on startup.
  Swap `DATABASE_URL` for PostgreSQL in production.

## Prerequisites

1. **Python 3.12** (a venv already exists at `backend/venv`).
2. **Node.js 18+** for the frontend.
3. **Ollama** running locally with a model pulled:
   ```powershell
   ollama pull llama3        # or: ollama pull llama3.2  (smaller/faster)
   ```
4. **Playwright Chromium** (already installed on this machine). If it is missing:
   ```powershell
   backend\venv\Scripts\python -m playwright install chromium
   ```

No system FFmpeg is required — faster-whisper decodes audio via PyAV.

## Running it

**Backend** (from `backend/`):
```powershell
venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```
Check readiness at http://127.0.0.1:8000/health — it reports whether Ollama and
the configured model are actually available.

**Frontend** (from `frontend/`):
```powershell
npm install
npm run dev
```
Open http://localhost:3000, sign up, and you are in.

## Using the bot

1. On the dashboard, click **🤖 Send bot to Meet**.
2. Paste a Google Meet link (`https://meet.google.com/abc-defg-hij`) and send.
3. Open the meeting — you will see a **live activity log**.
4. In Google Meet, **admit "AI Notetaker"** from the waiting room.
5. The bot records until everyone else leaves (or you click **Stop &
   summarise now**), then the report appears automatically.

> Tip: enabling **live captions** in the call improves speaker attribution,
> since Whisper provides the words and captions provide the names.

### The bot must be signed in to Google

Most Meet calls reject **anonymous** guests outright — you'll see *"You can't
join this video call — no one can join unless invited or admitted by the host"*
and the bot fails immediately. That is Google refusing an un-signed-in join, not
a bug.

Fix it once: sign the bot's browser profile into a Google account.

```powershell
cd backend
venv\Scripts\python setup_bot_login.py   # a Chrome window opens; log in, press Enter
```

This uses a dedicated, persistent Chrome profile (default `backend/.bot_profile`)
and is already wired in `.env`:

```
BOT_USER_DATA_DIR=.../backend/.bot_profile
BOT_BROWSER_CHANNEL=chrome
```

**Restart the backend** afterwards. Now the bot joins as a real signed-in user,
lands in the waiting room, and the host can admit it. Use a throwaway Google
account for the bot, not your personal one. If the bot's account is invited to
the meeting (or is in the same Workspace), it may be admitted automatically.

## Configuration

Copy `backend/.env.example` to `backend/.env` to tune anything (model sizes,
bot timeouts, display name, GPU, etc.). Sensible defaults mean an empty `.env`
works fine. Key ones:

| Setting | Default | Notes |
| --- | --- | --- |
| `OLLAMA_MODEL` | `llama3` | `llama3.2` is faster on modest hardware. |
| `WHISPER_MODEL` | `small` | `medium`/`large-v3` are more accurate but slower. |
| `WHISPER_DEVICE` | `cpu` | Set `cuda` + `WHISPER_COMPUTE_TYPE=float16` on an NVIDIA GPU. |
| `BOT_HEADLESS` | `false` | Meet blocks headless Chrome; keep visible on desktop. |
| `BOT_ALONE_GRACE_SECONDS` | `30` | How long everyone must be gone before the bot leaves. |
| `SECRET_KEY` | dev value | **Change for any real deployment.** |

## Two ways to capture Google Meet

| | Playwright bot (default) | Official Meet REST API (`ai/meet_api.py`) |
| --- | --- | --- |
| Works with any link you paste | ✅ | ❌ only meetings your Workspace owns |
| Terms-of-service friendly | ⚠️ browser automation | ✅ official |
| Speaker names | from live captions | from Google, exact |
| Setup | none | Google Cloud project + OAuth + eligible Workspace |
| Real-time | yes | no (fetch artifacts after the call) |

If your meetings live in a Google Workspace you control, prefer the official
API — see **`docs/GOOGLE_MEET_API.md`**. For arbitrary external links, the bot
is the only option.

## Verifying

Two self-contained checks live in `backend/_verify/`:

```powershell
# 1. Full capture path: real WebRTC audio → webm → Whisper → speaker labels → Ollama
venv\Scripts\python _verify\make_speech.ps1   # (run the .ps1 first to make a fixture)
venv\Scripts\python _verify\verify_capture.py

# 2. Black-box API test against a running server (start uvicorn first)
venv\Scripts\python _verify\smoke_api.py
```

## Notes & limits

- Google actively changes Meet's UI and detects automation. The bot uses
  resilient, layered selectors and debug screenshots (`storage/{id}_bot_*.png`),
  but a guest bot may still land in a waiting room and requires a human to admit
  it. A signed-in profile (`BOT_USER_DATA_DIR`) is more reliable.
- The in-process `bot_manager` fits a single-process deployment. To scale to
  multiple API workers, move it behind Redis + a worker service; the call sites
  do not change.
- Zoom and Microsoft Teams links are rejected with a clear message; only Google
  Meet is supported today.
