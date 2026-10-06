"""Speech-to-text engine using Hugging Face Transformers with Whisper models.

Provides the best transcription quality using state-of-the-art models from Hugging Face Hub.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch
import librosa

logger = logging.getLogger("lensai_bot.transcription.huggingface")


@dataclass
class TranscriptSegmentResult:
    start_time: int  # ms
    end_time: int    # ms
    text: str
    speaker: Optional[str] = None
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HuggingFaceWhisperEngine:
    """Hugging Face Transformers-based Whisper transcription engine."""
    
    _model = None
    _processor = None
    _device = None

    @classmethod
    def get_model(cls, model_name: str = "openai/whisper-large-v3"):
        """Load Hugging Face Whisper model with authentication."""
        if cls._model is None:
            from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
            
            # Get Hugging Face token
            hf_token = os.getenv("HUGGINGFACE_TOKEN")
            if not hf_token:
                raise ValueError("HUGGINGFACE_TOKEN not found in environment")
            
            # Determine device
            cls._device = "cuda" if torch.cuda.is_available() else "cpu"
            torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            
            logger.info(f"Loading Hugging Face model '{model_name}' on device '{cls._device}'...")
            
            # Load model
            cls._model = AutoModelForSpeechSeq2Seq.from_pretrained(
                model_name,
                torch_dtype=torch_dtype,
                low_cpu_mem_usage=True,
                use_safetensors=True,
                token=hf_token,
            )
            cls._model.to(cls._device)
            
            # Load processor
            cls._processor = AutoProcessor.from_pretrained(
                model_name,
                token=hf_token,
            )
            
            logger.info(f"✓ Loaded {model_name} successfully")
        
        return cls._model, cls._processor, cls._device

    def transcribe(
        self,
        audio_path: str | Path,
        language: Optional[str] = "en",
        model_name: str = "openai/whisper-large-v3",
    ) -> List[TranscriptSegmentResult]:
        """Transcribe audio file using Hugging Face Whisper model.
        
        Args:
            audio_path: Path to audio file
            language: Language code (e.g., 'en' for English)
            model_name: Hugging Face model identifier
            
        Returns:
            List of transcription segments with timestamps
        """
        path_str = str(audio_path)
        if not Path(path_str).exists():
            raise FileNotFoundError(f"Audio file not found: {path_str}")

        model, processor, device = self.get_model(model_name)
        
        # Load audio
        logger.info(f"Loading audio from {audio_path}")
        audio_array, sampling_rate = librosa.load(path_str, sr=16000, mono=True)
        
        # Process audio in chunks for better memory handling
        chunk_length_s = 30  # 30-second chunks
        stride_length_s = 5   # 5-second overlap
        
        chunk_length = chunk_length_s * sampling_rate
        stride_length = stride_length_s * sampling_rate
        
        results: List[TranscriptSegmentResult] = []
        offset_ms = 0
        
        # Process audio in overlapping chunks
        for i in range(0, len(audio_array), chunk_length - stride_length):
            chunk = audio_array[i:i + chunk_length]
            
            if len(chunk) == 0:
                break
            
            # Prepare inputs
            inputs = processor(
                chunk,
                sampling_rate=16000,
                return_tensors="pt",
            )
            
            input_features = inputs.input_features.to(device)
            
            # Generate transcription
            with torch.no_grad():
                predicted_ids = model.generate(
                    input_features,
                    language=language,
                    task="transcribe",
                    return_timestamps=True,
                    max_new_tokens=448,
                    num_beams=int(os.getenv("WHISPER_BEAM_SIZE", "5")),
                    temperature=float(os.getenv("WHISPER_TEMPERATURE", "0.0")),
                    condition_on_prev_tokens=os.getenv("WHISPER_CONDITION_ON_PREVIOUS_TEXT", "true").lower() == "true",
                )
            
            # Decode
            transcription = processor.batch_decode(
                predicted_ids,
                skip_special_tokens=True,
                output_offsets=True,
            )
            
            # Extract text and timestamps
            text = transcription[0].strip()
            
            if text:
                # Calculate timestamps for this chunk
                chunk_start_ms = offset_ms
                chunk_duration_ms = int((len(chunk) / sampling_rate) * 1000)
                chunk_end_ms = chunk_start_ms + chunk_duration_ms
                
                results.append(
                    TranscriptSegmentResult(
                        start_time=chunk_start_ms,
                        end_time=chunk_end_ms,
                        text=text,
                        speaker="Speaker",
                        confidence=1.0,  # HF Whisper doesn't provide confidence scores
                    )
                )
            
            offset_ms += int(((chunk_length - stride_length) / sampling_rate) * 1000)
        
        # Merge overlapping segments
        merged_results = self._merge_segments(results)
        
        logger.info(f"Transcribed {len(merged_results)} segments from {audio_path}")
        return merged_results

    def _merge_segments(self, segments: List[TranscriptSegmentResult]) -> List[TranscriptSegmentResult]:
        """Merge overlapping segments and remove duplicates."""
        if not segments:
            return []
        
        merged = []
        current = segments[0]
        
        for next_seg in segments[1:]:
            # Check if segments overlap significantly
            overlap = min(current.end_time, next_seg.end_time) - max(current.start_time, next_seg.start_time)
            
            if overlap > 3000:  # More than 3 seconds overlap
                # Merge if text is similar
                if current.text in next_seg.text or next_seg.text in current.text:
                    # Take the longer, more complete text
                    if len(next_seg.text) > len(current.text):
                        current = next_seg
                    continue
            
            merged.append(current)
            current = next_seg
        
        merged.append(current)
        return merged


# Alternative: Use Transformers Pipeline (simpler but less control)
class HuggingFacePipelineEngine:
    """Simplified pipeline-based transcription (faster setup, less control)."""
    
    _pipeline = None

    @classmethod
    def get_pipeline(cls, model_name: str = "openai/whisper-large-v3"):
        """Load Hugging Face pipeline."""
        if cls._pipeline is None:
            from transformers import pipeline
            
            hf_token = os.getenv("HUGGINGFACE_TOKEN")
            if not hf_token:
                raise ValueError("HUGGINGFACE_TOKEN not found in environment")
            
            device = 0 if torch.cuda.is_available() else -1
            torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            
            logger.info(f"Loading Hugging Face pipeline '{model_name}'...")
            
            cls._pipeline = pipeline(
                "automatic-speech-recognition",
                model=model_name,
                torch_dtype=torch_dtype,
                device=device,
                token=hf_token,
                model_kwargs={"use_safetensors": True},
            )
            
            logger.info(f"✓ Loaded pipeline successfully")
        
        return cls._pipeline

    def transcribe(
        self,
        audio_path: str | Path,
        language: Optional[str] = "en",
        model_name: str = "openai/whisper-large-v3",
    ) -> List[TranscriptSegmentResult]:
        """Transcribe using simplified pipeline."""
        path_str = str(audio_path)
        if not Path(path_str).exists():
            raise FileNotFoundError(f"Audio file not found: {path_str}")

        pipe = self.get_pipeline(model_name)
        
        # Transcribe with timestamps
        result = pipe(
            path_str,
            return_timestamps=True,
            generate_kwargs={
                "language": language,
                "task": "transcribe",
            },
        )
        
        # Convert to our format
        segments = []
        for chunk in result.get("chunks", []):
            timestamp = chunk.get("timestamp", (0, 0))
            text = chunk.get("text", "").strip()
            
            if text:
                start_ms = int(timestamp[0] * 1000) if timestamp[0] else 0
                end_ms = int(timestamp[1] * 1000) if timestamp[1] else start_ms + 1000
                
                segments.append(
                    TranscriptSegmentResult(
                        start_time=start_ms,
                        end_time=end_ms,
                        text=text,
                        speaker="Speaker",
                        confidence=1.0,
                    )
                )
        
        logger.info(f"Transcribed {len(segments)} segments from {audio_path}")
        return segments
