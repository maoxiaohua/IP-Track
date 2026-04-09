"""
Background Scheduler for Network Data Collection

Uses APScheduler to run periodic SNMP collection tasks.
Default schedule: every 10 minutes
"""

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from sqlalchemy import select, func
from utils.logger import logger
from core.database import get_db
from core.config import settings
from services.network_data_collector import network_data_collector
from services.alarm_service import alarm_service


class NetworkCollectionScheduler:
    """Scheduler for automated network data collection"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.collection_interval_minutes = settings.COLLECTION_INTERVAL_MINUTES
        self.ipam_scan_interval_minutes = settings.IPAM_SCAN_INTERVAL_MINUTES
        self.optical_module_interval_minutes = settings.OPTICAL_MODULE_INTERVAL_MINUTES
        self.is_running = False

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
            logger.info("Alarm cleanup job scheduled (daily at 3:00 AM)")
            logger.info(f"IPAM auto-scan job scheduled (interval: {self.ipam_scan_interval_minutes} min)")
            logger.info(f"Optical module collection job scheduled (interval: {self.optical_module_interval_minutes} min)")

        except Exception as e:
            logger.error(f"Failed to start network scheduler: {str(e)}", exc_info=True)
            raise

    def stop(self):
        """Stop the scheduler"""
        if self.is_running:
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
                    deleted_count = await alarm_service.cleanup_old_alarms(db, days_to_keep=30)
                    logger.info(f"Alarm cleanup completed: deleted {deleted_count} old alarms")
                except Exception as e:
                    logger.error(f"Alarm cleanup failed: {str(e)}", exc_info=True)
                finally:
                    break  # Only need one iteration

        except Exception as e:
            logger.error(f"Alarm cleanup error: {str(e)}", exc_info=True)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Alarm cleanup finished in {elapsed:.1f}s")

    async def _run_ipam_scan(self):
        """Run IPAM automatic subnet scan"""
        logger.info("Scheduled IPAM auto-scan started")
        start_time = datetime.now()

        try:
            # Import here to avoid circular dependency
            from services.ipam_service import ipam_service

            # Get database session
            async for db in get_db():
                try:
                    summary = await ipam_service.scan_all_auto_subnets(db)
                    logger.info(
                        f"IPAM auto-scan completed: "
                        f"{summary['scanned_subnets']}/{summary['total_subnets']} subnets scanned, "
                        f"{summary['total_ips_scanned']} IPs total"
                    )
                except Exception as e:
                    logger.error(f"IPAM auto-scan failed: {str(e)}", exc_info=True)
                finally:
                    break  # Only need one iteration

        except Exception as e:
            logger.error(f"IPAM scan error: {str(e)}", exc_info=True)

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

            scheduler.start()
            network_scheduler.is_running = True
            logger.info(f"Collection scheduler started with {len(scheduler.get_jobs())} jobs")
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

            scheduler.start()
            network_scheduler.is_running = True
            logger.info(f"IPAM scheduler started (interval: {settings.IPAM_SCAN_INTERVAL_MINUTES} min)")
    except Exception as e:
        logger.error(f"Failed to start IPAM scheduler: {str(e)}", exc_info=True)


async def stop_ipam_scheduler():
    """Stop the IPAM scheduler (for IPAM Service)"""
    try:
        if network_scheduler.is_running:
            network_scheduler.scheduler.shutdown()
            network_scheduler.is_running = False
            logger.info("IPAM scheduler stopped")
    except Exception as e:
        logger.error(f"Failed to stop IPAM scheduler: {str(e)}", exc_info=True)
