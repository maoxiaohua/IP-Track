# IP-Track Network Monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue.js-3.x-brightgreen.svg)](https://vuejs.org/)

A production-ready, open-source network monitoring platform for tracking IP addresses, managing switches, and monitoring network devices across multi-vendor environments. Built as a **microservice architecture** with 3 backend services and a modern Vue 3 frontend.

> **🔒 Privacy note**: This project and its documentation never require real network addressing information. All examples in this README use reserved documentation ranges only.

## ✨ Features

- **IP Address Lookup**: Track IP addresses to switch ports with cache and realtime modes, powered by a weighted IP-location matching engine
- **Multi-Vendor Support**: Cisco (IOS/NX-OS), Dell (Force10/OS10), Alcatel/Nokia (SR OS / SR Linux) selectable in the UI; command templates for Juniper/Arista/HPE/Huawei exist in `collection_strategy.py` but are not exposed in the UI yet
- **Hybrid CLI/SNMP Collection**: Per-vendor collection strategy — CLI primary with SNMP fallback, or fully configurable per switch
- **IPAM**: IP Address Management with automated subnet scanning
  - **Large-scale subnet support**: batch create, Excel import, template download — designed for **1000+ subnets**
  - **Live scan progress**: streaming scan results with real-time progress events
  - **IP enrichment**: hostname / machine type / vendor / last boot time collected via SNMP `sysName` / `sysDescr` / `sysUpTime`, plus mDNS hostname source
  - **Hostname search**: search IP inventory by hostname across the whole address space
  - **OS-type device inventory**: filter the address space by operating system / device type
- **Automated Network Data Collection**: ARP/MAC table collection on a schedule with retry, backoff, and a queued job system
- **Port Analysis**: Intelligent trunk/access port classification with confidence scoring and per-switch lookup-policy overrides
- **Optical Modules**: Monitor SFP/SFP+ module health (temperature, power, wavelength)
- **Alarm Management**: Comprehensive alerting with acknowledge / resolve / auto-resolve and configurable retention
- **Status Checker**: Periodic switch connectivity monitoring (ICMP ping every 300 seconds by default)
- **Switch Discovery**: Batch discovery of switches across network ranges via SNMP, with duplicate detection
- **BMC Reset Management**: Manage BMC servers, credential profiles, and reset history with verification workflows
- **Data Freshness**: Per-switch collection freshness indicators for port analysis, lookup, and optical inventory
- **Query History**: Persistent lookup history with revisiting and export
- **Modern UI**: Vue 3 + TypeScript frontend with Element Plus, ECharts, and Pinia state management
- **RESTful API**: FastAPI backend; OpenAPI docs are **disabled by default** (`API_DOCS_ENABLED=true` to enable `/docs`)
- **Authentication**: JWT login with admin/viewer roles; unauthenticated access is read-only

## 🏗️ Architecture

### Microservices Overview

| Service | Entry Point | Internal Port | Host Port | Responsibility |
|---------|-------------|---------------|-----------|----------------|
| `iptrack-backend-core` | `backend/src/main_core.py` | 8100 | 8101 | Switch CRUD, IP lookup, history, alarms, SNMP profiles, SNMP OID overrides, command templates, settings, BMC |
| `iptrack-backend-ipam` | `backend/src/main_ipam.py` | 8100 | 8102 | IPAM: subnets, IP inventory, scanning, enrichment, hostname search, dashboard |
| `iptrack-backend-collector` | `backend/src/main_collector.py` | 8100 | 8103 | ARP/MAC/optical collection, switch discovery, port analysis, CLI/SNMP collection |
| `iptrack-frontend` | Vite dev server | 5173 | 8001 | Vue 3 SPA |

### ⚠️ Critical Port Rule

- **All backend containers listen on port `8100` internally**, regardless of their function.
- Host ports `8101 / 8102 / 8103` are **only** for reaching the containers from the host machine.
- **Inter-container traffic (including the frontend Vite proxy) must always use the internal port `8100`**, never `8101/8102/8103`.

