# Quick Deployment Steps for lensaibot.duckdns.org

## Prerequisites Checklist
- [ ] AWS account with billing enabled
- [ ] AWS CLI installed on local machine
- [ ] SSH key pair for EC2 (create one if needed)
- [ ] DuckDNS account and token
- [ ] Your repository pushed to GitHub/GitLab

---

## Step 1: Launch EC2 Instance (AWS Console Method)

### 1.1 Go to EC2 Dashboard
```
AWS Console → Services → EC2 → Launch Instance
```

### 1.2 Configure Instance
```
Name: AI-Meeting-Assistant
AMI: Ubuntu Server 22.04 LTS (64-bit x86)
Instance Type: t3.xlarge (4 vCPU, 16 GB RAM)
Key Pair: Select or create new
```

### 1.3 Configure Storage
```
Volume: 100 GB gp3
```

### 1.4 Configure Security Group
Create new security group with these rules:
```
Name: ai-meeting-sg

Inbound Rules:
- SSH (22)        - Source: My IP
- HTTP (80)       - Source: 0.0.0.0/0
- HTTPS (443)     - Source: 0.0.0.0/0

Outbound Rules:
- All traffic     - Destination: 0.0.0.0/0
```

### 1.5 Launch Instance
Click "Launch Instance" and wait for it to start.

---

## Step 2: Allocate & Associate Elastic IP

### 2.1 Allocate Elastic IP
```
EC2 → Elastic IPs → Allocate Elastic IP address → Allocate
```

### 2.2 Associate with Instance
```
Actions → Associate Elastic IP address
Select your instance → Associate
```

**Note the Elastic IP** - Example: `54.123.45.67`

---

## Step 3: Configure DuckDNS

### 3.1 Update DuckDNS
1. Go to https://www.duckdns.org
2. Log in
3. Find or create `lensaibot` subdomain
4. Update IP address to your **Elastic IP** (from Step 2.2)
5. Click "update ip"

### 3.2 Verify DNS
Wait 2-3 minutes, then verify:
```bash
# On your local machine
nslookup lensaibot.duckdns.org
# Should show your Elastic IP
```

---

## Step 4: Connect to EC2 Instance

### 4.1 Get Connection Command
From AWS Console:
```
Select instance → Connect → SSH client tab
Copy the ssh command shown
```

### 4.2 Connect
```bash
# Example (adjust path to your key):
ssh -i "path/to/your-key.pem" ubuntu@lensaibot.duckdns.org

# If permission error on Windows:
icacls "path\to\your-key.pem" /inheritance:r
icacls "path\to\your-key.pem" /grant:r "%username%:R"
```

---

## Step 5: Upload Deployment Scripts

### 5.1 From Local Machine
Open a new terminal (keep SSH session open):

```bash
# Navigate to your project
cd "C:\Users\hp\Downloads\New folder (16)"

# Upload deployment scripts
scp -i "path/to/your-key.pem" deploy/*.sh ubuntu@lensaibot.duckdns.org:~/

# Make them executable on server
ssh -i "path/to/your-key.pem" ubuntu@lensaibot.duckdns.org "chmod +x ~/*.sh"
```

---

## Step 6: Run Setup Scripts on EC2

### 6.1 Setup EC2 Server (15-20 minutes)
```bash
# On EC2 instance
cd ~
./setup_ec2.sh
```

This will install:
- Node.js 20.x
- Python 3.11
- MongoDB
- Ollama + llama3 model (5GB download)
- Google Chrome
- Nginx
- PM2
- Certbot

**Wait for completion** - The llama3 model download takes 5-10 minutes.

### 6.2 Verify Installation
```bash
# Check services
sudo systemctl status mongod
sudo systemctl status ollama
ollama list  # Should show llama3
google-chrome --version
node --version
python3.11 --version
```

---

## Step 7: Deploy Application

### 7.1 Update Repository URL
```bash
# Edit deploy_app.sh
nano ~/deploy_app.sh

# Update this line with your actual repo:
# REPO_URL="https://github.com/YOUR_USERNAME/ai-meeting-assistant.git"
```

### 7.2 Run Deployment
```bash
./deploy_app.sh
```

This will:
- Clone your repository
- Install Python dependencies
- Install Node.js dependencies
- Build frontend
- Create .env files
- Start applications with PM2

### 7.3 Verify Deployment
```bash
# Check PM2 status
pm2 status

# Should show:
# ai-meeting-backend  | online
# ai-meeting-frontend | online

# View logs
pm2 logs --lines 50
```

### 7.4 Test Locally (Before SSL)
```bash
# Test backend
curl http://localhost:8000/api/health

# Test frontend
curl http://localhost:3000
```

---

## Step 8: Setup SSL Certificate

### 8.1 Run SSL Setup
```bash
./setup_ssl.sh
```

Enter your email when prompted (for certificate notifications).

This will:
- Verify domain points to server
- Request certificate from Let's Encrypt
- Configure auto-renewal

