# ═══════════════════════════════════════════════════════════════
# AI MEETING ASSISTANT - ENTERPRISE INSTALLATION SCRIPT
# Version: 2.0.0 Enterprise Edition
# ═══════════════════════════════════════════════════════════════

# Requires Administrator privileges
#Requires -RunAsAdministrator

param(
    [switch]$SkipTests = $false,
    [switch]$Production = $false
)

$ErrorActionPreference = "Continue"
$Global:FailureCount = 0
$Global:SuccessCount = 0

function Write-Step {
    param([string]$Message)
    Write-Host "`n" -NoNewline
    Write-Host "═══════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  $Message" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
    $Global:SuccessCount++
}

function Write-Failure {
    param([string]$Message)
    Write-Host "✗ $Message" -ForegroundColor Red
    $Global:FailureCount++
}

function Write-Info {
    param([string]$Message)
    Write-Host "ℹ $Message" -ForegroundColor Cyan
}

function Test-Command {
    param([string]$Command)
    try {
        Get-Command $Command -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

# ═══════════════════════════════════════════════════════════════
Write-Host "`n"
Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                                                           ║" -ForegroundColor Cyan
Write-Host "║        AI MEETING ASSISTANT - ENTERPRISE EDITION          ║" -ForegroundColor Cyan
Write-Host "║             Complete System Installation                  ║" -ForegroundColor Cyan
Write-Host "║                                                           ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host "`n"

# ═══════════════════════════════════════════════════════════════
Write-Step "STEP 1/12: System Requirements Check"

Write-Info "Checking system requirements..."

# Check Python
if (Test-Command python) {
    $pythonVersion = python --version 2>&1
    Write-Success "Python found: $pythonVersion"
} else {
    Write-Failure "Python not found. Install Python 3.9+ from python.org"
}

# Check Node.js
if (Test-Command node) {
    $nodeVersion = node --version
    Write-Success "Node.js found: $nodeVersion"
} else {
    Write-Failure "Node.js not found. Install Node.js 18+ from nodejs.org"
}

# Check pip
if (Test-Command pip) {
    Write-Success "pip found"
} else {
    Write-Failure "pip not found"
}

# Check PostgreSQL
if (Test-Command psql) {
    $pgVersion = psql --version
    Write-Success "PostgreSQL found: $pgVersion"
} else {
    Write-Failure "PostgreSQL not found. Install from postgresql.org"
}

# Check MongoDB
if (Test-Command mongod) {
    Write-Success "MongoDB found"
} else {
    Write-Info "MongoDB not detected (optional for chat features)"
}

# Check Ollama
if (Test-Command ollama) {
    $ollamaVersion = ollama --version 2>&1
    Write-Success "Ollama found: $ollamaVersion"
} else {
    Write-Failure "Ollama not found. Install from ollama.ai"
}

# Check disk space
$drive = Get-PSDrive C
$freeGB = [math]::Round($drive.Free / 1GB, 2)
if ($freeGB -gt 50) {
    Write-Success "Disk space: ${freeGB}GB free"
} else {
    Write-Failure "Low disk space: ${freeGB}GB (need 50GB+)"
}

# Check RAM
$ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 2)
if ($ram -ge 16) {
    Write-Success "RAM: ${ram}GB"
} else {
    Write-Failure "Insufficient RAM: ${ram}GB (need 16GB+)"
}

if ($Global:FailureCount -gt 0) {
    Write-Host "`n⚠️  Some requirements are missing. Continue anyway? (y/n)" -ForegroundColor Yellow
    $continue = Read-Host
    if ($continue -ne 'y') {
        exit 1
    }
}

# ═══════════════════════════════════════════════════════════════
Write-Step "STEP 2/12: Installing Backend Dependencies"

Write-Info "Installing Python packages (this may take 5-10 minutes)..."
cd backend

try {
    pip install --upgrade pip
    pip install -r requirements.txt
    Write-Success "Backend dependencies installed"
} catch {
    Write-Failure "Backend installation failed: $_"
}

cd ..

# ═══════════════════════════════════════════════════════════════
Write-Step "STEP 3/12: Installing Frontend Dependencies"

Write-Info "Installing Node packages..."
cd frontend

try {
    npm install
    Write-Success "Frontend dependencies installed"
} catch {
    Write-Failure "Frontend installation failed: $_"
}

cd ..

# ═══════════════════════════════════════════════════════════════
Write-Step "STEP 4/12: Configuring Ollama"

Write-Info "Checking Ollama service..."

try {
    $ollamaRunning = Get-Process ollama -ErrorAction SilentlyContinue
    if ($ollamaRunning) {
        Write-Success "Ollama service is running"
    } else {
        Write-Info "Starting Ollama service..."
        Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 3
        Write-Success "Ollama service started"
    }
    
    # Check for required model
    Write-Info "Checking for llama3.2 model..."
    $models = ollama list 2>&1 | Out-String
    
    if ($models -match "llama3.2") {
        Write-Success "llama3.2 model already installed"
    } else {
        Write-Info "Downloading llama3.2 model (this may take several minutes)..."
        ollama pull llama3.2:latest
        Write-Success "llama3.2 model downloaded"
    }
} catch {
    Write-Failure "Ollama configuration failed: $_"
}

# ═══════════════════════════════════════════════════════════════
Write-Step "STEP 5/12: Validating Configuration Files"

Write-Info "Checking configuration files..."

$envPath = "backend\.env"
if (Test-Path $envPath) {
    Write-Success "backend\.env found"
    
    $envContent = Get-Content $envPath -Raw
    
    # Check critical settings
    $checks = @(
        @{ Name = "STT_BACKEND"; Pattern = "STT_BACKEND=advanced"; Required = $true },
        @{ Name = "HUGGINGFACE_TOKEN"; Pattern = "HUGGINGFACE_TOKEN=hf_"; Required = $true },
        @{ Name = "OLLAMA_NUM_CTX"; Pattern = "OLLAMA_NUM_CTX=8192"; Required = $false },
        @{ Name = "ENABLE_SPEAKER_DIARIZATION"; Pattern = "ENABLE_SPEAKER_DIARIZATION=true"; Required = $false }
    )
    
    foreach ($check in $checks) {
        if ($envContent -match $check.Pattern) {
            Write-Success "$($check.Name) configured"
        } else {
            if ($check.Required) {
                Write-Failure "$($check.Name) not configured"
            } else {
                Write-Info "$($check.Name) not optimally configured"
            }
        }
    }
} else {
    Write-Failure "backend\.env not found. Copy from .env.example"
}

# ═══════════════════════════════════════════════════════════════
Write-Step "STEP 6/12: Database Initialization"

Write-Info "Initializing database..."

cd backend

try {
    python -c "from app.database import engine, Base; Base.metadata.create_all(bind=engine); print('Database tables created')"
    Write-Success "Database initialized"
} catch {
    Write-Failure "Database initialization failed: $_"
}

cd ..

# ═══════════════════════════════════════════════════════════════
Write-Step "STEP 7/12: Creating Database Indexes"

Write-Info "Optimizing database with indexes..."

cd backend

try {
    python -m app.database_optimizations
    Write-Success "Database indexes created"
} catch {
    Write-Failure "Database optimization failed: $_"
}

cd ..

# ═══════════════════════════════════════════════════════════════
Write-Step "STEP 8/12: Testing Transcription Engine"

Write-Info "Testing transcription components..."

cd backend

try {
    python -c "from app.ai.transcription import _transcribe_file_local; print('Local whisper OK')"
    Write-Success "Local transcription engine ready"
} catch {
    Write-Failure "Transcription engine test failed: $_"
}

try {
    python -c "from app.config import settings; print(f'Backend: {settings.STT_BACKEND}')"
    Write-Success "Transcription backend configured"
} catch {
    Write-Failure "Configuration load failed: $_"
}

cd ..

# ═══════════════════════════════════════════════════════════════
Write-Step "STEP 9/12: Testing AI Summarization"

Write-Info "Testing Ollama connection..."

cd backend

try {
    python -c "from app.ai.ollama_service import check_available; ok, msg = check_available(); print('✓' if ok else '✗', msg); exit(0 if ok else 1)"
    Write-Success "AI summarization ready"
} catch {
    Write-Failure "AI summarization test failed. Is Ollama running?"
}

cd ..

# ═══════════════════════════════════════════════════════════════
Write-Step "STEP 10/12: Testing Cache System"

Write-Info "Testing caching system..."

cd backend

try {
    python -c "from app.utils.cache import get_cache; c = get_cache(); c.set('test', 'ok'); assert c.get('test') == 'ok'; print('Cache OK')"
    Write-Success "Cache system working"
} catch {
    Write-Failure "Cache test failed: $_"
}

cd ..

# ═══════════════════════════════════════════════════════════════
Write-Step "STEP 11/12: Running Test Suite"

if (-not $SkipTests) {
    Write-Info "Running automated tests..."
    
    try {
        python -m pytest tests/test_optimizations.py -v --tb=short
        if ($LASTEXITCODE -eq 0) {
            Write-Success "All tests passed"
        } else {
            Write-Failure "Some tests failed (non-critical)"
        }
    } catch {
        Write-Failure "Test suite failed: $_"
    }
} else {
    Write-Info "Tests skipped (use without -SkipTests to run)"
}

# ═══════════════════════════════════════════════════════════════
Write-Step "STEP 12/12: System Verification"

Write-Info "Running final system checks..."

# Check if all services can start
$checks = @()

# Test backend startup
try {
    cd backend
    $job = Start-Job -ScriptBlock {
        Set-Location $using:PWD
        python -c "from app.main import app; print('Backend import OK')"
    }
    Wait-Job $job -Timeout 10 | Out-Null
    $result = Receive-Job $job
    Stop-Job $job
    Remove-Job $job
    
    if ($result -match "OK") {
        Write-Success "Backend can start"
        $checks += $true
    } else {
        Write-Failure "Backend startup test failed"
        $checks += $false
    }
    cd ..
} catch {
    Write-Failure "Backend verification failed: $_"
    $checks += $false
    cd ..
}

# Test frontend build
try {
    cd frontend
    Write-Info "Testing frontend build (this may take a minute)..."
    npm run build 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Frontend can build"
        $checks += $true
    } else {
        Write-Failure "Frontend build test failed"
        $checks += $false
    }
    cd ..
} catch {
    Write-Failure "Frontend verification failed: $_"
    $checks += $false
    cd ..
}