```text
                    ┌───────────────────────────────┐
                    │    Vue 3 Frontend (port 8001)  │
                    │ Lookup | Switches | IPAM | ... │
                    └───────┬───────────────────────┘
                            │ REST API (Vite proxy → :8100)
        ┌───────────────────┼───────────────────────┐
        │                   │                       │
┌───────▼─────────┐ ┌───────▼─────────┐ ┌───────────▼─────────┐
│ backend-core    │ │ backend-ipam    │ │ backend-collector   │
│ :8100 (host8101)│ │ :8100 (host8102)│ │ :8100 (host8103)    │
│ switches        │ │ subnets/IPAM    │ │ collection          │
│ lookup/history  │ │ scan/enrich     │ │ discovery           │
│ alarms/snmp/bmc │ │ hostname search │ │ port analysis       │
└───┬────────┬────┘ └────┬────────┬───┘ └───┬────────┬────────┘
    │        │           │        │          │        │
┌───▼────┐ ┌─▼─────┐     │        │          │        │
│Postgres│ │ Redis │     │        │          │        │
│  16    │ │  7    │     │        │          │        │
└────────┘ └───────┘     └────────┘          └────────┘
            (shared database & cache, internal network)
```

### Background Services

IP-Track runs several automated background tasks:

1. **Status Checker** (every 300 seconds by default, `STATUS_CHECK_INTERVAL_SECONDS`)
   - ICMP ping all enabled switches
   - Updates reachability, response time, last-check timestamp

2. **Network Data Collection** (default every 120 minutes)
   - Collects ARP and MAC tables from all switches (CLI/SNMP hybrid)
   - Runs port analysis (trunk/access classification)
   - Updates the IP location database
   - Retry / backoff / queued job handling via a collection worker pool

3. **IPAM Auto-Scan** (default every 60 minutes via `IPAM_SCAN_INTERVAL_MINUTES`; code default 30)
   - Scans configured subnets and updates IP reachability
   - Enriches IPs with hostname / machine type / vendor / last boot time
   - Tracks IP lifecycle and preserves IP identity across empty scans

4. **Optical Module Collection** (default every 720 minutes)
   - Collects SFP/SFP+ module information
   - Monitors temperature, TX/RX power, wavelength

5. **Alarm Cleanup** (daily at 3:00 AM)
   - Removes old alarms (default: 30 days retention)

6. **BMC Reset Scheduler**
   - Drives queued BMC resets, tracks verification status, and records history

## 🚀 Quick Start

### Prerequisites

- **Docker & Docker Compose** (recommended) — easiest deployment method
- OR **Python 3.11+**, **PostgreSQL 16+**, and **Redis 7+** for a manual install

### Installation (Docker — Recommended)

> Full walkthrough with screenshots-free step-by-step and first-use flow: **[QUICK_START.md](QUICK_START.md)**.
> No Docker available? See **[MANUAL_DEPLOYMENT.md](MANUAL_DEPLOYMENT.md)**.

1. **Clone the repository**
   ```bash
   sudo mkdir -p /opt/IP-Track
   git clone https://github.com/your-org/ip-track.git /opt/IP-Track
   cd /opt/IP-Track
   ```

2. **Build the backend image (required — compose only references the image)**
   ```bash
   docker build -t ip-track-backend:latest ./backend
   ```

