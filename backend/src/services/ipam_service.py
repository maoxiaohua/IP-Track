from typing import Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from models.ipam import IPSubnet, IPAddress, IPScanHistory, IPStatus
from models.switch import Switch
from services.ip_scan import ip_scan_service
from services.ip_lookup import ip_lookup_service
from utils.logger import logger
import ipaddress
from datetime import datetime, timedelta
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
        """
        ip_addresses = []

        for ip in network.hosts():
            ip_addr = IPAddress(
                subnet_id=subnet.id,
                ip_address=str(ip),
                status=IPStatus.AVAILABLE
            )
            ip_addresses.append(ip_addr)

        # Bulk insert
        db.add_all(ip_addresses)
        logger.info(f"Generated {len(ip_addresses)} IP addresses for subnet {subnet.id}")

    async def get_subnet(self, db: AsyncSession, subnet_id: int) -> Optional[IPSubnet]:
        """Get subnet by ID"""
        result = await db.execute(
            select(IPSubnet).where(IPSubnet.id == subnet_id)
        )
        return result.scalar_one_or_none()

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
            stats[row.status.value] = row.count

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
        Scan all IPs in a subnet
        """
        logger.info(f"Starting subnet scan: {subnet_id} (type: {scan_type})")
        start_time = datetime.now()

        # Get subnet
        subnet = await self.get_subnet(db, subnet_id)
        if not subnet:
            raise ValueError(f"Subnet {subnet_id} not found")

        # Get all IP addresses
        result = await db.execute(
            select(IPAddress).where(IPAddress.subnet_id == subnet_id)
        )
        ip_addresses = result.scalars().all()

        # Scan all IPs
        ip_list = [str(ip.ip_address) for ip in ip_addresses]
        scan_results = await ip_scan_service.scan_multiple_ips(ip_list, scan_type)

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

            # Update IP address
            ip_addr.is_reachable = scan_result['is_reachable']
            ip_addr.response_time = scan_result['response_time']
            ip_addr.hostname = scan_result['hostname']
            ip_addr.mac_address = scan_result['mac_address']
            ip_addr.os_type = scan_result['os_type']
            ip_addr.os_name = scan_result['os_name']
            ip_addr.os_version = scan_result['os_version']
            ip_addr.os_vendor = scan_result['os_vendor']
            ip_addr.last_scan_at = datetime.now()
            ip_addr.scan_count += 1

            if scan_result['is_reachable']:
                ip_addr.last_seen_at = datetime.now()
                if ip_addr.status == IPStatus.AVAILABLE:
                    ip_addr.status = IPStatus.USED

            # Try to find switch port
            if scan_result['mac_address']:
                await self._update_switch_info(db, ip_addr, scan_result['mac_address'])

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
        subnet.last_scan_at = datetime.now()

        await db.commit()

        elapsed = (datetime.now() - start_time).total_seconds()
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
        Update switch and port information for an IP address
        """
        try:
            # Query all switches for this MAC
            result = await db.execute(select(Switch).where(Switch.enabled == True))
            switches = result.scalars().all()

            for switch in switches:
                try:
                    from services.switch_manager import switch_manager
                    mac_results = switch_manager.query_mac_table(switch, mac_address)

                    if mac_results:
                        port_info = mac_results[0]
                        ip_addr.switch_id = switch.id
                        ip_addr.switch_port = port_info['port']
                        ip_addr.vlan_id = port_info.get('vlan')
                        logger.info(f"Found switch info for {ip_addr.ip_address}: {switch.name}:{port_info['port']}")
                        break

                except Exception as e:
                    logger.debug(f"Error querying switch {switch.name}: {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"Error updating switch info: {str(e)}")

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
            stats[row.status.value] = row.count

        total_ips = sum(stats.values())
        utilization = (stats['used'] / total_ips * 100) if total_ips > 0 else 0

        # Get subnet statistics
        subnets = await self.list_subnets(db, limit=10)
        subnet_stats = []
        for subnet in subnets:
            stats = await self.get_subnet_statistics(db, subnet.id)
            subnet_stats.append({
                'subnet_id': subnet.id,
                'subnet_name': subnet.name,
                'network': subnet.network,
                **stats,
                'last_scan_at': subnet.last_scan_at
            })

        # Recent changes (last 24 hours)
        yesterday = datetime.now() - timedelta(days=1)
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
            'used_ips': stats['used'],
            'available_ips': stats['available'],
            'offline_ips': stats['offline'],
            'overall_utilization': round(utilization, 2),
            'subnets': subnet_stats,
            'recent_changes': recent_changes
        }


# Singleton instance
ipam_service = IPAMService()
