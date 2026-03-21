# IP-Track Development Guide

**Last Updated**: 2026-03-15
**Version**: 2.2.0
**Purpose**: Core development guidelines and architecture rules for AI agents and developers

---

## Project Overview

**IP-Track** is an open-source network monitoring and IP address management (IPAM) platform designed for multi-vendor enterprise environments.

### Key Capabilities
- **IP Address Tracking**: Locate IP addresses to physical switch ports via ARP/MAC correlation
- **Multi-Vendor Support**: Cisco, Dell, Alcatel/Nokia, Juniper
- **IPAM**: Automated subnet scanning and IP address lifecycle management
- **Network Data Collection**: Automated ARP/MAC table collection with hybrid CLI/SNMP strategy
- **Port Analysis**: Intelligent trunk/access port classification
- **Alarm Management**: Centralized alerting for collection failures and network issues

### Technology Stack
- **Backend**: FastAPI (async Python), SQLAlchemy 2.0, Netmiko, pysnmp
- **Frontend**: Vue 3 (Composition API), TypeScript, Element Plus
- **Database**: PostgreSQL 16
- **Cache**: Redis 6+
- **Infrastructure**: Docker Compose

---

## Core Architecture

### System Components

```
┌─────────────────────────────────────────┐
│  Vue 3 Frontend (Port 8001)             │
│  IP Lookup | Switches | IPAM | Alarms  │
└──────────────┬──────────────────────────┘
               │ REST API (Axios)
┌──────────────▼──────────────────────────┐
│  FastAPI Backend (Port 8101)            │
│  ┌──────────────────────────────────┐  │
│  │ API Layer (v1 routes)            │  │
│  └────────┬─────────────────────────┘  │
│  ┌────────▼─────────────────────────┐  │
│  │ Service Layer                    │  │
│  │ - ip_lookup                      │  │
│  │ - cli_service (SSH)              │  │
│  │ - snmp_service                   │  │
│  │ - network_data_collector         │  │
│  │ - port_analysis                  │  │
│  │ - ipam_service                   │  │
│  └────────┬─────────────────────────┘  │
│  ┌────────▼─────────────────────────┐  │
│  │ Data Layer (SQLAlchemy Models)  │  │
│  └──────────────────────────────────┘  │
└──────────────┬──────────────────────────┘
               │
        ┌──────┴──────┐
        │             │
┌───────▼──────┐ ┌───▼────────┐
│ PostgreSQL   │ │   Redis    │
│ - switches   │ │ - Cache    │
│ - arp_table  │ │ - Sessions │
│ - mac_table  │ └────────────┘
│ - ip_subnets │
└──────────────┘
```

### Backend Directory Structure
```
backend/src/
├── api/v1/              # API endpoints (switches, lookup, ipam, discovery, alarms)
├── services/            # Business logic (collectors, analysis, managers)
├── models/              # SQLAlchemy ORM models
├── schemas/             # Pydantic request/response schemas
└── core/                # Configuration, database, security
```

### Key Services

**cli_service.py**
- Executes SSH commands via Netmiko
- Multi-vendor CLI parsing (Cisco, Dell, Nokia, Juniper)
- Command template system for vendor-specific commands

**network_data_collector.py**
- Automated ARP/MAC table collection
- Hybrid strategy: CLI primary, SNMP fallback (Cisco/Dell only)
- Batch processing with concurrent execution
- Retry logic with exponential backoff

**port_analysis_service.py**
- Classifies ports as access/trunk/uplink based on MAC count, VLAN count, naming patterns
- Confidence scoring algorithm
- Used by IP lookup for trunk filtering

**ip_lookup.py**
- Cache mode: Query database (fast, <100ms)
- Realtime mode: Direct SSH to switches (accurate, 20-30s)
- Trunk port filtering to exclude inter-switch links

---

## Quick Commands

### Docker Container Management

**Restart Backend:**
```bash
sudo docker restart iptrack-backend
```

**Restart Frontend:**
```bash
sudo docker restart iptrack-frontend
```

**Restart Database:**
```bash
sudo docker restart iptrack-postgres
```

