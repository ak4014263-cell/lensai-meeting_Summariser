# 🏢 LensAI Enterprise: 100 Concurrent Meetings Deployment

## 📊 Infrastructure Requirements for 100 Concurrent Meetings

### Single Server Approach (NOT Recommended)
This is **technically possible** but will require a very powerful dedicated server:

**Minimum Specifications:**
- **CPU:** 80-100 cores (AMD EPYC or Intel Xeon)
- **RAM:** 200-250 GB
- **Storage:** 2-4 TB NVMe SSD
- **Network:** 500 Mbps - 1 Gbps dedicated
- **Cost:** $800-1500/month

**Providers:**
- Hetzner AX161 (AMD EPYC 7502P, 32 cores, 256GB RAM) - €189/mo (~$200)
- OVH Scale-2 (AMD EPYC 7763, 64 cores, 256GB RAM) - $450/mo
- AWS c7i.metal (128 vCPU, 256GB RAM) - ~$4,500/mo

---

## ⭐ RECOMMENDED: Distributed Architecture

For 100 concurrent meetings, you should use **multiple bot worker servers** with a load balancer.

### Architecture Overview:

```
                    [Nginx Load Balancer]
                     lenss.ai/ai
                            ↓
        ┌──────────────┬───────────────┬──────────────┐
        ↓              ↓               ↓              ↓
   [Bot Worker 1] [Bot Worker 2] [Bot Worker 3] [Bot Worker 4]
   (25 meetings)  (25 meetings)  (25 meetings)  (25 meetings)
        ↓              ↓               ↓              ↓
                [Shared MongoDB Cluster]
                [Shared Storage (NFS/S3)]
```

### Infrastructure Components:

#### 1. Load Balancer (1 server)
- **Specs:** 4 vCPU, 8GB RAM
- **Cost:** $40/mo (DigitalOcean, Vultr)
- **Purpose:** Distribute requests to bot workers

#### 2. Bot Workers (4-5 servers)
Each handles 20-25 concurrent meetings:
- **Specs per worker:** 24 vCPU, 64GB RAM, 500GB SSD
- **Cost per worker:** $150-200/mo
- **Total for 5 workers:** $750-1000/mo

#### 3. Database Cluster (3 servers for MongoDB replica set)
- **Primary:** 8 vCPU, 32GB RAM
- **Secondary 1:** 8 vCPU, 32GB RAM  
- **Secondary 2:** 8 vCPU, 32GB RAM
- **Cost:** $400-500/mo total

#### 4. Shared Storage (NFS or S3)
- **Purpose:** Store recordings, transcripts, PDFs
- **Storage:** 5-10 TB
- **Cost:** $50-150/mo

**Total Monthly Cost:** $1,240 - 1,690/mo

---

## 🚀 Option 1: Single Powerful Server (Quick Start)

If you want to test with a single server first:

### Recommended Server:
**Hetzner AX161**
- AMD EPYC 7502P (32 cores / 64 threads)
- 256 GB DDR4 ECC RAM
- 2x 3.84 TB NVMe SSD
- 1 Gbit/s network
- **Cost:** €189/mo (~$205/mo)

**Order:** https://www.hetzner.com/dedicated-rootserver/ax161

### Alternative: OVH Scale-2
- AMD EPYC 7763 (64 cores / 128 threads)
- 256 GB DDR4 RAM
- 2x 960 GB NVMe SSD
- 3 Gbit/s network
- **Cost:** ~$450/mo

**Order:** https://www.ovhcloud.com/en/bare-metal/scale/

---

## ⚙️ Configuration for 100 Concurrent Meetings

### 1. Backend .env Configuration

