# 🚀 LensAI Production Deployment Checklist

## Pre-Deployment Checklist

### ✅ 1. VPS Requirements Verified
- [ ] **VPS IP:** 200.97.170.172
- [ ] **Domain:** lenss.ai (with DNS pointing to VPS)
- [ ] **SSH Access:** root/Lensai@898918
- [ ] **Minimum Specs:** 4 vCPU, 8GB RAM, 50GB SSD
- [ ] **OS:** Ubuntu 20.04 or 22.04 LTS

### ✅ 2. Credentials Ready
- [ ] **Google OAuth Client ID:** (from Google Cloud Console)
- [ ] **Google OAuth Client Secret:** (from Google Cloud Console)
- [ ] **HuggingFace Token:** (from HuggingFace account)
- [ ] **SSL Email:** (for Let's Encrypt certificate)

### ✅ 3. Google OAuth Configuration
**IMPORTANT:** Before deployment, update Google Cloud Console:

1. Go to: https://console.cloud.google.com/apis/credentials
2. Select your OAuth 2.0 Client
3. Add to **Authorized redirect URIs:**
   ```
   https://lenss.ai/ai/integrations/google/callback
   ```
4. Save changes

### ✅ 4. DNS Configuration
Verify DNS is pointing to VPS:
```bash
dig lenss.ai +short
# Should return: 200.97.170.172

dig www.lenss.ai +short
# Should return: 200.97.170.172
```

### ✅ 5. Code Repository
- [ ] All code pushed to: https://github.com/ak4014263-cell/lensai-meeting_Summariser.git
- [ ] Latest commit includes:
  - ✅ LensAI branding
  - ✅ Speaker recognition fixes
  - ✅ Concurrent meeting support (BOT_MAX_CONCURRENT=3)
  - ✅ Next.js config with basePath support
  - ✅ Deployment scripts

---

## 🎯 Deployment Steps

### Step 1: Connect to VPS
```bash
ssh root@200.97.170.172
# Password: Lensai@898918
```

### Step 2: Download Deployment Script
```bash
wget https://raw.githubusercontent.com/ak4014263-cell/lensai-meeting_Summariser/main/deploy-lenss-ai.sh
chmod +x deploy-lenss-ai.sh
```

### Step 3: Run Deployment
```bash
./deploy-lenss-ai.sh
```

**You'll be prompted for:**
1. Email for SSL certificate
2. Google OAuth Client ID
3. Google OAuth Client Secret
4. HuggingFace Token

**Deployment takes ~20-30 minutes** (installing dependencies, building frontend, etc.)

### Step 4: Setup Bot Google Account
After deployment completes:
```bash
cd ~/lensai-meeting_Summariser/backend
source venv/bin/activate
DISPLAY=:99 python setup_bot_login.py
```

**This will:**
- Open Chrome browser (headless)
- Ask you to login with a Google account
- Save the session for the bot to use

**Bot Account Requirements:**
- Use a dedicated Google account (not your personal one)
- Account should have calendar access
- Must accept Google Meet permissions

---

## 🧪 Post-Deployment Testing

### 1. Check Services Status
```bash
# Backend status
sudo systemctl status lensai-backend

# Frontend status
sudo systemctl status lensai-frontend

# MongoDB status
sudo systemctl status mongod

# Ollama status
sudo systemctl status ollama

# Xvfb (virtual display)
sudo systemctl status xvfb
```

### 2. View Logs
```bash
# Backend logs (real-time)
sudo journalctl -u lensai-backend -f

# Frontend logs
sudo journalctl -u lensai-frontend -f

# Check for errors in last 100 lines
sudo journalctl -u lensai-backend -n 100 --no-pager
```

### 3. Test API Health
```bash
curl https://lenss.ai/ai/api/health
```

Expected response:
```json
{
  "status": "healthy",
  "database": "connected",
  "ollama": "running"
}
```

### 4. Access Application
Open browser: **https://lenss.ai/ai**

**Expected:**
- ✅ Page loads without errors
- ✅ No 404 or CORS errors in console
- ✅ Can navigate to different pages
- ✅ Google OAuth login button appears

### 5. Test Google OAuth
1. Click "Sign in with Google"
2. Should redirect to Google login
3. After login, should return to: `https://lenss.ai/ai/dashboard`
4. Check browser console for errors

### 6. Test Meeting Creation
1. Click "Schedule Meeting" or "Join Meeting"
2. Enter Google Meet URL
3. Bot should join meeting
4. Check backend logs:
   ```bash
   sudo journalctl -u lensai-backend -f | grep -i "bot"
   ```

---

## 🔧 Configuration Updates

### Increase Concurrent Meeting Capacity

Edit backend `.env`:
```bash
cd ~/lensai-meeting_Summariser/backend
nano .env
```

Change:
```bash
BOT_MAX_CONCURRENT=5  # Increase from default 3
```

Restart backend:
```bash
sudo systemctl restart lensai-backend
```

### Optimize for Performance

**For 5-10 concurrent meetings:**
```bash
# Edit systemd service to add more workers
sudo nano /etc/systemd/system/lensai-backend.service
```

Change:
```
ExecStart=...uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
```

Reload:
```bash
sudo systemctl daemon-reload
sudo systemctl restart lensai-backend
```

---

## 🐛 Troubleshooting

### Issue: "502 Bad Gateway"

**Check if backend is running:**
```bash
sudo systemctl status lensai-backend
sudo journalctl -u lensai-backend -n 50
```

**Restart backend:**
```bash
sudo systemctl restart lensai-backend
```

---

### Issue: "Connection to MongoDB failed"

**Check MongoDB status:**
```bash
sudo systemctl status mongod
```

**Restart MongoDB:**
```bash
sudo systemctl restart mongod
sudo systemctl restart lensai-backend
```

---

### Issue: "Bot not joining meetings"

**1. Check bot login:**
```bash
cd ~/lensai-meeting_Summariser/backend
source venv/bin/activate
DISPLAY=:99 python setup_bot_login.py
```

**2. Check Xvfb (virtual display):**
```bash
sudo systemctl status xvfb
sudo systemctl restart xvfb
sudo systemctl restart lensai-backend
```

**3. Check Chrome processes:**
```bash
ps aux | grep chrome
```

**Kill stuck processes:**
```bash
pkill -f chrome
sudo systemctl restart lensai-backend
```

---

### Issue: "SSL Certificate errors"

**Renew certificate:**
```bash
sudo certbot renew
sudo systemctl reload nginx
```

**Force renewal:**
```bash
sudo certbot renew --force-renewal
```

---

### Issue: "High CPU/Memory usage"

**Check resource usage:**
```bash
htop
```

**Optimize Whisper model (in backend .env):**
```bash
# Change from large-v3 to medium or base
WHISPER_MODEL=medium  # or base for even faster
```

**Restart:**
```bash
sudo systemctl restart lensai-backend
```

---

## 📊 Monitoring Commands

### Check Active Meetings
```bash
curl https://lenss.ai/ai/api/meetings/active | jq .
```

### Monitor System Resources
```bash
# CPU and Memory
htop

# Disk usage
df -h

# Running Chrome instances (= active meetings)
ps aux | grep chrome | wc -l
```

### Watch Logs in Real-Time
```bash
# All backend logs
sudo journalctl -u lensai-backend -f

# Only bot-related logs
sudo journalctl -u lensai-backend -f | grep -i "bot\|meeting"

# Errors only
sudo journalctl -u lensai-backend -f | grep -i "error\|exception"
```

---

## 🔄 Updating the Application

### Pull Latest Code
```bash
cd ~/lensai-meeting_Summariser

# Backend
git pull origin main

# Update backend dependencies
cd backend
source venv/bin/activate
pip install -r requirements.txt
deactivate

# Update frontend
cd ../frontend
npm install
npm run build

# Restart services
sudo systemctl restart lensai-backend
sudo systemctl restart lensai-frontend
```

### View Update Logs
```bash
sudo journalctl -u lensai-backend -u lensai-frontend -f
```

---

## 🔐 Security Best Practices

### 1. Change Root Password
```bash
passwd root
```

### 2. Create Non-Root User
```bash
adduser lensai
usermod -aG sudo lensai

# Update systemd services to use this user
sudo nano /etc/systemd/system/lensai-backend.service
# Change User=root to User=lensai
```

### 3. Setup Firewall
```bash
sudo ufw status
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

### 4. Disable Password SSH (Use Keys)
```bash
# On your local machine, generate SSH key
ssh-keygen -t rsa -b 4096

# Copy to VPS
ssh-copy-id root@200.97.170.172

# Disable password login
sudo nano /etc/ssh/sshd_config
# Set: PasswordAuthentication no
sudo systemctl restart sshd
```

### 5. Regular Backups
```bash
# Backup MongoDB
mongodump --out /backup/mongodb-$(date +%Y%m%d)

# Backup application
tar -czf /backup/lensai-$(date +%Y%m%d).tar.gz ~/lensai-meeting_Summariser

# Backup .env files (SECURE LOCATION ONLY!)
cp ~/lensai-meeting_Summariser/backend/.env /backup/backend-env-$(date +%Y%m%d)
```

---

## ✅ Deployment Success Checklist

After deployment, verify:

- [ ] ✅ Can access https://lenss.ai/ai
- [ ] ✅ No 404 errors on homepage
- [ ] ✅ Google OAuth login works
- [ ] ✅ Can see dashboard after login
- [ ] ✅ Backend API responds to health check
- [ ] ✅ MongoDB is connected
- [ ] ✅ Ollama is running (llama3:latest model loaded)
- [ ] ✅ Bot can join Google Meet meetings
- [ ] ✅ Transcription works
- [ ] ✅ AI summary generation works
- [ ] ✅ PDF export works
- [ ] ✅ SSL certificate is valid
- [ ] ✅ All services restart automatically on reboot
- [ ] ✅ Logs show no critical errors

---

## 📞 Need Help?

### Check Logs First
```bash
sudo journalctl -u lensai-backend -n 200 --no-pager
sudo journalctl -u lensai-frontend -n 200 --no-pager
```

### Common Log Locations
- **Backend:** `sudo journalctl -u lensai-backend`
- **Frontend:** `sudo journalctl -u lensai-frontend`
- **Nginx:** `/var/log/nginx/error.log`
- **MongoDB:** `sudo journalctl -u mongod`

### Service Management
```bash
# Restart all services
sudo systemctl restart lensai-backend lensai-frontend nginx mongod ollama

# Check all statuses
sudo systemctl status lensai-backend lensai-frontend nginx mongod ollama
```

---

## 🎉 Deployment Complete!

Your LensAI Meeting Assistant is now live at:
### **https://lenss.ai/ai**

**Key Features Deployed:**
- ✅ Google Meet bot integration
- ✅ Real-time transcription (Whisper large-v3)
- ✅ Speaker recognition & identification
- ✅ AI-powered meeting summaries (Llama3)
- ✅ Task extraction & management
- ✅ PDF export
- ✅ Concurrent meeting support (3 simultaneous meetings)
- ✅ MongoDB database
- ✅ SSL/HTTPS enabled

**Next Steps:**
1. Share access with your team
2. Monitor first few meetings closely
3. Adjust `BOT_MAX_CONCURRENT` based on actual usage
4. Set up regular backups
5. Monitor resource usage

---

**Last Updated:** $(date)
**Deployment Script:** deploy-lenss-ai.sh
**Repository:** https://github.com/ak4014263-cell/lensai-meeting_Summariser.git
