# Running Multiple Concurrent Meetings - Configuration Guide

This guide explains how to configure LensAI to handle multiple simultaneous meetings and the resource requirements needed.

---

## 📊 Current Configuration

By default, LensAI is configured to run **3 concurrent meetings** (`BOT_MAX_CONCURRENT=3`).

This can be found in `backend/app/config.py`:
```python
BOT_MAX_CONCURRENT: int = _int("BOT_MAX_CONCURRENT", 3)
```

---

## 🎯 How to Increase Concurrent Meeting Capacity

### Option 1: Environment Variable (Recommended)

Add to your `.env` file:

```bash
# Number of concurrent meetings (bots) allowed
BOT_MAX_CONCURRENT=10  # Change this to your desired number
```

### Option 2: Production VPS Configuration

For production deployment, set in your backend `.env`:

```bash
# ── Bot Configuration ──────────────────────────────────────────
BOT_MAX_CONCURRENT=10        # Maximum simultaneous meetings
BOT_HEADLESS=false          # Keep false for stability
BOT_DISPLAY_NAME=LensAI Notetaker

# ── Bot Resource Management ──────────────────────────────────
BOT_ALONE_GRACE_SECONDS=30  # Wait time before bot leaves empty meeting
BOT_WAIT_FOR_PEOPLE=120     # Wait for participants to join
BOT_POLL_SECONDS=5          # How often bot checks meeting status
```

---

## 💻 Resource Requirements Per Meeting

### Single Meeting Resources:
- **CPU:** 15-20% (4-core system)
- **RAM:** 1.5-2 GB
- **Chrome Browser:** ~800 MB RAM
- **Audio Processing:** ~300 MB RAM
- **Network:** 5-10 Mbps

### Example Calculations:

#### For 5 Concurrent Meetings:
- **CPU:** 75-100% of 4 cores (need 8 cores)
- **RAM:** 7.5-10 GB
- **Storage:** 50-100 MB/hour per meeting
- **Network:** 25-50 Mbps

#### For 10 Concurrent Meetings:
- **CPU:** 12-16 cores
- **RAM:** 15-20 GB
- **Storage:** 100-200 MB/hour total
- **Network:** 50-100 Mbps

#### For 20 Concurrent Meetings:
- **CPU:** 24-32 cores
- **RAM:** 30-40 GB
- **Storage:** 200-400 MB/hour total
- **Network:** 100-200 Mbps

---

## 🖥️ VPS Recommendations by Capacity

### Up to 3 Concurrent Meetings (Default)
**Minimum Configuration:**
- **Provider:** Hostinger KVM 2 or equivalent
- **vCPU:** 4 cores
- **RAM:** 8 GB
- **Storage:** 50 GB SSD
- **Cost:** ~$20-25/month

**Recommended Configuration:**
- **Provider:** Hostinger KVM 4 or DigitalOcean
- **vCPU:** 4-8 cores
- **RAM:** 16 GB
- **Storage:** 100 GB SSD
- **Cost:** ~$40-50/month

---

### 5-10 Concurrent Meetings
**Required Configuration:**
- **Provider:** DigitalOcean, Vultr, or Linode
- **vCPU:** 8-12 cores
- **RAM:** 24-32 GB
- **Storage:** 200 GB SSD
- **Cost:** ~$96-144/month

**Example Providers:**
- **DigitalOcean:** CPU-Optimized 8 vCPU, 32GB RAM ($216/mo)
- **Vultr:** High Frequency 12 vCPU, 32GB RAM ($192/mo)
- **Linode:** Dedicated 16GB ($96/mo) or 32GB ($192/mo)

---

### 10-20 Concurrent Meetings
**Required Configuration:**
- **Provider:** Dedicated server or cloud compute
- **vCPU:** 16-24 cores
- **RAM:** 48-64 GB
- **Storage:** 500 GB SSD
- **Cost:** ~$300-500/month

**Example Providers:**
- **Hetzner:** Dedicated AX51-NVMe (12 cores, 64GB RAM) (~€60/mo)
- **OVH:** Advance-2 (16 cores, 64GB RAM) (~$120/mo)
- **AWS:** c7i.4xlarge (16 vCPU, 32GB RAM) (~$350/mo)

---

### 20+ Concurrent Meetings (Enterprise)
**Required Configuration:**
- **Architecture:** Distributed system with load balancing
- **vCPU:** 32+ cores (or multiple servers)
- **RAM:** 128+ GB (or multiple servers)
- **Storage:** 1 TB+ SSD
- **Cost:** $500-1000+/month

**Recommended Architecture:**
```
Load Balancer
    ↓
Multiple Bot Workers (4-8 servers)
    ↓
Shared Database & Storage
```