```bash
# ═══════════════════════════════════════════════════════════
# ENTERPRISE CONFIGURATION (100 Concurrent Meetings)
# ═══════════════════════════════════════════════════════════

# ── Bot Capacity ──────────────────────────────────────────
BOT_MAX_CONCURRENT=100          # 100 simultaneous meetings
BOT_HEADLESS=false              # Keep false for stability
BOT_ALONE_GRACE_SECONDS=15      # Faster cleanup
BOT_WAIT_FOR_PEOPLE=60          # Reduced waiting time
BOT_POLL_SECONDS=3              # Frequent status checks

# ── Performance: Use FASTER Whisper model ─────────────────
# For 100 meetings, accuracy vs speed trade-off is critical
WHISPER_MODEL=base              # base (fastest) or medium (balanced)
WHISPER_BEAM_SIZE=1             # Minimum for speed
WHISPER_DEVICE=cpu              # Use 'cuda' if GPU available
WHISPER_COMPUTE_TYPE=int8       # Fastest compute type

# ── Speaker Diarization (Optional for speed) ──────────────
ENABLE_SPEAKER_DIARIZATION=false # Disable for 2-3x speed boost
ENABLE_SPEAKER_MAPPING=true      # Keep lightweight mapping
NUM_SPEAKERS=0

# ── Ollama LLM Optimization ───────────────────────────────
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=llama3:latest
OLLAMA_NUM_CTX=8192            # Reduced context for speed
OLLAMA_TEMPERATURE=0.2
OLLAMA_TIMEOUT=600             # 10 minutes max
# Ollama parallel processing
OLLAMA_NUM_PARALLEL=8          # Process 8 summaries at once
OLLAMA_MAX_LOADED_MODELS=2

# ── Database ──────────────────────────────────────────────
MONGODB_URL=mongodb://localhost:27017
MONGO_DB_NAME=lensai_production
# For replica set:
# MONGODB_URL=mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0

# ── Memory Management ─────────────────────────────────────
# Reduce memory per bot
LLM_CHUNK_CHARS=16000          # Smaller chunks
LLM_CHUNK_OVERLAP_CHARS=1000
LLM_MAX_CHUNKS=50              # Limit processing

# ── System ────────────────────────────────────────────────
DISPLAY=:99
```

### 2. System Limits Configuration

Create `/etc/security/limits.d/lensai.conf`:

```conf
# LensAI Enterprise: 100 Concurrent Meetings
*               soft    nofile          500000
*               hard    nofile          500000
*               soft    nproc           500000
*               hard    nproc           500000
root            soft    nofile          500000
root            hard    nofile          500000
root            soft    nproc           500000
root            hard    nproc           500000
```

Edit `/etc/sysctl.conf`:

```conf
# Network tuning for 100 concurrent connections
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_fin_timeout = 30

# Memory management
vm.swappiness = 10
vm.vfs_cache_pressure = 50
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5

# File descriptors
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
```

Apply:
```bash
sudo sysctl -p
```

### 3. Systemd Service (Increased Workers)

Edit `/etc/systemd/system/lensai-backend.service`:

```ini
[Unit]
Description=LensAI Backend API - Enterprise (100 meetings)
After=network.target mongod.service ollama.service xvfb.service
Requires=mongod.service ollama.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/lensai-meeting_Summariser/backend
Environment="PATH=/root/lensai-meeting_Summariser/backend/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="DISPLAY=:99"
# 16 API workers for handling 100 concurrent meeting requests
ExecStart=/root/lensai-meeting_Summariser/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 16 --timeout-keep-alive 300
Restart=always
RestartSec=10
# Increase limits
LimitNOFILE=500000
LimitNPROC=500000

[Install]
WantedBy=multi-user.target
```

Reload:
```bash
sudo systemctl daemon-reload
sudo systemctl restart lensai-backend
```

### 4. MongoDB Optimization

Edit `/etc/mongod.conf`:

