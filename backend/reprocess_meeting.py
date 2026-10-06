"""Reprocess a meeting's audio file to regenerate transcript and summary."""

import sys
import os

# Add workspace to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
from app.ai.pipeline import process_meeting_audio
from app.database import SessionLocal

def reprocess_meeting(meeting_id: int):
    """Reprocess a meeting's audio file."""
    
    # Connect to SQLite
    db_path = os.path.join(os.path.dirname(__file__), "sql_app.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get meeting
    cursor.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,))
    meeting = cursor.fetchone()
    
    if not meeting:
        print(f"❌ Meeting ID {meeting_id} not found")
        conn.close()
        return
    
    print(f"✓ Found meeting: ID={meeting['id']}, Title='{meeting['title']}'")
    
    # Check audio file
    audio_path = meeting["audio_file_path"]
    if not audio_path or not os.path.exists(audio_path):
        print(f"❌ Audio file not found: {audio_path}")
        conn.close()
        return
    
    size = os.path.getsize(audio_path)
    print(f"✓ Audio file exists: {size / 1024 / 1024:.2f} MB")
    
    # Close SQLite connection
    conn.close()
    
    # Reprocess with the pipeline
    print("\n🔄 Reprocessing meeting audio...")
    print("   This will:")
    print("   1. Transcribe audio with Whisper large-v3-turbo")
    print("   2. Generate AI summary with llama3")
    print("   3. Extract action items and key points")
    print("\n   This may take 5-15 minutes depending on audio length.")
    print("   Please wait...\n")
    
    try:
        # Use the existing pipeline function
        process_meeting_audio(meeting_id, audio_path)
        
        print("\n✅ Meeting reprocessed successfully!")
        print(f"\nYou can now view the updated summary in the dashboard.")
        
    except Exception as e:
        print(f"\n❌ Error reprocessing meeting: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python reprocess_meeting.py <meeting_id>")
        print("Example: python reprocess_meeting.py 50")
        sys.exit(1)
    
    try:
        meeting_id = int(sys.argv[1])
        reprocess_meeting(meeting_id)
    except ValueError:
        print("Error: Meeting ID must be a number")
        sys.exit(1)
