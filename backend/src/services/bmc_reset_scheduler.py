"""
BMC Reset Scheduler

Runs daily and checks the database-configured day/hour before executing.
This allows the schedule to be changed from the web UI without a code deploy.
"""

from datetime import datetime

from sqlalchemy import select

from core.database import AsyncSessionLocal
from models.bmc_server import BMCServer
from services.bmc_service import bmc_service
from services.settings_service import settings_service
from services.network_scheduler import network_scheduler
from utils.logger import logger

JOB_ID = "bmc_monthly_reset"


async def _run_monthly_bmc_reset() -> None:
    """Check settings and execute BMC cold reset if conditions match."""
    try:
        async with AsyncSessionLocal() as db:
            enabled = await settings_service.get_setting(
                db, "bmc_monthly_reset_enabled", default=False
            )
            if not enabled:
                return

            target_day = int(await settings_service.get_setting(
                db, "bmc_monthly_reset_day", default=1
            ))
            target_hour = int(await settings_service.get_setting(
                db, "bmc_monthly_reset_hour", default=2
            ))

            now = datetime.now()
            if now.day != target_day or now.hour != target_hour:
                return

            result = await db.execute(
                select(BMCServer).where(
                    BMCServer.enabled == True,
                    BMCServer.verified == True,
                )
            )
            servers = result.scalars().all()

            if not servers:
                logger.info("No enabled & verified BMC servers found for monthly reset.")
                return

            logger.info("Starting scheduled monthly BMC cold reset...")
            server_ids = [s.id for s in servers]
            session_id, total = await bmc_service.reset_servers(
                db, server_ids, triggered_by="scheduled"
            )
            logger.info(
                f"Monthly BMC reset started: session={session_id}, servers={total}"
            )

    except Exception as e:
        logger.error(f"Monthly BMC reset failed: {e}")


def start_bmc_scheduler() -> None:
    """Register a daily checker job that respects db-configured day/hour settings."""
    scheduler = network_scheduler.scheduler

    if not scheduler.running:
        try:
            scheduler.start()
            logger.info("APScheduler started by BMC reset scheduler")
        except Exception as e:
            logger.warning(f"Could not start APScheduler: {e}")

    scheduler.add_job(
        _run_monthly_bmc_reset,
        trigger="cron",
        hour="*",       # check every hour
        minute="7",
        id=JOB_ID,
        name="BMC Monthly Cold Reset Checker",
        replace_existing=True,
        max_instances=1,
    )
    logger.info(f"BMC monthly reset scheduler registered (job_id={JOB_ID})")


def stop_bmc_scheduler() -> None:
    """Remove the BMC jobs from the scheduler."""
    scheduler = network_scheduler.scheduler
    try:
        scheduler.remove_job(JOB_ID)
        logger.info(f"BMC scheduler job removed (job_id={JOB_ID})")
    except Exception:
        pass
