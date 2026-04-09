"""
API Routes for IP Location and Network Data

Provides endpoints to:
1. Query IP location
2. Trigger manual data collection
3. View collection status
4. Get port analysis results
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, cast, Text, desc
from typing import Optional, List
from datetime import datetime, timedelta, timezone

from core.database import get_db
from models.ip_location import IPLocation
from models.arp_table import ARPTable
from models.mac_table import MACTable
from models.optical_module import OpticalModule
from models.port_analysis import PortAnalysis
from models.switch import Switch
from services.network_data_collector import network_data_collector
from services.network_scheduler import network_scheduler
from services.port_lookup_policy_service import (
    build_lookup_eligible_clause,
    normalize_lookup_policy_override,
    serialize_lookup_policy,
)

router = APIRouter(prefix="/network", tags=["network"])


class PortLookupPolicyUpdateRequest(BaseModel):
    port_name: str
    lookup_policy_override: Optional[str] = None
    lookup_policy_note: Optional[str] = None


@router.get("/ip-location/{ip_address}")
async def get_ip_location(
    ip_address: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get the physical location (switch and port) of an IP address

    Returns:
    - IP address
    - MAC address
    - Switch name and IP
    - Port name
    - VLAN
    - Confidence score
    - Last seen timestamps
    """
    # Query IP location
    result = await db.execute(
        select(IPLocation, Switch).join(
            Switch, IPLocation.switch_id == Switch.id
        ).where(cast(IPLocation.ip_address, Text) == ip_address)
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail=f"IP {ip_address} not found in location database")

    location, switch = row

    return {
        "ip_address": str(location.ip_address),
        "mac_address": location.mac_address,
        "switch": {
            "id": switch.id,
            "name": switch.name,
            "ip_address": str(switch.ip_address),
            "vendor": switch.vendor,
            "role": switch.role
        },
        "port_name": location.port_name,
        "vlan_id": location.vlan_id,
        "confidence_score": location.confidence_score,
        "detection_method": location.detection_method,
        "port_mac_count": location.port_mac_count,
        "appears_on_switches": location.appears_on_switches,
        "first_detected": location.first_detected.isoformat(),
        "last_confirmed": location.last_confirmed.isoformat(),
        "last_arp_seen": location.last_arp_seen.isoformat() if location.last_arp_seen else None,
        "last_mac_seen": location.last_mac_seen.isoformat() if location.last_mac_seen else None
    }


