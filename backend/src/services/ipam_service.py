from typing import Optional, List, Dict, Any, Callable, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, cast, Text, String, Integer, delete
from models.ipam import IPSubnet, IPAddress, IPScanHistory, IPStatus
from models.switch import Switch
from models.arp_table import ARPTable
from models.mac_table import MACTable
from models.port_analysis import PortAnalysis
from services.ip_scan import ip_scan_service
from services.ip_lookup import ip_lookup_service
from services.port_lookup_policy_service import build_lookup_eligible_clause
from core.config import settings
from core.database import AsyncSessionLocal
from utils.logger import logger
import ipaddress
from datetime import datetime, timedelta, timezone
import asyncio
import ctypes
import gc


class IPAMService:
    """Service for IP Address Management"""

    _libc = None

    @classmethod
    def _malloc_trim(cls) -> bool:
        """Ask glibc to return free heap pages to the OS when available."""
        try:
            if cls._libc is None:
                cls._libc = ctypes.CDLL("libc.so.6")
            return bool(cls._libc.malloc_trim(0))
        except Exception:
            return False

    def _release_scan_memory(self, context: str) -> None:
        """
        Reclaim short-lived scan allocations so long IPAM passes do not keep
        pushing RSS upward just because the allocator holds onto free arenas.
        """
        collected = gc.collect()
        trimmed = self._malloc_trim()

        if collected or trimmed:
            logger.debug(
                f"Released scan memory after {context}: "
                f"gc_collected={collected}, malloc_trim={trimmed}"
            )

    def _ip_address_order_by(self):
        """Return numeric IPv4 ordering expressions for subnet detail listings."""
        ip_text = func.host(IPAddress.ip_address)
        return [
            cast(func.split_part(ip_text, '.', 1), Integer),
            cast(func.split_part(ip_text, '.', 2), Integer),
            cast(func.split_part(ip_text, '.', 3), Integer),
            cast(func.split_part(ip_text, '.', 4), Integer),
        ]

    @staticmethod
    def _normalize_mac(mac_address: Optional[str]) -> Optional[str]:
        if not mac_address:
            return None
        return str(mac_address).lower()

    @staticmethod
    def _is_usable_arp_interface(interface_name: Optional[str]) -> bool:
        """
        ARP interfaces are sometimes logical placeholders rather than real ports.

        Examples seen on some 7250 IXR-e2 devices:
        - Dyn[I]
        - Oth[I]
        - Oth
        """
        if not interface_name:
            return False

        cleaned = str(interface_name).strip()
        if not cleaned:
            return False

        lowered = cleaned.lower()
        placeholder_values = {
            'dyn',
            'dyn[i]',
            'oth',
            'oth[i]',
            'other',
            'other[i]',
            'irb-interface',
        }
        if lowered in placeholder_values:
            return False

        non_physical_prefixes = (
            'irb',
            'vlan',
            'vlan.',
            'loopback',
            'lo',
            'system',
            'null',
            'bridge',
            'bvi',
            'mgmt',
        )
        if lowered.startswith(non_physical_prefixes):
            return False

        if '[' in cleaned and ']' in cleaned:
            return False

        return True

    async def get_live_location_overlays(
        self,
        db: AsyncSession,
        ip_addresses: List[IPAddress]
    ) -> Dict[int, Dict[str, Optional[str]]]:
        """
        Build best-effort switch/port overlays from the live ARP/MAC cache tables.

        This is used as a read-time fallback when the denormalized IPAM fields have
        not yet been refreshed by a subnet scan.
        """
        if not ip_addresses:
            return {}

        ip_by_string = {str(ip_addr.ip_address): ip_addr for ip_addr in ip_addresses}
        ip_strings = list(ip_by_string.keys())

        arp_rows = await db.execute(
            select(
                func.host(ARPTable.ip_address).label('ip_address'),
                cast(ARPTable.mac_address, String).label('mac_address'),
                ARPTable.switch_id.label('switch_id'),
                Switch.name.label('switch_name'),
                ARPTable.interface.label('switch_port'),
                ARPTable.vlan_id.label('vlan_id')
            )
            .join(Switch, ARPTable.switch_id == Switch.id)
            .where(func.host(ARPTable.ip_address).in_(ip_strings))
            .order_by(func.host(ARPTable.ip_address), ARPTable.last_seen.desc())
        )

        latest_arp_by_ip: Dict[str, Dict[str, Optional[str]]] = {}
        for row in arp_rows.mappings():
            ip_string = row['ip_address']
            if ip_string not in latest_arp_by_ip:
                latest_arp_by_ip[ip_string] = dict(row)

        macs = set()
        for ip_addr in ip_addresses:
            stored_mac = self._normalize_mac(str(ip_addr.mac_address)) if ip_addr.mac_address else None
            arp_mac = self._normalize_mac(latest_arp_by_ip.get(str(ip_addr.ip_address), {}).get('mac_address'))
            if stored_mac:
                macs.add(stored_mac)
            if arp_mac:
                macs.add(arp_mac)

        latest_mac_by_mac: Dict[str, Dict[str, Optional[str]]] = {}
        if macs:
            mac_rows = await db.execute(
                select(
                    cast(MACTable.mac_address, String).label('mac_address'),
                    MACTable.switch_id.label('switch_id'),
                    Switch.name.label('switch_name'),
                    MACTable.port_name.label('switch_port'),
                    MACTable.vlan_id.label('vlan_id')
                )
                .join(Switch, MACTable.switch_id == Switch.id)
                .outerjoin(
                    PortAnalysis,
                    and_(
                        PortAnalysis.switch_id == MACTable.switch_id,
                        PortAnalysis.port_name == MACTable.port_name
                    )
                )
                .where(func.lower(cast(MACTable.mac_address, String)).in_(list(macs)))
                .where(build_lookup_eligible_clause(PortAnalysis))
                .order_by(func.lower(cast(MACTable.mac_address, String)), MACTable.last_seen.desc())
            )

            for row in mac_rows.mappings():
                mac_key = self._normalize_mac(row['mac_address'])
                if mac_key and mac_key not in latest_mac_by_mac:
                    latest_mac_by_mac[mac_key] = dict(row)

        same_switch_mac_by_pair: Dict[tuple[int, str], Dict[str, Optional[str]]] = {}
        preferred_switch_ids = {
            int(arp_row['switch_id'])
            for arp_row in latest_arp_by_ip.values()
            if arp_row.get('switch_id') is not None
        }
        if macs and preferred_switch_ids:
            same_switch_rows = await db.execute(
                select(
                    cast(MACTable.mac_address, String).label('mac_address'),
                    MACTable.switch_id.label('switch_id'),
                    Switch.name.label('switch_name'),
                    MACTable.port_name.label('switch_port'),
                    MACTable.vlan_id.label('vlan_id')
                )
                .join(Switch, MACTable.switch_id == Switch.id)
                .where(MACTable.switch_id.in_(list(preferred_switch_ids)))
                .where(func.lower(cast(MACTable.mac_address, String)).in_(list(macs)))
                .order_by(MACTable.switch_id, func.lower(cast(MACTable.mac_address, String)), MACTable.last_seen.desc())
            )

            for row in same_switch_rows.mappings():
                mac_key = self._normalize_mac(row['mac_address'])
                switch_id = row['switch_id']
                if mac_key is None or switch_id is None:
                    continue
                pair_key = (int(switch_id), mac_key)
                if pair_key not in same_switch_mac_by_pair:
                    same_switch_mac_by_pair[pair_key] = dict(row)

        overlays: Dict[int, Dict[str, Optional[str]]] = {}
        for ip_string, ip_addr in ip_by_string.items():
            arp_overlay = latest_arp_by_ip.get(ip_string)
            stored_mac = self._normalize_mac(str(ip_addr.mac_address)) if ip_addr.mac_address else None
            arp_mac = self._normalize_mac(arp_overlay.get('mac_address')) if arp_overlay else None
            effective_mac = stored_mac or arp_mac
            mac_overlay = latest_mac_by_mac.get(effective_mac) if effective_mac else None
            same_switch_mac_overlay = None
            if arp_overlay and effective_mac and arp_overlay.get('switch_id') is not None:
                same_switch_mac_overlay = same_switch_mac_by_pair.get((int(arp_overlay['switch_id']), effective_mac))
            arp_port = arp_overlay.get('switch_port') if arp_overlay else None
            usable_arp_port = arp_port if self._is_usable_arp_interface(arp_port) else None

            if mac_overlay or arp_overlay or effective_mac:
                overlays[ip_addr.id] = {
                    'mac_address': effective_mac,
                    'switch_id': (
                        mac_overlay.get('switch_id') if mac_overlay
                        else same_switch_mac_overlay.get('switch_id') if same_switch_mac_overlay
                        else arp_overlay.get('switch_id') if arp_overlay
                        else None
                    ),
                    'switch_name': (
                        mac_overlay.get('switch_name') if mac_overlay
                        else same_switch_mac_overlay.get('switch_name') if same_switch_mac_overlay
                        else arp_overlay.get('switch_name') if arp_overlay
                        else None
                    ),
                    'switch_port': (
                        mac_overlay.get('switch_port') if mac_overlay
                        else same_switch_mac_overlay.get('switch_port') if same_switch_mac_overlay
                        else usable_arp_port
                    ),
                    'vlan_id': (
                        mac_overlay.get('vlan_id') if mac_overlay else None
                    ) or (
                        same_switch_mac_overlay.get('vlan_id') if same_switch_mac_overlay else None
                    ) or (
                        arp_overlay.get('vlan_id') if arp_overlay else None
                    )
                }

        return overlays

    async def create_subnet(
        self,
        db: AsyncSession,
        name: str,
        network: str,
        description: Optional[str] = None,
        vlan_id: Optional[int] = None,
        gateway: Optional[str] = None,
        dns_servers: Optional[str] = None,
        enabled: bool = True,
        auto_scan: bool = True,
        scan_interval: int = 3600
    ) -> IPSubnet:
        """
        Create a new IP subnet and generate all IP addresses
        """
        logger.info(f"Creating subnet: {network}")

        # Validate network
        try:
            net = ipaddress.ip_network(network, strict=False)
        except ValueError as e:
            raise ValueError(f"Invalid network format: {str(e)}")

        # Create subnet
        subnet = IPSubnet(
            name=name,
            network=str(net),
            description=description,
            vlan_id=vlan_id,
            gateway=gateway,
            dns_servers=dns_servers,
            enabled=enabled,
            auto_scan=auto_scan,
            scan_interval=scan_interval
        )

        db.add(subnet)
        await db.flush()  # Get subnet ID

        # Generate IP addresses
        await self._generate_ip_addresses(db, subnet, net)

        await db.commit()
        await db.refresh(subnet)

        logger.info(f"Subnet created: {subnet.id} with {net.num_addresses} IPs")
        return subnet

    async def _generate_ip_addresses(
        self,
        db: AsyncSession,
        subnet: IPSubnet,
        network: ipaddress.IPv4Network
    ):
        """
        Generate all IP addresses for a subnet
        Uses INSERT ... ON CONFLICT DO NOTHING to handle duplicate IPs gracefully
        """
        from sqlalchemy.dialects.postgresql import insert

        ip_addresses = []
        for ip in network.hosts():
            ip_addresses.append({
                'subnet_id': subnet.id,
                'ip_address': str(ip),
                'status': IPStatus.AVAILABLE.value,
                'is_reachable': False,
                'scan_count': 0
            })

        if ip_addresses:
            # Use INSERT ... ON CONFLICT DO NOTHING to handle duplicate IPs
            stmt = insert(IPAddress).values(ip_addresses)
            stmt = stmt.on_conflict_do_nothing(index_elements=['ip_address'])

            result = await db.execute(stmt)
            inserted_count = result.rowcount if result.rowcount else 0

            logger.info(f"Generated {len(ip_addresses)} IP addresses for subnet {subnet.id}, {inserted_count} new IPs inserted (others already exist)")
        else:
            logger.warning(f"No IP addresses to generate for subnet {subnet.id}")


    async def get_subnet(self, db: AsyncSession, subnet_id: int) -> Optional[IPSubnet]:
        """Get subnet by ID"""
        result = await db.execute(
            select(IPSubnet).where(IPSubnet.id == subnet_id)
        )
        return result.scalar_one_or_none()

    async def update_subnet(
        self,
        db: AsyncSession,
        subnet_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        vlan_id: Optional[int] = None,
        gateway: Optional[str] = None,
        dns_servers: Optional[str] = None,
        enabled: Optional[bool] = None,
        auto_scan: Optional[bool] = None,
        scan_interval: Optional[int] = None
    ) -> Optional[IPSubnet]:
        """Update an existing subnet"""
        subnet = await self.get_subnet(db, subnet_id)
        if not subnet:
            return None

        # Update fields if provided
        if name is not None:
            subnet.name = name
        if description is not None:
            subnet.description = description
        if vlan_id is not None:
            subnet.vlan_id = vlan_id
        if gateway is not None:
            subnet.gateway = gateway
        if dns_servers is not None:
            subnet.dns_servers = dns_servers
        if enabled is not None:
            subnet.enabled = enabled
        if auto_scan is not None:
            subnet.auto_scan = auto_scan
        if scan_interval is not None:
            subnet.scan_interval = scan_interval

        await db.commit()
        await db.refresh(subnet)

        logger.info(f"Subnet updated: {subnet.id}")
        return subnet

    async def list_subnets(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100
    ) -> List[IPSubnet]:
        """List all subnets"""
        result = await db.execute(
            select(IPSubnet)
            .order_by(IPSubnet.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def get_subnet_statistics(
        self,
        db: AsyncSession,
        subnet_id: int
    ) -> Dict:
        """Get statistics for a subnet"""
        # Count IPs by status
        result = await db.execute(
            select(
                IPAddress.status,
                func.count(IPAddress.id).label('count')
            )
            .where(IPAddress.subnet_id == subnet_id)
            .group_by(IPAddress.status)
        )

        stats = {status.value: 0 for status in IPStatus}
        for row in result:
            status_key = row.status.value if hasattr(row.status, 'value') else row.status
            stats[status_key] = row.count

        # Count reachable IPs
        result = await db.execute(
            select(func.count(IPAddress.id))
            .where(
                and_(
                    IPAddress.subnet_id == subnet_id,
                    IPAddress.is_reachable == True
                )
            )
        )
        reachable_count = result.scalar()

        total = sum(stats.values())
        utilization = (stats['used'] / total * 100) if total > 0 else 0

        return {
            'total_ips': total,
            'available_ips': stats['available'],
            'used_ips': stats['used'],
            'reserved_ips': stats['reserved'],
            'offline_ips': stats['offline'],
            'reachable_count': reachable_count,
            'utilization_percent': round(utilization, 2)
        }

    async def list_ip_addresses(
        self,
        db: AsyncSession,
        subnet_id: Optional[int] = None,
        status: Optional[IPStatus] = None,
        is_reachable: Optional[bool] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[IPAddress]:
        """List IP addresses with filters"""
        query = select(IPAddress)

        # Apply filters
        conditions = []
        if subnet_id:
            conditions.append(IPAddress.subnet_id == subnet_id)
        if status:
            conditions.append(IPAddress.status == status)
        if is_reachable is not None:
            conditions.append(IPAddress.is_reachable == is_reachable)
        if search:
            conditions.append(
                or_(
                    cast(IPAddress.ip_address, String).contains(search),
                    IPAddress.hostname.ilike(f'%{search}%'),
                    IPAddress.dns_name.ilike(f'%{search}%'),
                    IPAddress.system_name.ilike(f'%{search}%'),
                    IPAddress.machine_type.ilike(f'%{search}%'),
                    IPAddress.vendor.ilike(f'%{search}%'),
                    cast(IPAddress.mac_address, String).ilike(f'%{search}%'),
                    IPAddress.description.ilike(f'%{search}%')
                )
            )

        if conditions:
            query = query.where(and_(*conditions))

        query = query.order_by(*self._ip_address_order_by()).offset(skip).limit(limit)

        result = await db.execute(query)
        return result.scalars().all()

    async def get_ip_address(
        self,
        db: AsyncSession,
        ip_id: int
    ) -> Optional[IPAddress]:
        """Get IP address by ID"""
        result = await db.execute(
            select(IPAddress).where(IPAddress.id == ip_id)
        )
        return result.scalar_one_or_none()

    async def update_ip_address(
        self,
        db: AsyncSession,
        ip_id: int,
        status: Optional[IPStatus] = None,
        hostname: Optional[str] = None,
        mac_address: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[IPAddress]:
        """Update IP address"""
        ip_addr = await self.get_ip_address(db, ip_id)
        if not ip_addr:
            return None

        if status is not None:
            ip_addr.status = status
        if hostname is not None:
            ip_addr.hostname = hostname
        if mac_address is not None:
            ip_addr.mac_address = mac_address
        if description is not None:
            ip_addr.description = description

        await db.commit()
        await db.refresh(ip_addr)
        return ip_addr

    @staticmethod
    def _snapshot_ip_state(ip_addr: IPAddress) -> Dict[str, Any]:
        return {
            'is_reachable': ip_addr.is_reachable,
            'hostname': ip_addr.hostname,
            'os_name': ip_addr.os_name,
            'mac_address': str(ip_addr.mac_address) if ip_addr.mac_address else None,
            'switch_id': ip_addr.switch_id,
            'switch_port': ip_addr.switch_port,
            'last_seen_at': ip_addr.last_seen_at,
        }

    @staticmethod
    def _merge_scan_results(base_result: Dict[str, Any], override_result: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base_result)
        for key, value in override_result.items():
            if key in {'ip_address', 'is_reachable'}:
                merged[key] = value
            elif value is not None:
                merged[key] = value

        if merged.get('response_time') is None:
            merged['response_time'] = base_result.get('response_time')

        return merged

    async def scan_subnet(
        self,
        db: AsyncSession,
        subnet_id: int,
        scan_type: str = "full",
        include_results: bool = True,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None] | None]] = None,
        subnet_index: int = 1,
        total_subnets: int = 1
    ) -> Dict:
        """
        Scan all IPs in a subnet using a fast reachability pass followed by
        optional enrichment for the hosts that replied.
        """
        logger.info(f"Starting subnet scan: {subnet_id} (type: {scan_type})")
        start_time = datetime.now(timezone.utc)

        try:
            async def emit_progress(event_type: str, payload: Dict[str, Any]) -> None:
                if not progress_callback:
                    return
                maybe_awaitable = progress_callback(event_type, payload)
                if asyncio.iscoroutine(maybe_awaitable):
                    await maybe_awaitable

            # Get subnet
            subnet = await self.get_subnet(db, subnet_id)
            if not subnet:
                raise ValueError(f"Subnet {subnet_id} not found")

            # Get SNMP profile if configured for this subnet
            snmp_profile = None
            if subnet.snmp_profile_id:
                from models.ipam import SNMPProfile
                result = await db.execute(
                    select(SNMPProfile).where(SNMPProfile.id == subnet.snmp_profile_id)
                )
                profile = result.scalar_one_or_none()
                if profile and profile.enabled:
                    # Prepare SNMP profile dictionary for scanning
                    snmp_profile = {
                        'username': profile.username,
                        'auth_protocol': profile.auth_protocol,
                        'auth_password_encrypted': profile.auth_password_encrypted,
                        'priv_protocol': profile.priv_protocol,
                        'priv_password_encrypted': profile.priv_password_encrypted,
                        'port': profile.port,
                        'timeout': profile.timeout
                    }
                    logger.info(f"Using SNMP profile '{profile.name}' for subnet {subnet_id}")

            # Get all IP addresses
            result = await db.execute(
                select(IPAddress).where(IPAddress.subnet_id == subnet_id)
            )
            ip_addresses = result.scalars().all()
            ip_records_by_str = {
                str(ip.ip_address): ip
                for ip in ip_addresses
            }
            previous_state = {
                ip_addr.id: self._snapshot_ip_state(ip_addr)
                for ip_addr in ip_addresses
            }

            # Parse DNS servers from subnet configuration
            dns_servers = None
            if subnet.dns_servers:
                # dns_servers is stored as comma-separated string
                dns_servers = [s.strip() for s in subnet.dns_servers.split(',') if s.strip()]
                logger.info(f"Using DNS servers for subnet {subnet_id}: {dns_servers}")

            # Close the read transaction before the long-running network scan begins.
            await db.commit()

            ip_list = [str(ip.ip_address) for ip in ip_addresses]
            await emit_progress(
                'subnet_start',
                {
                    'subnet_id': subnet_id,
                    'subnet_name': subnet.name,
                    'subnet_network': str(subnet.network),
                    'total_ips': len(ip_list),
                    'subnet_index': subnet_index,
                    'total_subnets': total_subnets,
                }
            )

            quick_reachable = 0

            async def on_quick_progress(scan_result: Dict[str, Any], completed: int, total: int) -> None:
                nonlocal quick_reachable
                if scan_result.get('is_reachable'):
                    quick_reachable += 1

                await emit_progress(
                    'quick_progress',
                    {
                        'subnet_id': subnet_id,
                        'completed_ips': completed,
                        'total_ips': total,
                        'reachable_ips': quick_reachable,
                    }
                )

            quick_results = await ip_scan_service.scan_multiple_ips(
                ip_list,
                "quick",
                None,
                None,
                progress_callback=on_quick_progress
            )
            quick_results_by_ip = {
                scan_result['ip_address']: scan_result
                for scan_result in quick_results
            }
            final_results_by_ip = {
                ip: dict(scan_result)
                for ip, scan_result in quick_results_by_ip.items()
            }
            quick_finished_at = datetime.now(timezone.utc)

            for ip_str, scan_result in quick_results_by_ip.items():
                ip_addr = ip_records_by_str.get(ip_str)
                if not ip_addr:
                    continue

                ip_addr.is_reachable = scan_result['is_reachable']
                ip_addr.response_time = scan_result['response_time']
                ip_addr.last_scan_at = quick_finished_at
                ip_addr.scan_count += 1

                if scan_result['is_reachable']:
                    ip_addr.last_seen_at = quick_finished_at
                    if ip_addr.status in [IPStatus.AVAILABLE.value, IPStatus.OFFLINE.value]:
                        ip_addr.status = IPStatus.USED.value
                else:
                    if ip_addr.last_seen_at:
                        time_since_last_seen = quick_finished_at - ip_addr.last_seen_at
                        offline_threshold_hours = settings.IPAM_OFFLINE_THRESHOLD_HOURS

                        if time_since_last_seen.total_seconds() > offline_threshold_hours * 3600:
                            if ip_addr.status == IPStatus.USED.value:
                                ip_addr.status = IPStatus.OFFLINE.value
                                logger.info(
                                    f"Marking {ip_str} as OFFLINE "
                                    f"(not seen for {time_since_last_seen.total_seconds()/3600:.1f} hours)"
                                )

            subnet.last_scan_at = quick_finished_at
            await db.commit()

            reachable_ip_list = [
                scan_result['ip_address']
                for scan_result in quick_results
                if scan_result.get('is_reachable')
            ]

            await emit_progress(
                'quick_complete',
                {
                    'subnet_id': subnet_id,
                    'subnet_last_scan_at': quick_finished_at.isoformat(),
                    'total_ips_scanned': len(quick_results),
                    'reachable_ips': len(reachable_ip_list),
                    'unreachable_ips': len(quick_results) - len(reachable_ip_list),
                }
            )

            if scan_type != "quick" and reachable_ip_list:
                async def on_enrichment_progress(scan_result: Dict[str, Any], completed: int, total: int) -> None:
                    await emit_progress(
                        'enrichment_progress',
                        {
                            'subnet_id': subnet_id,
                            'completed_hosts': completed,
                            'total_hosts': total,
                            'reachable_ips': len(reachable_ip_list),
                            'subnet_last_scan_at': quick_finished_at.isoformat(),
                        }
                    )

                enrichment_results = await ip_scan_service.enrich_multiple_ips(
                    reachable_ip_list,
                    snmp_profile,
                    dns_servers,
                    progress_callback=on_enrichment_progress
                )

                for enrichment_result in enrichment_results:
                    ip_str = enrichment_result['ip_address']
                    base_result = final_results_by_ip.get(ip_str)
                    if base_result:
                        final_results_by_ip[ip_str] = self._merge_scan_results(base_result, enrichment_result)
                    else:
                        final_results_by_ip[ip_str] = enrichment_result

            new_devices = 0
            changed_devices = 0
            ordered_scan_results = []

            for ip_str in ip_list:
                scan_result = final_results_by_ip.get(ip_str)
                if not scan_result:
                    continue

                # Find IP address record
                ip_addr = ip_records_by_str.get(ip_str)
                if not ip_addr:
                    continue
                ordered_scan_results.append(scan_result)
                old_state = previous_state[ip_addr.id]

                # Detect reachability changes against the pre-scan snapshot.
                status_changed = old_state['is_reachable'] != scan_result['is_reachable']

                if scan_result['is_reachable'] and not old_state['last_seen_at']:
                    new_devices += 1

                # Try to find MAC address
                # First, try with MAC from scan result
                mac_to_lookup = scan_result['mac_address']

                # If scan didn't get MAC and IP is reachable, try to find it from ARP/MAC tables
                if not mac_to_lookup and scan_result['is_reachable']:
                    from models.arp_table import ARPTable
                    from models.mac_table import MACTable

                    # Try ARP table first
                    arp_result = await db.execute(
                        select(ARPTable)
                        .where(func.host(ARPTable.ip_address) == ip_str)
                        .order_by(ARPTable.last_seen.desc())
                        .limit(1)
                    )
                    arp_entry = arp_result.scalar_one_or_none()
                    if arp_entry:
                        mac_to_lookup = str(arp_entry.mac_address)
                        logger.info(f"Found MAC for {ip_str} from ARP table: {mac_to_lookup}")

                # Update hostname with source tracking (SolarWinds-style)
                if scan_result.get('hostname') is not None:
                    ip_addr.hostname = scan_result.get('hostname')
                if scan_result.get('hostname_source') is not None:
                    ip_addr.hostname_source = scan_result.get('hostname_source')  # SNMP, DNS, ARP, or None

                # Update SolarWinds-style SNMP/DNS fields
                if scan_result.get('dns_name') is not None:
                    ip_addr.dns_name = scan_result.get('dns_name')  # DNS PTR result
                if scan_result.get('system_name') is not None:
                    ip_addr.system_name = scan_result.get('system_name')  # SNMP sysName
                if scan_result.get('contact') is not None:
                    ip_addr.contact = scan_result.get('contact')  # SNMP sysContact
                if scan_result.get('location') is not None:
                    ip_addr.location = scan_result.get('location')  # SNMP sysLocation
                if scan_result.get('machine_type') is not None:
                    ip_addr.machine_type = scan_result.get('machine_type')  # SNMP sysDescr parsed
                if scan_result.get('vendor') is not None:
                    ip_addr.vendor = scan_result.get('vendor')  # SNMP vendor parsed

                # Update last_boot_time from SNMP sysUpTime
                if scan_result.get('last_boot_time'):
                    # Parse ISO format datetime string
                    try:
                        ip_addr.last_boot_time = datetime.fromisoformat(scan_result['last_boot_time'])
                    except:
                        pass

                # Only update MAC if we have one (don't overwrite with None)
                if mac_to_lookup:
                    ip_addr.mac_address = mac_to_lookup

                # If we still don't have MAC but IP already has one in DB, use existing MAC
                elif ip_addr.mac_address and scan_result['is_reachable']:
                    mac_to_lookup = str(ip_addr.mac_address)
                    logger.info(f"Using existing MAC for {ip_str}: {mac_to_lookup}")

                if scan_result.get('os_type') is not None:
                    ip_addr.os_type = scan_result['os_type']
                if scan_result.get('os_name') is not None:
                    ip_addr.os_name = scan_result['os_name']
                if scan_result.get('os_version') is not None:
                    ip_addr.os_version = scan_result['os_version']
                if scan_result.get('os_vendor') is not None:
                    ip_addr.os_vendor = scan_result['os_vendor']

                # Try to get hostname from switches table if we don't have one
                if not ip_addr.hostname:
                    # Query switches table by IP address (use host() to strip netmask)
                    from sqlalchemy.sql import text as sql_text
                    switch_result = await db.execute(
                        select(Switch.name)
                        .where(sql_text("host(switches.ip_address) = :ip"))
                        .params(ip=ip_str)
                    )
                    switch_name = switch_result.scalar_one_or_none()

                    if switch_name:
                        ip_addr.hostname = switch_name
                        ip_addr.hostname_source = 'SWITCH'
                        logger.info(f"Hostname from switches table for {ip_str}: {switch_name}")

                # Update switch info if we have MAC address
                if mac_to_lookup:
                    await self._update_switch_info(db, ip_addr, mac_to_lookup)

                # Detect network location changes
                new_mac = str(ip_addr.mac_address) if ip_addr.mac_address else None
                hostname_changed = old_state['hostname'] != ip_addr.hostname
                os_changed = old_state['os_name'] != ip_addr.os_name
                mac_changed = old_state['mac_address'] != new_mac
                switch_changed = old_state['switch_id'] != ip_addr.switch_id
                port_changed = old_state['switch_port'] != ip_addr.switch_port
                if status_changed or hostname_changed or os_changed or mac_changed or switch_changed or port_changed:
                    changed_devices += 1

                # Create history record with network location tracking
                history = IPScanHistory(
                    ip_address_id=ip_addr.id,
                    is_reachable=scan_result['is_reachable'],
                    response_time=scan_result['response_time'],
                    hostname=ip_addr.hostname,
                    mac_address=new_mac,
                    os_type=ip_addr.os_type,
                    os_name=ip_addr.os_name,
                    switch_id=ip_addr.switch_id,
                    switch_port=ip_addr.switch_port,
                    vlan_id=ip_addr.vlan_id,
                    status_changed=status_changed,
                    hostname_changed=hostname_changed,
                    os_changed=os_changed,
                    mac_changed=mac_changed,
                    switch_changed=switch_changed,
                    port_changed=port_changed
                )
                db.add(history)

            await db.commit()

            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            reachable = sum(1 for r in ordered_scan_results if r['is_reachable'])

            summary = {
                'subnet_id': subnet_id,
                'subnet_last_scan_at': quick_finished_at,
                'total_scanned': len(ordered_scan_results),
                'reachable': reachable,
                'unreachable': len(ordered_scan_results) - reachable,
                'new_devices': new_devices,
                'changed_devices': changed_devices,
                'scan_duration': elapsed
            }

            if include_results:
                summary['results'] = ordered_scan_results

            logger.info(
                "Subnet scan completed: "
                f"subnet_id={subnet_id}, total={summary['total_scanned']}, "
                f"reachable={summary['reachable']}, "
                f"unreachable={summary['unreachable']}, "
                f"new={summary['new_devices']}, "
                f"changed={summary['changed_devices']}, "
                f"duration={summary['scan_duration']:.2f}s"
            )
            await emit_progress(
                'subnet_complete',
                {
                    'summary': summary,
                }
            )
            return summary

        except Exception as e:
            # Rollback transaction on any error
            await db.rollback()
            logger.error(f"Error during subnet scan {subnet_id}: {str(e)}")
            logger.exception(e)
            raise
        finally:
            # Release ORM state between subnets so a full auto-scan pass does not
            # keep tens of thousands of IP/history objects attached to one session.
            db.expunge_all()
            self._release_scan_memory(f"subnet scan {subnet_id}")

    async def _update_switch_info(
        self,
        db: AsyncSession,
        ip_addr: IPAddress,
        mac_address: str
    ):
        """
        Update switch and port information for an IP address by querying database tables
        Only matches access ports (ports with 1-3 MAC addresses), not trunk ports
        """
        try:
            result = await db.execute(
                select(MACTable, Switch, PortAnalysis)
                .join(Switch, MACTable.switch_id == Switch.id)
                .outerjoin(
                    PortAnalysis,
                    and_(
                        PortAnalysis.switch_id == MACTable.switch_id,
                        PortAnalysis.port_name == MACTable.port_name
                    )
                )
                .where(
                    cast(MACTable.mac_address, Text) == cast(mac_address.lower(), Text)
                )
                .where(build_lookup_eligible_clause(PortAnalysis))
                .order_by(MACTable.last_seen.desc())
                .limit(1)
            )
            row = result.first()

            if row:
                mac_entry, switch, port_analysis = row
                mac_count = port_analysis.mac_count if port_analysis else None
                ip_addr.switch_id = switch.id
                ip_addr.switch_port = mac_entry.port_name
                ip_addr.vlan_id = mac_entry.vlan_id
                logger.info(
                    f"Found switch info for {ip_addr.ip_address} (MAC: {mac_address}): "
                    f"{switch.name} port {mac_entry.port_name} VLAN {mac_entry.vlan_id} "
                    f"(lookup-eligible port, mac_count={mac_count if mac_count is not None else 'n/a'})"
                )
                return

            # If not found in lookup-eligible MAC data, try ARP to identify the
            # switch first, then check raw MAC data on that same switch. This
            # helps platforms whose ARP interface values are placeholders such as
            # Dyn[I]/Oth[I] while the MAC table still has the physical port.

            result = await db.execute(
                select(ARPTable, Switch)
                .join(Switch, ARPTable.switch_id == Switch.id)
                .where(
                    cast(ARPTable.mac_address, Text) == cast(mac_address.lower(), Text)
                )
                .order_by(ARPTable.last_seen.desc())
                .limit(1)
            )
            row = result.first()

            if row:
                arp_entry, switch = row
                ip_addr.switch_id = switch.id

                same_switch_mac_result = await db.execute(
                    select(MACTable)
                    .where(
                        and_(
                            MACTable.switch_id == switch.id,
                            cast(MACTable.mac_address, Text) == cast(mac_address.lower(), Text)
                        )
                    )
                    .order_by(MACTable.last_seen.desc())
                    .limit(1)
                )
                same_switch_mac_entry = same_switch_mac_result.scalar_one_or_none()

                if same_switch_mac_entry:
                    ip_addr.switch_port = same_switch_mac_entry.port_name
                    ip_addr.vlan_id = same_switch_mac_entry.vlan_id or arp_entry.vlan_id
                    logger.info(
                        f"Found same-switch MAC port for {ip_addr.ip_address} (MAC: {mac_address}): "
                        f"{switch.name} port {same_switch_mac_entry.port_name}"
                    )
                    return

                # ARP interface is only a last resort and may be unusable on some models.
                if self._is_usable_arp_interface(arp_entry.interface):
                    ip_addr.switch_port = arp_entry.interface
                else:
                    ip_addr.switch_port = None
                ip_addr.vlan_id = arp_entry.vlan_id
                logger.info(
                    f"Found switch info from ARP for {ip_addr.ip_address} (MAC: {mac_address}): "
                    f"{switch.name}"
                )

        except Exception as e:
            logger.error(f"Error updating switch info for {ip_addr.ip_address}: {str(e)}")

    async def get_dashboard_stats(self, db: AsyncSession) -> Dict:
        """Get IPAM dashboard statistics"""
        # Total subnets
        result = await db.execute(select(func.count(IPSubnet.id)))
        total_subnets = result.scalar()

        # Total IPs by status
        result = await db.execute(
            select(
                IPAddress.status,
                func.count(IPAddress.id).label('count')
            )
            .group_by(IPAddress.status)
        )

        stats = {status.value: 0 for status in IPStatus}
        for row in result:
            # row.status is IPStatus enum, use .value to get string
            status_key = row.status.value if hasattr(row.status, 'value') else row.status
            stats[status_key] = row.count

        total_ips = sum(stats.values())
        utilization = (stats.get('used', 0) / total_ips * 100) if total_ips > 0 else 0

        # Get subnet statistics (all subnets for proper display)
        subnets = await self.list_subnets(db, limit=1000)
        subnet_stats = []
        for subnet in subnets:
            subnet_stat = await self.get_subnet_statistics(db, subnet.id)
            subnet_stats.append({
                'subnet_id': subnet.id,
                'subnet_name': subnet.name,
                'network': str(subnet.network),
                'description': subnet.description,
                'vlan_id': subnet.vlan_id,
                'gateway': str(subnet.gateway) if subnet.gateway else None,
                'dns_servers': subnet.dns_servers,
                'enabled': subnet.enabled,
                'auto_scan': subnet.auto_scan,
                'scan_interval': subnet.scan_interval,
                **subnet_stat,
                'last_scan_at': subnet.last_scan_at
            })

        # Recent changes (last 24 hours)
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        result = await db.execute(
            select(IPScanHistory)
            .where(
                and_(
                    IPScanHistory.scanned_at >= yesterday,
                    or_(
                        IPScanHistory.status_changed == True,
                        IPScanHistory.hostname_changed == True,
                        IPScanHistory.os_changed == True
                    )
                )
            )
            .order_by(IPScanHistory.scanned_at.desc())
            .limit(20)
        )
        recent_changes = result.scalars().all()

        return {
            'total_subnets': total_subnets,
            'total_ips': total_ips,
            'used_ips': stats.get('used', 0),
            'available_ips': stats.get('available', 0),
            'offline_ips': stats.get('offline', 0),
            'overall_utilization': round(utilization, 2),
            'subnets': subnet_stats,
            'recent_changes': recent_changes
        }

    async def batch_create_subnets(
        self,
        db: AsyncSession,
        subnets_data: List[Dict],
        skip_existing: bool = True
    ) -> Dict:
        """
        Batch create multiple subnets

        Args:
            db: Database session
            subnets_data: List of subnet data dictionaries
            skip_existing: Skip subnets with duplicate network addresses

        Returns:
            Dict with import results
        """
        logger.info(f"Starting batch import of {len(subnets_data)} subnets")

        total = len(subnets_data)
        success = 0
        failed = 0
        skipped = 0
        errors = []
        imported_ids = []

        # Get existing networks if skip_existing is True
        existing_networks = set()
        if skip_existing:
            result = await db.execute(select(IPSubnet.network))
            existing_networks = {str(row[0]) for row in result.fetchall()}

        for idx, subnet_data in enumerate(subnets_data):
            try:
                network_str = subnet_data.get('network')

                # Validate network format
                try:
                    net = ipaddress.ip_network(network_str, strict=False)
                    normalized_network = str(net)
                except ValueError as e:
                    raise ValueError(f"Invalid network format: {str(e)}")

                # Check for duplicates
                if skip_existing and normalized_network in existing_networks:
                    logger.info(f"Skipping duplicate network: {normalized_network}")
                    skipped += 1
                    continue

                # Check for IP address conflicts (overlapping subnets)
                # Check if any IP in this new subnet already exists
                try:
                    first_ip = str(list(net.hosts())[0] if net.num_addresses > 2 else net.network_address)
                    # Use text cast to compare INET with string
                    ip_check = await db.execute(
                        select(IPAddress).where(func.host(IPAddress.ip_address) == first_ip)
                    )
                    if ip_check.scalar_one_or_none():
                        logger.warning(f"Skipping subnet {normalized_network}: IP addresses already exist (overlapping subnet)")
                        skipped += 1
                        errors.append({
                            'index': idx,
                            'network': network_str,
                            'name': subnet_data.get('name'),
                            'error': 'IP地址冲突：该网段的IP地址已存在（可能与其他子网重叠）'
                        })
                        continue
                except (IndexError, AttributeError):
                    # Handle edge case where network has no hosts
                    pass

                # Use a savepoint for each subnet
                async with db.begin_nested():
                    # Create subnet
                    subnet = IPSubnet(
                        name=subnet_data.get('name'),
                        network=normalized_network,
                        description=subnet_data.get('description'),
                        vlan_id=subnet_data.get('vlan_id'),
                        gateway=subnet_data.get('gateway'),
                        dns_servers=subnet_data.get('dns_servers'),
                        enabled=subnet_data.get('enabled', True),
                        auto_scan=subnet_data.get('auto_scan', True),
                        scan_interval=subnet_data.get('scan_interval', 3600)
                    )

                    db.add(subnet)
                    await db.flush()  # Get subnet ID

                    # Generate IP addresses
                    await self._generate_ip_addresses(db, subnet, net)

                imported_ids.append(subnet.id)
                existing_networks.add(normalized_network)
                success += 1

                logger.info(f"Successfully imported subnet {idx + 1}/{total}: {subnet.name} ({normalized_network})")

            except Exception as e:
                failed += 1
                error_detail = {
                    'index': idx,
                    'network': subnet_data.get('network'),
                    'name': subnet_data.get('name'),
                    'error': str(e)
                }
                errors.append(error_detail)
                logger.error(f"Failed to import subnet {idx + 1}/{total}: {str(e)}")
                # Continue to next subnet

        # Commit all changes
        try:
            await db.commit()
            logger.info(f"Batch import completed: {success} success, {failed} failed, {skipped} skipped")
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to commit batch import: {str(e)}")
            raise ValueError(f"Database commit failed: {str(e)}")

        return {
            'total': total,
            'success': success,
            'failed': failed,
            'skipped': skipped,
            'errors': errors,
            'imported_ids': imported_ids
        }

    async def scan_all_auto_subnets(
        self,
        db: AsyncSession,
        scan_type: str = "quick",
        progress_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None] | None]] = None,
        max_subnets: Optional[int] = None,
    ) -> Dict:
        """
        Scan all subnets that have auto_scan enabled and are due for scanning.

        Returns:
            Dictionary with scan statistics
        """
        logger.info(f"Starting automatic subnet scan (type: {scan_type})")
        start_time = datetime.now(timezone.utc)

        # Keep the scheduling session lightweight by only loading the metadata
        # needed to decide which subnets are due. Each due subnet is then
        # scanned with a fresh short-lived session.
        result = await db.execute(
            select(
                IPSubnet.id,
                IPSubnet.name,
                IPSubnet.network,
                IPSubnet.last_scan_at,
                IPSubnet.scan_interval,
            ).where(
                and_(
                    IPSubnet.enabled == True,
                    IPSubnet.auto_scan == True
                )
            )
        )
        subnets = result.all()
        # End the read transaction before the hours-long scan pass starts.
        await db.commit()

        if not subnets:
            logger.info("No subnets with auto_scan enabled")
            return {
                'total_subnets': 0,
                'scanned_subnets': 0,
                'total_ips_scanned': 0,
                'duration': 0
            }

        logger.info(f"Found {len(subnets)} subnets with auto_scan enabled")

        scanned_count = 0
        total_ips = 0
        failed_subnets = []
        due_subnets = []
        now = datetime.now(timezone.utc)

        for subnet_id, subnet_name, subnet_network, last_scan_at, scan_interval in subnets:
            # Check if subnet needs scanning based on scan_interval
            if last_scan_at:
                time_since_scan = (now - last_scan_at).total_seconds()
                if time_since_scan < scan_interval:
                    logger.debug(
                        f"Skipping {subnet_name} - last scanned {time_since_scan:.0f}s ago "
                        f"(interval: {scan_interval}s)"
                    )
                    continue
            due_subnets.append((subnet_id, subnet_name, subnet_network))

        total_due_subnets = len(due_subnets)
        selected_due_subnets = due_subnets
        deferred_subnets = 0

        if max_subnets is not None and max_subnets >= 0:
            selected_due_subnets = due_subnets[:max_subnets]
            deferred_subnets = max(total_due_subnets - len(selected_due_subnets), 0)

        logger.info(
            f"{total_due_subnets} auto-scan subnets are due for scanning"
            + (
                f"; limiting this pass to {len(selected_due_subnets)} subnets and deferring {deferred_subnets}"
                if deferred_subnets
                else ""
            )
        )

        for index, (subnet_id, subnet_name, subnet_network) in enumerate(selected_due_subnets, start=1):
            subnet_db = None

            try:
                logger.info(f"Scanning subnet: {subnet_name} ({subnet_network})")
                subnet_db = AsyncSessionLocal()
                scan_result = await self.scan_subnet(
                    subnet_db,
                    subnet_id,
                    scan_type=scan_type,
                    include_results=False,
                    progress_callback=progress_callback,
                    subnet_index=index,
                    total_subnets=len(selected_due_subnets)
                )
                scanned_count += 1
                total_ips += scan_result.get('total_scanned', 0)
                logger.info(
                    f"Completed scan for {subnet_name}: "
                    f"{scan_result.get('reachable', 0)}/{scan_result.get('total_scanned', 0)} reachable"
                )
            except Exception as e:
                logger.error(f"Failed to scan subnet {subnet_name}: {str(e)}")
                failed_subnets.append({
                    'subnet_id': subnet_id,
                    'subnet_name': subnet_name,
                    'error': str(e)
                })
            finally:
                if subnet_db is not None:
                    await subnet_db.close()
                self._release_scan_memory(f"auto-scan subnet {subnet_id}")

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        summary = {
            'total_subnets': len(selected_due_subnets),
            'total_due_subnets': total_due_subnets,
            'deferred_subnets': deferred_subnets,
            'scanned_subnets': scanned_count,
            'failed_subnets': len(failed_subnets),
            'total_ips_scanned': total_ips,
            'duration': elapsed,
            'failures': failed_subnets
        }

        logger.info(
            f"Automatic subnet scan completed: "
            f"{scanned_count}/{len(selected_due_subnets)} subnets scanned, "
            f"{total_ips} IPs total, "
            f"deferred_subnets={deferred_subnets}, "
            f"duration: {elapsed:.1f}s"
        )

        self._release_scan_memory("automatic subnet scan pass")

        return summary

    async def cleanup_old_scan_history(
        self,
        db: AsyncSession,
        days_to_keep: int = settings.IP_SCAN_HISTORY_RETENTION_DAYS,
        batch_size: int = settings.IP_SCAN_HISTORY_CLEANUP_BATCH_SIZE
    ) -> int:
        """Delete stale IP scan history in batches to keep memory and lock time bounded."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        total_deleted = 0

        while True:
            stale_ids = (
                select(IPScanHistory.id)
                .where(IPScanHistory.scanned_at < cutoff)
                .order_by(IPScanHistory.id.asc())
                .limit(batch_size)
            )

            result = await db.execute(
                delete(IPScanHistory)
                .where(IPScanHistory.id.in_(stale_ids))
                .execution_options(synchronize_session=False)
            )
            batch_deleted = result.rowcount or 0

            if batch_deleted == 0:
                break

            total_deleted += batch_deleted
            await db.commit()

        if total_deleted:
            logger.info(
                f"Cleaned up {total_deleted} IP scan history rows older than {days_to_keep} days"
            )

        return total_deleted

    async def search_network(
        self,
        db: AsyncSession,
        network_cidr: str
    ) -> Dict:
        """
        Search for all IPs in a given network (CIDR notation)

        Returns network information and all IPs within the network.
        If the network exists in IPAM, returns managed IP data.
        """
        logger.info(f"Searching network: {network_cidr}")

        # Validate and parse network
        try:
            net = ipaddress.ip_network(network_cidr, strict=False)
        except ValueError as e:
            raise ValueError(f"Invalid network format: {str(e)}")

        # Check if network exists in IPAM
        result = await db.execute(
            select(IPSubnet).where(
                cast(IPSubnet.network, String) == str(net)
            )
        )
        subnet = result.scalar_one_or_none()

        # Get all IPs in the network
        ips_data = []

        if subnet:
            # Network is managed in IPAM - get IP data from database
            result = await db.execute(
                select(IPAddress, Switch.name).outerjoin(
                    Switch, IPAddress.switch_id == Switch.id
                ).where(
                    IPAddress.subnet_id == subnet.id
                ).order_by(IPAddress.ip_address)
            )

            for ip_addr, switch_name in result.all():
                ips_data.append({
                    'ip_address': str(ip_addr.ip_address),
                    'status': ip_addr.status,
                    'is_reachable': ip_addr.is_reachable,
                    'hostname': ip_addr.hostname,
                    'mac_address': ip_addr.mac_address,
                    'switch_name': switch_name,
                    'switch_port': ip_addr.switch_port,
                    'description': ip_addr.description,
                    'last_seen_at': ip_addr.last_seen_at
                })
        else:
            # Network not in IPAM - generate list of all IPs
            for ip in net.hosts():
                ips_data.append({
                    'ip_address': str(ip),
                    'status': IPStatus.AVAILABLE,
                    'is_reachable': None,
                    'hostname': None,
                    'mac_address': None,
                    'switch_name': None,
                    'switch_port': None,
                    'description': None,
                    'last_seen_at': None
                })

        # Calculate network info
        network_address = str(net.network_address)
        broadcast_address = str(net.broadcast_address)
        netmask = str(net.netmask)
        hosts = list(net.hosts())
        first_usable = str(hosts[0]) if hosts else network_address
        last_usable = str(hosts[-1]) if hosts else network_address

        return {
            'network': str(net),
            'network_address': network_address,
            'broadcast_address': broadcast_address,
            'netmask': netmask,
            'total_ips': net.num_addresses,
            'usable_ips': len(hosts),
            'first_usable': first_usable,
            'last_usable': last_usable,
            'ips': ips_data,
            'in_ipam': subnet is not None,
            'subnet_id': subnet.id if subnet else None,
            'subnet_name': subnet.name if subnet else None
        }


# Subnet Calculator function (standalone, no DB needed)
def calculate_subnet_info(ip_address: str, netmask: Optional[str] = None) -> Dict:
    """
    Calculate subnet information from IP address and netmask

    Args:
        ip_address: IP address (e.g., "10.101.63.25")
        netmask: Subnet mask (e.g., "255.255.255.0") or CIDR prefix (e.g., "24" or "/24")

    Returns:
        Dictionary with subnet calculation results
    """
    logger.info(f"Calculating subnet info for {ip_address}/{netmask}")

    # Parse IP address
    try:
        ip = ipaddress.ip_address(ip_address)
    except ValueError as e:
        raise ValueError(f"Invalid IP address: {str(e)}")

    # Determine prefix length
    if netmask is None:
        # If no netmask provided, assume /32 for IPv4 or /128 for IPv6
        prefix_len = 32 if isinstance(ip, ipaddress.IPv4Address) else 128
    elif netmask.startswith('/'):
        # CIDR notation like "/24"
        prefix_len = int(netmask[1:])
    elif '.' in netmask:
        # Dotted decimal notation like "255.255.255.0"
        # Convert to CIDR
        try:
            netmask_obj = ipaddress.IPv4Network(f"0.0.0.0/{netmask}", strict=False)
            prefix_len = netmask_obj.prefixlen
        except ValueError:
            raise ValueError(f"Invalid netmask format: {netmask}")
    else:
        # Plain number like "24"
        prefix_len = int(netmask)

    # Create network object
    try:
        net = ipaddress.ip_network(f"{ip_address}/{prefix_len}", strict=False)
    except ValueError as e:
        raise ValueError(f"Invalid network: {str(e)}")

    # Calculate network information
    hosts = list(net.hosts())
    first_usable = str(hosts[0]) if hosts else str(net.network_address)
    last_usable = str(hosts[-1]) if hosts else str(net.network_address)

    # Determine IP class (IPv4 only)
    ip_class = "N/A"
    is_private = ip.is_private

    if isinstance(ip, ipaddress.IPv4Address):
        first_octet = int(str(ip).split('.')[0])
        if 1 <= first_octet <= 126:
            ip_class = "A"
        elif 128 <= first_octet <= 191:
            ip_class = "B"
        elif 192 <= first_octet <= 223:
            ip_class = "C"
        elif 224 <= first_octet <= 239:
            ip_class = "D (Multicast)"
        elif 240 <= first_octet <= 255:
            ip_class = "E (Reserved)"

    # Binary representations
    if isinstance(ip, ipaddress.IPv4Address):
        binary_ip = '.'.join([bin(int(octet))[2:].zfill(8) for octet in str(ip).split('.')])
        binary_netmask = '.'.join([bin(int(octet))[2:].zfill(8) for octet in str(net.netmask).split('.')])
        hex_ip = '0x' + ''.join([hex(int(octet))[2:].zfill(2) for octet in str(ip).split('.')])

        # Wildcard mask (inverse of netmask)
        wildcard_octets = [str(255 - int(octet)) for octet in str(net.netmask).split('.')]
        wildcard_mask = '.'.join(wildcard_octets)
    else:
        binary_ip = bin(int(ip))[2:].zfill(128)
        binary_netmask = '1' * prefix_len + '0' * (128 - prefix_len)
        hex_ip = hex(int(ip))
        wildcard_mask = "N/A (IPv6)"

    return {
        'ip_address': str(ip),
        'cidr': f"{net.network_address}/{net.prefixlen}",
        'network_address': str(net.network_address),
        'broadcast_address': str(net.broadcast_address),
        'netmask': str(net.netmask),
        'wildcard_mask': wildcard_mask,
        'first_usable_ip': first_usable,
        'last_usable_ip': last_usable,
        'total_hosts': net.num_addresses,
        'usable_hosts': len(hosts),
        'ip_class': ip_class,
        'is_private': is_private,
        'binary_netmask': binary_netmask,
        'binary_ip': binary_ip,
        'hex_ip': hex_ip
    }


# Singleton instance
ipam_service = IPAMService()
