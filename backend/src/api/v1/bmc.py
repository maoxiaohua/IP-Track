"""
BMC Reset API Routes

REST API and SSE endpoints for BMC server management and cold reset operations.
Registered on the Core API service (port 8101).
"""

import asyncio
import csv
import io
import json
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from schemas.bmc import (
    BMCServerCreate,
    BMCServerUpdate,
    BMCServerResponse,
    BMCServerListResponse,
    BMCResetRequest,
    BMCResetStartResponse,
    BMCResetHistoryResponse,
    BMCResetHistoryListResponse,
    BMCGlobalCredentialsResponse,
    BMCGlobalCredentialsUpdate,
    BMCInfoResponse,
    BMCBatchImportRequest,
    BMCBatchImportResult,
    BMCCredentialProfileCreate,
    BMCCredentialProfileUpdate,
    BMCCredentialProfileResponse,
)
from services.bmc_service import bmc_service, _schedule_bg
from services.bmc_reset_status import bmc_reset_status_service
from utils.logger import logger

router = APIRouter(prefix="/bmc", tags=["bmc"])


# ── Server CRUD ──────────────────────────────────────────────────

@router.get("/servers", response_model=BMCServerListResponse)
async def list_servers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    enabled_only: bool = Query(False),
    verified: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, description="Filter by host or name (case-insensitive partial match)"),
    db: AsyncSession = Depends(get_db),
):
    """List all BMC servers with optional filtering."""
    items, total = await bmc_service.list_servers(db, skip, limit, enabled_only, verified=verified, search=search)
    return BMCServerListResponse(
        items=[BMCServerResponse.model_validate(s) for s in items],
        total=total,
    )


@router.post("/servers", response_model=BMCServerResponse, status_code=status.HTTP_201_CREATED)
async def create_server(
    data: BMCServerCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a new BMC server to the inventory."""
    try:
        server = await bmc_service.create_server(db, data)
        return BMCServerResponse.model_validate(server)
    except Exception as e:
        logger.error(f"Failed to create BMC server: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/servers/{server_id}", response_model=BMCServerResponse)
async def get_server(
    server_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single BMC server by ID."""
    server = await bmc_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="BMC server not found")
    return BMCServerResponse.model_validate(server)


