"""List all meetings in the database."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["ai_meeting_assistant"]
meetings = db["meetings"]

print("\nAll meetings in database:")
print("=" * 80)

for meeting in meetings.find({}, {"_id": 1, "title": 1, "status": 1, "created_at": 1}).sort("_id", -1):
    print(f"ID: {meeting['_id']:3d} | Title: {meeting.get('title', 'N/A'):40s} | Status: {meeting.get('status', 'N/A')}")

print("=" * 80)
print(f"Total: {meetings.count_documents({})} meetings")

client.close()
