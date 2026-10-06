"""Questions and Answers extractor .

Identifies important questions raised during the call along with answers or whether
they were left unanswered.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from ..config import config

logger = logging.getLogger("lensai_bot.intelligence.questions")


@dataclass
class MeetingQuestion:
    question: str
    asked_by: Optional[str] = None
    answered_by: Optional[str] = None
    answer: Optional[str] = None
    is_answered: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def extract_questions_and_answers(
    transcript_text: str,
    use_llm: bool = True
) -> List[MeetingQuestion]:
    """Extract key questions asked in the meeting and their answers."""
    if use_llm and transcript_text.strip():
        try:
            import ollama

            prompt = f"""You are an executive meeting analyst. Extract the 3 to 6 most important questions asked during this meeting, who asked them, who answered, and a summary of the answer.

Return ONLY a valid JSON list of objects:
[
  {{
    "question": "What is the expected release date for the mobile app?",
    "asked_by": "Sarah",
    "answered_by": "Dave",
    "answer": "Targeting November 15 pending QA approval",
    "is_answered": true
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
                MeetingQuestion(
                    question=item.get("question", ""),
                    asked_by=item.get("asked_by"),
                    answered_by=item.get("answered_by"),
                    answer=item.get("answer"),
                    is_answered=item.get("is_answered", True),
                )
                for item in parsed
            ]
        except Exception as exc:
            logger.debug(f"LLM questions extraction failed: {exc}")

    return []
