# AWS Deployment Guide for AI Meeting Assistant
## Deploy to lensaibot.duckdns.org

## 📋 Prerequisites

### Local Requirements
- AWS CLI installed and configured
- Docker installed
- Git installed
- SSH key pair for AWS EC2

### AWS Account Requirements
- Active AWS account
- IAM user with appropriate permissions
- Credit card on file (for AWS services)

### Domain Setup
- DuckDNS account at https://www.duckdns.org
- Token from DuckDNS for lensaibot subdomain

---

## 🏗️ Architecture Overview

```
Internet
    ↓
[lensaibot.duckdns.org]
    ↓
AWS EC2 Instance (Ubuntu 22.04)
    ├── Nginx (Reverse Proxy with SSL)
    ├── Frontend (Next.js on Port 3000)
    ├── Backend (FastAPI on Port 8000)
    ├── MongoDB (Port 27017)
    ├── Ollama (LLM on Port 11434)
    └── Chrome (for bot meetings)
```

---

## 🚀 Deployment Steps

### Step 1: Launch EC2 Instance

**Instance Specifications:**
- **Instance Type:** `t3.xlarge` or larger (4 vCPU, 16 GB RAM minimum)
  - For better performance: `t3.2xlarge` (8 vCPU, 32 GB RAM)
- **OS:** Ubuntu Server 22.04 LTS
- **Storage:** 100 GB EBS (gp3 for better performance)
- **Security Group:** Create with these rules:

```
Inbound Rules:
- SSH (22) from Your IP
- HTTP (80) from 0.0.0.0/0
- HTTPS (443) from 0.0.0.0/0
- Custom TCP (3000) from 0.0.0.0/0 [temporary, for testing]
- Custom TCP (8000) from 0.0.0.0/0 [temporary, for testing]

Outbound Rules:
- All traffic to 0.0.0.0/0
```

**AWS CLI Command:**
```bash
aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \
  --instance-type t3.xlarge \
  --key-name YourKeyPair \
  --security-group-ids sg-xxxxxxxxx \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":100,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=AI-Meeting-Assistant}]'
```

### Step 2: Allocate Elastic IP

```bash
# Allocate Elastic IP
aws ec2 allocate-address --domain vpc

# Associate with instance
aws ec2 associate-address \
  --instance-id i-xxxxxxxxx \
  --allocation-id eipalloc-xxxxxxxxx
```

**Note the Elastic IP** - you'll use this with DuckDNS.

### Step 3: Configure DuckDNS

1. Go to https://www.duckdns.org
2. Log in with your account
3. Add/update `lensaibot` subdomain
4. Set the IPv4 address to your **Elastic IP**
5. Note your **DuckDNS token**

**Auto-update script (optional):**
```bash
# On EC2 instance, create cron job to update DuckDNS
echo "*/5 * * * * curl 'https://www.duckdns.org/update?domains=lensaibot&token=YOUR_TOKEN&ip=' >/dev/null 2>&1" | crontab -
```

### Step 4: Connect to EC2 Instance

```bash
ssh -i YourKeyPair.pem ubuntu@lensaibot.duckdns.org
```

---

## 📦 Server Setup Script

Save this as `setup_server.sh` and run on EC2:

```bash
#!/bin/bash
set -e

echo "================================================"
echo "AI Meeting Assistant - AWS Deployment Setup"
echo "================================================"

# Update system
sudo apt update
sudo apt upgrade -y

# Install essential tools
sudo apt install -y git curl wget build-essential software-properties-common

# Install Node.js 20.x
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Install Python 3.11
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt install -y python3.11 python3.11-venv python3.11-dev python3-pip

# Install MongoDB
wget -qO - https://www.mongodb.org/static/pgp/server-7.0.asc | sudo apt-key add -
echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt update
sudo apt install -y mongodb-org
sudo systemctl start mongod
sudo systemctl enable mongod

# Install Chrome for bot
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y ./google-chrome-stable_current_amd64.deb
rm google-chrome-stable_current_amd64.deb

# Install Chrome dependencies for headless mode
sudo apt install -y xvfb x11vnc fluxbox

# Install Ollama (LLM)
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama service
sudo systemctl start ollama
sudo systemctl enable ollama

# Pull llama3 model
ollama pull llama3

# Install Nginx
sudo apt install -y nginx certbot python3-certbot-nginx

# Install PM2 for process management
sudo npm install -g pm2

# Configure firewall
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

echo "✅ Server setup complete!"
echo "Next: Clone your repository and configure the application"
```

