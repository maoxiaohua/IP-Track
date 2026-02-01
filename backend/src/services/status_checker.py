"""
Background service for periodic switch status checks
"""
import asyncio
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import AsyncSessionLocal
from models.switch import Switch
from utils.network import ping_multiple_hosts
from utils.logger import logger


class SwitchStatusChecker:
    """Background service to periodically check switch status via ping"""

    def __init__(self, check_interval: int = 30):
        """
        Initialize the status checker

        Args:
            check_interval: Interval in seconds between checks (default: 30)
        """
        self.check_interval = check_interval
        self.running = False
        self.task = None

    async def check_all_switches(self):
        """Check status of all switches"""
        try:
            async with AsyncSessionLocal() as db:
                # Get all enabled switches
                result = await db.execute(
                    select(Switch).where(Switch.enabled == True)
                )
                switches = result.scalars().all()

                if not switches:
                    logger.debug("No switches to check")
                    return

                # Ping all switches concurrently
                switch_ips = {str(sw.ip_address): sw for sw in switches}
                ping_results = await ping_multiple_hosts(list(switch_ips.keys()), timeout=2)

                # Update switch status
                reachable_count = 0
                unreachable_count = 0

                for ip, ping_result in ping_results.items():
                    switch = switch_ips[ip]
                    switch.is_reachable = ping_result["reachable"]
                    switch.last_check_at = datetime.utcnow()
                    switch.response_time_ms = ping_result.get("response_time_ms")

                    if ping_result["reachable"]:
                        reachable_count += 1
                    else:
                        unreachable_count += 1

                await db.commit()

                logger.info(
                    f"Switch status check completed: "
                    f"{reachable_count} reachable, {unreachable_count} unreachable"
                )

        except Exception as e:
            logger.error(f"Error checking switch status: {str(e)}")

    async def run(self):
        """Run the periodic status checker"""
        self.running = True
        logger.info(f"Starting switch status checker (interval: {self.check_interval}s)")

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


# Global instance
switch_status_checker = SwitchStatusChecker(check_interval=30)
