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
from services.port_lookup_policy_service import build_lookup_eligible_clause
from services.data_freshness_service import build_lookup_result_freshness
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

    @staticmethod
    def _is_usable_arp_interface(interface_name: Optional[str]) -> bool:
        if not interface_name:
            return False

        cleaned = str(interface_name).strip()
        if not cleaned:
            return False

        lowered = cleaned.lower()
        if lowered in {'dyn', 'dyn[i]', 'oth', 'oth[i]', 'other', 'other[i]', 'irb-interface'}:
            return False

        if lowered.startswith(('irb', 'vlan', 'vlan.', 'loopback', 'lo', 'system', 'null', 'bridge', 'bvi', 'mgmt')):
            return False

        if '[' in cleaned and ']' in cleaned:
            return False

        return True

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

    async def lookup_ip(self, db: AsyncSession, target_ip: str) -> Dict[str, any]:
        """
        Fast IP lookup from cached database tables (arp_table and mac_table)
        Query time: <100ms

        Returns detailed information about where the device is connected based on cached data
        Data from the last collection cycle. Query window is DYNAMICALLY configurable via database settings.
        """
        start_time = time.time()
        logger.info(f"Starting fast IP lookup from cache for {target_ip}")

        try:
            # Get dynamic cache hours from settings (with fallback to env)
            from services.settings_service import settings_service
            from core.config import settings as env_settings
            cache_hours = await settings_service.get_setting(
                db, 'ip_lookup_cache_hours', env_settings.IP_LOOKUP_CACHE_HOURS
            )

            # Step 1: Query ARP table for the target IP
            # Get the most recent entry within configurable time window
            arp_query = (
                select(ARPTable, Switch)
                .join(Switch, ARPTable.switch_id == Switch.id)
                .where(
                    and_(
                        cast(ARPTable.ip_address, INET) == cast(target_ip, INET),
                        ARPTable.last_seen > datetime.now(timezone.utc) - timedelta(hours=cache_hours)
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
                    db, target_ip, None, None, None, None, None,
                    "not_found", "No ARP entry found in cached data",
                    int((time.time() - start_time) * 1000)
                )
                return {
                    'found': False,
                    'target_ip': target_ip,
                    'message': f'No ARP entry found in cached data (last {int(cache_hours)} hours)',
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
                        MACTable.last_seen > datetime.now(timezone.utc) - timedelta(hours=cache_hours)
                    )
                )
                .where(build_lookup_eligible_clause(PortAnalysis))

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
            else:
                same_switch_mac_result = await db.execute(
                    select(MACTable)
                    .where(
                        and_(
                            cast(MACTable.mac_address, MACADDR) == cast(mac_address, MACADDR),
                            MACTable.switch_id == switch.id,
                            MACTable.last_seen > datetime.now(timezone.utc) - timedelta(hours=cache_hours)
                        )
                    )
                    .order_by(desc(MACTable.last_seen))
                    .limit(1)
                )
                same_switch_mac_entry = same_switch_mac_result.scalar_one_or_none()

                if same_switch_mac_entry:
                    port_name = same_switch_mac_entry.port_name
                    vlan_id = same_switch_mac_entry.vlan_id or vlan_id
                    mac_age_seconds = int((datetime.now(timezone.utc) - same_switch_mac_entry.last_seen).total_seconds())
                    data_age_seconds = max(data_age_seconds, mac_age_seconds)
                    logger.info(
                        f"Found same-switch MAC port {port_name} for {target_ip} on "
                        f"{switch.name} after lookup-policy filtering excluded other candidates"
                    )
                elif arp_interface and self._is_usable_arp_interface(arp_interface):
                    # Fallback to ARP interface only when it looks like a real port.
                    port_name = arp_interface
                    logger.info(f"Using ARP interface {port_name} (MAC table entry not found)")
                else:
                    # No port info at all
                    logger.info(f"No port information found for {mac_address}")
                    await self._log_query(
                        db, target_ip, mac_address, None, None, None, None,
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
                db, target_ip, mac_address, switch.id, switch.name,
                port_name, vlan_id,
                "success", None, query_time_ms
            )

            logger.info(f"Successfully located IP {target_ip} on switch {switch.name} port {port_name} (from cache, {data_age_seconds}s old)")
            freshness = build_lookup_result_freshness(
                switch,
                data_age_seconds=data_age_seconds,
                last_seen_at=arp_entry.last_seen
            )

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
                'message': f'Device located from cached data (data age: {data_age_seconds}s)',
                'freshness': freshness
            }

        except Exception as e:
            logger.error(f"Unexpected error during cache lookup: {str(e)}", exc_info=True)
            await self._log_query(
                db, target_ip, None, None, None, None, None,
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

    async def _log_query(
        self, db: AsyncSession, target_ip: str, mac: Optional[str],
        switch_id: Optional[int], switch_name: Optional[str], port: Optional[str], vlan: Optional[int],
        status: str, error_msg: Optional[str], query_time_ms: int
    ):
        """Log query to history table"""
        try:
            history = QueryHistory(
                target_ip=target_ip,
                found_mac=mac,
                switch_id=switch_id,
                switch_name=switch_name,
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



# Singleton instance
ip_lookup_service = IPLookupService()
