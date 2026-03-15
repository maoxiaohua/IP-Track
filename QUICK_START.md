# Quick Start Guide - IP-Track Network Monitor

Get started with IP-Track in **5 minutes** using Docker, or follow the manual installation guide for custom deployments.

---

## 🚀 Method 1: Docker (Recommended)

### Prerequisites

- Docker Engine 20.10+ ([Install Docker](https://docs.docker.com/get-docker/))
- Docker Compose 2.0+ (included with Docker Desktop)
- 2GB RAM minimum, 4GB recommended
- 10GB free disk space

### Step-by-Step Installation

#### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/ip-track.git
cd ip-track
```

#### 2. Initialize Configuration

```bash
chmod +x scripts/init_config.sh
./scripts/init_config.sh
```

**What this script does:**
- ✅ Creates `.env` from `.env.example` template
- ✅ Generates secure Fernet encryption key (AES-256)
- ✅ Generates random database password
- ✅ Sets up all required environment variables

#### 3. Review Configuration (Optional)

```bash
nano .env
```

**Key settings you might want to customize:**

```bash
# Collection frequency (default: every 2 hours)
COLLECTION_INTERVAL_MINUTES=120

# Worker pool sizes (adjust based on network size)
COLLECTION_WORKERS=10           # Concurrent switch collectors
IP_LOOKUP_WORKERS=50            # Concurrent SSH connections

# CORS origins (add your custom domains)
BACKEND_CORS_ORIGINS=["http://localhost:8001","http://localhost:3000"]
```

#### 4. Start All Services

```bash
docker-compose up -d
```

**Expected output:**
```
Creating iptrack-postgres ... done
Creating iptrack-redis    ... done
Creating iptrack-backend  ... done
Creating iptrack-frontend ... done
```

#### 5. Verify Services Are Running

```bash
docker-compose ps
```

**Expected status:**
```
NAME                STATUS              PORTS
iptrack-backend     Up X minutes        0.0.0.0:8101->8100/tcp
iptrack-frontend    Up X minutes        0.0.0.0:8001->5173/tcp
iptrack-postgres    Up X minutes (healthy)  0.0.0.0:5432->5432/tcp
iptrack-redis       Up X minutes (healthy)  0.0.0.0:6379->6379/tcp
```

#### 6. Access the Application

- **Frontend**: http://localhost:8001
- **API Documentation**: http://localhost:8101/api/docs
- **API Base URL**: http://localhost:8101/api/v1

---

## 📱 Using the Application

### Add Your First Switch

1. **Navigate to Switches Page**
   - Open http://localhost:8001
   - Click **Switches** in the navigation menu
   - Click **Add Switch** button

2. **Fill in Switch Details**

   **Example for Cisco Switch:**
   ```
   Name: Core-Switch-01
   IP Address: 192.168.1.1
   Vendor: Cisco
   Model: Catalyst 3850
   SSH Port: 22
   Username: admin
   Password: ********
   Enable Password: ******** (required for Cisco)
   Connection Timeout: 30
   Enabled: ✓
   CLI Enabled: ✓
   Auto Collect ARP: ✓
   Auto Collect MAC: ✓
   ```

   **Example for Dell Force10 Switch:**
   ```
   Name: Aggregation-Switch-01
   IP Address: 192.168.1.10
   Vendor: Dell
   Model: S4048
   SSH Port: 22
   Username: admin
   Password: ********
   Enable Password: ******** (required for Force10)
   Connection Timeout: 30
   Enabled: ✓
   ```

   **Example for Nokia 7220 Switch:**
   ```
   Name: Access-Switch-01
   IP Address: 192.168.1.20
   Vendor: Alcatel
   Model: 7220 IXR-D1
   SSH Port: 22
   Username: admin
   Password: ********
   Enable Password: (leave empty - not required)
   Connection Timeout: 30
   Enabled: ✓
   ```

3. **Test Connection**
   - Click **Test** button
   - Wait for connection test result
   - ✅ Green message = Success
   - ❌ Red message = Check credentials/network connectivity

4. **Save Switch**
   - Click **Create** button
   - Switch will appear in the list

### Trigger First Collection

**Option A: Manual Collection (Immediate)**

1. Go to **Switches** page
2. Find your switch in the list
3. Click **Collect** button
4. Wait 20-60 seconds for results
5. Check **Last Collection** column for timestamp

**Option B: Wait for Auto-Collection (2 hours)**

- First automatic collection runs 120 minutes after startup
- Subsequent collections every 120 minutes (configurable)

### Lookup an IP Address

1. **Go to IP Lookup Page**
   - Click **IP Lookup** in the navigation menu

2. **Enter IP Address**
   ```
   IP Address: 192.168.1.100
   ```

3. **Select Lookup Mode**
   - **Cache**: Fast (<100ms), uses database (requires prior collection)
   - **Realtime**: Accurate (20-30s), queries switches directly
   - **Auto**: Try cache first, fallback to realtime if not found

4. **Click Lookup**

5. **View Results**
   ```
   ✅ Found at:
   Switch: Core-Switch-01 (192.168.1.1)
   Port: GigabitEthernet1/0/24
   MAC: 00:11:22:33:44:55
   VLAN: 100
   ```

### Configure IPAM (IP Address Management)

1. **Navigate to IPAM Page**
   - Click **IPAM** in the navigation menu

2. **Add a Subnet**
   - Click **Add Subnet** button
   - Fill in details:
     ```
     Subnet: 192.168.1.0/24
     Description: Office LAN
     VLAN: 100
     Auto Scan: ✓
     ```
   - Click **Create**

3. **Trigger Manual Scan** (optional)
   - Click **Scan** button on subnet row
   - Wait for scan completion
   - View IP address list and status

4. **Auto-Scan Runs Every Hour**
   - Configured via `IPAM_SCAN_INTERVAL_MINUTES` (default: 60)
   - Updates IP reachability status automatically

---

## 🛠️ Docker Management Commands

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker logs iptrack-backend -f
docker logs iptrack-frontend -f
docker logs iptrack-postgres
docker logs iptrack-redis

# Last 50 lines
docker logs iptrack-backend --tail 50
```

### Restart Services

```bash
# All services
docker-compose restart

# Specific service
docker restart iptrack-backend
docker restart iptrack-frontend
```

### Stop Services

```bash
# Stop all
docker-compose down

# Stop and remove volumes (⚠️ deletes all data)
docker-compose down -v
```

### Update Application

```bash
# Pull latest code
git pull origin main

# Rebuild and restart
docker-compose down
docker-compose build
docker-compose up -d
```

### Check Service Health

```bash
# Backend API health
curl http://localhost:8101/api/v1/switches?limit=1

# Frontend accessibility
curl http://localhost:8001

# Database connection
docker exec iptrack-postgres pg_isready -U iptrack

# Redis connection
docker exec iptrack-redis redis-cli ping
```

---

## 🐛 Troubleshooting

### Backend Won't Start

**Symptom**: `docker logs iptrack-backend` shows errors

**Common causes and solutions:**

1. **Missing Python dependencies**
   ```bash
   # Check error message
   docker logs iptrack-backend --tail 20

   # If ModuleNotFoundError, install missing package
   docker exec iptrack-backend pip install PACKAGE_NAME

   # Restart backend
   docker restart iptrack-backend
   ```

2. **Configuration validation errors**
   ```bash
   # Error: ValidationError: Field required
   # Solution: Check .env has all required fields

   diff .env .env.example
   grep -E "DATABASE_USER|DATABASE_PASSWORD|ENCRYPTION_KEY" .env
   ```

3. **Database connection failure**
   ```bash
   # Restart PostgreSQL
   docker restart iptrack-postgres

   # Wait 10 seconds, then restart backend
   sleep 10
   docker restart iptrack-backend
   ```

### All Switches Show "Offline"

**Cause**: Status checker runs every 30 seconds

**Solution**: Wait 30-60 seconds after startup, then refresh the browser.

### Cannot Connect to Switches

**Symptoms:**
- Test connection fails
- Collection returns 0 results

**Solutions:**

1. **Verify network connectivity from container**
   ```bash
   docker exec iptrack-backend ping -c 3 SWITCH_IP
   ```

2. **Test SSH manually**
   ```bash
   docker exec -it iptrack-backend ssh USERNAME@SWITCH_IP
   ```

3. **Check switch credentials**
   - Username correct?
   - Password correct?
   - Enable password required? (Cisco/Dell Force10)

4. **Check firewall rules**
   - Allow SSH (port 22) from Docker host
   - Allow SNMP (port 161) if using SNMP

### No Data After Collection

**Cause**: First collection takes 120 minutes by default

**Solutions:**

1. **Trigger manual collection**
   ```bash
   curl -X POST http://localhost:8101/api/v1/network/collect-all
   ```

2. **Or use UI**: Switches → Select switch → **Collect** button

3. **Reduce interval** (optional)
   ```bash
   # Edit .env
   COLLECTION_INTERVAL_MINUTES=30  # Collect every 30 min

   # Restart backend
   docker restart iptrack-backend
   ```

### Frontend Shows API Errors

**Symptoms:**
- Red error messages in UI
- Console shows "Network Error" or "500 Internal Server Error"

**Solutions:**

1. **Check backend is running**
   ```bash
   docker ps | grep iptrack-backend
   docker logs iptrack-backend --tail 20
   ```

2. **Check CORS configuration**
   ```bash
   # In .env
   BACKEND_CORS_ORIGINS=["http://localhost:8001"]

   # Must include your frontend URL
   ```

3. **Restart both services**
   ```bash
   docker restart iptrack-backend iptrack-frontend
   ```

### Port Conflicts

**Error**: `Bind for 0.0.0.0:8001 failed: port is already allocated`

**Solution**:

```bash
# Check what's using the port
sudo netstat -tuln | grep 8001

# Option 1: Stop conflicting service
# Option 2: Change port in docker-compose.yml

# Edit docker-compose.yml
services:
  frontend:
    ports:
      - "8002:5173"  # Change 8001 to 8002
  backend:
    ports:
      - "8102:8100"  # Change 8101 to 8102

# Restart
docker-compose down
docker-compose up -d
```

---

## ⚙️ Configuration Tips

### Change Collection Frequency

Edit `.env`:

```bash
# Collect ARP/MAC every 30 minutes
COLLECTION_INTERVAL_MINUTES=30

# Scan IPAM subnets every 15 minutes
IPAM_SCAN_INTERVAL_MINUTES=15

# Collect optical modules every 6 hours
OPTICAL_MODULE_INTERVAL_MINUTES=360
```

Then restart backend:
```bash
docker restart iptrack-backend
```

### Tune for Large Networks

For networks with 300+ switches, edit `.env`:

```bash
COLLECTION_WORKERS=20
COLLECTION_BATCH_SIZE=5
COLLECTION_INTERVAL_MINUTES=180
IP_LOOKUP_WORKERS=100
DATABASE_POOL_SIZE=30
```

### Enable Debug Logging

Edit `.env`:

```bash
DEBUG=true
LOG_LEVEL=DEBUG
```

View detailed logs:
```bash
docker logs iptrack-backend -f
```

---

## 🔒 Production Deployment Tips

1. **Change Default Passwords**
   ```bash
   # .env
   DATABASE_PASSWORD=use_strong_password_here
   ```

2. **Disable Debug Mode**
   ```bash
   DEBUG=false
   LOG_LEVEL=INFO
   ```

3. **Set Up Reverse Proxy** (Nginx/Traefik)
   ```nginx
   server {
       listen 443 ssl;
       server_name iptrack.example.com;

       location / {
           proxy_pass http://localhost:8001;
       }

       location /api {
           proxy_pass http://localhost:8101;
       }
   }
   ```

4. **Enable Regular Backups**
   ```bash
   # Backup database daily
   0 2 * * * docker exec iptrack-postgres pg_dump -U iptrack iptrack > /backups/iptrack_$(date +\%Y\%m\%d).sql
   ```

5. **Use Docker Secrets** (for sensitive data)

6. **Configure Firewall**
   ```bash
   # Allow only necessary ports
   ufw allow 22/tcp      # SSH
   ufw allow 443/tcp     # HTTPS
   ufw deny 5432/tcp     # Block external DB access
   ```

---

## 📚 Next Steps

- 📖 Read [README.md](README.md) for full documentation
- 🏗️ Review [CLAUDE.md](CLAUDE.md) for architecture details
- 🤝 Check [CONTRIBUTING.md](CONTRIBUTING.md) to contribute
- 📊 Explore [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) for feature overview
- 🌐 Browse API docs: http://localhost:8101/api/docs

---

## ❓ Need Help?

- **Issues**: [GitHub Issues](https://github.com/yourusername/ip-track/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/ip-track/discussions)
- **API Docs**: http://localhost:8101/api/docs

---

**Last Updated**: 2026-03-15
**Version**: 2.2.0
