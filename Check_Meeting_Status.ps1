# Check Meeting Status Diagnostic
# This script checks what status is actually stored in the database

Write-Host "=== Meeting Status Diagnostic ===" -ForegroundColor Cyan
Write-Host ""

# Check if backend is running
Write-Host "1. Checking if backend is accessible..." -ForegroundColor Yellow
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method GET -TimeoutSec 5
    Write-Host "   ✓ Backend is running" -ForegroundColor Green
} catch {
    Write-Host "   ✗ Backend is not accessible on port 8000" -ForegroundColor Red
    Write-Host "   Please start the backend first: cd backend; uvicorn app.main:app --reload" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "2. Fetching recent meetings..." -ForegroundColor Yellow

# Try to get meetings from API
# Note: This requires authentication. We'll show the command to run manually
Write-Host ""
Write-Host "   To check your meetings, run this command in PowerShell:" -ForegroundColor Cyan
Write-Host "   " -NoNewline
Write-Host 'Invoke-RestMethod -Uri "http://127.0.0.1:8000/meetings" -Method GET -Headers @{"Authorization"="Bearer YOUR_TOKEN"}' -ForegroundColor White
Write-Host ""
Write-Host "   Or check directly in the database:" -ForegroundColor Cyan
Write-Host ""

# Check SQLite database directly
$dbPath = "backend\meetings.db"
if (Test-Path $dbPath) {
    Write-Host "   Database found at: $dbPath" -ForegroundColor Green
    Write-Host ""
    Write-Host "   Recent meetings in database:" -ForegroundColor Yellow
    
    # Use sqlite3 command if available
    $sqlite3 = Get-Command sqlite3 -ErrorAction SilentlyContinue
    if ($sqlite3) {
        Write-Host ""
        sqlite3 $dbPath "SELECT id, title, status, source, meet_url, date FROM meetings ORDER BY date DESC LIMIT 10;"
    } else {
        Write-Host "   Install sqlite3 to query database directly, or use:" -ForegroundColor Cyan
        Write-Host '   sqlite3 backend\meetings.db "SELECT id, title, status, source, date FROM meetings ORDER BY date DESC LIMIT 10;"'
    }
} else {
    Write-Host "   Database not found at: $dbPath" -ForegroundColor Red
    Write-Host "   Check if backend has created the database yet." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "3. Expected status values:" -ForegroundColor Yellow
Write-Host "   - created        : Draft meeting, no bot scheduled" -ForegroundColor White
Write-Host "   - bot_queued     : Bot scheduled, waiting for meeting time" -ForegroundColor Cyan
Write-Host "   - bot_launching  : Bot is starting up" -ForegroundColor Cyan
Write-Host "   - bot_joining    : Bot is joining the meeting" -ForegroundColor Cyan
Write-Host "   - bot_in_call    : Bot is in the call recording" -ForegroundColor Green
Write-Host "   - completed      : Meeting processed, summary ready" -ForegroundColor Green
Write-Host ""

Write-Host "=== Diagnostic Complete ===" -ForegroundColor Cyan
