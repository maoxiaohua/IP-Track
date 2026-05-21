"""
BMC Reset Scheduler

Runs daily and checks the database-configured day/hour before executing.
This allows the schedule to be changed from the web UI without a code deploy.
"""

from datetime import datetime

from sqlalchemy import select

from core.database import AsyncSessionLocal
from models.bmc_server import BMCServer
from services.bmc_service import bmc_service, _schedule_bg
from services.settings_service import settings_service
from services.network_scheduler import network_scheduler
from utils.logger import logger

JOB_ID = "bmc_monthly_reset"
VERIFY_JOB_ID = "bmc_periodic_verify"


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


async def _run_periodic_bmc_verify() -> None:
    """Re-verify all enabled BMC servers on an interval."""
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(BMCServer.id).where(BMCServer.enabled == True)
            )
            server_ids = [row[0] for row in result.all()]

            if not server_ids:
                logger.info("Periodic BMC verify: no enabled servers found")
                return

            for sid in server_ids:
                _schedule_bg(bmc_service._bg_collect_info(sid))

            logger.info(
                "Periodic BMC verify: scheduled background collection for %d server(s)",
                len(server_ids),
            )

    except Exception as e:
        logger.error(f"Periodic BMC verify failed: {e}")


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

    scheduler.add_job(
        _run_periodic_bmc_verify,
        trigger="interval",
        hours=6,
        minutes=37,
        id=VERIFY_JOB_ID,
        name="BMC Periodic Verification",
        replace_existing=True,
        max_instances=1,
    )
    logger.info(f"BMC periodic verify scheduler registered (job_id={VERIFY_JOB_ID})")


def stop_bmc_scheduler() -> None:
    """Remove the BMC jobs from the scheduler."""
    scheduler = network_scheduler.scheduler
    for job_id in (JOB_ID, VERIFY_JOB_ID):
        try:
            scheduler.remove_job(job_id)
            logger.info(f"BMC scheduler job removed (job_id={job_id})")
        except Exception:
            pass
