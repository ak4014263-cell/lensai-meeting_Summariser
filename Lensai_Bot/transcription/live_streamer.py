"""Live meeting stream buffer & rolling note generator .

Accumulates real-time audio PCM/WAV chunks from WebSocket or in-browser capture,
transcribes in rolling windows, and emits live activity events.
"""

from __future__ import annotations

import io
import logging
import wave
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("lensai_bot.transcription.streamer")


class LiveStreamBuffer:
    """Accumulates incoming PCM audio chunks and manages rolling window transcriptions."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        sample_width: int = 2,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.raw_frames = bytearray()
        self.segments: List[Dict[str, Any]] = []
        self.live_notes: str = ""

    def append_chunk(self, pcm_bytes: bytes) -> None:
        """Add raw PCM audio bytes to the buffer."""
        self.raw_frames.extend(pcm_bytes)

    @property
    def total_duration_ms(self) -> int:
        bytes_per_ms = (self.sample_rate * self.channels * self.sample_width) / 1000.0
        return int(len(self.raw_frames) / bytes_per_ms) if bytes_per_ms else 0

    def export_wav(self) -> bytes:
        """Package current buffer into a standard WAV audio byte stream."""
        bio = io.BytesIO()
        with wave.open(bio, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.sample_width)
            wf.setframerate(self.sample_rate)
            wf.writeframes(bytes(self.raw_frames))
        return bio.getvalue()