Run it:
```bash
chmod +x setup_server.sh
./setup_server.sh
```

---

## 📂 Deploy Application

### Clone Repository

```bash
cd /home/ubuntu
git clone <your-repo-url> ai-meeting-assistant
cd ai-meeting-assistant
```

### Configure Backend

```bash
cd backend

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
playwright install-deps

# Create .env file
cat > .env << 'EOF'
# Database
DATABASE_URL=sqlite:///./sql_app.db
MONGODB_URL=mongodb://localhost:27017

# Ollama (LLM)
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=llama3
OLLAMA_NUM_CTX=32768
OLLAMA_TEMPERATURE=0.3
OLLAMA_TIMEOUT=1200

# Transcription
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

# Auth
SECRET_KEY=$(openssl rand -hex 32)
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Frontend URL
FRONTEND_BASE_URL=https://lensaibot.duckdns.org
FRONTEND_URL=https://lensaibot.duckdns.org

# Google OAuth (optional - configure later)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=https://lensaibot.duckdns.org/api/integrations/google/callback
BOT_EMAIL=your-email@gmail.com

# Email Notifications
SEND_EMAIL_NOTIFICATIONS=false
SMTP_HOST=
SMTP_PORT=587
SMTP_TLS=true
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=noreply@lensaibot.duckdns.org
SMTP_FROM_NAME=AI Meeting Assistant

# Storage
STORAGE_DIR=/home/ubuntu/ai-meeting-assistant/backend/storage

# Live transcription
LIVE_ENABLED=true
LIVE_CHUNK_SECONDS=15
LIVE_SUMMARY_INTERVAL=45
EOF

# Create storage directory
mkdir -p storage

# Initialize database
# python init_db.py  # if you have this script
```

### Configure Frontend

```bash
cd ../frontend

# Install dependencies
npm install

# Create .env.local
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=https://lensaibot.duckdns.org/api
NEXT_PUBLIC_WS_URL=wss://lensaibot.duckdns.org/ws
EOF

# Build production version
npm run build
```

---

## 🔧 Configure PM2 (Process Manager)

Create PM2 ecosystem file:

```bash
cd /home/ubuntu/ai-meeting-assistant

cat > ecosystem.config.js << 'EOF'
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
      },
      error_file: '/home/ubuntu/logs/backend-error.log',
      out_file: '/home/ubuntu/logs/backend-out.log',
      time: true
    },
    {
      name: 'ai-meeting-frontend',
      cwd: '/home/ubuntu/ai-meeting-assistant/frontend',
      script: 'npm',
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
EOF

# Create logs directory
mkdir -p /home/ubuntu/logs

# Start applications
pm2 start ecosystem.config.js

# Save PM2 configuration
pm2 save

# Setup PM2 to start on boot
pm2 startup
# Run the command that PM2 outputs
```

---

## 🌐 Configure Nginx