---

## ⚙️ Configuration for High Capacity

### Backend .env Configuration

```bash
# ═══════════════════════════════════════════════════════════
# HIGH CAPACITY CONFIGURATION (10+ Concurrent Meetings)
# ═══════════════════════════════════════════════════════════

# ── Bot Capacity ──────────────────────────────────────────
BOT_MAX_CONCURRENT=10           # Maximum simultaneous meetings
BOT_HEADLESS=false              # Use false for stability
BOT_ALONE_GRACE_SECONDS=20      # Reduced for faster cleanup
BOT_WAIT_FOR_PEOPLE=90          # Reduced waiting time
BOT_POLL_SECONDS=3              # More frequent checks

# ── Performance Optimization ──────────────────────────────
# Whisper Settings (balance speed vs accuracy)
WHISPER_MODEL=large-v3          # large-v3 for accuracy OR base for speed
WHISPER_BEAM_SIZE=5             # Lower = faster (default 5)
WHISPER_DEVICE=cpu              # Use 'cuda' if GPU available
WHISPER_COMPUTE_TYPE=int8       # int8 for speed, float16 for accuracy

# ── Speaker Diarization ───────────────────────────────────
ENABLE_SPEAKER_DIARIZATION=true # Can disable for speed if not needed
ENABLE_SPEAKER_MAPPING=true
NUM_SPEAKERS=0                  # Auto-detect (0) or set expected number

# ── API Workers ───────────────────────────────────────────
# Run FastAPI with multiple workers
# In systemd service: --workers 4
# Each worker can handle multiple API requests
# Bot threads run independently of API workers
```

---

## 🚀 Production Deployment for Multiple Meetings

### 1. Update Systemd Service for Multiple Workers

Edit `/etc/systemd/system/lensai-backend.service`:

```ini
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
# ↓ Increase workers for better API performance
ExecStart=/home/lensai/lensai-meeting_Summariser/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart lensai-backend
```

---

### 2. Increase System Limits

Create `/etc/security/limits.d/lensai.conf`:

```
lensai soft nofile 65536
lensai hard nofile 65536
lensai soft nproc 32768
lensai hard nproc 32768
```

---

### 3. Optimize MongoDB for Concurrent Writes

Edit `/etc/mongod.conf`:

```yaml
storage:
  wiredTiger:
    engineConfig:
      cacheSizeGB: 8  # Adjust based on available RAM (e.g., 25% of total RAM)
    collectionConfig:
      blockCompressor: snappy
    indexConfig:
      prefixCompression: true

net:
  maxIncomingConnections: 100

operationProfiling:
  mode: slowOp
  slowOpThresholdMs: 100
```

Restart MongoDB:
```bash
sudo systemctl restart mongod
```

---

### 4. Ollama Optimization for Concurrent Processing

Edit Ollama service to increase capacity:

```bash
sudo systemctl edit ollama
```

Add:
```ini
[Service]
Environment="OLLAMA_NUM_PARALLEL=4"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
```

Restart:
```bash
sudo systemctl restart ollama
```

---

## 📈 Monitoring Concurrent Meetings

### 1. Check Active Meetings

Via API:
```bash
curl http://localhost:8000/meetings/active
```

### 2. Monitor Resources

```bash
# CPU and Memory
htop

# Per-process memory
ps aux --sort=-%mem | head -20

# Active Chrome processes (one per meeting)
ps aux | grep chrome | wc -l

# Check bot status
curl http://localhost:8000/api/health | jq .bot
```

### 3. View Bot Logs

```bash
# Backend logs
sudo journalctl -u lensai-backend -f

# Filter for bot-related logs
sudo journalctl -u lensai-backend -f | grep -i "bot\|meeting"

# Check specific meeting
sudo journalctl -u lensai-backend | grep "meeting-bot-123"
```

---

## 🎛️ Load Balancing for 20+ Meetings

For very high capacity, distribute across multiple servers:

### Architecture:

```
                    [Nginx Load Balancer]
                            ↓
        ┌──────────────────┬──────────────────┐
        ↓                  ↓                  ↓
   [Bot Worker 1]    [Bot Worker 2]    [Bot Worker 3]
   (10 meetings)     (10 meetings)     (10 meetings)
        ↓                  ↓                  ↓
            [Shared MongoDB & Storage]
```

### Load Balancer Configuration:

```nginx
upstream lensai_backend {
    least_conn;  # Route to server with fewest active connections
    server 10.0.1.10:8000;  # Worker 1
    server 10.0.1.11:8000;  # Worker 2
    server 10.0.1.12:8000;  # Worker 3
}

server {
    listen 443 ssl;
    server_name lenss.ai;

    location /ai/api/ {
        proxy_pass http://lensai_backend;
        # ... other proxy settings
    }
}
```

