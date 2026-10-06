"""Meeting BaaS API client (https://docs.meetingbaas.com/api-v2).

Meeting BaaS is a hosted service that sends a bot into Google Meet / Zoom /
Teams, records + transcribes the call, and returns the artifacts. It handles the
fragile capture layer (waiting rooms, UI changes, long calls) that our own
Playwright bot struggles with, so it is the most reliable way to record
meetings you don't control.

Verified API shape (v2):

    POST /v2/bots                 create a bot -> {success, data:{bot_id, ...}}
    GET  /v2/bots/{bot_id}        bot state + artifact URLs
    GET  /v2/bots                 list bots
    DELETE /v2/bots/{bot_id}      make the bot leave

Auth header: `x-meeting-baas-api-key: <key>`.

The bot record exposes `transcription` (and `diarization`, `raw_transcription`)
as signed S3 URLs. The transcription artifact is JSON:

    {"result": {"utterances": [{"text", "start", "end", "speaker", ...}]}}

`start`/`end` are seconds. Each utterance already carries a `speaker` name, so
no separate diarization step is needed.
"""

from __future__ import annotations

from typing import Any

import requests

from ..config import settings


class MeetingBaasError(RuntimeError):
    pass


# Provider status -> our meeting status is handled by the runner; these are the
# statuses Meeting BaaS reports on a bot.
TERMINAL_OK = {"completed", "call_ended", "ended"}
TERMINAL_FAIL = {"failed", "error", "bot_rejected", "timeout"}


def _headers() -> dict[str, str]:
    if not settings.MEETINGBAAS_API_KEY:
        raise MeetingBaasError(
            "MEETINGBAAS_API_KEY is not set. Add it to backend/.env."
        )
    return {
        "x-meeting-baas-api-key": settings.MEETINGBAAS_API_KEY,
        "Content-Type": "application/json",
    }


def _url(path: str) -> str:
    return f"{settings.MEETINGBAAS_BASE_URL.rstrip('/')}{path}"


def _unwrap(response: requests.Response) -> Any:
    try:
        payload = response.json()
    except ValueError:
        response.raise_for_status()
        raise MeetingBaasError(f"Non-JSON response ({response.status_code}).")

    if not response.ok:
        detail = ""
        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("error") or str(payload)
        raise MeetingBaasError(f"Meeting BaaS API {response.status_code}: {detail}")

    # v2 wraps successful bodies as {"success": true, "data": ...}
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def create_bot(
    meeting_url: str,
    bot_name: str | None = None,
    *,
    transcription: bool = True,
    webhook_url: str | None = None,
    recording_mode: str = "speaker_view",
    extra: dict[str, Any] | None = None,
    leave_when_alone_seconds: int | None = 60,
    waiting_room_timeout: int = 600,
    bot_image: str | None = None,
    stream_to_url: str | None = None,
) -> dict[str, Any]:
    """Dispatch a bot to a Google Meet / Zoom / Teams meeting.

    The bot stays for the whole call and, by Meeting BaaS default, leaves once
    everyone else has gone — which is what triggers the transcript + summary.
    ``leave_when_alone_seconds`` asks it to leave that many seconds after it is
    the only participant left; ``waiting_room_timeout`` bounds the lobby wait.

    Returns the created bot record (with bot_id).
    """
    base_body: dict[str, Any] = {
        "bot_name": bot_name or settings.MEETINGBAAS_BOT_NAME,
        "meeting_url": meeting_url,
        "recording_mode": recording_mode,
    }
    if transcription:
        # Meeting BaaS requires BOTH the enable flag and a transcription_config
        # (with a provider) — otherwise it 400s or leaves transcription off,
        # which is why earlier bots produced no transcript.
        base_body["transcription_enabled"] = True
        base_body["transcription_config"] = {"provider": "gladia"}
    avatar = bot_image if bot_image is not None else settings.MEETINGBAAS_BOT_IMAGE_URL
    if avatar:
        # The bot's profile picture in the meeting (the LensAi logo).
        base_body["bot_image"] = avatar
    hook = webhook_url or settings.MEETINGBAAS_WEBHOOK_URL
    if hook:
        base_body["callback_config"] = {"enabled": True, "url": hook}
    if stream_to_url:
        # Live audio stream for in-meeting transcription + rolling summary.
        # `audio_frequency` must be an integer sample rate (verified).
        base_body["streaming_enabled"] = True
        base_body["streaming_config"] = {
            "input": stream_to_url,
            "audio_frequency": settings.LIVE_SAMPLE_RATE,
        }
    if extra:
        base_body["extra"] = extra

    # Best-effort auto-leave config. Field names vary across API revisions, so
    # if the request is rejected for an unknown field we retry without it and
    # fall back to Meeting BaaS's own defaults (which also auto-leave).
    timeout_config: dict[str, Any] = {"waiting_room_timeout": waiting_room_timeout}
    if leave_when_alone_seconds is not None:
        timeout_config["noone_talking_timeout"] = leave_when_alone_seconds
        timeout_config["everyone_left_timeout"] = leave_when_alone_seconds

    attempts = [dict(base_body, timeout_config=timeout_config), base_body]

    last_error: MeetingBaasError | None = None
    for body in attempts:
        print(f"[meetingbaas] POST /v2/bots keys={sorted(body.keys())} "
              f"transcription_enabled={body.get('transcription_enabled')}")
        try:
            response = requests.post(_url("/v2/bots"), headers=_headers(), json=body, timeout=45)
        except requests.RequestException as exc:
            raise MeetingBaasError(f"Could not reach Meeting BaaS: {exc}") from exc

        if response.status_code in (400, 422) and "timeout_config" in body:
            # Likely an unknown timeout field — drop it and try the plain body.
            last_error = MeetingBaasError(f"Meeting BaaS {response.status_code}: {response.text[:200]}")
            continue

        data = _unwrap(response)
        if not isinstance(data, dict) or not data.get("bot_id"):
            raise MeetingBaasError(f"Unexpected create-bot response: {data}")
        return data

    raise last_error or MeetingBaasError("Could not create the bot.")