```bash
sudo tee /etc/nginx/sites-available/ai-meeting-assistant << 'EOF'
# Upstream servers
upstream backend {
    server 127.0.0.1:8000;
}

upstream frontend {
    server 127.0.0.1:3000;
}

# HTTP -> HTTPS redirect
server {
    listen 80;
    server_name lensaibot.duckdns.org;
    
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    
    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS server
server {
    listen 443 ssl http2;
    server_name lensaibot.duckdns.org;
    
    # SSL certificates (will be configured by certbot)
    ssl_certificate /etc/letsencrypt/live/lensaibot.duckdns.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/lensaibot.duckdns.org/privkey.pem;
    
    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    # Max upload size for meeting recordings
    client_max_body_size 500M;
    
    # API Backend
    location /api {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        
        # Timeouts for long-running requests
        proxy_read_timeout 600s;
        proxy_connect_timeout 600s;
        proxy_send_timeout 600s;
    }
    
    # WebSocket for live transcription
    location /ws {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket timeouts
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
    
    # Frontend Next.js
    location / {
        proxy_pass http://frontend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }
    
    # Static files caching
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|svg|woff|woff2)$ {
        proxy_pass http://frontend;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
EOF

# Enable site
sudo ln -sf /etc/nginx/sites-available/ai-meeting-assistant /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Don't restart yet - need SSL certificate first
```

---

## 🔒 Setup SSL Certificate

```bash
# Stop nginx temporarily
sudo systemctl stop nginx

# Get SSL certificate
sudo certbot certonly --standalone -d lensaibot.duckdns.org --agree-tos --email your-email@example.com

# Start nginx
sudo systemctl start nginx
sudo systemctl enable nginx

# Test auto-renewal
sudo certbot renew --dry-run

# Setup auto-renewal cron (certbot usually does this automatically)
echo "0 0,12 * * * root certbot renew --quiet" | sudo tee -a /etc/crontab > /dev/null
```

---

## ✅ Verification

### Check Services Status

```bash
# MongoDB
sudo systemctl status mongod

# Ollama
sudo systemctl status ollama
ollama list  # Should show llama3

# PM2 processes
pm2 status
pm2 logs

# Nginx
sudo systemctl status nginx
sudo nginx -t

# Check ports
sudo netstat -tulpn | grep LISTEN
```

### Test URLs

```bash
# Backend health check
curl https://lensaibot.duckdns.org/api/health

# Frontend
curl https://lensaibot.duckdns.org
```

### Browser Testing

1. **Frontend:** https://lensaibot.duckdns.org
2. **Backend API:** https://lensaibot.duckdns.org/api/docs
3. **Create account** and test features

---

## 🔧 Maintenance Commands

### Update Application

```bash
cd /home/ubuntu/ai-meeting-assistant

# Pull latest changes
git pull origin main

# Update backend
cd backend
source venv/bin/activate
pip install -r requirements.txt --upgrade
pm2 restart ai-meeting-backend

# Update frontend
cd ../frontend
npm install
npm run build
pm2 restart ai-meeting-frontend

# Check status
pm2 status
```

### View Logs

```bash
# PM2 logs
pm2 logs ai-meeting-backend
pm2 logs ai-meeting-frontend

# Log files
tail -f /home/ubuntu/logs/backend-out.log
tail -f /home/ubuntu/logs/frontend-out.log

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# System logs
journalctl -u mongod -f
journalctl -u ollama -f
```

### Restart Services

```bash
# Restart all
pm2 restart all

# Restart specific service
pm2 restart ai-meeting-backend
pm2 restart ai-meeting-frontend

# Restart Nginx
sudo systemctl restart nginx

# Restart MongoDB
sudo systemctl restart mongod

# Restart Ollama
sudo systemctl restart ollama
```

### Database Backup

```bash
# Create backup script
cat > /home/ubuntu/backup_db.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/home/ubuntu/backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup SQLite
cp /home/ubuntu/ai-meeting-assistant/backend/sql_app.db $BACKUP_DIR/sql_app_$DATE.db

# Backup MongoDB
mongodump --out=$BACKUP_DIR/mongo_$DATE

# Keep only last 7 days
find $BACKUP_DIR -type f -mtime +7 -delete

echo "Backup completed: $DATE"
EOF

chmod +x /home/ubuntu/backup_db.sh

# Add to crontab (daily at 2 AM)
echo "0 2 * * * /home/ubuntu/backup_db.sh" | crontab -
```

---

## 🐛 Troubleshooting

### Backend Not Starting

