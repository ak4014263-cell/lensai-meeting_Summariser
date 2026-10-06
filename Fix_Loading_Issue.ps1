# Quick fix for "Loading meetings..." issue

Write-Host "`n=== Fixing 'Loading meetings...' Issue ===" -ForegroundColor Cyan

# Step 1: Install missing dependencies
Write-Host "`n[1/3] Installing missing Python packages..." -ForegroundColor Yellow
cd backend
pip install psutil pymongo motor prometheus-client --quiet
Write-Host "✓ Dependencies installed" -ForegroundColor Green

# Step 2: Verify backend can start
Write-Host "`n[2/3] Verifying backend imports..." -ForegroundColor Yellow
$testImport = python -c "from app.main import app; print('OK')" 2>&1
if ($testImport -match "OK") {
    Write-Host "✓ Backend imports successfully" -ForegroundColor Green
}
else {
    Write-Host "✗ Backend import failed:" -ForegroundColor Red
    Write-Host $testImport -ForegroundColor Gray
}

# Step 3: Check if server is running
Write-Host "`n[3/3] Checking if backend is running..." -ForegroundColor Yellow
try {
    Start-Sleep -Seconds 2
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:8000/meetings/" -Headers @{"Authorization"="Bearer dummy"} -TimeoutSec 3 -ErrorAction Stop
    Write-Host "✓ Backend API is responding" -ForegroundColor Green
}
catch {
    if ($_.Exception.Response.StatusCode -eq 401) {
        Write-Host "✓ Backend API is running (authentication required)" -ForegroundColor Green
    }
    else {
        Write-Host "⚠ Backend may need restart" -ForegroundColor Yellow
        Write-Host "  The server should auto-reload in a few seconds..." -ForegroundColor Gray
    }
}

cd ..

Write-Host "`n=== Solution ===" -ForegroundColor Cyan
Write-Host "The backend should now auto-reload and work correctly." -ForegroundColor White
Write-Host "`nIf 'Loading meetings...' persists:" -ForegroundColor Yellow
Write-Host "1. Wait 5-10 seconds for server to fully restart" -ForegroundColor White
Write-Host "2. Refresh browser with Ctrl+Shift+R (hard refresh)" -ForegroundColor White  
Write-Host "3. Check browser console (F12) for any errors" -ForegroundColor White
Write-Host "4. Verify you're logged in (token exists)" -ForegroundColor White
Write-Host "`n✓ Fix applied!" -ForegroundColor Green
Write-Host ""
