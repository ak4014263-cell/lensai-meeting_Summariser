"""Speech to text via OpenAI's audio transcriptions endpoint.

This is a drop-in alternative to the local faster-whisper backend in
`transcription.py`: `transcribe_file()` returns exactly the same shape, so the
pipeline, speaker attribution and export paths do not care which one ran.

Why `whisper-1` specifically
---------------------------
It is the only OpenAI STT model that supports ``response_format=verbose_json``
with ``timestamp_granularities[]=segment``. The gpt-4o-transcribe family only
returns ``json``/``text``, i.e. a bare string with no timings, and
`pipeline.label_speakers()` needs per-segment start/end times to overlap Whisper
segments against the meeting's caption timeline for speaker names. Switching
model without timestamps would silently reduce every transcript to one unnamed
speaker.

Upload constraints handled here
-------------------------------
* The endpoint accepts mp3, mp4, mpeg, mpga, m4a, wav and webm — **not flac**,
  which is what the hosted MeetingBaaS path downloads. Unsupported containers
  are re-encoded.
* Uploads are capped at 25 MB. Anything larger is split into fixed windows and
  the per-window timestamps are shifted back onto the meeting timeline.

Re-encoding and splitting use PyAV, which is already a dependency (it is how
faster-whisper decodes webm/opus without a system ffmpeg binary).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Callable, Iterator

from ..config import settings

# Containers the API accepts directly, so we can upload without touching them.
_NATIVE_FORMATS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}

# Transcode target for anything we have to rewrite.
_PCM_RATE = 16000
_PCM_CHANNELS = 1

_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4


class OpenAiSttError(RuntimeError):
    """Raised when transcription could not be completed."""


# ────────────────────────────── audio helpers ────────────────────────────


def probe_duration_seconds(file_path: str) -> float:
    """Best-effort container duration in seconds (0.0 when unknown)."""
    try:
        import av

        with av.open(file_path) as container:
            if container.duration:
                return float(container.duration) / 1_000_000.0
            for stream in container.streams:
                if stream.type == "audio" and stream.duration and stream.time_base:
                    return float(stream.duration * stream.time_base)
    except Exception:
        pass
    return 0.0


def _write_wav_window(
    src_path: str,
    dest_path: str,
    start_s: float | None = None,
    end_s: float | None = None,
) -> bool:
    """Re-encode ``src_path`` to 16 kHz mono PCM WAV, optionally a time window.

    Returns True when at least one audio frame was written.
    """
    import av

    wrote = False
    with av.open(src_path) as src:
        audio_streams = [s for s in src.streams if s.type == "audio"]
        if not audio_streams:
            raise OpenAiSttError(f"No audio stream found in {os.path.basename(src_path)}")
        in_stream = audio_streams[0]

        if start_s:
            # seek() takes the stream time_base; nudge slightly early so the
            # first frame of the window is never clipped.
            try:
                target = max(0.0, start_s - 0.05)
                src.seek(int(target / in_stream.time_base), stream=in_stream)
            except Exception:
                pass  # fall back to decoding from the beginning and filtering

        with av.open(dest_path, mode="w", format="wav") as dst:
            out_stream = dst.add_stream("pcm_s16le", rate=_PCM_RATE)
            out_stream.layout = "mono"

            resampler = av.AudioResampler(
                format="s16", layout="mono", rate=_PCM_RATE
            )

            for frame in src.decode(in_stream):
                if frame.pts is not None and in_stream.time_base:
                    ts = float(frame.pts * in_stream.time_base)
                    if start_s is not None and ts + 0.05 < start_s:
                        continue
                    if end_s is not None and ts >= end_s:
                        break

                frame.pts = None
                for resampled in resampler.resample(frame):
                    for packet in out_stream.encode(resampled):
                        dst.mux(packet)
                        wrote = True

            for resampled in resampler.resample(None) or []:
                for packet in out_stream.encode(resampled):
                    dst.mux(packet)
                    wrote = True
            for packet in out_stream.encode(None):
                dst.mux(packet)
                wrote = True

    return wrote


# ─────────────────────────────── HTTP call ───────────────────────────────


def _post_transcription(file_path: str, report: Callable[[str], None]) -> dict[str, Any]:
    """POST one audio file to the transcriptions endpoint, with retries."""
    import requests

    url = f"{settings.OPENAI_BASE_URL.rstrip('/')}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    data = {
        "model": settings.OPENAI_STT_MODEL,
        "response_format": "verbose_json",
        "timestamp_granularities[]": "segment",
    }
    if settings.WHISPER_LANGUAGE:
        data["language"] = settings.WHISPER_LANGUAGE

    last_error: str | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with open(file_path, "rb") as handle:
                response = requests.post(
                    url,
                    headers=headers,
                    data=data,
                    files={"file": (os.path.basename(file_path), handle)},
                    timeout=settings.OPENAI_STT_TIMEOUT,
                )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt == _MAX_ATTEMPTS:
                break
            backoff = 2 ** attempt
            report(f"Network error ({last_error}); retrying in {backoff}s...")
            time.sleep(backoff)
            continue

        if response.status_code == 200:
            try:
                return response.json()
            except json.JSONDecodeError as exc:
                raise OpenAiSttError(f"Malformed response from OpenAI: {exc}") from exc

        body = (response.text or "")[:400]
        if response.status_code in _RETRY_STATUS and attempt < _MAX_ATTEMPTS:
            backoff = 2 ** attempt
            report(f"OpenAI returned {response.status_code}; retrying in {backoff}s...")
            time.sleep(backoff)
            last_error = f"HTTP {response.status_code}: {body}"
            continue

        # 401/400 and friends are not worth retrying.
        raise OpenAiSttError(f"OpenAI transcription failed (HTTP {response.status_code}): {body}")

    raise OpenAiSttError(f"OpenAI transcription failed after {_MAX_ATTEMPTS} attempts: {last_error}")


def _segments_from_response(payload: dict[str, Any], offset_ms: int) -> list[dict[str, Any]]:
    """Map the API's segment objects onto our internal segment shape."""
    out: list[dict[str, Any]] = []
    raw = payload.get("segments")

    if not raw:
        # verbose_json normally includes segments; if a model or proxy omits
        # them, keep the text rather than losing the transcript entirely.
        text = (payload.get("text") or "").strip()
        if text:
            out.append(
                {
                    "start_ms": offset_ms,
                    "end_ms": offset_ms,
                    "text": text,
                    "confidence": None,
                }
            )
        return out

    for seg in raw:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        out.append(
            {
                "start_ms": offset_ms + int(float(seg.get("start") or 0.0) * 1000),
                "end_ms": offset_ms + int(float(seg.get("end") or 0.0) * 1000),
                "text": text,
                # Same field the local backend reports, so downstream code and
                # the confidence column stay consistent across backends.
                "confidence": seg.get("avg_logprob"),
            }
        )
    return out


