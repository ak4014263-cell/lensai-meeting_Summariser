"""Markdown and Notion-ready export generator ."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def export_meeting_markdown(
    title: str,
    date_str: str,
    duration_str: str,
    executive_summary: str,
    key_points: List[str],
    action_items: List[Dict[str, Any]],
    decisions: List[str],
    next_steps: Optional[List[str]] = None,
    speaker_analytics: Optional[Dict[str, Any]] = None,
    sentiment_report: Optional[Dict[str, Any]] = None,
    soundbites: Optional[List[Dict[str, Any]]] = None,
    questions: Optional[List[Dict[str, Any]]] = None,
    risks: Optional[List[Dict[str, Any]]] = None,
    transcript_segments: Optional[List[Dict[str, Any]]] = None,
    include_transcript: bool = False,
    include_analytics: bool = False,
) -> str:
    """Generate a comprehensive Markdown document with meeting summary."""
    md = []
    md.append(f"# 📝 {title}")
    md.append(f"**Date**: {date_str} | **Duration**: {duration_str}\n")
    md.append("---\n")

    # Overview
    md.append("## Overview")
    md.append(f"{executive_summary}\n")

    # Key Discussion Points
    if key_points:
        md.append("## Key Discussion Points")
        for kp in key_points:
            md.append(f"- {kp}")
        md.append("")

    # Decisions Made
    md.append("## Decisions Made")
    if decisions:
        for dec in decisions:
            md.append(f"- {dec}")
    else:
        md.append("No formal decisions were recorded.")
    md.append("")

    # Action Items
    md.append("## Action Items")
    if action_items:
        for item in action_items:
            task = item.get("task") or item.get("text") or ""
            assignee = item.get("assignee") or item.get("owner")
            deadline = item.get("deadline")
            
            metadata = []
            if assignee:
                metadata.append(f"Owner: {assignee}")
            if deadline:
                metadata.append(f"Deadline: {deadline}")
            
            if metadata:
                md.append(f"- {task} *({', '.join(metadata)})*")
            else:
                md.append(f"- {task}")
    else:
        md.append("No specific action items were assigned.")
    md.append("")

    # Next Steps
    md.append("## Next Steps")
    if next_steps:
        for step in next_steps:
            md.append(f"- {step}")
    else:
        md.append("No next steps were identified.")
    md.append("")

    # Speaker Analytics (Optional)
    if include_analytics and speaker_analytics and speaker_analytics.get("speakers"):
        md.append("---\n")
        md.append("## 📊 Speaker Analytics")
        md.append(f"- **Dominant Speaker**: {speaker_analytics.get('dominant_speaker') or 'N/A'}")
        md.append(f"- **Conversation Balance Score**: {int((speaker_analytics.get('balance_score', 0)) * 100)}%\n")
        md.append("| Speaker | Talk Time % | Total Words | WPM | Monologue Max | Questions |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for spk in speaker_analytics.get("speakers", []):
            time_mins = round(spk.get("total_time_ms", 0) / 60000.0, 1)
            mono_sec = int(spk.get("longest_monologue_ms", 0) / 1000)
            md.append(
                f"| {spk.get('speaker')} | {spk.get('talk_time_pct')}% ({time_mins}m) | "
                f"{spk.get('total_words')} | {spk.get('words_per_minute')} | {mono_sec}s | {spk.get('question_count')} |"
            )
        md.append("")

    # Full Transcript (Optional)
    if include_transcript and transcript_segments:
        md.append("---\n")
        md.append("## 📜 Full Transcript")
        for s in transcript_segments:
            sec = int(s.get("start_time", 0) / 1000)
            mmss = f"{sec // 60:02d}:{sec % 60:02d}"
            spk = s.get("speaker") or "Speaker"
            md.append(f"**`[{mmss}]` {spk}**: {s.get('text', '')}\n")

    return "\n".join(md)