**Restart All Services:**
```bash
sudo docker restart iptrack-backend iptrack-frontend iptrack-postgres
```

**View Logs:**
```bash
# Backend logs (last 50 lines)
sudo docker logs iptrack-backend --tail 50

# Follow backend logs in real-time
sudo docker logs iptrack-backend -f

# Frontend logs
sudo docker logs iptrack-frontend --tail 50

# Database logs
sudo docker logs iptrack-postgres --tail 50
```

**Container Status:**
```bash
# Check all containers
docker ps

# Check specific container
docker ps | grep iptrack
```

**Execute Commands in Container:**
```bash
# Access backend shell
sudo docker exec -it iptrack-backend bash

# Access database
sudo docker exec -it iptrack-postgres psql -U iptrack -d iptrack

# Run Django management command (if applicable)
sudo docker exec iptrack-backend python manage.py <command>
```

### Development Workflow Commands

**After Code Changes:**
```bash
# 1. Restart backend to apply changes
sudo docker restart iptrack-backend

# 2. Check logs for errors
sudo docker logs iptrack-backend --tail 30

# 3. Test API endpoint
curl http://localhost:8101/api/v1/health
```

**Database Operations:**
```bash
# Backup database
sudo docker exec iptrack-postgres pg_dump -U iptrack iptrack > backup_$(date +%Y%m%d).sql

# Restore database
cat backup.sql | sudo docker exec -i iptrack-postgres psql -U iptrack -d iptrack

# Connect to database
sudo docker exec -it iptrack-postgres psql -U iptrack -d iptrack
```

**Clear Cache:**
```bash
# Redis cache
sudo docker exec iptrack-redis redis-cli FLUSHALL
```

### Configuration Changes

**Modify Environment Variables:**
```bash
# 1. Edit .env file
nano /opt/IP-Track/.env

# 2. After changing .env, recreate containers to reload environment variables
cd /opt/IP-Track
sudo docker compose down
sudo docker compose up -d

# OR for single service (e.g., backend only)
sudo docker stop iptrack-backend && sudo docker rm iptrack-backend
sudo docker compose up -d backend
```

**Common Configuration Examples:**

```bash
# Change IPAM scan interval (default: 60 minutes, example: 6 hours = 360 minutes)
sed -i 's/IPAM_SCAN_INTERVAL_MINUTES=60/IPAM_SCAN_INTERVAL_MINUTES=360/' /opt/IP-Track/.env

# Change network data collection interval (default: 120 minutes)
sed -i 's/COLLECTION_INTERVAL_MINUTES=120/COLLECTION_INTERVAL_MINUTES=180/' /opt/IP-Track/.env

# Change worker pool sizes
sed -i 's/COLLECTION_WORKERS=10/COLLECTION_WORKERS=20/' /opt/IP-Track/.env

# After any .env changes, recreate containers
cd /opt/IP-Track && sudo docker compose down && sudo docker compose up -d
```

**Verify Configuration Inside Container:**
```bash
# Check environment variables
sudo docker exec iptrack-backend printenv | grep IPAM
sudo docker exec iptrack-backend printenv | grep COLLECTION

# Check scheduler logs
sudo docker logs iptrack-backend | grep "scheduled (interval:"
```

---

## Configuration Rules

### Environment-Based Configuration

**ALL configuration must come from environment variables** (`.env` file) or database.

**NEVER hardcode:**
- IP addresses
- Credentials (passwords, SNMP communities)
- Performance parameters (worker pool sizes, timeouts, intervals)
- Vendor-specific settings
- Network-specific values (VLANs, subnets)

### Configuration Files

**Primary: `.env`** (root directory)
- Database credentials
- Redis connection
- Encryption key (Fernet)
- Performance tunables (worker pools, timeouts, batch sizes)
- Feature toggles
- Scheduler intervals

**Template: `.env.example`**
- Placeholder values only
- Never contains real credentials
- Committed to repository

