import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import socketio

from . import models
from . import models_tasks  # Import task models for table creation
from . import models_kanban  # Import kanban models for table creation
from .ai.bot_manager import bot_manager
from .auth import router as auth_router
from .config import settings
from .database import engine
from .db_migrate import sync_schema
from .integrations import router as integrations_router
from .meetings import router as meetings_router
from .chat_websocket import sio as chat_sio
from .chat_router_mongo import router as chat_router
from .mongo_db import connect_to_mongo, close_mongo_connection


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create new tables, then add any columns missing from existing ones.
    models.Base.metadata.create_all(bind=engine)
    sync_schema(engine)

    # Connect to MongoDB for chat system
    await connect_to_mongo()

    print(f"[startup] storage      : {settings.STORAGE_DIR}")
    print(f"[startup] ollama       : {settings.OLLAMA_HOST} ({settings.OLLAMA_MODEL})")
    if settings.use_openai_stt:
        print(
            f"[startup] speech-to-text: OpenAI {settings.OPENAI_STT_MODEL} "
            f"(local fallback: {settings.WHISPER_MODEL} on {settings.WHISPER_DEVICE})"
        )
    else:
        reason = (
            " (STT_BACKEND=openai but OPENAI_API_KEY is unset)"
            if settings.STT_BACKEND == "openai"
            else ""
        )
        print(
            f"[startup] speech-to-text: local {settings.WHISPER_MODEL} "
            f"on {settings.WHISPER_DEVICE}{reason}"
        )
    live = "on" if settings.LIVE_ENABLED else "off"
    print(
        f"[startup] live notes   : {live} "
        f"(chunk {settings.LIVE_CHUNK_SECONDS}s @ {settings.LIVE_SAMPLE_RATE} Hz, "
        f"summary every {settings.LIVE_SUMMARY_INTERVAL}s)"
    )
    print(
        f"[startup] bot          : name='{settings.BOT_DISPLAY_NAME}' "
        f"headless={settings.BOT_HEADLESS} max_concurrent={settings.BOT_MAX_CONCURRENT}"
    )
    print(
        f"[startup] google oauth : "
        f"{'configured' if settings.google_configured else 'NOT configured'} "
        f"(redirect {settings.GOOGLE_REDIRECT_URI})"
    )

    from .ai.calendar_worker import calendar_worker

    calendar_worker.start()
    yield

    calendar_worker.stop()
    active = bot_manager.active()
    if active:
        print(f"[shutdown] asking {len(active)} bot(s) to leave their meetings...")
        bot_manager.stop_all()
    
    # Close MongoDB connection
    await close_mongo_connection()


fastapi_app = FastAPI(
    title="AI Meeting Assistant API",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/api-docs"
)

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://lensaibot.duckdns.org",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

fastapi_app.include_router(auth_router.router)
fastapi_app.include_router(meetings_router.router)
fastapi_app.include_router(integrations_router.router)
fastapi_app.include_router(chat_router)

# LensAI-inspired features (Phases 1-5)
from .routers import tasks as tasks_router
from .routers import documents as docs_router
from .routers import chat_channels as chat_channels_router
from .routers import goals as goals_router
from .routers import time_tracking as time_router

# Advanced features
from .routers import kanban as kanban_router
from .routers import pomodoro as pomodoro_router
from .routers import analytics as analytics_router
from .routers import templates as templates_router
from .routers import automation as automation_router

fastapi_app.include_router(tasks_router.router)
fastapi_app.include_router(docs_router.router)
fastapi_app.include_router(chat_channels_router.router)
fastapi_app.include_router(goals_router.router)
fastapi_app.include_router(time_router.router)

# Advanced feature routers
fastapi_app.include_router(kanban_router.router)
fastapi_app.include_router(pomodoro_router.router)
fastapi_app.include_router(analytics_router.router)
fastapi_app.include_router(templates_router.router)
fastapi_app.include_router(automation_router.router)


@fastapi_app.get("/")
def read_root():
    return {"message": "Welcome to the AI Meeting Assistant API"}


@fastapi_app.get("/health")
def health():
    """Dependency check: is the AI stack actually ready to process a meeting?"""
    from .ai.ollama_service import check_available

    ollama_ok, ollama_detail = check_available()

    return {
        "status": "ok",
        "ollama": {
            "ok": ollama_ok,
            "detail": ollama_detail,
            "host": settings.OLLAMA_HOST,
            "model": settings.OLLAMA_MODEL,
        },
        "whisper": {
            "model": settings.WHISPER_MODEL,
            "device": settings.WHISPER_DEVICE,
        },
        "bot": {
            "display_name": settings.BOT_DISPLAY_NAME,
            "headless": settings.BOT_HEADLESS,
            "active": len(bot_manager.active()),
            "limit": settings.BOT_MAX_CONCURRENT,
        },
        "google": {
            "configured": settings.google_configured,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "scopes": settings.GOOGLE_SCOPES,
        },
        "meetingbaas": {
            "configured": settings.meetingbaas_configured,
            "webhook_url": settings.MEETINGBAAS_WEBHOOK_URL or None,
        },
        "storage": str(settings.STORAGE_DIR),
    }


