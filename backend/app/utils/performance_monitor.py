"""Performance monitoring and quality metrics for the AI Meeting Assistant."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import psutil

logger = logging.getLogger("lensai_bot.performance")


@dataclass
class PerformanceMetric:
    """Single performance measurement."""
    operation: str
    duration_ms: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None


class PerformanceMonitor:
    """Monitor and track performance metrics across the application."""
    
    def __init__(self):
        self.metrics: List[PerformanceMetric] = []
        self.process = psutil.Process()
    
    @contextmanager
    def measure(self, operation: str, **metadata):
        """
        Context manager to measure operation duration and resource usage.
        
        Usage:
            monitor = PerformanceMonitor()
            with monitor.measure("transcribe_audio", file_size_mb=5.2):
                # ... transcription code ...
                pass
        """
        start_time = time.time()
        start_cpu = self.process.cpu_percent()
        start_memory = self.process.memory_info().rss / (1024 * 1024)  # MB
        
        try:
            yield
        finally:
            duration = (time.time() - start_time) * 1000  # Convert to ms
            end_cpu = self.process.cpu_percent()
            end_memory = self.process.memory_info().rss / (1024 * 1024)
            
            metric = PerformanceMetric(
                operation=operation,
                duration_ms=duration,
                metadata=metadata,
                cpu_percent=(start_cpu + end_cpu) / 2,
                memory_mb=end_memory - start_memory,
            )
            
            self.metrics.append(metric)
            
            # Log performance
            logger.info(
                f"[PERF] {operation}: {duration:.0f}ms "
                f"(CPU: {metric.cpu_percent:.1f}%, Memory: +{metric.memory_mb:.1f}MB)"
            )
    
    def get_summary(self) -> Dict[str, Any]:
        """Get performance summary statistics."""
        if not self.metrics:
            return {}
        
        operations = {}
        for metric in self.metrics:
            if metric.operation not in operations:
                operations[metric.operation] = []
            operations[metric.operation].append(metric.duration_ms)
        
        summary = {}
        for op, durations in operations.items():
            summary[op] = {
                "count": len(durations),
                "total_ms": sum(durations),
                "avg_ms": sum(durations) / len(durations),
                "min_ms": min(durations),
                "max_ms": max(durations),
            }
        
        return summary
    
    def log_summary(self):
        """Log performance summary."""
        summary = self.get_summary()
        logger.info("=== Performance Summary ===")
        for op, stats in summary.items():
            logger.info(
                f"  {op}: {stats['count']} calls, "
                f"avg={stats['avg_ms']:.0f}ms, "
                f"total={stats['total_ms']:.0f}ms"
            )


# Global monitor instance
_global_monitor = PerformanceMonitor()


def get_monitor() -> PerformanceMonitor:
    """Get the global performance monitor."""
    return _global_monitor


@dataclass
class TranscriptionQualityMetrics:
    """Quality metrics for transcription output."""
    
    total_segments: int
    total_duration_ms: int
    avg_segment_length_ms: float
    speakers_detected: int
    language: str
    
    # Quality indicators
    avg_confidence: Optional[float] = None
    silence_ratio: Optional[float] = None  # Ratio of silence to total duration
    speech_rate_wpm: Optional[float] = None  # Words per minute
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_segments": self.total_segments,
            "total_duration_ms": self.total_duration_ms,
            "avg_segment_length_ms": self.avg_segment_length_ms,
            "speakers_detected": self.speakers_detected,
            "language": self.language,
            "avg_confidence": self.avg_confidence,
            "silence_ratio": self.silence_ratio,
            "speech_rate_wpm": self.speech_rate_wpm,
        }


def calculate_transcription_quality(segments: List[Dict[str, Any]], duration_ms: int) -> TranscriptionQualityMetrics:
    """Calculate quality metrics from transcription segments."""
    
    if not segments:
        return TranscriptionQualityMetrics(
            total_segments=0,
            total_duration_ms=duration_ms,
            avg_segment_length_ms=0,
            speakers_detected=0,
            language="unknown",
        )
    
    # Basic metrics
    total_segments = len(segments)
    total_speech_ms = sum(seg["end_ms"] - seg["start_ms"] for seg in segments)
    avg_segment_length = total_speech_ms / total_segments if total_segments > 0 else 0
    
    # Unique speakers
    speakers = set(seg.get("speaker", "Speaker") for seg in segments)
    speakers_detected = len(speakers)
    
    # Confidence
    confidences = [seg.get("confidence", 0) for seg in segments if seg.get("confidence")]
    avg_confidence = sum(confidences) / len(confidences) if confidences else None
    
    # Silence ratio
    silence_ratio = 1 - (total_speech_ms / duration_ms) if duration_ms > 0 else 0
    
    # Speech rate (words per minute)
    total_words = sum(len(seg.get("text", "").split()) for seg in segments)
    duration_minutes = duration_ms / 60000
    speech_rate = total_words / duration_minutes if duration_minutes > 0 else None
    
    metrics = TranscriptionQualityMetrics(
        total_segments=total_segments,
        total_duration_ms=duration_ms,
        avg_segment_length_ms=avg_segment_length,
        speakers_detected=speakers_detected,
        language=segments[0].get("language", "unknown") if segments else "unknown",
        avg_confidence=avg_confidence,
        silence_ratio=silence_ratio,
        speech_rate_wpm=speech_rate,
    )
    
    logger.info(f"[QUALITY] Transcription metrics: {metrics.to_dict()}")
    
    return metrics


@dataclass
class SummaryQualityMetrics:
    """Quality metrics for AI-generated summaries."""
    
    summary_length_words: int
    key_points_count: int
    processing_time_ms: float
    
    # Quality indicators
    avg_sentence_length: float
    complexity_score: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary_length_words": self.summary_length_words,
            "key_points_count": self.key_points_count,
            "processing_time_ms": self.processing_time_ms,
            "avg_sentence_length": self.avg_sentence_length,
            "complexity_score": self.complexity_score,
        }


def calculate_summary_quality(summary_text: str, key_points: List[str], processing_time_ms: float) -> SummaryQualityMetrics:
    """Calculate quality metrics from AI summary."""
    
    words = summary_text.split()
    summary_length = len(words)
    
    sentences = summary_text.split('.')
    avg_sentence_length = summary_length / len(sentences) if sentences else 0
    
    metrics = SummaryQualityMetrics(
        summary_length_words=summary_length,
        key_points_count=len(key_points),
        processing_time_ms=processing_time_ms,
        avg_sentence_length=avg_sentence_length,
    )
    
    logger.info(f"[QUALITY] Summary metrics: {metrics.to_dict()}")
    
    return metrics
