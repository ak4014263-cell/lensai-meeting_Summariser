"""Grounded 'Ask AI' meeting assistant.

Answers user questions strictly based on what was discussed in the meeting transcript,
citing speaker quotes and timestamps when available.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..config import config

logger = logging.getLogger("lensai_bot.assistant.ask_ai")


def ask_meeting_ai(
    question: str,
    transcript_text: str,
    segments: Optional[List[Dict[str, Any]]] = None,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Answer a user question grounded in the meeting transcript."""
    if not transcript_text.strip():
        return "No meeting transcript is available to answer your question."

    # Format transcript context
    context_lines = []
    if segments:
        for s in segments[:150]:
            sec = int(s.get("start_time", 0) / 1000)
            mmss = f"{sec // 60:02d}:{sec % 60:02d}"
            context_lines.append(f"[{mmss}] {s.get('speaker', 'Speaker')}: {s.get('text', '')}")
        context_str = "\n".join(context_lines)
    else:
        context_str = transcript_text[:12000]

    system_instruction = """You are LensAI Assistant, an intelligent meeting co-pilot.
Your task is to answer the user's question accurately and objectively using ONLY the provided meeting transcript.
- If the answer was explicitly discussed, state what was said, mention who said it, and cite the approximate timestamp if visible.
- If the question was not addressed or mentioned in the transcript, state clearly: "This topic was not discussed during the meeting."
- Keep your tone concise, professional, and helpful.
"""

    prompt = f"""Meeting Transcript:
{context_str}

User Question: {question}

Answer:"""

    try:
        import ollama

        client = ollama.Client(host=config.ollama_host)
        resp = client.generate(
            model=config.ollama_model,
            prompt=f"{system_instruction}\n\n{prompt}",
            options={"temperature": 0.2},
        )
        return resp.get("response", "").strip()
    except Exception as exc:
        logger.error(f"Failed to query Ollama for Ask AI: {exc}")
        return f"Could not generate an answer due to an AI model error: {exc}"
