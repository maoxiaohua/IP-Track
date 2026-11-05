"""Shared health probe, so all backend services report the same shape."""
from fastapi.responses import JSONResponse
from sqlalchemy import text

from core.database import AsyncSessionLocal


async def check_health(service: str, version: str) -> JSONResponse:
    """Probe the database so a broken backend is not reported as healthy."""
    database = "up"
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        database = "down"

    healthy = database == "up"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "healthy" if healthy else "unhealthy",
            "service": service,
            "version": version,
            "database": database,
        },
    )
