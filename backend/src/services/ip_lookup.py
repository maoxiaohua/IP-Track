from typing import Optional, Dict, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models.switch import Switch
from models.query_history import QueryHistory
from models.mac_cache import MACAddressCache
from services.switch_manager import switch_manager, SwitchConnectionError
from utils.logger import logger
import time
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor


class IPLookupService:
    """Service for looking up IP addresses on network switches"""

    def __init__(self):
        # Thread pool for concurrent switch queries
        self.executor = ThreadPoolExecutor(max_workers=10)

    def _query_arp_single(self, switch: Switch, target_ip: str) -> Tuple[Optional[str], Optional[Switch]]:
        """Query ARP table on a single switch (runs in thread pool)"""
        try:
            logger.debug(f"Querying ARP table on switch {switch.name}")
            found_mac = switch_manager.query_arp_table(switch, target_ip)
            if found_mac:
                logger.info(f"Found MAC {found_mac} for IP {target_ip} on switch {switch.name}")
                return (found_mac, switch)
            return (None, None)
        except SwitchConnectionError as e:
            logger.error(f"Failed to query switch {switch.name}: {str(e)}")
            return (None, None)
        except Exception as e:
            logger.error(f"Unexpected error querying switch {switch.name}: {str(e)}")
            return (None, None)

    def _query_mac_single(self, switch: Switch, mac_address: str) -> Tuple[List, Optional[Switch]]:
        """Query MAC table on a single switch (runs in thread pool)"""
        try:
            logger.debug(f"Querying MAC table on switch {switch.name}")
            results = switch_manager.query_mac_table(switch, mac_address)
            if results:
                logger.info(f"Found {len(results)} port(s) for MAC {mac_address} on switch {switch.name}")
                return (results, switch)
            return ([], None)
        except SwitchConnectionError as e:
            logger.error(f"Failed to query switch {switch.name}: {str(e)}")
            return ([], None)
        except Exception as e:
            logger.error(f"Unexpected error querying switch {switch.name}: {str(e)}")
            return ([], None)

    async def _query_arp_concurrent(self, switches: List[Switch], target_ip: str) -> Tuple[Optional[str], Optional[Switch]]:
        """Query ARP tables on all switches concurrently"""
        loop = asyncio.get_event_loop()

        # Create tasks for all switches
        tasks = [
            loop.run_in_executor(self.executor, self._query_arp_single, switch, target_ip)
            for switch in switches
        ]

        # Wait for all queries to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Find the first successful result
        for result in results:
            if isinstance(result, tuple) and result[0] is not None:
                return result

        return (None, None)

    async def _query_mac_concurrent(self, switches: List[Switch], mac_address: str) -> Tuple[List, Optional[Switch]]:
        """Query MAC tables on all switches concurrently"""
        loop = asyncio.get_event_loop()

        # Create tasks for all switches
        tasks = [
            loop.run_in_executor(self.executor, self._query_mac_single, switch, mac_address)
            for switch in switches
        ]

        # Wait for all queries to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Find the first successful result
        for result in results:
            if isinstance(result, tuple) and result[0]:
                return result

        return ([], None)

    async def lookup_ip(self, db: AsyncSession, target_ip: str) -> Dict[str, any]:
        """
        Lookup an IP address across all enabled switches
        Returns detailed information about where the device is connected
        """
        start_time = time.time()
        logger.info(f"Starting IP lookup for {target_ip}")

        try:
            # Get all enabled switches ordered by priority (lower number = higher priority)
            result = await db.execute(
                select(Switch)
                .where(Switch.enabled == True)
                .order_by(Switch.priority.asc(), Switch.role.desc())  # Core first, then aggregation, then access
            )
            switches = result.scalars().all()

            if not switches:
                logger.warning("No enabled switches found in database")
                await self._log_query(
                    db, target_ip, None, None, None, None,
                    "error", "No enabled switches configured",
                    int((time.time() - start_time) * 1000)
                )
                return {
                    'found': False,
                    'target_ip': target_ip,
                    'message': 'No enabled switches configured',
                    'query_time_ms': int((time.time() - start_time) * 1000)
                }

            logger.info(f"Querying {len(switches)} switches ordered by priority")

            # Step 1: Query ARP tables to find MAC address (concurrent, but prioritized)
            # Group switches by priority for staged querying
            priority_groups = {}
            for switch in switches:
                if switch.priority not in priority_groups:
                    priority_groups[switch.priority] = []
                priority_groups[switch.priority].append(switch)

            mac_address = None
            arp_switch = None

            # Query by priority groups (highest priority first)
            for priority in sorted(priority_groups.keys()):
                group_switches = priority_groups[priority]
                logger.info(f"Querying priority {priority} group ({len(group_switches)} switches) for ARP")
                mac_address, arp_switch = await self._query_arp_concurrent(group_switches, target_ip)
                if mac_address:
                    break  # Found MAC, stop querying

            if not mac_address:
                logger.info(f"No ARP entry found for IP {target_ip}")
                await self._log_query(
                    db, target_ip, None, None, None, None,
                    "not_found", "No ARP entry found for this IP",
                    int((time.time() - start_time) * 1000)
                )
                return {
                    'found': False,
                    'target_ip': target_ip,
                    'message': 'No ARP entry found for this IP address',
                    'query_time_ms': int((time.time() - start_time) * 1000)
                }

            # Step 2: Query MAC address tables to find port (concurrent, prioritized)
            results = []
            port_switch = None

            # Query by priority groups (same order as ARP query)
            for priority in sorted(priority_groups.keys()):
                group_switches = priority_groups[priority]
                logger.info(f"Querying priority {priority} group ({len(group_switches)} switches) for MAC")
                results, port_switch = await self._query_mac_concurrent(group_switches, mac_address)
                if results:
                    break  # Found MAC, stop querying

            port_info = results[0] if results else None

            if not port_info:
                logger.info(f"MAC {mac_address} not found in any MAC address table")
                await self._log_query(
                    db, target_ip, mac_address, None, None, None,
                    "not_found", "MAC address not found in any switch MAC table",
                    int((time.time() - start_time) * 1000)
                )
                return {
                    'found': False,
                    'target_ip': target_ip,
                    'mac_address': mac_address,
                    'message': 'MAC address not found in any switch MAC table',
                    'query_time_ms': int((time.time() - start_time) * 1000)
                }

            # Step 3: Update MAC address cache
            await self._update_mac_cache(
                db, mac_address, target_ip, port_switch.id,
                port_info['port'], port_info['vlan']
            )

            # Step 4: Log successful query
            query_time_ms = int((time.time() - start_time) * 1000)
            await self._log_query(
                db, target_ip, mac_address, port_switch.id,
                port_info['port'], port_info['vlan'],
                "success", None, query_time_ms
            )

            logger.info(f"Successfully located IP {target_ip} on switch {port_switch.name} port {port_info['port']}")

            return {
                'found': True,
                'target_ip': target_ip,
                'mac_address': mac_address,
                'switch_id': port_switch.id,
                'switch_name': port_switch.name,
                'switch_ip': str(port_switch.ip_address),
                'port_name': port_info['port'],
                'vlan_id': port_info['vlan'],
                'query_time_ms': query_time_ms,
                'message': 'Device successfully located'
            }

        except Exception as e:
            logger.error(f"Unexpected error during IP lookup: {str(e)}")
            await self._log_query(
                db, target_ip, None, None, None, None,
                "error", f"Internal error: {str(e)}",
                int((time.time() - start_time) * 1000)
            )
            return {
                'found': False,
                'target_ip': target_ip,
                'message': f'Internal error: {str(e)}',
                'query_time_ms': int((time.time() - start_time) * 1000)
            }

    async def _log_query(
        self, db: AsyncSession, target_ip: str, mac: Optional[str],
        switch_id: Optional[int], port: Optional[str], vlan: Optional[int],
        status: str, error_msg: Optional[str], query_time_ms: int
    ):
        """Log query to history table"""
        try:
            history = QueryHistory(
                target_ip=target_ip,
                found_mac=mac,
                switch_id=switch_id,
                port_name=port,
                vlan_id=vlan,
                query_status=status,
                error_message=error_msg,
                query_time_ms=query_time_ms
            )
            db.add(history)
            await db.commit()
        except Exception as e:
            logger.error(f"Failed to log query history: {str(e)}")
            await db.rollback()

    async def _update_mac_cache(
        self, db: AsyncSession, mac: str, ip: str,
        switch_id: int, port: str, vlan: int
    ):
        """Update or create MAC address cache entry"""
        try:
            # Check if entry exists
            result = await db.execute(
                select(MACAddressCache).where(
                    MACAddressCache.mac_address == mac,
                    MACAddressCache.switch_id == switch_id,
                    MACAddressCache.port_name == port
                )
            )
            cache_entry = result.scalar_one_or_none()

            if cache_entry:
                # Update existing entry
                cache_entry.ip_address = ip
                cache_entry.vlan_id = vlan
                cache_entry.last_seen = datetime.utcnow()
            else:
                # Create new entry
                cache_entry = MACAddressCache(
                    mac_address=mac,
                    ip_address=ip,
                    switch_id=switch_id,
                    port_name=port,
                    vlan_id=vlan
                )
                db.add(cache_entry)

            await db.commit()
            logger.debug(f"Updated MAC cache for {mac}")

        except Exception as e:
            logger.error(f"Failed to update MAC cache: {str(e)}")
            await db.rollback()


# Singleton instance
ip_lookup_service = IPLookupService()