def get_bot(bot_id: str) -> dict[str, Any]:
    """Fetch a bot's current state and artifact URLs."""
    try:
        response = requests.get(_url(f"/v2/bots/{bot_id}"), headers=_headers(), timeout=45)
    except requests.RequestException as exc:
        raise MeetingBaasError(f"Could not reach Meeting BaaS: {exc}") from exc
    data = _unwrap(response)
    if not isinstance(data, dict):
        raise MeetingBaasError(f"Unexpected get-bot response: {data}")
    return data


def leave_bot(bot_id: str) -> bool:
    """Ask the bot to leave the meeting now.

    The v2 route is POST /v2/bots/{id}/leave with a JSON body (the API rejects
    an empty body). There is no DELETE route.
    """
    try:
        response = requests.post(
            _url(f"/v2/bots/{bot_id}/leave"),
            headers=_headers(),
            json={"bot_id": bot_id},
            timeout=45,
        )
    except requests.RequestException as exc:
        raise MeetingBaasError(f"Could not reach Meeting BaaS: {exc}") from exc
    return response.ok


def _guess_extension(url: str, content_type: str | None, default: str) -> str:
    """Pick a file extension from the URL path or content type."""
    import os
    from urllib.parse import urlparse

    path = urlparse(url).path
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    if ext in ("mp4", "mp3", "wav", "m4a", "webm", "ogg", "opus", "aac", "flac"):
        return ext
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        mapping = {
            "audio/mpeg": "mp3",
            "audio/mp4": "m4a",
            "audio/wav": "wav",
            "audio/x-wav": "wav",
            "audio/webm": "webm",
            "audio/ogg": "ogg",
            "video/mp4": "mp4",
            "video/webm": "webm",
        }
        if ct in mapping:
            return mapping[ct]
    return default


def download_recording(bot_data: dict[str, Any], dest_path_no_ext: str) -> str | None:
    """Download the meeting recording to local storage.

    Prefers the audio artifact (smaller, ideal for Whisper); falls back to the
    video. ``dest_path_no_ext`` is the target path without extension; the real
    extension is derived from the artifact. Returns the written file path, or
    None when no recording is available.
    """
    url = bot_data.get("audio") or bot_data.get("video")
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return None
    default_ext = "mp4" if not bot_data.get("audio") else "wav"

    try:
        with requests.get(url, stream=True, timeout=300) as response:
            response.raise_for_status()
            ext = _guess_extension(url, response.headers.get("content-type"), default_ext)
            dest = f"{dest_path_no_ext}.{ext}"
            with open(dest, "wb") as fh:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        fh.write(chunk)
    except (requests.RequestException, OSError) as exc:
        raise MeetingBaasError(f"Could not download the recording: {exc}") from exc

    import os

    if not os.path.exists(dest) or os.path.getsize(dest) < 1024:
        return None
    return dest


