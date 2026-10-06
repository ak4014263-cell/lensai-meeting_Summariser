#!/bin/bash
################################################################################
# AI Meeting Assistant - Application Deployment Script
# Run this after setup_ec2.sh
# Usage: bash deploy_app.sh
################################################################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}"
echo "========================================================"
echo "  AI Meeting Assistant - Application Deployment"
echo "========================================================"
echo -e "${NC}"

# Configuration
APP_DIR="$HOME/ai-meeting-assistant"
REPO_URL="https://github.com/YOUR_USERNAME/ai-meeting-assistant.git"  # UPDATE THIS!
DOMAIN="lensaibot.duckdns.org"

# Check if repo URL is still default
if [[ "$REPO_URL" == *"YOUR_USERNAME"* ]]; then
    echo -e "${YELLOW}Please update REPO_URL in this script with your actual repository URL${NC}"
    read -p "Enter your repository URL: " REPO_URL
fi

# Clone or pull repository
echo -e "${YELLOW}[1/8] Fetching application code...${NC}"
if [ -d "$APP_DIR" ]; then
    echo "Directory exists, pulling latest changes..."
    cd "$APP_DIR"
    git pull origin main || git pull origin master
else
    echo "Cloning repository..."
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# Setup Backend
echo -e "${YELLOW}[2/8] Setting up backend...${NC}"
cd "$APP_DIR/backend"

# Create virtual environment
if [ ! -d "venv" ]; then
    python3.11 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
playwright install-deps

# Create .env file
echo -e "${YELLOW}[3/8] Creating backend .env file...${NC}"
cat > .env << 'ENV_EOF'
# Database
DATABASE_URL=sqlite:///./sql_app.db
MONGODB_URL=mongodb://localhost:27017

# Ollama (LLM)
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=llama3
OLLAMA_NUM_CTX=32768
OLLAMA_TEMPERATURE=0.3
OLLAMA_TIMEOUT=1200

# Transcription - Using faster Whisper model
STT_BACKEND=local
HUGGINGFACE_MODEL=openai/whisper-large-v3-turbo
WHISPER_MODEL=large-v3
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
WHISPER_BEAM_SIZE=5
WHISPER_VAD=true

# LLM Processing
LLM_CHUNK_CHARS=20000
LLM_CHUNK_OVERLAP_CHARS=1000
LLM_MAX_CHUNKS=100

# Bot Configuration
BOT_DISPLAY_NAME=AI Notetaker
BOT_HEADLESS=false
BOT_BROWSER_CHANNEL=chrome
BOT_ADMISSION_TIMEOUT=300
BOT_WAIT_FOR_PEOPLE=120
BOT_ALONE_GRACE_SECONDS=30
BOT_MAX_MEETING_MINUTES=180
BOT_POLL_SECONDS=5
BOT_POST_CALL_DELAY=5
BOT_DEBUG_SCREENSHOTS=true
BOT_MAX_CONCURRENT=3

# Auth - Generate secure secret
SECRET_KEY=$(openssl rand -hex 32)
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Frontend URL
FRONTEND_BASE_URL=https://lensaibot.duckdns.org
FRONTEND_URL=https://lensaibot.duckdns.org

# Google OAuth (configure these later if needed)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=https://lensaibot.duckdns.org/api/integrations/google/callback
BOT_EMAIL=

# Email Notifications (configure these later if needed)
SEND_EMAIL_NOTIFICATIONS=false
SMTP_HOST=
SMTP_PORT=587
SMTP_TLS=true
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=noreply@lensaibot.duckdns.org
SMTP_FROM_NAME=AI Meeting Assistant

# Storage
STORAGE_DIR=$APP_DIR/backend/storage

# Live transcription
LIVE_ENABLED=true
LIVE_CHUNK_SECONDS=15
LIVE_SUMMARY_INTERVAL=45
ENV_EOF

# Replace APP_DIR placeholder with actual path
sed -i "s|\$APP_DIR|$APP_DIR|g" .env

# Create storage directory
mkdir -p storage

echo "Backend .env created with secure SECRET_KEY"

