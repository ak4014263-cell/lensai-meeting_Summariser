# Quick connection test for AI Meeting Assistant

Write-Host "`n=== AI Meeting Assistant Connection Test ===" -ForegroundColor Cyan

# Test 1: Backend API
Write-Host "`n[1/5] Testing Backend API..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:8000/docs" -Method GET -TimeoutSec 5
    Write-Host "✓ Backend API is running on http://127.0.0.1:8000" -ForegroundColor Green
}
catch {
    Write-Host "✗ Backend API is NOT responding on port 8000" -ForegroundColor Red
    Write-Host "  Start backend first!" -ForegroundColor Yellow
}

# Test 2: Frontend
Write-Host "`n[2/5] Testing Frontend..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:3000" -Method GET -TimeoutSec 5 -UseBasicParsing
    Write-Host "✓ Frontend is running on http://localhost:3000" -ForegroundColor Green
}
catch {
    Write-Host "✗ Frontend is NOT responding on port 3000" -ForegroundColor Red
    Write-Host "  Start frontend!" -ForegroundColor Yellow
}

# Test 3: PostgreSQL
Write-Host "`n[3/5] Testing PostgreSQL..." -ForegroundColor Yellow
$pgRunning = Get-Process postgres -ErrorAction SilentlyContinue
if ($pgRunning) {
    Write-Host "✓ PostgreSQL is running" -ForegroundColor Green
}
else {
    Write-Host "✗ PostgreSQL is NOT running" -ForegroundColor Red
}

# Test 4: Ollama
Write-Host "`n[4/5] Testing Ollama..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method GET -TimeoutSec 5
    Write-Host "✓ Ollama is running" -ForegroundColor Green
    
    $models = $response.models | Where-Object { $_.name -match "llama3.2" }
    if ($models) {
        Write-Host "✓ llama3.2 model found" -ForegroundColor Green
    }
    else {
        Write-Host "⚠ llama3.2 model not found. Run: ollama pull llama3.2" -ForegroundColor Yellow
    }
}
catch {
    Write-Host "✗ Ollama is NOT running" -ForegroundColor Red
    Write-Host "  Start with: ollama serve" -ForegroundColor Yellow
}

# Test 5: API Health Check
Write-Host "`n[5/5] Testing API Health..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method GET -TimeoutSec 5 -ErrorAction Stop
    Write-Host "✓ API Health: $($response.status)" -ForegroundColor Green
    
    if ($response.services) {
        foreach ($service in $response.services.PSObject.Properties) {
            $status = $service.Value
            $color = if ($status -eq "healthy") { "Green" } else { "Yellow" }
            Write-Host "  - $($service.Name): $status" -ForegroundColor $color
        }
    }
}
catch {
    Write-Host "✗ API Health check failed" -ForegroundColor Red
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
Write-Host "If any tests failed, start the required services." -ForegroundColor White
Write-Host "`nQuick Fix for 'Loading meetings...' issue:" -ForegroundColor Cyan
Write-Host "1. Clear browser cache: Ctrl+Shift+Delete" -ForegroundColor White
Write-Host "2. Hard reload page: Ctrl+Shift+R" -ForegroundColor White
Write-Host "3. Check browser console (F12) for errors" -ForegroundColor White
Write-Host "4. Restart frontend: npm run dev" -ForegroundColor White
Write-Host "`n"
