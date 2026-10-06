"""
Install pyannote.audio for speaker diarization (voice-based speaker identification).

This will enable automatic speaker detection and naming even when Google Meet
captions don't provide names.
"""

import subprocess
import sys

print("Installing pyannote.audio for speaker diarization...")
print("This will enable automatic speaker identification from voice patterns.\n")

packages = [
    "pyannote.audio==3.1.1",
    "pyannote.core==5.0.0",
]

try:
    for package in packages:
        print(f"Installing {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    
    print("\n✅ Speaker diarization dependencies installed!")
    print("\n📝 Next steps:")
    print("1. Get a HuggingFace token from: https://huggingface.co/settings/tokens")
    print("2. Accept terms at: https://huggingface.co/pyannote/speaker-diarization-3.1")
    print("3. Add to .env file: HUGGINGFACE_TOKEN=your_token_here")
    print("\nOnce configured, speakers will be automatically identified as Speaker 1, Speaker 2, etc.")
    print("These will be mapped to actual participant names from Google Meet.")
    
except subprocess.CalledProcessError as e:
    print(f"\n❌ Installation failed: {e}")
    print("You may need to install system dependencies first.")
    sys.exit(1)
