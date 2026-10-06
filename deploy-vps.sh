#!/bin/bash

################################################################################
# LensAI Meeting Assistant - VPS Deployment Script
# 
# This script automates the deployment of LensAI on a fresh Ubuntu VPS
# 
# Usage: 
#   1. SSH into your VPS
#   2. wget https://raw.githubusercontent.com/ak4014263-cell/lensai-meeting_Summariser/main/deploy-vps.sh
#   3. chmod +x deploy-vps.sh
#   4. ./deploy-vps.sh
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [ "$EUID" -eq 0 ]; then 
        log_error "Please do not run this script as root. Use a non-root user with sudo privileges."
        exit 1
    fi
}

# Banner
echo "================================================"
echo "  LensAI Meeting Assistant - VPS Deployment"
echo "================================================"
echo ""

# Check if running as root
check_root

# Get configuration from user
log_info "Please provide the following information:"
echo ""

read -p "Enter your domain name (e.g., lensai.yourdomain.com): " DOMAIN_NAME
read -p "Enter your email for SSL certificate: " SSL_EMAIL
read -p "Enter your Google OAuth Client ID: " GOOGLE_CLIENT_ID
read -sp "Enter your Google OAuth Client Secret: " GOOGLE_CLIENT_SECRET
echo ""
read -p "Enter your HuggingFace Token: " HUGGINGFACE_TOKEN

log_info "Configuration received. Starting deployment..."
sleep 2

################################################################################
# Step 1: Update System
################################################################################
log_info "Step 1/10: Updating system packages..."
sudo apt update && sudo apt upgrade -y

################################################################################
# Step 2: Install Dependencies
################################################################################
log_info "Step 2/10: Installing dependencies..."

# Node.js 20.x
log_info "Installing Node.js 20.x..."
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Python 3.11
log_info "Installing Python 3.11..."
sudo apt install -y python3.11 python3.11-venv python3-pip

# MongoDB 7.0
log_info "Installing MongoDB 7.0..."
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
   sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \
   sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt update
sudo apt install -y mongodb-org
sudo systemctl start mongod
sudo systemctl enable mongod

# Nginx
log_info "Installing Nginx..."
sudo apt install -y nginx
sudo systemctl start nginx
sudo systemctl enable nginx

# Ollama
log_info "Installing Ollama..."
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl start ollama
sudo systemctl enable ollama

# Chrome & dependencies
log_info "Installing Chrome and dependencies..."
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y \
    ./google-chrome-stable_current_amd64.deb \
    xvfb \
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils
rm google-chrome-stable_current_amd64.deb

# Git
sudo apt install -y git

################################################################################
# Step 3: Setup Xvfb Service
################################################################################
log_info "Step 3/10: Setting up Xvfb (virtual display)..."
sudo tee /etc/systemd/system/xvfb.service > /dev/null <<EOF
[Unit]
Description=X Virtual Frame Buffer Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24
Restart=always
User=$USER

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl start xvfb
sudo systemctl enable xvfb

################################################################################
# Step 4: Clone Repository
################################################################################
log_info "Step 4/10: Cloning LensAI repository..."
cd ~
if [ -d "lensai-meeting_Summariser" ]; then
    log_warn "Repository already exists. Pulling latest changes..."
    cd lensai-meeting_Summariser
    git pull origin main
    cd ~
else
    git clone https://github.com/ak4014263-cell/lensai-meeting_Summariser.git
fi

################################################################################
# Step 5: Setup Backend
################################################################################
log_info "Step 5/10: Setting up backend..."
cd ~/lensai-meeting_Summariser/backend

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Create .env file
log_info "Creating backend .env file..."
cat > .env <<EOF
# MongoDB
MONGODB_URL=mongodb://localhost:27017
MONGO_DB_NAME=lensai_production

# Ollama
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=llama3:latest

# Bot Configuration
BOT_DISPLAY_NAME=LensAI Notetaker
BOT_HEADLESS=false
BOT_USER_DATA_DIR=$HOME/lensai-meeting_Summariser/backend/.bot_profile

# Google OAuth
GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI=https://$DOMAIN_NAME/integrations/google/callback

# Frontend URL
FRONTEND_BASE_URL=https://$DOMAIN_NAME

# HuggingFace Token
HUGGINGFACE_TOKEN=$HUGGINGFACE_TOKEN

# Speech-to-Text
STT_BACKEND=advanced
WHISPER_MODEL=large-v3
ENABLE_SPEAKER_DIARIZATION=true
ENABLE_SPEAKER_MAPPING=true