```yaml
storage:
  dbPath: /var/lib/mongodb
  journal:
    enabled: true
  wiredTiger:
    engineConfig:
      cacheSizeGB: 80  # 30-40% of total RAM (e.g., 80GB on 256GB server)
      journalCompressor: snappy
      directoryForIndexes: true
    collectionConfig:
      blockCompressor: snappy
    indexConfig:
      prefixCompression: true

net:
  port: 27017
  bindIp: 0.0.0.0
  maxIncomingConnections: 2000  # Handle many concurrent connections

operationProfiling:
  mode: slowOp
  slowOpThresholdMs: 100

replication:
  # For replica set (distributed setup)
  # replSetName: "rs0"

# Enable sharding for very large deployments
# sharding:
#   clusterRole: shardsvr
```

Restart:
```bash
sudo systemctl restart mongod
```

### 5. Ollama Optimization

```bash
sudo systemctl edit ollama
```

Add:
```ini
[Service]
Environment="OLLAMA_NUM_PARALLEL=8"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
Environment="OLLAMA_KEEP_ALIVE=24h"
```

Restart:
```bash
sudo systemctl restart ollama
```

### 6. Nginx Configuration (Enterprise)

```nginx
# Upstream for load balancing (if using multiple workers)
upstream lensai_backend {
    least_conn;  # Route to server with fewest connections
    
    # For single server
    server 127.0.0.1:8000;
    
    # For distributed setup, add worker IPs:
    # server 10.0.1.10:8000 max_fails=3 fail_timeout=30s;
    # server 10.0.1.11:8000 max_fails=3 fail_timeout=30s;
    # server 10.0.1.12:8000 max_fails=3 fail_timeout=30s;
    # server 10.0.1.13:8000 max_fails=3 fail_timeout=30s;
    
    keepalive 512;  # Keep connections alive
}

server {
    listen 443 ssl http2;
    server_name lenss.ai www.lenss.ai;
    
    ssl_certificate /etc/letsencrypt/live/lenss.ai/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/lenss.ai/privkey.pem;
    
    client_max_body_size 500M;
    client_body_timeout 300s;
    
    # Connection limits
    limit_conn_zone $binary_remote_addr zone=addr:10m;
    limit_conn addr 100;
    
    location /ai/api/ {
        rewrite ^/ai/api/(.*) /$1 break;
        proxy_pass http://lensai_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts for long meetings
        proxy_read_timeout 600s;
        proxy_connect_timeout 75s;
        proxy_send_timeout 600s;
        
        # Keep-alive
        proxy_set_header Connection "";
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
    }
    
    location /ai/ {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

---

## 🔄 Distributed Setup (4 Bot Workers)

### Load Balancer Server (lenss.ai)
**IP:** 200.97.170.172
**Specs:** 4 vCPU, 8GB RAM
**Role:** Nginx reverse proxy + Frontend

### Bot Worker Servers

#### Worker 1 (10.0.1.10)
```bash
BOT_MAX_CONCURRENT=25
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

#### Worker 2 (10.0.1.11)
```bash
BOT_MAX_CONCURRENT=25
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

#### Worker 3 (10.0.1.12)
```bash
BOT_MAX_CONCURRENT=25
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

#### Worker 4 (10.0.1.13)
```bash
BOT_MAX_CONCURRENT=25
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Shared MongoDB Cluster
Set up 3-node replica set for high availability.

---

## 📊 Resource Calculations

### Per Meeting Resource Usage:
- **CPU:** 0.8-1.0 core (per meeting)
- **RAM:** 2-2.5 GB (per meeting)
- **Network:** 5-10 Mbps
- **Storage:** 100-200 MB/hour

### For 100 Concurrent Meetings:
- **CPU:** 80-100 cores
- **RAM:** 200-250 GB
- **Network:** 500 Mbps - 1 Gbps
- **Storage:** 10-20 GB/hour (2TB/week)

---

## 🚀 Deployment Scripts

### Enterprise Deployment Script

Create `deploy-enterprise-100.sh`:

```bash
#!/bin/bash

set -e

echo "================================================"
echo "  LensAI Enterprise: 100 Concurrent Meetings"
echo "================================================"

# Install dependencies (same as before)
sudo apt update && sudo apt upgrade -y

