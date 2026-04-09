from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.config import settings
from api.v1 import switches, lookup, history, discovery, ipam, command_templates, alarms, collection, snmp_profiles, settings as settings_module
from api.routes import snmp_config, network
from services.status_checker import switch_status_checker
from services.network_scheduler import network_scheduler
from services.collection_worker import worker_pool
from utils.logger import logger
import os
import logging

# Configure SQLAlchemy logging to WARNING level BEFORE any database imports
# This reduces log verbosity significantly
for sqlalchemy_logger in ['sqlalchemy.engine', 'sqlalchemy.pool', 'sqlalchemy.dialects', 'sqlalchemy.orm']:
    sql_logger = logging.getLogger(sqlalchemy_logger)
    sql_logger.setLevel(logging.WARNING)
    sql_logger.propagate = False  # Don't propagate to root logger

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="IP Address to Switch Port Tracking System",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(switches.router, prefix=settings.API_V1_PREFIX)
app.include_router(lookup.router, prefix=settings.API_V1_PREFIX)
app.include_router(history.router, prefix=settings.API_V1_PREFIX)
app.include_router(discovery.router, prefix=settings.API_V1_PREFIX)
app.include_router(ipam.router, prefix=settings.API_V1_PREFIX)
app.include_router(command_templates.router, prefix=settings.API_V1_PREFIX)
app.include_router(alarms.router, prefix=settings.API_V1_PREFIX)
app.include_router(collection.router, prefix=settings.API_V1_PREFIX)
app.include_router(snmp_profiles.router, prefix=settings.API_V1_PREFIX)
app.include_router(snmp_config.router, prefix=settings.API_V1_PREFIX)
app.include_router(network.router, prefix=settings.API_V1_PREFIX)
app.include_router(settings_module.router, prefix=settings.API_V1_PREFIX)


@app.on_event("startup")
async def startup_event():
    """Run on application startup"""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Debug mode: {settings.DEBUG}")

    # Start background switch status checker
    switch_status_checker.start()
    logger.info("Background switch status checker started")

    # Start network data scheduler using the configured interval.
    network_scheduler.start(interval_minutes=settings.COLLECTION_INTERVAL_MINUTES)
    logger.info("Network data scheduler started")

    # Start collection worker pool
    await worker_pool.start()
    logger.info("Collection worker pool started")


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown"""
    logger.info(f"Shutting down {settings.APP_NAME}")

    # Stop background switch status checker
    switch_status_checker.stop()
    logger.info("Background switch status checker stopped")

    # Stop network data scheduler
    network_scheduler.stop()
    logger.info("Network data scheduler stopped")

    # Stop worker pool gracefully
    await worker_pool.stop()
    logger.info("Collection worker pool stopped")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/api/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8100,
        reload=settings.DEBUG
    )
