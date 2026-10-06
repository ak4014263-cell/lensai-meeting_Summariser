# ═══════════════════════════════════════════════════════════════
# AI MEETING ASSISTANT - ENTERPRISE VALIDATION SCRIPT
# Comprehensive system validation for production deployment
# ═══════════════════════════════════════════════════════════════

param(
    [switch]$Verbose = $false,
    [switch]$FullTest = $false
)

$ErrorActionPreference = "Continue"
$ValidationResults = @()

function Add-ValidationResult {
    param(
        [string]$Category,
        [string]$Test,
        [bool]$Passed,
        [string]$Message = "",
        [string]$Severity = "Error"
    )
    
    $Global:ValidationResults += [PSCustomObject]@{
        Category = $Category
        Test = $Test
        Passed = $Passed
        Message = $Message
        Severity = $Severity
    }
    
    $icon = if ($Passed) { "✓" } else { "✗" }
    $color = if ($Passed) { "Green" } else { if ($Severity -eq "Warning") { "Yellow" } else { "Red" } }
    
    Write-Host "  $icon $Test" -ForegroundColor $color -NoNewline
    if ($Message -and ($Verbose -or -not $Passed)) {
        Write-Host " - $Message" -ForegroundColor Gray
    } else {
        Write-Host ""
    }
}

function Test-ServicePort {
    param([int]$Port, [string]$Service)
    try {
        $connection = Test-NetConnection -ComputerName localhost -Port $Port -WarningAction SilentlyContinue
        return $connection.TcpTestSucceeded
    } catch {
        return $false
    }
}

Write-Host "`n╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     AI MEETING ASSISTANT - ENTERPRISE VALIDATION          ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

# ═══════════════════════════════════════════════════════════════
Write-Host "CATEGORY 1: System Requirements" -ForegroundColor Yellow

# Python
try {
    $pythonVersion = python --version 2>&1
    $passed = $pythonVersion -match "Python 3\.(9|1[0-9])"
    Add-ValidationResult "System" "Python 3.9+" $passed $pythonVersion
} catch {
    Add-ValidationResult "System" "Python 3.9+" $false "Not found"
}

# Node.js
try {
    $nodeVersion = node --version
    $versionNum = [int]($nodeVersion -replace 'v(\d+)\..*', '$1')
    $passed = $versionNum -ge 18
    Add-ValidationResult "System" "Node.js 18+" $passed $nodeVersion
} catch {
    Add-ValidationResult "System" "Node.js 18+" $false "Not found"
}

# PostgreSQL
try {
    $pgVersion = psql --version
    $passed = $pgVersion -match "PostgreSQL"
    Add-ValidationResult "System" "PostgreSQL" $passed $pgVersion
} catch {
    Add-ValidationResult "System" "PostgreSQL" $false "Not found"
}

# Ollama
try {
    $ollamaVersion = ollama --version 2>&1
    $passed = $ollamaVersion -match "ollama"
    Add-ValidationResult "System" "Ollama" $passed $ollamaVersion
} catch {
    Add-ValidationResult "System" "Ollama" $false "Not found"
}

# Disk Space
$drive = Get-PSDrive C
$freeGB = [math]::Round($drive.Free / 1GB, 2)
$passed = $freeGB -gt 50
Add-ValidationResult "System" "Disk Space (50GB+)" $passed "${freeGB}GB free" $(if ($passed) { "Info" } else { "Warning" })

# RAM
$ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 2)
$passed = $ram -ge 16
Add-ValidationResult "System" "RAM (16GB+)" $passed "${ram}GB" $(if ($passed) { "Info" } else { "Warning" })

# GPU (optional)
try {
    $gpu = Get-WmiObject Win32_VideoController | Where-Object { $_.Name -match "NVIDIA" }
    if ($gpu) {
        Add-ValidationResult "System" "NVIDIA GPU" $true $gpu.Name "Info"
    } else {
        Add-ValidationResult "System" "NVIDIA GPU" $false "Not found (optional)" "Warning"
    }
} catch {
    Add-ValidationResult "System" "NVIDIA GPU" $false "Not detected (optional)" "Warning"
}

