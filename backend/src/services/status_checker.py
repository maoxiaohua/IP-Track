"""
Background service for periodic switch status checks
"""
import asyncio
from datetime import datetime
from sqlalchemy import select

from core.config import settings
from core.database import AsyncSessionLocal
from models.switch import Switch
from utils.network import ping_multiple_hosts
from utils.logger import logger


class SwitchStatusChecker:
    """Background service for lightweight high-frequency switch reachability checks."""

    def __init__(self):
        self.check_interval = settings.STATUS_CHECK_INTERVAL_SECONDS
        self.ping_timeout = settings.STATUS_CHECK_PING_TIMEOUT_SECONDS
        self.concurrency = settings.STATUS_CHECK_CONCURRENCY
        self.running = False
        self.task: asyncio.Task | None = None
        self._check_lock = asyncio.Lock()
        self._is_checking = False
        self.last_run_started_at: datetime | None = None
        self.last_run_completed_at: datetime | None = None
        self.last_summary: dict | None = None

    async def check_all_switches(self) -> dict:
        """Run one full reachability sweep across enabled switches."""
        if self._check_lock.locked():
            logger.info("Switch status check already in progress, skipping overlapping request")
            return {"status": "skipped", "reason": "already_running"}

        started_at = datetime.utcnow()
        try:
            async with self._check_lock:
                self._is_checking = True
                self.last_run_started_at = started_at

                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(Switch).where(Switch.enabled == True)
                    )
                    switches = result.scalars().all()

                    if not switches:
                        summary = {
                            "status": "completed",
                            "switches_total": 0,
                            "reachable": 0,
                            "unreachable": 0,
                            "started_at": started_at.isoformat(),
                            "completed_at": datetime.utcnow().isoformat(),
                            "elapsed_seconds": 0.0,
                        }
                        self.last_run_completed_at = datetime.utcnow()
                        self.last_summary = summary
                        logger.debug("No switches to check")
                        return summary

                    switch_ips = {str(sw.ip_address): sw for sw in switches}
                    ping_results = await ping_multiple_hosts(
                        list(switch_ips.keys()),
                        timeout=self.ping_timeout,
                        concurrency=self.concurrency
                    )

                    checked_at = datetime.utcnow()
                    reachable_count = 0
                    unreachable_count = 0

                    for ip, ping_result in ping_results.items():
                        switch = switch_ips[ip]
                        switch.is_reachable = ping_result["reachable"]
                        switch.last_check_at = checked_at
                        switch.response_time_ms = ping_result.get("response_time_ms")

                        if ping_result["reachable"]:
                            reachable_count += 1
                        else:
                            unreachable_count += 1

                    await db.commit()

                    completed_at = datetime.utcnow()
                    elapsed_seconds = round((completed_at - started_at).total_seconds(), 2)
                    summary = {
                        "status": "completed",
                        "switches_total": len(switches),
                        "reachable": reachable_count,
                        "unreachable": unreachable_count,
                        "started_at": started_at.isoformat(),
                        "completed_at": completed_at.isoformat(),
                        "elapsed_seconds": elapsed_seconds,
                    }
                    self.last_run_completed_at = completed_at
                    self.last_summary = summary

                    logger.info(
                        "Switch status check completed: "
                        f"{reachable_count} reachable, {unreachable_count} unreachable, "
                        f"elapsed={elapsed_seconds}s"
                    )
                    return summary

        except Exception as e:
            logger.error(f"Error checking switch status: {str(e)}")
            failed_at = datetime.utcnow()
            self.last_run_completed_at = failed_at
            self.last_summary = {
                "status": "failed",
                "error": str(e),
                "started_at": started_at.isoformat(),
                "completed_at": failed_at.isoformat(),
            }
            return self.last_summary
        finally:
            self._is_checking = False

    async def run(self):
        """Run the periodic status checker"""
        self.running = True
        logger.info(
            "Starting switch status checker "
            f"(interval={self.check_interval}s, timeout={self.ping_timeout}s, concurrency={self.concurrency})"
        )

        while self.running:
            try:
                await self.check_all_switches()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                logger.info("Switch status checker cancelled")
                break
            except Exception as e:
                logger.error(f"Error in status checker loop: {str(e)}")
                await asyncio.sleep(self.check_interval)

    def start(self):
        """Start the background task"""
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self.run())
            logger.info("Switch status checker started")

    def stop(self):
        """Stop the background task"""
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            logger.info("Switch status checker stopped")

    def get_status(self) -> dict:
        """Return runtime status for debugging and operations."""
        return {
            "enabled": settings.FEATURE_STATUS_CHECKER,
            "running": self.running,
            "is_checking": self._is_checking,
            "interval_seconds": self.check_interval,
            "ping_timeout_seconds": self.ping_timeout,
            "concurrency": self.concurrency,
            "last_run_started_at": self.last_run_started_at.isoformat() if self.last_run_started_at else None,
            "last_run_completed_at": self.last_run_completed_at.isoformat() if self.last_run_completed_at else None,
            "last_summary": self.last_summary,
        }


# Global instance
switch_status_checker = SwitchStatusChecker()