# ──────────────────────────── window planning ────────────────────────────


def _windows(duration_s: float, chunk_s: int) -> Iterator[tuple[float, float]]:
    start = 0.0
    while start < duration_s:
        yield start, min(start + chunk_s, duration_s)
        start += chunk_s


def _needs_rewrite(file_path: str) -> tuple[bool, str]:
    """Whether the file must be re-encoded/split, and why."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in _NATIVE_FORMATS:
        return True, f"{ext or 'unknown'} is not an accepted upload format"

    size_mb = os.path.getsize(file_path) / 1_048_576
    if size_mb > settings.OPENAI_MAX_UPLOAD_MB:
        return True, f"{size_mb:.1f} MB exceeds the {settings.OPENAI_MAX_UPLOAD_MB:.0f} MB upload cap"

    return False, ""


# ──────────────────────────────── entry point ────────────────────────────


def transcribe_pcm(pcm: bytes, sample_rate: int | None = None) -> str:
    """Transcribe raw 16-bit mono PCM and return plain text.

    Used by the live path, which holds PCM in memory rather than a file. The
    bytes are wrapped in a WAV header (a few dozen bytes) so the API accepts
    them without a transcode.
    """
    if not pcm:
        return ""
    if not settings.openai_stt_configured:
        raise OpenAiSttError("OPENAI_API_KEY is not set.")

    import wave

    rate = sample_rate or settings.LIVE_SAMPLE_RATE
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".wav", prefix="lensai_live_")
        os.close(fd)
        with wave.open(tmp_path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(pcm)

        payload = _post_transcription(tmp_path, lambda _m: None)
        return (payload.get("text") or "").strip()
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def transcribe_file(
    file_path: str,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Transcribe an audio file with OpenAI, mirroring the local backend's output.

    Returns ``{"segments": [...], "language": str, "duration_ms": int}`` where
    each segment is ``{"start_ms", "end_ms", "text", "confidence"}``.
    """

    def report(message: str) -> None:
        print(f"[STT/openai] {message}")
        if progress:
            try:
                progress(message)
            except Exception:
                pass

    if not settings.openai_stt_configured:
        raise OpenAiSttError("OPENAI_API_KEY is not set.")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    size = os.path.getsize(file_path)
    if size < 2048:
        report(f"Audio file is only {size} bytes — nothing to transcribe.")
        return {"segments": [], "language": None, "duration_ms": 0}

    duration_s = probe_duration_seconds(file_path)
    rewrite, reason = _needs_rewrite(file_path)

    report(
        f"Transcribing {os.path.basename(file_path)} "
        f"({size / 1_048_576:.1f} MB, {duration_s:.0f}s) "
        f"with {settings.OPENAI_STT_MODEL}..."
    )

    started = time.time()

    # ── Fast path: upload the original file untouched. ──
    if not rewrite:
        payload = _post_transcription(file_path, report)
        segments = _segments_from_response(payload, 0)
        language = payload.get("language")
        api_duration = float(payload.get("duration") or 0.0)
        duration_ms = int((api_duration or duration_s) * 1000)
        report(
            f"Done in {time.time() - started:.1f}s: {len(segments)} segments, "
            f"language={language}, audio duration={duration_ms / 1000:.0f}s"
        )
        return {"segments": segments, "language": language, "duration_ms": duration_ms}

    # ── Slow path: re-encode, splitting when necessary. ──
    report(f"Re-encoding to 16 kHz mono WAV ({reason}).")

    if duration_s <= 0:
        # Without a duration we cannot plan windows; try a single rewrite.
        chunk_plan = [(0.0, 0.0)]
    else:
        chunk_plan = list(_windows(duration_s, max(30, settings.OPENAI_CHUNK_SECONDS)))

    all_segments: list[dict[str, Any]] = []
    language: str | None = None
    tmp_dir = tempfile.mkdtemp(prefix="lensai_stt_")

    try:
        for index, (start_s, end_s) in enumerate(chunk_plan, start=1):
            window = os.path.join(tmp_dir, f"part_{index:03d}.wav")
            single = len(chunk_plan) == 1

            wrote = _write_wav_window(
                file_path,
                window,
                start_s=None if single else start_s,
                end_s=None if single else end_s,
            )
            if not wrote or os.path.getsize(window) < 2048:
                continue

            part_mb = os.path.getsize(window) / 1_048_576
            if part_mb > settings.OPENAI_MAX_UPLOAD_MB:
                # Should not happen with the default window, but never send a
                # request that is certain to be rejected.
                report(
                    f"Part {index} is {part_mb:.1f} MB, over the cap — "
                    "lower OPENAI_CHUNK_SECONDS. Skipping this window.",
                )
                continue

            if not single:
                report(
                    f"Part {index}/{len(chunk_plan)} "
                    f"({start_s:.0f}s–{end_s:.0f}s, {part_mb:.1f} MB)..."
                )

            payload = _post_transcription(window, report)
            offset_ms = 0 if single else int(start_s * 1000)
            all_segments.extend(_segments_from_response(payload, offset_ms))
            language = language or payload.get("language")

            try:
                os.remove(window)
            except OSError:
                pass
    finally:
        try:
            for leftover in os.listdir(tmp_dir):
                try:
                    os.remove(os.path.join(tmp_dir, leftover))
                except OSError:
                    pass
            os.rmdir(tmp_dir)
        except OSError:
            pass

    all_segments.sort(key=lambda s: s["start_ms"])
    duration_ms = int(duration_s * 1000) or (all_segments[-1]["end_ms"] if all_segments else 0)

    report(
        f"Done in {time.time() - started:.1f}s: {len(all_segments)} segments, "
        f"language={language}, audio duration={duration_ms / 1000:.0f}s"
    )
    return {"segments": all_segments, "language": language, "duration_ms": duration_ms}
