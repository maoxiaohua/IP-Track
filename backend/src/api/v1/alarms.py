"""
Alarm API Endpoints

REST API for managing alarms and alerts across all modules.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from api.deps import get_db
from schemas.alarm import (
    AlarmCreate,
    AlarmUpdate,
    AlarmResponse,
    AlarmListResponse,
    AlarmStatsResponse
)
from models.alarm import AlarmSeverity, AlarmStatus, AlarmSourceType
from services.alarm_service import alarm_service
from utils.logger import logger


router = APIRouter(prefix="/alarms", tags=["alarms"])


@router.get("", response_model=AlarmListResponse)
async def list_alarms(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    severity: Optional[str] = None,
    alarm_status: Optional[str] = Query(None, alias="status"),
    source_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    List alarms with filtering and pagination.

    Args:
        skip: Number of records to skip (pagination)
        limit: Maximum number of records to return
        severity: Optional severity filter (critical, error, warning, info)
        alarm_status: Optional status filter (active, acknowledged, resolved, auto_resolved)
        source_type: Optional source type filter (collection, switch, batch, system)
    """
    try:
        # Convert string parameters to enums (case-insensitive)
        severity_enum = None
        if severity:
            severity_enum = AlarmSeverity(severity.lower())

        status_enum = None
        if alarm_status:
            status_enum = AlarmStatus(alarm_status.lower())

        source_type_enum = None
        if source_type:
            source_type_enum = AlarmSourceType(source_type.lower())

        alarms, total = await alarm_service.get_active_alarms(
            db=db,
            severity=severity_enum,
            status=status_enum,
            source_type=source_type_enum,
            skip=skip,
            limit=limit
        )

        return AlarmListResponse(items=alarms, total=total)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid parameter value: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error listing alarms: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list alarms: {str(e)}"
        )


@router.get("/stats", response_model=AlarmStatsResponse)
async def get_alarm_stats(db: AsyncSession = Depends(get_db)):
    """Get alarm statistics for dashboard."""
    try:
        stats = await alarm_service.get_alarm_stats(db)
        return AlarmStatsResponse(**stats)

    except Exception as e:
        logger.error(f"Error getting alarm stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get alarm stats: {str(e)}"
        )


@router.get("/{alarm_id}", response_model=AlarmResponse)
async def get_alarm(
    alarm_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get alarm details by ID."""
    try:
        from sqlalchemy import select
        from models.alarm import Alarm

        result = await db.execute(
            select(Alarm).where(Alarm.id == alarm_id)
        )
        alarm = result.scalar_one_or_none()

        if not alarm:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alarm with ID {alarm_id} not found"
            )

        return alarm

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting alarm {alarm_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get alarm: {str(e)}"
        )


@router.post("/{alarm_id}/acknowledge", response_model=AlarmResponse)
async def acknowledge_alarm(
    alarm_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Acknowledge an alarm."""
    try:
        alarm = await alarm_service.acknowledge_alarm(
            db=db,
            alarm_id=alarm_id,
            user="web_user"  # TODO: Get from authentication context
        )
        return alarm

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error acknowledging alarm {alarm_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to acknowledge alarm: {str(e)}"
        )


@router.post("/{alarm_id}/resolve", response_model=AlarmResponse)
async def resolve_alarm(
    alarm_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Resolve an alarm."""
    try:
        alarm = await alarm_service.resolve_alarm(
            db=db,
            alarm_id=alarm_id,
            user="web_user"  # TODO: Get from authentication context
        )
        return alarm

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error resolving alarm {alarm_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve alarm: {str(e)}"
        )


@router.delete("/{alarm_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alarm(
    alarm_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete an alarm."""
    try:
        from sqlalchemy import select
        from models.alarm import Alarm

        result = await db.execute(
            select(Alarm).where(Alarm.id == alarm_id)
        )
        alarm = result.scalar_one_or_none()

        if not alarm:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alarm with ID {alarm_id} not found"
            )

        await db.delete(alarm)
        await db.commit()

        logger.info(f"Deleted alarm {alarm_id}")

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting alarm {alarm_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete alarm: {str(e)}"
        )