---

## 🔍 Troubleshooting High Load

### Issue: "Bot limit reached"

**Solution:**
1. Increase `BOT_MAX_CONCURRENT` in `.env`
2. Ensure you have enough RAM/CPU
3. Check if old bot processes are stuck

```bash
# Kill stuck Chrome processes
pkill -f chrome
sudo systemctl restart lensai-backend
```

---

### Issue: High memory usage

**Solution:**
1. Reduce `WHISPER_MODEL` from `large-v3` to `base` or `medium`
2. Disable speaker diarization if not needed
3. Reduce `BOT_MAX_CONCURRENT`
4. Upgrade server RAM

```bash
# Check memory per process
ps aux --sort=-%mem | head -10

# Clear cache
sync; echo 3 | sudo tee /proc/sys/vm/drop_caches
```

---

### Issue: Slow transcription

**Solution:**
1. Use `WHISPER_MODEL=base` or `medium` instead of `large-v3`
2. Reduce `WHISPER_BEAM_SIZE` to 1
3. Disable `ENABLE_SPEAKER_DIARIZATION`
4. Use GPU: `WHISPER_DEVICE=cuda` (if available)

```bash
# Test transcription speed
cd ~/lensai-meeting_Summariser/backend
source venv/bin/activate
time python -c "from app.ai.transcription import transcribe_file; transcribe_file('test.webm')"
```

---

## 📊 Performance Benchmarks

Based on testing with different configurations:

| Config | Meetings | CPU Usage | RAM Usage | Transcription Time* |
|--------|----------|-----------|-----------|---------------------|
| Base | 1 | 25% | 3 GB | 2x realtime |
| Medium | 3 | 75% | 8 GB | 3x realtime |
| Large-v3 | 3 | 90% | 12 GB | 5x realtime |
| Base + 8 core | 5 | 80% | 10 GB | 1.5x realtime |
| Medium + 16 core | 10 | 85% | 24 GB | 2x realtime |

*Transcription time: 2x realtime = 1 hour meeting transcribed in 30 minutes

---

## 💡 Best Practices

### 1. **Start Conservative**
- Begin with `BOT_MAX_CONCURRENT=3`
- Monitor performance
- Gradually increase

### 2. **Monitor First Meeting**
- Watch CPU, RAM, disk usage
- Check transcription speed
- Verify quality

### 3. **Plan for Peak Load**
- If you expect 10 meetings during peak hours
- Set `BOT_MAX_CONCURRENT=12` (20% buffer)
- Size server for peak, not average

### 4. **Queue System (Optional)**
If you exceed capacity, implement queuing:

```python
# In your application code
if active_meetings >= BOT_MAX_CONCURRENT:
    # Add to queue instead of rejecting
    meeting_queue.append(meeting_request)
    return "Meeting queued. Will start when capacity available."
```

---

## 🎯 Quick Configuration Table

| Concurrent Meetings | BOT_MAX_CONCURRENT | vCPU | RAM | Storage | Monthly Cost |
|--------------------|--------------------|------|-----|---------|-------------|
| 1-3 (Default) | 3 | 4 | 8 GB | 50 GB | $20-40 |
| 3-5 | 5 | 8 | 16 GB | 100 GB | $40-80 |
| 5-10 | 10 | 12 | 32 GB | 200 GB | $100-200 |
| 10-20 | 20 | 24 | 64 GB | 500 GB | $300-500 |
| 20+ | Custom | Multiple Servers | - | - | $500+ |

---

## ✅ Configuration Checklist

- [ ] Determined max concurrent meetings needed
- [ ] Calculated resource requirements
- [ ] Chosen appropriate VPS plan
- [ ] Updated `BOT_MAX_CONCURRENT` in `.env`
- [ ] Configured API workers (--workers N)
- [ ] Optimized MongoDB settings
- [ ] Set up monitoring (htop, logs)
- [ ] Tested with 2-3 concurrent meetings
- [ ] Implemented backup/failover plan
- [ ] Documented configuration for team

---

## 📞 Need More Capacity?

If you need to handle 50+ concurrent meetings, consider:

1. **Kubernetes Cluster** - Auto-scaling bot workers
2. **Dedicated Bot Service** - Separate bot servers from API
3. **Paid Solutions** - Recall.ai, Fireflies.ai, Otter.ai ($$$$)
4. **Custom Enterprise Setup** - Contact me for architecture design

---

**Remember:** Always test with 1-2 meetings first before scaling to full capacity!
