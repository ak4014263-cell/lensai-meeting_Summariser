#!/bin/bash
################################################################################
# AI Meeting Assistant - SSL Certificate Setup
# Run this after deploy_app.sh
# Usage: bash setup_ssl.sh
################################################################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}"
echo "========================================================"
echo "  AI Meeting Assistant - SSL Certificate Setup"
echo "========================================================"
echo -e "${NC}"

DOMAIN="lensaibot.duckdns.org"
EMAIL=""

# Ask for email if not set
if [ -z "$EMAIL" ]; then
    read -p "Enter your email for SSL certificate notifications: " EMAIL
fi

# Verify domain resolves to this server
echo -e "${YELLOW}Verifying domain resolution...${NC}"
SERVER_IP=$(curl -s ifconfig.me)
DOMAIN_IP=$(dig +short $DOMAIN | tail -n1)

echo "Server IP: $SERVER_IP"
echo "Domain IP: $DOMAIN_IP"

if [ "$SERVER_IP" != "$DOMAIN_IP" ]; then
    echo -e "${RED}Warning: Domain does not resolve to this server!${NC}"
    echo "Please update DuckDNS to point to $SERVER_IP"
    echo ""
    read -p "Do you want to continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Stop nginx temporarily
echo -e "${YELLOW}Stopping Nginx temporarily...${NC}"
sudo systemctl stop nginx

# Get SSL certificate
echo -e "${YELLOW}Requesting SSL certificate from Let's Encrypt...${NC}"
sudo certbot certonly \
    --standalone \
    -d $DOMAIN \
    --agree-tos \
    --email $EMAIL \
    --non-interactive

# Start nginx
echo -e "${YELLOW}Starting Nginx...${NC}"
sudo systemctl start nginx

# Test auto-renewal
echo -e "${YELLOW}Testing certificate auto-renewal...${NC}"
sudo certbot renew --dry-run

# Setup auto-renewal cron (if not already set by certbot)
if ! sudo crontab -l | grep -q "certbot renew"; then
    echo "0 0,12 * * * certbot renew --quiet" | sudo crontab -
    echo "Auto-renewal cron job added"
fi

echo -e "${GREEN}"
echo "========================================================"
echo "  ✅ SSL Certificate Installed!"
echo "========================================================"
echo ""
echo "Certificate details:"
sudo certbot certificates | grep -A 5 $DOMAIN
echo ""
echo "Next step: Run setup_nginx.sh to configure Nginx"
echo "========================================================"
echo -e "${NC}"