# System optimization
sudo tee -a /etc/sysctl.conf > /dev/null <<EOF
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.ip_local_port_range = 1024 65535
vm.swappiness = 10
fs.file-max = 2097152
EOF

sudo sysctl -p

# Increase limits
sudo tee /etc/security/limits.d/lensai.conf > /dev/null <<EOF
*               soft    nofile          500000
*               hard    nofile          500000
*               soft    nproc           500000
*               hard    nproc           500000
EOF

# Clone and setup (same as standard deployment)
cd ~
git clone https://github.com/ak4014263-cell/lensai-meeting_Summariser.git
cd lensai-meeting_Summariser/backend

# Update .env
cat >> .env <<EOF
BOT_MAX_CONCURRENT=100
WHISPER_MODEL=base
ENABLE_SPEAKER_DIARIZATION=false
OLLAMA_NUM_PARALLEL=8
EOF

# Setup systemd with 16 workers
sudo tee /etc/systemd/system/lensai-backend.service > /dev/null <<SYSEOF
[Unit]
Description=LensAI Backend API - Enterprise
After=network.target mongod.service ollama.service xvfb.service
Requires=mongod.service ollama.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/lensai-meeting_Summariser/backend
Environment="PATH=/root/lensai-meeting_Summariser/backend/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="DISPLAY=:99"
ExecStart=/root/lensai-meeting_Summariser/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 16
Restart=always
RestartSec=10
LimitNOFILE=500000
LimitNPROC=500000

[Install]
WantedBy=multi-user.target
SYSEOF

sudo systemctl daemon-reload
sudo systemctl enable lensai-backend
sudo systemctl start lensai-backend

echo "✅ Enterprise deployment complete!"
echo "🚀 Ready for 100 concurrent meetings"
```

---

## 📈 Monitoring for 100 Meetings

### Install Monitoring Tools

```bash
# htop for resource monitoring
sudo apt install -y htop

# Prometheus + Grafana (optional but recommended)
# Follow: https://prometheus.io/docs/prometheus/latest/installation/
```

### Monitor Active Meetings

```bash
# Count active Chrome processes (= active meetings)
ps aux | grep chrome | wc -l

# Memory usage by Chrome
ps aux --sort=-%mem | grep chrome | head -20

# API endpoint
curl https://lenss.ai/ai/api/meetings/active | jq '. | length'
```

### Resource Alerts

Create `/root/monitor.sh`:

```bash
#!/bin/bash

# Alert if CPU > 90%
CPU=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
if (( $(echo "$CPU > 90" | bc -l) )); then
    echo "⚠️  HIGH CPU: ${CPU}%"
fi

# Alert if RAM > 90%
MEM=$(free | grep Mem | awk '{printf("%.0f", $3/$2 * 100.0)}')
if [ $MEM -gt 90 ]; then
    echo "⚠️  HIGH MEMORY: ${MEM}%"
fi

# Count active meetings
MEETINGS=$(ps aux | grep chrome | wc -l)
echo "📊 Active meetings: $MEETINGS"
```

Run every 5 minutes:
```bash
chmod +x /root/monitor.sh
(crontab -l 2>/dev/null; echo "*/5 * * * * /root/monitor.sh >> /var/log/lensai-monitor.log") | crontab -
```

---

## 🐛 Troubleshooting 100 Meetings

### Issue: "Too many open files"

```bash
# Increase limits
ulimit -n 500000

# Verify
ulimit -n
```

### Issue: High memory usage

```bash
# Clear cache
sync; echo 3 | sudo tee /proc/sys/vm/drop_caches

# Kill stuck Chrome processes
pkill -f "chrome.*--user-data-dir=.*/meeting-bot-"

# Restart backend
sudo systemctl restart lensai-backend
```

### Issue: Slow transcriptions

```bash
# Switch to faster Whisper model
cd ~/lensai-meeting_Summariser/backend
nano .env

# Change to:
WHISPER_MODEL=tiny  # or base
ENABLE_SPEAKER_DIARIZATION=false

