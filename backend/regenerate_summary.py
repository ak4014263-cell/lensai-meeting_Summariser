"""Script to regenerate summary for a specific meeting."""

import sys
import os

# Add workspace to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient
from Lensai_Bot.intelligence.summarizer import generate_executive_summary
from app.ai.pipeline import build_transcript_text

def regenerate_summary(meeting_title: str):
    """Find meeting by title and regenerate its summary."""
    
    # Connect to MongoDB
    client = MongoClient("mongodb://localhost:27017")
    db = client["ai_meeting_assistant"]
    meetings_collection = db["meetings"]
    
    # Find the meeting
    meeting = meetings_collection.find_one({"title": {"$regex": meeting_title, "$options": "i"}})
    
    if not meeting:
        print(f"❌ Meeting '{meeting_title}' not found")
        print("\nAvailable meetings:")
        for m in meetings_collection.find({}, {"_id": 1, "title": 1}).sort("_id", -1).limit(10):
            print(f"  ID {m['_id']}: {m['title']}")
        return
    
    meeting_id = meeting["_id"]
    print(f"✓ Found meeting: ID={meeting_id}, Title='{meeting['title']}'")
    
    # Check if transcript exists
    if not meeting.get("transcript") or not meeting["transcript"].get("segments"):
        print("❌ No transcript found for this meeting")
        return
    
    segments = meeting["transcript"]["segments"]
    print(f"✓ Transcript has {len(segments)} segments")
    
    # Regenerate summary
    print("\n🔄 Regenerating summary with updated configuration...")
    print("   (Using llama3 with 20-minute timeout)")
    
    try:
        # Build transcript text
        transcript_text = build_transcript_text(segments)
        
        # Generate summary using the Lensai summarizer
        summary_data = generate_executive_summary(
            transcript_text=transcript_text,
            segments=segments,
            meeting_title=meeting["title"]
        )
        
        # Update the meeting in database
        meetings_collection.update_one(
            {"_id": meeting_id},
            {
                "$set": {
                    "summary": summary_data["summary"],
                    "action_items": summary_data["action_items"],
                    "key_points": summary_data["key_points"],
                }
            }
        )
        
        print("\n✅ Summary regenerated successfully!")
        print("\n" + "="*60)
        print("SUMMARY:")
        print("="*60)
        print(summary_data["summary"])
        print("\n" + "="*60)
        print("KEY POINTS:")
        print("="*60)
        for point in summary_data["key_points"]:
            print(f"• {point}")
        print("\n" + "="*60)
        print("ACTION ITEMS:")
        print("="*60)
        for item in summary_data["action_items"]:
            print(f"• {item}")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Error generating summary: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        client.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python regenerate_summary.py <meeting_title>")
        print("Example: python regenerate_summary.py test6")
        sys.exit(1)
    
    meeting_title = sys.argv[1]
    regenerate_summary(meeting_title)