def download_transcript(bot_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Download + parse the transcription artifact into a speaker timeline.

    Returns entries shaped like the pipeline's caption timeline:
    ``[{"startMs", "endMs", "text", "speaker"}]``.
    """
    url = bot_data.get("transcription")
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return []

    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise MeetingBaasError(f"Could not download transcript: {exc}") from exc

    utterances = (payload.get("result") or {}).get("utterances") or []
    timeline: list[dict[str, Any]] = []
    for utt in utterances:
        text = (utt.get("text") or "").strip()
        if not text:
            continue
        start = float(utt.get("start") or 0.0)
        end = float(utt.get("end") or start)
        speaker = (utt.get("speaker") or "").strip() or None
        timeline.append(
            {
                "startMs": int(start * 1000),
                "endMs": int(max(start, end) * 1000),
                "text": text,
                "speaker": speaker,
            }
        )
    timeline.sort(key=lambda e: e["startMs"])
    return timeline


def participant_names(bot_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    names: dict[str, dict[str, Any]] = {}
    bot_name = (bot_data.get("bot_name") or settings.MEETINGBAAS_BOT_NAME).lower()
    for group in ("speakers", "participants"):
        for person in bot_data.get(group) or []:
            name = (person.get("name") or "").strip()
            if not name or name.lower() == bot_name:
                continue
            names.setdefault(name, {"firstMs": 0, "lastMs": 0})
    return names


def verify_webhook(headers: dict[str, str], raw_body: bytes) -> tuple[bool, str]:
    """Verify an incoming Meeting BaaS webhook.

    Supports two schemes, in order of strength:
      1. Standard-Webhooks / svix HMAC when MEETINGBAAS_WEBHOOK_SECRET is set:
         signed content is `{id}.{timestamp}.{body}`, HMAC-SHA256 with the
         base64 secret (after the `whsec_` prefix), compared constant-time,
         with a 5-minute timestamp tolerance.
      2. Shared API-key header (`x-meeting-baas-api-key`) matching our key.

    Returns ``(ok, reason)``. When neither a secret nor a key header is present
    it returns ``(False, ...)`` so an unauthenticated caller is rejected in
    production; callers may choose to allow it in dev.
    """
    import base64
    import hashlib
    import hmac
    import time

    # Case-insensitive header access.
    h = {k.lower(): v for k, v in headers.items()}

    secret = settings.MEETINGBAAS_WEBHOOK_SECRET
    if secret:
        sig_header = h.get("webhook-signature") or h.get("svix-signature")
        msg_id = h.get("webhook-id") or h.get("svix-id")
        ts = h.get("webhook-timestamp") or h.get("svix-timestamp")
        if not (sig_header and msg_id and ts):
            return False, "missing webhook signature headers"

        # Reject stale deliveries (replay protection).
        try:
            if abs(time.time() - int(ts)) > 300:
                return False, "webhook timestamp outside tolerance"
        except ValueError:
            return False, "invalid webhook timestamp"

        key = secret
        if key.startswith("whsec_"):
            key = key[len("whsec_") :]
        try:
            key_bytes = base64.b64decode(key)
        except Exception:
            key_bytes = key.encode()

        signed = f"{msg_id}.{ts}.".encode() + raw_body
        expected = base64.b64encode(hmac.new(key_bytes, signed, hashlib.sha256).digest()).decode()

        # The header may carry several space-delimited "v1,<sig>" entries.
        for part in sig_header.split():
            candidate = part.split(",", 1)[-1]
            if hmac.compare_digest(candidate, expected):
                return True, "valid signature"
        return False, "signature mismatch"

    # Fallback: shared API-key header.
    provided = h.get("x-meeting-baas-api-key")
    if provided and settings.MEETINGBAAS_API_KEY:
        if hmac.compare_digest(provided, settings.MEETINGBAAS_API_KEY):
            return True, "valid api-key header"
        return False, "api-key header mismatch"

    return False, "no signature secret configured and no api-key header present"


def check_available() -> tuple[bool, str]:
    if not settings.MEETINGBAAS_API_KEY:
        return False, "MEETINGBAAS_API_KEY is not set."
    try:
        response = requests.get(_url("/v2/bots?limit=1"), headers=_headers(), timeout=20)
    except requests.RequestException as exc:
        return False, f"Meeting BaaS unreachable: {exc}"
    if response.status_code == 401:
        return False, "Meeting BaaS API key is invalid."
    if not response.ok:
        return False, f"Meeting BaaS returned {response.status_code}."
    return True, "Meeting BaaS API key is valid."
