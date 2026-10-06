# AI Meeting Assistant - AWS Deployment Scripts

Deploy your AI Meeting Assistant to AWS EC2 and make it accessible at **lensaibot.duckdns.org**.

## 🚀 Quick Start (3 Options)

### Option 1: Automated Full Deployment (Recommended)
```bash
# On EC2 instance
bash full_deploy.sh
```
This runs everything automatically - takes about 25-30 minutes.

### Option 2: Step-by-Step Manual Deployment
```bash
# 1. Setup EC2 server (15-20 min)
bash setup_ec2.sh

# 2. Deploy application (5-10 min)
bash deploy_app.sh

# 3. Setup SSL certificate (2-3 min)
bash setup_ssl.sh

# 4. Configure Nginx (1 min)
bash setup_nginx.sh
```

### Option 3: Follow Detailed Guide
See `DEPLOYMENT_STEPS.md` for complete step-by-step instructions with screenshots and explanations.

---

## 📋 Prerequisites

### Before You Start
- [ ] AWS account with billing enabled
- [ ] EC2 instance launched (Ubuntu 22.04, t3.xlarge or larger)
- [ ] Elastic IP allocated and associated
- [ ] DuckDNS configured to point lensaibot to your Elastic IP
- [ ] SSH access to your EC2 instance
- [ ] Your code repository URL
- [ ] Email address for SSL certificates

---

## 📁 Deployment Files

| File | Purpose |
|------|---------|
| `full_deploy.sh` | **Automated full deployment** - runs all steps |
| `setup_ec2.sh` | Install all server dependencies |
| `deploy_app.sh` | Clone repo, install app, start with PM2 |
| `setup_ssl.sh` | Request SSL certificate from Let's Encrypt |
| `setup_nginx.sh` | Configure Nginx reverse proxy |
| `DEPLOYMENT_STEPS.md` | **Detailed step-by-step guide** |
| `README.md` | This file |

---

## 🎯 What Gets Installed

### System Services
- ✅ Node.js 20.x
- ✅ Python 3.11
- ✅ MongoDB 7.0
- ✅ Ollama + llama3 model (4.7GB)
- ✅ Google Chrome (for bot meetings)
- ✅ Nginx (web server)
- ✅ PM2 (process manager)
- ✅ Certbot (SSL certificates)

### Your Application
- ✅ Backend API (FastAPI on port 8000)
- ✅ Frontend (Next.js on port 3000)
- ✅ Nginx reverse proxy with SSL
- ✅ Automatic process management
- ✅ Auto-restart on failure
- ✅ Log management

---

## 📖 Detailed Deployment Steps

### Step 1: Prepare EC2 Instance

1. **Launch EC2 instance:**
   - AMI: Ubuntu 22.04 LTS
   - Type: t3.xlarge (4 vCPU, 16 GB RAM)
   - Storage: 100 GB gp3
   - Security Group: Allow SSH(22), HTTP(80), HTTPS(443)

2. **Allocate Elastic IP** and associate with instance

3. **Configure DuckDNS:**
   - Go to https://www.duckdns.org
   - Update `lensaibot` subdomain with your Elastic IP

4. **Connect via SSH:**
   ```bash
   ssh -i your-key.pem ubuntu@lensaibot.duckdns.org
   ```

### Step 2: Upload Deployment Scripts

From your local machine:
```bash
# Navigate to project directory
cd "C:\Users\hp\Downloads\New folder (16)"

# Upload scripts to EC2
scp -i your-key.pem deploy/*.sh ubuntu@lensaibot.duckdns.org:~/

# Make executable
ssh -i your-key.pem ubuntu@lensaibot.duckdns.org "chmod +x ~/*.sh"
```

### Step 3: Run Deployment

Choose one of the 3 options above.

### Step 4: Verify Deployment

```bash
# Check services
pm2 status
sudo systemctl status nginx mongod ollama

# Test URLs
curl https://lensaibot.duckdns.org
curl https://lensaibot.duckdns.org/api/health

# View logs
pm2 logs
```

### Step 5: Access Your Application

Open in browser:
- **Frontend:** https://lensaibot.duckdns.org
- **API Docs:** https://lensaibot.duckdns.org/api/docs

---

## 🔧 Post-Deployment Configuration

### Configure Email Notifications

1. Edit backend .env:
   ```bash
   nano ~/ai-meeting-assistant/backend/.env
   ```

2. Update email settings:
   ```env
   SEND_EMAIL_NOTIFICATIONS=true
   SMTP_HOST=smtp.gmail.com
   SMTP_USERNAME=your-email@gmail.com
   SMTP_PASSWORD=your-app-password
   ```

3. Restart backend:
   ```bash
   pm2 restart ai-meeting-backend
   ```

See `../backend/EMAIL_SETUP.md` for details.

### Configure Google OAuth (Optional)

1. Create OAuth credentials at https://console.cloud.google.com
2. Add redirect URI: `https://lensaibot.duckdns.org/api/integrations/google/callback`
3. Update .env with credentials
4. Restart backend

See `../AWS_DEPLOYMENT_GUIDE.md` for details.

---

## 📊 Monitoring & Maintenance

### View Status
```bash
pm2 status              # Application status
pm2 monit              # Real-time monitoring
htop                   # System resources
df -h                  # Disk usage
free -h                # Memory usage
```

