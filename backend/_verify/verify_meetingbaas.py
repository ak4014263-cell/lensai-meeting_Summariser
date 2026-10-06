"""Prove the Meeting BaaS -> pipeline path using a REAL completed bot.

Uses the existing completed bot on the account to exercise every step that a
live hosted-bot job depends on, minus the create call (which would dispatch a
real bot and cost tokens):

    get_bot -> download_transcript -> speaker timeline
      -> create a Meeting row -> process_meeting_audio (Whisper skipped;
         the hosted transcript is the caption timeline) -> Ollama summary
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai import meetingbaas  # noqa: E402
from app.ai.pipeline import build_transcript_text  # noqa: E402


def fail(msg: str) -> None:
    print(f"\n[FAIL] {msg}")
    sys.exit(1)


def main() -> None:
    print("1. API key / list bots")
    ok, msg = meetingbaas.check_available()
    print("  ", msg)
    if not ok:
        fail(msg)

    import requests

    listed = requests.get(
        meetingbaas._url("/v2/bots?limit=10"), headers=meetingbaas._headers(), timeout=30
    ).json()["data"]
    completed = [b for b in listed if (b.get("status") or "").lower() in meetingbaas.TERMINAL_OK]
    if not completed:
        fail("No completed bot on the account to test against.")
    bot_id = completed[0]["bot_id"]
    print(f"   using completed bot {bot_id}")

    print("2. get_bot + download transcript")
    data = meetingbaas.get_bot(bot_id)
    timeline = meetingbaas.download_transcript(data)
    names = meetingbaas.participant_names(data)
    print(f"   status={data.get('status')} segments={len(timeline)} participants={list(names)}")
    if not timeline:
        fail("No transcript segments parsed from the hosted bot.")
    labelled = sum(1 for s in timeline if s.get("speaker"))
    print(f"   segments with a speaker name: {labelled}/{len(timeline)}")
    for seg in timeline[:4]:
        print(f"    [{seg['startMs']/1000:6.1f}s] {seg['speaker']}: {seg['text'][:70]}")

    print("3. Run the shared pipeline (create meeting -> summarise)")
    from app.database import SessionLocal
    from app import models
    from app.ai.pipeline import process_meeting_audio

    db = SessionLocal()
    try:
        user = db.query(models.User).first()
        if not user:
            user = models.User(email="verify@test.local", hashed_password="x")
            db.add(user)
            db.commit()
            db.refresh(user)
        meeting = models.Meeting(
            title="[verify] MeetingBaas import",
            owner_id=user.id,
            source="meetingbaas",
            platform="google_meet",
            external_bot_id=bot_id,
            status="processing_audio",
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        mid = meeting.id

        ok = process_meeting_audio(mid, file_path=None, captions=timeline, participant_names=names, db=db)
        db.expire_all()
        meeting = db.query(models.Meeting).filter(models.Meeting.id == mid).first()
        segs = db.query(models.TranscriptSegment).filter(models.TranscriptSegment.meeting_id == mid).count()
        summary = meeting.summary
        print(f"   pipeline ok={ok} status={meeting.status} stored_segments={segs}")
        if summary:
            print(f"   summary: {(summary.executive_summary or '')[:160]}")
            print(f"   key_points={len(summary.key_points.splitlines()) if summary.key_points else 0} "
                  f"decisions={len(meeting.decisions)} actions={len(meeting.action_items)}")
        if meeting.status != "completed":
            fail(f"pipeline did not complete (status={meeting.status})")
        if segs == 0:
            fail("no transcript segments persisted")
        if not (summary and summary.executive_summary):
            fail("no summary produced")

        # Clean up the verification meeting.
        db.delete(meeting)
        db.commit()
    finally:
        db.close()

    print("\nALL MEETING BAAS CHECKS PASSED")


if __name__ == "__main__":
    main()
