"""Executive summary and timestamped chapters generator .

Generates:
- High-level Executive Summary (TL;DR)
- Timestamped Chapters / Topics
- Key Discussion Points
- Next Steps
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..config import config

logger = logging.getLogger("lensai_bot.intelligence.summarizer")


@dataclass
class MeetingChapter:
    title: str
    start_time_str: str  # e.g. "02:15"
    start_time_ms: int
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutiveMeetingSummary:
    executive_summary: str
    key_points: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    chapters: List[MeetingChapter] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def generate_executive_summary(
    transcript_text: str,
    segments: Optional[List[Dict[str, Any]]] = None,
    use_llm: bool = True
) -> ExecutiveMeetingSummary:
    """Generate comprehensive executive summary and timestamped chapter breakdown."""
    if use_llm and transcript_text.strip():
        try:
            import ollama

            # Format sample timeline if segments are provided
            timeline_hints = ""
            if segments:
                # pick sample timestamps across the meeting
                step = max(len(segments) // 6, 1)
                hints = []
                for i in range(0, len(segments), step):
                    s = segments[i]
                    sec = int(s.get("start_time", 0) / 1000)
                    hints.append(f"[{sec // 60:02d}:{sec % 60:02d}] {s.get('speaker', '')}: {s.get('text', '')[:60]}")
                timeline_hints = "\nTimeline outline:\n" + "\n".join(hints)

            prompt = f"""You are a world-class executive chief of staff. Write a concise, comprehensive meeting summary based on this transcript.

Return ONLY valid JSON with this exact schema:
{{
  "executive_summary": "A concise paragraph overview describing what the meeting focused on, who participated, and what was discussed at a high level.",
  "key_points": [
    "Brief discussion point 1 in 10-15 words",
    "Brief discussion point 2 in 10-15 words",
    "Brief discussion point 3 in 10-15 words"
  ],
  "decisions": [
    "Formal decision 1",
    "Formal decision 2"
  ],
  "action_items": [
    "Specific action item with owner and context",
    "Another action item"
  ],
  "next_steps": [
    "Next step or follow-up action 1",
    "Next step or follow-up action 2"
  ],
  "chapters": [
    {{
      "title": "Topic / Agenda Item Name",
      "start_time_str": "MM:SS",
      "summary": "Brief explanation of what was covered during this chapter"
    }}
  ]
}}

Important guidelines:
- Overview: Write 2-3 sentences describing the meeting focus and participants
- Key Discussion Points: MUST be exactly 3-4 short bullet points (10-15 words each). Do NOT include speaker names. Keep them concise and high-level. Example: "Discussed Q4 roadmap priorities and timeline adjustments"
- Decisions Made: Only list formal decisions that were explicitly made
- Action Items: Extract specific tasks that need to be done
- Next Steps: List follow-up actions the team agreed to take
- If no decisions were made, return empty array
- If no action items were assigned, return empty array

Transcript:
{transcript_text[:14000]}
{timeline_hints}
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

            data = json.loads(raw.strip())
            chapters = []
            for ch in data.get("chapters", []):
                ts = ch.get("start_time_str", "00:00")
                ms = 0
                try:
                    parts = ts.split(":")
                    if len(parts) == 2:
                        ms = (int(parts[0]) * 60 + int(parts[1])) * 1000
                except Exception:
                    pass
                chapters.append(
                    MeetingChapter(
                        title=ch.get("title", "Discussion"),
                        start_time_str=ts,
                        start_time_ms=ms,
                        summary=ch.get("summary", ""),
                    )
                )

            return ExecutiveMeetingSummary(
                executive_summary=data.get("executive_summary", "Meeting notes captured."),
                key_points=data.get("key_points", []),
                decisions=data.get("decisions", []),
                action_items=data.get("action_items", []),
                next_steps=data.get("next_steps", []),
                chapters=chapters,
            )
        except Exception as exc:
            logger.warning(f"LLM executive summary generation failed: {exc}")

    # Fallback heuristic summary
    first_lines = transcript_text.strip().split("\n")[:5]
    fallback_summary = " ".join(first_lines) if first_lines else "No transcript available."
    return ExecutiveMeetingSummary(
        executive_summary=fallback_summary[:300],
        key_points=["Meeting recording captured by LensAI Bot."],
        decisions=[],
        action_items=[],
        next_steps=[],
        chapters=[MeetingChapter(title="Meeting Overview", start_time_str="00:00", start_time_ms=0, summary="General discussion.")],
    )
