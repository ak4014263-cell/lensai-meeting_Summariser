# LensAI Meeting Assistant - VPS Deployment Guide

Complete guide to deploy LensAI Meeting Assistant on a VPS (DigitalOcean, Linode, Vultr, Hostinger KVM, etc.)

## Table of Contents
1. [VPS Requirements](#vps-requirements)
2. [Pre-deployment Checklist](#pre-deployment-checklist)
3. [Step-by-Step Deployment](#step-by-step-deployment)
4. [Configuration](#configuration)
5. [SSL Setup](#ssl-setup)
6. [Monitoring & Maintenance](#monitoring--maintenance)
7. [Troubleshooting](#troubleshooting)

---

## VPS Requirements

### Minimum Specifications
- **CPU:** 4 cores (recommended 8 cores for production)
- **RAM:** 8 GB (recommended 16 GB)
- **Storage:** 50 GB SSD (recommended 100 GB)
- **OS:** Ubuntu 22.04 LTS or Ubuntu 24.04 LTS
- **Network:** 100 Mbps+ bandwidth

### Recommended VPS Providers
1. **Hostinger KVM 4** ($35-45/month)
   - 4 vCPU, 16GB RAM, 200GB SSD
   - Good for production

2. **DigitalOcean Droplet** ($48/month)
   - 4 vCPU, 8GB RAM, 160GB SSD
   - Easy setup, great documentation

3. **Vultr High Frequency** ($48/month)
   - 4 vCPU, 16GB RAM, 320GB SSD
   - Better CPU performance

4. **Linode Dedicated 8GB** ($36/month)
   - 4 vCPU, 8GB RAM, 160GB SSD
   - Reliable, good support

### Why These Specs?
- **Whisper large-v3:** Needs 4-6 GB RAM
- **Ollama llama3:** Needs 4-8 GB RAM
- **MongoDB + Services:** 2-4 GB RAM
- **Chrome Browser (bot):** 1-2 GB RAM
- **Node.js Frontend:** 512 MB - 1 GB RAM

---

## Pre-deployment Checklist

### Domain Setup
- [ ] Domain name purchased (e.g., `lensai.yourdomain.com`)
- [ ] DNS A record pointing to your VPS IP
- [ ] Wait 10-30 minutes for DNS propagation

### Required Accounts/Keys
- [ ] GitHub account with access to repository
- [ ] Google OAuth credentials (for Google Meet integration)
- [ ] Google Cloud Project with Calendar API enabled
- [ ] HuggingFace token (for Whisper & diarization)
- [ ] SSL certificate (Let's Encrypt - free)

### Local Preparation
- [ ] Update `.env` files with production settings
- [ ] Test application locally
- [ ] Commit all changes to GitHub

---

## Step-by-Step Deployment

### Step 1: Initial VPS Setup

#### 1.1 Connect to VPS
```bash
ssh root@YOUR_VPS_IP
```

#### 1.2 Update System
```bash
apt update && apt upgrade -y
```

#### 1.3 Create Non-Root User
```bash
adduser lensai
usermod -aG sudo lensai
```

#### 1.4 Setup Firewall
```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

#### 1.5 Switch to New User
```bash
su - lensai
```

---

### Step 2: Install Dependencies

#### 2.1 Install Node.js 20.x
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version  # Should be v20.x
npm --version
```

#### 2.2 Install Python 3.11+
```bash
sudo apt install -y python3.11 python3.11-venv python3-pip
python3.11 --version
```

#### 2.3 Install MongoDB
```bash
# Import MongoDB GPG key
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
   sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg \
   --dearmor

# Add MongoDB repository
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \
   sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list

# Install MongoDB
sudo apt update
sudo apt install -y mongodb-org

# Start MongoDB
sudo systemctl start mongod
sudo systemctl enable mongod
sudo systemctl status mongod
```

#### 2.4 Install Nginx
```bash
sudo apt install -y nginx
sudo systemctl start nginx
sudo systemctl enable nginx
```

#### 2.5 Install Ollama
```bash
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama service
sudo systemctl start ollama
sudo systemctl enable ollama

# Pull llama3 model
ollama pull llama3:latest
```

#### 2.6 Install Chrome & Dependencies (for Meeting Bot)
```bash
# Install Chrome dependencies
sudo apt install -y \
    wget \
    gnupg \
    ca-certificates \
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

# Install Google Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb
sudo apt --fix-broken install -y

# Install Xvfb (virtual display for headless Chrome)
sudo apt install -y xvfb

# Create Xvfb service
sudo tee /etc/systemd/system/xvfb.service > /dev/null <<EOF
[Unit]
Description=X Virtual Frame Buffer Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24
Restart=always
User=lensai

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl start xvfb
sudo systemctl enable xvfb
```

---

### Step 3: Clone and Setup Application

#### 3.1 Clone Repository
```bash
cd ~
git clone https://github.com/ak4014263-cell/lensai-meeting_Summariser.git
cd lensai-meeting_Summariser
```

#### 3.2 Setup Backend
```bash
cd backend

# Create Python virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Copy and configure .env
cp .env.example .env
nano .env  # Edit with your production settings
```

**Backend .env Configuration:**
```bash
# MongoDB
MONGODB_URL=mongodb://localhost:27017
MONGO_DB_NAME=lensai_production

# Ollama
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=llama3:latest

# Bot Configuration
BOT_DISPLAY_NAME=LensAI Notetaker
BOT_HEADLESS=false
BOT_USER_DATA_DIR=/home/lensai/lensai-meeting_Summariser/backend/.bot_profile

# Google OAuth (YOUR CREDENTIALS)
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=https://lensai.yourdomain.com/integrations/google/callback

# Frontend URL
FRONTEND_BASE_URL=https://lensai.yourdomain.com

# HuggingFace Token
HUGGINGFACE_TOKEN=hf_your_token_here

# Speech-to-Text
STT_BACKEND=advanced
WHISPER_MODEL=large-v3
ENABLE_SPEAKER_DIARIZATION=true
ENABLE_SPEAKER_MAPPING=true

# Display for Chrome
DISPLAY=:99
```

#### 3.3 Setup Frontend
```bash
cd ~/lensai-meeting_Summariser/frontend

# Install dependencies
npm install

# Create .env.local
cat > .env.local <<EOF
NEXT_PUBLIC_API_URL=https://lensai.yourdomain.com/api
EOF

# Build production version
npm run build
```

---

### Step 4: Create Systemd Services

#### 4.1 Backend Service
```bash
sudo tee /etc/systemd/system/lensai-backend.service > /dev/null <<EOF
[Unit]
Description=LensAI Backend API
After=network.target mongod.service ollama.service xvfb.service
Requires=mongod.service ollama.service

[Service]
Type=simple
User=lensai
WorkingDirectory=/home/lensai/lensai-meeting_Summariser/backend
Environment="PATH=/home/lensai/lensai-meeting_Summariser/backend/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="DISPLAY=:99"
ExecStart=/home/lensai/lensai-meeting_Summariser/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

#### 4.2 Frontend Service
```bash
sudo tee /etc/systemd/system/lensai-frontend.service > /dev/null <<EOF
[Unit]
Description=LensAI Frontend (Next.js)
After=network.target

[Service]
Type=simple
User=lensai
WorkingDirectory=/home/lensai/lensai-meeting_Summariser/frontend
Environment="PATH=/usr/bin:/bin"
Environment="NODE_ENV=production"
Environment="PORT=3000"
ExecStart=/usr/bin/npm start
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

#### 4.3 Enable and Start Services
```bash
sudo systemctl daemon-reload
sudo systemctl enable lensai-backend
sudo systemctl enable lensai-frontend
sudo systemctl start lensai-backend
sudo systemctl start lensai-frontend

# Check status
sudo systemctl status lensai-backend
sudo systemctl status lensai-frontend
```

---

### Step 5: Configure Nginx Reverse Proxy

#### 5.1 Create Nginx Configuration
```bash
sudo tee /etc/nginx/sites-available/lensai <<EOF
server {
    listen 80;
    server_name lensai.yourdomain.com;

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
```

#### 5.2 Enable Site
```bash
sudo ln -s /etc/nginx/sites-available/lensai /etc/nginx/sites-enabled/
sudo nginx -t  # Test configuration
sudo systemctl restart nginx
```

---

### Step 6: Setup SSL with Let's Encrypt

#### 6.1 Install Certbot
```bash
sudo apt install -y certbot python3-certbot-nginx
```

#### 6.2 Obtain SSL Certificate
```bash
sudo certbot --nginx -d lensai.yourdomain.com
```

Follow prompts:
- Enter email address
- Agree to terms
- Choose to redirect HTTP to HTTPS (recommended)

#### 6.3 Auto-renewal
```bash
# Test renewal
sudo certbot renew --dry-run

# Certbot auto-renewal is already configured via systemd timer
sudo systemctl status certbot.timer
```

---

### Step 7: Setup Bot Google Account

#### 7.1 Run Bot Setup (One-Time)
```bash
cd ~/lensai-meeting_Summariser/backend
source venv/bin/activate

# This will open a browser window (via Xvfb)
DISPLAY=:99 python setup_bot_login.py
```

**Note:** Since you're on a headless VPS, you have two options:

**Option A: Use SSH X11 Forwarding (Recommended)**
```bash
# From your local machine:
ssh -X lensai@YOUR_VPS_IP

# Then run:
cd ~/lensai-meeting_Summariser/backend
source venv/bin/activate
python setup_bot_login.py
```

**Option B: Use VNC**
```bash
# Install VNC server on VPS
sudo apt install -y tightvncserver

# Start VNC (as lensai user)
vncserver :1

# Connect via VNC client from local machine
# Then run setup_bot_login.py in the VNC session
```

**Option C: Setup on Local Machine**
1. Run `setup_bot_login.py` on your local Windows/Mac machine
2. Copy the `.bot_profile` folder to VPS:
```bash
# From local machine:
scp -r backend/.bot_profile lensai@YOUR_VPS_IP:~/lensai-meeting_Summariser/backend/
```

#### 7.2 Verify Bot Profile
```bash
ls -la ~/lensai-meeting_Summariser/backend/.bot_profile
# Should contain browser profile files
```

---

## Configuration

### Database Initialization

#### Create Tables
```bash
cd ~/lensai-meeting_Summariser/backend
source venv/bin/activate

# Create all database tables
python create_all_tables.py
```

### Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable APIs:
   - Google Calendar API
   - Google Meet REST API (if available)
4. Create OAuth 2.0 credentials:
   - Application type: Web application
   - Authorized redirect URIs: `https://lensai.yourdomain.com/integrations/google/callback`
5. Copy Client ID and Client Secret to `.env`

### HuggingFace Token

1. Go to [HuggingFace](https://huggingface.co/)
2. Sign up/login
3. Go to Settings → Access Tokens
4. Create new token with read permissions
5. Copy to `.env` as `HUGGINGFACE_TOKEN`

---

## Monitoring & Maintenance

### Check Service Status
```bash
# All services
sudo systemctl status lensai-backend lensai-frontend mongod ollama nginx

# View logs
sudo journalctl -u lensai-backend -f
sudo journalctl -u lensai-frontend -f
```

### Monitor Resources
```bash
# Install htop
sudo apt install -y htop

# Monitor CPU, RAM, Disk
htop

# Check disk usage
df -h

# Check memory
free -h
```

### Backup Script
```bash
# Create backup directory
mkdir -p ~/backups

# Create backup script
cat > ~/backup.sh <<'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=~/backups

# Backup MongoDB
mongodump --out=$BACKUP_DIR/mongo_$DATE

# Backup application files
tar -czf $BACKUP_DIR/lensai_$DATE.tar.gz ~/lensai-meeting_Summariser

# Backup meeting storage
tar -czf $BACKUP_DIR/storage_$DATE.tar.gz ~/lensai-meeting_Summariser/backend/storage

# Keep only last 7 days
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete
find $BACKUP_DIR -name "mongo_*" -mtime +7 -exec rm -rf {} \;

echo "Backup completed: $DATE"
EOF

chmod +x ~/backup.sh

# Add to crontab (daily at 2 AM)
(crontab -l 2>/dev/null; echo "0 2 * * * ~/backup.sh") | crontab -
```

### Update Application
```bash
cd ~/lensai-meeting_Summariser

# Pull latest code
git pull origin main

# Update backend
cd backend
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart lensai-backend

# Update frontend
cd ../frontend
npm install
npm run build
sudo systemctl restart lensai-frontend
```

---

## Troubleshooting

### Backend Won't Start
```bash
# Check logs
sudo journalctl -u lensai-backend -n 100 --no-pager

# Common issues:
# 1. MongoDB not running
sudo systemctl status mongod
sudo systemctl start mongod

# 2. Ollama not running
sudo systemctl status ollama
sudo systemctl start ollama

# 3. Port already in use
sudo lsof -i :8000
# Kill process if needed

# 4. Python dependencies
cd ~/lensai-meeting_Summariser/backend
source venv/bin/activate
pip install -r requirements.txt
```

### Frontend Won't Start
```bash
# Check logs
sudo journalctl -u lensai-frontend -n 100 --no-pager

# Rebuild if needed
cd ~/lensai-meeting_Summariser/frontend
rm -rf .next
npm run build
sudo systemctl restart lensai-frontend
```

### Bot Can't Join Meetings
```bash
# Check Xvfb display
ps aux | grep Xvfb
sudo systemctl status xvfb

# Check Chrome installation
google-chrome --version

# Check bot profile
ls -la ~/lensai-meeting_Summariser/backend/.bot_profile

# Test manually
cd ~/lensai-meeting_Summariser/backend
source venv/bin/activate
DISPLAY=:99 python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); print('Playwright OK')"
```

### SSL Certificate Issues
```bash
# Renew certificate manually
sudo certbot renew

# Check certificate status
sudo certbot certificates

# Re-obtain if expired
sudo certbot --nginx -d lensai.yourdomain.com --force-renewal
```

### High Memory Usage
```bash
# Check what's using memory
ps aux --sort=-%mem | head -n 10

# Restart services to free memory
sudo systemctl restart lensai-backend
sudo systemctl restart lensai-frontend

# Consider upgrading VPS if consistently high
```

### MongoDB Issues
```bash
# Check MongoDB status
sudo systemctl status mongod

# View MongoDB logs
sudo tail -f /var/log/mongodb/mongod.log

# Repair if needed
sudo systemctl stop mongod
sudo mongod --repair
sudo systemctl start mongod
```

---

## Performance Optimization

### Enable Gzip Compression (Nginx)
```bash
sudo nano /etc/nginx/nginx.conf

# Add in http block:
gzip on;
gzip_vary on;
gzip_proxied any;
gzip_comp_level 6;
gzip_types text/plain text/css text/xml text/javascript application/json application/javascript application/xml+rss;

sudo systemctl restart nginx
```

### MongoDB Optimization
```bash
# Edit MongoDB config
sudo nano /etc/mongod.conf

# Add:
storage:
  wiredTiger:
    engineConfig:
      cacheSizeGB: 2  # Adjust based on RAM

sudo systemctl restart mongod
```

### PM2 Alternative (Optional)
If you prefer PM2 over systemd:
```bash
sudo npm install -g pm2

# Backend
cd ~/lensai-meeting_Summariser/backend
pm2 start "venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000" --name lensai-backend

# Frontend
cd ~/lensai-meeting_Summariser/frontend
pm2 start npm --name lensai-frontend -- start

# Save PM2 config
pm2 save
pm2 startup
```

---

## Security Hardening

### 1. Enable Firewall Rules
```bash
# Only allow necessary ports
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 2. Disable Root SSH
```bash
sudo nano /etc/ssh/sshd_config

# Set:
PermitRootLogin no

sudo systemctl restart sshd
```

### 3. Setup Fail2Ban
```bash
sudo apt install -y fail2ban

sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

### 4. Regular Updates
```bash
# Auto-update security patches
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

---

## Cost Estimation

### Monthly Costs (Example)
- **VPS (Hostinger KVM 4):** $40
- **Domain:** $1-2/month (amortized)
- **SSL:** Free (Let's Encrypt)
- **Backups (optional):** $5-10
- **Total:** ~$45-52/month

### Resource Usage (Typical)
- **CPU:** 20-40% average, 80%+ during meetings
- **RAM:** 6-10 GB average, 12-14 GB during meetings
- **Storage:** 20-50 GB (grows with recordings)
- **Bandwidth:** 50-200 GB/month

---

## Quick Start Commands

Once everything is set up:

```bash
# Start all services
sudo systemctl start lensai-backend lensai-frontend mongod ollama nginx xvfb

# Check all services
sudo systemctl status lensai-backend lensai-frontend mongod ollama nginx xvfb

# View logs
sudo journalctl -u lensai-backend -f
sudo journalctl -u lensai-frontend -f

# Access application
open https://lensai.yourdomain.com
```

---

## Support & Resources

- **GitHub Issues:** https://github.com/ak4014263-cell/lensai-meeting_Summariser/issues
- **Documentation:** Check README.md in repository
- **Deployment Script:** See `deploy/` folder for automated scripts

---

## Summary Checklist

- [ ] VPS purchased and configured
- [ ] Domain name configured with DNS
- [ ] All dependencies installed
- [ ] Application cloned and built
- [ ] Environment variables configured
- [ ] Systemd services created and running
- [ ] Nginx configured and running
- [ ] SSL certificate obtained and working
- [ ] Bot Google account set up
- [ ] MongoDB initialized
- [ ] Application accessible at https://lensai.yourdomain.com
- [ ] Test meeting recorded successfully
- [ ] Backups configured
- [ ] Monitoring set up

---

**Deployment Complete! 🎉**

Your LensAI Meeting Assistant is now live and ready for production use!
