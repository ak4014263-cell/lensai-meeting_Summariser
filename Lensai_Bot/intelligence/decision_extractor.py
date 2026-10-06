"""Decisions made extractor .

Extracts explicit decisions, agreements, consensus points, and approvals from the meeting.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from ..config import config

logger = logging.getLogger("lensai_bot.intelligence.decisions")


@dataclass
class MeetingDecision:
    decision: str
    context: Optional[str] = None
    agreed_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def extract_decisions(
    transcript_text: str,
    use_llm: bool = True
) -> List[MeetingDecision]:
    """Extract formal decisions and consensus reached in the meeting."""
    if use_llm and transcript_text.strip():
        try:
            import ollama

            prompt = f"""You are an executive recording secretary. Identify all key decisions, formal approvals, and explicit agreements reached in this meeting.

Return ONLY a valid JSON list:
[
  {{
    "decision": "Team agreed to migrate infrastructure to Google Cloud by Q4",
    "context": "Prompted by pricing and scalability requirements",
    "agreed_by": "All / Lead Architect"
  }}
]

Transcript:
{transcript_text[:10000]}
"""
            client = ollama.Client(host=config.ollama_host)
            resp = client.generate(
                model=config.ollama_model,
                prompt=prompt,
                options={"temperature": 0.1},
            )
            raw = resp.get("response", "").strip()
            if raw.startswith("```json"):
                raw = raw[7:]
            if raw.startswith("```"):
                raw = raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]

            parsed = json.loads(raw.strip())
            return [
                MeetingDecision(
                    decision=item.get("decision", ""),
                    context=item.get("context"),
                    agreed_by=item.get("agreed_by"),
                )
                for item in parsed
            ]
        except Exception as exc:
            logger.debug(f"LLM decision extraction fell back to heuristics: {exc}")

    # Heuristic fallback
    decisions = []
    markers = [r"decided to\s+([^.?!]+)", r"agreed that\s+([^.?!]+)", r"approved\s+([^.?!]+)"]
    for m in markers:
        for match in re.finditer(m, transcript_text, re.IGNORECASE):
            text = match.group(0).strip().capitalize()
            decisions.append(MeetingDecision(decision=text))
            if len(decisions) >= 5:
                break
    return decisions
