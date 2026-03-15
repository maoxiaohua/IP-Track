"""
Alarm Service

Centralized service for creating, managing, and tracking alarms across all modules.
Implements de-duplication, auto-resolution, and cleanup logic.
"""

import hashlib
from typing import List, Optional, Tuple, Dict
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, or_, desc, cast, String
from utils.logger import logger
from models.alarm import Alarm, AlarmSeverity, AlarmStatus, AlarmSourceType


class AlarmService:
    """Service for managing alarms"""

    def _generate_fingerprint(
        self,
        source_type: AlarmSourceType,
        source_id: Optional[int],
        title: str,
        severity: AlarmSeverity
    ) -> str:
        """
        Generate MD5 fingerprint for de-duplication.

        Fingerprint is based on: source_type + source_id + title + severity
        This ensures that the same issue from the same source creates only one alarm.
        """
        fingerprint_str = f"{source_type.value}_{source_id}_{title}_{severity.value}"
        return hashlib.md5(fingerprint_str.encode()).hexdigest()

    async def create_alarm(
        self,
        db: AsyncSession,
        severity: AlarmSeverity,
        title: str,
        message: str,
        source_type: AlarmSourceType,
        source_id: Optional[int] = None,
        source_name: Optional[str] = None,
        details: Optional[Dict] = None
    ) -> Alarm:
        """
        Create alarm with automatic de-duplication.

        If an identical alarm exists in ACTIVE or ACKNOWLEDGED status,
        increment occurrence_count and update last_occurrence_at instead
        of creating a duplicate.

        Args:
            db: Database session
            severity: Alarm severity level
            title: Short description
            message: Detailed message
            source_type: Type of source (switch, batch, collection, system)
            source_id: Optional ID of source object
            source_name: Optional name of source for display
            details: Optional structured error details

        Returns:
            Created or updated Alarm object
        """
        fingerprint = self._generate_fingerprint(source_type, source_id, title, severity)

        # First check for existing active/acknowledged alarm
        result = await db.execute(
            select(Alarm).where(
                and_(
                    Alarm.fingerprint == fingerprint,
                    cast(Alarm.status, String).in_([AlarmStatus.ACTIVE.value, AlarmStatus.ACKNOWLEDGED.value])
                )
            )
        )
        existing_active_alarm = result.scalar_one_or_none()

        if existing_active_alarm:
            # Update existing active alarm
            existing_active_alarm.occurrence_count += 1
            existing_active_alarm.last_occurrence_at = datetime.now()
            existing_active_alarm.message = message  # Update to latest message
            existing_active_alarm.details = details

            logger.info(
                f"Alarm de-duplicated: {title} "
                f"(occurrence #{existing_active_alarm.occurrence_count})"
            )

            await db.commit()
            await db.refresh(existing_active_alarm)
            return existing_active_alarm

        # Check for existing resolved alarm with same fingerprint
        result = await db.execute(
            select(Alarm).where(
                and_(
                    Alarm.fingerprint == fingerprint,
                    cast(Alarm.status, String).in_([AlarmStatus.RESOLVED.value, AlarmStatus.AUTO_RESOLVED.value])
                )
            ).order_by(Alarm.resolved_at.desc())
        )
        existing_resolved_alarm = result.scalar_one_or_none()

        if existing_resolved_alarm:
            # Reactivate resolved alarm instead of creating duplicate
            existing_resolved_alarm.status = AlarmStatus.ACTIVE
            existing_resolved_alarm.occurrence_count = 1
            existing_resolved_alarm.last_occurrence_at = datetime.now()
            existing_resolved_alarm.message = message
            existing_resolved_alarm.details = details
            existing_resolved_alarm.resolved_at = None
            existing_resolved_alarm.resolved_by = None
            existing_resolved_alarm.acknowledged_at = None
            existing_resolved_alarm.acknowledged_by = None

            logger.info(
                f"Alarm reactivated: [{severity.value.upper()}] {title} "
                f"(was resolved at {existing_resolved_alarm.resolved_at})"
            )

            await db.commit()
            await db.refresh(existing_resolved_alarm)
            return existing_resolved_alarm

        # Create new alarm only if no existing alarm found
        alarm = Alarm(
            severity=severity,
            status=AlarmStatus.ACTIVE,
            title=title,
            message=message,
            source_type=source_type,
            source_id=source_id,
            source_name=source_name,
            details=details,
            fingerprint=fingerprint,
            occurrence_count=1
        )

        db.add(alarm)
        await db.commit()
        await db.refresh(alarm)

        logger.info(
            f"Alarm created: [{severity.value.upper()}] {title} "
            f"(source: {source_type.value}:{source_id})"
        )

        return alarm

    async def acknowledge_alarm(
        self,
        db: AsyncSession,
        alarm_id: int,
        user: str = "system"
    ) -> Alarm:
        """
        Mark alarm as acknowledged.

        Args:
            db: Database session
            alarm_id: Alarm ID
            user: User who acknowledged (default: "system")

        Returns:
            Updated Alarm object
        """
        result = await db.execute(
            select(Alarm).where(Alarm.id == alarm_id)
        )
        alarm = result.scalar_one_or_none()

        if not alarm:
            raise ValueError(f"Alarm with ID {alarm_id} not found")

        if alarm.status != AlarmStatus.ACTIVE:
            logger.warning(
                f"Attempted to acknowledge alarm {alarm_id} "
                f"with status {alarm.status.value}"
            )
            return alarm

        alarm.status = AlarmStatus.ACKNOWLEDGED
        alarm.acknowledged_at = datetime.now()
        alarm.acknowledged_by = user

        await db.commit()
        await db.refresh(alarm)

        logger.info(f"Alarm {alarm_id} acknowledged by {user}")

        return alarm

    async def resolve_alarm(
        self,
        db: AsyncSession,
        alarm_id: int,
        user: str = "system"
    ) -> Alarm:
        """
        Mark alarm as resolved.

        Args:
            db: Database session
            alarm_id: Alarm ID
            user: User who resolved (default: "system")

        Returns:
            Updated Alarm object
        """
        result = await db.execute(
            select(Alarm).where(Alarm.id == alarm_id)
        )
        alarm = result.scalar_one_or_none()

        if not alarm:
            raise ValueError(f"Alarm with ID {alarm_id} not found")

        if alarm.status in [AlarmStatus.RESOLVED, AlarmStatus.AUTO_RESOLVED]:
            logger.warning(
                f"Attempted to resolve alarm {alarm_id} "
                f"with status {alarm.status.value}"
            )
            return alarm

        alarm.status = AlarmStatus.RESOLVED
        alarm.resolved_at = datetime.now()
        alarm.resolved_by = user

        await db.commit()
        await db.refresh(alarm)

        logger.info(f"Alarm {alarm_id} resolved by {user}")

        return alarm

    async def auto_resolve_alarms(
        self,
        db: AsyncSession,
        source_type: AlarmSourceType,
        source_id: int,
        severity: Optional[AlarmSeverity] = None
    ) -> int:
        """
        Auto-resolve alarms for a source that has recovered.

        Called after successful collection to automatically clear alarms
        for switches that are now working properly.

        Args:
            db: Database session
            source_type: Type of source
            source_id: ID of source
            severity: Optional severity filter (only resolve alarms with this severity)

        Returns:
            Number of alarms auto-resolved
        """
        conditions = [
            cast(Alarm.source_type, String) == source_type.value,
            Alarm.source_id == source_id,
            cast(Alarm.status, String).in_([AlarmStatus.ACTIVE.value, AlarmStatus.ACKNOWLEDGED.value])
        ]

        # Add severity filter if specified
        if severity:
            conditions.append(cast(Alarm.severity, String) == severity.value)

        result = await db.execute(
            select(Alarm).where(and_(*conditions))
        )
        alarms = result.scalars().all()

        count = 0
        for alarm in alarms:
            alarm.status = AlarmStatus.AUTO_RESOLVED
            alarm.resolved_at = datetime.now()
            alarm.resolved_by = "system"
            count += 1

        if count > 0:
            await db.commit()
            severity_msg = f" (severity={severity.value})" if severity else ""
            logger.info(
                f"Auto-resolved {count} alarms for "
                f"{source_type.value}:{source_id}{severity_msg}"
            )

        return count

    async def cleanup_old_alarms(
        self,
        db: AsyncSession,
        days_to_keep: int = 30
    ) -> int:
        """
        Delete resolved alarms older than specified days.

        Args:
            db: Database session
            days_to_keep: Number of days to keep resolved alarms (default: 30)

        Returns:
            Number of alarms deleted
        """
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)

        result = await db.execute(
            select(Alarm).where(
                and_(
                    cast(Alarm.status, String).in_([AlarmStatus.RESOLVED.value, AlarmStatus.AUTO_RESOLVED.value]),
                    Alarm.resolved_at < cutoff_date
                )
            )
        )
        alarms_to_delete = result.scalars().all()

        count = len(alarms_to_delete)

        for alarm in alarms_to_delete:
            await db.delete(alarm)

        if count > 0:
            await db.commit()
            logger.info(
                f"Cleaned up {count} resolved alarms older than {days_to_keep} days"
            )

        return count

    async def get_active_alarms(
        self,
        db: AsyncSession,
        severity: Optional[AlarmSeverity] = None,
        status: Optional[AlarmStatus] = None,
        source_type: Optional[AlarmSourceType] = None,
        skip: int = 0,
        limit: int = 100
    ) -> Tuple[List[Alarm], int]:
        """
        Get active alarms with filtering and pagination.

        Args:
            db: Database session
            severity: Optional severity filter
            status: Optional status filter
            source_type: Optional source type filter
            skip: Number of records to skip (pagination)
            limit: Maximum number of records to return

        Returns:
            Tuple of (alarms list, total count)
        """
        # Build query with filters
        query = select(Alarm)
        filters = []

        if severity:
            logger.debug(f"Filtering by severity: {severity} (value={severity.value})")
            filters.append(cast(Alarm.severity, String) == severity.value)
        if status:
            logger.debug(f"Filtering by status: {status} (value={status.value})")
            filters.append(cast(Alarm.status, String) == status.value)
        if source_type:
            logger.debug(f"Filtering by source_type: {source_type} (value={source_type.value})")
            filters.append(cast(Alarm.source_type, String) == source_type.value)

        if filters:
            query = query.where(and_(*filters))

        # Get total count
        count_query = select(func.count(Alarm.id))
        if filters:
            count_query = count_query.where(and_(*filters))

        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        # Get paginated results, ordered by most recent first
        query = query.order_by(desc(Alarm.created_at)).offset(skip).limit(limit)
        result = await db.execute(query)
        alarms = result.scalars().all()

        return list(alarms), total

    async def get_alarm_stats(self, db: AsyncSession) -> Dict:
        """
        Get alarm statistics for dashboard.

        Returns:
            Dictionary with statistics
        """
        # Count by status
        status_result = await db.execute(
            select(
                Alarm.status,
                func.count(Alarm.id)
            ).group_by(Alarm.status)
        )
        status_counts = {row[0].value: row[1] for row in status_result.all()}

        # Count by severity (active/acknowledged only)
        severity_result = await db.execute(
            select(
                Alarm.severity,
                func.count(Alarm.id)
            ).where(
                cast(Alarm.status, String).in_([AlarmStatus.ACTIVE.value, AlarmStatus.ACKNOWLEDGED.value])
            ).group_by(Alarm.severity)
        )
        severity_counts = {row[0]: row[1] for row in severity_result.all()}

        # Count by source type (active/acknowledged only)
        source_result = await db.execute(
            select(
                Alarm.source_type,
                func.count(Alarm.id)
            ).where(
                cast(Alarm.status, String).in_([AlarmStatus.ACTIVE.value, AlarmStatus.ACKNOWLEDGED.value])
            ).group_by(Alarm.source_type)
        )
        source_counts = {row[0]: row[1] for row in source_result.all()}

        # Top failing switches
        top_switches_result = await db.execute(
            select(
                Alarm.source_id,
                Alarm.source_name,
                func.count(Alarm.id).label('alarm_count')
            ).where(
                and_(
                    cast(Alarm.source_type, String) == AlarmSourceType.SWITCH.value,
                    cast(Alarm.status, String).in_([AlarmStatus.ACTIVE.value, AlarmStatus.ACKNOWLEDGED.value])
                )
            ).group_by(Alarm.source_id, Alarm.source_name)
            .order_by(desc('alarm_count'))
            .limit(10)
        )
        top_switches = [
            {
                'switch_id': row[0],
                'switch_name': row[1],
                'alarm_count': row[2]
            }
            for row in top_switches_result.all()
        ]

        return {
            'total_active': status_counts.get('active', 0),
            'total_acknowledged': status_counts.get('acknowledged', 0),
            'total_resolved': status_counts.get('resolved', 0) + status_counts.get('auto_resolved', 0),
            'by_severity': severity_counts,
            'by_source_type': source_counts,
            'top_failing_switches': top_switches
        }


# Singleton instance
alarm_service = AlarmService()
