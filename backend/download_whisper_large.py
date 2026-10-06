"""Download Whisper large-v3 model for maximum transcription accuracy (95-98%)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

print("🚀 Downloading Whisper large-v3 model...")
print("⚠️  This is a 3 GB download - it will take several minutes")
print("=" * 60)

try:
    from faster_whisper import WhisperModel
    
    print("\nStarting download...")
    model = WhisperModel(
        "large-v3",
        device="cpu",
        compute_type="int8",
    )
    print("\n✅ Whisper large-v3 model downloaded successfully!")
    print("📊 This model provides 95-98% transcription accuracy")
    print("\nYou can now restart your backend server.")
    
except Exception as e:
    print(f"\n❌ Error downloading model: {e}")
    sys.exit(1)