### 8.2 Verify Certificate
```bash
sudo certbot certificates
```

---

## Step 9: Configure Nginx

### 9.1 Run Nginx Setup
```bash
./setup_nginx.sh
```

This will:
- Create Nginx configuration
- Enable HTTPS
- Setup reverse proxy
- Restart Nginx

### 9.2 Verify Nginx
```bash
sudo nginx -t
sudo systemctl status nginx
```

---

## Step 10: Test Deployment

### 10.1 Test URLs
```bash
# From EC2 or local machine
curl https://lensaibot.duckdns.org
curl https://lensaibot.duckdns.org/api/health
```

### 10.2 Browser Test
Open in your browser:
1. **Frontend:** https://lensaibot.duckdns.org
2. **API Docs:** https://lensaibot.duckdns.org/api/docs
3. **Create account** and test features

---

## Step 11: Configure Email (Optional)

### 11.1 Update Backend .env
```bash
nano ~/ai-meeting-assistant/backend/.env

# Update these lines:
SEND_EMAIL_NOTIFICATIONS=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=your-email@gmail.com
```

### 11.2 Restart Backend
```bash
pm2 restart ai-meeting-backend
```

### 11.3 Test Email
```bash
cd ~/ai-meeting-assistant/backend
source venv/bin/activate
python test_email.py your-email@gmail.com
```

---

## Step 12: Configure Google OAuth (Optional)

### 12.1 Create Google OAuth Credentials
1. Go to https://console.cloud.google.com
2. Create project
3. Enable Google Meet API
4. Create OAuth 2.0 credentials
5. Add authorized redirect URI: `https://lensaibot.duckdns.org/api/integrations/google/callback`

### 12.2 Update Backend .env
```bash
nano ~/ai-meeting-assistant/backend/.env

# Update:
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
BOT_EMAIL=your-gmail@gmail.com
```

### 12.3 Restart Backend
```bash
pm2 restart ai-meeting-backend
```

---

## ✅ Deployment Complete!

Your application is now live at:
- **Frontend:** https://lensaibot.duckdns.org
- **Backend API:** https://lensaibot.duckdns.org/api
- **API Docs:** https://lensaibot.duckdns.org/api/docs

---

## Maintenance Commands

### View Logs
```bash
pm2 logs
pm2 logs ai-meeting-backend
pm2 logs ai-meeting-frontend
```

### Restart Services
```bash
pm2 restart all
pm2 restart ai-meeting-backend
pm2 restart ai-meeting-frontend
```

### Update Application
```bash
cd ~/ai-meeting-assistant
git pull
cd backend && source venv/bin/activate && pip install -r requirements.txt
cd ../frontend && npm install && npm run build
pm2 restart all
```

### Check System Resources
```bash
htop
df -h
free -h
pm2 monit
```

### Backup Database
```bash
# Create backup
./backup_db.sh

# View backups
ls -lh ~/backups/
```

### View Service Status
```bash
sudo systemctl status mongod
sudo systemctl status ollama
sudo systemctl status nginx
pm2 status
```

---

## Troubleshooting

### Backend Not Starting
```bash
pm2 logs ai-meeting-backend
cd ~/ai-meeting-assistant/backend
source venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Frontend Not Starting
```bash
pm2 logs ai-meeting-frontend
cd ~/ai-meeting-assistant/frontend
npm run build
npm start
```

### SSL Certificate Issues
```bash
sudo certbot renew
sudo certbot certificates
sudo nginx -t
sudo systemctl restart nginx
```

### Bot Not Joining Meetings
```bash
# Check Chrome
google-chrome --version

# Check virtual display
ps aux | grep Xvfb

# Restart virtual display
./ai-meeting-assistant/start_xvfb.sh
```

### High Memory Usage
```bash
# Check memory
free -h

# Restart services
pm2 restart all
sudo systemctl restart mongod
```

---

## Cost Estimate

**AWS Monthly Costs (Approximate):**
- EC2 t3.xlarge: ~$120-150/month
- 100 GB EBS Storage: ~$10/month
- Data Transfer: ~$10-30/month (varies with usage)
- **Total: ~$140-190/month**

**To Reduce Costs:**
- Use t3.large instead of t3.xlarge (~$60/month)
- Use EC2 Reserved Instance (~30-40% discount)
- Stop instance when not in use (for development)

---

## Security Recommendations

1. **Change default SSH port** (optional)
2. **Setup fail2ban** for SSH protection
3. **Enable automatic security updates**
4. **Regular backups** to S3
5. **Monitor CloudWatch logs**
6. **Rotate secrets regularly**

---

## Support

If you need help:
1. Check logs: `pm2 logs`
2. Check system: `sudo systemctl status nginx mongod ollama`
3. Review AWS_DEPLOYMENT_GUIDE.md for detailed troubleshooting
4. Check application logs in `~/logs/`

---

**Last Updated:** September 17, 2026
**Domain:** lensaibot.duckdns.org
**Status:** Ready for deployment
