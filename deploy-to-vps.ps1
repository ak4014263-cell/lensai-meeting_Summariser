# LensAI Deployment Script - Automated SSH Deployment
# This script will SSH into your VPS and run the deployment

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  LensAI Deployment to lenss.ai/ai" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# VPS Details
$VPS_IP = "200.97.170.172"
$VPS_USER = "root"
$VPS_PASSWORD = "Lensai@898918"

Write-Host "Target VPS: $VPS_IP" -ForegroundColor Green
Write-Host ""

# Get user inputs
Write-Host "Please provide the following information:" -ForegroundColor Yellow
Write-Host ""

$SSL_EMAIL = Read-Host "Enter your email for SSL certificate"
$GOOGLE_CLIENT_ID = Read-Host "Enter your Google OAuth Client ID"
$GOOGLE_CLIENT_SECRET = Read-Host "Enter your Google OAuth Client Secret" -AsSecureString
$GOOGLE_CLIENT_SECRET_TEXT = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($GOOGLE_CLIENT_SECRET))
$HUGGINGFACE_TOKEN = Read-Host "Enter your HuggingFace Token"

Write-Host ""
Write-Host "Configuration received. Preparing deployment..." -ForegroundColor Green
Write-Host ""

# Create deployment commands
$commands = @"
set -e

# Create non-root user
adduser --disabled-password --gecos '' lensai 2>/dev/null || echo 'User exists'
echo 'lensai:Lensai@898918' | chpasswd
usermod -aG sudo lensai

# Download deployment script
sudo -u lensai bash -c 'cd ~ && wget -q https://raw.githubusercontent.com/ak4014263-cell/lensai-meeting_Summariser/main/deploy-lenss-ai.sh -O deploy-lenss-ai.sh && chmod +x deploy-lenss-ai.sh'

# Run deployment with environment variables
sudo -u lensai bash -c 'cd ~ && export SSL_EMAIL="$SSL_EMAIL" GOOGLE_CLIENT_ID="$GOOGLE_CLIENT_ID" GOOGLE_CLIENT_SECRET="$GOOGLE_CLIENT_SECRET_TEXT" HUGGINGFACE_TOKEN="$HUGGINGFACE_TOKEN" && bash deploy-lenss-ai.sh'

echo ""
echo "Deployment completed!"
"@

# Save commands to temporary file
$tempScript = [System.IO.Path]::GetTempFileName() + ".sh"
$commands | Out-File -FilePath $tempScript -Encoding ASCII

Write-Host "Connecting to VPS and running deployment..." -ForegroundColor Yellow
Write-Host "This may take 20-30 minutes..." -ForegroundColor Yellow
Write-Host ""

# Use plink (PuTTY) if available, otherwise show manual instructions
$plinkPath = "C:\Program Files\PuTTY\plink.exe"

if (Test-Path $plinkPath) {
    Write-Host "Using PuTTY plink to connect..." -ForegroundColor Green
    
    # Run commands via plink
    & $plinkPath -ssh $VPS_USER@$VPS_IP -pw $VPS_PASSWORD -batch -m $tempScript
    
} else {
    Write-Host "PuTTY not found. Please run these commands manually:" -ForegroundColor Red
    Write-Host ""
    Write-Host "1. Connect to VPS:" -ForegroundColor Yellow
    Write-Host "   ssh root@$VPS_IP" -ForegroundColor White
    Write-Host ""
    Write-Host "2. Create user and download script:" -ForegroundColor Yellow
    Write-Host @"
adduser --disabled-password --gecos '' lensai
echo 'lensai:Lensai@898918' | chpasswd
usermod -aG sudo lensai
sudo -u lensai bash -c 'cd ~ && wget https://raw.githubusercontent.com/ak4014263-cell/lensai-meeting_Summariser/main/deploy-lenss-ai.sh && chmod +x deploy-lenss-ai.sh'
sudo -u lensai bash -c 'cd ~ && ./deploy-lenss-ai.sh'
"@ -ForegroundColor White
    Write-Host ""
    Write-Host "When prompted, provide:" -ForegroundColor Yellow
    Write-Host "  Email: $SSL_EMAIL" -ForegroundColor White
    Write-Host "  Google Client ID: $GOOGLE_CLIENT_ID" -ForegroundColor White
    Write-Host "  Google Client Secret: $GOOGLE_CLIENT_SECRET_TEXT" -ForegroundColor White
    Write-Host "  HuggingFace Token: $HUGGINGFACE_TOKEN" -ForegroundColor White
}

# Clean up
Remove-Item $tempScript -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Next Steps" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "After deployment completes:" -ForegroundColor Green
Write-Host "1. Access your application: https://lenss.ai/ai" -ForegroundColor White
Write-Host "2. Setup bot Google account (see documentation)" -ForegroundColor White
Write-Host "3. Test a meeting!" -ForegroundColor White
Write-Host ""
