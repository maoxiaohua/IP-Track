from typing import Optional, Dict, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, cast, and_, or_, desc
from sqlalchemy.dialects.postgresql import MACADDR, INET
from models.switch import Switch
from models.arp_table import ARPTable
from models.mac_table import MACTable
from models.port_analysis import PortAnalysis
from models.query_history import QueryHistory
from models.mac_cache import MACAddressCache
from services.switch_manager import switch_manager, SwitchConnectionError
from core.config import settings
from utils.logger import logger
import time
import asyncio
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor


class IPLookupService:
    """Service for looking up IP addresses on network switches"""

    def __init__(self):
        # Thread pool for concurrent switch queries (configurable via environment)
        self.executor = ThreadPoolExecutor(max_workers=settings.IP_LOOKUP_WORKERS)

    def _query_arp_single(self, switch: Switch, target_ip: str) -> Tuple[Optional[Dict], Optional[Switch]]:
        """
        Query ARP table on a single switch (runs in thread pool)
        Returns tuple of (arp_data_dict, switch) where arp_data contains mac, port, vlan
        """
        try:
            logger.debug(f"Querying ARP table on switch {switch.name}")
            arp_data = switch_manager.query_arp_table_with_port(switch, target_ip)
            if arp_data and arp_data.get('mac'):
                logger.info(f"Found MAC {arp_data['mac']} for IP {target_ip} on switch {switch.name}")
                if arp_data.get('port'):
                    logger.info(f"Port info from ARP: {arp_data['port']}")
                return (arp_data, switch)
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

    async def _query_arp_concurrent(self, switches: List[Switch], target_ip: str) -> Tuple[Optional[Dict], Optional[Switch]]:
        """Query ARP tables on all switches concurrently, return arp_data dict and switch"""
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

    async def lookup_ip_from_cache(self, db: AsyncSession, target_ip: str) -> Dict[str, any]:
        """
        Fast IP lookup from cached database tables (arp_table and mac_table)
        Query time: <100ms (vs 20-30s for realtime queries)

        Returns detailed information about where the device is connected based on cached data
        """
        start_time = time.time()
        logger.info(f"Starting fast IP lookup from cache for {target_ip}")

        try:
            # Step 1: Query ARP table for the target IP
            # Get the most recent entry within last 24 hours
            arp_query = (
                select(ARPTable, Switch)
                .join(Switch, ARPTable.switch_id == Switch.id)
                .where(
                    and_(
                        cast(ARPTable.ip_address, INET) == cast(target_ip, INET),
                        ARPTable.last_seen > datetime.now(timezone.utc) - timedelta(hours=24)
                    )
                )
                .order_by(desc(ARPTable.last_seen))
                .limit(1)
            )

            result = await db.execute(arp_query)
            row = result.first()

            if not row:
                logger.info(f"No ARP entry found for IP {target_ip} in cache")
                await self._log_query(
                    db, target_ip, None, None, None, None,
                    "not_found", "No ARP entry found in cached data",
                    int((time.time() - start_time) * 1000)
                )
                return {
                    'found': False,
                    'target_ip': target_ip,
                    'message': 'No ARP entry found in cached data (last 24 hours)',
                    'query_time_ms': int((time.time() - start_time) * 1000),
                    'query_mode': 'cache'
                }

            arp_entry, switch = row
            mac_address = str(arp_entry.mac_address)

            logger.info(f"Found MAC {mac_address} for IP {target_ip} in cache (last seen: {arp_entry.last_seen})")

            # Store ARP interface as fallback (may be L3 interface like irb99, vlan99)
            arp_interface = arp_entry.interface
            vlan_id = arp_entry.vlan_id
            data_age_seconds = int((datetime.now(timezone.utc) - arp_entry.last_seen).total_seconds())

            # Step 2: Always query MAC table first to get physical port
            # (ARP interface is often L3 interface like IRB, not physical port)
            logger.info(f"Checking MAC table for physical port of MAC {mac_address}")

            mac_query = (
                select(MACTable)
                .outerjoin(
                    PortAnalysis,
                    and_(
                        PortAnalysis.switch_id == MACTable.switch_id,
                        PortAnalysis.port_name == MACTable.port_name
                    )
                )
                .where(
                    and_(
                        cast(MACTable.mac_address, MACADDR) == cast(mac_address, MACADDR),
                        # MACTable.switch_id == switch.id,  # REMOVED: Allow finding MAC on any switch
                        MACTable.last_seen > datetime.now(timezone.utc) - timedelta(hours=24)
                    )
                )
                # IP Lookup MUST filter trunk/uplink ports
                # Only search in access ports (1 MAC) to find true device connection
                # This ensures we return the actual physical connection point
                .where(
                    or_(
                        # Include if no port analysis (new ports)
                        PortAnalysis.id.is_(None),
                        # ONLY include access ports (1 MAC = true device connection)
                        PortAnalysis.port_type == 'access'
                    )
                )

                .order_by(desc(MACTable.last_seen))
                .limit(1)
            )

            mac_result = await db.execute(mac_query)
            mac_entry = mac_result.scalar_one_or_none()

            if mac_entry:
                # Found physical port in MAC table
                # IMPORTANT: Use the switch from MAC table (physical location), not from ARP (gateway)
                # This handles L2/L3 topology where ARP is on gateway but MAC is on access switch
                port_name = mac_entry.port_name
                vlan_id = mac_entry.vlan_id or vlan_id
                
                # Get the actual switch where MAC was found (physical connection)
                actual_switch_result = await db.execute(
                    select(Switch).where(Switch.id == mac_entry.switch_id)
                )
                actual_switch = actual_switch_result.scalar_one_or_none()
                if actual_switch:
                    switch = actual_switch  # Override with physical switch location
                
                # Update data age to MAC table entry if it's newer
                mac_age_seconds = int((datetime.now(timezone.utc) - mac_entry.last_seen).total_seconds())
                data_age_seconds = max(data_age_seconds, mac_age_seconds)
                logger.info(f"Found physical port {port_name} in MAC table on switch {switch.name} (ID: {switch.id})")
            elif arp_interface:
                # Fallback to ARP interface (may be L3 interface like irb99)
                port_name = arp_interface
                logger.info(f"Using ARP interface {port_name} (MAC table entry not found)")
            else:
                # No port info at all
                logger.info(f"No port information found for {mac_address}")
                await self._log_query(
                    db, target_ip, mac_address, None, None, None,
                    "not_found", "MAC address found but port information not available",
                    int((time.time() - start_time) * 1000)
                )
                return {
                    'found': False,
                    'target_ip': target_ip,
                    'mac_address': mac_address,
                    'message': 'MAC address found but port information not available',
                    'query_time_ms': int((time.time() - start_time) * 1000),
                    'query_mode': 'cache',
                    'data_age_seconds': data_age_seconds
                }

            # Step 3: Update MAC cache
            if port_name:
                await self._update_mac_cache(
                    db, mac_address, target_ip, switch.id,
                    port_name, vlan_id or 1
                )

            # Step 4: Log successful query
            query_time_ms = int((time.time() - start_time) * 1000)
            await self._log_query(
                db, target_ip, mac_address, switch.id,
                port_name, vlan_id,
                "success", None, query_time_ms
            )

            logger.info(f"Successfully located IP {target_ip} on switch {switch.name} port {port_name} (from cache, {data_age_seconds}s old)")

            return {
                'found': True,
                'target_ip': target_ip,
                'mac_address': mac_address,
                'switch_id': switch.id,
                'switch_name': switch.name,
                'switch_ip': str(switch.ip_address),
                'port_name': port_name,
                'vlan_id': vlan_id or 1,
                'query_time_ms': query_time_ms,
                'query_mode': 'cache',
                'data_age_seconds': data_age_seconds,
                'last_seen': arp_entry.last_seen.isoformat(),
                'message': f'Device located from cached data (data age: {data_age_seconds}s)'
            }

        except Exception as e:
            logger.error(f"Unexpected error during cache lookup: {str(e)}", exc_info=True)
            await self._log_query(
                db, target_ip, None, None, None, None,
                "error", f"Cache lookup error: {str(e)}",
                int((time.time() - start_time) * 1000)
            )
            return {
                'found': False,
                'target_ip': target_ip,
                'message': f'Cache lookup error: {str(e)}',
                'query_time_ms': int((time.time() - start_time) * 1000),
                'query_mode': 'cache'
            }

    async def lookup_ip_realtime(self, db: AsyncSession, target_ip: str) -> Dict[str, any]:
        """
        Realtime IP lookup by querying switches directly via SSH/CLI
        Query time: 20-30s for 339 switches

        Returns detailed information about where the device is connected
        """
        start_time = time.time()
        logger.info(f"Starting REALTIME IP lookup for {target_ip}")

        try:
            # Get all enabled switches
            result = await db.execute(
                select(Switch)
                .where(Switch.enabled == True)
                .order_by(Switch.id.asc())
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
                    'query_time_ms': int((time.time() - start_time) * 1000),
                    'query_mode': 'realtime'
                }

            logger.info(f"Querying {len(switches)} switches concurrently")

            # Step 1: Query ARP tables to find MAC address (concurrent across all switches)
            mac_address = None
            arp_switch = None
            arp_data = None

            logger.info(f"Querying all {len(switches)} switches for ARP")
            arp_data, arp_switch = await self._query_arp_concurrent(switches, target_ip)
            if arp_data and arp_data.get('mac'):
                mac_address = arp_data['mac']

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
                    'query_time_ms': int((time.time() - start_time) * 1000),
                    'query_mode': 'realtime'
                }

            # Step 2: Check if port info is already available from ARP output
            if arp_data.get('port'):
                # Port info available from ARP (Dell S5232 and similar)
                logger.info(f"Port information available from ARP: {arp_data['port']}")

                # Check if port should be included (filter trunk ports)
                include, reason = await self._should_include_port(
                    db, arp_switch.id, arp_data['port']
                )

                if not include:
                    # Port is filtered (trunk/uplink), treat as not found
                    logger.info(
                        f"Filtered trunk port {arp_data['port']} from ARP on {arp_switch.name} "
                        f"(reason: {reason}). Treating as not found."
                    )
                    await self._log_query(
                        db, target_ip, mac_address, None, None, None,
                        "filtered", f"Port filtered: {reason}",
                        int((time.time() - start_time) * 1000)
                    )
                    return {
                        'found': False,
                        'target_ip': target_ip,
                        'mac_address': mac_address,
                        'message': f'Port {arp_data["port"]} filtered (trunk/uplink port)',
                        'query_time_ms': int((time.time() - start_time) * 1000),
                        'query_mode': 'realtime',
                        'filtered_port': arp_data['port'],
                        'filter_reason': reason
                    }

                port_info = {
                    'port': arp_data['port'],
                    'vlan': arp_data.get('vlan', 1),  # Default to VLAN 1 if not provided
                    'mac': mac_address
                }
                port_switch = arp_switch

                # Update cache and log
                await self._update_mac_cache(
                    db, mac_address, target_ip, port_switch.id,
                    port_info['port'], port_info['vlan']
                )

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
                    'query_mode': 'realtime',
                    'message': 'Device successfully located (realtime query from ARP)'
                }

            # Step 2b: Query MAC address tables to find port (concurrent across all switches)
            results = []
            port_switch = None

            logger.info(f"Querying all {len(switches)} switches for MAC")
            results, port_switch = await self._query_mac_concurrent(switches, mac_address)

            # Filter trunk ports
            if results and port_switch:
                filtered_results = []
                for port_info in results:
                    include, reason = await self._should_include_port(
                        db, port_switch.id, port_info['port']
                    )
                    if include:
                        filtered_results.append(port_info)
                        logger.debug(f"Including port {port_info['port']} on {port_switch.name} (reason: {reason})")
                    else:
                        logger.info(
                            f"Filtered trunk port {port_info['port']} on {port_switch.name} "
                            f"for MAC {mac_address} (reason: {reason})"
                        )
                results = filtered_results

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
                    'query_time_ms': int((time.time() - start_time) * 1000),
                    'query_mode': 'realtime'
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
                'query_mode': 'realtime',
                'message': 'Device successfully located (realtime query from MAC table)'
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
                'message': f'Realtime lookup error: {str(e)}',
                'query_time_ms': int((time.time() - start_time) * 1000),
                'query_mode': 'realtime'
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
            # Check if entry exists - cast string to MACADDR for comparison
            result = await db.execute(
                select(MACAddressCache).where(
                    cast(MACAddressCache.mac_address, MACADDR) == cast(mac, MACADDR),
                    MACAddressCache.switch_id == switch_id,
                    MACAddressCache.port_name == port
                )
            )
            cache_entry = result.scalar_one_or_none()

            if cache_entry:
                # Update existing entry
                cache_entry.ip_address = ip
                cache_entry.vlan_id = vlan
                cache_entry.last_seen = datetime.now(timezone.utc)
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

    async def _should_include_port(
        self,
        db: AsyncSession,
        switch_id: int,
        port_name: str
    ) -> Tuple[bool, str]:
        """
        Determine if port should be included in lookup results.
        Filters trunk/uplink ports based on port_analysis.

        Args:
            db: Database session
            switch_id: Switch ID
            port_name: Port name to check

        Returns:
            Tuple of (include: bool, reason: str)
            - include: True if port should be included in results
            - reason: Explanation for the decision
        """
        try:
            # Query port_analysis for this port
            result = await db.execute(
                select(PortAnalysis).where(
                    and_(
                        PortAnalysis.switch_id == switch_id,
                        PortAnalysis.port_name == port_name
                    )
                )
            )
            port_analysis = result.scalar_one_or_none()

            # No analysis - allow port (conservative approach)
            if not port_analysis:
                return (True, "no_analysis")

            # Primary filter: port_type
            if port_analysis.port_type in ['trunk', 'uplink']:
                return (
                    False,
                    f"port_type={port_analysis.port_type}, macs={port_analysis.mac_count}"
                )

            # Backup filter: excessive MAC count (safety net for misclassified ports)
            if port_analysis.mac_count > 10:
                return (False, f"excessive_macs={port_analysis.mac_count}")

            # Include this port
            return (True, f"access_port (type={port_analysis.port_type}, macs={port_analysis.mac_count})")

        except Exception as e:
            logger.error(f"Error checking port analysis for {port_name}: {str(e)}")
            # On error, include port (conservative approach - don't filter due to errors)
            return (True, f"error_checking_analysis: {str(e)}")

    async def lookup_ip(self, db: AsyncSession, target_ip: str, mode: str = 'auto') -> Dict[str, any]:
        """
        Smart IP lookup with multiple query modes

        Args:
            db: Database session
            target_ip: Target IP address to lookup
            mode: Query mode - 'auto', 'cache', or 'realtime'
                  - 'auto' (default): Try cache first, fallback to realtime if not found
                  - 'cache': Only query database (fast, <100ms)
                  - 'realtime': Only query switches via SSH (slow, 20-30s, most accurate)

        Returns:
            Dict with lookup results including query_mode indicator
        """
        logger.info(f"IP lookup request for {target_ip}, mode={mode}")

        if mode == 'realtime':
            # Force realtime query
            return await self.lookup_ip_realtime(db, target_ip)

        if mode == 'cache':
            # Force cache query only
            return await self.lookup_ip_from_cache(db, target_ip)

        # Auto mode: Try cache first, fallback to realtime if needed
        if mode == 'auto':
            logger.info("Auto mode: Trying cache lookup first")
            cache_result = await self.lookup_ip_from_cache(db, target_ip)

            if cache_result['found']:
                # Found in cache, return immediately
                logger.info(f"Found in cache, returning result (age: {cache_result.get('data_age_seconds', 0)}s)")
                return cache_result

            # Not found in cache, try realtime query
            logger.info("Not found in cache, falling back to realtime query")
            realtime_result = await self.lookup_ip_realtime(db, target_ip)
            realtime_result['query_mode'] = 'auto_fallback'  # Indicate we fell back to realtime
            return realtime_result

        # Invalid mode, default to auto
        logger.warning(f"Invalid mode '{mode}', defaulting to auto")
        return await self.lookup_ip(db, target_ip, mode='auto')


# Singleton instance
ip_lookup_service = IPLookupService()
