#!/bin/bash
################################################################################
# AI Meeting Assistant - EC2 Server Setup Script
# Run this script on a fresh Ubuntu 22.04 EC2 instance
# Usage: bash setup_ec2.sh
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
echo "========================================================"
echo "  AI Meeting Assistant - EC2 Setup"
echo "  Domain: lensaibot.duckdns.org"
echo "========================================================"
echo -e "${NC}"

# Check if running as root
if [ "$EUID" -eq 0 ]; then 
   echo -e "${RED}Please do not run as root. Run as ubuntu user.${NC}"
   exit 1
fi

# Update system
echo -e "${YELLOW}[1/15] Updating system packages...${NC}"
sudo apt update
sudo apt upgrade -y

# Install essential tools
echo -e "${YELLOW}[2/15] Installing essential tools...${NC}"
sudo apt install -y \
    git \
    curl \
    wget \
    build-essential \
    software-properties-common \
    ca-certificates \
    gnupg \
    lsb-release \
    unzip

# Install Node.js 20.x
echo -e "${YELLOW}[3/15] Installing Node.js 20.x...${NC}"
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

echo "Node version: $(node --version)"
echo "NPM version: $(npm --version)"

# Install Python 3.11
echo -e "${YELLOW}[4/15] Installing Python 3.11...${NC}"
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt install -y \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-pip

echo "Python version: $(python3.11 --version)"

# Install MongoDB 7.0
echo -e "${YELLOW}[5/15] Installing MongoDB 7.0...${NC}"
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | sudo gpg --dearmor -o /usr/share/keyrings/mongodb-archive-keyring.gpg
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-archive-keyring.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt update
sudo apt install -y mongodb-org

sudo systemctl start mongod
sudo systemctl enable mongod

echo "MongoDB status:"
sudo systemctl status mongod --no-pager | head -n 3

# Install Google Chrome
echo -e "${YELLOW}[6/15] Installing Google Chrome...${NC}"
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y ./google-chrome-stable_current_amd64.deb
rm google-chrome-stable_current_amd64.deb

echo "Chrome version: $(google-chrome --version)"

# Install Chrome dependencies
echo -e "${YELLOW}[7/15] Installing Chrome dependencies...${NC}"
sudo apt install -y \
    xvfb \
    x11vnc \
    fluxbox \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0

# Install Ollama
echo -e "${YELLOW}[8/15] Installing Ollama (LLM runtime)...${NC}"
curl -fsSL https://ollama.com/install.sh | sh

sudo systemctl start ollama
sudo systemctl enable ollama

echo "Ollama status:"
sudo systemctl status ollama --no-pager | head -n 3

# Pull llama3 model (this takes time!)
echo -e "${YELLOW}[9/15] Pulling llama3 model (this may take 5-10 minutes)...${NC}"
ollama pull llama3

echo "Ollama models:"
ollama list

# Install Nginx
echo -e "${YELLOW}[10/15] Installing Nginx...${NC}"
sudo apt install -y nginx

sudo systemctl start nginx
sudo systemctl enable nginx

echo "Nginx status:"
sudo systemctl status nginx --no-pager | head -n 3

# Install Certbot for SSL
echo -e "${YELLOW}[11/15] Installing Certbot for SSL certificates...${NC}"
sudo apt install -y certbot python3-certbot-nginx

# Install PM2 globally
echo -e "${YELLOW}[12/15] Installing PM2 process manager...${NC}"
sudo npm install -g pm2

echo "PM2 version: $(pm2 --version)"

# Configure firewall
echo -e "${YELLOW}[13/15] Configuring UFW firewall...${NC}"
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw --force enable

echo "Firewall status:"
sudo ufw status

# Create necessary directories
echo -e "${YELLOW}[14/15] Creating application directories...${NC}"
mkdir -p ~/logs
mkdir -p ~/backups
mkdir -p ~/ai-meeting-assistant

# Install additional Python packages globally
echo -e "${YELLOW}[15/15] Installing additional tools...${NC}"
pip3 install --upgrade pip

# Summary
echo -e "${GREEN}"
echo "========================================================"
echo "  ✅ EC2 Setup Complete!"
echo "========================================================"
echo ""
echo "Installed Services:"
echo "  ✓ Node.js $(node --version)"
echo "  ✓ Python $(python3.11 --version | awk '{print $2}')"
echo "  ✓ MongoDB (running)"
echo "  ✓ Ollama + llama3 model"
echo "  ✓ Google Chrome $(google-chrome --version | awk '{print $3}')"
echo "  ✓ Nginx (running)"
echo "  ✓ PM2 $(pm2 --version)"
echo "  ✓ Certbot"
echo ""
echo "Next Steps:"
echo "  1. Configure DuckDNS to point lensaibot to this server's IP"
echo "  2. Clone your application repository"
echo "  3. Run deploy_app.sh to deploy the application"
echo "  4. Run setup_ssl.sh to configure SSL certificate"
echo ""
echo "Your server IP: $(curl -s ifconfig.me)"
echo "========================================================"
echo -e "${NC}"
