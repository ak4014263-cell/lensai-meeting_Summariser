"""Professional PDF meeting report and consolidated participant discussion generator (ReportLab)."""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)




def generate_meeting_pdf(
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
    transcript_segments: Optional[List[Dict[str, Any]]] = None,
    participants: Optional[List[str]] = None,
    include_transcript: bool = False,
    include_analytics: bool = False,
) -> bytes:
    """Compile meeting intelligence and diarized dialogue into a consolidated PDF document."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    header_title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1E1B4B"),
    )

    meta_style = ParagraphStyle(
        "DocMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#4B5563"),
    )

    section_heading = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#4338CA"),
        spaceBefore=12,
        spaceAfter=6,
    )

    body_style = ParagraphStyle(
        "BodyTextCustom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#1F2937"),
    )

    bullet_style = ParagraphStyle(
        "BulletCustom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#374151"),
        leftIndent=15,
    )

    speaker_badge_style = ParagraphStyle(
        "SpeakerBadge",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#4F46E5"),
    )

    dialogue_style = ParagraphStyle(
        "DialogueText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#111827"),
    )

    time_style = ParagraphStyle(
        "TimeBadge",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#6B7280"),
    )

    story = []

    # ── Title & Attendees Only ──
    story.append(Paragraph(title or "Meeting Summary", header_title_style))
    story.append(Spacer(1, 6))

    # Extract first names only from participants list
    if participants:
        first_names = [p.strip().split()[0] if p.strip() else p for p in participants]
        participants_list = ", ".join(first_names)
    else:
        participants_list = "Participants"
    
    attendees_style = ParagraphStyle(
        "AttendeesText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#4B5563"),
    )
    story.append(Paragraph(participants_list, attendees_style))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E5E7EB"), spaceBefore=2, spaceAfter=10))

    # ── 1. Overview ──
    story.append(Paragraph("Overview", section_heading))
    summary_clean = executive_summary or "No overview was generated for this session."
    story.append(Paragraph(summary_clean.replace("\n", "<br/>"), body_style))
    story.append(Spacer(1, 12))

    # ── 2. Key Discussion Points ──
    if key_points:
        story.append(Paragraph("Key Discussion Points", section_heading))
        for kp in key_points:
            story.append(Paragraph(f"• &nbsp; {kp}", bullet_style))
            story.append(Spacer(1, 2))
        story.append(Spacer(1, 10))

    # ── 3. Decisions Made ──
    story.append(Paragraph("Decisions Made", section_heading))
    if decisions:
        for dec in decisions:
            story.append(Paragraph(f"• &nbsp; {dec}", bullet_style))
            story.append(Spacer(1, 2))
    else:
        story.append(Paragraph("No formal decisions were recorded.", body_style))
    story.append(Spacer(1, 10))

    # ── 4. Action Items ──
    story.append(Paragraph("Action Items", section_heading))
    if action_items:
        for item in action_items:
            task = item.get("task") or item.get("text") or ""
            assignee = item.get("assignee") or item.get("owner")
            deadline = item.get("deadline")
            
            # Format: Task (Owner: Name, Deadline: Date) or just Task
            item_text = task
            metadata = []
            if assignee:
                metadata.append(f"Owner: {assignee}")
            if deadline:
                metadata.append(f"Deadline: {deadline}")
            if metadata:
                item_text += f" <i>({', '.join(metadata)})</i>"
            
            story.append(Paragraph(f"• &nbsp; {item_text}", bullet_style))
            story.append(Spacer(1, 2))
    else:
        story.append(Paragraph("No specific action items were assigned.", body_style))
    story.append(Spacer(1, 10))

    # ── 5. Next Steps ──
    story.append(Paragraph("Next Steps", section_heading))
    if next_steps:
        for step in next_steps:
            story.append(Paragraph(f"• &nbsp; {step}", bullet_style))
            story.append(Spacer(1, 2))
    else:
        story.append(Paragraph("No next steps were identified.", body_style))
    story.append(Spacer(1, 10))

    # ── 6. Participant Conversational Intelligence (Optional) ──
    if include_analytics and speaker_analytics and speaker_analytics.get("speakers"):
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E5E7EB"), spaceBefore=6, spaceAfter=10))
        story.append(Paragraph("Participant Discussion Analytics", section_heading))
        analytics_rows = [
            [
                Paragraph("<b>Participant</b>", meta_style),
                Paragraph("<b>Talk Time %</b>", meta_style),
                Paragraph("<b>Duration</b>", meta_style),
                Paragraph("<b>Total Words</b>", meta_style),
                Paragraph("<b>Words/Min</b>", meta_style),
                Paragraph("<b>Questions</b>", meta_style),
            ]
        ]
        for spk in speaker_analytics.get("speakers", []):
            time_mins = f"{round(spk.get('total_time_ms', 0) / 60000.0, 1)}m"
            speaker_full = spk.get('speaker', 'Speaker')
            # Extract first name only (split on whitespace, take first part)
            speaker_display = speaker_full.strip().split()[0] if speaker_full.strip() else 'Speaker'
            analytics_rows.append([
                Paragraph(f"<b>{speaker_display}</b>", body_style),
                Paragraph(f"{spk.get('talk_time_pct')}%", body_style),
                Paragraph(time_mins, body_style),
                Paragraph(str(spk.get("total_words", 0)), body_style),
                Paragraph(str(spk.get("words_per_minute", 0)), body_style),
                Paragraph(str(spk.get("question_count", 0)), body_style),
            ])
        analytics_table = Table(analytics_rows, colWidths=[150, 75, 75, 75, 75, 80])
        analytics_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F9FAFB")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
                ("PADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ])
        )
        story.append(analytics_table)
        story.append(Spacer(1, 14))

    # ── 7. Consolidated Participant Discussion (Optional - Full Transcript) ──
    if include_transcript and transcript_segments:
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E5E7EB"), spaceBefore=6, spaceAfter=10))
        story.append(Paragraph("Full Transcript", section_heading))
        story.append(Paragraph(
            "Complete speaker-attributed dialogue chronologically consolidated below:",
            meta_style
        ))
        story.append(Spacer(1, 8))

        dialogue_rows = []
        speaker_colors = [
            colors.HexColor("#312E81"),  # Indigo
            colors.HexColor("#065F46"),  # Emerald
            colors.HexColor("#831843"),  # Rose
            colors.HexColor("#1E3A8A"),  # Blue
            colors.HexColor("#701A75"),  # Purple
        ]
        speaker_color_map = {}

        for s in transcript_segments:
            text = (s.get("text") or "").strip()
            if not text:
                continue

            sec = int(s.get("start_time", 0) / 1000)
            timestamp_str = f"{sec // 60:02d}:{sec % 60:02d}"
            spk = s.get("speaker") or "Speaker"
            
            # Extract first name only (split on whitespace, take first part)
            spk_display = spk.strip().split()[0] if spk.strip() else "Speaker"

            if spk not in speaker_color_map:
                color_idx = len(speaker_color_map) % len(speaker_colors)
                speaker_color_map[spk] = speaker_colors[color_idx]

            spk_color = speaker_color_map[spk].hexval()
            spk_formatted = f"<font color='{spk_color}'><b>{spk_display}</b></font>"

            dialogue_rows.append([
                Paragraph(f"[{timestamp_str}]", time_style),
                Paragraph(spk_formatted, speaker_badge_style),
                Paragraph(text, dialogue_style),
            ])

        if dialogue_rows:
            dialogue_table = Table(dialogue_rows, colWidths=[45, 95, 390])
            dialogue_table.setStyle(
                TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 4),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#F3F4F6")),
                ])
            )
            story.append(dialogue_table)

    doc.build(story)
    return buffer.getvalue()
