#!/bin/bash

################################################################################
# LensAI Enterprise Deployment: 100 Concurrent Meetings
# 
# Optimized for high-performance servers (32+ cores, 256GB RAM)
# 
# Usage: 
#   wget https://raw.githubusercontent.com/ak4014263-cell/lensai-meeting_Summariser/main/deploy-enterprise-100.sh
#   chmod +x deploy-enterprise-100.sh
#   ./deploy-enterprise-100.sh
################################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

log_enterprise() {
    echo -e "${BLUE}[ENTERPRISE]${NC} $1"
}

# Banner
clear
echo "========================================================"
echo "  🏢 LensAI Enterprise Deployment"
echo "  100 Concurrent Meetings Configuration"
echo "========================================================"
echo ""
log_enterprise "This deployment is optimized for:"
echo "  • 32+ CPU cores"
echo "  • 256GB+ RAM"
echo "  • 100 simultaneous meeting bots"
echo "  • Production-grade performance"
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

log_info "Starting enterprise deployment..."
sleep 2

################################################################################
# System Update & Optimization
################################################################################
log_info "Updating system packages..."
sudo apt update && sudo apt upgrade -y

log_enterprise "Configuring system for 100 concurrent meetings..."

# Kernel optimization for high concurrency
log_info "Optimizing kernel parameters..."
sudo tee -a /etc/sysctl.conf > /dev/null <<EOF

# LensAI Enterprise: 100 Concurrent Meetings Optimization
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_probes = 5
net.ipv4.tcp_keepalive_intvl = 15

# Memory management
vm.swappiness = 10
vm.vfs_cache_pressure = 50
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
vm.overcommit_memory = 1

# File descriptors
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 1024
EOF

sudo sysctl -p

# Increase system limits
log_info "Increasing system resource limits..."
sudo tee /etc/security/limits.d/lensai.conf > /dev/null <<EOF
# LensAI Enterprise Resource Limits
*               soft    nofile          500000
*               hard    nofile          500000
*               soft    nproc           500000
*               hard    nproc           500000
*               soft    memlock         unlimited
*               hard    memlock         unlimited
root            soft    nofile          500000
root            hard    nofile          500000
root            soft    nproc           500000
root            hard    nproc           500000
EOF

################################################################################
# Install Dependencies
################################################################################
log_info "Installing core dependencies..."

# Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Python 3.11
sudo apt install -y python3.11 python3.11-venv python3-pip build-essential

# MongoDB
log_info "Installing MongoDB..."
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
   sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \
   sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt update
sudo apt install -y mongodb-org

# MongoDB optimization for high concurrency
log_enterprise "Optimizing MongoDB for 100+ concurrent connections..."
sudo tee /etc/mongod.conf > /dev/null <<'MONGOEOF'
storage:
  dbPath: /var/lib/mongodb
  journal:
    enabled: true
  wiredTiger:
    engineConfig:
      cacheSizeGB: 80
      journalCompressor: snappy
      directoryForIndexes: true
    collectionConfig:
      blockCompressor: snappy
    indexConfig:
      prefixCompression: true

systemLog:
  destination: file
  logAppend: true
  path: /var/log/mongodb/mongod.log
  verbosity: 0

net:
  port: 27017
  bindIp: 0.0.0.0
  maxIncomingConnections: 5000

processManagement:
  timeZoneInfo: /usr/share/zoneinfo

operationProfiling:
  mode: slowOp
  slowOpThresholdMs: 100

setParameter:
  enableLocalhostAuthBypass: true
MONGOEOF

sudo systemctl start mongod
sudo systemctl enable mongod

# Nginx
log_info "Installing Nginx..."
sudo apt install -y nginx

# Nginx optimization
sudo tee /etc/nginx/nginx.conf > /dev/null <<'NGINXCONF'
user www-data;
worker_processes auto;
worker_rlimit_nofile 100000;
pid /run/nginx.pid;

events {
    worker_connections 10000;
    use epoll;
    multi_accept on;
}

