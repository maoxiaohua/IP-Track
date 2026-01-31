from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from api.deps import get_db
from schemas.ipam import (
    IPSubnetCreate,
    IPSubnetUpdate,
    IPSubnetResponse,
    IPAddressResponse,
    IPAddressUpdate,
    IPAddressDetailResponse,
    IPScanRequest,
    IPScanSummary,
    IPSubnetStatistics,
    IPAMDashboard,
    IPStatus,
    IPScanHistoryResponse
)
from services.ipam_service import ipam_service
from models.ipam import IPAddress
from utils.logger import logger

router = APIRouter(prefix="/ipam", tags=["ipam"])


# Subnet endpoints
@router.post("/subnets", response_model=IPSubnetResponse, status_code=status.HTTP_201_CREATED)
async def create_subnet(
    subnet: IPSubnetCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new IP subnet

    This will automatically generate all IP addresses in the subnet.
    """
    try:
        result = await ipam_service.create_subnet(
            db=db,
            name=subnet.name,
            network=subnet.network,
            description=subnet.description,
            vlan_id=subnet.vlan_id,
            gateway=str(subnet.gateway) if subnet.gateway else None,
            dns_servers=subnet.dns_servers,
            enabled=subnet.enabled,
            auto_scan=subnet.auto_scan,
            scan_interval=subnet.scan_interval
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error creating subnet: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create subnet"
        )


@router.get("/subnets", response_model=List[IPSubnetResponse])
async def list_subnets(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """List all IP subnets"""
    subnets = await ipam_service.list_subnets(db, skip=skip, limit=limit)

    # Add statistics to each subnet
    result = []
    for subnet in subnets:
        stats = await ipam_service.get_subnet_statistics(db, subnet.id)
        subnet_dict = {
            **subnet.__dict__,
            **stats
        }
        result.append(subnet_dict)

    return result


@router.get("/subnets/{subnet_id}", response_model=IPSubnetResponse)
async def get_subnet(
    subnet_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get subnet by ID"""
    subnet = await ipam_service.get_subnet(db, subnet_id)
    if not subnet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subnet {subnet_id} not found"
        )

    # Add statistics
    stats = await ipam_service.get_subnet_statistics(db, subnet.id)
    return {**subnet.__dict__, **stats}


@router.get("/subnets/{subnet_id}/statistics", response_model=IPSubnetStatistics)
async def get_subnet_statistics(
    subnet_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get subnet statistics"""
    subnet = await ipam_service.get_subnet(db, subnet_id)
    if not subnet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subnet {subnet_id} not found"
        )

    stats = await ipam_service.get_subnet_statistics(db, subnet.id)
    return {
        'subnet_id': subnet.id,
        'subnet_name': subnet.name,
        'network': subnet.network,
        **stats,
        'last_scan_at': subnet.last_scan_at
    }


@router.delete("/subnets/{subnet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subnet(
    subnet_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete a subnet and all its IP addresses"""
    subnet = await ipam_service.get_subnet(db, subnet_id)
    if not subnet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subnet {subnet_id} not found"
        )

    await db.delete(subnet)
    await db.commit()


# IP Address endpoints
@router.get("/ip-addresses", response_model=List[IPAddressResponse])
async def list_ip_addresses(
    subnet_id: Optional[int] = Query(None),
    status: Optional[IPStatus] = Query(None),
    is_reachable: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """
    List IP addresses with filters

    - **subnet_id**: Filter by subnet
    - **status**: Filter by status (available, used, reserved, offline)
    - **is_reachable**: Filter by reachability
    - **search**: Search in IP, hostname, or description
    """
    return await ipam_service.list_ip_addresses(
        db=db,
        subnet_id=subnet_id,
        status=status,
        is_reachable=is_reachable,
        search=search,
        skip=skip,
        limit=limit
    )


@router.get("/ip-addresses/{ip_id}", response_model=IPAddressDetailResponse)
async def get_ip_address(
    ip_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get IP address details by ID"""
    from sqlalchemy import select
    from models.ipam import IPSubnet
    from models.switch import Switch

    result = await db.execute(
        select(IPAddress, IPSubnet.name, Switch.name)
        .join(IPSubnet, IPAddress.subnet_id == IPSubnet.id)
        .outerjoin(Switch, IPAddress.switch_id == Switch.id)
        .where(IPAddress.id == ip_id)
    )
    row = result.first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IP address {ip_id} not found"
        )

    ip_addr, subnet_name, switch_name = row
    return {
        **ip_addr.__dict__,
        'subnet_name': subnet_name,
        'switch_name': switch_name
    }


@router.put("/ip-addresses/{ip_id}", response_model=IPAddressResponse)
async def update_ip_address(
    ip_id: int,
    update_data: IPAddressUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update IP address"""
    ip_addr = await ipam_service.update_ip_address(
        db=db,
        ip_id=ip_id,
        status=update_data.status,
        hostname=update_data.hostname,
        mac_address=update_data.mac_address,
        description=update_data.description
    )

    if not ip_addr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IP address {ip_id} not found"
        )

    return ip_addr


@router.get("/ip-addresses/{ip_id}/history", response_model=List[IPScanHistoryResponse])
async def get_ip_scan_history(
    ip_id: int,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db)
):
    """Get scan history for an IP address"""
    from sqlalchemy import select
    from models.ipam import IPScanHistory

    result = await db.execute(
        select(IPScanHistory)
        .where(IPScanHistory.ip_address_id == ip_id)
        .order_by(IPScanHistory.scanned_at.desc())
        .limit(limit)
    )

    return result.scalars().all()


# Scan endpoints
@router.post("/scan", response_model=IPScanSummary)
async def scan_ips(
    scan_request: IPScanRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Scan IP addresses

    - **subnet_id**: Scan all IPs in a subnet
    - **ip_addresses**: Scan specific IP addresses
    - **scan_type**: 'quick' (ping only) or 'full' (ping + hostname + MAC + OS)
    """
    if scan_request.subnet_id:
        # Scan entire subnet
        return await ipam_service.scan_subnet(
            db=db,
            subnet_id=scan_request.subnet_id,
            scan_type=scan_request.scan_type
        )
    elif scan_request.ip_addresses:
        # Scan specific IPs
        from services.ip_scan import ip_scan_service
        import time

        start_time = time.time()
        results = await ip_scan_service.scan_multiple_ips(
            scan_request.ip_addresses,
            scan_request.scan_type
        )
        elapsed = time.time() - start_time

        reachable = sum(1 for r in results if r['is_reachable'])

        return {
            'total_scanned': len(results),
            'reachable': reachable,
            'unreachable': len(results) - reachable,
            'new_devices': 0,
            'changed_devices': 0,
            'scan_duration': elapsed,
            'results': results
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either subnet_id or ip_addresses must be provided"
        )


# Dashboard endpoint
@router.get("/dashboard", response_model=IPAMDashboard)
async def get_dashboard(
    db: AsyncSession = Depends(get_db)
):
    """Get IPAM dashboard statistics"""
    return await ipam_service.get_dashboard_stats(db)