@fastapi_app.websocket("/ws/live/{meeting_id}")
async def live_audio_stream(websocket: WebSocket, meeting_id: int):
    """Receive the live meeting audio stream from Meeting BaaS.

    The bot connects here (see `streaming_config.input`) and pushes PCM audio
    while the call is running. We buffer it, transcribe rolling windows with
    Whisper, and refresh the meeting's live summary — all off the event loop.

    Note: this must be reachable from the internet, so PUBLIC_WS_BASE_URL has to
    point at a public https/wss host (a tunnel like ngrok in development).
    Because it is internet-facing, the `token` query parameter minted by
    `ai.live_session.mint_live_token()` is required: it binds the stream to one
    meeting so nobody can inject audio into someone else's transcript.
    """
    from .ai.live_session import live_manager, verify_live_token

    ok, reason = verify_live_token(meeting_id, websocket.query_params.get("token"))
    if not ok:
        print(f"[live {meeting_id}] rejected audio stream: {reason}")
        # Closing before accept() denies the handshake outright.
        await websocket.close(code=1008)
        return

    # Never allocate a session for a meeting that does not exist.
    from .database import SessionLocal

    db = SessionLocal()
    try:
        exists = (
            db.query(models.Meeting.id)
            .filter(models.Meeting.id == meeting_id)
            .first()
            is not None
        )
    finally:
        db.close()
    if not exists:
        print(f"[live {meeting_id}] rejected audio stream: unknown meeting")
        await websocket.close(code=1008)
        return

    await websocket.accept()
    session = live_manager.get_or_create(meeting_id)
    print(f"[live {meeting_id}] audio stream connected")

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            # Binary frames are raw PCM audio.
            data = message.get("bytes")
            if data:
                session.add_audio(data)
                session.maybe_process()
                continue

            # Text frames carry JSON control/metadata (shape varies); log once
            # so the format can be adapted without breaking the audio path.
            text = message.get("text")
            if text:
                snippet = text[:200]
                print(f"[live {meeting_id}] control frame: {snippet}")
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"[live {meeting_id}] stream error: {exc}")
    finally:
        print(f"[live {meeting_id}] stream closed "
              f"({session.bytes_received / 1024:.0f} KB received)")
        live_manager.close(meeting_id)


@fastapi_app.post("/webhooks/meetingbaas")
async def meetingbaas_webhook(request: Request):
    """Receive Meeting BaaS bot lifecycle events (production delivery path).

    Set MEETINGBAAS_WEBHOOK_URL to this endpoint's public https URL. Incoming
    requests are signature-verified (MEETINGBAAS_WEBHOOK_SECRET, else the API
    key header). Processing is idempotent, so it is safe alongside the poller.
    """
    from fastapi import Response

    from .ai import meetingbaas
    from .ai.meetingbaas_runner import finalize
    from .database import SessionLocal
    from . import models
    from .models import MeetingStatus

    raw = await request.body()

    ok, reason = meetingbaas.verify_webhook(dict(request.headers), raw)
    if not ok:
        # In pure-local dev with no secret/key header we still accept, but warn.
        if reason.startswith("no signature secret"):
            print(f"[webhook] WARNING: unverified Meeting BaaS webhook accepted ({reason}).")
        else:
            print(f"[webhook] rejected: {reason}")
            return Response(status_code=401, content=reason)

    try:
        payload = await request.json()
    except Exception:
        return {"ok": False, "reason": "invalid json"}

    event = (payload.get("event") or payload.get("type") or "").lower()
    data = payload.get("data") or {}
    bot_id = data.get("bot_id") or payload.get("bot_id")
    if not bot_id:
        return {"ok": True, "ignored": "no bot_id"}

    db = SessionLocal()
    try:
        meeting = (
            db.query(models.Meeting)
            .filter(models.Meeting.external_bot_id == bot_id)
            .first()
            )
        if not meeting:
            return {"ok": True, "ignored": "unknown bot_id"}
        if meeting.status in MeetingStatus.TERMINAL:
            return {"ok": True, "note": "already terminal"}

        if event in ("complete", "completed", "bot.completed", "recording.done"):
            # Fetch the authoritative record (with artifact URLs), then process.
            full = meetingbaas.get_bot(bot_id)
            finalize(db, meeting.id, full)
        elif event in ("failed", "bot.failed", "error"):
            meeting.error_message = str(data.get("error") or data.get("error_message") or event)[:2000]
            meeting.status = MeetingStatus.BOT_FAILED
            db.commit()
        return {"ok": True}
    finally:
        db.close()


class CombinedSocketIOASGIApp(socketio.ASGIApp):
    """Wrap FastAPI with Socket.IO so WebSocket connections work cleanly on /socket.io
    and forward any FastAPI attributes for backwards compatibility."""
    def __getattr__(self, name):
        return getattr(self.other_asgi_app, name)


# Root ASGI application mounted for uvicorn
app = CombinedSocketIOASGIApp(
    chat_sio,
    other_asgi_app=fastapi_app,
    socketio_path='socket.io'
)

