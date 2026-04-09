"""
Core API Service - Switches, IP Lookup, History, Alarms, SNMP Profiles, Command Templates, Settings
Runs independently on port 8101
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.v1 import switches, lookup, history, alarms, snmp_profiles, command_templates, settings as settings_module
from services.status_checker import switch_status_checker
from core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    # Startup
    print("🚀 Starting Core API Service...")

    # Start background status checker
    if settings.FEATURE_STATUS_CHECKER:
        switch_status_checker.start()
        print("✅ Status checker started")
    else:
        print("ℹ️ Status checker disabled by configuration")

    yield

    # Shutdown
    print("🛑 Stopping Core API Service...")
    if settings.FEATURE_STATUS_CHECKER:
        switch_status_checker.stop()


app = FastAPI(
    title="IP-Track Core API",
    description="Switches, IP Lookup, History, Alarms, SNMP Profiles",
    version="2.3.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8001", "http://127.0.0.1:8001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(switches.router, prefix=settings.API_V1_PREFIX)
app.include_router(lookup.router, prefix=settings.API_V1_PREFIX)
app.include_router(history.router, prefix=settings.API_V1_PREFIX)
app.include_router(alarms.router, prefix=settings.API_V1_PREFIX)
app.include_router(snmp_profiles.router, prefix=settings.API_V1_PREFIX)
app.include_router(command_templates.router, prefix=settings.API_V1_PREFIX)
app.include_router(settings_module.router, prefix=settings.API_V1_PREFIX)

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "core-api",
        "version": "2.3.0"
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "IP-Track Core API",
        "docs": "/docs",
        "health": "/health"
    }
