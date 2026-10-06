#!/bin/bash

################################################################################
# LensAI Meeting Assistant - lenss.ai Deployment Script
# 
# Deploys LensAI to lenss.ai/ai subdirectory
# 
# Usage: 
#   wget https://raw.githubusercontent.com/ak4014263-cell/lensai-meeting_Summariser/main/deploy-lenss-ai.sh
#   chmod +x deploy-lenss-ai.sh
#   ./deploy-lenss-ai.sh
################################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Banner
echo "================================================"
echo "  LensAI Deployment for lenss.ai/ai"
echo "================================================"
echo ""

# Pre-configured domain
DOMAIN_NAME="lenss.ai"
BASE_PATH="/ai"

log_info "Deploying to: https://${DOMAIN_NAME}${BASE_PATH}"
echo ""

# Get configuration
read -p "Enter your email for SSL certificate: " SSL_EMAIL
read -p "Enter your Google OAuth Client ID: " GOOGLE_CLIENT_ID
read -sp "Enter your Google OAuth Client Secret: " GOOGLE_CLIENT_SECRET
echo ""
read -p "Enter your HuggingFace Token: " HUGGINGFACE_TOKEN

log_info "Starting deployment..."

################################################################################
# System Update
################################################################################
log_info "Updating system..."
sudo apt update && sudo apt upgrade -y

################################################################################
# Install Dependencies
################################################################################
log_info "Installing dependencies..."

# Node.js
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Python
sudo apt install -y python3.11 python3.11-venv python3-pip

# MongoDB
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
   sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \
   sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt update
sudo apt install -y mongodb-org
sudo systemctl start mongod
sudo systemctl enable mongod

# Nginx
sudo apt install -y nginx

# Ollama
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl start ollama
sudo systemctl enable ollama

# Chrome & Xvfb
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y \
    ./google-chrome-stable_current_amd64.deb \
    xvfb fonts-liberation libappindicator3-1 \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 \
    libnss3 libwayland-client0 libxcomposite1 libxdamage1 \
    libxfixes3 libxkbcommon0 libxrandr2 xdg-utils
rm google-chrome-stable_current_amd64.deb

# Git
sudo apt install -y git

################################################################################
# Setup Xvfb
################################################################################
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
# Clone Repository
################################################################################
log_info "Cloning repository..."
cd ~
if [ -d "lensai-meeting_Summariser" ]; then
    cd lensai-meeting_Summariser
    git pull origin main
    cd ~
else
    git clone https://github.com/ak4014263-cell/lensai-meeting_Summariser.git
fi

################################################################################
# Setup Backend
################################################################################
log_info "Setting up backend..."
cd ~/lensai-meeting_Summariser/backend

python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium

# Backend .env
cat > .env <<EOF
MONGODB_URL=mongodb://localhost:27017
MONGO_DB_NAME=lensai_production

OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=llama3:latest

BOT_DISPLAY_NAME=LensAI Notetaker
BOT_HEADLESS=false
BOT_USER_DATA_DIR=$HOME/lensai-meeting_Summariser/backend/.bot_profile

GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI=https://$DOMAIN_NAME$BASE_PATH/integrations/google/callback

FRONTEND_BASE_URL=https://$DOMAIN_NAME$BASE_PATH

HUGGINGFACE_TOKEN=$HUGGINGFACE_TOKEN

STT_BACKEND=advanced
WHISPER_MODEL=large-v3
ENABLE_SPEAKER_DIARIZATION=true
ENABLE_SPEAKER_MAPPING=true

DISPLAY=:99
BOT_ALONE_GRACE_SECONDS=30
EOF

deactivate

################################################################################
# Setup Frontend
################################################################################
log_info "Setting up frontend..."
cd ~/lensai-meeting_Summariser/frontend

npm install

# Frontend .env.local with base path
cat > .env.local <<EOF
NEXT_PUBLIC_API_URL=https://$DOMAIN_NAME$BASE_PATH/api
NEXT_PUBLIC_BASE_PATH=$BASE_PATH
EOF

# Update next.config.ts for base path
cat > next.config.ts <<'NEXTCONFIG'
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  basePath: '/ai',
  assetPrefix: '/ai',
  output: 'standalone',
  experimental: {
    turbo: {
      loaders: {},
    },
  },
};

export default nextConfig;
NEXTCONFIG

npm run build

################################################################################
# Pull Ollama Model
################################################################################
log_info "Pulling llama3 model..."
ollama pull llama3:latest

################################################################################
# Create Systemd Services
################################################################################
log_info "Creating services..."

# Backend
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
ExecStart=$HOME/lensai-meeting_Summariser/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Frontend
sudo tee /etc/systemd/system/lensai-frontend.service > /dev/null <<EOF
[Unit]
Description=LensAI Frontend
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

sudo systemctl daemon-reload
sudo systemctl enable lensai-backend lensai-frontend

################################################################################
# Configure Nginx for lenss.ai/ai
################################################################################
log_info "Configuring Nginx..."

sudo tee /etc/nginx/sites-available/lenss-ai > /dev/null <<'NGINXCONF'
server {
    listen 80;
    server_name lenss.ai www.lenss.ai;

    client_max_body_size 100M;

    # Root site redirect to /ai
    location = / {
        return 301 https://lenss.ai/ai;
    }

    # LensAI Backend API at /ai/api
    location /ai/api/ {
        rewrite ^/ai/api/(.*) /$1 break;
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # WebSocket at /ai/ws
    location /ai/ws/ {
        rewrite ^/ai/ws/(.*) /ws/$1 break;
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400;
    }

    # Frontend at /ai
    location /ai {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ai/ {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINXCONF

sudo ln -sf /etc/nginx/sites-available/lenss-ai /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

################################################################################
# Setup SSL
################################################################################
log_info "Setting up SSL..."
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d lenss.ai -d www.lenss.ai --non-interactive --agree-tos --email $SSL_EMAIL --redirect

################################################################################
# Start Services
################################################################################
log_info "Starting services..."
sudo systemctl start lensai-backend lensai-frontend

sleep 5

################################################################################
# Firewall
################################################################################
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable

################################################################################
# Initialize Database
################################################################################
log_info "Initializing database..."
cd ~/lensai-meeting_Summariser/backend
source venv/bin/activate
python create_all_tables.py 2>/dev/null || true
deactivate

################################################################################
# Done
################################################################################
echo ""
echo "================================================"
echo "  🎉 Deployment Complete!"
echo "================================================"
echo ""
log_info "LensAI is deployed at: https://lenss.ai/ai"
echo ""
echo "📋 Next Steps:"
echo "  1. Setup bot Google account:"
echo "     cd ~/lensai-meeting_Summariser/backend"
echo "     source venv/bin/activate"
echo "     DISPLAY=:99 python setup_bot_login.py"
echo ""
echo "  2. Access application: https://lenss.ai/ai"
echo ""
echo "  3. View logs:"
echo "     sudo journalctl -u lensai-backend -f"
echo ""
echo "  4. Google OAuth Redirect URI:"
echo "     https://lenss.ai/ai/integrations/google/callback"
echo ""
echo "================================================"