**Settings Class: `backend/src/core/config.py`**
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    DATABASE_USER: str
    DATABASE_PASSWORD: str
    DATABASE_HOST: str = "localhost"

    # Performance
    COLLECTION_WORKERS: int = 10
    IP_LOOKUP_WORKERS: int = 50

    # Feature Toggles
    FEATURE_IPAM: bool = True

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
```

### Database-Stored Configuration

Switch-specific settings stored in `switches` table:
- IP address, credentials (encrypted)
- Vendor, model
- Collection preferences
- SNMP settings

---

## Security Rules

### Credential Protection

1. **Encryption**: All passwords encrypted with Fernet (AES-256) before storage
   ```python
   # backend/src/core/security.py
   from cryptography.fernet import Fernet
   cipher = Fernet(settings.ENCRYPTION_KEY)
   encrypted = cipher.encrypt(password.encode()).decode()
   ```

2. **Environment Variables**: Encryption key stored in `.env`, never committed
   ```bash
   # Generate key
   python scripts/generate_key.py
   ```

3. **Git Exclusions**: `.gitignore` prevents credential leaks
   ```
   .env
   .env.local
   *.backup
   ```

### What Must NEVER Be Committed

- `.env` files with real credentials
- Database dumps with production data
- Backup files (`.bak`, `.backup`, `.old`)
- SSH private keys
- Configuration files with IP addresses or credentials
- Log files with sensitive data

---

## Development Guidelines

### 1. Environment-Agnostic Code

**BAD:**
```python
switches = ["10.56.4.137", "10.64.48.25"]  # Hardcoded IPs
DATABASE_URL = "postgresql://iptrack:iptrack123@localhost/iptrack"  # Hardcoded password
```

**GOOD:**
```python
from core.config import settings
workers = ThreadPoolExecutor(max_workers=settings.IP_LOOKUP_WORKERS)
db_url = settings.DATABASE_URL  # Constructed from env vars
```

### 2. Multi-Vendor Support

When adding vendor support:

1. Add vendor to database constraint:
   ```sql
   ALTER TABLE switches ADD CONSTRAINT switches_vendor_check
   CHECK (vendor IN ('cisco', 'dell', 'alcatel', 'juniper', 'NEW_VENDOR'));
   ```

2. Add CLI parsers to `cli_service.py`:
   ```python
   def _parse_NEW_VENDOR_arp_table(self, output: str) -> List[Dict]:
       # Vendor-specific parsing logic
       pass
   ```

3. Add device type mapping:
   ```python
   VENDOR_DEVICE_TYPE_MAP = {
       'NEW_VENDOR': 'netmiko_device_type'
   }
   ```

4. Add command templates to database or config

### 3. Collection Strategy

**Hybrid Approach (Vendor-Specific):**
- **Cisco/Dell**: CLI primary, SNMP fallback (mature SNMP support)
- **Alcatel/Nokia**: CLI only (limited SNMP MIB support)
- **Juniper**: CLI primary, SNMP fallback

**Implementation Pattern:**
```python
# Try CLI first
arp_entries = await cli_service.collect_arp_table(switch)

# SNMP fallback for Cisco/Dell only
if len(arp_entries) == 0 and vendor in ['cisco', 'dell']:
    if switch.snmp_enabled:
        arp_entries = await snmp_service.collect_arp_table(switch)
```

### 4. Port Analysis and Trunk Filtering

**Critical Rule**: Always filter trunk/uplink ports from IP lookup results

**Classification Logic:**
- 1-2 MACs → Access port (high confidence)
- 3-5 MACs → Possible access (gray area)
- 6-10 MACs → Likely trunk
- >10 MACs → Trunk/uplink (high confidence)

**Usage in IP Lookup:**
```python
# Filter out trunk/uplink ports
.where(
    or_(
        PortAnalysis.id.is_(None),  # No analysis yet
        and_(
            PortAnalysis.port_type.notin_(['trunk', 'uplink']),
            PortAnalysis.mac_count <= 10
        )
    )
)
```

### 5. Modular Service Design

Each service should:
- Accept database session as parameter
- Use environment variables from `settings`
- Return structured data (not raw strings)
- Handle errors gracefully with logging
- Be testable independently

**Example:**
```python
class IPLookupService:
    def __init__(self):
        self.executor = ThreadPoolExecutor(
            max_workers=settings.IP_LOOKUP_WORKERS
        )

    async def lookup_ip(
        self,
        db: AsyncSession,
        ip_address: str,
        mode: str = "cache"
    ) -> Optional[IPLookupResult]:
        # Implementation
        pass
