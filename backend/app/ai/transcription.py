"""Speech to text with faster-whisper.

The model is loaded lazily and cached process-wide: loading costs seconds and
hundreds of MB, so it must not happen at import time (that would stall FastAPI
startup) nor once per request.

faster-whisper decodes audio through PyAV, so webm/opus recordings from the
meeting bot work without a system ffmpeg binary on PATH.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

from ..config import settings

_model = None
_model_lock = threading.Lock()
_load_error: str | None = None


def get_model():
    """Return the shared WhisperModel, loading it on first use."""
    global _model, _load_error

    if _model is not None:
        return _model
    if _load_error is not None:
        raise RuntimeError(_load_error)

    with _model_lock:
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel

            print(
                f"[STT] Loading faster-whisper '{settings.WHISPER_MODEL}' "
                f"({settings.WHISPER_DEVICE}/{settings.WHISPER_COMPUTE_TYPE})..."
            )
            _model = WhisperModel(
                settings.WHISPER_MODEL,
                device=settings.WHISPER_DEVICE,
                compute_type=settings.WHISPER_COMPUTE_TYPE,
            )
            print("[STT] Model ready.")
            return _model
        except Exception as exc:
            _load_error = f"Could not load Whisper model '{settings.WHISPER_MODEL}': {exc}"
            print(f"[STT] {_load_error}")
            raise RuntimeError(_load_error) from exc


def transcribe_file(
    file_path: str,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Transcribe an audio file into timestamped segments.

    Returns ``{"segments": [...], "language": str, "duration_ms": int}`` where
    each segment is ``{"start_ms", "end_ms", "text", "confidence", "speaker"}``.

    Dispatches to the configured STT backend:
    - Advanced (HF + diarization) when STT_BACKEND=advanced
    - Hugging Face when STT_BACKEND=huggingface 
    - OpenAI when STT_BACKEND=openai
    - Local faster-whisper otherwise
    """
    if settings.STT_BACKEND == "advanced":
        return _transcribe_file_advanced(file_path, progress=progress)
    
    if settings.STT_BACKEND == "huggingface":
        return _transcribe_file_huggingface(file_path, progress=progress)
    
    if settings.use_openai_stt:
        from .openai_stt import OpenAiSttError, transcribe_file as openai_transcribe

        try:
            return openai_transcribe(file_path, progress=progress)
        except (OpenAiSttError, FileNotFoundError):
            raise
        except Exception as exc:
            # An unexpected client-side failure should not cost the user their
            # recording: fall through to the local model instead.
            message = f"OpenAI transcription errored ({exc}); falling back to local Whisper."
            print(f"[STT] {message}")
            if progress:
                try:
                    progress(message)
                except Exception:
                    pass

    return _transcribe_file_local(file_path, progress=progress)