@router.put("/servers/{server_id}", response_model=BMCServerResponse)
async def update_server(
    server_id: int,
    data: BMCServerUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing BMC server."""
    server = await bmc_service.update_server(db, server_id, data)
    if not server:
        raise HTTPException(status_code=404, detail="BMC server not found")
    return BMCServerResponse.model_validate(server)


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    server_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a BMC server from the inventory."""
    deleted = await bmc_service.delete_server(db, server_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="BMC server not found")


# ── Reset Execution ──────────────────────────────────────────────

@router.post("/reset", response_model=BMCResetStartResponse)
async def start_reset(
    data: BMCResetRequest,
    db: AsyncSession = Depends(get_db),
):
    """Start a batch BMC cold reset for the given servers.

    Returns immediately with a session_id.
    Subscribe to `/bmc/reset-events` for live SSE progress.
    """
    try:
        session_id, total = await bmc_service.reset_servers(
            db, data.server_ids, triggered_by="manual"
        )
        return BMCResetStartResponse(
            session_id=session_id,
            message=f"BMC reset started for {total} server(s)",
            total_servers=total,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/reset-status")
async def get_reset_status():
    """Get a snapshot of the current BMC reset progress."""
    return bmc_reset_status_service.get_status()


@router.get("/reset-events")
async def stream_reset_events(request: Request):
    """SSE endpoint streaming live BMC reset progress."""

    async def event_generator():
        queue = await bmc_reset_status_service.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            await bmc_reset_status_service.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Reset History ────────────────────────────────────────────────

@router.get("/history", response_model=BMCResetHistoryListResponse)
async def list_reset_history(
    server_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Get BMC reset history with optional filtering."""
    items, total = await bmc_service.get_reset_history(
        db, server_id=server_id, status=status_filter, skip=skip, limit=limit
    )
    return BMCResetHistoryListResponse(
        items=[BMCResetHistoryResponse.model_validate(h) for h in items],
        total=total,
    )


# ── Global Credentials ───────────────────────────────────────────

@router.get("/settings/credentials", response_model=BMCGlobalCredentialsResponse)
async def get_global_credentials(
    db: AsyncSession = Depends(get_db),
):
    """Get global IPMI credentials configuration (password is never returned)."""
    creds = await bmc_service.get_global_credentials(db)
    return BMCGlobalCredentialsResponse(**creds)


@router.put("/settings/credentials")
async def update_global_credentials(
    data: BMCGlobalCredentialsUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update global IPMI credentials for BMC reset."""
    try:
        await bmc_service.update_global_credentials(db, data.username, data.password)
        return {"message": "Global BMC credentials updated successfully"}
    except Exception as e:
        logger.error(f"Failed to update BMC global credentials: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Credential Profiles ──────────────────────────────────────

@router.get("/settings/profiles", response_model=List[BMCCredentialProfileResponse])
async def list_credential_profiles(
    db: AsyncSession = Depends(get_db),
):
    """List all credential profiles."""
    return await bmc_service.list_credential_profiles(db)


@router.post("/settings/profiles", response_model=BMCCredentialProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_credential_profile(
    data: BMCCredentialProfileCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new credential profile."""
    try:
        profile = await bmc_service.create_credential_profile(
            db, data.name, data.username, data.password
        )
        return BMCCredentialProfileResponse(
            id=profile.id,
            name=profile.name,
            username=profile.username,
            password_set=bool(profile.password_encrypted),
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )
    except Exception as e:
        logger.error(f"Failed to create credential profile: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/settings/profiles/{profile_id}", response_model=BMCCredentialProfileResponse)
async def update_credential_profile(
    profile_id: int,
    data: BMCCredentialProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a credential profile."""
    profile = await bmc_service.update_credential_profile(
        db, profile_id, data.name, data.username, data.password
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Credential profile not found")
    return BMCCredentialProfileResponse(
        id=profile.id,
        name=profile.name,
        username=profile.username,
        password_set=bool(profile.password_encrypted),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.delete("/settings/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a credential profile."""
    deleted = await bmc_service.delete_credential_profile(db, profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Credential profile not found")


# ── Schedule Settings ───────────────────────────────────────────

@router.get("/settings/schedule")
async def get_schedule_settings(
    db: AsyncSession = Depends(get_db),
):
    """Get BMC monthly reset schedule configuration."""
    return await bmc_service.get_schedule_settings(db)


@router.put("/settings/schedule")
async def update_schedule_settings(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Update BMC monthly reset schedule configuration."""
    allowed_keys = {
        "bmc_monthly_reset_enabled": "boolean",
        "bmc_monthly_reset_day": "integer",
        "bmc_monthly_reset_hour": "integer",
        "bmc_reset_timeout_seconds": "integer",
        "bmc_verify_interval_hours": "integer",
    }
    for key, value in data.items():
        if key not in allowed_keys:
            raise HTTPException(status_code=400, detail=f"Unknown setting: {key}")
        await bmc_service.update_schedule_setting(db, key, value, allowed_keys[key])
    return {"message": "Schedule settings updated"}


# ── BMC Info Query ────────────────────────────────────────────────

@router.post("/servers/{server_id}/query-info")
async def query_bmc_info(
    server_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Trigger background BMC info collection (serial, firmware) for a server.

    Returns immediately. Collection runs in background and updates the server
    record within ~60s. Use GET /servers/{server_id} to check results.
    """
    server = await bmc_service.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="BMC server not found")
    _schedule_bg(bmc_service._bg_collect_info(server_id))
    return {"message": "BMC info collection started", "server_id": server_id}


@router.post("/reverify-stale")
async def reverify_stale_servers(
    db: AsyncSession = Depends(get_db),
):
    """Re-verify all servers that never had a background verification run
    (verified=False, verify_error=NULL). Returns immediately; verification
    runs in background.
    """
    stale_ids = await bmc_service.get_stale_unverified_ids(db)
    for sid in stale_ids:
        _schedule_bg(bmc_service._bg_collect_info(sid))
    return {"message": f"Re-verification scheduled for {len(stale_ids)} stale server(s)", "count": len(stale_ids)}


# ── Export ───────────────────────────────────────────────────────

CSV_HEADERS = [
    "ID", "Server Name", "Host", "Username", "Verified", "Verify Error",
    "Serial Number", "BMC Firmware", "BMC Info Updated",
    "Enabled", "Credential Profile", "Use Global Credentials",
    "Notes", "Created At", "Updated At",
]


@router.get("/export/success")
async def export_success_list(db: AsyncSession = Depends(get_db)):
    """Export all verified BMC servers as CSV."""
    content = io.StringIO()
    writer = csv.writer(content)
    writer.writerow(CSV_HEADERS)
    servers = await bmc_service.get_servers_for_export(db, verified_filter=True)
    for s in servers:
        writer.writerow([
            s.id, s.name, s.host, s.username, "OK",
            s.verify_error or "", s.serial_number or "", s.bmc_firmware_version or "",
            str(s.bmc_info_updated_at) if s.bmc_info_updated_at else "",
            "Yes" if s.enabled else "No",
            s.credential_profile_name or "",
            "Yes" if s.use_global_credentials else "No",
            s.notes or "",
            str(s.created_at) if s.created_at else "",
            str(s.updated_at) if s.updated_at else "",
        ])
    return StreamingResponse(
        iter([content.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=bmc_verified_success_{len(servers)}.csv"},
    )


@router.get("/export/failure")
async def export_failure_list(db: AsyncSession = Depends(get_db)):
    """Export all failed/unverified BMC servers as CSV."""
    content = io.StringIO()
    writer = csv.writer(content)
    writer.writerow(CSV_HEADERS)
    servers = await bmc_service.get_servers_for_export(db, verified_filter=False)
    for s in servers:
        writer.writerow([
            s.id, s.name, s.host, s.username, "Fail",
            s.verify_error or "", s.serial_number or "", s.bmc_firmware_version or "",
            str(s.bmc_info_updated_at) if s.bmc_info_updated_at else "",
            "Yes" if s.enabled else "No",
            s.credential_profile_name or "",
            "Yes" if s.use_global_credentials else "No",
            s.notes or "",
            str(s.created_at) if s.created_at else "",
            str(s.updated_at) if s.updated_at else "",
        ])
    return StreamingResponse(
        iter([content.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=bmc_verified_failure_{len(servers)}.csv"},
    )


# ── Batch Import ──────────────────────────────────────────────────

@router.post("/servers/batch-import", response_model=BMCBatchImportResult)
async def batch_import_servers(
    data: BMCBatchImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """Batch import BMC servers from an IP range with shared credentials."""
    try:
        result = await bmc_service.batch_create_servers(db, data)
        return BMCBatchImportResult(
            total=result["total"],
            created=result["created"],
            skipped=result["skipped"],
            errors=result.get("errors", []),
            servers=[BMCServerResponse.model_validate(s) for s in result["servers"]],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Batch import failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