```

### 6. Database Migrations

- Use Alembic for schema changes
- Never modify production data in migrations
- Test migrations on development database first
- Document breaking changes

### 7. API Design

- Follow REST principles
- Use Pydantic schemas for validation
- Return consistent error responses
- Document with OpenAPI (FastAPI automatic)
- Version API endpoints (`/api/v1/...`)

### 8. Open-Source Coding Standards

**MANDATORY**: All code modifications and additions MUST follow these principles:

#### ✅ No Hardcoded Values

**BAD:**
```python
# Hardcoded thresholds
if mac_count > 10:
    port_type = 'trunk'

# Hardcoded network specifics
DEFAULT_VLAN = 99
MANAGEMENT_SUBNET = "10.56.4.0/24"

# Hardcoded device names
if switch_name.startswith('CNHZ-'):
    region = 'china'
```

**GOOD:**
```python
# Configuration-driven
if mac_count > settings.PORT_TRUNK_THRESHOLD:
    port_type = 'trunk'

# Generic logic
if subnet.vlan_id:
    vlan = subnet.vlan_id

# Pattern-based, not hardcoded
if switch.location:
    region = switch.location
```

#### ✅ Applicable to Any Dataset

**BAD:**
```typescript
// Assumes specific data structure
const topSubnets = subnets.slice(0, 5)  // Only shows first 5

// Assumes specific value ranges
if (utilization > 80) {
    chartColor = 'red'  // Hardcoded threshold
}
```

**GOOD:**
```typescript
// Configurable or dynamic
const topSubnets = subnets.slice(0, displayLimit)

// Percentage-based or configurable
const chartColor = utilization > utilizationThreshold ? 'red' : 'green'

// Works with any data size
const sortedSubnets = [...subnets].sort((a, b) => {
    const aUtil = a.utilization_percent ?? 0
    const bUtil = b.utilization_percent ?? 0
    return bUtil - aUtil  // Generic sorting
})
```

#### ✅ Automatically Handle Edge Cases (null/undefined)

**BAD:**
```python
# Crashes on None
mac_count = port_analysis.mac_count + 1

# Assumes data exists
confidence = result['confidence_score']
```

**GOOD:**
```python
# Safe with None
mac_count = (port_analysis.mac_count or 0) + 1

# Null-safe
confidence = result.get('confidence_score', 0.0)

# Multiple levels of safety
if port_analysis and port_analysis.mac_count is not None:
    mac_count = port_analysis.mac_count
else:
    mac_count = 0
```

**TypeScript:**
```typescript
// Bad
const utilization = subnet.utilization_percent * 100

// Good - handles null/undefined
const utilization = (subnet.utilization_percent ?? 0) * 100

// Good - optional chaining
const macCount = portAnalysis?.mac_count ?? 0
```

#### ✅ Suitable for Open-Source Project Release

**Checklist for Every Code Change:**
- [ ] No environment-specific values (IPs, passwords, hostnames)
- [ ] No lab/company-specific logic or naming
- [ ] All configuration via environment variables or database
- [ ] Generic error messages (no internal references)
- [ ] Works with empty/minimal datasets
- [ ] Handles missing optional fields gracefully
- [ ] Documentation uses generic examples
- [ ] No assumptions about deployment environment

**Example - Complete Refactoring:**

**Before (Lab-specific):**
```python
# CNHZ-specific logic
if switch.name.startswith('CNHZ-L3'):
    priority = 100
elif switch.name.startswith('CNHZ-L2'):
    priority = 50

# Hardcoded infrastructure
REDIS_HOST = "10.56.4.137"
ALLOWED_SUBNETS = ["10.56.0.0/16", "10.64.0.0/16"]
```

**After (Open-source ready):**
```python
# Generic role-based logic
if switch.role == 'core':
    priority = settings.CORE_SWITCH_PRIORITY
