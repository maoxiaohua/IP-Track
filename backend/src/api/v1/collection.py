"""
Collection Job Management API
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, or_
from typing import List, Optional
from datetime import datetime, timedelta

from api.deps import get_db
from models.collection_job import CollectionJob, JobType, JobStatus
from models.switch import Switch
from services.collection_worker import worker_pool
from schemas.collection import (
    CollectionJobResponse, CollectionJobCreate,
    WorkerPoolStatusResponse, CollectionStatsResponse
)

router = APIRouter(prefix="/collection", tags=["collection"])


@router.get("/jobs", response_model=List[CollectionJobResponse])
async def list_jobs(
    status: Optional[JobStatus] = None,
    job_type: Optional[JobType] = None,
    switch_id: Optional[int] = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """List collection jobs with filters"""
    stmt = select(CollectionJob)

    filters = []
    if status:
        filters.append(CollectionJob.status == status)
    if job_type:
        filters.append(CollectionJob.job_type == job_type)
    if switch_id:
        filters.append(CollectionJob.switch_id == switch_id)

    if filters:
        stmt = stmt.where(and_(*filters))

    stmt = stmt.order_by(CollectionJob.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return jobs


@router.post("/jobs", response_model=dict)
async def create_collection_job(
    job_create: CollectionJobCreate,
    db: AsyncSession = Depends(get_db)
):
    """Manually create a collection job"""
    # Verify switch exists
    switch_result = await db.execute(
        select(Switch).where(Switch.id == job_create.switch_id)
    )
    switch = switch_result.scalar_one_or_none()

    if not switch:
        raise HTTPException(status_code=404, detail="Switch not found")

    # Create job
    jobs_created = await worker_pool.create_jobs(
        db, [switch], job_create.job_type, priority=job_create.priority or 0
    )

    return {"success": True, "jobs_created": jobs_created}


@router.get("/pool/status", response_model=WorkerPoolStatusResponse)
async def get_pool_status(db: AsyncSession = Depends(get_db)):
    """Get worker pool status"""
    status = await worker_pool.get_pool_status(db)
    return status


@router.get("/stats", response_model=CollectionStatsResponse)
async def get_collection_stats(
    hours: int = Query(24, description="Statistics window in hours"),
    db: AsyncSession = Depends(get_db)
):
    """Get collection statistics"""
    since = datetime.utcnow() - timedelta(hours=hours)

    # Count jobs by status
    stmt = select(
        CollectionJob.status,
        func.count(CollectionJob.id).label('count')
    ).where(
        CollectionJob.created_at >= since
    ).group_by(CollectionJob.status)

    result = await db.execute(stmt)
    status_counts = {row.status: row.count for row in result}

    # Average duration
    duration_stmt = select(
        func.avg(CollectionJob.duration_seconds)
    ).where(
        and_(
            CollectionJob.created_at >= since,
            CollectionJob.status == 'success'
        )
    )
    duration_result = await db.execute(duration_stmt)
    avg_duration = duration_result.scalar()

    return {
        "window_hours": hours,
        "status_counts": status_counts,
        "avg_duration_seconds": float(avg_duration) if avg_duration else 0,
        "success_rate": (
            status_counts.get('success', 0) /
            sum(status_counts.values()) * 100
            if sum(status_counts.values()) > 0 else 0
        )
    }


@router.post("/trigger", response_model=dict)
async def trigger_collection(
    switch_ids: Optional[List[int]] = None,
    job_type: JobType = JobType.ALL,
    db: AsyncSession = Depends(get_db)
):
    """Manually trigger collection for all or specific switches"""
    stmt = select(Switch).where(
        and_(
            Switch.enabled == True,
            or_(
                Switch.cli_enabled == True,
                Switch.snmp_enabled == True
            )
        )
    )

    if switch_ids:
        stmt = stmt.where(Switch.id.in_(switch_ids))

    result = await db.execute(stmt)
    switches = result.scalars().all()

    jobs_created = await worker_pool.create_jobs(db, switches, job_type, priority=10)

    return {
        "success": True,
        "switches": len(switches),
        "jobs_created": jobs_created,
        "job_type": job_type.value
    }


@router.put("/switches/{switch_id}/collection-method")
async def update_collection_method(
    switch_id: int,
    mac_method: Optional[str] = None,
    arp_method: Optional[str] = None,
    optical_method: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Manually set collection method for a switch (admin override)"""
    switch_result = await db.execute(
        select(Switch).where(Switch.id == switch_id)
    )
    switch = switch_result.scalar_one_or_none()

    if not switch:
        raise HTTPException(status_code=404, detail="Switch not found")

    updated = []

    if mac_method:
        if mac_method not in ['cli', 'auto']:
            raise HTTPException(status_code=400, detail="Invalid method")
        switch.mac_collection_method = mac_method
        switch.mac_method_override = (mac_method != 'auto')
        updated.append('mac')

    if arp_method:
        if arp_method not in ['cli', 'auto']:
            raise HTTPException(status_code=400, detail="Invalid method")
        switch.arp_collection_method = arp_method
        switch.arp_method_override = (arp_method != 'auto')
        updated.append('arp')

    if optical_method:
        if optical_method not in ['snmp', 'cli', 'auto']:
            raise HTTPException(status_code=400, detail="Invalid method")
        switch.optical_collection_method = optical_method
        switch.optical_method_override = (optical_method != 'auto')
        updated.append('optical')

    await db.commit()

    return {
        "success": True,
        "switch_id": switch_id,
        "updated": updated
    }
