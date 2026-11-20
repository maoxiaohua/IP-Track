"""
Core API Service - Switches, IP Lookup, History, Alarms, SNMP Profiles, Command Templates, Settings
Runs independently on port 8101
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.v1 import switches, lookup, history, alarms, snmp_profiles, command_templates, snmp_oid_overrides, settings as settings_module, bmc, auth, visio
from api.routes import snmp_config
from services.status_checker import switch_status_checker
from services.ip_lookup import ip_lookup_service
from services.bmc_reset_scheduler import start_bmc_scheduler, stop_bmc_scheduler
from services.auth_service import ensure_initial_admin
from core.auth import ReadOnlyGuestMiddleware
from core.config import settings
from core.database import AsyncSessionLocal
from core.health import check_health


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    # Startup
    print("🚀 Starting Core API Service...")

    # Bootstrap the first admin account (no-op once any user exists)
    try:
        async with AsyncSessionLocal() as session:
            await ensure_initial_admin(session)
    except Exception as e:
        print(f"⚠️ 初始管理员检查失败（请确认已执行 database/migrations/030_add_users.sql）: {e}")

    # Start background status checker
    if settings.FEATURE_STATUS_CHECKER:
        switch_status_checker.start()
        print("✅ Status checker started")
    else:
        print("ℹ️ Status checker disabled by configuration")

    # Start BMC reset scheduler
    try:
        start_bmc_scheduler()
        print("✅ BMC reset scheduler started")
    except Exception as e:
        print(f"⚠️ BMC reset scheduler failed to start: {e}")

    yield

    # Shutdown
    print("🛑 Stopping Core API Service...")
    if settings.FEATURE_STATUS_CHECKER:
        switch_status_checker.stop()
    stop_bmc_scheduler()
    await ip_lookup_service.shutdown()


_DOCS = {} if settings.API_DOCS_ENABLED else {"docs_url": None, "redoc_url": None, "openapi_url": None}

app = FastAPI(
    title="IP-Track Core API",
    description="Switches, IP Lookup, History, Alarms, SNMP Profiles",
    version="2.3.0",
    lifespan=lifespan,
    **_DOCS,
)

# Guests are read-only: write requests without a token get HTTP 401.
# Added before CORS so CORS stays outermost and headers are present on 401s.
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
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(switches.router, prefix=settings.API_V1_PREFIX)
app.include_router(lookup.router, prefix=settings.API_V1_PREFIX)
app.include_router(history.router, prefix=settings.API_V1_PREFIX)
app.include_router(alarms.router, prefix=settings.API_V1_PREFIX)
app.include_router(snmp_profiles.router, prefix=settings.API_V1_PREFIX)
app.include_router(snmp_config.router, prefix=settings.API_V1_PREFIX)
app.include_router(command_templates.router, prefix=settings.API_V1_PREFIX)
app.include_router(snmp_oid_overrides.router, prefix=settings.API_V1_PREFIX)
app.include_router(settings_module.router, prefix=settings.API_V1_PREFIX)
app.include_router(bmc.router, prefix=settings.API_V1_PREFIX)
app.include_router(visio.router, prefix=settings.API_V1_PREFIX)

@app.get("/health")
async def health():
    """Health check endpoint (probes the database)"""
    return await check_health("core-api", "2.3.0")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "IP-Track Core API",
        "health": "/health"
    }