@router.get("/ip-locations")
async def list_ip_locations(
    min_confidence: Optional[float] = Query(default=0, ge=0, le=100),
    switch_id: Optional[int] = None,
    port_name: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """List all IP locations with optional filters"""
    query = select(IPLocation, Switch).join(
        Switch, IPLocation.switch_id == Switch.id
    )

    # Apply filters
    if min_confidence > 0:
        query = query.where(IPLocation.confidence_score >= min_confidence)
    if switch_id:
        query = query.where(IPLocation.switch_id == switch_id)
    if port_name:
        query = query.where(IPLocation.port_name == port_name)

    # Order by confidence (highest first)
    query = query.order_by(IPLocation.confidence_score.desc())

    # Pagination
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    rows = result.all()

    return {
        "count": len(rows),
        "items": [
            {
                "ip_address": str(loc.ip_address),
                "mac_address": loc.mac_address,
                "switch_name": sw.name,
                "switch_ip": str(sw.ip_address),
                "port_name": loc.port_name,
                "vlan_id": loc.vlan_id,
                "confidence_score": loc.confidence_score,
                "last_confirmed": loc.last_confirmed.isoformat()
            }
            for loc, sw in rows
        ]
    }


@router.get("/port-analysis/{switch_id}")
async def get_port_analysis(
    switch_id: int,
    port_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get port analysis results for a switch"""
    query = select(PortAnalysis, Switch).join(
        Switch, PortAnalysis.switch_id == Switch.id
    ).where(PortAnalysis.switch_id == switch_id)

    if port_type:
        query = query.where(PortAnalysis.port_type == port_type)

    query = query.order_by(PortAnalysis.port_name)

    result = await db.execute(query)
    rows = result.all()

    if not rows:
        raise HTTPException(status_code=404, detail=f"Switch {switch_id} not found or no port analysis available")

    switch = rows[0][1]

    return {
        "switch": {
            "id": switch.id,
            "name": switch.name,
            "ip_address": str(switch.ip_address)
        },
        "ports": [
            {
                "port_name": port.port_name,
                "mac_count": port.mac_count,
                "unique_vlans": port.unique_vlans,
                "port_type": port.port_type,
                "confidence_score": port.confidence_score,
                "analyzed_at": port.analyzed_at.isoformat(),
                **serialize_lookup_policy(port)
            }
            for port, _ in rows
        ],
        "summary": {
            "total_ports": len(rows),
            "access_ports": sum(1 for p, _ in rows if p.port_type == 'access'),
            "trunk_ports": sum(1 for p, _ in rows if p.port_type == 'trunk'),
            "uplink_ports": sum(1 for p, _ in rows if p.port_type == 'uplink'),
            "unknown_ports": sum(1 for p, _ in rows if p.port_type == 'unknown'),
            "lookup_included_ports": sum(
                1 for p, _ in rows if serialize_lookup_policy(p)["lookup_included"]
            ),
            "lookup_excluded_ports": sum(
                1 for p, _ in rows if not serialize_lookup_policy(p)["lookup_included"]
            )
        }
    }


@router.put("/port-analysis/{switch_id}/lookup-policy")
async def update_port_lookup_policy(
    switch_id: int,
    request: PortLookupPolicyUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Create or update a manual lookup policy override for a switch port."""
    result = await db.execute(
        select(Switch).where(Switch.id == switch_id)
    )
    switch = result.scalar_one_or_none()

    if not switch:
        raise HTTPException(status_code=404, detail=f"Switch {switch_id} not found")

    try:
        lookup_policy_override = normalize_lookup_policy_override(request.lookup_policy_override)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    port_name = request.port_name.strip()
    if not port_name:
        raise HTTPException(status_code=400, detail="port_name is required")

    result = await db.execute(
        select(PortAnalysis).where(
            and_(
                PortAnalysis.switch_id == switch_id,
                PortAnalysis.port_name == port_name
            )
        )
    )
    port = result.scalar_one_or_none()

    if not port:
        port = PortAnalysis(
            switch_id=switch_id,
            port_name=port_name,
            mac_count=0,
            unique_vlans=0,
            port_type="unknown",
            confidence_score=0.0
        )
        db.add(port)

    port.lookup_policy_override = lookup_policy_override
    port.lookup_policy_note = (request.lookup_policy_note or "").strip() or None
    port.lookup_policy_updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(port)

    return {
        "switch_id": switch_id,
        "switch_name": switch.name,
        "port_name": port.port_name,
        "port_type": port.port_type,
        "mac_count": port.mac_count,
        **serialize_lookup_policy(port)
    }


@router.get("/mac-table/{mac_address}")
async def get_mac_locations(
    mac_address: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Find all switch ports where a MAC address appears.
    Excludes trunk/uplink ports to show only meaningful locations (access ports).
    """
    # Normalize MAC format
    mac_normalized = mac_address.lower().replace('-', ':')

    # Join with port_analysis to filter out ports excluded from lookup matching
    result = await db.execute(
        select(MACTable, Switch)
        .join(Switch, MACTable.switch_id == Switch.id)
        .outerjoin(
            PortAnalysis,
            and_(
                PortAnalysis.switch_id == MACTable.switch_id,
                PortAnalysis.port_name == MACTable.port_name
            )
        )
        .where(cast(MACTable.mac_address, Text) == mac_normalized)
        .where(build_lookup_eligible_clause(PortAnalysis))
        .order_by(desc(MACTable.last_seen))
    )
    rows = result.all()

    if not rows:
        raise HTTPException(status_code=404, detail=f"MAC {mac_address} not found on any access ports")

    return {
        "mac_address": mac_normalized,
        "locations": [
            {
                "switch_name": sw.name,
                "switch_ip": str(sw.ip_address),
                "port_name": mac.port_name,
                "vlan_id": mac.vlan_id,
                "first_seen": mac.first_seen.isoformat(),
                "last_seen": mac.last_seen.isoformat()
            }
            for mac, sw in rows
        ],
        "appears_on_switches": len(set([sw.id for _, sw in rows]))
    }


@router.get("/optical-modules/search")
async def search_optical_modules(
    serial_number: Optional[str] = None,
    model: Optional[str] = None,
    vendor: Optional[str] = None,
    switch_name: Optional[str] = None,
    switch_ip: Optional[str] = None,
    port_name: Optional[str] = None,
    module_type: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """
    Search optical modules by various criteria.

    All search parameters support partial matching (case-insensitive).

    Args:
        serial_number: Module serial number (partial match)
        model: Module model (partial match)
        vendor: Module vendor (partial match)
        switch_name: Switch name (partial match)
        switch_ip: Switch IP address (exact or partial match)
        port_name: Port name (partial match)
        module_type: Module type (SFP, SFP+, QSFP, etc.)
        limit: Maximum number of results (default: 100, max: 1000)
        offset: Offset for pagination

    Returns:
        List of optical modules with switch and location information
    """
    query = select(OpticalModule).order_by(
        desc(OpticalModule.collected_at),
        OpticalModule.switch_name,
        OpticalModule.port_name
    )

    # Build filters - all use ILIKE for case-insensitive partial matching
    filters = []

    if serial_number:
        filters.append(OpticalModule.serial_number.ilike(f"%{serial_number}%"))

    if model:
        filters.append(OpticalModule.model.ilike(f"%{model}%"))

    if vendor:
        filters.append(OpticalModule.vendor.ilike(f"%{vendor}%"))

    if switch_name:
        filters.append(OpticalModule.switch_name.ilike(f"%{switch_name}%"))

    if switch_ip:
        # Support both exact and partial IP matching
        filters.append(cast(OpticalModule.switch_ip, Text).ilike(f"%{switch_ip}%"))

    if port_name:
        filters.append(OpticalModule.port_name.ilike(f"%{port_name}%"))

    if module_type:
        filters.append(OpticalModule.module_type.ilike(f"%{module_type}%"))

    if filters:
        query = query.where(and_(*filters))

    # Get total count before pagination
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total_count = count_result.scalar()

    # Apply pagination
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    modules = result.scalars().all()

    return {
        "total": total_count,
        "count": len(modules),
        "offset": offset,
        "limit": limit,
        "modules": [
            {
                "id": module.id,
                "serial_number": module.serial_number,
                "model": module.model,
                "part_number": module.part_number,
                "vendor": module.vendor,
                "module_type": module.module_type,
                "speed_gbps": module.speed_gbps,
                "switch_id": module.switch_id,
                "switch_name": module.switch_name,
                "switch_ip": str(module.switch_ip) if module.switch_ip else None,
                "port_name": module.port_name,
                "collected_at": module.collected_at.isoformat(),
                "first_seen": module.first_seen.isoformat(),
                "last_seen": module.last_seen.isoformat()
            }
            for module in modules
        ]
    }


@router.get("/optical-modules/statistics")
async def get_optical_module_statistics(db: AsyncSession = Depends(get_db)):
    """Get statistics about optical modules"""
    # Total modules
    result = await db.execute(select(func.count(OpticalModule.id)))
    total_modules = result.scalar()

    # Modules by type
    result = await db.execute(
        select(OpticalModule.module_type, func.count(OpticalModule.id))
        .group_by(OpticalModule.module_type)
        .order_by(desc(func.count(OpticalModule.id)))
    )
    by_type = {row[0] if row[0] else "Unknown": row[1] for row in result.all()}

    # Modules by vendor
    result = await db.execute(
        select(OpticalModule.vendor, func.count(OpticalModule.id))
        .where(OpticalModule.vendor.isnot(None))
        .group_by(OpticalModule.vendor)
        .order_by(desc(func.count(OpticalModule.id)))
        .limit(10)
    )
    by_vendor = {row[0]: row[1] for row in result.all()}

    # Modules by speed
    result = await db.execute(
        select(OpticalModule.speed_gbps, func.count(OpticalModule.id))
        .where(OpticalModule.speed_gbps.isnot(None))
        .group_by(OpticalModule.speed_gbps)
        .order_by(OpticalModule.speed_gbps)
    )
    by_speed = {f"{row[0]}G" if row[0] else "Unknown": row[1] for row in result.all()}

    # Recent collections (last 24 hours)
    one_day_ago = datetime.now() - timedelta(days=1)
    result = await db.execute(
        select(func.count(OpticalModule.id))
        .where(OpticalModule.collected_at >= one_day_ago)
    )
    recent_collections = result.scalar()

    return {
        "total_modules": total_modules,
        "by_type": by_type,
        "by_vendor": by_vendor,
        "by_speed": by_speed,
        "collections_last_24h": recent_collections
    }


@router.post("/optical-modules/collect")
async def trigger_optical_module_collection(db: AsyncSession = Depends(get_db)):
    """Manually trigger optical module collection from all switches"""
    summary = await network_data_collector.collect_optical_modules_from_all_switches(db)
    return summary


@router.post("/collection/trigger")
async def trigger_collection(db: AsyncSession = Depends(get_db)):
    """Manually trigger a network data collection cycle"""
    summary = await network_data_collector.collect_from_all_switches(db)
    return summary


@router.get("/collection/status")
async def get_collection_status():
    """Get scheduler status and next collection time"""
    status = network_scheduler.get_status()

    return {
        "scheduler_running": status['running'],
        "next_collection": status['next_run'],
        "interval_minutes": status['interval_minutes'],
        "collector_running": network_data_collector.collection_running
    }


@router.get("/statistics")
async def get_statistics(db: AsyncSession = Depends(get_db)):
    """Get overall network statistics"""
    # Count total IPs
    result = await db.execute(select(func.count(IPLocation.id)))
    total_ips = result.scalar()

    # Count high confidence IPs (>=70)
    result = await db.execute(
        select(func.count(IPLocation.id)).where(IPLocation.confidence_score >= 70)
    )
    high_confidence_ips = result.scalar()

    # Count total switches
    result = await db.execute(
        select(func.count(Switch.id)).where(Switch.snmp_enabled == True)
    )
    total_switches = result.scalar()

    # Count total ports analyzed
    result = await db.execute(select(func.count(PortAnalysis.id)))
    total_ports = result.scalar()

    # Get recent ARP entries (last hour)
    one_hour_ago = datetime.now() - timedelta(hours=1)
    result = await db.execute(
        select(func.count(ARPTable.id)).where(ARPTable.collected_at >= one_hour_ago)
    )
    recent_arp = result.scalar()

    # Get recent MAC entries (last hour)
    result = await db.execute(
        select(func.count(MACTable.id)).where(MACTable.collected_at >= one_hour_ago)
    )
    recent_mac = result.scalar()

    return {
        "ip_locations": {
            "total": total_ips,
            "high_confidence": high_confidence_ips,
            "confidence_rate": round(high_confidence_ips / total_ips * 100, 1) if total_ips > 0 else 0
        },
        "switches": {
            "total_snmp_enabled": total_switches
        },
        "ports": {
            "total_analyzed": total_ports
        },
        "recent_activity": {
            "arp_entries_last_hour": recent_arp,
            "mac_entries_last_hour": recent_mac
        }
    }
