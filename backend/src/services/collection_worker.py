"""
Collection Worker Pool Service

Manages parallel worker pool for MAC/ARP/Optical collection.
Workers pull jobs from PostgreSQL queue and execute them independently.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from sqlalchemy import select, and_, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.switch import Switch
from models.collection_job import CollectionJob, JobType, JobStatus
from services.network_data_collector import NetworkDataCollector
from utils.logger import logger
from services.alarm_service import alarm_service
from models.alarm import AlarmSeverity, AlarmSourceType, AlarmStatus


class CollectionWorker:
    """Individual worker that processes collection jobs"""

    def __init__(self, worker_id: str, collector: NetworkDataCollector):
        self.worker_id = worker_id
        self.collector = collector
        self.is_running = False
        self.current_job: Optional[CollectionJob] = None
        self.jobs_processed = 0
        self.jobs_succeeded = 0
        self.jobs_failed = 0

    @staticmethod
    def _enum_value(value: Any) -> str:
        """Normalize enum-like values persisted in string columns."""
        if value is None:
            return ""
        return value.value if hasattr(value, "value") else str(value)

    async def run(self, db: AsyncSession):
        """Main worker loop - pull jobs and execute"""
        self.is_running = True
        logger.info(f"Worker {self.worker_id} started")

        while self.is_running:
            try:
                # Pull next pending job from queue (ordered by priority DESC, created_at ASC)
                job = await self._get_next_job(db)

                if job:
                    self.current_job = job
                    try:
                        await asyncio.wait_for(
                            self._execute_job(db, job),
                            timeout=settings.COLLECTION_JOB_HARD_TIMEOUT_SECONDS
                        )
                    except asyncio.TimeoutError:
                        logger.error(
                            f"Worker {self.worker_id} job {job.id} exceeded hard timeout "
                            f"({settings.COLLECTION_JOB_HARD_TIMEOUT_SECONDS}s), "
                            f"worker will continue with next job"
                        )
                        try:
                            job.status = 'timeout'
                            job.error_message = (
                                f"Hard timeout ({settings.COLLECTION_JOB_HARD_TIMEOUT_SECONDS}s) exceeded"
                            )
                            job.completed_at = datetime.utcnow()
                            await db.commit()
                        except Exception as cleanup_error:
                            logger.error(
                                f"Failed to mark job {job.id} as timeout after hard limit: {cleanup_error}"
                            )
                            await db.rollback()
                        self.jobs_failed += 1
                    self.jobs_processed += 1
                else:
                    # No jobs available, sleep briefly
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                logger.info(f"Worker {self.worker_id} cancelled")
                break
            except Exception as e:
                logger.error(f"Worker {self.worker_id} error: {e}", exc_info=True)
                await asyncio.sleep(5)  # Back off on error

        logger.info(f"Worker {self.worker_id} stopped (processed={self.jobs_processed}, "
                   f"succeeded={self.jobs_succeeded}, failed={self.jobs_failed})")

    async def _get_next_job(self, db: AsyncSession) -> Optional[CollectionJob]:
        """Get next pending job from queue with row-level locking"""
        try:
            # Use FOR UPDATE SKIP LOCKED for lock-free queue semantics
            stmt = (
                select(CollectionJob)
                .where(CollectionJob.status == 'pending')
                .order_by(CollectionJob.priority.desc(), CollectionJob.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )

            result = await db.execute(stmt)
            job = result.scalar_one_or_none()

            if job:
                # Mark as running
                job.status = 'running'
                job.worker_id = self.worker_id
                job.started_at = datetime.utcnow()
                await db.commit()
                logger.debug(f"Worker {self.worker_id} claimed job {job.id}")
            else:
                # No job found, commit to close transaction
                await db.commit()

            return job

        except Exception as e:
            logger.error(f"Error getting next job: {e}")
            await db.rollback()
            return None

    async def _execute_job(self, db: AsyncSession, job: CollectionJob):
        """Execute a collection job"""
        start_time = datetime.utcnow()
        job_type_value = self._enum_value(job.job_type)

        try:
            # Get switch details
            switch_result = await db.execute(
                select(Switch).where(Switch.id == job.switch_id)
            )
            switch = switch_result.scalar_one_or_none()

            if not switch:
                raise Exception(f"Switch {job.switch_id} not found")

            # Close the read transaction before any long-running network I/O begins.
            await db.commit()

            # Execute collection based on job type
            if job.job_type == JobType.MAC:
                entries = await self.collector.collect_mac_single_switch(db, switch)
                job.entries_collected = len(entries) if entries else 0

            elif job.job_type == JobType.ARP:
                entries = await self.collector.collect_arp_single_switch(db, switch)
                job.entries_collected = len(entries) if entries else 0

            elif job.job_type == JobType.OPTICAL:
                entries = await self.collector.collect_optical_single_switch(db, switch)
                job.entries_collected = len(entries) if entries else 0

            elif job.job_type == JobType.ALL:
                mac_entries = await self.collector.collect_mac_single_switch(db, switch)
                mac_result_message = switch.last_collection_message
                arp_entries = await self.collector.collect_arp_single_switch(db, switch)
                arp_result_message = switch.last_collection_message
                optical_entries = await self.collector.collect_optical_single_switch(db, switch)
                mac_count = len(mac_entries) if mac_entries else 0
                arp_count = len(arp_entries) if arp_entries else 0
                optical_count = len(optical_entries) if optical_entries else 0
                job.entries_collected = (
                    mac_count +
                    arp_count +
                    optical_count
                )

                # The switches page primarily reflects whether network data collection
                # produced any usable L2/L3 entries. Optical modules can legitimately be
                # absent, and some devices are considered healthy even when only ARP or
                # only MAC data is populated in a collection run.
                combined_result_message = (
                    f"MAC: {mac_count} entries, ARP: {arp_count} entries, "
                    f"Optical: {optical_count} entries"
                )

                # Determine optical collection status
                optical_status = getattr(switch, 'last_optical_collection_status', None)
                optical_failed = (optical_status == 'failed')

                if mac_count == 0 and arp_count == 0:
                    failure_message = self.collector._build_collection_failure_message(
                        switch,
                        mac_result_message or "MAC: 0 entries after trying all available methods",
                        arp_result_message or "ARP: 0 entries after trying all available methods"
                    )
                    if optical_failed:
                        failure_message += (
                            f"; Optical: failed — "
                            f"{getattr(switch, 'last_optical_collection_message', 'unknown error')}"
                        )
                    await self.collector._mark_switch_collection_failed(
                        db,
                        switch,
                        reason=failure_message,
                        collected_at=start_time
                    )
                    raise RuntimeError(failure_message)

                # Unified status: ALL collection types must succeed
                # Optical 'empty' means no modules physically present — not a failure
                if optical_failed:
                    switch.last_collection_status = 'failed'
                    switch.last_collection_message = (
                        f"{combined_result_message}; "
                        f"Optical FAILED: {getattr(switch, 'last_optical_collection_message', 'unknown error')}"
                    )
                else:
                    switch.last_collection_status = 'success'
                    optical_note = ""
                    if optical_status == 'empty':
                        optical_note = " (Optical: no modules detected)"
                    switch.last_collection_message = combined_result_message + optical_note

            # Mark job as successful
            job.status = 'success'
            job.completed_at = datetime.utcnow()
            job.duration_seconds = (job.completed_at - start_time).total_seconds()
            self.jobs_succeeded += 1

            # Ensure switch changes (capability learning) are committed
            db.add(switch)
            
            # Only auto-resolve alarms when the switch collected usable ARP/MAC data.
            if switch.last_collection_status == 'success':
                await alarm_service.auto_resolve_alarms(
                    db=db,
                    source_type=AlarmSourceType.SWITCH,
                    source_id=switch.id
                )
            
            await db.commit()
            logger.info(f"Job {job.id} completed: {job.entries_collected} entries")

        except asyncio.TimeoutError:
            job.status = 'timeout'
            job.error_message = "Collection timeout exceeded"
            job.completed_at = datetime.utcnow()
            job.duration_seconds = (job.completed_at - start_time).total_seconds()
            self.jobs_failed += 1
            
            # Create alarm for timeout
            try:
                switch_result = await db.execute(
                    select(Switch).where(Switch.id == job.switch_id)
                )
                switch = switch_result.scalar_one_or_none()
                
                if switch:
                    await self.collector._mark_switch_collection_failed(
                        db,
                        switch,
                        reason="Collection timeout exceeded",
                        collected_at=start_time
                    )
                    alarm = await alarm_service.create_alarm(
                        db=db,
                        severity=AlarmSeverity.WARNING,
                        title=f"Collection timeout: {switch.name}",
                        message=f"Collection timeout exceeded for {job_type_value} collection",
                        source_type=AlarmSourceType.SWITCH,
                        source_id=switch.id,
                        source_name=switch.name,
                        details={
                            'error_type': 'timeout',
                            'job_type': job_type_value,
                            'job_id': job.id,
                            'switch_ip': str(switch.ip_address),
                            'vendor': switch.vendor
                        }
                    )
                    if alarm.occurrence_count >= settings.CONSECUTIVE_FAILURE_AUTO_RESOLVE:
                        alarm.status = AlarmStatus.AUTO_RESOLVED
                        alarm.resolved_at = datetime.utcnow()
                        alarm.resolved_by = "system (consecutive failure threshold)"
                        await db.commit()
                        logger.info(
                            f"Auto-resolved timeout alarm for switch {switch.name} "
                            f"after {alarm.occurrence_count} consecutive failures"
                        )
            except Exception as alarm_error:
                logger.error(f"Failed to create timeout alarm: {alarm_error}")
            
            await db.commit()
            logger.warning(f"Job {job.id} timeout")

        except Exception as e:
            job.status = 'failed'
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            job.duration_seconds = (job.completed_at - start_time).total_seconds()
            self.jobs_failed += 1
            
            # Create alarm for failure
            try:
                switch_result = await db.execute(
                    select(Switch).where(Switch.id == job.switch_id)
                )
                switch = switch_result.scalar_one_or_none()
                
                if switch:
                    await self.collector._mark_switch_collection_failed(
                        db,
                        switch,
                        reason=str(e),
                        collected_at=start_time
                    )
                    # Determine severity based on error message
                    severity = AlarmSeverity.ERROR
                    if 'auth' in str(e).lower() or 'password' in str(e).lower():
                        severity = AlarmSeverity.ERROR
                    elif 'connect' in str(e).lower() or 'unreachable' in str(e).lower():
                        severity = AlarmSeverity.WARNING
                    
                    alarm = await alarm_service.create_alarm(
                        db=db,
                        severity=severity,
                        title=f"Collection failed: {switch.name}",
                        message=str(e),
                        source_type=AlarmSourceType.SWITCH,
                        source_id=switch.id,
                        source_name=switch.name,
                        details={
                            'error_type': type(e).__name__,
                            'job_type': job_type_value,
                            'job_id': job.id,
                            'switch_ip': str(switch.ip_address),
                            'vendor': switch.vendor,
                            'model': switch.model
                        }
                    )
                    if alarm.occurrence_count >= settings.CONSECUTIVE_FAILURE_AUTO_RESOLVE:
                        alarm.status = AlarmStatus.AUTO_RESOLVED
                        alarm.resolved_at = datetime.utcnow()
                        alarm.resolved_by = "system (consecutive failure threshold)"
                        await db.commit()
                        logger.info(
                            f"Auto-resolved failure alarm for switch {switch.name} "
                            f"after {alarm.occurrence_count} consecutive failures"
                        )
            except Exception as alarm_error:
                logger.error(f"Failed to create failure alarm: {alarm_error}")
            
            await db.commit()
            logger.error(f"Job {job.id} failed: {e}", exc_info=True)

    def stop(self):
        """Stop worker gracefully"""
        self.is_running = False


class CollectionWorkerPool:
    """Manages pool of collection workers"""

    def __init__(self, max_workers: int = 10):
        self.max_workers = max_workers
        self.workers: List[CollectionWorker] = []
        self.worker_tasks: List[asyncio.Task] = []
        self.collector = NetworkDataCollector()
        self.is_running = False

    async def start(self):
        """Start worker pool"""
        if self.is_running:
            logger.warning("Worker pool already running")
            return

        self.is_running = True
        logger.info(f"Starting collection worker pool with {self.max_workers} workers")

        # Import here to avoid circular dependency
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            await self._reclaim_stale_running_jobs(session)

        # Start periodic stale job reclamation (runs every 5 minutes)
        reclaim_task = asyncio.create_task(self._periodic_reclaim())
        self.worker_tasks.append(reclaim_task)

        # Create workers
        for i in range(self.max_workers):
            worker_id = f"worker-{i+1}"
            worker = CollectionWorker(worker_id, self.collector)
            self.workers.append(worker)

            # Create database session for this worker
            async def run_worker(w: CollectionWorker):
                async with AsyncSessionLocal() as session:
                    await w.run(session)

            task = asyncio.create_task(run_worker(worker))
            self.worker_tasks.append(task)

        logger.info(f"Worker pool started with {len(self.workers)} workers")

    async def _reclaim_stale_running_jobs(self, db: AsyncSession) -> int:
        """Move orphaned RUNNING jobs back to PENDING on process startup."""
        stmt = (
            update(CollectionJob)
            .where(CollectionJob.status == JobStatus.RUNNING)
            .values(
                status=JobStatus.PENDING,
                worker_id=None,
                started_at=None
            )
        )
        result = await db.execute(stmt)
        await db.commit()

        reclaimed = result.rowcount or 0
        if reclaimed:
            logger.warning(f"Reclaimed {reclaimed} stale running collection jobs on startup")
        else:
            logger.info("No stale running collection jobs found on startup")
        return reclaimed

    async def _periodic_reclaim(self):
        """Periodically reclaim stale RUNNING jobs during runtime."""
        while self.is_running:
            try:
                await asyncio.sleep(300)
                if not self.is_running:
                    break

                from core.database import AsyncSessionLocal
                async with AsyncSessionLocal() as db:
                    stale_cutoff = datetime.utcnow() - timedelta(
                        minutes=settings.STALE_JOB_RECLAIM_MINUTES
                    )
                    stmt = (
                        update(CollectionJob)
                        .where(
                            CollectionJob.status == JobStatus.RUNNING,
                            CollectionJob.started_at.is_not(None),
                            CollectionJob.started_at < stale_cutoff
                        )
                        .values(
                            status=JobStatus.PENDING,
                            worker_id=None,
                            started_at=None
                        )
                    )
                    result = await db.execute(stmt)
                    await db.commit()
                    if result.rowcount:
                        logger.warning(
                            f"Periodic reclaim: moved {result.rowcount} stale RUNNING "
                            f"jobs back to PENDING (older than "
                            f"{settings.STALE_JOB_RECLAIM_MINUTES} min)"
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Periodic stale job reclaim failed: {e}")

    async def stop(self):
        """Stop worker pool gracefully"""
        logger.info("Stopping collection worker pool")
        self.is_running = False

        # Stop all workers
        for worker in self.workers:
            worker.stop()

        # Cancel all tasks
        for task in self.worker_tasks:
            task.cancel()

        # Wait for tasks to complete
        if self.worker_tasks:
            await asyncio.gather(*self.worker_tasks, return_exceptions=True)

        self.workers.clear()
        self.worker_tasks.clear()
        logger.info("Worker pool stopped")

    async def create_jobs(self, db: AsyncSession, switches: List[Switch],
                         job_type: JobType, batch_id: Optional[str] = None,
                         priority: int = 0) -> int:
        """Create collection jobs for a list of switches"""
        if not batch_id:
            batch_id = str(uuid.uuid4())

        switch_ids = [switch.id for switch in switches]
        active_result = await db.execute(
            select(CollectionJob.switch_id).where(
                CollectionJob.switch_id.in_(switch_ids),
                CollectionJob.job_type == job_type.value,
                CollectionJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING])
            )
        )
        active_switch_ids = set(active_result.scalars().all())

        jobs_created = 0
        for switch in switches:
            if switch.id in active_switch_ids:
                continue

            job = CollectionJob(
                switch_id=switch.id,
                job_type=job_type.value,
                status=JobStatus.PENDING.value,
                batch_id=batch_id,
                priority=priority
            )
            db.add(job)
            jobs_created += 1

        await db.commit()
        logger.info(f"Created {jobs_created} {job_type.value} jobs (batch={batch_id})")
        return jobs_created

    async def cleanup_old_jobs(
        self,
        db: AsyncSession,
        days_to_keep: int = settings.COLLECTION_JOB_RETENTION_DAYS,
        batch_size: int = settings.COLLECTION_JOB_CLEANUP_BATCH_SIZE
    ) -> int:
        """Delete completed collection jobs older than the retention window in batches."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        terminal_statuses = [
            JobStatus.SUCCESS.value,
            JobStatus.FAILED.value,
            JobStatus.TIMEOUT.value,
            JobStatus.CANCELLED.value,
        ]
        total_deleted = 0

        while True:
            stale_ids = (
                select(CollectionJob.id)
                .where(
                    CollectionJob.status.in_(terminal_statuses),
                    CollectionJob.completed_at.is_not(None),
                    CollectionJob.completed_at < cutoff
                )
                .order_by(CollectionJob.id.asc())
                .limit(batch_size)
            )

            result = await db.execute(
                delete(CollectionJob)
                .where(CollectionJob.id.in_(stale_ids))
                .execution_options(synchronize_session=False)
            )
            batch_deleted = result.rowcount or 0

            if batch_deleted == 0:
                break

            total_deleted += batch_deleted
            await db.commit()

        if total_deleted:
            logger.info(
                f"Cleaned up {total_deleted} collection jobs older than {days_to_keep} days"
            )

        return total_deleted

    async def get_pool_status(self, db: AsyncSession) -> Dict[str, Any]:
        """Get current status of worker pool"""
        # Count jobs by status
        pending_stmt = select(CollectionJob).where(CollectionJob.status == 'pending')
        running_stmt = select(CollectionJob).where(CollectionJob.status == JobStatus.RUNNING)

        pending_result = await db.execute(pending_stmt)
        running_result = await db.execute(running_stmt)

        pending_jobs = len(pending_result.scalars().all())
        running_jobs = len(running_result.scalars().all())

        return {
            "is_running": self.is_running,
            "max_workers": self.max_workers,
            "active_workers": len([w for w in self.workers if w.is_running]),
            "pending_jobs": pending_jobs,
            "running_jobs": running_jobs,
            "workers": [
                {
                    "worker_id": w.worker_id,
                    "is_running": w.is_running,
                    "jobs_processed": w.jobs_processed,
                    "jobs_succeeded": w.jobs_succeeded,
                    "jobs_failed": w.jobs_failed,
                    "current_job_id": w.current_job.id if w.current_job else None
                }
                for w in self.workers
            ]
        }


# Global worker pool instance (configurable via environment)
worker_pool = CollectionWorkerPool(max_workers=settings.COLLECTION_WORKERS)