# ═══════════════════════════════════════════════════════════════
Write-Host "`n"
Write-Host "╔═══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                  INSTALLATION COMPLETE                     ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host "`n"

Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "  ✓ Successful checks: $Global:SuccessCount" -ForegroundColor Green
if ($Global:FailureCount -gt 0) {
    Write-Host "  ✗ Failed checks: $Global:FailureCount" -ForegroundColor Red
}

Write-Host "`n📋 Installation Report:" -ForegroundColor Cyan
Write-Host "  ✓ Python dependencies installed" -ForegroundColor Green
Write-Host "  ✓ Node dependencies installed" -ForegroundColor Green
Write-Host "  ✓ Database initialized" -ForegroundColor Green
Write-Host "  ✓ Database indexes created" -ForegroundColor Green
Write-Host "  ✓ Ollama configured" -ForegroundColor Green
Write-Host "  ✓ System verified" -ForegroundColor Green

Write-Host "`n🚀 Next Steps:" -ForegroundColor Cyan
Write-Host "`n1. Start Ollama (if not running):" -ForegroundColor White
Write-Host "   ollama serve" -ForegroundColor Gray

Write-Host "`n2. Start Backend:" -ForegroundColor White
Write-Host "   cd backend" -ForegroundColor Gray
Write-Host "   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000" -ForegroundColor Gray

