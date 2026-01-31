from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from api.deps import get_db
from schemas.discovery import (
    SwitchDiscoveryRequest,
    SwitchDiscoveryResponse,
    DiscoveredSwitch
)
from schemas.switch import SwitchCreate, SwitchResponse
from services.switch_discovery import switch_discovery_service
from services.switch_manager import switch_manager
from core.security import credential_encryption
from models.switch import Switch
from utils.logger import logger

router = APIRouter(prefix="/discovery", tags=["discovery"])

# Store discovered switches temporarily (in production, use Redis or database)
_discovery_cache = {}


@router.post("/scan", response_model=SwitchDiscoveryResponse)
async def discover_switches(
    request: SwitchDiscoveryRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Scan an IP range to discover switches

    This endpoint will:
    1. Scan the specified IP range
    2. Try each credential set on each IP
    3. Detect vendor, model, and role automatically
    4. Return list of discovered switches
    """
    try:
        logger.info(f"Starting switch discovery for range: {request.ip_range}")

        # Convert credentials to dict format
        credentials = [
            {
                'username': cred.username,
                'password': cred.password,
                'enable_password': cred.enable_password,
                'port': cred.port
            }
            for cred in request.credentials
        ]

        # Perform discovery
        discovered = await switch_discovery_service.discover_switches(
            request.ip_range,
            credentials
        )

        # Store in cache for later batch add (use session ID in production)
        session_id = f"discovery_{len(_discovery_cache)}"
        _discovery_cache[session_id] = discovered

        # Convert to response format (exclude passwords)
        switches_response = [
            DiscoveredSwitch(
                ip_address=sw['ip_address'],
                name=sw['name'],
                vendor=sw['vendor'],
                model=sw['model'],
                role=sw['role'],
                priority=sw['priority'],
                ssh_port=sw['ssh_port'],
                username=sw['username']
            )
            for sw in discovered
        ]

        # Calculate total scanned IPs
        from services.switch_discovery import SwitchDiscoveryService
        temp_service = SwitchDiscoveryService()
        ip_list = temp_service._parse_ip_range(request.ip_range)
        total_scanned = len(ip_list)

        return SwitchDiscoveryResponse(
            total_scanned=total_scanned,
            discovered=len(discovered),
            switches=switches_response
        )

    except Exception as e:
        logger.error(f"Error during switch discovery: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to discover switches: {str(e)}"
        )


@router.post("/batch-add", response_model=List[SwitchResponse])
async def batch_add_switches(
    discovered_switches: List[SwitchCreate],
    db: AsyncSession = Depends(get_db)
):
    """
    Batch add discovered switches to the database

    Takes a list of switch configurations and adds them all at once.
    """
    try:
        added_switches = []

        for switch_data in discovered_switches:
            # Check if switch already exists
            from sqlalchemy import select
            result = await db.execute(
                select(Switch).where(Switch.ip_address == str(switch_data.ip_address))
            )
            existing = result.scalar_one_or_none()

            if existing:
                logger.warning(f"Switch {switch_data.ip_address} already exists, skipping")
                continue

            # Encrypt credentials
            password_encrypted = credential_encryption.encrypt(switch_data.password)
            enable_password_encrypted = None
            if switch_data.enable_password:
                enable_password_encrypted = credential_encryption.encrypt(switch_data.enable_password)

            # Create switch
            switch = Switch(
                name=switch_data.name,
                ip_address=str(switch_data.ip_address),
                vendor=switch_data.vendor,
                model=switch_data.model,
                role=switch_data.role,
                priority=switch_data.priority,
                ssh_port=switch_data.ssh_port,
                username=switch_data.username,
                password_encrypted=password_encrypted,
                enable_password_encrypted=enable_password_encrypted,
                enabled=switch_data.enabled,
                connection_timeout=switch_data.connection_timeout
            )

            db.add(switch)
            added_switches.append(switch)

        await db.commit()

        # Refresh all switches to get IDs
        for switch in added_switches:
            await db.refresh(switch)

        logger.info(f"Successfully added {len(added_switches)} switches")
        return added_switches

    except Exception as e:
        await db.rollback()
        logger.error(f"Error batch adding switches: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to batch add switches: {str(e)}"
        )