# ═══════════════════════════════════════════════════════════════
Write-Host "`nCATEGORY 2: Service Status" -ForegroundColor Yellow

# Ollama Service
$ollamaRunning = Get-Process ollama -ErrorAction SilentlyContinue
if ($ollamaRunning) {
    Add-ValidationResult "Services" "Ollama Process" $true "PID: $($ollamaRunning.Id)"
} else {
    Add-ValidationResult "Services" "Ollama Process" $false "Not running"
}

# Ollama Port
$ollamaPort = Test-ServicePort -Port 11434 -Service "Ollama"
Add-ValidationResult "Services" "Ollama Port (11434)" $ollamaPort

# PostgreSQL Port
$pgPort = Test-ServicePort -Port 5432 -Service "PostgreSQL"
Add-ValidationResult "Services" "PostgreSQL Port (5432)" $pgPort

# MongoDB Port (optional)
$mongoPort = Test-ServicePort -Port 27017 -Service "MongoDB"
Add-ValidationResult "Services" "MongoDB Port (27017)" $mongoPort "Optional for chat" $(if ($mongoPort) { "Info" } else { "Warning" })

# Redis Port (optional)
$redisPort = Test-ServicePort -Port 6379 -Service "Redis"
Add-ValidationResult "Services" "Redis Port (6379)" $redisPort "Optional for distributed cache" "Warning"

# ═══════════════════════════════════════════════════════════════
Write-Host "`nCATEGORY 3: Configuration Files" -ForegroundColor Yellow

# Backend .env
$envExists = Test-Path "backend\.env"
Add-ValidationResult "Config" "backend\.env exists" $envExists

if ($envExists) {
    $envContent = Get-Content "backend\.env" -Raw
    
    # Check critical settings
    $hasHFToken = $envContent -match "HUGGINGFACE_TOKEN=hf_\w+"
    Add-ValidationResult "Config" "Hugging Face Token" $hasHFToken
    
    $hasAdvanced = $envContent -match "STT_BACKEND=advanced"
    Add-ValidationResult "Config" "STT_BACKEND=advanced" $hasAdvanced "For best quality" $(if ($hasAdvanced) { "Info" } else { "Warning" })
    
    $hasContext = $envContent -match "OLLAMA_NUM_CTX=8192"
    Add-ValidationResult "Config" "OLLAMA_NUM_CTX=8192" $hasContext "For detailed summaries" $(if ($hasContext) { "Info" } else { "Warning" })
    
    $hasDiarization = $envContent -match "ENABLE_SPEAKER_DIARIZATION=true"
    Add-ValidationResult "Config" "Speaker Diarization" $hasDiarization "For speaker names" $(if ($hasDiarization) { "Info" } else { "Warning" })
}

# Frontend .env.local
$frontendEnv = Test-Path "frontend\.env.local"
Add-ValidationResult "Config" "frontend\.env.local exists" $frontendEnv "Optional" "Warning"

# ═══════════════════════════════════════════════════════════════
Write-Host "`nCATEGORY 4: Dependencies" -ForegroundColor Yellow

cd backend

# Python packages
try {
    $packages = @("transformers", "torch", "pyannote.audio", "noisereduce", "psutil", "ollama")
    foreach ($package in $packages) {
        $installed = pip show $package 2>&1
        $passed = $installed -notmatch "WARNING"
        Add-ValidationResult "Dependencies" "Python: $package" $passed
    }
} catch {
    Add-ValidationResult "Dependencies" "Python packages" $false "Check failed"
}

cd ../frontend

# Node packages
try {
    $packageJson = Get-Content "package.json" | ConvertFrom-Json
    $hasNext = $packageJson.dependencies.next -ne $null
    $hasReact = $packageJson.dependencies.react -ne $null
    Add-ValidationResult "Dependencies" "Next.js" $hasNext
    Add-ValidationResult "Dependencies" "React" $hasReact
} catch {
    Add-ValidationResult "Dependencies" "Node packages" $false "Check failed"
}

cd ..

# ═══════════════════════════════════════════════════════════════
Write-Host "`nCATEGORY 5: Database" -ForegroundColor Yellow

cd backend

