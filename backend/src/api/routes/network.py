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
from services.port_analysis_service import port_analysis_service
from services.port_lookup_policy_service import (
    build_lookup_eligible_clause,
    normalize_lookup_policy_override,
    serialize_lookup_policy,
)
from services.data_freshness_service import (
    build_lookup_result_freshness,
    build_optical_inventory_freshness,
    build_optical_module_freshness,
    build_port_analysis_freshness,
)

router = APIRouter(prefix="/network", tags=["network"])


class PortLookupPolicyUpdateRequest(BaseModel):
    port_name: str
    lookup_policy_override: Optional[str] = None
    lookup_policy_note: Optional[str] = None


def _port_analysis_priority(port: PortAnalysis) -> tuple:
    normalized_name = port_analysis_service.normalize_port_name(port.port_name)
    return (
        1 if port.lookup_policy_override else 0,
        port.lookup_policy_updated_at or datetime.min.replace(tzinfo=timezone.utc),
        1 if port.port_name == normalized_name else 0,
        port.analyzed_at or datetime.min.replace(tzinfo=timezone.utc),
        float(port.confidence_score or 0),
        -len(port.port_name or ""),
    )


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
    last_seen_at = max(
        [ts for ts in [location.last_arp_seen, location.last_mac_seen, location.last_confirmed] if ts is not None],
        default=None
    )
    data_age_seconds = (
        int((datetime.now(timezone.utc) - last_seen_at).total_seconds())
        if last_seen_at else None
    )

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
        "last_mac_seen": location.last_mac_seen.isoformat() if location.last_mac_seen else None,
        "freshness": build_lookup_result_freshness(
            switch,
            data_age_seconds=data_age_seconds,
            last_seen_at=last_seen_at
        )
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
                "last_confirmed": loc.last_confirmed.isoformat(),
                "freshness_status": build_lookup_result_freshness(
                    sw,
                    data_age_seconds=(
                        int((datetime.now(timezone.utc) - max(
                            [ts for ts in [loc.last_arp_seen, loc.last_mac_seen, loc.last_confirmed] if ts is not None],
                            default=loc.last_confirmed
                        )).total_seconds())
                        if (loc.last_arp_seen or loc.last_mac_seen or loc.last_confirmed)
                        else None
                    ),
                    last_seen_at=max(
                        [ts for ts in [loc.last_arp_seen, loc.last_mac_seen, loc.last_confirmed] if ts is not None],
                        default=None
                    )
                )["status"]
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
    deduped_rows = {}
    for port, row_switch in rows:
        canonical_name = port_analysis_service.normalize_port_name(port.port_name)
        existing = deduped_rows.get(canonical_name)
        if existing is None or _port_analysis_priority(port) > _port_analysis_priority(existing[0]):
            deduped_rows[canonical_name] = (port, row_switch, canonical_name)

    normalized_rows = sorted(
        deduped_rows.values(),
        key=lambda item: item[2]
    )
    latest_analyzed_at = max((port.analyzed_at for port, _, _ in normalized_rows), default=None)

    return {
        "switch": {
            "id": switch.id,
            "name": switch.name,
            "ip_address": str(switch.ip_address)
        },
        "freshness": build_port_analysis_freshness(switch, latest_analyzed_at),
        "ports": [
            {
                "port_name": canonical_name,
                "mac_count": port.mac_count,
                "unique_vlans": port.unique_vlans,
                "port_type": port.port_type,
                "confidence_score": port.confidence_score,
                "analyzed_at": port.analyzed_at.isoformat(),
                **serialize_lookup_policy(port)
            }
            for port, _, canonical_name in normalized_rows
        ],
        "summary": {
            "total_ports": len(normalized_rows),
            "access_ports": sum(1 for p, _, _ in normalized_rows if p.port_type == 'access'),
            "trunk_ports": sum(1 for p, _, _ in normalized_rows if p.port_type == 'trunk'),
            "uplink_ports": sum(1 for p, _, _ in normalized_rows if p.port_type == 'uplink'),
            "unknown_ports": sum(1 for p, _, _ in normalized_rows if p.port_type == 'unknown'),
            "lookup_included_ports": sum(
                1 for p, _, _ in normalized_rows if serialize_lookup_policy(p)["lookup_included"]
            ),
            "lookup_excluded_ports": sum(
                1 for p, _, _ in normalized_rows if not serialize_lookup_policy(p)["lookup_included"]
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

    port_name = port_analysis_service.normalize_port_name(request.port_name)
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
    query = select(OpticalModule, Switch).join(
        Switch, OpticalModule.switch_id == Switch.id
    ).order_by(
        desc(OpticalModule.last_seen),
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
    rows = result.all()

    module_payloads = []
    present_count = 0
    historical_count = 0

    for module, switch in rows:
        module_freshness = build_optical_module_freshness(switch, module.last_seen)
        if module_freshness["is_present"]:
            present_count += 1
        else:
            historical_count += 1

        module_payloads.append(
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
                "last_seen": module.last_seen.isoformat(),
                "presence_status": module_freshness["presence_status"],
                "is_present": module_freshness["is_present"],
                "freshness_status": module_freshness["status"],
                "freshness_warning": module_freshness["warning"],
                "switch_is_reachable": switch.is_reachable,
                "switch_last_optical_collection_at": module_freshness["last_optical_collection_at"],
                "switch_last_optical_success_at": module_freshness["last_optical_success_at"],
                "switch_last_optical_collection_status": module_freshness["last_optical_collection_status"],
                "switch_last_optical_collection_message": module_freshness["last_optical_collection_message"],
            }
        )

    return {
        "total": total_count,
        "count": len(module_payloads),
        "offset": offset,
        "limit": limit,
        "present_count": present_count,
        "historical_count": historical_count,
        "modules": module_payloads
    }


@router.get("/optical-modules/statistics")
async def get_optical_module_statistics(db: AsyncSession = Depends(get_db)):
    """Get statistics about optical modules"""
    rows = (
        await db.execute(
            select(OpticalModule, Switch)
            .join(Switch, OpticalModule.switch_id == Switch.id)
        )
    ).all()

    total_modules = len(rows)
    present_modules = 0
    historical_modules = 0
    by_type: dict[str, int] = {}
    by_vendor: dict[str, int] = {}
    by_speed: dict[str, int] = {}
    switch_ids = set()
    present_switch_ids = set()
    stale_switch_ids = set()

    for module, switch in rows:
        switch_ids.add(switch.id)

        inventory_freshness = build_optical_inventory_freshness(switch)
        if inventory_freshness["status"] == "stale":
            stale_switch_ids.add(switch.id)

        module_freshness = build_optical_module_freshness(switch, module.last_seen)
        if module_freshness["is_present"]:
            present_modules += 1
            present_switch_ids.add(switch.id)
        else:
            historical_modules += 1

        module_type = module.module_type or "Unknown"
        by_type[module_type] = by_type.get(module_type, 0) + 1

        if module.vendor:
            by_vendor[module.vendor] = by_vendor.get(module.vendor, 0) + 1

        speed_label = f"{module.speed_gbps}G" if module.speed_gbps else "Unknown"
        by_speed[speed_label] = by_speed.get(speed_label, 0) + 1

    by_type = dict(sorted(by_type.items(), key=lambda item: item[1], reverse=True))
    by_vendor = dict(sorted(by_vendor.items(), key=lambda item: item[1], reverse=True)[:10])
    by_speed = dict(sorted(by_speed.items(), key=lambda item: item[0]))

    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    recent_collections = sum(1 for module, _ in rows if module.last_seen and module.last_seen >= one_day_ago)

    return {
        "total_modules": total_modules,
        "present_modules": present_modules,
        "historical_modules": historical_modules,
        "switches_with_modules": len(switch_ids),
        "switches_with_present_modules": len(present_switch_ids),
        "stale_switches": len(stale_switch_ids),
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
