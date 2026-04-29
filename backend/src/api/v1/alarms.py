"""
Alarm API Endpoints

REST API for managing alarms and alerts across all modules.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, cast, String
from typing import Optional
from datetime import datetime
from api.deps import get_db
from schemas.alarm import (
    AlarmCreate,
    AlarmUpdate,
    AlarmResponse,
    AlarmListResponse,
    AlarmStatsResponse,
    SwitchAlarmGroupListResponse,
    SwitchAlarmGroupResponse,
    SwitchAlarmTimelineEventResponse,
    SwitchAlarmTimelineResponse,
)
from models.alarm import Alarm, AlarmSeverity, AlarmStatus, AlarmSourceType
from models.switch import Switch
from services.data_freshness_service import build_lookup_result_freshness
from services.alarm_service import alarm_service
from utils.logger import logger


router = APIRouter(prefix="/alarms", tags=["alarms"])


def _is_switch_source(source_type) -> bool:
    return (source_type.value if hasattr(source_type, "value") else str(source_type)) == AlarmSourceType.SWITCH.value


def _serialize_alarm(alarm: Alarm, switch: Switch | None = None) -> AlarmResponse:
    payload = AlarmResponse.model_validate(alarm).model_dump()

    if switch:
        freshness = build_lookup_result_freshness(switch)
        payload.update({
            "current_switch_is_reachable": switch.is_reachable,
            "current_switch_collection_status": switch.last_collection_status,
            "current_switch_collection_message": switch.last_collection_message,
            "current_freshness_status": freshness["status"],
            "current_freshness_warning": freshness["warning"],
        })

    return AlarmResponse(**payload)


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _severity_rank(severity: Optional[str]) -> int:
    order = {
        AlarmSeverity.CRITICAL.value: 4,
        AlarmSeverity.ERROR.value: 3,
        AlarmSeverity.WARNING.value: 2,
        AlarmSeverity.INFO.value: 1,
    }
    return order.get(severity or "", 0)


def _alarm_last_event_at(alarm: Alarm) -> datetime:
    timestamps = [
        ts for ts in [
            alarm.created_at,
            alarm.last_occurrence_at,
            alarm.acknowledged_at,
            alarm.resolved_at,
        ]
        if ts is not None
    ]
    return max(timestamps)


def _serialize_switch_alarm_group(
    switch: Switch,
    alarms: list[Alarm]
) -> SwitchAlarmGroupResponse:
    active_count = sum(1 for alarm in alarms if _enum_value(alarm.status) == AlarmStatus.ACTIVE.value)
    acknowledged_count = sum(1 for alarm in alarms if _enum_value(alarm.status) == AlarmStatus.ACKNOWLEDGED.value)
    resolved_count = sum(
        1 for alarm in alarms
        if _enum_value(alarm.status) in [AlarmStatus.RESOLVED.value, AlarmStatus.AUTO_RESOLVED.value]
    )
    open_alarms = [
        alarm for alarm in alarms
        if _enum_value(alarm.status) in [AlarmStatus.ACTIVE.value, AlarmStatus.ACKNOWLEDGED.value]
    ]
    highest_active = None
    if open_alarms:
        highest_active = max(
            (_enum_value(alarm.severity) for alarm in open_alarms),
            key=_severity_rank
        )

    latest_alarm = max(alarms, key=_alarm_last_event_at)
    freshness = build_lookup_result_freshness(switch)

    return SwitchAlarmGroupResponse(
        switch_id=switch.id,
        switch_name=switch.name,
        switch_ip=str(switch.ip_address) if switch.ip_address else None,
        active_count=active_count,
        acknowledged_count=acknowledged_count,
        resolved_count=resolved_count,
        open_count=active_count + acknowledged_count,
        total_alarm_records=len(alarms),
        total_occurrences=sum(alarm.occurrence_count for alarm in alarms),
        highest_active_severity=highest_active,
        latest_alarm_id=latest_alarm.id,
        latest_alarm_title=latest_alarm.title,
        latest_alarm_message=latest_alarm.message,
        latest_alarm_status=_enum_value(latest_alarm.status),
        latest_event_at=_alarm_last_event_at(latest_alarm),
        current_switch_is_reachable=switch.is_reachable,
        current_switch_collection_status=switch.last_collection_status,
        current_switch_collection_message=switch.last_collection_message,
        current_freshness_status=freshness["status"],
        current_freshness_warning=freshness["warning"],
    )


def _build_timeline_events(alarms: list[Alarm]) -> list[SwitchAlarmTimelineEventResponse]:
    events: list[SwitchAlarmTimelineEventResponse] = []

    for alarm in alarms:
        severity = _enum_value(alarm.severity)
        status = _enum_value(alarm.status)

        events.append(SwitchAlarmTimelineEventResponse(
            timestamp=alarm.created_at,
            event_type="created",
            alarm_id=alarm.id,
            severity=severity,
            status=status,
            title=alarm.title,
            message=alarm.message,
            occurrence_count=alarm.occurrence_count,
            note="告警创建",
            details=alarm.details,
        ))

        if alarm.occurrence_count > 1 and alarm.last_occurrence_at and alarm.last_occurrence_at > alarm.created_at:
            events.append(SwitchAlarmTimelineEventResponse(
                timestamp=alarm.last_occurrence_at,
                event_type="reoccurred",
                alarm_id=alarm.id,
                severity=severity,
                status=status,
                title=alarm.title,
                message=alarm.message,
                occurrence_count=alarm.occurrence_count,
                note=f"重复发生，累计 {alarm.occurrence_count} 次",
                details=alarm.details,
            ))

        if alarm.acknowledged_at:
            events.append(SwitchAlarmTimelineEventResponse(
                timestamp=alarm.acknowledged_at,
                event_type="acknowledged",
                alarm_id=alarm.id,
                severity=severity,
                status=status,
                title=alarm.title,
                message=alarm.message,
                occurrence_count=alarm.occurrence_count,
                actor=alarm.acknowledged_by,
                note="告警已确认",
                details=alarm.details,
            ))

        if alarm.resolved_at:
            events.append(SwitchAlarmTimelineEventResponse(
                timestamp=alarm.resolved_at,
                event_type="auto_resolved" if status == AlarmStatus.AUTO_RESOLVED.value else "resolved",
                alarm_id=alarm.id,
                severity=severity,
                status=status,
                title=alarm.title,
                message=alarm.message,
                occurrence_count=alarm.occurrence_count,
                actor=alarm.resolved_by,
                note="告警已自动恢复" if status == AlarmStatus.AUTO_RESOLVED.value else "告警已解决",
                details=alarm.details,
            ))

    return sorted(events, key=lambda event: event.timestamp, reverse=True)


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

        switch_ids = list({
            alarm.source_id
            for alarm in alarms
            if _is_switch_source(alarm.source_type) and alarm.source_id is not None
        })
        switch_map = {}
        if switch_ids:
            switch_result = await db.execute(
                select(Switch).where(Switch.id.in_(switch_ids))
            )
            switch_map = {switch.id: switch for switch in switch_result.scalars().all()}

        return AlarmListResponse(
            items=[
                _serialize_alarm(
                    alarm,
                    switch_map.get(alarm.source_id) if _is_switch_source(alarm.source_type) else None
                )
                for alarm in alarms
            ],
            total=total
        )

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


@router.get("/switch-groups", response_model=SwitchAlarmGroupListResponse)
async def get_switch_alarm_groups(
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """Aggregate alarms by switch for fault-tracking views."""
    try:
        result = await db.execute(
            select(Alarm)
            .where(
                and_(
                    cast(Alarm.source_type, String) == AlarmSourceType.SWITCH.value,
                    Alarm.source_id.is_not(None)
                )
            )
            .order_by(Alarm.created_at.desc())
        )
        alarms = result.scalars().all()

        grouped: dict[int, list[Alarm]] = {}
        for alarm in alarms:
            if alarm.source_id is None:
                continue
            grouped.setdefault(alarm.source_id, []).append(alarm)

        switch_ids = list(grouped.keys())
        switch_map = {}
        if switch_ids:
            switch_result = await db.execute(
                select(Switch).where(Switch.id.in_(switch_ids))
            )
            switch_map = {switch.id: switch for switch in switch_result.scalars().all()}

        items = [
            _serialize_switch_alarm_group(switch_map[switch_id], grouped_alarms)
            for switch_id, grouped_alarms in grouped.items()
            if switch_id in switch_map
        ]
        items.sort(
            key=lambda item: (
                item.open_count,
                _severity_rank(item.highest_active_severity),
                item.latest_event_at.timestamp() if item.latest_event_at else 0
            ),
            reverse=True
        )

        return SwitchAlarmGroupListResponse(
            items=items[:limit],
            total=len(items)
        )

    except Exception as e:
        logger.error(f"Error getting switch alarm groups: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get switch alarm groups: {str(e)}"
        )


@router.get("/switches/{switch_id}/timeline", response_model=SwitchAlarmTimelineResponse)
async def get_switch_alarm_timeline(
    switch_id: int,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """Get a derived fault timeline for a single switch."""
    try:
        switch_result = await db.execute(
            select(Switch).where(Switch.id == switch_id)
        )
        switch = switch_result.scalar_one_or_none()

        if not switch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Switch with ID {switch_id} not found"
            )

        result = await db.execute(
            select(Alarm)
            .where(
                and_(
                    cast(Alarm.source_type, String) == AlarmSourceType.SWITCH.value,
                    Alarm.source_id == switch_id
                )
            )
            .order_by(Alarm.created_at.desc())
            .limit(limit)
        )
        alarms = result.scalars().all()

        active_count = sum(1 for alarm in alarms if _enum_value(alarm.status) == AlarmStatus.ACTIVE.value)
        acknowledged_count = sum(1 for alarm in alarms if _enum_value(alarm.status) == AlarmStatus.ACKNOWLEDGED.value)
        resolved_count = sum(
            1 for alarm in alarms
            if _enum_value(alarm.status) in [AlarmStatus.RESOLVED.value, AlarmStatus.AUTO_RESOLVED.value]
        )
        freshness = build_lookup_result_freshness(switch)

        return SwitchAlarmTimelineResponse(
            switch_id=switch.id,
            switch_name=switch.name,
            switch_ip=str(switch.ip_address) if switch.ip_address else None,
            active_count=active_count,
            acknowledged_count=acknowledged_count,
            resolved_count=resolved_count,
            open_count=active_count + acknowledged_count,
            total_alarm_records=len(alarms),
            total_occurrences=sum(alarm.occurrence_count for alarm in alarms),
            current_switch_is_reachable=switch.is_reachable,
            current_switch_collection_status=switch.last_collection_status,
            current_switch_collection_message=switch.last_collection_message,
            current_freshness_status=freshness["status"],
            current_freshness_warning=freshness["warning"],
            events=_build_timeline_events(alarms)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting switch alarm timeline for {switch_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get switch alarm timeline: {str(e)}"
        )


@router.get("/{alarm_id}", response_model=AlarmResponse)
async def get_alarm(
    alarm_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get alarm details by ID."""
    try:
        result = await db.execute(
            select(Alarm).where(Alarm.id == alarm_id)
        )
        alarm = result.scalar_one_or_none()

        if not alarm:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alarm with ID {alarm_id} not found"
            )

        switch = None
        if _is_switch_source(alarm.source_type) and alarm.source_id is not None:
            switch_result = await db.execute(
                select(Switch).where(Switch.id == alarm.source_id)
            )
            switch = switch_result.scalar_one_or_none()

        return _serialize_alarm(alarm, switch)

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
        switch = None
        if _is_switch_source(alarm.source_type) and alarm.source_id is not None:
            switch_result = await db.execute(
                select(Switch).where(Switch.id == alarm.source_id)
            )
            switch = switch_result.scalar_one_or_none()
        return _serialize_alarm(alarm, switch)

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
        switch = None
        if _is_switch_source(alarm.source_type) and alarm.source_id is not None:
            switch_result = await db.execute(
                select(Switch).where(Switch.id == alarm.source_id)
            )
            switch = switch_result.scalar_one_or_none()
        return _serialize_alarm(alarm, switch)

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
