"""
Collection Service - Network Data Collection, Command Templates, Discovery
Runs independently on port 8103
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.v1 import discovery, command_templates
from api.routes import network
from services.network_scheduler import start_collection_scheduler, stop_collection_scheduler
from services.collection_worker import worker_pool


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


app = FastAPI(
    title="IP-Track Collection Service",
    description="Network Data Collection and Discovery",
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
app.include_router(network.router, prefix=settings.API_V1_PREFIX)
app.include_router(discovery.router, prefix=settings.API_V1_PREFIX)
app.include_router(command_templates.router, prefix=settings.API_V1_PREFIX)

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "collector",
        "version": "2.3.0"
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "IP-Track Collection Service",
        "docs": "/docs",
        "health": "/health"
    }
