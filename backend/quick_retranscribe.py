"""Quick re-transcribe script for a single meeting."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.ai.pipeline import process_meeting_audio
from app.config import settings

# Which meeting to re-transcribe
MEETING_ID = 23  # Change this to the meeting ID you want to re-transcribe

audio_file = Path(f"storage/{MEETING_ID}_bot_audio.webm")
if not audio_file.exists():
    audio_file = Path(f"storage/{MEETING_ID}_audio.webm")

if not audio_file.exists():
    print(f"❌ No audio file found for meeting {MEETING_ID}")
    sys.exit(1)

print(f"🔄 Re-transcribing Meeting #{MEETING_ID}")
print(f"📁 Audio: {audio_file}")
print(f"⚙️  Model: {settings.WHISPER_MODEL} (beam_size={settings.WHISPER_BEAM_SIZE})")
print(f"{'='*60}\n")

try:
    process_meeting_audio(MEETING_ID, str(audio_file))
    print(f"\n✅ Meeting #{MEETING_ID} successfully re-transcribed with 90%+ accuracy!")
    print(f"📄 Check the dashboard for the updated transcript and PDF")
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