### View Logs
```bash
pm2 logs                           # All logs
pm2 logs ai-meeting-backend        # Backend only
pm2 logs ai-meeting-frontend       # Frontend only
tail -f ~/logs/backend-out.log     # Backend output
tail -f ~/logs/frontend-out.log    # Frontend output
sudo tail -f /var/log/nginx/error.log  # Nginx errors
```

### Restart Services
```bash
pm2 restart all                # Restart all
pm2 restart ai-meeting-backend # Backend only
pm2 restart ai-meeting-frontend # Frontend only
sudo systemctl restart nginx   # Nginx
sudo systemctl restart mongod  # MongoDB
sudo systemctl restart ollama  # Ollama
```

### Update Application
```bash
cd ~/ai-meeting-assistant
git pull origin main

# Update backend
cd backend
source venv/bin/activate
pip install -r requirements.txt --upgrade

# Update frontend
cd ../frontend
npm install
npm run build

# Restart
pm2 restart all
```

### Backup Database
```bash
# Manual backup
./backup_db.sh

# View backups
ls -lh ~/backups/

# Automated daily backups are configured via cron
```

---

## 🐛 Troubleshooting

### Backend Not Starting
```bash
pm2 logs ai-meeting-backend --lines 100
cd ~/ai-meeting-assistant/backend
source venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Frontend Not Starting
```bash
pm2 logs ai-meeting-frontend --lines 100
cd ~/ai-meeting-assistant/frontend
rm -rf .next
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

# Restart Xvfb
pkill Xvfb
Xvfb :99 -screen 0 1920x1080x24 &

# Restart backend
pm2 restart ai-meeting-backend
```

### High Memory Usage
```bash
# Check what's using memory
htop
pm2 list

# Restart services
pm2 restart all
sudo systemctl restart mongod

# Check logs for memory leaks
pm2 logs --err
```

### Domain Not Resolving
```bash
# Check DNS
nslookup lensaibot.duckdns.org
dig lensaibot.duckdns.org

# Update DuckDNS
curl "https://www.duckdns.org/update?domains=lensaibot&token=YOUR_TOKEN&ip="

# Verify Elastic IP association in AWS Console
```

---

## 💰 Cost Estimate

### AWS Monthly Costs
- **EC2 t3.xlarge:** ~$120-150/month
- **100 GB EBS Storage:** ~$10/month
- **Data Transfer:** ~$10-30/month
- **Total:** ~$140-190/month

### Cost Optimization
- Use **t3.large** instead (~$60/month savings)
- Use **Reserved Instance** (~30-40% discount)
- **Stop** instance when not in use (dev/test)
- Use **S3** for meeting recordings (~$0.023/GB)

---

## 🔒 Security Checklist

- [x] SSH key authentication only
- [x] UFW firewall enabled
- [x] HTTPS with valid SSL certificate
- [x] Security headers configured
- [ ] Change SSH port (optional)
- [ ] Setup fail2ban (recommended)
- [ ] Enable automatic security updates
- [ ] Regular backups to S3
- [ ] Rotate secrets regularly

---

## 📚 Additional Resources

- **Full Deployment Guide:** `AWS_DEPLOYMENT_GUIDE.md`
- **Step-by-Step Guide:** `DEPLOYMENT_STEPS.md`
- **Email Setup:** `../backend/EMAIL_SETUP.md`
- **Backend API Docs:** https://lensaibot.duckdns.org/api/docs

---

## ❓ Common Questions

### How long does deployment take?
- Automated: 25-30 minutes total
- Manual steps: 20-25 minutes total
- Most time spent downloading llama3 model (5-10 min)

### Can I use a different domain?
Yes, update `DOMAIN` variable in the scripts and follow the same process.

### What if I don't have a DuckDNS account?
You can use any domain - just point its A record to your Elastic IP.

### Can I scale horizontally?
Yes, but requires setting up a load balancer and shared storage. See AWS_DEPLOYMENT_GUIDE.md.

### How do I backup my data?
Run `./backup_db.sh` - it's also configured to run daily via cron.

---

## 🆘 Need Help?

1. Check logs: `pm2 logs`
2. Check service status: `pm2 status`
3. Review troubleshooting section above
4. Check AWS_DEPLOYMENT_GUIDE.md for detailed solutions
5. Verify all prerequisites are met

---

## ✅ Deployment Checklist

- [ ] EC2 instance launched and running
- [ ] Elastic IP allocated and associated
- [ ] Security group configured (ports 22, 80, 443)
- [ ] DuckDNS configured with Elastic IP
- [ ] SSH connection working
- [ ] Deployment scripts uploaded and executable
- [ ] `setup_ec2.sh` completed successfully
- [ ] `deploy_app.sh` completed successfully
- [ ] `setup_ssl.sh` completed successfully
- [ ] `setup_nginx.sh` completed successfully
- [ ] Application accessible via HTTPS
- [ ] PM2 processes running (backend & frontend)
- [ ] SSL certificate valid
- [ ] Email notifications configured (optional)
- [ ] Google OAuth configured (optional)

---

**Last Updated:** September 17, 2026  
**Domain:** lensaibot.duckdns.org  
**Status:** Ready for deployment  
**Estimated Deployment Time:** 25-30 minutes