```bash
# Check logs
pm2 logs ai-meeting-backend --lines 100

# Check Python version
python3.11 --version

# Test manually
cd /home/ubuntu/ai-meeting-assistant/backend
source venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Frontend Not Starting

```bash
# Check Node version
node --version  # Should be 20.x

# Rebuild
cd /home/ubuntu/ai-meeting-assistant/frontend
rm -rf .next node_modules
npm install
npm run build

# Test manually
npm start
```

### Bot Not Joining Meetings

```bash
# Check Chrome installation
google-chrome --version

# Check Xvfb (virtual display)
sudo apt install -y xvfb
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99

# Test Playwright
cd /home/ubuntu/ai-meeting-assistant/backend
source venv/bin/activate
python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); browser = p.chromium.launch(channel='chrome'); print('✓ Chrome OK'); browser.close()"
```

### SSL Certificate Issues

```bash
# Check certificate
sudo certbot certificates

# Renew manually
sudo certbot renew

# Check Nginx configuration
sudo nginx -t

# View certificate expiry
echo | openssl s_client -servername lensaibot.duckdns.org -connect lensaibot.duckdns.org:443 2>/dev/null | openssl x509 -noout -dates
```

### High Memory Usage

```bash
# Check memory
free -h
htop

# Restart services to clear memory
pm2 restart all
sudo systemctl restart mongod

# Check PM2 memory limits
pm2 show ai-meeting-backend
pm2 show ai-meeting-frontend

# Increase swap if needed
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 📊 Monitoring Setup (Optional)

### Install Monitoring Tools

```bash
# Install htop, iotop, netdata
sudo apt install -y htop iotop

# Install Netdata (web-based monitoring)
bash <(curl -Ss https://my-netdata.io/kickstart.sh)

# Access at: http://your-ip:19999
```

### PM2 Monitoring

```bash
# PM2 built-in monitoring
pm2 monit

# Web dashboard (optional)
pm2 install pm2-logrotate
pm2 set pm2-logrotate:max_size 50M
pm2 set pm2-logrotate:retain 7
```

---

## 🚀 Performance Optimization

### Nginx Caching

Add to `/etc/nginx/nginx.conf` in `http` block:

```nginx
# Cache settings
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=api_cache:10m max_size=1g inactive=60m;
proxy_cache_key "$scheme$request_method$host$request_uri";
```

### MongoDB Optimization

```bash
# Edit MongoDB config
sudo nano /etc/mongod.conf

# Add:
# net:
#   maxIncomingConnections: 200
# storage:
#   wiredTiger:
#     engineConfig:
#       cacheSizeGB: 2
```

### PM2 Cluster Mode (for frontend)

Update `ecosystem.config.js`:

```javascript
{
  name: 'ai-meeting-frontend',
  instances: 2,  // Use 2 instances
  exec_mode: 'cluster',
  // ... rest of config
}
```

---

## 📝 Summary Checklist

- [ ] EC2 instance launched (t3.xlarge or larger)
- [ ] Elastic IP allocated and associated
- [ ] DuckDNS configured (lensaibot.duckdns.org)
- [ ] Server dependencies installed
- [ ] MongoDB running
- [ ] Ollama running with llama3 model
- [ ] Chrome installed for bot
- [ ] Application cloned and configured
- [ ] Backend .env configured
- [ ] Frontend .env.local configured
- [ ] PM2 processes running
- [ ] Nginx configured
- [ ] SSL certificate installed
- [ ] All services verified
- [ ] Backups scheduled
- [ ] Monitoring setup

---

## 🆘 Support

If you encounter issues:

1. Check service status: `pm2 status`
2. View logs: `pm2 logs`
3. Check Nginx: `sudo nginx -t`
4. Check MongoDB: `sudo systemctl status mongod`
5. Check Ollama: `ollama list`
6. Review this guide's troubleshooting section

---

**Deployment Date:** September 17, 2026  
**Domain:** lensaibot.duckdns.org  
**AWS Region:** Configure based on your location  
**Estimated Monthly Cost:** $150-300 (depending on usage and instance type)