3. **Run the setup script**
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```
   This script:
   - Creates `.env` from `.env.example`
   - Generates `ENCRYPTION_KEY`, `DATABASE_PASSWORD`, `REDIS_PASSWORD`
   - Starts PostgreSQL/Redis, applies `database/migrations/*.sql` (idempotent)
   - Starts all 6 containers and waits for health checks

   > If the frontend image fails to build (unreachable Node base image, npm registry or a required proxy), set `NODE_IMAGE` / `NPM_REGISTRY` / `NPM_PROXY` in `.env` — no Dockerfile edit needed — then run `docker compose up -d --build frontend`. See [QUICK_START.md §2](QUICK_START.md#第-3-步运行安装脚本).

4. **Verify services are running**
   ```bash
   docker compose ps
   ```
   Expected: 6 containers — `iptrack-postgres`, `iptrack-redis`, `iptrack-backend-core`, `iptrack-backend-ipam`, `iptrack-backend-collector`, `iptrack-frontend`.
   Default bindings are host-local only: `127.0.0.1:5432/6379/8101/8102/8103`, frontend on `0.0.0.0:8001`.

   ```bash
   for p in 8101 8102 8103; do
     printf "backend %s " $p
     curl --noproxy '*' -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:$p/health
   done
   curl --noproxy '*' -s -o /dev/null -w "frontend %{http_code}\n" http://127.0.0.1:8001/
   ```

5. **Get the initial admin password** (printed once to the core log)
   ```bash
   docker compose logs backend-core | grep 初始管理员
   ```
   Unauthenticated users are read-only; creating/modifying/deleting requires login.
   First login forces a password change (min. 8 characters).

6. **Access the application**
   - **Frontend UI**: http://YOUR_SERVER_IP:8001
   - **Health checks**: `:8101/health` (core), `:8102/health` (IPAM), `:8103/health` (collector)
   - **API base URL**: http://YOUR_SERVER_IP:8101/api/v1
   - **API docs**: disabled by default; set `API_DOCS_ENABLED=true` in `.env`, then `docker compose up -d`

### First Steps

1. **Open the web UI** at http://YOUR_SERVER_IP:8001 and **log in** with `admin` / the temporary password from step 5
2. **Add your first switch**:
   - Navigate to **Switches → 新增交换机**
   - Fill in switch details:
     - Name (e.g., `core-sw-01`)
     - IP Address (e.g., `192.0.2.10` — documentation range)
     - Vendor (the UI currently offers **Cisco / Dell / Alcatel-Lucent**)
     - Model
     - CLI protocol (SSH/Telnet), username and password
     - Enable password (if required by the vendor)
     - SNMP (optional): credentials source — a profile from **More → SNMP Profiles**, or inline
   - Click **测试** to verify, then **保存**
3. **Enable auto-collection** or trigger a manual collection (collect first — lookup reads the cache)
4. **Start using IP Lookup** to locate devices on the network (e.g., look up `203.0.113.50`)

## 📖 Documentation

**Deploy / operate**
- **[QUICK_START.md](QUICK_START.md)** — Docker 首次部署 + 首次使用（首选）
- **[MANUAL_DEPLOYMENT.md](MANUAL_DEPLOYMENT.md)** — 没有 Docker，用 systemd + Nginx 部署
- **[INTERNAL_DEPLOYMENT.md](INTERNAL_DEPLOYMENT.md)** — 运维、备份恢复、监控、性能调优、故障排查
- **[QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)** — 主机名 / OS 类型 / Last Boot Time 专项排障

**Design / reference**
- **Microservices Architecture**: [MICROSERVICES_ARCHITECTURE.md](MICROSERVICES_ARCHITECTURE.md)
- **IPAM Feature Guide**: [IPAM_FEATURES_GUIDE.md](IPAM_FEATURES_GUIDE.md)
- **IPAM Scan Enhancements**: [IPAM_SCAN_ENHANCEMENT.md](IPAM_SCAN_ENHANCEMENT.md)
- **Collection Strategy**: [COLLECTION_STRATEGY_OPTIMIZATION.md](COLLECTION_STRATEGY_OPTIMIZATION.md)
- **Project Summary**: [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)
- **Configuration Reference**: [.env.example](.env.example)
- **Development Rules**: [CLAUDE.md](CLAUDE.md)

> `NMAP_INSTALL_GUIDE.md` / `install_nmap.sh` are outdated: nmap is **not used** by the current scan path (OS type comes from TTL + SNMP). See [QUICK_START_GUIDE.md §1](QUICK_START_GUIDE.md#1-关于-nmap当前版本不参与扫描).
>
> Interactive API docs are **disabled by default** (`/docs` → 404). Enable with `API_DOCS_ENABLED=true`, then open http://127.0.0.1:8101/docs.

## 🛠️ Configuration

IP-Track uses **environment variables exclusively** for all configuration — no hardcoded addresses or credentials in the codebase.

### Essential Variables

```bash
# Database (required)
DATABASE_USER=iptrack
DATABASE_PASSWORD=your_secure_password  # Auto-generated by setup.sh
DATABASE_HOST=postgres                   # 'postgres' in Docker, '127.0.0.1' for manual
DATABASE_NAME=iptrack

# Security (required)
# base64-encoded 32 random bytes (NOT a Fernet key); used to encrypt stored
# device credentials and to sign JWTs — never change it after first start
ENCRYPTION_KEY=your_generated_key       # Auto-generated by setup.sh

# Redis Cache
REDIS_HOST=redis                        # 'redis' in Docker, 'localhost' for manual
REDIS_ENABLED=true

# Collection Schedule
COLLECTION_ENABLED=true
COLLECTION_INTERVAL_MINUTES=120         # ARP/MAC collection every 2 hours
IPAM_SCAN_INTERVAL_MINUTES=60          # IPAM subnet scans every hour
OPTICAL_MODULE_INTERVAL_MINUTES=720    # Optical module data every 12 hours

# Worker Pool Sizes
COLLECTION_WORKERS=10                  # Concurrent switch collectors
IP_LOOKUP_WORKERS=50                   # Concurrent SSH connections for lookup
DISCOVERY_WORKERS=20                   # Concurrent workers for discovery
IPAM_SCAN_WORKERS=20                   # Concurrent IPAM scanners

# Feature Toggles
FEATURE_IPAM=true
FEATURE_ALARMS=true
FEATURE_OPTICAL_MODULES=true
FEATURE_PORT_ANALYSIS=true
FEATURE_STATUS_CHECKER=true            # ICMP ping monitoring every STATUS_CHECK_INTERVAL_SECONDS (default 300s)
```

See [.env.example](.env.example) for the complete list of configuration options (100+ variables covering database pooling, vendor collection methods, port-analysis scoring thresholds, logging, alarms, BMC, and more).

### Performance Tuning

**Small Networks (a few dozen switches)**
```bash
COLLECTION_WORKERS=5
COLLECTION_BATCH_SIZE=10
COLLECTION_INTERVAL_MINUTES=60
IP_LOOKUP_WORKERS=20
```

**Medium Networks (tens to a few hundred switches)**
```bash
COLLECTION_WORKERS=10
COLLECTION_BATCH_SIZE=5
COLLECTION_INTERVAL_MINUTES=120
IP_LOOKUP_WORKERS=50
```

**Large Networks (hundreds of switches, 1000+ subnets)**
```bash
COLLECTION_WORKERS=20
COLLECTION_BATCH_SIZE=5
COLLECTION_INTERVAL_MINUTES=180
IP_LOOKUP_WORKERS=100
DATABASE_POOL_SIZE=30
DATABASE_MAX_OVERFLOW=20
IPAM_CPU_LIMIT=4.0
IPAM_MEMORY_LIMIT=4G
```

## 🔌 Supported Vendors

> **重要**：当前前端“新增交换机”的厂商下拉只有 **Cisco / Dell / Alcatel-Lucent** 三项。下表后三行（Juniper / Arista / HPE / Huawei）只存在于 `collection_strategy.py` 的命令模板中，**无法从界面选择**，除非自行扩展前端下拉与后端处理器。

| Vendor | Device Types | Collection Method | Enable Mode | Device Types |
|--------|--------------|-------------------|-------------|--------------|
| Cisco | IOS, IOS-XE, NX-OS | CLI primary, SNMP fallback | ✅ Required | `cisco_ios` / `cisco_nxos` |
| Dell | Force10 (S-series), OS10 | CLI primary, SNMP fallback | Force10 only | `dell_force10` / `dell_os10` |
| Alcatel/Nokia | SR OS (7250/7750), SR Linux (7220) | CLI only (configurable) | ❌ Not required | `nokia_sros` / `nokia_srl` |
| Juniper | JunOS | CLI primary, SNMP fallback | ❌ Not required | `juniper_junos` |
| Arista | EOS | Template-driven | ❌ Not required | `arista_eos` |
| HPE | ProCurve | Template-driven | ❌ Not required | `hp_procurve` |
| Huawei | VRP | Template-driven | ❌ Not required | `huawei` |

### Collection Strategy

- **Cisco, Dell, Juniper**: CLI first, SNMP fallback if CLI fails or returns empty results
- **Alcatel/Nokia**: CLI-driven command templates (SNMP MIBs not widely supported)
- **Arista / HPE / Huawei**: driven by configurable CLI command templates in [collection_strategy.py](backend/src/config/collection_strategy.py)
- The global default and per-vendor methods are configurable (`GLOBAL_L2_TABLE_METHOD`, `*_PRIMARY_METHOD`, `*_FALLBACK_METHOD`)

## 🔧 Development

### Local Development Setup (Without Docker)

1. **Install Python dependencies**
   ```bash
   cd backend
   python3.11 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Install frontend dependencies**
   ```bash
   cd frontend
   npm install
   ```

3. **Start PostgreSQL and Redis**
   ```bash
   docker compose up -d postgres redis
   ```
   Or install manually and configure the connection in `.env`.

4. **Initialize `.env` file**
   ```bash
   cp .env.example .env
   # Generate the key setup.sh would normally create:
   python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
   # Put the result in .env as ENCRYPTION_KEY, then point at local services:
   #   DATABASE_HOST=127.0.0.1
   #   REDIS_HOST=127.0.0.1
   ```

5. **Run database migrations**
   ```bash
   # Docker path: applied automatically via database/init/*.sql on first PostgreSQL start
   # Manual path: apply the incremental migrations in database/migrations/ in order
   ```

6. **Start the three backend services** (one terminal each)
   ```bash
   cd backend
   source venv/bin/activate
   export PYTHONPATH=$(pwd)/src
   uvicorn main_core:app --reload --host 0.0.0.0 --port 8101

   uvicorn main_ipam:app --reload --host 0.0.0.0 --port 8102

   uvicorn main_collector:app --reload --host 0.0.0.0 --port 8103
   ```

7. **Start the frontend**
   ```bash
   cd frontend
   npm run dev
   ```

8. **Access the application**
   - Frontend: http://localhost:5173 (Vite dev server)
   - Health: http://localhost:8101/health, `:8102/health`, `:8103/health`
   - API docs: disabled by default — set `API_DOCS_ENABLED=true`, then http://localhost:8101/docs

### Running Tests

```bash
# Backend tests
cd backend
source venv/bin/activate
pytest

# Backend tests with coverage
pytest --cov=src --cov-report=html

# Frontend tests
cd frontend
npm run test
```

## 🐛 Troubleshooting

### ⚠️ Dev vs. Production entry point (dual-entry deployment)

The frontend can be reached through **two different entry points**. Always confirm which one you are verifying on after a code change.

| Entry | Address | Technology | Purpose |
|-------|---------|------------|---------|
| **Vite dev server** | `http://<host>:8001` | Vite HMR + Docker volume mount | Development, hot reload on change |
| **Nginx production** | `http://<your-domain>` | Nginx reverse proxy + static build | End-user production traffic |

**Key difference**:

```
User browser → http://<your-domain> → Nginx:80 → <deploy-root>/frontend/dist/index.html (static build)
                                                       → /api/* → proxy_pass to backend containers

Developer → http://<host>:8001 → Docker port mapping → Vite Dev Server:5173 → live source compile
```

**After changing frontend code, the production site only reflects it after a build**:

```bash
# 1. Build the production bundle (required — source-only changes don't reach users)
cd frontend
npx vite build                # outputs to frontend/dist/

# 2. Reload Nginx if its config changed
sudo nginx -s reload

# 3. Verify the production deployment
curl -s http://127.0.0.1/ | head -5
```

**Lesson learned (from a real incident)**: a frontend feature worked perfectly on the Vite dev server (`:8001`) but users never saw it — they were on the Nginx production entry while development was verified only on the dev server. Always build `dist/` and verify the actual entry point users use.

### Backend Won't Start

**Symptom**: Container restarts; logs show `ModuleNotFoundError`.

**Solution**:
```bash
docker compose logs --tail 50 backend-core
# Rebuild the shared backend image, then recreate the container
docker build -t ip-track-backend:latest ./backend && docker compose up -d backend-core
```

### All Switches Show "Offline"

**Cause**: The status checker runs every **300 seconds** (`STATUS_CHECK_INTERVAL_SECONDS`).
**Solution**: Wait up to 5 minutes after startup, then refresh. Still offline → check reachability from the collector container:
```bash
docker exec -it iptrack-backend-collector ping -c 3 SWITCH_IP
docker compose logs --tail=100 backend-collector
```

### No Data After Collection

**Cause**: The first collection is scheduled 120 minutes after startup (or your configured interval).
**Solution**: Trigger a manual collection from the UI — **Switches** page → open the switch → **采集** (ARP/MAC can be collected separately in the detail page). There is no `collect-all` endpoint in the current version.

> Lookup is **cache-only**: you must collect before querying.

### Configuration Validation Errors

**Symptom**: Backend logs show `ValidationError: Field required`.
**Solution**:
```bash
diff .env .env.example
grep -E "DATABASE_USER|DATABASE_PASSWORD|ENCRYPTION_KEY" .env
```

### Remember to restart after code changes

Source code is mounted into the containers (`./backend/src:/app/src`), but the container start command has **no `--reload` flag** — Python changes do **not** hot-reload. Restart the affected service:
```bash
docker compose restart backend-core       # after core API changes
docker compose restart backend-ipam       # after IPAM changes
docker compose restart backend-collector  # after collection/SNMP/CLI changes
docker compose restart frontend           # after frontend changes
```

> **Note**: `docker compose restart` does **not** re-read environment changes. If you changed `.env` or environment variables, use `docker compose up -d <service>` to recreate containers.

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. ✅ **No hardcoded values** — all configuration via `.env` or the database
2. ✅ **Update `.env.example`** when adding new config options
3. ✅ **Follow existing patterns** — async/await, type hints, Pydantic schemas
4. ✅ **Test with multiple vendors** if modifying collectors
5. ✅ **Update documentation** — CLAUDE.md, README.md, API docs

### Contribution Workflow

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (`pytest` for backend, `npm run test` for frontend)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## 📊 Project Statistics

- **Version**: 2.2.0
- **Backend**: 92 Python files, ~28,000 lines
- **Frontend**: 43 Vue/TS files, ~16,000 lines
- **Database Tables**: 20+
- **API Endpoints**: 140+
- **Supported Vendors**: 7 (with configurable command templates)
- **Performance**: <100 ms cached queries, 20–30 s realtime queries
- **Scale**: hundreds of switches, tens of thousands of managed IPs, designed for **1000+ subnets**

## 📝 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

### MIT License Summary

- ✅ Commercial use allowed
- ✅ Modification allowed
- ✅ Distribution allowed
- ✅ Private use allowed
- ⚠️ No warranty provided
- ⚠️ License and copyright notice must be included

## 🙏 Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/), [Vue 3](https://vuejs.org/), and [PostgreSQL](https://www.postgresql.org/)
- Network device communication via [Netmiko](https://github.com/ktbyers/netmiko)
- SNMP support via [pysnmp](https://github.com/lextudio/pysnmp)
- UI components from [Element Plus](https://element-plus.org/)
- Charts via [ECharts](https://echarts.apache.org/)

## 🔗 Related Projects

- [Netmiko](https://github.com/ktbyers/netmiko) — multi-vendor SSH library
- [NAPALM](https://github.com/napalm-automation/napalm) — network automation library
- [NetBox](https://github.com/netbox-community/netbox) — IPAM and DCIM tool

---

**⭐ Star this repository if you find it useful!**

**Last Updated**: 2026-11-05
**Version**: 2.2.0
**Maintained By**: IP-Track Contributors
