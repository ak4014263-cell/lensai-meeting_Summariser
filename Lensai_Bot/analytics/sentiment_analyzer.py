"""Meeting and per-speaker sentiment & tone analyzer .

Evaluates:
- Overall conversation mood (Positive / Neutral / Negative / Mixed)
- Sentiment score (-1.0 to +1.0)
- Per-speaker sentiment breakdown
- Key positive highlights and tension/concern points
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..config import config

logger = logging.getLogger("lensai_bot.analytics.sentiment")

# Simple Lexical fallbacks when LLM is unavailable
POSITIVE_WORDS = {
    "great", "excellent", "awesome", "agree", "perfect", "good", "love", "excited",
    "happy", "resolved", "approved", "success", "congrats", "thanks", "helpful", "clear"
}
NEGATIVE_WORDS = {
    "bad", "issue", "problem", "delay", "blocked", "fail", "broken", "disagree",
    "concern", "risk", "frustrated", "confused", "late", "error", "bug", "worried"
}


@dataclass
class SpeakerSentiment:
    speaker: str
    sentiment: str  # positive | neutral | negative
    score: float    # -1.0 to +1.0
    positive_words_count: int = 0
    negative_words_count: int = 0


@dataclass
class MeetingSentimentReport:
    overall_sentiment: str  # "positive" | "neutral" | "negative" | "mixed"
    overall_score: float    # -1.0 to +1.0
    positive_percentage: float
    neutral_percentage: float
    negative_percentage: float
    speaker_sentiments: List[SpeakerSentiment] = field(default_factory=list)
    key_positive_moments: List[str] = field(default_factory=list)
    key_tension_moments: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _lexical_sentiment(text: str) -> tuple[str, float, int, int]:
    """Fast local lexical sentiment fallback."""
    tokens = [w.strip(".,!?\"'()").lower() for w in text.split()]
    pos = sum(1 for w in tokens if w in POSITIVE_WORDS)
    neg = sum(1 for w in tokens if w in NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return "neutral", 0.0, 0, 0
    score = (pos - neg) / float(total)
    if score > 0.2:
        sentiment = "positive"
    elif score < -0.2:
        sentiment = "negative"
    else:
        sentiment = "neutral"
    return sentiment, round(score, 2), pos, neg


def analyze_sentiment(
    transcript_text: str,
    segments: Optional[List[Dict[str, Any]]] = None,
    use_llm: bool = True
) -> MeetingSentimentReport:
    """Analyze the sentiment and tone of the meeting transcript."""
    # 1. Per-speaker lexical baseline
    speaker_segments: Dict[str, List[str]] = {}
    if segments:
        for seg in segments:
            spk = seg.get("speaker") or "Unknown"
            speaker_segments.setdefault(spk, []).append(seg.get("text") or "")

    speaker_results: List[SpeakerSentiment] = []
    total_pos = 0
    total_neg = 0

    for spk, texts in speaker_segments.items():
        combined = " ".join(texts)
        sent, score, pos, neg = _lexical_sentiment(combined)
        total_pos += pos
        total_neg += neg
        speaker_results.append(
            SpeakerSentiment(
                speaker=spk,
                sentiment=sent,
                score=score,
                positive_words_count=pos,
                negative_words_count=neg,
            )
        )

    # 2. Try LLM refinement if available
    llm_report = None
    if use_llm and transcript_text.strip():
        try:
            import ollama
            prompt = f"""You are an executive meeting analyst. Analyze the emotional tone and sentiment of the following transcript.
Return ONLY valid JSON matching this exact structure:
{{
  "overall_sentiment": "positive" | "neutral" | "negative" | "mixed",
  "overall_score": float between -1.0 and 1.0,
  "positive_percentage": float between 0 and 100,
  "neutral_percentage": float between 0 and 100,
  "negative_percentage": float between 0 and 100,
  "key_positive_moments": ["quote or moment 1", "quote or moment 2"],
  "key_tension_moments": ["quote or concern 1", "quote or concern 2"]
}}

Transcript:
{transcript_text[:5000]}
"""
            client = ollama.Client(host=config.ollama_host)
            resp = client.generate(
                model=config.ollama_model,
                prompt=prompt,
                options={"temperature": 0.1},
            )
            raw = resp.get("response", "").strip()
            # Clean JSON markdown fences
            if raw.startswith("```json"):
                raw = raw[7:]
            if raw.startswith("```"):
                raw = raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            llm_report = json.loads(raw.strip())
        except Exception as exc:
            logger.debug(f"LLM sentiment analysis fell back to lexical: {exc}")

    if llm_report and isinstance(llm_report, dict):
        return MeetingSentimentReport(
            overall_sentiment=llm_report.get("overall_sentiment", "neutral"),
            overall_score=float(llm_report.get("overall_score", 0.0)),
            positive_percentage=float(llm_report.get("positive_percentage", 50.0)),
            neutral_percentage=float(llm_report.get("neutral_percentage", 40.0)),
            negative_percentage=float(llm_report.get("negative_percentage", 10.0)),
            speaker_sentiments=speaker_results,
            key_positive_moments=llm_report.get("key_positive_moments", []),
            key_tension_moments=llm_report.get("key_tension_moments", []),
        )

    # Pure lexical fallback calculation
    total_tokens = total_pos + total_neg
    if total_tokens > 0:
        pos_pct = round((total_pos / total_tokens) * 100, 1)
        neg_pct = round((total_neg / total_tokens) * 100, 1)
        neu_pct = max(0.0, 100.0 - pos_pct - neg_pct)
        score = round((total_pos - total_neg) / float(total_tokens), 2)
    else:
        pos_pct, neu_pct, neg_pct = 20.0, 70.0, 10.0
        score = 0.1

    overall = "positive" if score > 0.2 else ("negative" if score < -0.2 else "neutral")

    return MeetingSentimentReport(
        overall_sentiment=overall,
        overall_score=score,
        positive_percentage=pos_pct,
        neutral_percentage=neu_pct,
        negative_percentage=neg_pct,
        speaker_sentiments=speaker_results,
        key_positive_moments=[],
        key_tension_moments=[],
    )