def _transcribe_file_local(
    file_path: str,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Transcribe with the local faster-whisper model."""

    def report(message: str) -> None:
        print(f"[STT] {message}")
        if progress:
            try:
                progress(message)
            except Exception:
                pass

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    size = os.path.getsize(file_path)
    if size < 2048:
        report(f"Audio file is only {size} bytes — nothing to transcribe.")
        return {"segments": [], "language": None, "duration_ms": 0}

    model = get_model()
    report(f"Transcribing {os.path.basename(file_path)} ({size / 1_048_576:.1f} MB)...")

    kwargs: dict[str, Any] = {
        "beam_size": settings.WHISPER_BEAM_SIZE,
        # Whisper hallucinates confident nonsense over long silences; VAD
        # trimming is the single biggest quality win on meeting audio.
        "vad_filter": settings.WHISPER_VAD,
        "condition_on_previous_text": False,
    }
    if settings.WHISPER_VAD:
        kwargs["vad_parameters"] = {"min_silence_duration_ms": 500}
    if settings.WHISPER_LANGUAGE:
        kwargs["language"] = settings.WHISPER_LANGUAGE

    segment_iter, info = model.transcribe(file_path, **kwargs)

    segments: list[dict[str, Any]] = []
    for seg in segment_iter:  # generator: work happens as we iterate
        text = (seg.text or "").strip()
        if not text:
            continue
        segments.append(
            {
                "start_ms": int(seg.start * 1000),
                "end_ms": int(seg.end * 1000),
                "text": text,
                "confidence": getattr(seg, "avg_logprob", None),
            }
        )
        if len(segments) % 25 == 0:
            report(f"{len(segments)} segments transcribed so far...")

    duration_ms = int(getattr(info, "duration", 0) * 1000)
    language = getattr(info, "language", None)
    report(
        f"Done: {len(segments)} segments, language={language}, "
        f"audio duration={duration_ms / 1000:.0f}s"
    )

    return {"segments": segments, "language": language, "duration_ms": duration_ms}


def transcribe_audio_task(meeting_id: int, file_path: str) -> None:
    """Background entry point for uploaded audio (kept for API compatibility)."""
    from .pipeline import process_meeting_audio

    process_meeting_audio(meeting_id, file_path)


def _transcribe_file_huggingface(
    file_path: str,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Transcribe using Hugging Face Transformers Whisper model."""

    def report(message: str) -> None:
        print(f"[STT-HF] {message}")
        if progress:
            try:
                progress(message)
            except Exception:
                pass

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    size = os.path.getsize(file_path)
    if size < 2048:
        report(f"Audio file is only {size} bytes — nothing to transcribe.")
        return {"segments": [], "language": None, "duration_ms": 0}

    try:
        from Lensai_Bot.transcription.huggingface_whisper import HuggingFacePipelineEngine
        
        model_name = settings.HUGGINGFACE_MODEL
        report(f"Using Hugging Face model: {model_name}")
        report(f"Transcribing {os.path.basename(file_path)} ({size / 1_048_576:.1f} MB)...")
        
        engine = HuggingFacePipelineEngine()
        segments_results = engine.transcribe(
            file_path,
            language=settings.WHISPER_LANGUAGE or "en",
            model_name=model_name,
        )
        
        # Convert to expected format
        segments = []
        duration_ms = 0
        for seg in segments_results:
            segments.append({
                "start_ms": seg.start_time,
                "end_ms": seg.end_time,
                "text": seg.text,
                "confidence": seg.confidence,
                "speaker": seg.speaker or "Speaker",
            })
            duration_ms = max(duration_ms, seg.end_time)
        
        report(
            f"Done: {len(segments)} segments, language={settings.WHISPER_LANGUAGE or 'auto'}, "
            f"audio duration={duration_ms / 1000:.0f}s"
        )
        
        return {
            "segments": segments,
            "language": settings.WHISPER_LANGUAGE or "en",
            "duration_ms": duration_ms
        }
        
    except Exception as exc:
        report(f"Hugging Face transcription failed: {exc}")
        report("Falling back to local faster-whisper...")
        return _transcribe_file_local(file_path, progress=progress)


def _transcribe_file_advanced(
    file_path: str,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Transcribe using advanced engine with speaker diarization and noise reduction.
    
    This is the BEST QUALITY option combining:
    - Hugging Face Whisper large-v3 for transcription
    - Pyannote.audio for speaker diarization
    - Noisereduce for audio enhancement
    - VAD for intelligent segmentation
    """

    def report(message: str) -> None:
        print(f"[STT-ADVANCED] {message}")
        if progress:
            try:
                progress(message)
            except Exception:
                pass

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    size = os.path.getsize(file_path)
    if size < 2048:
        report(f"Audio file is only {size} bytes — nothing to transcribe.")
        return {"segments": [], "language": None, "duration_ms": 0}

    try:
        from Lensai_Bot.transcription.advanced_transcription import create_transcription_engine
        
        model_name = settings.HUGGINGFACE_MODEL
        report(f"Using ADVANCED transcription (HF + Diarization + Noise Reduction)")
        report(f"Model: {model_name}")
        report(f"Processing {os.path.basename(file_path)} ({size / 1_048_576:.1f} MB)...")
        
        engine = create_transcription_engine()
        segments_results = engine.transcribe(
            file_path,
            language=settings.WHISPER_LANGUAGE or "en",
            model_name=model_name,
        )
        
        # Convert to expected format
        segments = []
        duration_ms = 0
        for seg in segments_results:
            segments.append({
                "start_ms": seg.start_time,
                "end_ms": seg.end_time,
                "text": seg.text,
                "confidence": seg.confidence,
                "speaker": seg.speaker or "Speaker",
            })
            duration_ms = max(duration_ms, seg.end_time)
        
        # Count unique speakers
        unique_speakers = len(set(s.get("speaker", "Speaker") for s in segments))
        
        report(
            f"✓ Done: {len(segments)} segments, {unique_speakers} speakers detected, "
            f"language={settings.WHISPER_LANGUAGE or 'auto'}, "
            f"duration={duration_ms / 1000:.0f}s"
        )
        
        return {
            "segments": segments,
            "language": settings.WHISPER_LANGUAGE or "en",
            "duration_ms": duration_ms
        }
        
    except Exception as exc:
        report(f"Advanced transcription failed: {exc}")
        report("Falling back to Hugging Face basic transcription...")
        return _transcribe_file_huggingface(file_path, progress=progress)

