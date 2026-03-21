# Microservices Architecture - IP-Track

**Date**: 2026-03-20
**Version**: 2.3.0
**Purpose**: Independent backend services for isolated restarts

---

## Architecture Overview

IP-Track backend has been split into **3 independent microservices**:

```
┌────────────────────────────────────────────────────────────┐
│  Frontend (Vue 3) - Port 8001                              │
│  Vite dev server with API routing                          │
└───────────────┬────────────────────────────────────────────┘
                │
        ┌───────┴──────────────────────────────┐
        │  Vite Proxy Routing (path-based)     │
        │                                       │
        ▼                ▼                     ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Core API     │  │ IPAM Service │  │ Collector    │
│ Port 8101    │  │ Port 8102    │  │ Port 8103    │
├──────────────┤  ├──────────────┤  ├──────────────┤
│ • Switches   │  │ • IP Subnets │  │ • Discovery  │
│ • IP Lookup  │  │ • IP Addrs   │  │ • MAC/ARP    │
│ • History    │  │ • IP Scan    │  │ • Collections│
│ • Alarms     │  │ • Auto-scan  │  │ • Optical    │
│ • SNMP Profs │  │ • IPAM Dash  │  │ • Cmd Tmpl   │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                  │
       └─────────────────┴──────────────────┘
                         │
                ┌────────┴────────┐
                ▼                 ▼
         ┌──────────────┐  ┌──────────┐
         │ PostgreSQL   │  │  Redis   │
         │ Port 5432    │  │  Port    │
         └──────────────┘  └──────────┘
```

---

## Service Breakdown

### 1. Core API Service (Port 8101)

**Container**: `iptrack-backend-core`
**Entry Point**: `/app/src/main_core.py`
**Modules**:
- Switches management (`/api/v1/switches`)
- IP Lookup (`/api/v1/lookup`)
- Search history (`/api/v1/history`)
- Alarms (`/api/v1/alarms`)
- SNMP Profiles (`/api/v1/snmp-profiles`)

**Background Tasks**:
- Status checker (ping switches every 30s)

**Restart Command**:
```bash
sudo docker restart iptrack-backend-core
```

**When to restart**:
- Switch management bugs
- IP lookup issues
- Status checker problems
- SNMP profile changes

---

### 2. IPAM Service (Port 8102)

**Container**: `iptrack-backend-ipam`
**Entry Point**: `/app/src/main_ipam.py`
**Modules**:
- IP subnet management (`/api/v1/ipam/subnets`)
- IP address tracking (`/api/v1/ipam/ip-addresses`)
- Subnet scanning (`/api/v1/ipam/scan`)
- IPAM dashboard (`/api/v1/ipam/dashboard`)
- Network calculator (`/api/v1/ipam/subnet-calculator`)

**Background Tasks**:
- IPAM auto-scan scheduler (every 120 minutes by default)

**Restart Command**:
```bash
sudo docker restart iptrack-backend-ipam
```

**When to restart**:
- IPAM bugs or enhancements
- IP scanning issues
- Subnet management problems

---

### 3. Collector Service (Port 8103)

**Container**: `iptrack-backend-collector`
**Entry Point**: `/app/src/main_collector.py`
**Modules**:
- Network discovery (`/api/v1/discovery`)
- MAC/ARP table collection
- Optical module data collection
- Command templates (`/api/v1/command-templates`)

**Background Tasks**:
- Collection worker pool (10 workers by default)
- Network data collection scheduler (every 120 minutes)
- Optical module collection (every 720 minutes)
- Alarm cleanup (daily at 3:00 AM)

**Restart Command**:
```bash
sudo docker restart iptrack-backend-collector
```

**When to restart**:
- Collection service bugs
- Worker pool issues
- Discovery problems
- Command template changes

---

## API Routing (Frontend → Backend)

