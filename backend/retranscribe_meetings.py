"""Re-transcribe existing meeting audio with improved Whisper medium model.

This script finds all meetings that have audio files but may have been transcribed
with the old base model, and re-processes them with the medium model for 90%+ accuracy.
"""

import os
import sys
from pathlib import Path

# Add the app directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal
from app import models
from app.ai.pipeline import process_meeting_audio
from app.config import settings


def find_meetings_with_audio():
    """Find all meetings that have audio files in storage."""
    db = SessionLocal()
    try:
        storage_path = Path(settings.STORAGE_DIR)
        audio_files = list(storage_path.glob("*_bot_audio.webm")) + list(storage_path.glob("*_audio.webm"))
        
        meetings_with_audio = []
        for audio_file in audio_files:
            # Extract meeting ID from filename (e.g., "23_bot_audio.webm" -> 23)
            meeting_id = int(audio_file.name.split("_")[0])
            
            meeting = db.query(models.Meeting).filter(
                models.Meeting.id == meeting_id
            ).first()
            
            if meeting:
                meetings_with_audio.append({
                    'id': meeting_id,
                    'title': meeting.title,
                    'audio_path': str(audio_file),
                    'has_transcript': len(meeting.transcript_segments) > 0,
                    'status': meeting.status
                })
        
        return meetings_with_audio
    finally:
        db.close()


def retranscribe_meeting(meeting_id: int, audio_path: str):
    """Re-transcribe a single meeting with improved settings."""
    print(f"\n{'='*60}")
    print(f"Re-transcribing Meeting #{meeting_id}")
    print(f"Audio: {Path(audio_path).name}")
    print(f"Settings: model={settings.WHISPER_MODEL}, beam_size={settings.WHISPER_BEAM_SIZE}")
    print(f"{'='*60}\n")
    
    try:
        # This will re-run the full pipeline: transcription + summary + PDF
        process_meeting_audio(meeting_id, audio_path)
        print(f"✓ Meeting #{meeting_id} successfully re-transcribed!")
        return True
    except Exception as exc:
        print(f"✗ Failed to re-transcribe Meeting #{meeting_id}: {exc}")
        return False


def main():
    print("🔍 Scanning for meetings with audio files...\n")
    
    meetings = find_meetings_with_audio()
    
    if not meetings:
        print("No meetings with audio files found.")
        return
    
    print(f"Found {len(meetings)} meeting(s) with audio:\n")
    for i, meeting in enumerate(meetings, 1):
        status = "✓ Has transcript" if meeting['has_transcript'] else "✗ No transcript"
        print(f"{i}. Meeting #{meeting['id']}: {meeting['title']}")
        print(f"   Status: {meeting['status']} | {status}")
        print(f"   Audio: {Path(meeting['audio_path']).name}")
    
    print(f"\n{'='*60}")
    print("Re-transcription will use:")
    print(f"  • Model: {settings.WHISPER_MODEL} (90%+ accuracy)")
    print(f"  • Beam size: {settings.WHISPER_BEAM_SIZE} (improved accuracy)")
    print(f"  • VAD filter: {settings.WHISPER_VAD} (removes silence)")
    print(f"{'='*60}\n")
    
    choice = input("Re-transcribe ALL meetings? (y/n): ").strip().lower()
    
    if choice != 'y':
        print("\nOperation cancelled.")
        return
    
    print("\n🚀 Starting re-transcription...\n")
    
    success_count = 0
    fail_count = 0
    
    for meeting in meetings:
        if retranscribe_meeting(meeting['id'], meeting['audio_path']):
            success_count += 1
        else:
            fail_count += 1
    
    print(f"\n{'='*60}")
    print("Re-transcription complete!")
    print(f"  ✓ Successful: {success_count}")
    print(f"  ✗ Failed: {fail_count}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