# Restart
sudo systemctl restart lensai-backend
```

### Issue: MongoDB connection pool exhausted

Edit `/etc/mongod.conf`:
```yaml
net:
  maxIncomingConnections: 5000
```

Restart:
```bash
sudo systemctl restart mongod
```

---

## 💰 Cost Comparison

### Single Server (Hetzner AX161)
- **Cost:** $205/mo
- **Capacity:** 80-100 meetings
- **Pros:** Simple setup, single point of management
- **Cons:** No redundancy, all eggs in one basket

### Distributed (4 Workers + DB Cluster)
- **Cost:** $1,240-1,690/mo
- **Capacity:** 100+ meetings (scalable)
- **Pros:** High availability, horizontal scaling
- **Cons:** More complex, requires load balancing

### Cloud (AWS/GCP)
- **Cost:** $3,000-5,000/mo
- **Pros:** Managed services, auto-scaling
- **Cons:** Very expensive

---

## ✅ Testing 100 Meetings

### Load Test Script

```python
# test_load.py
import asyncio
import aiohttp
import time

async def start_meeting(session, meeting_num):
    url = "https://lenss.ai/ai/api/meetings"
    data = {
        "meet_url": f"https://meet.google.com/test-{meeting_num}",
        "title": f"Load Test Meeting {meeting_num}"
    }
    
    async with session.post(url, json=data) as response:
        result = await response.json()
        print(f"Meeting {meeting_num}: {result.get('status')}")
        return result

async def main():
    start_time = time.time()
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for i in range(1, 101):  # 100 meetings
            task = asyncio.create_task(start_meeting(session, i))
            tasks.append(task)
            
            # Stagger starts by 5 seconds
            if i % 10 == 0:
                await asyncio.sleep(5)
        
        results = await asyncio.gather(*tasks)
    
    elapsed = time.time() - start_time
    print(f"\n✅ Started {len(results)} meetings in {elapsed:.2f} seconds")

if __name__ == "__main__":
    asyncio.run(main())
```

Run:
```bash
pip install aiohttp
python test_load.py
```

---

## 🎯 Recommended Approach

### Phase 1: Single Server Testing (Week 1)
1. Deploy on Hetzner AX161 ($205/mo)
2. Test with 10-20 meetings
3. Gradually increase to 50 meetings
4. Monitor performance

### Phase 2: Optimization (Week 2)
1. Tune Whisper model (base vs medium)
2. Optimize database queries
3. Reduce memory per bot
4. Test up to 80 meetings

### Phase 3: Full Load (Week 3)
1. Attempt 100 meetings
2. If performance issues, consider distributed setup
3. Monitor for 24-48 hours

### Phase 4: Production (Week 4)
1. Setup monitoring/alerting
2. Backup strategy
3. Document runbooks
4. Train team on operations

---

## 📞 Support Scaling Path

### Current: 3 meetings → $40/mo
### Target: 100 meetings

**Option A:** Single powerful server - $205/mo
**Option B:** Distributed 4 workers - $1,200/mo
**Option C:** Cloud managed - $3,000-5,000/mo

**I recommend:** Start with Option A (Hetzner AX161), then scale to Option B if needed.

---

## ✅ Final Checklist for 100 Meetings

- [ ] Ordered Hetzner AX161 or equivalent (32+ cores, 256GB RAM)
- [ ] Updated BOT_MAX_CONCURRENT=100 in .env
- [ ] Switched to WHISPER_MODEL=base for speed
- [ ] Increased system limits (file descriptors, connections)
- [ ] Configured MongoDB for high concurrency
- [ ] Setup systemd with 16 API workers
- [ ] Configured Ollama for parallel processing
- [ ] Setup monitoring (htop, logs, custom scripts)
- [ ] Load tested with 10, 25, 50 meetings
- [ ] Documented runbooks for ops team
- [ ] Backup strategy in place
- [ ] Budget approved (~$200-1500/mo)

---

**🚀 Ready to handle 100 concurrent meetings!**

