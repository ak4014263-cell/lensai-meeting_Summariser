"""Script to regenerate summary for a specific meeting from SQLite database."""

import sys
import os
import sqlite3
import json

# Add workspace to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Lensai_Bot.intelligence.summarizer import generate_executive_summary
from app.ai.pipeline import build_transcript_text

def regenerate_summary(meeting_title: str):
    """Find meeting by title and regenerate its summary."""
    
    # Connect to SQLite
    db_path = os.path.join(os.path.dirname(__file__), "sql_app.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Find the meeting
    cursor.execute(
        "SELECT * FROM meetings WHERE title LIKE ? ORDER BY id DESC",
        (f"%{meeting_title}%",)
    )
    meeting = cursor.fetchone()
    
    if not meeting:
        print(f"❌ Meeting '{meeting_title}' not found")
        print("\nAvailable meetings:")
        cursor.execute("SELECT id, title, status FROM meetings ORDER BY id DESC LIMIT 20")
        for row in cursor.fetchall():
            print(f"  ID {row['id']}: {row['title']} ({row['status']})")
        conn.close()
        return
    
    meeting_id = meeting["id"]
    print(f"✓ Found meeting: ID={meeting_id}, Title='{meeting['title']}'")
    
    # Get transcript segments
    cursor.execute("SELECT * FROM transcript_segments WHERE meeting_id = ? ORDER BY start_time", (meeting_id,))
    segment_rows = cursor.fetchall()
    
    if not segment_rows:
        print("❌ No transcript segments found for this meeting")
        conn.close()
        return
    
    # Convert to expected format
    segments = []
    for row in segment_rows:
        segments.append({
            "start_ms": row["start_time"],
            "end_ms": row["end_time"],
            "text": row["text"],
            "speaker": row["speaker"] or "Speaker",
            "confidence": row["confidence"]
        })
    
    print(f"✓ Transcript has {len(segments)} segments")
    
    # Regenerate summary
    print("\n🔄 Regenerating summary with updated configuration...")
    print("   (Using llama3 with 20-minute timeout)")
    print("   This may take several minutes, please wait...\n")
    
    try:
        # Build transcript text
        transcript_text = build_transcript_text(segments)
        
        # Generate summary using the Lensai summarizer
        summary_data = generate_executive_summary(
            transcript_text=transcript_text,
            segments=segments,
            meeting_title=meeting["title"]
        )
        
        # Update summary in database
        cursor.execute(
            """UPDATE summaries 
               SET executive_summary = ?, key_points = ?, next_steps = ?
               WHERE meeting_id = ?""",
            (
                summary_data["summary"],
                "\n".join(summary_data["key_points"]),
                "\n".join(summary_data["action_items"]),
                meeting_id
            )
        )
        
        if cursor.rowcount == 0:
            # Insert if not exists
            cursor.execute(
                """INSERT INTO summaries (meeting_id, executive_summary, key_points, next_steps)
                   VALUES (?, ?, ?, ?)""",
                (
                    meeting_id,
                    summary_data["summary"],
                    "\n".join(summary_data["key_points"]),
                    "\n".join(summary_data["action_items"])
                )
            )
        
        # Update action items
        cursor.execute("DELETE FROM action_items WHERE meeting_id = ?", (meeting_id,))
        for item in summary_data["action_items"]:
            cursor.execute(
                "INSERT INTO action_items (meeting_id, text) VALUES (?, ?)",
                (meeting_id, item)
            )
        
        conn.commit()
        
        print("\n✅ Summary regenerated successfully!")
        print("\n" + "="*80)
        print("SUMMARY:")
        print("="*80)
        print(summary_data["summary"])
        print("\n" + "="*80)
        print("KEY POINTS:")
        print("="*80)
        for i, point in enumerate(summary_data["key_points"], 1):
            print(f"{i}. {point}")
        print("\n" + "="*80)
        print("ACTION ITEMS:")
        print("="*80)
        for i, item in enumerate(summary_data["action_items"], 1):
            print(f"{i}. {item}")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ Error generating summary: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python regenerate_summary_sqlite.py <meeting_title>")
        print("Example: python regenerate_summary_sqlite.py test6")
        sys.exit(1)
    
    meeting_title = sys.argv[1]
    regenerate_summary(meeting_title)
