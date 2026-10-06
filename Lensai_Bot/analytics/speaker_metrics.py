"""Speaker and talk-time analytics .

Calculates:
- Talk-time % and duration per speaker
- Words per minute (WPM)
- Longest monologue per speaker
- Number of questions asked by each speaker
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SpeakerMetric:
    speaker: str
    total_time_ms: int = 0
    total_words: int = 0
    talk_time_pct: float = 0.0
    words_per_minute: float = 0.0
    longest_monologue_ms: int = 0
    turn_count: int = 0
    question_count: int = 0


@dataclass
class MeetingSpeakerAnalytics:
    total_duration_ms: int
    speakers: List[SpeakerMetric] = field(default_factory=list)
    dominant_speaker: Optional[str] = None
    balance_score: float = 0.0  # 1.0 = equally balanced, 0.0 = one person spoke 100%

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def calculate_speaker_metrics(segments: List[Dict[str, Any]]) -> MeetingSpeakerAnalytics:
    """Calculate detailed conversational metrics from transcript segments.
    
    Each segment is expected to have:
      - speaker: str
      - start_time: int (ms)
      - end_time: int (ms)
      - text: str
    """
    if not segments:
        return MeetingSpeakerAnalytics(total_duration_ms=0)

    # Sort segments by start_time
    sorted_segs = sorted(segments, key=lambda s: s.get("start_time", 0))
    min_time = sorted_segs[0].get("start_time", 0)
    max_time = max(s.get("end_time", 0) for s in sorted_segs)
    total_duration_ms = max(max_time - min_time, 1)

    speaker_stats: Dict[str, Dict[str, Any]] = {}

    for seg in sorted_segs:
        spk = seg.get("speaker") or "Unknown Speaker"
        start = seg.get("start_time", 0)
        end = seg.get("end_time", start)
        dur = max(end - start, 0)
        text = (seg.get("text") or "").strip()
        words = len(text.split()) if text else 0
        is_question = bool(re.search(r"\?\s*$", text)) or bool(
            re.match(r"^(who|what|when|where|why|how|can|could|would|is|are|do|does|did)\b", text, re.I)
        )

        if spk not in speaker_stats:
            speaker_stats[spk] = {
                "total_time_ms": 0,
                "total_words": 0,
                "longest_monologue_ms": 0,
                "turn_count": 0,
                "question_count": 0,
            }

        stats = speaker_stats[spk]
        stats["total_time_ms"] += dur
        stats["total_words"] += words
        stats["turn_count"] += 1
        if dur > stats["longest_monologue_ms"]:
            stats["longest_monologue_ms"] = dur
        if is_question:
            stats["question_count"] += 1

    total_speech_ms = sum(s["total_time_ms"] for s in speaker_stats.values()) or total_duration_ms

    metrics_list: List[SpeakerMetric] = []
    dominant_speaker = None
    max_time = -1

    for spk, stats in speaker_stats.items():
        pct = round((stats["total_time_ms"] / total_speech_ms) * 100, 1)
        mins = stats["total_time_ms"] / 60000.0
        wpm = round(stats["total_words"] / mins, 1) if mins > 0.05 else 0.0

        if stats["total_time_ms"] > max_time:
            max_time = stats["total_time_ms"]
            dominant_speaker = spk

        metrics_list.append(
            SpeakerMetric(
                speaker=spk,
                total_time_ms=stats["total_time_ms"],
                total_words=stats["total_words"],
                talk_time_pct=pct,
                words_per_minute=wpm,
                longest_monologue_ms=stats["longest_monologue_ms"],
                turn_count=stats["turn_count"],
                question_count=stats["question_count"],
            )
        )

    # Sort descending by talk-time
    metrics_list.sort(key=lambda m: m.total_time_ms, reverse=True)

    # Balance score using Herfindahl-Hirschman index normalized
    # 1.0 = perfectly even split, 0.0 = single speaker
    if len(metrics_list) <= 1:
        balance_score = 0.0
    else:
        n = len(metrics_list)
        sum_sq = sum((m.talk_time_pct / 100.0) ** 2 for m in metrics_list)
        # HHI ranges from 1/n to 1. Normalized: (1 - HHI) / (1 - 1/n)
        hhi_min = 1.0 / n
        balance_score = round(max(0.0, min(1.0, (1.0 - sum_sq) / (1.0 - hhi_min))), 2)

    return MeetingSpeakerAnalytics(
        total_duration_ms=total_duration_ms,
        speakers=metrics_list,
        dominant_speaker=dominant_speaker,
        balance_score=balance_score,
    )
