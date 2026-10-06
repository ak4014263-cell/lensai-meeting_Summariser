"""Command Line Interface (CLI) for LensAI Bot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analytics.sentiment_analyzer import analyze_sentiment
from .analytics.soundbites import extract_soundbites
from .analytics.speaker_metrics import calculate_speaker_metrics
from .assistant.ask_ai import ask_meeting_ai
from .assistant.email_drafter import draft_followup_email
from .config import config
from .export.csv_export import export_action_items_csv
from .export.markdown_export import export_meeting_markdown
from .intelligence.action_extractor import extract_action_items
from .intelligence.decision_extractor import extract_decisions
from .intelligence.questions_extractor import extract_questions_and_answers
from .intelligence.risk_detector import detect_risks_and_blockers
from .intelligence.summarizer import generate_executive_summary
from .runner.meet_bot import MeetBotRunner
from .transcription.whisper_engine import WhisperEngine


def cmd_join(args):
    """Dispatch bot into a live Google Meet call."""
    url = args.url
    print(f"🤖 Dispatching LensAI Bot into: {url}")
    runner = MeetBotRunner(
        meet_url=url,
        bot_name=args.name or config.bot_name,
        event_callback=lambda msg, lvl: print(f"[{lvl.upper()}] {msg}"),
    )
    audio_path = runner.run()
    print(f"✅ Call completed. Recording saved to: {audio_path}")


def cmd_analyze(args):
    """Run the complete AI intelligence analysis on an audio file or transcript."""
    transcript_text = ""
    segments = []

    if args.audio:
        print(f"🎙️ Transcribing audio with Faster-Whisper: {args.audio}")
        engine = WhisperEngine()
        seg_objs = engine.transcribe(args.audio)
        segments = [s.to_dict() for s in seg_objs]
        transcript_text = "\n".join(f"{s['speaker']}: {s['text']}" for s in segments)
    elif args.transcript:
        print(f"📄 Reading transcript file: {args.transcript}")
        transcript_text = Path(args.transcript).read_text(encoding="utf-8")
        # Build segments from lines
        for line in transcript_text.splitlines():
            line = line.strip()
            if not line:
                continue
            spk = "Speaker"
            txt = line
            if ":" in line:
                parts = line.split(":", 1)
                spk = parts[0].strip()
                txt = parts[1].strip()
            segments.append({"speaker": spk, "text": txt, "start_time": 0, "end_time": 5000})

    print("🧠 Extracting Executive Summary & Chapters...")
    summary_obj = generate_executive_summary(transcript_text, segments)

    print("🎯 Extracting Action Items & Assignees...")
    actions = extract_action_items(transcript_text, segments)

    print("✅ Extracting Decisions...")
    decisions = extract_decisions(transcript_text)

    print("📊 Computing Speaker Talk-time Metrics...")
    speaker_analytics = calculate_speaker_metrics(segments)

    print("🎭 Analyzing Meeting Sentiment & Mood...")
    sentiment = analyze_sentiment(transcript_text, segments)

    print("🎙️ Extracting Notable Soundbites...")
    soundbites = extract_soundbites(segments)

    print("❓ Extracting Questions & Answers...")
    questions = extract_questions_and_answers(transcript_text)

    print("⚠️ Extracting Risks & Blockers...")
    risks = detect_risks_and_blockers(transcript_text)

    # Export Markdown
    md_content = export_meeting_markdown(
        title=args.title or "Meeting Intelligence Report",
        date_str="Today",
        duration_str=f"{round(speaker_analytics.total_duration_ms / 60000.0, 1)} mins",
        executive_summary=summary_obj.executive_summary,
        key_points=summary_obj.key_points,
        action_items=[a.to_dict() for a in actions],
        decisions=[d.decision for d in decisions],
        speaker_analytics=speaker_analytics.to_dict(),
        sentiment_report=sentiment.to_dict(),
        soundbites=[sb.to_dict() for sb in soundbites],
        questions=[q.to_dict() for q in questions],
        risks=[r.to_dict() for r in risks],
        transcript_segments=segments,
    )

    out_file = args.output or "meeting_report.md"
    Path(out_file).write_text(md_content, encoding="utf-8")
    print(f"\n🎉 Complete Meeting Report saved to: {out_file}")

    if args.csv_actions:
        csv_file = args.csv_actions
        csv_content = export_action_items_csv([a.to_dict() for a in actions], args.title or "Meeting")
        Path(csv_file).write_text(csv_content, encoding="utf-8")
        print(f"📊 Action items CSV saved to: {csv_file}")


def cmd_ask(args):
    """Ask a question grounded in the meeting transcript."""
    transcript_text = Path(args.transcript).read_text(encoding="utf-8")
    answer = ask_meeting_ai(args.question, transcript_text)
    print(f"\n🤖 Answer:\n{answer}")


def cmd_email(args):
    """Draft a follow-up email from meeting summary & action items."""
    transcript_text = Path(args.transcript).read_text(encoding="utf-8")
    summary = generate_executive_summary(transcript_text)
    actions = extract_action_items(transcript_text)
    decisions = extract_decisions(transcript_text)

    email = draft_followup_email(
        meeting_title=args.title or "Project Sync",
        executive_summary=summary.executive_summary,
        action_items=[a.to_dict() for a in actions],
        decisions=[d.decision for d in decisions],
    )
    print(f"\nSubject: {email['subject']}\n")
    print(email["body_text"])


def main():
    parser = argparse.ArgumentParser(description="LensAI Bot CLI — Full Meeting Intelligence Suite")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # join
    p_join = subparsers.add_parser("join", help="Join a live Google Meet call")
    p_join.add_argument("--url", required=True, help="Google Meet URL")
    p_join.add_argument("--name", help="Custom bot participant name")
    p_join.set_defaults(func=cmd_join)

    # analyze
    p_an = subparsers.add_parser("analyze", help="Run full AI analysis on audio or transcript")
    p_an.add_argument("--audio", help="Path to meeting audio file")
    p_an.add_argument("--transcript", help="Path to text transcript file")
    p_an.add_argument("--title", default="Team Meeting", help="Meeting title")
    p_an.add_argument("--output", default="meeting_report.md", help="Output Markdown report path")
    p_an.add_argument("--csv-actions", help="Optional CSV output file for action items")
    p_an.set_defaults(func=cmd_analyze)

    # ask
    p_ask = subparsers.add_parser("ask", help="Ask AI a question grounded in the meeting")
    p_ask.add_argument("--transcript", required=True, help="Path to transcript file")
    p_ask.add_argument("--question", required=True, help="Question to ask")
    p_ask.set_defaults(func=cmd_ask)

    # email
    p_email = subparsers.add_parser("email", help="Draft a post-meeting recap email")
    p_email.add_argument("--transcript", required=True, help="Path to transcript file")
    p_email.add_argument("--title", default="Team Sync", help="Meeting title")
    p_email.set_defaults(func=cmd_email)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
