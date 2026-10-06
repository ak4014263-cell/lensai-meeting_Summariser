# Speaker Recognition Fix for Two Users

## Problem
When two users join a Google Meet meeting, their names are not properly recognized in the transcript and summary.

## Root Causes Identified

1. **Bot Account Name**: The bot is signed into a Google account named "reframe" which was appearing in captions
2. **Generic Speaker Labels**: Google Meet sometimes shows "Speaker 1", "Speaker 2" instead of actual names
3. **Speaker Mapping**: Need better fuzzy matching between caption labels and participant names

## Fixes Applied

### 1. Bot Name Filtering (`backend/app/ai/bot.py`)
✅ Added comprehensive bot name filtering including:
- "reframe" (legacy bot account)
- "AI Notetaker"
- "LensAI Notetaker"
- "you"
- All bot name variations

### 2. Enhanced Speaker Identifier (`backend/app/ai/speaker_identifier.py`)
✅ Improved speaker name recognition:
- **Fuzzy matching**: "Ajay" matches "Ajay Kumar"
- **Smart numbered mapping**: "Speaker 1" → first available participant
- **Auto-assignment**: Unrecognized labels automatically map to unassigned participants
- **Generic label detection**: Better detection of "Speaker", "You", "Guest", etc.

### 3. Configuration (`backend/.env`)
✅ Added explicit bot configuration:
```
BOT_DISPLAY_NAME=LensAI Notetaker
ENABLE_SPEAKER_MAPPING=true
```

## How It Works Now

### Two-User Meeting Flow:
1. **Bot Joins**: LensAI bot enters as "LensAI Notetaker" or "reframe" (filtered out)
2. **Participant Detection**: Bot extracts participant list from Google Meet DOM
   - Example: ["Ajay Kumar", "Bishnu Prasad"]
3. **Caption Capture**: Google Meet captions show speaker labels
   - Ideal: "Ajay Kumar: Hello"
   - Generic: "Speaker 1: Hello"
4. **Speaker Mapping**:
   - "Ajay Kumar" → Recognized as real name → Used as-is
   - "Ajay" → Fuzzy matched to "Ajay Kumar"
   - "Speaker 1" → Mapped to first participant "Ajay Kumar"
   - "Speaker 2" → Mapped to second participant "Bishnu Prasad"
   - "reframe" → Filtered out (bot's own name)

## Testing Checklist

### Before Meeting:
- [ ] Backend server running (localhost:8000)
- [ ] Frontend running (localhost:3001)
- [ ] Check `.env` has `ENABLE_SPEAKER_MAPPING=true`
- [ ] Check `.env` has `BOT_DISPLAY_NAME=LensAI Notetaker`

### During Meeting:
- [ ] Bot successfully joins Google Meet
- [ ] Captions are enabled (bot tries to enable automatically)
- [ ] Two users join and speak
- [ ] Live transcript shows correct names (not "Speaker 1", "Speaker 2")

### After Meeting:
- [ ] AI Summary generated
- [ ] Check transcript segments have correct speaker names
- [ ] Check PDF export shows correct speaker names
- [ ] Verify "reframe" does not appear anywhere

## Common Issues & Solutions

### Issue: Still seeing "Speaker 1", "Speaker 2"
**Cause**: Google Meet captions not showing real names
**Solution**:
1. Enable captions manually in Google Meet (CC button)
2. Ensure participants have their Google account names set
3. Wait a few seconds for Google to recognize speakers

### Issue: Bot name "reframe" still appears
**Cause**: Bot filtering not working
**Solution**:
1. Check backend logs for speaker mapping
2. Verify participant list is being extracted
3. Restart backend server to apply changes

### Issue: Names are mixed up
**Cause**: Caption timing mismatch
**Solution**:
1. This is handled automatically by temporal correlation
2. System maps speakers based on who spoke when
3. First speaker gets first participant name, etc.

## Advanced Configuration

### Force Specific Name Mapping
Edit `backend/app/ai/speaker_identifier.py` to add custom mappings:

```python
# In __init__ method, add:
self.custom_mappings = {
    "Speaker 1": "Ajay Kumar",
    "Speaker 2": "Bishnu Prasad",
}
```

### Increase Speaker Detection Accuracy
In `backend/.env`:
```
# Enable audio-based speaker diarization (more accurate but slower)
ENABLE_SPEAKER_DIARIZATION=true
NUM_SPEAKERS=2  # Set to expected number of speakers
```

## Verification Commands

### Check speaker mappings in database:
```python
from backend.app.database import SessionLocal
from backend.app.models import Meeting

db = SessionLocal()
meeting = db.query(Meeting).order_by(Meeting.id.desc()).first()
print("Participants:", meeting.participant_names)
```

### Check transcript segments:
```python
import json
if meeting.transcript:
    segments = json.loads(meeting.transcript)
    for seg in segments[:5]:  # First 5 segments
        print(f"{seg.get('speaker')}: {seg.get('text')[:50]}")
```

## Next Steps

If issues persist:
1. Share backend logs during meeting
2. Share example transcript output
3. Check Google Meet caption settings
4. Consider changing bot Google account display name

## Success Criteria

✅ Two users join meeting
✅ Each user's name appears correctly in transcript
✅ AI summary shows correct speaker names
✅ PDF export has correct attendee names
✅ No "reframe", "Speaker 1", or "Speaker 2" labels in final output
