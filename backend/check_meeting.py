import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "sql_app.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Get test6 meeting details
cursor.execute("SELECT * FROM meetings WHERE title LIKE '%test6%'")
meeting = cursor.fetchone()

if meeting:
    print("Meeting details:")
    for key in meeting.keys():
        print(f"  {key}: {meeting[key]}")
    
    print("\nChecking audio file:")
    audio_path = meeting["audio_file_path"]
    if audio_path and os.path.exists(audio_path):
        size = os.path.getsize(audio_path)
        print(f"  ✓ Audio file exists: {audio_path}")
        print(f"  Size: {size / 1024 / 1024:.2f} MB")
    elif audio_path:
        print(f"  ❌ Audio file not found: {audio_path}")
    else:
        print("  ❌ No audio file path recorded")

conn.close()
