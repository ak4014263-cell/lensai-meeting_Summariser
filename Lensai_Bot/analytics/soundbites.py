"""Key soundbites & highlight detection.

Extracts memorable quotes, key agreements, pivotal announcements, and important
takeaway soundbites with timestamps.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

from ..config import config

logger = logging.getLogger("lensai_bot.analytics.soundbites")


@dataclass
class Soundbite:
    speaker: str
    quote: str
    start_time_ms: int
    end_time_ms: int
    category: str  # "announcement" | "decision" | "milestone" | "key_insight" | "concern"
    importance_score: float  # 0.0 - 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def extract_soundbites(
    segments: List[Dict[str, Any]],
    use_llm: bool = True
) -> List[Soundbite]:
    """Detect and extract impactful soundbites from transcript segments."""
    if not segments:
        return []

    # Fast heuristic candidate collection (looking for decision or insight markers)
    impact_markers = [
        "we decided", "we need to", "the plan is", "going forward",
        "key takeaway", "important thing", "announcement", "deadline is",
        "our goal", "the problem is", "huge milestone", "let's commit to"
    ]

    candidates = []
    for s in segments:
        txt = (s.get("text") or "").lower()
        if any(marker in txt for marker in impact_markers):
            candidates.append(s)

    # If LLM is enabled and we have text, use it to curate and categorize
    if use_llm and len(segments) > 0:
        try:
            import ollama

            # Format formatted snippet
            sample_lines = []
            for s in segments[:100]:  # focus on top segments
                spk = s.get("speaker") or "Speaker"
                start = s.get("start_time", 0)
                sec = int(start / 1000)
                mmss = f"{sec // 60:02d}:{sec % 60:02d}"
                sample_lines.append(f"[{mmss}] {spk}: {s.get('text', '')}")

            prompt = f"""You are a professional meeting editor. Select the 3 to 6 most critical, high-impact soundbites/quotes from this meeting.
Return ONLY valid JSON as a list of objects:
[
  {{
    "speaker": "Name",
    "quote": "Exact or near-exact quote",
    "timestamp_str": "MM:SS",
    "category": "decision" | "announcement" | "milestone" | "key_insight" | "concern",
    "importance_score": 0.9
  }}
]

Transcript:
{chr(10).join(sample_lines)}
"""
            client = ollama.Client(host=config.ollama_host)
            resp = client.generate(
                model=config.ollama_model,
                prompt=prompt,
                options={"temperature": 0.2},
            )
            raw = resp.get("response", "").strip()
            if raw.startswith("```json"):
                raw = raw[7:]
            if raw.startswith("```"):
                raw = raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]

            parsed = json.loads(raw.strip())
            results: List[Soundbite] = []
            for item in parsed:
                # Convert MM:SS to ms
                ts = item.get("timestamp_str", "00:00")
                ms = 0
                try:
                    parts = ts.split(":")
                    if len(parts) == 2:
                        ms = (int(parts[0]) * 60 + int(parts[1])) * 1000
                except Exception:
                    pass

                results.append(
                    Soundbite(
                        speaker=item.get("speaker", "Unknown"),
                        quote=item.get("quote", ""),
                        start_time_ms=ms,
                        end_time_ms=ms + 5000,
                        category=item.get("category", "key_insight"),
                        importance_score=float(item.get("importance_score", 0.8)),
                    )
                )
            if results:
                return results
        except Exception as exc:
            logger.debug(f"LLM soundbite extraction fell back to heuristics: {exc}")

    # Fallback to candidates from heuristic
    fallback_bites: List[Soundbite] = []
    for c in candidates[:5]:
        fallback_bites.append(
            Soundbite(
                speaker=c.get("speaker") or "Speaker",
                quote=c.get("text") or "",
                start_time_ms=c.get("start_time", 0),
                end_time_ms=c.get("end_time", c.get("start_time", 0) + 4000),
                category="key_insight",
                importance_score=0.75,
            )
        )
    return fallback_bites