# Database connection
try {
    python -c "from app.database import engine; engine.execute('SELECT 1'); print('OK')" 2>&1 | Out-Null
    $passed = $LASTEXITCODE -eq 0
    Add-ValidationResult "Database" "PostgreSQL Connection" $passed
} catch {
    Add-ValidationResult "Database" "PostgreSQL Connection" $false "Connection failed"
}

# Database tables
try {
    python -c "from app import models; from app.database import engine; from sqlalchemy import inspect; inspector = inspect(engine); tables = inspector.get_table_names(); print(len(tables), 'tables')"
    $passed = $LASTEXITCODE -eq 0
    Add-ValidationResult "Database" "Tables Created" $passed
} catch {
    Add-ValidationResult "Database" "Tables Created" $false
}

# Database indexes
try {
    python -c "from app.database import engine; from sqlalchemy import text; result = engine.execute(text('SELECT COUNT(*) FROM pg_indexes WHERE schemaname = ''public''')); count = result.scalar(); print(f'{count} indexes'); exit(0 if count > 20 else 1)"
    $passed = $LASTEXITCODE -eq 0
    Add-ValidationResult "Database" "Indexes Created (20+)" $passed
} catch {
    Add-ValidationResult "Database" "Indexes Created" $false "Run database_optimizations.py"
}

cd ..

# ═══════════════════════════════════════════════════════════════
Write-Host "`nCATEGORY 6: AI Components" -ForegroundColor Yellow

cd backend

# Ollama connection
try {
    python -c "from app.ai.ollama_service import check_available; ok, msg = check_available(); print(msg); exit(0 if ok else 1)"
    $passed = $LASTEXITCODE -eq 0
    Add-ValidationResult "AI" "Ollama Connection" $passed
} catch {
    Add-ValidationResult "AI" "Ollama Connection" $false
}

# Ollama model
try {
    $models = ollama list 2>&1 | Out-String
    $hasModel = $models -match "llama3.2"
    Add-ValidationResult "AI" "llama3.2 Model" $hasModel
} catch {
    Add-ValidationResult "AI" "llama3.2 Model" $false "Run: ollama pull llama3.2"
}

# Transcription engine
try {
    python -c "from app.ai.transcription import get_model; get_model(); print('OK')" 2>&1 | Out-Null
    $passed = $LASTEXITCODE -eq 0
    Add-ValidationResult "AI" "Whisper Model" $passed
} catch {
    Add-ValidationResult "AI" "Whisper Model" $false
}

# Advanced transcription
try {
    python -c "from app.config import settings; print(settings.STT_BACKEND); exit(0 if settings.STT_BACKEND == 'advanced' else 1)"
    $passed = $LASTEXITCODE -eq 0
    Add-ValidationResult "AI" "Advanced Transcription" $passed "Best quality" $(if ($passed) { "Info" } else { "Warning" })
} catch {
    Add-ValidationResult "AI" "Advanced Transcription" $false
}

cd ..

# ═══════════════════════════════════════════════════════════════
Write-Host "`nCATEGORY 7: Performance Features" -ForegroundColor Yellow

cd backend

# Cache system
try {
    python -c "from app.utils.cache import get_cache; c = get_cache(); c.set('test', 'ok'); assert c.get('test') == 'ok'; print('OK')"
    $passed = $LASTEXITCODE -eq 0
    Add-ValidationResult "Performance" "Cache System" $passed
} catch {
    Add-ValidationResult "Performance" "Cache System" $false
}

# Performance monitoring
try {
    python -c "from app.utils.performance_monitor import get_monitor; m = get_monitor(); print('OK')"
    $passed = $LASTEXITCODE -eq 0
    Add-ValidationResult "Performance" "Performance Monitor" $passed
} catch {
    Add-ValidationResult "Performance" "Performance Monitor" $false
}

# Retry logic
try {
    python -c "from app.utils.retry_logic import retry_with_backoff; print('OK')"
    $passed = $LASTEXITCODE -eq 0
    Add-ValidationResult "Performance" "Retry Logic" $passed
} catch {
    Add-ValidationResult "Performance" "Retry Logic" $false
}

