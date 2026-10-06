#!/bin/bash
################################################################################
# AI Meeting Assistant - Complete Automated Deployment
# This runs all deployment steps in sequence
# Usage: bash full_deploy.sh
################################################################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║         AI Meeting Assistant - Full Deployment           ║
║              Deploy to lensaibot.duckdns.org             ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# Configuration
DOMAIN="lensaibot.duckdns.org"
EMAIL=""

# Ask for configuration
echo -e "${YELLOW}Pre-Deployment Configuration${NC}"
echo "=================================="
echo ""

read -p "Enter your email for SSL certificates: " EMAIL
read -p "Enter your GitHub repository URL: " REPO_URL
read -p "Enter your email for application notifications (optional): " APP_EMAIL

echo ""
echo -e "${BLUE}Configuration Summary:${NC}"
echo "  Domain: $DOMAIN"
echo "  SSL Email: $EMAIL"
echo "  Repository: $REPO_URL"
echo "  App Email: $APP_EMAIL"
echo ""
read -p "Is this correct? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled"
    exit 1
fi

# Update deploy_app.sh with repo URL
sed -i "s|REPO_URL=.*|REPO_URL=\"$REPO_URL\"|" ~/deploy_app.sh

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Step 1/5: Server Setup (15-20 minutes)                  ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
./setup_ec2.sh
echo -e "${GREEN}✓ Server setup complete${NC}"

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Step 2/5: Application Deployment (5-10 minutes)         ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
./deploy_app.sh
echo -e "${GREEN}✓ Application deployed${NC}"

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Step 3/5: SSL Certificate Setup (2-3 minutes)           ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
# Pass email to setup_ssl.sh
EMAIL="$EMAIL" ./setup_ssl.sh
echo -e "${GREEN}✓ SSL certificate installed${NC}"

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Step 4/5: Nginx Configuration (1 minute)                ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
./setup_nginx.sh
echo -e "${GREEN}✓ Nginx configured${NC}"

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Step 5/5: Final Verification                            ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"

# Wait for services to stabilize
echo "Waiting for services to stabilize..."
sleep 10

# Test deployment
echo ""
echo "Testing deployment..."

# Test backend
if curl -sf https://$DOMAIN/api/health > /dev/null; then
    echo -e "${GREEN}✓ Backend health check passed${NC}"
else
    echo -e "${RED}✗ Backend health check failed${NC}"
fi

# Test frontend
if curl -sf https://$DOMAIN > /dev/null; then
    echo -e "${GREEN}✓ Frontend accessible${NC}"
else
    echo -e "${RED}✗ Frontend not accessible${NC}"
fi

# Check SSL
SSL_VALID=$(echo | openssl s_client -servername $DOMAIN -connect $DOMAIN:443 2>/dev/null | openssl x509 -noout -checkend 86400 && echo "valid" || echo "invalid")
if [ "$SSL_VALID" == "valid" ]; then
    echo -e "${GREEN}✓ SSL certificate valid${NC}"
else
    echo -e "${RED}✗ SSL certificate issue${NC}"
fi

# Check PM2
PM2_STATUS=$(pm2 list | grep -c "online" || echo "0")
if [ "$PM2_STATUS" -ge 2 ]; then
    echo -e "${GREEN}✓ All PM2 processes running${NC}"
else
    echo -e "${RED}✗ Some PM2 processes not running${NC}"
fi

echo ""
echo -e "${BLUE}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║          ✓ DEPLOYMENT COMPLETE!                          ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

echo ""
echo -e "${GREEN}Your application is now live!${NC}"
echo ""
echo "📱 Access your application:"
echo "   Frontend:  https://$DOMAIN"
echo "   API:       https://$DOMAIN/api"
echo "   API Docs:  https://$DOMAIN/api/docs"
echo ""
echo "📊 Monitor your application:"
echo "   PM2 Status:     pm2 status"
echo "   View Logs:      pm2 logs"
echo "   System Monitor: htop"
echo ""
echo "🔧 Useful commands:"
echo "   Restart all:    pm2 restart all"
echo "   Update app:     cd ~/ai-meeting-assistant && git pull && pm2 restart all"
echo "   Backup DB:      ~/backup_db.sh"
echo ""
echo "📚 Documentation:"
echo "   Full guide:     ~/AWS_DEPLOYMENT_GUIDE.md"
echo "   Quick steps:    ~/DEPLOYMENT_STEPS.md"
echo ""
echo "⚙️  Next steps (optional):"
echo "   1. Configure email notifications (see EMAIL_SETUP.md)"
echo "   2. Setup Google OAuth (see AWS_DEPLOYMENT_GUIDE.md)"
echo "   3. Configure custom domain (if not using DuckDNS)"
echo "   4. Setup automated backups to S3"
echo ""
echo -e "${YELLOW}Server Information:${NC}"
echo "   IP Address:     $(curl -s ifconfig.me)"
echo "   Domain:         $DOMAIN"
echo "   Ubuntu:         $(lsb_release -ds)"
echo "   Node.js:        $(node --version)"
echo "   Python:         $(python3.11 --version | awk '{print $2}')"
echo ""
echo -e "${GREEN}Deployment completed successfully! 🎉${NC}"
echo ""