elif switch.role == 'aggregation':
    priority = settings.AGGREGATION_SWITCH_PRIORITY
else:
    priority = settings.ACCESS_SWITCH_PRIORITY

# Configuration-driven
REDIS_HOST = settings.REDIS_HOST
# No hardcoded subnet filtering - use database-configured subnets
```

**Real-World Application (IPAM Module Example):**

```typescript
// Subnet table sorting - works for any dataset
const paginatedSubnets = computed(() => {
    // Generic sorting by utilization (no hardcoded limits)
    const sortedSubnets = [...subnets.value].sort((a, b) => {
        // Safe null handling
        const aUtil = a.utilization_percent ?? 0
        const bUtil = b.utilization_percent ?? 0
        return bUtil - aUtil  // Descending order
    })

    // Dynamic pagination (works with any page size)
    const start = (currentPage - 1) * pageSize
    const end = start + pageSize
    return sortedSubnets.slice(start, end)
})
```

**Key Principles:**
1. **Configuration over Convention**: Use `settings` or database config instead of hardcoded values
2. **Defensive Programming**: Always check for null/undefined before accessing properties
3. **Generic Logic**: Write code that works for any network, any dataset, any deployment
4. **No Assumptions**: Don't assume data exists, specific formats, or value ranges

---

## Troubleshooting

### Backend Fails to Start

**Symptom:** Container restarts, logs show `ModuleNotFoundError`

**Common Causes:**

1. **Missing Python dependencies**
   ```bash
   # Check if module is installed
   docker exec iptrack-backend pip list | grep MODULE_NAME

   # Install missing module
   docker exec iptrack-backend pip install MODULE_NAME

   # Verify requirements.txt is complete
   ```

2. **Configuration validation errors**
   ```
   ValidationError: Field required [type=missing]
   ```
   - Check `.env` has all required variables
   - Compare with `.env.example`
   - Verify `backend/src/core/config.py` Settings class

3. **Database connection failure**
   - Verify PostgreSQL is running: `docker ps | grep postgres`
   - Check credentials in `.env`
   - Test connection: `docker exec iptrack-postgres pg_isready`

**Example Fix (March 2026):**
```bash
# Issue: ModuleNotFoundError: No module named 'apscheduler'
# Cause: APScheduler missing from requirements.txt
# Solution:
echo "APScheduler==3.10.4" >> backend/requirements.txt
docker exec iptrack-backend pip install APScheduler==3.10.4
docker restart iptrack-backend
```

### SQLAlchemy Concurrent Access Error

**Symptom:**
```
This session is provisioning a new connection; concurrent operations are not permitted
```

**Cause:** Multiple async tasks sharing one `AsyncSession` instance

**Solution:** Use independent database session per concurrent task
```python
async def process_switch(switch: Switch):
    async with AsyncSessionLocal() as switch_db:  # Independent session
        try:
            await collect_data(switch_db, switch)
            await switch_db.commit()
        except Exception as e:
            await switch_db.rollback()
```

### Zero MAC Entries from Switch

**Symptom:** Collection succeeds but `mac_count = 0`, port analysis empty

**Possible Causes:**
1. CLI command incorrect for vendor/model
2. Parser regex doesn't match output format
3. SSH user lacks privileges
4. L3-only device (no MAC table)

**Debugging:**
```bash
# Manual SSH test
ssh admin@SWITCH_IP
> show mac address-table  # Test command manually

# Check CLI service logs
docker logs iptrack-backend | grep "switch_id"