# Display for Chrome
DISPLAY=:99

# Bot Behavior
BOT_ALONE_GRACE_SECONDS=30
BOT_WAIT_FOR_PEOPLE=120
BOT_POLL_SECONDS=5
EOF

deactivate

################################################################################
# Step 6: Setup Frontend
################################################################################
log_info "Step 6/10: Setting up frontend..."
cd ~/lensai-meeting_Summariser/frontend

# Install dependencies
npm install

# Create .env.local
cat > .env.local <<EOF
NEXT_PUBLIC_API_URL=https://$DOMAIN_NAME/api
EOF

# Build production version
npm run build

################################################################################
# Step 7: Pull Ollama Model
################################################################################
log_info "Step 7/10: Pulling Ollama llama3 model (this may take a while)..."
ollama pull llama3:latest

################################################################################
# Step 8: Create Systemd Services
################################################################################
log_info "Step 8/10: Creating systemd services..."

# Backend service
sudo tee /etc/systemd/system/lensai-backend.service > /dev/null <<EOF
[Unit]
Description=LensAI Backend API
After=network.target mongod.service ollama.service xvfb.service
Requires=mongod.service ollama.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/lensai-meeting_Summariser/backend
Environment="PATH=$HOME/lensai-meeting_Summariser/backend/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="DISPLAY=:99"
ExecStart=$HOME/lensai-meeting_Summariser/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Frontend service
sudo tee /etc/systemd/system/lensai-frontend.service > /dev/null <<EOF
[Unit]
Description=LensAI Frontend (Next.js)
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/lensai-meeting_Summariser/frontend
Environment="PATH=/usr/bin:/bin"
Environment="NODE_ENV=production"
Environment="PORT=3000"
ExecStart=/usr/bin/npm start
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Reload and enable services
sudo systemctl daemon-reload
sudo systemctl enable lensai-backend
sudo systemctl enable lensai-frontend

################################################################################
# Step 9: Configure Nginx
################################################################################
log_info "Step 9/10: Configuring Nginx..."

sudo tee /etc/nginx/sites-available/lensai > /dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN_NAME;

    client_max_body_size 100M;

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # WebSocket for chat
    location /ws/ {
        proxy_pass http://127.0.0.1:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 86400;
    }

    # Frontend
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/lensai /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

################################################################################
# Step 10: Setup SSL with Let's Encrypt
################################################################################
log_info "Step 10/10: Setting up SSL certificate..."

sudo apt install -y certbot python3-certbot-nginx

log_info "Obtaining SSL certificate for $DOMAIN_NAME..."
sudo certbot --nginx -d $DOMAIN_NAME --non-interactive --agree-tos --email $SSL_EMAIL --redirect

################################################################################
# Start Services
################################################################################
log_info "Starting LensAI services..."
sudo systemctl start lensai-backend
sudo systemctl start lensai-frontend

# Wait for services to start
sleep 5

# Check service status
log_info "Checking service status..."
sudo systemctl status lensai-backend --no-pager -l
sudo systemctl status lensai-frontend --no-pager -l

################################################################################
# Setup Firewall
################################################################################
log_info "Configuring firewall..."
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable

################################################################################
# Setup Database
################################################################################
log_info "Initializing database..."
cd ~/lensai-meeting_Summariser/backend
source venv/bin/activate
python create_all_tables.py 2>/dev/null || log_warn "Database tables may already exist"
deactivate

################################################################################
# Done!
################################################################################
echo ""
echo "================================================"
echo "  🎉 Deployment Complete!"
echo "================================================"
echo ""
log_info "LensAI is now deployed and running!"
echo ""
echo "🌐 Access your application at: https://$DOMAIN_NAME"
echo ""
echo "📋 Next Steps:"
echo "  1. Setup bot Google account:"
echo "     cd ~/lensai-meeting_Summariser/backend"
echo "     source venv/bin/activate"
echo "     DISPLAY=:99 python setup_bot_login.py"
echo ""
echo "  2. View logs:"
echo "     sudo journalctl -u lensai-backend -f"
echo "     sudo journalctl -u lensai-frontend -f"
echo ""
echo "  3. Check status:"
echo "     sudo systemctl status lensai-backend lensai-frontend"
echo ""
echo "  4. Update application:"
echo "     cd ~/lensai-meeting_Summariser"
echo "     git pull origin main"
echo "     sudo systemctl restart lensai-backend lensai-frontend"
echo ""
echo "================================================"
echo ""