# Setup Frontend
echo -e "${YELLOW}[4/8] Setting up frontend...${NC}"
cd "$APP_DIR/frontend"

# Install dependencies
npm install

# Create .env.local
cat > .env.local << 'FRONTEND_ENV_EOF'
NEXT_PUBLIC_API_URL=https://lensaibot.duckdns.org/api
NEXT_PUBLIC_WS_URL=wss://lensaibot.duckdns.org/ws
FRONTEND_ENV_EOF

echo "Frontend .env.local created"

# Build frontend
echo -e "${YELLOW}[5/8] Building frontend for production...${NC}"
npm run build

# Setup PM2 ecosystem
echo -e "${YELLOW}[6/8] Configuring PM2...${NC}"
cd "$APP_DIR"

cat > ecosystem.config.js << 'PM2_EOF'
module.exports = {
  apps: [
    {
      name: 'ai-meeting-backend',
      cwd: '/home/ubuntu/ai-meeting-assistant/backend',
      script: '/home/ubuntu/ai-meeting-assistant/backend/venv/bin/uvicorn',
      args: 'app.main:app --host 0.0.0.0 --port 8000',
      interpreter: '/home/ubuntu/ai-meeting-assistant/backend/venv/bin/python',
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '2G',
      env: {
        PYTHONPATH: '/home/ubuntu/ai-meeting-assistant/backend',
        DISPLAY: ':99'
      },
      error_file: '/home/ubuntu/logs/backend-error.log',
      out_file: '/home/ubuntu/logs/backend-out.log',
      time: true,
      kill_timeout: 5000
    },
    {
      name: 'ai-meeting-frontend',
      cwd: '/home/ubuntu/ai-meeting-assistant/frontend',
      script: 'node_modules/next/dist/bin/next',
      args: 'start',
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        PORT: 3000,
        NODE_ENV: 'production'
      },
      error_file: '/home/ubuntu/logs/frontend-error.log',
      out_file: '/home/ubuntu/logs/frontend-out.log',
      time: true
    }
  ]
};
PM2_EOF

# Start virtual display for Chrome (headless issues with Google Meet)
echo -e "${YELLOW}[7/8] Starting virtual display...${NC}"
# Kill existing Xvfb if running
pkill Xvfb || true
sleep 1
# Start Xvfb on display :99
Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 &
echo "Virtual display started on :99"

# Add to PM2 startup
cat > "$APP_DIR/start_xvfb.sh" << 'XVFB_EOF'
#!/bin/bash
pkill Xvfb || true
sleep 1
Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 &
XVFB_EOF

chmod +x "$APP_DIR/start_xvfb.sh"

# Add Xvfb to crontab
(crontab -l 2>/dev/null; echo "@reboot $APP_DIR/start_xvfb.sh") | sort -u | crontab -

# Start applications with PM2
echo -e "${YELLOW}[8/8] Starting applications with PM2...${NC}"
pm2 delete all || true  # Delete old processes if any
sleep 2
pm2 start ecosystem.config.js
pm2 save
pm2 startup | grep -v "PM2" | bash || true

# Wait for services to start
echo "Waiting for services to start..."
sleep 5

# Check status
pm2 status

echo -e "${GREEN}"
echo "========================================================"
echo "  ✅ Application Deployed!"
echo "========================================================"
echo ""
echo "Services Status:"
pm2 status
echo ""
echo "Quick Commands:"
echo "  View logs:     pm2 logs"
echo "  Restart all:   pm2 restart all"
echo "  Stop all:      pm2 stop all"
echo "  Status:        pm2 status"
echo ""
echo "Application URLs (after SSL setup):"
echo "  Frontend:      https://$DOMAIN"
echo "  Backend API:   https://$DOMAIN/api"
echo "  API Docs:      https://$DOMAIN/api/docs"
echo ""
echo "Next Steps:"
echo "  1. Run setup_ssl.sh to configure SSL certificate"
echo "  2. Configure Nginx with setup_nginx.sh"
echo "  3. Test the application in your browser"
echo ""
echo "========================================================"
echo -e "${NC}"