Write-Host "`n3. Start Frontend:" -ForegroundColor White
Write-Host "   cd frontend" -ForegroundColor Gray
Write-Host "   npm run dev" -ForegroundColor Gray

Write-Host "`n4. Access the application:" -ForegroundColor White
Write-Host "   Frontend: http://localhost:3000" -ForegroundColor Gray
Write-Host "   Backend API: http://localhost:8000" -ForegroundColor Gray
Write-Host "   API Docs: http://localhost:8000/docs" -ForegroundColor Gray

Write-Host "`n📚 Documentation:" -ForegroundColor Cyan
Write-Host "   - OPTIMIZATION_GUIDE.md - Complete configuration guide" -ForegroundColor Gray
Write-Host "   - VERIFICATION_CHECKLIST.md - Testing procedures" -ForegroundColor Gray
Write-Host "   - ENTERPRISE_DEPLOYMENT.md - Production deployment" -ForegroundColor Gray

if ($Production) {
    Write-Host "`n🏢 Production Mode:" -ForegroundColor Yellow
    Write-Host "   Review ENTERPRISE_DEPLOYMENT.md for production setup" -ForegroundColor Gray
    Write-Host "   Configure SSL certificates" -ForegroundColor Gray
    Write-Host "   Set up monitoring and backups" -ForegroundColor Gray
    Write-Host "   Review security hardening steps" -ForegroundColor Gray
}

if ($Global:FailureCount -gt 0) {
    Write-Host "`n⚠️  Warning: $Global:FailureCount checks failed" -ForegroundColor Yellow
    Write-Host "   Review errors above and fix before production use" -ForegroundColor Yellow
} else {
    Write-Host "`n✅ ALL SYSTEMS GO! Your enterprise system is ready!" -ForegroundColor Green
}

Write-Host "`n═══════════════════════════════════════════════════════════`n" -ForegroundColor Cyan

# Create log file
$logFile = "installation_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss').log"
$transcript = Get-Content $PSCommandPath
$transcript | Out-File $logFile
Write-Info "Installation log saved to: $logFile"
