from typing import Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, cast, Text, String
from models.ipam import IPSubnet, IPAddress, IPScanHistory, IPStatus
from models.switch import Switch
from services.ip_scan import ip_scan_service
from services.ip_lookup import ip_lookup_service
from core.config import settings
from utils.logger import logger
import ipaddress
from datetime import datetime, timedelta, timezone
import asyncio


class IPAMService:
    """Service for IP Address Management"""

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
                    IPAddress.ip_address.cast(str).contains(search),
                    IPAddress.hostname.ilike(f'%{search}%'),
                    IPAddress.description.ilike(f'%{search}%')
                )
            )

        if conditions:
            query = query.where(and_(*conditions))

        query = query.order_by(IPAddress.ip_address).offset(skip).limit(limit)

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

    async def scan_subnet(
        self,
        db: AsyncSession,
        subnet_id: int,
        scan_type: str = "full"
    ) -> Dict:
        """
        Scan all IPs in a subnet with integrated Ping+DNS+SNMP workflow
        """
        logger.info(f"Starting subnet scan: {subnet_id} (type: {scan_type})")
        start_time = datetime.now(timezone.utc)

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

        # Parse DNS servers from subnet configuration
        dns_servers = None
        if subnet.dns_servers:
            # dns_servers is stored as comma-separated string
            dns_servers = [s.strip() for s in subnet.dns_servers.split(',') if s.strip()]
            logger.info(f"Using DNS servers for subnet {subnet_id}: {dns_servers}")

        # Scan all IPs with SNMP profile (if configured) and DNS servers
        ip_list = [str(ip.ip_address) for ip in ip_addresses]
        scan_results = await ip_scan_service.scan_multiple_ips(
            ip_list,
            scan_type,
            snmp_profile,  # Pass SNMP profile to scanning service
            dns_servers    # Pass DNS servers for PTR lookups
        )

        # Update database
        new_devices = 0
        changed_devices = 0

        for scan_result in scan_results:
            ip_str = scan_result['ip_address']

            # Find IP address record
            ip_addr = next((ip for ip in ip_addresses if str(ip.ip_address) == ip_str), None)
            if not ip_addr:
                continue

            # Detect changes
            status_changed = ip_addr.is_reachable != scan_result['is_reachable']
            hostname_changed = ip_addr.hostname != scan_result['hostname']
            os_changed = ip_addr.os_name != scan_result['os_name']

            if scan_result['is_reachable'] and not ip_addr.last_seen_at:
                new_devices += 1

            if status_changed or hostname_changed or os_changed:
                changed_devices += 1

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
                    .where(cast(ARPTable.ip_address, Text) == ip_str)
                    .order_by(ARPTable.last_seen.desc())
                    .limit(1)
                )
                arp_entry = arp_result.scalar_one_or_none()
                if arp_entry:
                    mac_to_lookup = str(arp_entry.mac_address)
                    logger.info(f"Found MAC for {ip_str} from ARP table: {mac_to_lookup}")

            # Update basic IP address fields
            ip_addr.is_reachable = scan_result['is_reachable']
            ip_addr.response_time = scan_result['response_time']

            # Update hostname with source tracking (SolarWinds-style)
            ip_addr.hostname = scan_result.get('hostname')
            ip_addr.hostname_source = scan_result.get('hostname_source')  # SNMP, DNS, ARP, or None

            # Update SolarWinds-style SNMP/DNS fields
            ip_addr.dns_name = scan_result.get('dns_name')  # DNS PTR result
            ip_addr.system_name = scan_result.get('system_name')  # SNMP sysName
            ip_addr.contact = scan_result.get('contact')  # SNMP sysContact
            ip_addr.location = scan_result.get('location')  # SNMP sysLocation
            ip_addr.machine_type = scan_result.get('machine_type')  # SNMP sysDescr parsed
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

            ip_addr.os_type = scan_result['os_type']
            ip_addr.os_name = scan_result['os_name']
            ip_addr.os_version = scan_result['os_version']
            ip_addr.os_vendor = scan_result['os_vendor']
            ip_addr.last_scan_at = datetime.now(timezone.utc)
            ip_addr.scan_count += 1

            # Intelligent status update logic
            if scan_result['is_reachable']:
                # IP is reachable now
                ip_addr.last_seen_at = datetime.now(timezone.utc)

                # If status is AVAILABLE or OFFLINE, mark as USED
                if ip_addr.status in [IPStatus.AVAILABLE.value, IPStatus.OFFLINE.value]:
                    ip_addr.status = IPStatus.USED.value
            else:
                # IP is NOT reachable
                # Only mark as OFFLINE if it hasn't been seen for a long time
                # This prevents temporary network issues from marking IPs as offline
                if ip_addr.last_seen_at:
                    time_since_last_seen = datetime.now(timezone.utc) - ip_addr.last_seen_at
                    offline_threshold_hours = settings.IPAM_OFFLINE_THRESHOLD_HOURS

                    if time_since_last_seen.total_seconds() > offline_threshold_hours * 3600:
                        # Mark as OFFLINE only if USED (don't change RESERVED or AVAILABLE)
                        if ip_addr.status == IPStatus.USED.value:
                            ip_addr.status = IPStatus.OFFLINE.value
                            logger.info(f"Marking {ip_str} as OFFLINE (not seen for {time_since_last_seen.total_seconds()/3600:.1f} hours)")

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

            # Create history record
            history = IPScanHistory(
                ip_address_id=ip_addr.id,
                is_reachable=scan_result['is_reachable'],
                response_time=scan_result['response_time'],
                hostname=scan_result['hostname'],
                mac_address=scan_result['mac_address'],
                os_type=scan_result['os_type'],
                os_name=scan_result['os_name'],
                status_changed=status_changed,
                hostname_changed=hostname_changed,
                os_changed=os_changed
            )
            db.add(history)

        # Update subnet last scan time
        subnet.last_scan_at = datetime.now(timezone.utc)

        await db.commit()

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        reachable = sum(1 for r in scan_results if r['is_reachable'])

        summary = {
            'total_scanned': len(scan_results),
            'reachable': reachable,
            'unreachable': len(scan_results) - reachable,
            'new_devices': new_devices,
            'changed_devices': changed_devices,
            'scan_duration': elapsed,
            'results': scan_results
        }

        logger.info(f"Subnet scan completed: {summary}")
        return summary

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
            # First, try to find MAC address in mac_table (most accurate)
            from models.mac_table import MACTable

            result = await db.execute(
                select(MACTable, Switch)
                .join(Switch, MACTable.switch_id == Switch.id)
                .where(
                    cast(MACTable.mac_address, Text) == cast(mac_address.lower(), Text)
                )
                .order_by(MACTable.last_seen.desc())
                .limit(1)
            )
            row = result.first()

            if row:
                mac_entry, switch = row

                # Check how many MAC addresses are on this port
                mac_count_result = await db.execute(
                    select(func.count(MACTable.id))
                    .where(
                        and_(
                            MACTable.switch_id == switch.id,
                            MACTable.port_name == mac_entry.port_name
                        )
                    )
                )
                mac_count = mac_count_result.scalar()

                # Only use this port if it has 3 or fewer MAC addresses (likely an access port)
                # Ports with many MACs are trunk/uplink ports
                if mac_count <= 3:
                    ip_addr.switch_id = switch.id
                    ip_addr.switch_port = mac_entry.port_name
                    ip_addr.vlan_id = mac_entry.vlan_id
                    logger.info(
                        f"Found switch info for {ip_addr.ip_address} (MAC: {mac_address}): "
                        f"{switch.name} port {mac_entry.port_name} VLAN {mac_entry.vlan_id} "
                        f"(port has {mac_count} MACs - access port)"
                    )
                else:
                    logger.debug(
                        f"Skipping port {mac_entry.port_name} for {ip_addr.ip_address}: "
                        f"has {mac_count} MACs (likely trunk/uplink port)"
                    )
                return

            # If not found in mac_table, try arp_table (may have switch but not port)
            from models.arp_table import ARPTable

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
                # ARP table usually doesn't have accurate port info, but may have interface
                if arp_entry.interface:
                    ip_addr.switch_port = arp_entry.interface
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
                        select(IPAddress).where(cast(IPAddress.ip_address, Text) == first_ip)
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

    async def scan_all_auto_subnets(self, db: AsyncSession) -> Dict:
        """
        Scan all subnets that have auto_scan enabled and are due for scanning.

        Returns:
            Dictionary with scan statistics
        """
        logger.info("Starting automatic subnet scan")
        start_time = datetime.now(timezone.utc)

        # Get all enabled subnets with auto_scan
        result = await db.execute(
            select(IPSubnet).where(
                and_(
                    IPSubnet.enabled == True,
                    IPSubnet.auto_scan == True
                )
            )
        )
        subnets = result.scalars().all()

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

        for subnet in subnets:
            # Check if subnet needs scanning based on scan_interval
            if subnet.last_scan_at:
                time_since_scan = (datetime.now(timezone.utc) - subnet.last_scan_at).total_seconds()
                if time_since_scan < subnet.scan_interval:
                    logger.debug(
                        f"Skipping {subnet.name} - last scanned {time_since_scan:.0f}s ago "
                        f"(interval: {subnet.scan_interval}s)"
                    )
                    continue

            try:
                logger.info(f"Scanning subnet: {subnet.name} ({subnet.network})")
                scan_result = await self.scan_subnet(db, subnet.id, scan_type="full")
                scanned_count += 1
                total_ips += scan_result.get('total_scanned', 0)
                logger.info(
                    f"Completed scan for {subnet.name}: "
                    f"{scan_result.get('reachable', 0)}/{scan_result.get('total_scanned', 0)} reachable"
                )
            except Exception as e:
                logger.error(f"Failed to scan subnet {subnet.name}: {str(e)}")
                failed_subnets.append({
                    'subnet_id': subnet.id,
                    'subnet_name': subnet.name,
                    'error': str(e)
                })

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        summary = {
            'total_subnets': len(subnets),
            'scanned_subnets': scanned_count,
            'failed_subnets': len(failed_subnets),
            'total_ips_scanned': total_ips,
            'duration': elapsed,
            'failures': failed_subnets
        }

        logger.info(
            f"Automatic subnet scan completed: "
            f"{scanned_count}/{len(subnets)} subnets scanned, "
            f"{total_ips} IPs total, "
            f"duration: {elapsed:.1f}s"
        )

        return summary

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
