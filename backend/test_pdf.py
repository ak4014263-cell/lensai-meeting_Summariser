from app.database import SessionLocal
from app.models import Meeting, TranscriptSegment
from app.meetings.router import export_pdf
from fastapi import Response

db = SessionLocal()
meeting = db.query(Meeting).filter(Meeting.id == 24).first()
print('Testing PDF export for Meeting 24 (title:', meeting.title, 'status:', meeting.status, ')')

# Check transcript segments
segs = db.query(TranscriptSegment).filter(TranscriptSegment.meeting_id == 24).all()
print(f'Transcript segments found: {len(segs)}')

# Test speaker metrics directly
seg_dicts = [{'speaker': s.speaker, 'text': s.text, 'start_time': s.start_time, 'end_time': s.end_time} for s in segs]
from Lensai_Bot.analytics.speaker_metrics import calculate_speaker_metrics
from Lensai_Bot.analytics.sentiment_analyzer import analyze_sentiment
from Lensai_Bot.intelligence.action_extractor import extract_soundbites
from Lensai_Bot.export.pdf_export import export_meeting_pdf

speaker_analytics = calculate_speaker_metrics(seg_dicts)
print('Speaker metrics calculated successfully:', speaker_analytics.dominant_speaker)

sentiment = analyze_sentiment(seg_dicts)
print('Sentiment analyzed successfully:', sentiment.overall_sentiment)

soundbites = extract_soundbites(seg_dicts)
print('Soundbites extracted successfully:', len(soundbites))

pdf_bytes = export_meeting_pdf(
    title=meeting.title,
    date_str='2026-09-15',
    duration_str='3m',
    summary=meeting.summary or 'No summary',
    decisions=['Decision 1'] if meeting.decisions else [],
    actions=['Action 1'] if meeting.action_items else [],
    participants=['ak4014263@gmail.com'],
    transcript_segments=seg_dicts,
    speaker_analytics=speaker_analytics,
    sentiment=sentiment,
    soundbites=soundbites,
)
print('PDF generated successfully! Byte length:', len(pdf_bytes))
