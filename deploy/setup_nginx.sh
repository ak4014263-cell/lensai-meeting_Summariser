#!/bin/bash
################################################################################
# AI Meeting Assistant - Nginx Configuration Script
# Run this after deploy_app.sh and setup_ssl.sh
# Usage: bash setup_nginx.sh
################################################################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}"
echo "========================================================"
echo "  AI Meeting Assistant - Nginx Setup"
echo "========================================================"
echo -e "${NC}"

DOMAIN="lensaibot.duckdns.org"

# Check if SSL certificate exists
if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    echo -e "${RED}Error: SSL certificate not found!${NC}"
    echo "Please run setup_ssl.sh first"
    exit 1
fi

# Create Nginx configuration
echo -e "${YELLOW}Creating Nginx configuration...${NC}"
sudo tee /etc/nginx/sites-available/ai-meeting-assistant > /dev/null << 'EOF'
# Upstream servers
upstream backend {
    server 127.0.0.1:8000;
    keepalive 32;
}

upstream frontend {
    server 127.0.0.1:3000;
    keepalive 32;
}

# HTTP -> HTTPS redirect
server {
    listen 80;
    listen [::]:80;
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
    listen [::]:443 ssl http2;
    server_name lensaibot.duckdns.org;
    
    # SSL certificates
    ssl_certificate /etc/letsencrypt/live/lensaibot.duckdns.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/lensaibot.duckdns.org/privkey.pem;
    
    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
    
    # Max upload size for meeting recordings
    client_max_body_size 500M;
    
    # Timeouts
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
    proxy_read_timeout 600s;
    send_timeout 600s;
    
    # API Backend - /api prefix
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
        proxy_buffering off;
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
        
        # Disable buffering for WebSocket
        proxy_buffering off;
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
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|svg|woff|woff2|ttf|eot)$ {
        proxy_pass http://frontend;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    
    # Next.js specific paths
    location /_next/static {
        proxy_pass http://frontend;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
EOF

# Enable site
echo -e "${YELLOW}Enabling site configuration...${NC}"
sudo ln -sf /etc/nginx/sites-available/ai-meeting-assistant /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test configuration
echo -e "${YELLOW}Testing Nginx configuration...${NC}"
sudo nginx -t

# Restart Nginx
echo -e "${YELLOW}Restarting Nginx...${NC}"
sudo systemctl restart nginx

echo -e "${GREEN}"
echo "========================================================"
echo "  ✅ Nginx Configured Successfully!"
echo "========================================================"
echo ""
echo "Your application is now available at:"
echo "  🌐 https://$DOMAIN"
echo ""
echo "API Documentation:"
echo "  📚 https://$DOMAIN/api/docs"
echo ""
echo "Test the deployment:"
echo "  curl https://$DOMAIN"
echo "  curl https://$DOMAIN/api/health"
echo ""
echo "========================================================"
echo -e "${NC}"
