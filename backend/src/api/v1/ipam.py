from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.responses import StreamingResponse
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
    IPAddressListResponse,
    IPScanRequest,
    IPScanSummary,
    IPSubnetStatistics,
    IPAMDashboard,
    IPStatus,
    IPScanHistoryResponse,
    IPSubnetBatchImportRequest,
    IPSubnetBatchImportResult,
    NetworkSearchRequest,
    NetworkSearchResponse,
    SubnetCalculatorRequest,
    SubnetCalculatorResponse
)
from services.ipam_service import ipam_service
from models.ipam import IPAddress
from utils.logger import logger

# Temporarily disabled due to missing openpyxl package
# TODO: Install openpyxl when network is available
# import openpyxl
# from openpyxl import Workbook
# from openpyxl.styles import Font, PatternFill, Alignment
from io import BytesIO

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
        # Get statistics
        stats = await ipam_service.get_subnet_statistics(db, result.id)
        # Convert IP objects to strings
        return {
            "id": result.id,
            "name": result.name,
            "network": str(result.network),
            "description": result.description,
            "vlan_id": result.vlan_id,
            "gateway": str(result.gateway) if result.gateway else None,
            "dns_servers": result.dns_servers,
            "enabled": result.enabled,
            "auto_scan": result.auto_scan,
            "scan_interval": result.scan_interval,
            "last_scan_at": result.last_scan_at,
            "created_at": result.created_at,
            "updated_at": result.updated_at,
            **stats
        }
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