# Query helpers
try {
    python -c "from app.utils.query_helpers import MeetingQueries; print('OK')"
    $passed = $LASTEXITCODE -eq 0
    Add-ValidationResult "Performance" "Query Optimization" $passed
} catch {
    Add-ValidationResult "Performance" "Query Optimization" $false
}

cd ..

# ═══════════════════════════════════════════════════════════════
if ($FullTest) {
    Write-Host "`nCATEGORY 8: Full Test Suite" -ForegroundColor Yellow
    
    try {
        python -m pytest tests/test_optimizations.py -v
        $passed = $LASTEXITCODE -eq 0
        Add-ValidationResult "Testing" "Automated Tests" $passed
    } catch {
        Add-ValidationResult "Testing" "Automated Tests" $false "Run: python -m pytest tests/test_optimizations.py"
    }
}

# ═══════════════════════════════════════════════════════════════
Write-Host "`n╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                   VALIDATION RESULTS                       ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

# Summary
$totalTests = $ValidationResults.Count
$passed = ($ValidationResults | Where-Object { $_.Passed }).Count
$failed = ($ValidationResults | Where-Object { -not $_.Passed -and $_.Severity -eq "Error" }).Count
$warnings = ($ValidationResults | Where-Object { -not $_.Passed -and $_.Severity -eq "Warning" }).Count

Write-Host "Total Checks: $totalTests" -ForegroundColor Cyan
Write-Host "✓ Passed: $passed" -ForegroundColor Green
if ($failed -gt 0) {
    Write-Host "✗ Failed: $failed" -ForegroundColor Red
}
if ($warnings -gt 0) {
    Write-Host "⚠ Warnings: $warnings" -ForegroundColor Yellow
}

# Pass rate
$passRate = [math]::Round(($passed / $totalTests) * 100, 1)
Write-Host "`nPass Rate: $passRate%" -ForegroundColor $(if ($passRate -ge 90) { "Green" } elseif ($passRate -ge 75) { "Yellow" } else { "Red" })

# Critical failures
$criticalFailures = $ValidationResults | Where-Object { -not $_.Passed -and $_.Severity -eq "Error" }
if ($criticalFailures.Count -gt 0) {
    Write-Host "`n⚠️  CRITICAL ISSUES FOUND:" -ForegroundColor Red
    foreach ($failure in $criticalFailures) {
        Write-Host "  ✗ $($failure.Category): $($failure.Test)" -ForegroundColor Red
        if ($failure.Message) {
            Write-Host "    $($failure.Message)" -ForegroundColor Gray
        }
    }
}

# Recommendations
Write-Host "`n📋 RECOMMENDATIONS:" -ForegroundColor Cyan

if ($failed -eq 0 -and $warnings -eq 0) {
    Write-Host "`n🎉 ALL CHECKS PASSED!" -ForegroundColor Green
    Write-Host "Your enterprise system is ready for production!" -ForegroundColor Green
} elseif ($failed -eq 0) {
    Write-Host "`n✅ SYSTEM READY (with warnings)" -ForegroundColor Yellow
    Write-Host "Address warnings for optimal performance" -ForegroundColor Yellow
} else {
    Write-Host "`n⚠️  SYSTEM NOT READY" -ForegroundColor Red
    Write-Host "Fix critical issues before deployment" -ForegroundColor Red
}

Write-Host "`nNext Steps:" -ForegroundColor Cyan
if ($failed -gt 0) {
    Write-Host "  1. Fix critical issues listed above" -ForegroundColor White
    Write-Host "  2. Re-run validation: .\Validate_Enterprise_System.ps1" -ForegroundColor White
} else {
    Write-Host "  1. Review ENTERPRISE_DEPLOYMENT.md" -ForegroundColor White
    Write-Host "  2. Run: .\Enterprise_Install.ps1 (if not done)" -ForegroundColor White
    Write-Host "  3. Start services and test" -ForegroundColor White
}

Write-Host "`n═══════════════════════════════════════════════════════════`n" -ForegroundColor Cyan

# Export results
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$reportFile = "validation_report_$timestamp.json"
$ValidationResults | ConvertTo-Json | Out-File $reportFile
Write-Host "📄 Full report saved to: $reportFile" -ForegroundColor Gray

# Exit code
if ($failed -gt 0) {
    exit 1
} else {
    exit 0
}
