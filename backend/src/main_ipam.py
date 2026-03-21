"""
IPAM Service - IP Address Management and Subnet Scanning
Runs independently on port 8102
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.v1 import ipam
from services.network_scheduler import start_ipam_scheduler, stop_ipam_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    # Startup
    print("🚀 Starting IPAM Service...")

    # Start IPAM auto-scan scheduler
    await start_ipam_scheduler()
    print("✅ IPAM scheduler started")

    yield

    # Shutdown
    print("🛑 Stopping IPAM Service...")
    await stop_ipam_scheduler()


app = FastAPI(
    title="IP-Track IPAM Service",
    description="IP Address Management and Subnet Scanning",
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
from core.config import settings
app.include_router(ipam.router, prefix=settings.API_V1_PREFIX)

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "ipam",
        "version": "2.3.0"
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "IP-Track IPAM Service",
        "docs": "/docs",
        "health": "/health"
    }
