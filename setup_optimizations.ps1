# AI Meeting Assistant - Optimization Setup Script
# Windows PowerShell version
# Run this script to install all optimization dependencies

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  AI Meeting Assistant - Optimization Setup" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is installed
Write-Host "[1/6] Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  ✓ Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Python not found! Please install Python 3.9+ first" -ForegroundColor Red
    exit 1
}

# Check if pip is installed
Write-Host "[2/6] Checking pip installation..." -ForegroundColor Yellow
try {
    $pipVersion = pip --version 2>&1
    Write-Host "  ✓ pip found: $pipVersion" -ForegroundColor Green
} catch {
    Write-Host "  ✗ pip not found! Please install pip first" -ForegroundColor Red
    exit 1
}

# Install backend dependencies
Write-Host "[3/6] Installing backend Python packages..." -ForegroundColor Yellow
Write-Host "  This may take 5-10 minutes for large packages like torch..." -ForegroundColor Cyan
cd backend
try {
    pip install -r requirements.txt
    Write-Host "  ✓ Backend dependencies installed successfully" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Failed to install backend dependencies" -ForegroundColor Red
    Write-Host "  Try running: pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}
cd ..

# Check if Ollama is installed
Write-Host "[4/6] Checking Ollama installation..." -ForegroundColor Yellow
try {
    $ollamaVersion = ollama --version 2>&1
    Write-Host "  ✓ Ollama found: $ollamaVersion" -ForegroundColor Green
    
    # Check if model is pulled
    Write-Host "  Checking for llama3.2 model..." -ForegroundColor Cyan
    $ollamaList = ollama list 2>&1 | Out-String
    if ($ollamaList -match "llama3.2") {
        Write-Host "  ✓ llama3.2 model already installed" -ForegroundColor Green
    } else {
        Write-Host "  Pulling llama3.2 model (this may take a few minutes)..." -ForegroundColor Cyan
        ollama pull llama3.2:latest
        Write-Host "  ✓ llama3.2 model installed" -ForegroundColor Green
    }
} catch {
    Write-Host "  ✗ Ollama not found!" -ForegroundColor Red
    Write-Host "  Please install Ollama from: https://ollama.ai/download" -ForegroundColor Yellow
    Write-Host "  After installation, run: ollama pull llama3.2:latest" -ForegroundColor Yellow
}

# Verify Hugging Face token
Write-Host "[5/6] Checking Hugging Face configuration..." -ForegroundColor Yellow
$envPath = "backend\.env"
if (Test-Path $envPath) {
    $envContent = Get-Content $envPath -Raw
    if ($envContent -match "HUGGINGFACE_TOKEN=hf_[a-zA-Z0-9]+") {
        Write-Host "  ✓ Hugging Face token configured" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ Hugging Face token not found or invalid" -ForegroundColor Yellow
        Write-Host "  Get your token from: https://huggingface.co/settings/tokens" -ForegroundColor Cyan
        Write-Host "  Add to backend\.env: HUGGINGFACE_TOKEN=hf_your_token_here" -ForegroundColor Cyan
    }
    
    # Check STT backend
    if ($envContent -match "STT_BACKEND=advanced") {
        Write-Host "  ✓ Advanced transcription backend enabled" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ STT_BACKEND not set to 'advanced'" -ForegroundColor Yellow
        Write-Host "  For best quality, set: STT_BACKEND=advanced" -ForegroundColor Cyan
    }
} else {
    Write-Host "  ✗ backend\.env not found!" -ForegroundColor Red
    Write-Host "  Please copy .env.example to .env and configure" -ForegroundColor Yellow
}

# Summary and next steps
Write-Host ""
Write-Host "[6/6] Setup Summary" -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan

$setupComplete = $true

# Check PyTorch/CUDA
Write-Host ""
Write-Host "GPU Acceleration (Optional but recommended):" -ForegroundColor Yellow
try {
    python -c "import torch; print('  ✓ PyTorch:', torch.__version__); print('  ✓ CUDA available:', torch.cuda.is_available())"
} catch {
    Write-Host "  ⚠ PyTorch not properly configured for GPU" -ForegroundColor Yellow
    Write-Host "  For GPU support, install: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "Required Services:" -ForegroundColor Yellow
Write-Host "  - PostgreSQL database" -ForegroundColor White
Write-Host "  - MongoDB (for chat features)" -ForegroundColor White  
Write-Host "  - Ollama service (ollama serve)" -ForegroundColor White

Write-Host ""
Write-Host "Configuration Files:" -ForegroundColor Yellow
Write-Host "  - backend\.env (main configuration)" -ForegroundColor White
Write-Host "  - See OPTIMIZATION_GUIDE.md for all options" -ForegroundColor White

Write-Host ""
if ($setupComplete) {
    Write-Host "==================================================" -ForegroundColor Green
    Write-Host "  ✓ Setup Complete!" -ForegroundColor Green
    Write-Host "==================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next Steps:" -ForegroundColor Cyan
    Write-Host "  1. Start Ollama: ollama serve" -ForegroundColor White
    Write-Host "  2. Start backend: cd backend && uvicorn app.main:app --reload" -ForegroundColor White
    Write-Host "  3. Start frontend: cd frontend && npm run dev" -ForegroundColor White
    Write-Host "  4. Open browser: http://localhost:3000" -ForegroundColor White
    Write-Host ""
    Write-Host "Documentation:" -ForegroundColor Cyan
    Write-Host "  - Read OPTIMIZATION_GUIDE.md for details" -ForegroundColor White
    Write-Host "  - Check backend\.env for configuration options" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host "  ⚠ Setup incomplete - see warnings above" -ForegroundColor Red
    Write-Host "==================================================" -ForegroundColor Red
}

Write-Host "Press any key to exit..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
