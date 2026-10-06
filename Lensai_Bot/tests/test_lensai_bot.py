"""Unit and integration tests for LensAI Bot ."""

from __future__ import annotations

import unittest
from Lensai_Bot.analytics.speaker_metrics import calculate_speaker_metrics
from Lensai_Bot.analytics.sentiment_analyzer import analyze_sentiment
from Lensai_Bot.analytics.soundbites import extract_soundbites
from Lensai_Bot.intelligence.action_extractor import extract_action_items
from Lensai_Bot.intelligence.decision_extractor import extract_decisions
from Lensai_Bot.calendar.rules import CalendarEventRule
from Lensai_Bot.calendar.google_calendar import extract_meeting_url
from Lensai_Bot.export.markdown_export import export_meeting_markdown
from Lensai_Bot.export.csv_export import export_action_items_csv


class TestLensAIBot(unittest.TestCase):
    def setUp(self):
        self.sample_segments = [
            {
                "speaker": "Alice",
                "start_time": 0,
                "end_time": 10000,
                "text": "Good morning team! Today we need to decide on our cloud infrastructure migration.",
            },
            {
                "speaker": "Bob",
                "start_time": 11000,
                "end_time": 25000,
                "text": "I reviewed the costs and I think AWS will be too expensive. Can we use Google Cloud instead?",
            },
            {
                "speaker": "Alice",
                "start_time": 26000,
                "end_time": 40000,
                "text": "We decided to migrate our backend to Google Cloud. Bob will prepare the deployment script by Friday.",
            },
            {
                "speaker": "Charlie",
                "start_time": 41000,
                "end_time": 50000,
                "text": "Awesome! I love this plan. I will review the architecture tomorrow morning.",
            },
        ]
        self.sample_transcript = "\n".join(f"{s['speaker']}: {s['text']}" for s in self.sample_segments)

    def test_speaker_metrics(self):
        analytics = calculate_speaker_metrics(self.sample_segments)
        self.assertEqual(len(analytics.speakers), 3)
        # Alice spoke 10s + 14s = 24s
        self.assertEqual(analytics.dominant_speaker, "Alice")
        self.assertGreater(analytics.balance_score, 0.5)
        # Bob asked a question
        bob = next(s for s in analytics.speakers if s.speaker == "Bob")
        self.assertEqual(bob.question_count, 1)

    def test_sentiment_analysis(self):
        report = analyze_sentiment(self.sample_transcript, self.sample_segments, use_llm=False)
        self.assertIn(report.overall_sentiment, ["positive", "neutral", "mixed"])
        self.assertGreaterEqual(report.positive_percentage, 0.0)

    def test_soundbites_extraction(self):
        soundbites = extract_soundbites(self.sample_segments, use_llm=False)
        self.assertIsInstance(soundbites, list)
        self.assertTrue(any("decided" in sb.quote.lower() for sb in soundbites))

    def test_action_items_heuristics(self):
        actions = extract_action_items(self.sample_transcript, self.sample_segments, use_llm=False)
        self.assertTrue(len(actions) > 0)

    def test_decisions_heuristics(self):
        decisions = extract_decisions(self.sample_transcript, use_llm=False)
        self.assertTrue(len(decisions) > 0)
        self.assertTrue(any("decided" in d.decision.lower() for d in decisions))

    def test_calendar_rules(self):
        rule = CalendarEventRule(only_with_video_link=True, only_external=False)
        # Event with meet link
        e1 = {"summary": "Product Review", "meeting_url": "https://meet.google.com/abc-defg-hij"}
        ok1, _ = rule.is_eligible(e1)
        self.assertTrue(ok1)

        # Event without meet link
        e2 = {"summary": "Coffee Break", "meeting_url": None}
        ok2, _ = rule.is_eligible(e2)
        self.assertFalse(ok2)

        # Ignored title
        e3 = {"summary": "Focus Time", "meeting_url": "https://meet.google.com/abc-defg-hij"}
        ok3, _ = rule.is_eligible(e3)
        self.assertFalse(ok3)

    def test_calendar_url_extraction(self):
        e1 = {"hangoutLink": "https://meet.google.com/xyz-uvwx-rst"}
        self.assertEqual(extract_meeting_url(e1), "https://meet.google.com/xyz-uvwx-rst")

        e2 = {"description": "Join Zoom Meeting: https://company.zoom.us/j/1234567890?pwd=abc"}
        self.assertIn("zoom.us/j/1234567890", extract_meeting_url(e2))

    def test_export_markdown_and_csv(self):
        md = export_meeting_markdown(
            title="Q3 Strategy",
            date_str="2026-09-15",
            duration_str="45m",
            executive_summary="Team aligned on cloud migration.",
            key_points=["Google Cloud approved"],
            action_items=[{"task": "Prepare script", "assignee": "Bob", "deadline": "Friday"}],
            decisions=["Migrate backend to GCP"],
        )
        self.assertIn("# 📝 Q3 Strategy", md)
        self.assertIn("@Bob", md)

        csv_str = export_action_items_csv(
            [{"task": "Prepare script", "assignee": "Bob", "deadline": "Friday"}],
            meeting_title="Q3 Strategy"
        )
        self.assertIn("Prepare script", csv_str)
        self.assertIn("Bob", csv_str)


if __name__ == "__main__":
    unittest.main()
