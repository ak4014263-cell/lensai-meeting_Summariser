"""Action items and task extractor .

Extracts:
- Task description
- Assignee / Owner (who is responsible)
- Deadline / Due date / Timing commitment
- Source quote and timestamp offset
- Priority (high, medium, low)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from ..config import config

logger = logging.getLogger("lensai_bot.intelligence.actions")


@dataclass
class ActionItem:
    task: str
    assignee: Optional[str] = None
    deadline: Optional[str] = None
    priority: str = "medium"  # "high" | "medium" | "low"
    context_quote: Optional[str] = None
    source_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def extract_action_items(
    transcript_text: str,
    segments: Optional[List[Dict[str, Any]]] = None,
    use_llm: bool = True
) -> List[ActionItem]:
    """Extract structured action items with owners and deadlines."""
    items: List[ActionItem] = []

    if use_llm and transcript_text.strip():
        try:
            import ollama

            prompt = f"""You are an expert executive project manager. Extract all concrete action items, commitments, and assigned tasks from this meeting transcript.

For each action item provide:
- task: clear, imperative statement of what needs to be done
- assignee: person assigned or committed to it (or "Unassigned" if not specified)
- deadline: deadline, timeframe or date mentioned (or "Not specified")
- priority: "high", "medium", or "low"
- context_quote: short snippet from the meeting where this was committed to

Return ONLY a valid JSON array of objects:
[
  {{
    "task": "Prepare the Q3 product roadmap deck",
    "assignee": "Alex",
    "deadline": "By Friday 5 PM",
    "priority": "high",
    "context_quote": "Alex: I'll finish the Q3 roadmap deck by Friday"
  }}
]

Transcript:
{transcript_text[:12000]}
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
            for entry in parsed:
                # Find matching segment timestamp if possible
                source_ms = None
                quote = entry.get("context_quote")
                if quote and segments:
                    q_words = set(quote.lower().split())
                    best_match = None
                    max_overlap = 0
                    for seg in segments:
                        s_words = set((seg.get("text") or "").lower().split())
                        overlap = len(q_words & s_words)
                        if overlap > max_overlap:
                            max_overlap = overlap
                            best_match = seg.get("start_time")
                    if max_overlap >= 3:
                        source_ms = best_match

                items.append(
                    ActionItem(
                        task=entry.get("task", ""),
                        assignee=entry.get("assignee") if entry.get("assignee") != "Unassigned" else None,
                        deadline=entry.get("deadline") if entry.get("deadline") != "Not specified" else None,
                        priority=entry.get("priority", "medium"),
                        context_quote=entry.get("context_quote"),
                        source_ms=source_ms,
                    )
                )
            if items:
                return items
        except Exception as exc:
            logger.debug(f"LLM action item extraction fell back to regex heuristics: {exc}")

    # Fallback heuristic using commitment patterns
    patterns = [
        r"(?:i will|i'll|we will|we'll|let's|going to|needs to|action item is to)\s+([^.?!]+)",
        r"(?:@?(\w+)\s+(?:will|should|to)\s+([^.?!]+))",
    ]
    for seg in (segments or []):
        txt = seg.get("text", "")
        spk = seg.get("speaker")
        for pat in patterns:
            for match in re.finditer(pat, txt, re.IGNORECASE):
                task_snippet = match.group(0).strip()
                if len(task_snippet) > 10:
                    items.append(
                        ActionItem(
                            task=task_snippet.capitalize(),
                            assignee=spk,
                            deadline=None,
                            priority="medium",
                            context_quote=txt,
                            source_ms=seg.get("start_time"),
                        )
                    )
                if len(items) >= 8:
                    break

    return items