http {
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    keepalive_requests 1000;
    types_hash_max_size 2048;
    server_tokens off;

    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;

    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml text/javascript application/json application/javascript application/xml+rss;

    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
NGINXCONF

# Ollama
log_info "Installing Ollama..."
curl -fsSL https://ollama.com/install.sh | sh

# Ollama optimization for parallel processing
log_enterprise "Configuring Ollama for parallel AI processing..."
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null <<EOF
[Service]
Environment="OLLAMA_NUM_PARALLEL=8"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
Environment="OLLAMA_KEEP_ALIVE=24h"
Environment="OLLAMA_ORIGINS=*"
EOF

sudo systemctl daemon-reload
sudo systemctl start ollama
sudo systemctl enable ollama

# Chrome & Xvfb
log_info "Installing Google Chrome and Xvfb..."
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y \
    ./google-chrome-stable_current_amd64.deb \
    xvfb fonts-liberation libappindicator3-1 \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 \
    libnss3 libwayland-client0 libxcomposite1 libxdamage1 \
    libxfixes3 libxkbcommon0 libxrandr2 xdg-utils
rm google-chrome-stable_current_amd64.deb

# Git & monitoring tools
sudo apt install -y git htop iotop nethogs

################################################################################
# Setup Xvfb (Virtual Display)
################################################################################
log_info "Configuring virtual display for 100 bots..."
sudo tee /etc/systemd/system/xvfb.service > /dev/null <<EOF
[Unit]
Description=X Virtual Frame Buffer Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24 -ac
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
log_info "Cloning LensAI repository..."
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
log_info "Setting up backend for 100 concurrent meetings..."
cd ~/lensai-meeting_Summariser/backend

python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium

# Enterprise backend .env
log_enterprise "Configuring enterprise environment variables..."
cat > .env <<EOF
# ═══════════════════════════════════════════════════════════
# LENSAI ENTERPRISE: 100 CONCURRENT MEETINGS
# ═══════════════════════════════════════════════════════════

# ── Database ──────────────────────────────────────────────
MONGODB_URL=mongodb://localhost:27017
MONGO_DB_NAME=lensai_production

# ── LLM Configuration ─────────────────────────────────────
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=llama3:latest
OLLAMA_TIMEOUT=600
OLLAMA_NUM_CTX=8192
OLLAMA_TEMPERATURE=0.2
OLLAMA_NUM_PARALLEL=8
OLLAMA_MAX_LOADED_MODELS=2

# ── Bot Configuration (ENTERPRISE: 100 MEETINGS) ─────────
BOT_DISPLAY_NAME=LensAI Notetaker
BOT_MAX_CONCURRENT=100
BOT_HEADLESS=false
BOT_USER_DATA_DIR=$HOME/lensai-meeting_Summariser/backend/.bot_profile
BOT_ALONE_GRACE_SECONDS=15
BOT_WAIT_FOR_PEOPLE=60
BOT_POLL_SECONDS=3

# ── Google OAuth ──────────────────────────────────────────
GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI=https://$DOMAIN_NAME$BASE_PATH/integrations/google/callback

# ── Frontend ──────────────────────────────────────────────
FRONTEND_BASE_URL=https://$DOMAIN_NAME$BASE_PATH

# ── HuggingFace ───────────────────────────────────────────
HUGGINGFACE_TOKEN=$HUGGINGFACE_TOKEN

# ── Speech-to-Text (OPTIMIZED FOR SPEED) ─────────────────
STT_BACKEND=advanced
WHISPER_MODEL=base
WHISPER_BEAM_SIZE=1
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8

# ── Speaker Recognition ───────────────────────────────────
ENABLE_SPEAKER_DIARIZATION=false
ENABLE_SPEAKER_MAPPING=true
NUM_SPEAKERS=0

# ── Performance Optimization ──────────────────────────────
LLM_CHUNK_CHARS=16000
LLM_CHUNK_OVERLAP_CHARS=1000
LLM_MAX_CHUNKS=50

# ── System ────────────────────────────────────────────────
DISPLAY=:99
BOT_POST_CALL_DELAY=5

# ── Email Notifications ───────────────────────────────────
SEND_EMAIL_NOTIFICATIONS=false
EOF

deactivate

################################################################################
# Setup Frontend
################################################################################
log_info "Setting up frontend..."
cd ~/lensai-meeting_Summariser/frontend

npm install

cat > .env.local <<EOF
NEXT_PUBLIC_API_URL=https://$DOMAIN_NAME$BASE_PATH/api
NEXT_PUBLIC_BASE_PATH=$BASE_PATH
EOF

log_info "Building frontend for production..."
npm run build

################################################################################
# Pull Ollama Models
################################################################################
log_info "Pulling AI models (this may take 5-10 minutes)..."
ollama pull llama3:latest

################################################################################
# Create Systemd Services (ENTERPRISE)
################################################################################
log_enterprise "Creating enterprise systemd services..."

# Backend with 16 API workers
sudo tee /etc/systemd/system/lensai-backend.service > /dev/null <<EOF
[Unit]
Description=LensAI Backend API - Enterprise (100 meetings)
After=network.target mongod.service ollama.service xvfb.service
Requires=mongod.service ollama.service xvfb.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/lensai-meeting_Summariser/backend
Environment="PATH=$HOME/lensai-meeting_Summariser/backend/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="DISPLAY=:99"
ExecStart=$HOME/lensai-meeting_Summariser/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 16 --timeout-keep-alive 300 --limit-concurrency 10000
Restart=always
RestartSec=10
LimitNOFILE=500000
LimitNPROC=500000

[Install]
WantedBy=multi-user.target
EOF

# Frontend
sudo tee /etc/systemd/system/lensai-frontend.service > /dev/null <<EOF
[Unit]
Description=LensAI Frontend - Enterprise
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
LimitNOFILE=100000

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable lensai-backend lensai-frontend

################################################################################
# Configure Nginx
################################################################################
log_info "Configuring Nginx for enterprise traffic..."

sudo tee /etc/nginx/sites-available/lenss-ai > /dev/null <<'NGINXSITE'
upstream lensai_backend {
    least_conn;
    server 127.0.0.1:8000 max_fails=3 fail_timeout=30s;
    keepalive 512;
}

server {
    listen 80;
    server_name lenss.ai www.lenss.ai;

    client_max_body_size 500M;
    client_body_timeout 300s;
    
    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=100r/s;
    limit_conn_zone $binary_remote_addr zone=addr:10m;

    location = / {
        return 301 https://lenss.ai/ai;
    }

    location /ai/api/ {
        limit_req zone=api burst=200 nodelay;
        limit_conn addr 100;
        
        rewrite ^/ai/api/(.*) /$1 break;
        proxy_pass http://lensai_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_connect_timeout 75s;
        proxy_send_timeout 600s;
        proxy_buffering off;
    }

    location /ai/ws/ {
        rewrite ^/ai/ws/(.*) /ws/$1 break;
        proxy_pass http://lensai_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400;
    }

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
NGINXSITE

sudo ln -sf /etc/nginx/sites-available/lenss-ai /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

################################################################################
# Setup SSL
################################################################################
log_info "Setting up SSL certificate..."
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d lenss.ai -d www.lenss.ai --non-interactive --agree-tos --email $SSL_EMAIL --redirect

################################################################################
# Start Services
################################################################################
log_info "Starting all services..."
sudo systemctl start lensai-backend lensai-frontend

sleep 5

################################################################################
# Firewall
################################################################################
log_info "Configuring firewall..."
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
# Create Monitoring Script
################################################################################
log_enterprise "Setting up monitoring tools..."

sudo tee /usr/local/bin/lensai-monitor > /dev/null <<'MONITOR'
#!/bin/bash

echo "========================================"
echo "  LensAI Enterprise Monitor"
echo "========================================"
echo ""

# Active meetings
MEETINGS=$(ps aux | grep chrome | grep "meeting-bot-" | wc -l)
echo "📊 Active Meetings: $MEETINGS / 100"

# CPU
CPU=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
echo "💻 CPU Usage: ${CPU}%"

# Memory
MEM=$(free | grep Mem | awk '{printf("%.1f"), $3/$2 * 100.0}')
echo "🧠 Memory Usage: ${MEM}%"

# Disk
DISK=$(df -h / | awk 'NR==2{print $5}')
echo "💾 Disk Usage: $DISK"

# Services
echo ""
echo "Services Status:"
systemctl is-active --quiet lensai-backend && echo "  ✅ Backend: Running" || echo "  ❌ Backend: Stopped"
systemctl is-active --quiet lensai-frontend && echo "  ✅ Frontend: Running" || echo "  ❌ Frontend: Stopped"
systemctl is-active --quiet mongod && echo "  ✅ MongoDB: Running" || echo "  ❌ MongoDB: Stopped"
systemctl is-active --quiet ollama && echo "  ✅ Ollama: Running" || echo "  ❌ Ollama: Stopped"

echo ""
echo "========================================"
MONITOR

sudo chmod +x /usr/local/bin/lensai-monitor

################################################################################
# Done
################################################################################
clear
echo ""
echo "========================================================"
echo "  🎉 ENTERPRISE DEPLOYMENT COMPLETE!"
echo "========================================================"
echo ""
log_enterprise "LensAI is configured for 100 concurrent meetings!"
echo ""
echo "📍 Application URL: https://lenss.ai/ai"
echo "📊 Capacity: 100 simultaneous meetings"
echo "💻 API Workers: 16"
echo "🤖 Bot Max Concurrent: 100"
echo ""
echo "========================================================"
echo "📋 NEXT STEPS:"
echo "========================================================"
echo ""
echo "1️⃣  Setup Bot Google Account:"
echo "   cd ~/lensai-meeting_Summariser/backend"
echo "   source venv/bin/activate"
echo "   DISPLAY=:99 python setup_bot_login.py"
echo ""
echo "2️⃣  Monitor System:"
echo "   lensai-monitor"
echo ""
echo "3️⃣  View Logs:"
echo "   sudo journalctl -u lensai-backend -f"
echo ""
echo "4️⃣  Check Active Meetings:"
echo "   curl https://lenss.ai/ai/api/meetings/active | jq ."
echo ""
echo "5️⃣  Update Google OAuth:"
echo "   https://lenss.ai/ai/integrations/google/callback"
echo ""
echo "========================================================"
echo "⚙️  PERFORMANCE TIPS:"
echo "========================================================"
echo ""
echo "• Monitor with: lensai-monitor"
echo "• View resources: htop"
echo "• Active bots: ps aux | grep chrome | wc -l"
echo "• If slow, switch to Whisper 'tiny' model in .env"
echo "• Scale horizontally with multiple worker servers"
echo ""
echo "========================================================"
echo "🚀 Ready for enterprise-scale meeting transcription!"
echo "========================================================"
echo ""
