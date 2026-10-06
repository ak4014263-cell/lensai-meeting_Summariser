"""Risks, roadblocks, and blocker detector (Fireflies parity).

Identifies project risks, blockers, compliance concerns, or uncertainties raised in the discussion.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from ..config import config

logger = logging.getLogger("lensai_bot.intelligence.risks")


@dataclass
class MeetingRisk:
    risk: str
    severity: str  # "high" | "medium" | "low"
    mitigation: Optional[str] = None
    raised_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def detect_risks_and_blockers(
    transcript_text: str,
    use_llm: bool = True
) -> List[MeetingRisk]:
    """Detect discussed risks, technical blockers, and uncertainties."""
    if use_llm and transcript_text.strip():
        try:
            import ollama

            prompt = f"""You are a risk management consultant. Extract any technical roadblocks, project delays, budget concerns, or risks discussed in this meeting.

Return ONLY a valid JSON list:
[
  {{
    "risk": "Third-party payment gateway migration might delay checkout by 2 weeks",
    "severity": "high",
    "mitigation": "Assign 2 additional backend engineers to speed up testing",
    "raised_by": "Alex"
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
                MeetingRisk(
                    risk=item.get("risk", ""),
                    severity=item.get("severity", "medium"),
                    mitigation=item.get("mitigation"),
                    raised_by=item.get("raised_by"),
                )
                for item in parsed
            ]
        except Exception as exc:
            logger.debug(f"LLM risk detection failed: {exc}")

    return []