# Trigger manual collection with debug
curl -X POST http://localhost:8101/api/v1/switches/SWITCH_ID/collect
```

**Solution:** Verify command template and parser in `cli_service.py`

### Frontend Shows "All Offline" or No Data

**Symptom:** Switch list shows all devices offline or empty

**Causes:**

1. **Backend not running**
   ```bash
   docker ps | grep iptrack-backend
   docker logs iptrack-backend
   ```

2. **Database empty (fresh install)**
   - Add switches via UI or API
   - Wait for first collection cycle (120 min default)
   - Or trigger manual collection

3. **Status checker not running**
   - Check `.env`: `FEATURE_STATUS_CHECKER=true`
   - Verify logs: `docker logs iptrack-backend | grep "status checker"`

4. **Collection not yet run**
   - First collection happens 120 minutes after startup
   - Trigger manually: `POST /api/v1/network/collect-all`

### IPAM Shows No IP Status

**Cause:** IPAM scanner runs every 60 minutes by default

**Solution:**
- Wait for first scan cycle
- Or trigger manual scan in IPAM UI
- Check config: `IPAM_SCAN_INTERVAL_MINUTES`

---

## Quick Reference

### Environment Variables (Key Settings)

```bash
# Database
DATABASE_USER=iptrack
DATABASE_PASSWORD=secure_password
DATABASE_HOST=postgres
DATABASE_NAME=iptrack

# Security
ENCRYPTION_KEY=<generated_fernet_key>

# Performance
COLLECTION_WORKERS=10        # Concurrent switch collectors
IP_LOOKUP_WORKERS=50         # Concurrent SSH connections
COLLECTION_BATCH_SIZE=5      # Switches per batch

# Scheduler Intervals
COLLECTION_INTERVAL_MINUTES=120      # ARP/MAC collection
IPAM_SCAN_INTERVAL_MINUTES=60        # IP subnet scans
OPTICAL_MODULE_INTERVAL_MINUTES=720  # Optical module data

# Timeouts
DEFAULT_SSH_TIMEOUT=30
CLI_COMMAND_TIMEOUT=60
CONNECTION_TIMEOUT=30

# Feature Toggles
FEATURE_IPAM=true
FEATURE_ALARMS=true
FEATURE_PORT_ANALYSIS=true
FEATURE_STATUS_CHECKER=true
```

### Common Commands

```bash
# Start system
docker-compose up -d

# View logs
docker logs iptrack-backend -f
docker logs iptrack-frontend -f

# Restart services
docker restart iptrack-backend
docker restart iptrack-frontend

# Check service health
curl http://localhost:8101/api/v1/switches?limit=1
curl http://localhost:8001/

# Manual collection
curl -X POST http://localhost:8101/api/v1/network/collect-all

# Database access
docker exec -it iptrack-postgres psql -U iptrack iptrack

# Install missing dependency (with proxy)
docker exec iptrack-backend pip install --proxy http://PROXY:PORT PACKAGE
```

### File Structure Quick Reference

```
ip-track/
├── .env                    # Environment variables (NEVER commit)
├── .env.example            # Template (safe to commit)
├── docker-compose.yml      # Service orchestration
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt    # Python dependencies
│   └── src/
│       ├── main.py         # FastAPI app entry
│       ├── core/           # Config, database, security
│       ├── api/v1/         # API endpoints
│       ├── services/       # Business logic
│       ├── models/         # Database models
│       └── schemas/        # Pydantic schemas
├── frontend/
│   ├── src/
│   │   ├── views/          # Page components
│   │   ├── components/     # Reusable components
│   │   ├── api/            # API clients
│   │   └── stores/         # Pinia state
│   └── vite.config.ts      # Build config (API proxy)
├── database/
│   └── init/               # PostgreSQL init scripts
└── scripts/
    ├── generate_key.py     # Generate encryption key
    └── init_config.sh      # First-time setup
```

---

## Development Workflow

1. **Setup**: Run `./scripts/init_config.sh` to generate `.env`
2. **Start**: `docker-compose up -d`
3. **Code**: Edit in `backend/src/` or `frontend/src/`
4. **Test**: Verify changes in browser (http://localhost:8001)
5. **Debug**: Check logs with `docker logs -f`
6. **Commit**: Ensure no sensitive data in changes

---

## Contributing

When submitting changes:

1. ✅ No hardcoded IPs, credentials, or environment-specific values
2. ✅ All configuration via `.env` or database
3. ✅ Update `.env.example` if adding new config options
4. ✅ Follow existing code patterns (async/await, type hints)
5. ✅ Test with multiple vendors if modifying collectors
6. ✅ Update this guide if changing architecture

---

**Document Version**: 2.2.0
**Last Updated**: 2026-03-15
**Maintained By**: IP-Track Contributors
