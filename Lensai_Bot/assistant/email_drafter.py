"""Follow-up email drafter.

Generates a polished recap email containing:
- Executive summary
- Key decisions
- Action items & assigned owners
- Next steps
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..config import config

logger = logging.getLogger("lensai_bot.assistant.email_drafter")


def draft_followup_email(
    meeting_title: str,
    executive_summary: str,
    action_items: List[Dict[str, Any]],
    decisions: Optional[List[str]] = None,
    attendees: Optional[List[str]] = None,
    use_llm: bool = True,
) -> Dict[str, str]:
    """Draft a professional follow-up email.
    
    Returns:
      {
        "subject": "Recap & Next Steps: [Meeting Title]",
        "body_text": "...",
        "body_html": "..."
      }
    """
    subject = f"Recap & Action Items: {meeting_title}"

    # Build action items list
    action_lines = []
    for item in action_items:
        task = item.get("task", "")
        owner = item.get("assignee") or "Unassigned"
        deadline = item.get("deadline")
        suffix = f" (by {deadline})" if deadline else ""
        action_lines.append(f"- **@{owner}**: {task}{suffix}")
    actions_formatted = "\n".join(action_lines) if action_lines else "- No explicit action items assigned."

    decisions_lines = []
    for d in (decisions or []):
        decisions_lines.append(f"- {d}")
    decisions_formatted = "\n".join(decisions_lines) if decisions_lines else "- None noted."

    if use_llm:
        try:
            import ollama

            prompt = f"""You are an executive assistant drafting a high-priority meeting follow-up email.

Meeting Title: {meeting_title}
Attendees: {', '.join(attendees) if attendees else 'Team'}

Executive Summary:
{executive_summary}

Decisions Made:
{decisions_formatted}

Action Items:
{actions_formatted}

Draft an email with Subject line and Body. Keep it crisp, structured with markdown bold headers, and action-oriented. Do not include markdown code block quotes.
"""
            client = ollama.Client(host=config.ollama_host)
            resp = client.generate(
                model=config.ollama_model,
                prompt=prompt,
                options={"temperature": 0.2},
            )
            raw = resp.get("response", "").strip()
            # Extract subject if provided by LLM
            lines = raw.split("\n")
            if lines and lines[0].lower().startswith("subject:"):
                subject = lines[0][8:].strip()
                body_text = "\n".join(lines[1:]).strip()
            else:
                body_text = raw
            return {
                "subject": subject,
                "body_text": body_text,
            }
        except Exception as exc:
            logger.debug(f"LLM email draft fallback: {exc}")

    # Fallback template
    body_text = f"""Hi team,

Thank you for your time today in the {meeting_title} sync. Here is a quick recap of what we discussed and next steps:

### Executive Summary
{executive_summary}

### Key Decisions
{decisions_formatted}

### Action Items & Commitments
{actions_formatted}

Please reply if anything was missed or needs adjustment.

Best regards,
LensAI Meeting Assistant"""

    return {
        "subject": subject,
        "body_text": body_text,
    }
