# Launch Queued Bot Script
# This script manually launches the bot for a meeting that's in bot_queued status

param(
    [Parameter(Mandatory=$false)]
    [int]$MeetingId
)

Write-Host "=== Launch Queued Bot ===" -ForegroundColor Cyan
Write-Host ""

if (-not $MeetingId) {
    Write-Host "Fetching recent queued meetings..." -ForegroundColor Yellow
    Write-Host ""
    
    # Show recent bot_queued meetings
    $query = @"
SELECT id, title, status, meet_url, date 
FROM meetings 
WHERE status = 'bot_queued' 
ORDER BY date DESC 
LIMIT 10;
"@
    
    $dbPath = "backend\meetings.db"
    if (Test-Path $dbPath) {
        $sqlite3 = Get-Command sqlite3 -ErrorAction SilentlyContinue
        if ($sqlite3) {
            Write-Host "Queued meetings:" -ForegroundColor Green
            sqlite3 $dbPath $query
            Write-Host ""
        }
    }
    
    $MeetingId = Read-Host "Enter Meeting ID to launch bot"
}

Write-Host ""
Write-Host "Launching bot for meeting ID: $MeetingId" -ForegroundColor Yellow

# Use Python to launch the bot
$pythonScript = @"
from app.database import SessionLocal
from app.models import Meeting, MeetingStatus
from app.ai.bot_manager import bot_manager

db = SessionLocal()
try:
    meeting = db.query(Meeting).filter(Meeting.id == $MeetingId).first()
    if not meeting:
        print(f'❌ Meeting {$MeetingId} not found')
        exit(1)
    
    if not meeting.meet_url:
        print(f'❌ Meeting {$MeetingId} has no meeting URL')
        exit(1)
    
    print(f'Meeting: {meeting.title}')
    print(f'Status: {meeting.status}')
    print(f'URL: {meeting.meet_url}')
    print('')
    
    if meeting.status not in [MeetingStatus.BOT_QUEUED, MeetingStatus.CREATED, MeetingStatus.BOT_FAILED]:
        print(f'⚠️  Meeting is already in status: {meeting.status}')
        print('   Bot may already be running or completed')
    
    print('🚀 Launching bot...')
    started, msg = bot_manager.start(meeting.id, meeting.meet_url)
    
    if started:
        print(f'✅ Bot launched successfully!')
        print(f'   Watch progress at: http://127.0.0.1:3000/dashboard/meetings/{meeting.id}')
    else:
        print(f'❌ Failed to launch bot: {msg}')
        exit(1)
        
finally:
    db.close()
"@

Set-Location "backend"
Write-Host ""
python -c $pythonScript
Write-Host ""

Write-Host "=== Done ===" -ForegroundColor Cyan