**Frontend Vite proxy** ([vite.config.ts](frontend/vite.config.ts#L21-L45)) routes requests:

| Frontend Request Path       | Target Service | Port |
|-----------------------------|----------------|------|
| `/api/v1/ipam/*`            | IPAM Service   | 8102 |
| `/api/v1/discovery/*`       | Collector      | 8103 |
| `/api/v1/command-templates/*` | Collector    | 8103 |
| `/api/v1/switches/*`        | Core API       | 8101 |
| `/api/v1/lookup/*`          | Core API       | 8101 |
| `/api/v1/history/*`         | Core API       | 8101 |
| `/api/v1/alarms/*`          | Core API       | 8101 |
| `/api/v1/snmp-profiles/*`   | Core API       | 8101 |

**Key Design**: Vite proxy uses path-based routing to transparently route frontend API calls to the correct backend service.

---

## Independent Restart Benefits

### Before (Monolith)
```
sudo docker restart iptrack-backend
↓
ALL modules offline for 10-20 seconds
✗ Switches page: 503 errors
✗ IPAM page: 503 errors
✗ Discovery: 503 errors
✗ Alarms: 503 errors
```

### After (Microservices)
```
sudo docker restart iptrack-backend-ipam
↓
ONLY IPAM module offline for 5-10 seconds
✓ Switches page: still working
✓ IP Lookup: still working
✗ IPAM page: 503 errors (expected)
✓ Discovery: still working
✓ Alarms: still working
```

**User Experience**: Restarting one service doesn't affect other modules.

---

## Files Created/Modified

### New Files
- [backend/src/main_core.py](backend/src/main_core.py) - Core API entry point
- [backend/src/main_ipam.py](backend/src/main_ipam.py) - IPAM service entry point
- [backend/src/main_collector.py](backend/src/main_collector.py) - Collector service entry point

### Modified Files
- [docker-compose.yml](docker-compose.yml#L49-L131) - Split backend into 3 services
- [frontend/vite.config.ts](frontend/vite.config.ts#L21-L45) - API routing configuration
- [backend/src/services/network_scheduler.py](backend/src/services/network_scheduler.py#L297-L389) - Added service-specific start/stop functions

---

## Common Operations

### Start All Services
```bash
cd /opt/IP-Track
sudo docker compose up -d
```

### Restart Individual Services
```bash
# Core API (switches, lookup, alarms)
sudo docker restart iptrack-backend-core

# IPAM only
sudo docker restart iptrack-backend-ipam

# Collector only (discovery, collection)
sudo docker restart iptrack-backend-collector
```

### Check Service Status
```bash
# View running containers
sudo docker ps | grep iptrack

# Check logs
sudo docker logs iptrack-backend-core --tail 50
sudo docker logs iptrack-backend-ipam --tail 50
sudo docker logs iptrack-backend-collector --tail 50
```

### Health Checks
```bash
# Direct service health
curl http://localhost:8101/health  # Core
curl http://localhost:8102/health  # IPAM
curl http://localhost:8103/health  # Collector

# Through frontend proxy
curl http://localhost:8001/api/v1/switches?limit=1  # Core
curl http://localhost:8001/api/v1/ipam/dashboard     # IPAM
curl http://localhost:8001/api/v1/discovery/status   # Collector
```

---

## Troubleshooting

### Service Won't Start

1. **Check logs**:
   ```bash
   sudo docker logs iptrack-backend-SERVICENAME --tail 100
   ```

2. **Common issues**:
   - Import errors: Check `main_*.py` imports
   - Port conflicts: Check `docker ps` for port bindings
   - Database connection: Ensure PostgreSQL is healthy

### API Returns 404

**Symptom**: `{"detail":"Not Found"}`

**Cause**: Router prefix mismatch

**Solution**: Check that routers use only `/api/v1` prefix, not resource-specific prefixes:
```python
# Correct
app.include_router(switches.router, prefix=settings.API_V1_PREFIX)  # /api/v1

# Wrong
app.include_router(switches.router, prefix="/api/v1/switches")  # Double prefix!
```

### Frontend Can't Reach Backend

1. **Check Vite proxy**: Ensure [vite.config.ts](frontend/vite.config.ts) has correct container names:
   - `iptrack-backend-core:8100`
   - `iptrack-backend-ipam:8100`
   - `iptrack-backend-collector:8100`

2. **Check Docker network**: All containers must be on `iptrack-network`:
   ```bash
   sudo docker inspect iptrack-backend-core | grep NetworkMode
   ```

3. **Restart frontend**:
   ```bash
   sudo docker restart iptrack-frontend
   ```

---

## Performance Considerations

### Shared Resources
- **Database**: All services share PostgreSQL (connection pooling configured)
- **Redis**: Shared cache (minimal contention)

### Resource Usage
Each backend service:
- **Memory**: ~200-300 MB
- **CPU**: <5% idle, 10-30% during collection

**Total overhead** vs monolith: ~100 MB additional memory (negligible)

### Scalability
Future improvements (not implemented):
- Run multiple instances of each service (with load balancer)
- Add message queue for inter-service communication (RabbitMQ, Redis pub/sub)
- Split database per service (true microservices)

---

## Rollback to Monolith

If needed, restore the original monolith architecture:

1. **Edit docker-compose.yml**:
   ```yaml
   backend:
     image: ip-track-backend:latest
     container_name: iptrack-backend
     ports:
       - "8101:8100"
     command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"]
   ```

2. **Edit frontend/vite.config.ts**:
   ```typescript
   proxy: {
     '/api': {
       target: 'http://iptrack-backend:8100',
       changeOrigin: true,
       secure: false
     }
   }
   ```

3. **Restart**:
   ```bash
   sudo docker compose down
   sudo docker compose up -d
   ```

---

## Future Enhancements

### Potential Improvements
1. **API Gateway**: Use Nginx or Traefik instead of Vite proxy for production
2. **Service Discovery**: Use Consul or Eureka for dynamic service registration
3. **Message Queue**: Add RabbitMQ for async inter-service communication
4. **Monitoring**: Add Prometheus + Grafana for service metrics
5. **Distributed Tracing**: Add Jaeger or Zipkin for request tracing
6. **Health Checks**: Add liveness/readiness probes to docker-compose
7. **Database Per Service**: Split PostgreSQL database per service (full microservices)

### Not Recommended
- **Over-splitting**: Current 3-service split is optimal for IP-Track's use case
- **Separate databases**: Adds complexity without clear benefits for this application
- **Kubernetes**: Overkill for single-server deployment

---

**Document Version**: 1.0
**Last Updated**: 2026-03-20
**Author**: Claude Code Agent
