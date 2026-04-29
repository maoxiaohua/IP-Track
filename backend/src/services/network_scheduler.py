"""
Background Scheduler for Network Data Collection

Uses APScheduler to run periodic SNMP collection tasks.
Default schedule: every 10 minutes
"""

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from utils.logger import logger
from core.database import get_db
from core.database import AsyncSessionLocal
from core.config import settings
from services.network_data_collector import network_data_collector
from services.alarm_service import alarm_service
from services.ipam_scan_status import ipam_scan_status_service


class NetworkCollectionScheduler:
    """Scheduler for automated network data collection"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.collection_interval_minutes = settings.COLLECTION_INTERVAL_MINUTES
        self.ipam_scan_interval_minutes = settings.IPAM_SCAN_INTERVAL_MINUTES
        self.optical_module_interval_minutes = settings.OPTICAL_MODULE_INTERVAL_MINUTES
        self.is_running = False
        self._ipam_scan_lock = asyncio.Lock()
        self._current_ipam_scan_context: str | None = None
        self._startup_ipam_catchup_task: asyncio.Task | None = None

    def is_ipam_scan_running(self) -> bool:
        """Return whether any IPAM subnet scan is currently in progress."""
        return self._ipam_scan_lock.locked()

    def set_ipam_scan_context(self, context: str) -> None:
        """Record human-readable context for the active IPAM scan."""
        self._current_ipam_scan_context = context

    def clear_ipam_scan_context(self) -> None:
        """Clear active IPAM scan context once the scan finishes."""
        self._current_ipam_scan_context = None

    def cancel_ipam_startup_catchup(self) -> None:
        """Cancel any delayed startup IPAM catch-up that has not started yet."""
        task = self._startup_ipam_catchup_task
        if task and not task.done():
            task.cancel()
        self._startup_ipam_catchup_task = None

    def get_ipam_scan_busy_message(self) -> str:
        """Return a friendly conflict message for concurrent IPAM scans."""
        if self._current_ipam_scan_context:
            return f"{self._current_ipam_scan_context}，请等待完成后再重试"
        return "IPAM 扫描正在进行中，请等待当前自动/手动扫描完成后再重试"

    def start(self, interval_minutes: int = None):
        """
        Start the scheduler

        Args:
            interval_minutes: Collection interval (defaults to config value)
        """
        try:
            if interval_minutes is not None:
                self.collection_interval_minutes = interval_minutes
            else:
                self.collection_interval_minutes = settings.COLLECTION_INTERVAL_MINUTES

            logger.info(f"Adding collection job with interval: {self.collection_interval_minutes} min")

            # Add collection job
            self.scheduler.add_job(
                self._run_collection,
                trigger=IntervalTrigger(minutes=self.collection_interval_minutes),
                id='network_data_collection',
                name='Network Data Collection',
                replace_existing=True,
                max_instances=1  # Prevent overlapping runs
            )

            # Add daily alarm cleanup job (configurable hour)
            self.scheduler.add_job(
                self._run_alarm_cleanup,
                trigger=CronTrigger(hour=settings.ALARM_CLEANUP_HOUR, minute=0),
                id='alarm_cleanup',
                name='Alarm Cleanup (30 days)',
                replace_existing=True,
                max_instances=1
            )

            self.scheduler.add_job(
                self._run_collection_job_cleanup,
                trigger=CronTrigger(hour=settings.ALARM_CLEANUP_HOUR, minute=10),
                id='collection_job_cleanup',
                name='Collection Job Cleanup',
                replace_existing=True,
                max_instances=1
            )

            self.scheduler.add_job(
                self._run_ipam_history_cleanup,
                trigger=CronTrigger(hour=settings.ALARM_CLEANUP_HOUR, minute=20),
                id='ipam_history_cleanup',
                name='IPAM History Cleanup',
                replace_existing=True,
                max_instances=1
            )

            # Add IPAM auto-scan job (runs every hour)
            self.scheduler.add_job(
                self._run_ipam_scan,
                trigger=IntervalTrigger(minutes=self.ipam_scan_interval_minutes),
                id='ipam_auto_scan',
                name='IPAM Auto Scan',
                replace_existing=True,
                max_instances=1
            )

            # Add optical module collection job (runs every 12 hours)
            self.scheduler.add_job(
                self._run_optical_module_collection,
                trigger=IntervalTrigger(minutes=self.optical_module_interval_minutes),
                id='optical_module_collection',
                name='Optical Module Collection',
                replace_existing=True,
                max_instances=1
            )

            logger.info(f"Starting APScheduler with {len(self.scheduler.get_jobs())} jobs")
            self.scheduler.start()
            self.is_running = True
            logger.info(f"APScheduler started successfully. Running: {self.scheduler.running}")

            logger.info(f"Network collection scheduler started (interval: {self.collection_interval_minutes} min)")
            logger.info(f"Alarm cleanup job scheduled (daily at {settings.ALARM_CLEANUP_HOUR:02d}:00)")
            logger.info(f"Collection job cleanup scheduled (daily at {settings.ALARM_CLEANUP_HOUR:02d}:10)")
            logger.info(f"IPAM history cleanup scheduled (daily at {settings.ALARM_CLEANUP_HOUR:02d}:20)")
            logger.info(f"IPAM auto-scan job scheduled (interval: {self.ipam_scan_interval_minutes} min)")
            logger.info(f"Optical module collection job scheduled (interval: {self.optical_module_interval_minutes} min)")
            asyncio.create_task(
                self.trigger_startup_catchup(
                    include_collection=True,
                    include_ipam=True,
                    include_optical=True
                )
            )

        except Exception as e:
            logger.error(f"Failed to start network scheduler: {str(e)}", exc_info=True)
            raise

    def stop(self):
        """Stop the scheduler"""
        if self.is_running:
            self.cancel_ipam_startup_catchup()
            self.scheduler.shutdown()
            self.is_running = False
            logger.info("Network collection scheduler stopped")

    async def _get_active_job_counts(self, db, job_type: str) -> tuple[int, int]:
        """Return pending/running queue depth for a given job type."""
        from models.collection_job import CollectionJob, JobStatus

        result = await db.execute(
            select(
                func.count(CollectionJob.id).filter(
                    (CollectionJob.job_type == job_type) &
                    (CollectionJob.status == JobStatus.PENDING)
                ).label('pending_count'),
                func.count(CollectionJob.id).filter(
                    (CollectionJob.job_type == job_type) &
                    (CollectionJob.status == JobStatus.RUNNING)
                ).label('running_count')
            )
        )
        row = result.one()
        return int(row.pending_count or 0), int(row.running_count or 0)

    async def _latest_job_created_at(self, db, job_type: str):
        """Return the newest created_at timestamp for a given collection job type."""
        from models.collection_job import CollectionJob

        result = await db.execute(
            select(func.max(CollectionJob.created_at))
            .where(CollectionJob.job_type == job_type)
        )
        return result.scalar_one_or_none()

    async def _should_run_collection_catchup(self, db) -> bool:
        """Determine whether switch collection is overdue on startup."""
        from models.collection_job import JobType

        pending_jobs, running_jobs = await self._get_active_job_counts(db, JobType.ALL.value)
        if pending_jobs > 0 or running_jobs > 0:
            logger.info(
                "Skipping startup catch-up for switch collection because queue is busy "
                f"(pending={pending_jobs}, running={running_jobs})"
            )
            return False

        latest_job_at = await self._latest_job_created_at(db, JobType.ALL.value)
        if latest_job_at is None:
            logger.info("Startup catch-up: no historical switch collection jobs found")
            return True

        due_before = datetime.now(timezone.utc) - timedelta(minutes=settings.COLLECTION_INTERVAL_MINUTES)
        is_due = latest_job_at <= due_before
        logger.info(
            "Startup catch-up check for switch collection: "
            f"latest_job_at={latest_job_at.isoformat()}, due={is_due}"
        )
        return is_due

    async def _should_run_optical_catchup(self, db) -> bool:
        """Determine whether optical collection is overdue on startup."""
        from models.collection_job import JobType

        pending_jobs, running_jobs = await self._get_active_job_counts(db, JobType.OPTICAL.value)
        if pending_jobs > 0 or running_jobs > 0:
            logger.info(
                "Skipping startup catch-up for optical collection because queue is busy "
                f"(pending={pending_jobs}, running={running_jobs})"
            )
            return False

        latest_job_at = await self._latest_job_created_at(db, JobType.OPTICAL.value)
        if latest_job_at is None:
            logger.info("Startup catch-up: no historical optical collection jobs found")
            return True

        due_before = datetime.now(timezone.utc) - timedelta(minutes=settings.OPTICAL_MODULE_INTERVAL_MINUTES)
        is_due = latest_job_at <= due_before
        logger.info(
            "Startup catch-up check for optical collection: "
            f"latest_job_at={latest_job_at.isoformat()}, due={is_due}"
        )
        return is_due

    async def _should_run_ipam_catchup(self, db) -> bool:
        """Determine whether any IPAM subnet is already due on startup."""
        from models.ipam import IPSubnet
        from sqlalchemy import and_

        result = await db.execute(
            select(IPSubnet.last_scan_at, IPSubnet.scan_interval)
            .where(
                and_(
                    IPSubnet.enabled == True,
                    IPSubnet.auto_scan == True
                )
            )
        )
        rows = result.all()
        if not rows:
            logger.info("Startup catch-up: no auto-scan subnets configured")
            return False

        now = datetime.now(timezone.utc)
        for last_scan_at, scan_interval in rows:
            if last_scan_at is None:
                logger.info("Startup catch-up: found subnet with no previous IPAM scan")
                return True
            if (now - last_scan_at).total_seconds() >= (scan_interval or 0):
                logger.info(
                    "Startup catch-up: found overdue IPAM subnet "
                    f"(last_scan_at={last_scan_at.isoformat()}, interval={scan_interval}s)"
                )
                return True

        logger.info("Startup catch-up: no overdue IPAM subnets found")
        return False

    async def trigger_startup_catchup(
        self,
        *,
        include_collection: bool = False,
        include_ipam: bool = False,
        include_optical: bool = False
    ) -> None:
        """Run overdue jobs immediately on startup instead of waiting a full interval."""
        try:
            async for db in get_db():
                try:
                    if include_collection and await self._should_run_collection_catchup(db):
                        logger.info("Triggering immediate startup catch-up for switch collection")
                        asyncio.create_task(self._run_collection())

                    if include_optical and await self._should_run_optical_catchup(db):
                        logger.info("Triggering immediate startup catch-up for optical collection")
                        asyncio.create_task(self._run_optical_module_collection())

                    if include_ipam and await self._should_run_ipam_catchup(db):
                        self.schedule_ipam_startup_catchup()
                finally:
                    break
        except Exception as e:
            logger.error(f"Startup catch-up check failed: {str(e)}", exc_info=True)

    def schedule_ipam_startup_catchup(self) -> None:
        """Schedule a delayed, bounded startup catch-up scan for IPAM."""
        max_subnets = settings.IPAM_STARTUP_CATCHUP_MAX_SUBNETS
        if max_subnets == 0:
            logger.info("Startup catch-up for IPAM is disabled (max_subnets=0)")
            return

        existing_task = self._startup_ipam_catchup_task
        if existing_task and not existing_task.done():
            logger.info("Startup catch-up for IPAM is already scheduled")
            return

        delay_seconds = max(settings.IPAM_STARTUP_CATCHUP_DELAY_SECONDS, 0)
        logger.info(
            "Scheduling delayed startup catch-up for IPAM "
            f"(delay={delay_seconds}s, max_subnets={max_subnets})"
        )
        task = asyncio.create_task(
            self._run_ipam_startup_catchup_after_delay(
                delay_seconds=delay_seconds,
                max_subnets=max_subnets,
            )
        )
        self._startup_ipam_catchup_task = task

        def _clear_task(completed_task: asyncio.Task) -> None:
            if self._startup_ipam_catchup_task is completed_task:
                self._startup_ipam_catchup_task = None

        task.add_done_callback(_clear_task)

    async def _run_ipam_startup_catchup_after_delay(
        self,
        *,
        delay_seconds: int,
        max_subnets: int,
    ) -> None:
        """Wait for the startup grace period, then run a limited IPAM catch-up pass."""
        try:
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

            async with AsyncSessionLocal() as db:
                if not await self._should_run_ipam_catchup(db):
                    logger.info("Startup catch-up for IPAM skipped after delay: no overdue subnets remain")
                    return

            logger.info(
                "Triggering delayed startup catch-up for IPAM auto-scan "
                f"(max_subnets={max_subnets})"
            )
            await self._run_ipam_scan(startup_catchup=True, max_subnets=max_subnets)
        except asyncio.CancelledError:
            logger.info("Delayed startup catch-up for IPAM was cancelled")
            raise
        except Exception as e:
            logger.error(f"Delayed startup catch-up for IPAM failed: {str(e)}", exc_info=True)

    async def _run_collection(self):
        """Run a single collection cycle by creating jobs for worker pool"""
        logger.info("Scheduled collection started - creating jobs for worker pool")
        start_time = datetime.now()

        try:
            # Import here to avoid circular dependency
            from services.collection_worker import worker_pool
            from models.switch import Switch
            from models.collection_job import JobType
            from sqlalchemy import and_, or_

            # Get database session
            async for db in get_db():
                try:
                    pending_jobs, running_jobs = await self._get_active_job_counts(db, JobType.ALL.value)
                    if pending_jobs > 0 or running_jobs > 0:
                        logger.warning(
                            "Skipping scheduled full collection because queue is still busy "
                            f"(pending={pending_jobs}, running={running_jobs})"
                        )
                        break

                    # Get all enabled switches with CLI or SNMP enabled
                    stmt = select(Switch).where(
                        and_(
                            Switch.enabled == True,
                            or_(
                                Switch.cli_enabled == True,
                                Switch.snmp_enabled == True
                            )
                        )
                    )

                    result = await db.execute(stmt)
                    switches = result.scalars().all()

                    logger.info(f"Creating collection jobs for {len(switches)} switches")

                    # Create jobs for all switches (MAC+ARP combined, optical separate)
                    # Priority 0 for scheduled jobs (lower than manual jobs which use priority 10)
                    jobs_created = await worker_pool.create_jobs(
                        db, switches, JobType.ALL, priority=0
                    )

                    logger.info(
                        f"Scheduled collection: created {jobs_created} jobs for {len(switches)} switches. "
                        f"Workers will process them concurrently."
                    )

                except Exception as e:
                    logger.error(f"Collection job creation failed: {str(e)}", exc_info=True)
                finally:
                    break  # Only need one iteration

        except Exception as e:
            logger.error(f"Scheduler error: {str(e)}", exc_info=True)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Job creation finished in {elapsed:.1f}s (workers will execute asynchronously)")

    async def _run_alarm_cleanup(self):
        """Run alarm cleanup job - delete resolved alarms older than 30 days"""
        logger.info("Scheduled alarm cleanup started")
        start_time = datetime.now()

        try:
            # Get database session
            async for db in get_db():
                try:
                    deleted_count = await alarm_service.cleanup_old_alarms(
                        db,
                        days_to_keep=settings.ALARM_RETENTION_DAYS
                    )
                    logger.info(f"Alarm cleanup completed: deleted {deleted_count} old alarms")
                except Exception as e:
                    logger.error(f"Alarm cleanup failed: {str(e)}", exc_info=True)
                finally:
                    break  # Only need one iteration

        except Exception as e:
            logger.error(f"Alarm cleanup error: {str(e)}", exc_info=True)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Alarm cleanup finished in {elapsed:.1f}s")

    async def _run_collection_job_cleanup(self):
        """Run collection job retention cleanup."""
        logger.info("Scheduled collection job cleanup started")
        start_time = datetime.now()

        try:
            from services.collection_worker import worker_pool

            async for db in get_db():
                try:
                    deleted_count = await worker_pool.cleanup_old_jobs(
                        db,
                        days_to_keep=settings.COLLECTION_JOB_RETENTION_DAYS
                    )
                    logger.info(f"Collection job cleanup completed: deleted {deleted_count} old jobs")
                except Exception as e:
                    logger.error(f"Collection job cleanup failed: {str(e)}", exc_info=True)
                finally:
                    break

        except Exception as e:
            logger.error(f"Collection job cleanup error: {str(e)}", exc_info=True)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Collection job cleanup finished in {elapsed:.1f}s")

    async def _run_ipam_history_cleanup(self):
        """Run IP scan history retention cleanup."""
        logger.info("Scheduled IP scan history cleanup started")
        start_time = datetime.now()

        try:
            from services.ipam_service import ipam_service

            async for db in get_db():
                try:
                    deleted_count = await ipam_service.cleanup_old_scan_history(
                        db,
                        days_to_keep=settings.IP_SCAN_HISTORY_RETENTION_DAYS
                    )
                    logger.info(f"IP scan history cleanup completed: deleted {deleted_count} rows")
                except Exception as e:
                    logger.error(f"IP scan history cleanup failed: {str(e)}", exc_info=True)
                finally:
                    break

        except Exception as e:
            logger.error(f"IP scan history cleanup error: {str(e)}", exc_info=True)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"IP scan history cleanup finished in {elapsed:.1f}s")

    async def _run_ipam_scan(self, *, startup_catchup: bool = False, max_subnets: int | None = None):
        """Run IPAM automatic subnet scan"""
        if self._ipam_scan_lock.locked():
            logger.warning("Skipping IPAM auto-scan because another IPAM scan is already running")
            return

        async with self._ipam_scan_lock:
            scan_label = "startup catch-up" if startup_catchup else "scheduled"
            logger.info(f"Scheduled IPAM auto-scan started ({scan_label})")
            start_time = datetime.now()
            self.set_ipam_scan_context(
                "当前正在执行 IPAM 启动补扫" if startup_catchup else "当前正在执行自动 IPAM 扫描"
            )

            try:
                # Import here to avoid circular dependency
                from services.ipam_service import ipam_service
                start_message = (
                    "IPAM 启动补扫已启动，正在检查待补扫子网"
                    if startup_catchup
                    else "自动 IPAM 快速扫描已启动，正在检查待扫描子网"
                )
                await ipam_scan_status_service.start_scan(
                    source="auto",
                    scan_type="quick",
                    total_subnets=0,
                    message=start_message
                )

                async with AsyncSessionLocal() as db:
                    try:
                        summary = await ipam_service.scan_all_auto_subnets(
                            db,
                            scan_type="quick",
                            progress_callback=ipam_scan_status_service.consume_scan_event,
                            max_subnets=max_subnets,
                        )
                        logger.info(
                            f"IPAM auto-scan completed: "
                            f"{summary['scanned_subnets']}/{summary['total_subnets']} subnets scanned, "
                            f"{summary['total_ips_scanned']} IPs total"
                        )
                        deferred_subnets = summary.get('deferred_subnets', 0)
                        if summary['total_subnets'] == 0:
                            await ipam_scan_status_service.complete_scan(
                                summary=summary,
                                message=(
                                    "当前没有需要补扫的到期子网"
                                    if startup_catchup
                                    else "当前没有到期的自动快速扫描子网"
                                )
                            )
                        else:
                            if startup_catchup and deferred_subnets:
                                completion_message = (
                                    f"IPAM 启动补扫完成，本次补扫 {summary['scanned_subnets']} 个到期子网，"
                                    f"{summary['total_ips_scanned']} 个 IP；剩余 {deferred_subnets} 个子网留待后续定时任务处理"
                                )
                            elif startup_catchup:
                                completion_message = (
                                    f"IPAM 启动补扫完成，共补扫 {summary['scanned_subnets']} 个到期子网，"
                                    f"{summary['total_ips_scanned']} 个 IP"
                                )
                            else:
                                completion_message = (
                                    f"自动 IPAM 快速扫描完成，共扫描 {summary['scanned_subnets']} 个子网，"
                                    f"{summary['total_ips_scanned']} 个 IP"
                                )
                            await ipam_scan_status_service.complete_scan(
                                summary=summary,
                                message=completion_message
                            )
                    except Exception as e:
                        await db.rollback()
                        logger.error(f"IPAM auto-scan failed: {str(e)}", exc_info=True)
                        await ipam_scan_status_service.fail_scan(
                            error=str(e),
                            message="IPAM 启动补扫失败" if startup_catchup else "自动 IPAM 扫描失败"
                        )

            except Exception as e:
                logger.error(f"IPAM scan error: {str(e)}", exc_info=True)
                await ipam_scan_status_service.fail_scan(
                    error=str(e),
                    message="IPAM 启动补扫启动失败" if startup_catchup else "自动 IPAM 扫描启动失败"
                )
            finally:
                self.clear_ipam_scan_context()

            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"IPAM auto-scan finished in {elapsed:.1f}s")

    async def _run_optical_module_collection(self):
        """Run optical module collection from all switches via worker pool"""
        logger.info("Scheduled optical module collection started - creating jobs for worker pool")
        start_time = datetime.now()

        try:
            # Import here to avoid circular dependency
            from services.collection_worker import worker_pool
            from models.switch import Switch
            from models.collection_job import JobType
            from sqlalchemy import and_, or_

            # Get database session
            async for db in get_db():
                try:
                    pending_jobs, running_jobs = await self._get_active_job_counts(db, JobType.OPTICAL.value)
                    if pending_jobs > 0 or running_jobs > 0:
                        logger.warning(
                            "Skipping scheduled optical collection because queue is still busy "
                            f"(pending={pending_jobs}, running={running_jobs})"
                        )
                        break

                    # Get all enabled switches with CLI or SNMP enabled
                    stmt = select(Switch).where(
                        and_(
                            Switch.enabled == True,
                            or_(
                                Switch.cli_enabled == True,
                                Switch.snmp_enabled == True
                            )
                        )
                    )

                    result = await db.execute(stmt)
                    switches = result.scalars().all()

                    logger.info(f"Creating optical module collection jobs for {len(switches)} switches")

                    # Create OPTICAL jobs for all switches
                    # Priority 5 for scheduled optical jobs (between manual priority 10 and regular priority 0)
                    jobs_created = await worker_pool.create_jobs(
                        db, switches, JobType.OPTICAL, priority=5
                    )

                    logger.info(
                        f"Scheduled optical module collection: created {jobs_created} jobs for {len(switches)} switches. "
                        f"Workers will process them concurrently."
                    )

                except Exception as e:
                    logger.error(f"Optical job creation failed: {str(e)}", exc_info=True)
                finally:
                    break  # Only need one iteration

        except Exception as e:
            logger.error(f"Optical scheduler error: {str(e)}", exc_info=True)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Optical job creation finished in {elapsed:.1f}s (workers will execute asynchronously)")


    async def run_now(self):
        """Trigger immediate collection (outside of schedule)"""
        logger.info("Manual collection triggered")
        await self._run_collection()

    def get_status(self) -> dict:
        """Get scheduler status"""
        jobs = self.scheduler.get_jobs()

        if not jobs:
            return {
                'running': self.is_running,
                'next_run': None,
                'interval_minutes': self.collection_interval_minutes
            }

        job = jobs[0]
        next_run = job.next_run_time

        return {
            'running': self.is_running,
            'next_run': next_run.isoformat() if next_run else None,
            'interval_minutes': self.collection_interval_minutes,
            'job_id': job.id,
            'job_name': job.name
        }


# Singleton instance
network_scheduler = NetworkCollectionScheduler()


# ======================================================================
# Async Start/Stop Functions for Multi-Service Architecture
# ======================================================================

async def start_collection_scheduler():
    """Start only the collection-related scheduler jobs (for Collection Service)"""
    try:
        scheduler = network_scheduler.scheduler

        if not scheduler.running:
            logger.info("Starting Collection Service scheduler...")

            # Add collection job
            scheduler.add_job(
                network_scheduler._run_collection,
                trigger=IntervalTrigger(minutes=settings.COLLECTION_INTERVAL_MINUTES),
                id='network_data_collection',
                name='Network Data Collection',
                replace_existing=True,
                max_instances=1
            )

            # Add optical module collection job
            scheduler.add_job(
                network_scheduler._run_optical_module_collection,
                trigger=IntervalTrigger(minutes=settings.OPTICAL_MODULE_INTERVAL_MINUTES),
                id='optical_module_collection',
                name='Optical Module Collection',
                replace_existing=True,
                max_instances=1
            )

            # Add alarm cleanup job
            scheduler.add_job(
                network_scheduler._run_alarm_cleanup,
                trigger=CronTrigger(hour=settings.ALARM_CLEANUP_HOUR, minute=0),
                id='alarm_cleanup',
                name='Alarm Cleanup (30 days)',
                replace_existing=True,
                max_instances=1
            )

            scheduler.add_job(
                network_scheduler._run_collection_job_cleanup,
                trigger=CronTrigger(hour=settings.ALARM_CLEANUP_HOUR, minute=10),
                id='collection_job_cleanup',
                name='Collection Job Cleanup',
                replace_existing=True,
                max_instances=1
            )

            scheduler.start()
            network_scheduler.is_running = True
            logger.info(f"Collection scheduler started with {len(scheduler.get_jobs())} jobs")
            asyncio.create_task(
                network_scheduler.trigger_startup_catchup(
                    include_collection=True,
                    include_optical=True
                )
            )
    except Exception as e:
        logger.error(f"Failed to start collection scheduler: {str(e)}", exc_info=True)


async def stop_collection_scheduler():
    """Stop the collection scheduler (for Collection Service)"""
    try:
        if network_scheduler.is_running:
            network_scheduler.scheduler.shutdown()
            network_scheduler.is_running = False
            logger.info("Collection scheduler stopped")
    except Exception as e:
        logger.error(f"Failed to stop collection scheduler: {str(e)}", exc_info=True)


async def start_ipam_scheduler():
    """Start only the IPAM auto-scan scheduler job (for IPAM Service)"""
    try:
        scheduler = network_scheduler.scheduler

        if not scheduler.running:
            logger.info("Starting IPAM Service scheduler...")

            # Add IPAM auto-scan job
            scheduler.add_job(
                network_scheduler._run_ipam_scan,
                trigger=IntervalTrigger(minutes=settings.IPAM_SCAN_INTERVAL_MINUTES),
                id='ipam_auto_scan',
                name='IPAM Auto Scan',
                replace_existing=True,
                max_instances=1
            )

            scheduler.add_job(
                network_scheduler._run_ipam_history_cleanup,
                trigger=CronTrigger(hour=settings.ALARM_CLEANUP_HOUR, minute=20),
                id='ipam_history_cleanup',
                name='IPAM History Cleanup',
                replace_existing=True,
                max_instances=1
            )

            scheduler.start()
            network_scheduler.is_running = True
            logger.info(f"IPAM scheduler started (interval: {settings.IPAM_SCAN_INTERVAL_MINUTES} min)")
            asyncio.create_task(
                network_scheduler.trigger_startup_catchup(include_ipam=True)
            )
    except Exception as e:
        logger.error(f"Failed to start IPAM scheduler: {str(e)}", exc_info=True)


async def stop_ipam_scheduler():
    """Stop the IPAM scheduler (for IPAM Service)"""
    try:
        if network_scheduler.is_running:
            network_scheduler.cancel_ipam_startup_catchup()
            network_scheduler.scheduler.shutdown()
            network_scheduler.is_running = False
            logger.info("IPAM scheduler stopped")
    except Exception as e:
        logger.error(f"Failed to stop IPAM scheduler: {str(e)}", exc_info=True)
