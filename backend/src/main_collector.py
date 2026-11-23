"""
Collection Service - Network Data Collection, Command Templates, Discovery
Runs independently on port 8103
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.v1 import discovery, command_templates, snmp_oid_overrides, topology, config_backups
from api.routes import network
# models/__init__.py 为空：拓扑四张表必须显式导入，否则 metadata 里没有它们。
from models.topology import (  # noqa: F401
    LldpNeighbor, SwitchInterface, TopologyLink, TopologyUnknownNode,
)
# 配置备份两张表同样需要显式导入
from models.config_backup import ConfigBackup, ConfigBlob  # noqa: F401
from services.network_scheduler import start_collection_scheduler, stop_collection_scheduler
from services.collection_worker import worker_pool
from services.switch_discovery import switch_discovery_service
from core.auth import ReadOnlyGuestMiddleware
from core.config import settings
from core.health import check_health


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    # Startup
    print("🚀 Starting Collection Service...")

    # Start collection worker pool
    await worker_pool.start()
    print("✅ Collection workers started")

    # Start network data collection scheduler
    await start_collection_scheduler()
    print("✅ Collection scheduler started")

    yield

    # Shutdown
    print("🛑 Stopping Collection Service...")
    await stop_collection_scheduler()
    await worker_pool.stop()
    await switch_discovery_service.shutdown()


_DOCS = {} if settings.API_DOCS_ENABLED else {"docs_url": None, "redoc_url": None, "openapi_url": None}

app = FastAPI(
    title="IP-Track Collection Service",
    description="Network Data Collection and Discovery",
    version="2.3.0",
    lifespan=lifespan,
    **_DOCS,
)

# Guests are read-only: write requests without a token get HTTP 401.
app.add_middleware(ReadOnlyGuestMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(network.router, prefix=settings.API_V1_PREFIX)
app.include_router(discovery.router, prefix=settings.API_V1_PREFIX)
app.include_router(command_templates.router, prefix=settings.API_V1_PREFIX)
app.include_router(snmp_oid_overrides.router, prefix=settings.API_V1_PREFIX)
app.include_router(topology.router, prefix=settings.API_V1_PREFIX)
app.include_router(config_backups.router, prefix=settings.API_V1_PREFIX)

@app.get("/health")
async def health():
    """Health check endpoint (probes the database)"""
    return await check_health("collector", "2.3.0")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "IP-Track Collection Service",
        "health": "/health"
    }
