"""Reprocess an existing Meeting BaaS bot recording through the new pipeline.

Downloads the recording to local storage (named after the meeting), runs Whisper
on it, and generates the Ollama summary. Proves the end-to-end path without
needing a live meeting.

Usage:  python _verify\\reprocess.py <meeting_id>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models  # noqa: E402
from app.ai import meetingbaas  # noqa: E402
from app.ai.meetingbaas_runner import _finish  # noqa: E402
from app.database import SessionLocal  # noqa: E402

meeting_id = int(sys.argv[1]) if len(sys.argv) > 1 else 10

db = SessionLocal()
try:
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        print(f"meeting {meeting_id} not found")
        sys.exit(1)
    if not meeting.external_bot_id:
        print("meeting has no Meeting BaaS bot id")
        sys.exit(1)

    print(f"Fetching bot {meeting.external_bot_id} ...")
    data = meetingbaas.get_bot(meeting.external_bot_id)
    print("  status:", data.get("status"))
    print("  duration_seconds:", data.get("duration_seconds"))
    print("  audio artifact:", bool(data.get("audio")))
    print("  transcription artifact:", bool(data.get("transcription")))

    # Clear previous empty results so we can see the new outcome clearly.
    db.query(models.Summary).filter(models.Summary.meeting_id == meeting_id).delete()
    db.query(models.TranscriptSegment).filter(
        models.TranscriptSegment.meeting_id == meeting_id
    ).delete()
    db.commit()

    print("\nRunning the new _finish (download recording -> Whisper -> Ollama)...")
    _finish(db, meeting_id, data)

    db.expire_all()
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    segs = (
        db.query(models.TranscriptSegment)
        .filter(models.TranscriptSegment.meeting_id == meeting_id)
        .count()
    )
    print("\n=== RESULT ===")
    print("status           :", meeting.status)
    print("audio_file_path  :", meeting.audio_file_path)
    print("transcript segs  :", segs)
    if meeting.summary:
        print("summary          :", (meeting.summary.executive_summary or "")[:400])
        print("key_points       :", len((meeting.summary.key_points or "").splitlines()))
    print("decisions        :", len(meeting.decisions))
    print("action_items     :", len(meeting.action_items))
finally:
    db.close()
