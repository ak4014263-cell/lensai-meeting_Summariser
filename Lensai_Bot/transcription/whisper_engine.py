"""Speech-to-text engine using faster-whisper ."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import config

logger = logging.getLogger("lensai_bot.transcription.whisper")


@dataclass
class TranscriptSegmentResult:
    start_time: int  # ms
    end_time: int    # ms
    text: str
    speaker: Optional[str] = None
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WhisperEngine:
    _model = None

    @classmethod
    def get_model(cls):
        if cls._model is None:
            # pyrefly: ignore [missing-import]
            from faster_whisper import WhisperModel
            logger.info(
                f"Loading faster-whisper model '{config.whisper_model_size}' "
                f"on device='{config.whisper_device}' ({config.whisper_compute_type})..."
            )
            cls._model = WhisperModel(
                config.whisper_model_size,
                device=config.whisper_device,
                compute_type=config.whisper_compute_type,
            )
        return cls._model

    def transcribe(
        self,
        audio_path: str | Path,
        language: Optional[str] = "en",
    ) -> List[TranscriptSegmentResult]:
        """Transcribe an audio file into timestamped segments with maximum quality."""
        path_str = str(audio_path)
        if not Path(path_str).exists():
            raise FileNotFoundError(f"Audio file not found: {path_str}")

        model = self.get_model()
        
        # Advanced settings for maximum transcription quality
        segments, info = model.transcribe(
            path_str,
            language=language,
            beam_size=config.whisper_beam_size,
            # VAD (Voice Activity Detection) for better silence handling
            vad_filter=getattr(config, 'whisper_vad_filter', True),
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=400,
            ),
            # Context awareness - use previous text for better accuracy
            condition_on_previous_text=getattr(config, 'whisper_condition_on_previous_text', True),
            # Quality thresholds
            temperature=getattr(config, 'whisper_temperature', 0.0),
            compression_ratio_threshold=getattr(config, 'whisper_compression_ratio_threshold', 2.4),
            log_prob_threshold=getattr(config, 'whisper_log_prob_threshold', -1.0),
            no_speech_threshold=getattr(config, 'whisper_no_speech_threshold', 0.6),
            # Decoding parameters for accuracy
            patience=getattr(config, 'whisper_patience', 1.0),
            length_penalty=getattr(config, 'whisper_length_penalty', 1.0),
            # Better word-level timestamps
            word_timestamps=False,  # Set to True for word-level timing (slower but more precise)
        )

        results: List[TranscriptSegmentResult] = []
        for s in segments:
            text = s.text.strip()
            if not text:
                continue
            start_ms = int(s.start * 1000)
            end_ms = int(s.end * 1000)
            # avg_logprob mapped to approximate 0-1 confidence
            conf = min(max(round(2.71828 ** s.avg_logprob, 2), 0.0), 1.0)
            results.append(
                TranscriptSegmentResult(
                    start_time=start_ms,
                    end_time=end_ms,
                    text=text,
                    speaker="Speaker",
                    confidence=conf,
                )
            )

        logger.info(f"Transcribed {len(results)} segments from {audio_path}")
        return results