@router.post("/subnets/batch", response_model=IPSubnetBatchImportResult, status_code=status.HTTP_201_CREATED)
async def batch_import_subnets(
    request: IPSubnetBatchImportRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Batch import multiple IP subnets

    This endpoint allows you to import multiple subnets at once.
    - Maximum 100 subnets per request
    - Optionally skip existing networks (duplicates)
    - Returns detailed results with success/failure counts
    """
    try:
        # Convert Pydantic models to dictionaries
        subnets_data = [subnet.model_dump() for subnet in request.subnets]

        # Call service method
        result = await ipam_service.batch_create_subnets(
            db=db,
            subnets_data=subnets_data,
            skip_existing=request.skip_existing
        )

        return result

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error in batch import: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch import failed: {str(e)}"
        )


@router.get("/subnets/template/download")
async def download_excel_template():
    """
    Download Excel template for batch subnet import

    Returns an Excel file with example data and column headers
    """
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Excel export功能暂时不可用，请联系管理员安装openpyxl库"
    )


@router.post("/subnets/import/excel", response_model=IPSubnetBatchImportResult, status_code=status.HTTP_201_CREATED)
async def import_subnets_from_excel(
    file: UploadFile = File(...),
    skip_existing: bool = Query(True, description="Skip existing networks"),
    db: AsyncSession = Depends(get_db)
):
    """
    Import subnets from Excel file

    Upload an Excel file with subnet data. Use the template for correct format.
    Required columns: 子网名称, 网络地址(CIDR)
    Optional columns: 描述, VLAN ID, 网关, DNS服务器
    """
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Excel导入功能暂时不可用，请联系管理员安装openpyxl库"
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
            "id": subnet.id,
            "name": subnet.name,
            "network": str(subnet.network),
            "description": subnet.description,
            "vlan_id": subnet.vlan_id,
            "gateway": str(subnet.gateway) if subnet.gateway else None,
            "dns_servers": subnet.dns_servers,
            "enabled": subnet.enabled,
            "auto_scan": subnet.auto_scan,
            "scan_interval": subnet.scan_interval,
            "last_scan_at": subnet.last_scan_at,
            "created_at": subnet.created_at,
            "updated_at": subnet.updated_at,
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
    return {
        "id": subnet.id,
        "name": subnet.name,
        "network": str(subnet.network),
        "description": subnet.description,
        "vlan_id": subnet.vlan_id,
        "gateway": str(subnet.gateway) if subnet.gateway else None,
        "dns_servers": subnet.dns_servers,
        "enabled": subnet.enabled,
        "auto_scan": subnet.auto_scan,
        "scan_interval": subnet.scan_interval,
        "last_scan_at": subnet.last_scan_at,
        "created_at": subnet.created_at,
        "updated_at": subnet.updated_at,
        **stats
    }


@router.put("/subnets/{subnet_id}", response_model=IPSubnetResponse)
async def update_subnet(
    subnet_id: int,
    update_data: IPSubnetUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update an existing subnet"""
    try:
        subnet = await ipam_service.update_subnet(
            db=db,
            subnet_id=subnet_id,
            name=update_data.name,
            description=update_data.description,
            vlan_id=update_data.vlan_id,
            gateway=str(update_data.gateway) if update_data.gateway else None,
            dns_servers=update_data.dns_servers,
            enabled=update_data.enabled,
            auto_scan=update_data.auto_scan,
            scan_interval=update_data.scan_interval
        )

        if not subnet:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subnet {subnet_id} not found"
            )

        # Add statistics
        stats = await ipam_service.get_subnet_statistics(db, subnet.id)
        return {
            "id": subnet.id,
            "name": subnet.name,
            "network": str(subnet.network),
            "description": subnet.description,
            "vlan_id": subnet.vlan_id,
            "gateway": str(subnet.gateway) if subnet.gateway else None,
            "dns_servers": subnet.dns_servers,
            "enabled": subnet.enabled,
            "auto_scan": subnet.auto_scan,
            "scan_interval": subnet.scan_interval,
            "last_scan_at": subnet.last_scan_at,
            "created_at": subnet.created_at,
            "updated_at": subnet.updated_at,
            **stats
        }
    except Exception as e:
        logger.error(f"Error updating subnet: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update subnet"
        )


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
        'network': str(subnet.network),
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
@router.get("/ip-addresses", response_model=IPAddressListResponse)
async def list_ip_addresses(
    subnet_id: Optional[int] = Query(None),
    status: Optional[IPStatus] = Query(None),
    is_reachable: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=10000),
    db: AsyncSession = Depends(get_db)
):
    """
    List IP addresses with filters and pagination

    - **subnet_id**: Filter by subnet
    - **status**: Filter by status (available, used, reserved, offline)
    - **is_reachable**: Filter by reachability
    - **search**: Search in IP, hostname, or description
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return (1-10000)
    """
    from sqlalchemy import select, and_, or_, func
    from models.switch import Switch

    # Build query with switch join
    query = select(IPAddress, Switch.name.label('switch_name')).outerjoin(
        Switch, IPAddress.switch_id == Switch.id
    )

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

    # Get total count before pagination
    count_query = select(func.count(IPAddress.id))
    if conditions:
        count_query = count_query.where(and_(*conditions))

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Apply pagination and ordering
    query = query.order_by(IPAddress.ip_address).offset(skip).limit(limit)

    result = await db.execute(query)
    rows = result.all()

    # Convert to response format
    items = []
    for ip_addr, switch_name in rows:
        ip_dict = {
            'id': ip_addr.id,
            'subnet_id': ip_addr.subnet_id,
            'ip_address': str(ip_addr.ip_address),
            'status': ip_addr.status,
            'is_reachable': ip_addr.is_reachable,
            'response_time': ip_addr.response_time,
            'hostname': ip_addr.hostname,
            'mac_address': str(ip_addr.mac_address) if ip_addr.mac_address else None,
            'switch_id': ip_addr.switch_id,
            'switch_name': switch_name,
            'switch_port': ip_addr.switch_port,
            'vlan_id': ip_addr.vlan_id,
            'os_type': ip_addr.os_type,
            'os_name': ip_addr.os_name,
            'os_version': ip_addr.os_version,
            'os_vendor': ip_addr.os_vendor,
            'description': ip_addr.description,
            'last_seen_at': ip_addr.last_seen_at,
            'last_scan_at': ip_addr.last_scan_at,
            'scan_count': ip_addr.scan_count,
            'created_at': ip_addr.created_at,
            'updated_at': ip_addr.updated_at
        }
        items.append(ip_dict)

    return IPAddressListResponse(items=items, total=total)


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


# Network Search endpoint
@router.post("/network-search", response_model=NetworkSearchResponse)
async def search_network(
    request: NetworkSearchRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Search for all IPs in a given network (CIDR)

    Example: 10.101.63.0/24

    Returns all IP addresses in the subnet and their usage status.
    If the network exists in IPAM, returns managed IP data.
    If not, returns calculated network information.
    """
    try:
        result = await ipam_service.search_network(db, request.network)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error searching network: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to search network"
        )


# Subnet Calculator endpoint
@router.post("/subnet-calculator", response_model=SubnetCalculatorResponse)
async def calculate_subnet(
    request: SubnetCalculatorRequest
):
    """
    Calculate subnet information from IP address and netmask

    Input:
    - IP address (e.g., 10.101.63.25)
    - Netmask (e.g., 255.255.255.0 or /24)

    Output:
    - Network address
    - Broadcast address
    - First/last usable host
    - Total hosts
    - Subnet mask
    - CIDR notation
    - Binary and hex representations
    """
    try:
        from services.ipam_service import calculate_subnet_info
        result = calculate_subnet_info(request.ip_address, request.netmask)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error calculating subnet: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to calculate subnet"
        )
