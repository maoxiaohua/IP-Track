from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, or_, and_, cast, String
from typing import List, Dict, Any
from datetime import datetime, timezone
import asyncio
from api.deps import get_db
from models.switch import Switch
from models.arp_table import ARPTable
from models.mac_table import MACTable
from models.port_analysis import PortAnalysis
from models.optical_module import OpticalModule
from schemas.switch import SwitchCreate, SwitchUpdate, SwitchResponse, SwitchTestResponse, SwitchListResponse
from core.security import credential_encryption, decrypt_password
from services.switch_manager import switch_manager
from services.cli_service import cli_service
# Temporarily disabled: from services.snmp_service import snmp_service
from services.port_analysis_service import port_analysis_service
from utils.logger import logger
from utils.network import ping_host, ping_multiple_hosts

router = APIRouter(prefix="/switches", tags=["switches"])


@router.post("", response_model=SwitchResponse, status_code=status.HTTP_201_CREATED)
async def create_switch(
    switch_data: SwitchCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new switch with SNMP authentication"""
    try:
        # Check if switch with same IP already exists
        result = await db.execute(
            select(Switch).where(Switch.ip_address == str(switch_data.ip_address))
        )
        existing = result.scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Switch with IP {switch_data.ip_address} already exists"
            )

        # Encrypt SSH credentials (optional)
        password_encrypted = None
        enable_password_encrypted = None
        if switch_data.password:
            password_encrypted = credential_encryption.encrypt(switch_data.password)
        if switch_data.enable_password:
            enable_password_encrypted = credential_encryption.encrypt(switch_data.enable_password)

        # Encrypt SNMP credentials (required)
        snmp_auth_password_encrypted = None
        snmp_priv_password_encrypted = None
        
        if switch_data.snmp_version == '3':
            # SNMPv3 - encrypt auth and priv passwords
            snmp_auth_password_encrypted = credential_encryption.encrypt(switch_data.snmp_auth_password)
            snmp_priv_password_encrypted = credential_encryption.encrypt(switch_data.snmp_priv_password)
        elif switch_data.snmp_version == '2c' and switch_data.snmp_community:
            # SNMPv2c - encrypt community string (store in auth_password field)
            snmp_auth_password_encrypted = credential_encryption.encrypt(switch_data.snmp_community)

        # Create switch
        switch = Switch(
            name=switch_data.name,
            ip_address=str(switch_data.ip_address),
            vendor=switch_data.vendor,
            model=switch_data.model,
            role=switch_data.role,
            priority=switch_data.priority,
            enabled=switch_data.enabled,
            
            # SSH fields (optional)
            ssh_port=switch_data.ssh_port,
            username=switch_data.username,
            password_encrypted=password_encrypted,
            enable_password_encrypted=enable_password_encrypted,
            connection_timeout=switch_data.connection_timeout,
            
            # SNMP fields (required)
            snmp_enabled=switch_data.snmp_enabled,
            snmp_version=switch_data.snmp_version,
            snmp_port=switch_data.snmp_port,
            snmp_username=switch_data.snmp_username,
            snmp_auth_protocol=switch_data.snmp_auth_protocol,
            snmp_auth_password_encrypted=snmp_auth_password_encrypted,
            snmp_priv_protocol=switch_data.snmp_priv_protocol,
            snmp_priv_password_encrypted=snmp_priv_password_encrypted
        )

        db.add(switch)
        await db.commit()
        await db.refresh(switch)

        logger.info(f"Created switch with SNMP: {switch.name} ({switch.ip_address})")
        return switch

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating switch: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create switch: {str(e)}"
        )


@router.get("", response_model=SwitchListResponse)
async def list_switches(
    skip: int = 0,
    limit: int = 100,
    search: str = None,
    db: AsyncSession = Depends(get_db)
):
    """List all switches with pagination and search"""
    try:
        # Build base query
        query = select(Switch)

        # Add search filter if provided
        if search:
            search_filter = (
                Switch.name.ilike(f"%{search}%") |
                cast(Switch.ip_address, String).ilike(f"%{search}%")
            )
            query = query.where(search_filter)

        # Get total count
        count_query = select(Switch.id)
        if search:
            count_query = count_query.where(search_filter)
        count_result = await db.execute(count_query)
        total = len(count_result.all())

        # Get paginated results
        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        switches = result.scalars().all()

        return SwitchListResponse(items=switches, total=total)
    except Exception as e:
        logger.error(f"Error listing switches: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list switches: {str(e)}"
        )


@router.get("/{switch_id}", response_model=SwitchResponse)
async def get_switch(
    switch_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific switch by ID"""
    try:
        result = await db.execute(
            select(Switch).where(Switch.id == switch_id)
        )
        switch = result.scalar_one_or_none()

        if not switch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Switch with ID {switch_id} not found"
            )

        return switch
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting switch: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get switch: {str(e)}"
        )


@router.put("/{switch_id}", response_model=SwitchResponse)
async def update_switch(
    switch_id: int,
    switch_data: SwitchUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a switch"""
    try:
        result = await db.execute(
            select(Switch).where(Switch.id == switch_id)
        )
        switch = result.scalar_one_or_none()

        if not switch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Switch with ID {switch_id} not found"
            )

        # Update fields
        update_data = switch_data.model_dump(exclude_unset=True)

        # Handle SSH password encryption
        if 'password' in update_data and update_data['password']:
            update_data['password_encrypted'] = credential_encryption.encrypt(update_data.pop('password'))
        elif 'password' in update_data:
            update_data.pop('password')

        if 'enable_password' in update_data and update_data['enable_password']:
            update_data['enable_password_encrypted'] = credential_encryption.encrypt(update_data.pop('enable_password'))
        elif 'enable_password' in update_data:
            update_data.pop('enable_password')

        # Handle SNMP password encryption
        if 'snmp_auth_password' in update_data and update_data['snmp_auth_password']:
            update_data['snmp_auth_password_encrypted'] = credential_encryption.encrypt(update_data.pop('snmp_auth_password'))
        elif 'snmp_auth_password' in update_data:
            update_data.pop('snmp_auth_password')

        if 'snmp_priv_password' in update_data and update_data['snmp_priv_password']:
            update_data['snmp_priv_password_encrypted'] = credential_encryption.encrypt(update_data.pop('snmp_priv_password'))
        elif 'snmp_priv_password' in update_data:
            update_data.pop('snmp_priv_password')

        if 'snmp_community' in update_data and update_data['snmp_community']:
            # Store community in auth_password field for v2c
            update_data['snmp_auth_password_encrypted'] = credential_encryption.encrypt(update_data.pop('snmp_community'))
        elif 'snmp_community' in update_data:
            update_data.pop('snmp_community')

        # Update switch
        for field, value in update_data.items():
            setattr(switch, field, value)

        await db.commit()
        await db.refresh(switch)

        logger.info(f"Updated switch: {switch.name} ({switch.ip_address})")
        return switch

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating switch: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update switch: {str(e)}"
        )


@router.delete("/{switch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_switch(
    switch_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete a switch"""
    try:
        result = await db.execute(
            select(Switch).where(Switch.id == switch_id)
        )
        switch = result.scalar_one_or_none()

        if not switch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Switch with ID {switch_id} not found"
            )

        await db.delete(switch)
        await db.commit()

        logger.info(f"Deleted switch: {switch.name} ({switch.ip_address})")

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting switch: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete switch: {str(e)}"
        )


@router.post("/{switch_id}/test", response_model=SwitchTestResponse)
async def test_switch_connection(
    switch_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Test connection to a switch using SNMP"""
    try:
        result = await db.execute(
            select(Switch).where(Switch.id == switch_id)
        )
        switch = result.scalar_one_or_none()

        if not switch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Switch with ID {switch_id} not found"
            )

        # Test SNMP connectivity if enabled
        if switch.snmp_enabled and switch.snmp_auth_password_encrypted:
            from services.snmp_service import snmp_service
            from core.security import decrypt_password
            
            try:
                # Prepare SNMP config
                snmp_config = {
                    'snmp_username': switch.snmp_username,
                    'snmp_auth_protocol': switch.snmp_auth_protocol,
                    'snmp_auth_password_encrypted': switch.snmp_auth_password_encrypted,
                    'snmp_priv_protocol': switch.snmp_priv_protocol,
                    'snmp_priv_password_encrypted': switch.snmp_priv_password_encrypted,
                    'snmp_port': switch.snmp_port or 161
                }
                
                # Try to get system description via SNMP
                auth_password = decrypt_password(switch.snmp_auth_password_encrypted)
                priv_password = decrypt_password(switch.snmp_priv_password_encrypted) if switch.snmp_priv_password_encrypted else None

                from pysnmp.hlapi.v3arch.asyncio import (
                    SnmpEngine, UsmUserData, UdpTransportTarget, ContextData,
                    ObjectType, ObjectIdentity, get_cmd,
                    usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol, usmHMAC128SHA224AuthProtocol,
                    usmDESPrivProtocol, usmAesCfb128Protocol, usmAesCfb192Protocol, usmAesCfb256Protocol
                )

                # Map protocol names to pysnmp protocol objects
                auth_map = {
                    'MD5': usmHMACMD5AuthProtocol,
                    'SHA': usmHMACSHAAuthProtocol,
                    'SHA256': usmHMAC128SHA224AuthProtocol,
                }
                priv_map = {
                    'DES': usmDESPrivProtocol,
                    'AES': usmAesCfb128Protocol,
                    'AES128': usmAesCfb128Protocol,
                    'AES192': usmAesCfb192Protocol,
                    'AES256': usmAesCfb256Protocol,
                }

                # Get protocols from switch config or use defaults
                auth_proto = auth_map.get(switch.snmp_auth_protocol, usmHMACSHAAuthProtocol)
                priv_proto = priv_map.get(switch.snmp_priv_protocol, usmAesCfb128Protocol)

                # Create SNMP authentication
                auth_data = UsmUserData(
                    switch.snmp_username,
                    authKey=auth_password,
                    privKey=priv_password if priv_password else auth_password,
                    authProtocol=auth_proto,
                    privProtocol=priv_proto
                )

                # Create transport target (pysnmp 7.x requires .create())
                transport = await UdpTransportTarget.create(
                    (str(switch.ip_address), switch.snmp_port or 161),
                    timeout=5,
                    retries=2
                )

                # Test SNMP GET
                errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                    SnmpEngine(),
                    auth_data,
                    transport,
                    ContextData(),
                    ObjectType(ObjectIdentity('1.3.6.1.2.1.1.1.0'))  # sysDescr
                )
                
                if errorIndication:
                    return SwitchTestResponse(
                        success=False,
                        message=f"SNMP connection failed: {errorIndication}",
                        details={"error_type": "connection_error"}
                    )
                elif errorStatus:
                    return SwitchTestResponse(
                        success=False,
                        message=f"SNMP error: {errorStatus.prettyPrint()}",
                        details={"error_type": "snmp_error"}
                    )
                else:
                    sys_descr = str(varBinds[0][1])[:200]
                    return SwitchTestResponse(
                        success=True,
                        message="SNMP connection successful",
                        details={
                            "system_description": sys_descr,
                            "snmp_version": switch.snmp_version,
                            "connection_type": "snmp"
                        }
                    )
            
            except Exception as e:
                logger.error(f"SNMP test failed for switch {switch_id}: {str(e)}")
                return SwitchTestResponse(
                    success=False,
                    message=f"SNMP test failed: {str(e)}",
                    details={"error_type": "exception"}
                )
        else:
            # Fallback to ping test
            is_reachable, response_time = ping_host(str(switch.ip_address), timeout=5)
            
            if is_reachable:
                return SwitchTestResponse(
                    success=True,
                    message=f"Switch is reachable (ping: {response_time:.2f}ms)",
                    details={"response_time_ms": response_time, "connection_type": "ping"}
                )
            else:
                return SwitchTestResponse(
                    success=False,
                    message="Switch is not reachable",
                    details={"connection_type": "ping"}
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing switch connection: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to test switch connection: {str(e)}"
        )


@router.post("/bulk", response_model=List[SwitchResponse], status_code=status.HTTP_201_CREATED)
async def bulk_create_switches(
    switches_data: List[SwitchCreate],
    db: AsyncSession = Depends(get_db)
):
    """Bulk create switches"""
    created_switches = []
    errors = []

    for idx, switch_data in enumerate(switches_data):
        try:
            # Check if switch with same IP already exists
            result = await db.execute(
                select(Switch).where(Switch.ip_address == str(switch_data.ip_address))
            )
            existing = result.scalar_one_or_none()
            if existing:
                errors.append(f"Row {idx + 1}: Switch with IP {switch_data.ip_address} already exists")
                continue

            # Encrypt credentials
            password_encrypted = None
            enable_password_encrypted = None
            if switch_data.password:
                password_encrypted = credential_encryption.encrypt(switch_data.password)
            if switch_data.enable_password:
                enable_password_encrypted = credential_encryption.encrypt(switch_data.enable_password)

            # Encrypt SNMP credentials
            snmp_auth_password_encrypted = None
            snmp_priv_password_encrypted = None
            
            if switch_data.snmp_version == '3':
                snmp_auth_password_encrypted = credential_encryption.encrypt(switch_data.snmp_auth_password)
                snmp_priv_password_encrypted = credential_encryption.encrypt(switch_data.snmp_priv_password)
            elif switch_data.snmp_version == '2c' and switch_data.snmp_community:
                snmp_auth_password_encrypted = credential_encryption.encrypt(switch_data.snmp_community)

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
                connection_timeout=switch_data.connection_timeout,
                snmp_enabled=switch_data.snmp_enabled,
                snmp_version=switch_data.snmp_version,
                snmp_port=switch_data.snmp_port,
                snmp_username=switch_data.snmp_username,
                snmp_auth_protocol=switch_data.snmp_auth_protocol,
                snmp_auth_password_encrypted=snmp_auth_password_encrypted,
                snmp_priv_protocol=switch_data.snmp_priv_protocol,
                snmp_priv_password_encrypted=snmp_priv_password_encrypted
            )

            db.add(switch)
            created_switches.append(switch)

        except Exception as e:
            errors.append(f"Row {idx + 1}: {str(e)}")

    if errors:
        await db.rollback()
        error_msg = "; ".join(errors[:5])  # Limit error message length
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bulk creation failed: {error_msg}"
        )

    await db.commit()
    for switch in created_switches:
        await db.refresh(switch)

    logger.info(f"Bulk created {len(created_switches)} switches")
    return created_switches


@router.get("/{switch_id}/arp", response_model=Dict[str, Any])
async def get_switch_arp_table(
    switch_id: int,
    limit: int = 1000,
    db: AsyncSession = Depends(get_db)
):
    """Get ARP table entries for a specific switch"""
    try:
        # Verify switch exists
        result = await db.execute(
            select(Switch).where(Switch.id == switch_id)
        )
        switch = result.scalar_one_or_none()

        if not switch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Switch with ID {switch_id} not found"
            )

        # Get ARP entries
        result = await db.execute(
            select(ARPTable)
            .where(ARPTable.switch_id == switch_id)
            .order_by(desc(ARPTable.last_seen))
            .limit(limit)
        )
        arp_entries = result.scalars().all()

        # Format response
        entries = []
        for entry in arp_entries:
            entries.append({
                'id': entry.id,
                'ip_address': str(entry.ip_address),
                'mac_address': str(entry.mac_address),
                'vlan_id': entry.vlan_id,
                'interface': entry.interface,
                'age_seconds': entry.age_seconds,
                'collected_at': entry.collected_at.isoformat() if entry.collected_at else None,
                'first_seen': entry.first_seen.isoformat() if entry.first_seen else None,
                'last_seen': entry.last_seen.isoformat() if entry.last_seen else None
            })

        return {
            'switch_id': switch_id,
            'switch_name': switch.name,
            'switch_ip': str(switch.ip_address),
            'total_entries': len(entries),
            'entries': entries
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting ARP table for switch {switch_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get ARP table: {str(e)}"
        )


@router.get("/{switch_id}/mac", response_model=Dict[str, Any])
async def get_switch_mac_table(
    switch_id: int,
    limit: int = 5000,
    db: AsyncSession = Depends(get_db)
):
    """Get MAC address table entries for a specific switch"""
    try:
        # Verify switch exists
        result = await db.execute(
            select(Switch).where(Switch.id == switch_id)
        )
        switch = result.scalar_one_or_none()

        if not switch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Switch with ID {switch_id} not found"
            )

        # Get MAC entries, excluding trunk/uplink ports
        # Strategy:
        # 1. If port_analysis exists: use port_type to filter (only exclude trunk/uplink)
        # 2. If no port_analysis: show all MACs (analysis will be created in next collection cycle)
        #    - This is safer than using arbitrary MAC count threshold
        #    - Cascaded switches and APs typically have 5-30 MACs, which are NOT trunks
        #    - Temporary display of trunk MACs is acceptable until port_analysis is available

        result = await db.execute(
            select(MACTable)
            .outerjoin(
                PortAnalysis,
                and_(
                    PortAnalysis.switch_id == MACTable.switch_id,
                    PortAnalysis.port_name == MACTable.port_name
                )
            )
            .where(MACTable.switch_id == switch_id)
            .where(
                or_(
                    # If no port_analysis: show all (will be classified in next collection)
                    PortAnalysis.id.is_(None),
                    # If port_analysis exists: only exclude explicit trunk/uplink
                    PortAnalysis.port_type.notin_(['trunk', 'uplink'])
                )
            )
            .order_by(desc(MACTable.last_seen))
            .limit(limit)
        )
        mac_entries = result.scalars().all()

        # Format response
        entries = []
        for entry in mac_entries:
            entries.append({
                'id': entry.id,
                'mac_address': str(entry.mac_address),
                'port_name': entry.port_name,
                'vlan_id': entry.vlan_id,
                'is_dynamic': bool(entry.is_dynamic),
                'collected_at': entry.collected_at.isoformat() if entry.collected_at else None,
                'first_seen': entry.first_seen.isoformat() if entry.first_seen else None,
                'last_seen': entry.last_seen.isoformat() if entry.last_seen else None
            })

        return {
            'switch_id': switch_id,
            'switch_name': switch.name,
            'switch_ip': str(switch.ip_address),
            'total_entries': len(entries),
            'entries': entries
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting MAC table for switch {switch_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get MAC table: {str(e)}"
        )


@router.post("/{switch_id}/collect/arp", response_model=Dict[str, Any])
async def collect_switch_arp_table(
    switch_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Manually collect ARP table from switch via CLI/SNMP"""
    try:
        # Verify switch exists
        result = await db.execute(
            select(Switch).where(Switch.id == switch_id)
        )
        switch = result.scalar_one_or_none()

        if not switch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Switch with ID {switch_id} not found"
            )

        logger.info(f"Manual ARP collection triggered for switch {switch.name} ({switch.ip_address})")

        # Prepare switch config for CLI
        cli_config = {
            'username': switch.username,
            'password_encrypted': switch.password_encrypted,
            'enable_password_encrypted': switch.enable_password_encrypted,
            'device_type': 'nokia_sros',  # Will be determined based on vendor
            'vendor': switch.vendor,
            'model': switch.model,
            'name': switch.name,
            'ssh_port': switch.ssh_port,
            'connection_timeout': switch.connection_timeout
        }

        # Determine collection strategy based on vendor/model
        arp_entries = []
        collection_method = None

        # Determine if SNMP should be tried first
        try:
            from config.collection_strategy import CollectionStrategy, CollectionMethod
            collection_strategy = CollectionStrategy.get_strategy(switch.vendor or '', switch.model or '')
            use_snmp_first = (collection_strategy == CollectionMethod.SNMP_PRIMARY)
        except ImportError:
            # Fallback: SNMP first for Cisco/Dell, CLI first for Alcatel
            vendor_lower = switch.vendor.lower() if switch.vendor else ''
            use_snmp_first = vendor_lower in ['cisco', 'dell']

        # SNMP-first strategy (Cisco, Dell)
        if use_snmp_first:
            # Try SNMP first
            if switch.snmp_enabled:
                logger.info(f"Collecting ARP via SNMP (primary) for {switch.name}")
                try:
                    snmp_config = {
                        'snmp_username': switch.snmp_username,
                        'snmp_auth_protocol': switch.snmp_auth_protocol,
                        'snmp_auth_password_encrypted': switch.snmp_auth_password_encrypted,
                        'snmp_priv_protocol': switch.snmp_priv_protocol,
                        'snmp_priv_password_encrypted': switch.snmp_priv_password_encrypted,
                        'snmp_port': switch.snmp_port
                    }
                    # Add timeout to prevent hanging indefinitely
                    arp_entries_snmp = await asyncio.wait_for(
                        snmp_service.collect_arp_table(
                            str(switch.ip_address),
                            snmp_config
                        ),
                        timeout=30.0  # 30 second timeout
                    )
                    if arp_entries_snmp:
                        arp_entries = arp_entries_snmp
                        collection_method = 'SNMP'
                        logger.info(f"✅ Collected {len(arp_entries)} ARP entries via SNMP from {switch.name}")
                except asyncio.TimeoutError:
                    logger.warning(f"SNMP ARP collection timeout for {switch.name} (30s exceeded)")
                except Exception as e:
                    logger.warning(f"SNMP ARP collection failed for {switch.name}: {str(e)}")

            # CLI fallback
            if not arp_entries:
                logger.info(f"Falling back to CLI for ARP on {switch.name}")
                try:
                    arp_entries_cli = await asyncio.to_thread(
                        cli_service.collect_arp_table_cli,
                        str(switch.ip_address),
                        cli_config,
                        None  # templates
                    )
                    if arp_entries_cli:
                        arp_entries = arp_entries_cli
                        collection_method = 'CLI (fallback)'
                        logger.info(f"Collected {len(arp_entries)} ARP entries via CLI fallback from {switch.name}")
                except Exception as e:
                    logger.warning(f"CLI ARP fallback failed for {switch.name}: {str(e)}")

        # CLI-first strategy (Alcatel)
        else:
            # Try CLI
            logger.info(f"Collecting ARP via CLI (primary) for {switch.name}")
            try:
                arp_entries_cli = await asyncio.to_thread(
                    cli_service.collect_arp_table_cli,
                    str(switch.ip_address),
                    cli_config,
                    None  # templates
                )
                if arp_entries_cli:
                    arp_entries = arp_entries_cli
                    collection_method = 'CLI'
                    logger.info(f"Collected {len(arp_entries)} ARP entries via CLI from {switch.name}")
            except Exception as e:
                logger.warning(f"CLI ARP collection failed for {switch.name}: {str(e)}")

            # Alcatel: CLI only, no SNMP fallback

        if not arp_entries:
            return {
                'switch_id': switch_id,
                'switch_name': switch.name,
                'switch_ip': str(switch.ip_address),
                'total_entries': 0,
                'collection_method': None,
                'message': f'Failed to collect ARP table via CLI{" and SNMP" if switch.vendor and switch.vendor.lower() in ["cisco", "dell"] else ""}',
                'entries': []
            }

        # Store in database
        now = datetime.now(timezone.utc)
        
        # Delete old entries for this switch
        await db.execute(
            ARPTable.__table__.delete().where(ARPTable.switch_id == switch_id)
        )

        # Insert new entries
        for entry in arp_entries:
            arp_record = ARPTable(
                switch_id=switch_id,
                ip_address=entry['ip_address'],
                mac_address=entry['mac_address'],
                vlan_id=entry.get('vlan_id'),
                interface=entry.get('interface'),
                age_seconds=entry.get('age_seconds'),
                collected_at=now,
                first_seen=now,
                last_seen=now
            )
            db.add(arp_record)

        await db.commit()

        logger.info(f"✅ Stored {len(arp_entries)} ARP entries for {switch.name}")

        return {
            'switch_id': switch_id,
            'switch_name': switch.name,
            'switch_ip': str(switch.ip_address),
            'total_entries': len(arp_entries),
            'collection_method': collection_method,
            'message': f'Successfully collected {len(arp_entries)} ARP entries via {collection_method}',
            'entries': arp_entries[:100]  # Return first 100 for preview
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error collecting ARP table for switch {switch_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to collect ARP table: {str(e)}"
        )


@router.post("/{switch_id}/collect/mac", response_model=Dict[str, Any])
async def collect_switch_mac_table(
    switch_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Manually collect MAC address table from switch via CLI/SNMP"""
    try:
        # Verify switch exists
        result = await db.execute(
            select(Switch).where(Switch.id == switch_id)
        )
        switch = result.scalar_one_or_none()

        if not switch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Switch with ID {switch_id} not found"
            )

        logger.info(f"Manual MAC collection triggered for switch {switch.name} ({switch.ip_address})")

        # Prepare switch config for CLI
        cli_config = {
            'username': switch.username,
            'password_encrypted': switch.password_encrypted,
            'enable_password_encrypted': switch.enable_password_encrypted,
            'device_type': 'nokia_sros',
            'vendor': switch.vendor,
            'model': switch.model,
            'name': switch.name,
            'ssh_port': switch.ssh_port,
            'connection_timeout': switch.connection_timeout
        }

        # Determine collection strategy based on vendor/model
        mac_entries = []
        collection_method = None

        # Determine if SNMP should be tried first
        try:
            from config.collection_strategy import CollectionStrategy, CollectionMethod
            collection_strategy = CollectionStrategy.get_strategy(switch.vendor or '', switch.model or '')
            use_snmp_first = (collection_strategy == CollectionMethod.SNMP_PRIMARY)
        except ImportError:
            # Fallback: SNMP first for Cisco/Dell, CLI first for Alcatel
            vendor_lower = switch.vendor.lower() if switch.vendor else ''
            use_snmp_first = vendor_lower in ['cisco', 'dell']

        # SNMP-first strategy (Cisco, Dell)
        if use_snmp_first:
            # Try SNMP first
            if switch.snmp_enabled:
                logger.info(f"Collecting MAC via SNMP (primary) for {switch.name}")
                try:
                    snmp_config = {
                        'snmp_username': switch.snmp_username,
                        'snmp_auth_protocol': switch.snmp_auth_protocol,
                        'snmp_auth_password_encrypted': switch.snmp_auth_password_encrypted,
                        'snmp_priv_protocol': switch.snmp_priv_protocol,
                        'snmp_priv_password_encrypted': switch.snmp_priv_password_encrypted,
                        'snmp_port': switch.snmp_port
                    }
                    # Add timeout to prevent hanging indefinitely
                    mac_entries_snmp = await asyncio.wait_for(
                        snmp_service.collect_mac_table(
                            str(switch.ip_address),
                            snmp_config
                        ),
                        timeout=30.0  # 30 second timeout
                    )
                    if mac_entries_snmp:
                        mac_entries = mac_entries_snmp
                        collection_method = 'SNMP'
                        logger.info(f"✅ Collected {len(mac_entries)} MAC entries via SNMP from {switch.name}")
                except asyncio.TimeoutError:
                    logger.warning(f"SNMP MAC collection timeout for {switch.name} (30s exceeded)")
                except Exception as e:
                    logger.warning(f"SNMP MAC collection failed for {switch.name}: {str(e)}")

            # CLI fallback
            if not mac_entries:
                logger.info(f"Falling back to CLI for MAC on {switch.name}")
                try:
                    mac_entries_cli = await asyncio.to_thread(
                        cli_service.collect_mac_table_cli,
                        str(switch.ip_address),
                        cli_config,
                        None  # templates
                    )
                    if mac_entries_cli:
                        mac_entries = mac_entries_cli
                        collection_method = 'CLI (fallback)'
                        logger.info(f"Collected {len(mac_entries)} MAC entries via CLI fallback from {switch.name}")
                except Exception as e:
                    logger.warning(f"CLI MAC fallback failed for {switch.name}: {str(e)}")

        # CLI-first strategy (Alcatel)
        else:
            # Try CLI
            logger.info(f"Collecting MAC via CLI (primary) for {switch.name}")
            try:
                mac_entries_cli = await asyncio.to_thread(
                    cli_service.collect_mac_table_cli,
                    str(switch.ip_address),
                    cli_config,
                    None  # templates
                )
                if mac_entries_cli:
                    mac_entries = mac_entries_cli
                    collection_method = 'CLI'
                    logger.info(f"Collected {len(mac_entries)} MAC entries via CLI from {switch.name}")
            except Exception as e:
                logger.warning(f"CLI MAC collection failed for {switch.name}: {str(e)}")

            # Alcatel: CLI only, no SNMP fallback

        if not mac_entries:
            return {
                'switch_id': switch_id,
                'switch_name': switch.name,
                'switch_ip': str(switch.ip_address),
                'total_entries': 0,
                'collection_method': None,
                'message': f'Failed to collect MAC table via CLI{" and SNMP" if switch.vendor and switch.vendor.lower() in ["cisco", "dell"] else ""}',
                'entries': []
            }

        # Store in database
        now = datetime.now(timezone.utc)
        
        # Delete old entries for this switch
        await db.execute(
            MACTable.__table__.delete().where(MACTable.switch_id == switch_id)
        )

        # Insert new entries
        for entry in mac_entries:
            mac_record = MACTable(
                switch_id=switch_id,
                mac_address=entry['mac_address'],
                port_name=entry['port_name'],
                vlan_id=entry.get('vlan_id'),
                is_dynamic=entry.get('is_dynamic', 1),
                collected_at=now,
                first_seen=now,
                last_seen=now
            )
            db.add(mac_record)

        await db.commit()

        logger.info(f"✅ Stored {len(mac_entries)} MAC entries for {switch.name}")

        return {
            'switch_id': switch_id,
            'switch_name': switch.name,
            'switch_ip': str(switch.ip_address),
            'total_entries': len(mac_entries),
            'collection_method': collection_method,
            'message': f'Successfully collected {len(mac_entries)} MAC entries via {collection_method}',
            'entries': mac_entries[:100]  # Return first 100 for preview
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error collecting MAC table for switch {switch_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to collect MAC table: {str(e)}"
        )


@router.post("/{switch_id}/collect/device-info", response_model=Dict[str, Any])
async def collect_switch_device_info(
    switch_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Manually collect device information (hostname, model, version) from switch via CLI"""
    try:
        # Verify switch exists
        result = await db.execute(
            select(Switch).where(Switch.id == switch_id)
        )
        switch = result.scalar_one_or_none()

        if not switch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Switch with ID {switch_id} not found"
            )

        logger.info(f"Manual device info collection triggered for switch {switch.name} ({switch.ip_address})")

        # Prepare switch config for CLI
        cli_config = {
            'username': switch.username,
            'password_encrypted': switch.password_encrypted,
            'device_type': 'nokia_sros',
            'vendor': switch.vendor,
            'model': switch.model,
            'ssh_port': switch.ssh_port,
            'connection_timeout': switch.connection_timeout
        }

        # Collect device info
        device_info = await asyncio.to_thread(
            cli_service.get_device_info_cli,
            str(switch.ip_address),
            cli_config
        )

        if not device_info:
            return {
                'switch_id': switch_id,
                'switch_ip': str(switch.ip_address),
                'success': False,
                'message': 'Failed to collect device information',
                'updated_fields': []
            }

        # Update switch information
        updated_fields = []
        old_values = {}
        
        if device_info.get('hostname'):
            hostname = device_info['hostname']
            # Validate hostname
            if (hostname and 
                hostname != switch.name and
                len(hostname) >= 2 and
                hostname.strip() not in [':', '-', '_', '.'] and
                any(c.isalnum() for c in hostname)):
                old_values['name'] = switch.name
                switch.name = hostname
                updated_fields.append('name')

        if device_info.get('model'):
            if device_info['model'] != switch.model:
                old_values['model'] = switch.model
                switch.model = device_info['model']
                updated_fields.append('model')

        if updated_fields:
            db.add(switch)
            await db.commit()
            await db.refresh(switch)
            logger.info(f"✅ Updated device info for {switch.ip_address}: {updated_fields}")

        return {
            'switch_id': switch_id,
            'switch_ip': str(switch.ip_address),
            'success': True,
            'message': f'Successfully collected device information. Updated fields: {", ".join(updated_fields)}' if updated_fields else 'No changes detected',
            'updated_fields': updated_fields,
            'old_values': old_values,
            'new_values': {
                'name': switch.name,
                'model': switch.model,
                'vendor': switch.vendor
            },
            'device_info': device_info
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error collecting device info for switch {switch_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to collect device information: {str(e)}"
        )


@router.post("/{switch_id}/analyze-ports", response_model=Dict[str, Any])
async def trigger_port_analysis(
    switch_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger port analysis for a specific switch.

    This endpoint:
    1. Collects MAC table from the switch via CLI/SNMP
    2. Analyzes ports based on MAC count, VLAN distribution, and port naming
    3. Stores port_analysis records in the database

    Useful for switches that have stale or missing port_analysis data.
    """
    try:
        # Verify switch exists
        result = await db.execute(
            select(Switch).where(Switch.id == switch_id)
        )
        switch = result.scalar_one_or_none()

        if not switch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Switch with ID {switch_id} not found"
            )

        logger.info(f"Manual port analysis triggered for switch {switch.name} ({switch.ip_address})")

        # Step 1: Collect MAC table
        mac_entries = []

        # Try CLI first if enabled
        if switch.cli_enabled and switch.password_encrypted:
            logger.info(f"  Collecting MAC table via CLI for {switch.name}")
            try:
                cli_config = {
                    'username': switch.username,
                    'password_encrypted': switch.password_encrypted,
                    'device_type': 'nokia_sros',  # Will be determined by CLI service
                    'vendor': switch.vendor,
                    'model': switch.model,
                    'ssh_port': switch.ssh_port,
                    'connection_timeout': switch.connection_timeout
                }

                mac_entries = await asyncio.to_thread(
                    cli_service.collect_mac_table_cli,
                    str(switch.ip_address),
                    cli_config
                )

                if mac_entries:
                    logger.info(f"  ✅ CLI MAC collection successful: {len(mac_entries)} entries")
            except Exception as e:
                logger.warning(f"  CLI MAC collection failed for {switch.name}: {str(e)}")

        # SNMP fallback - ENABLED for Cisco and Dell only (Alcatel uses CLI)
        # Cisco和Dell使用SNMP收集，Alcatel使用CLI收集
        if not mac_entries and switch.snmp_enabled and switch.snmp_auth_password_encrypted:
            vendor_lower = switch.vendor.lower() if switch.vendor else ''
            if vendor_lower in ['cisco', 'dell']:
                logger.info(f"  Falling back to SNMP for MAC collection on {switch.name} [vendor: {switch.vendor}]")
                try:
                    from core.config import get_snmp_config
                    mac_entries = await snmp_service.collect_mac_table_async(
                        str(switch.ip_address),
                        get_snmp_config()
                    )
                    if mac_entries:
                        logger.info(f"  ✅ SNMP MAC fallback successful: {len(mac_entries)} entries")
                except Exception as e:
                    logger.warning(f"  SNMP MAC fallback also failed for {switch.name}: {str(e)}")
            else:
                logger.debug(f"  Skipping SNMP fallback for {switch.name} (vendor: {switch.vendor}, uses CLI only)")

        if not mac_entries:
            return {
                'switch_id': switch_id,
                'switch_ip': str(switch.ip_address),
                'switch_name': switch.name,
                'success': False,
                'message': 'No MAC entries collected. CLI failed or returned zero entries.',
                'ports_analyzed': 0,
                'collection_methods_tried': [
                    'CLI' if switch.cli_enabled else None,
                    'SNMP' if switch.snmp_enabled else None
                ]
            }

        # Step 2: Analyze ports
        logger.info(f"  Analyzing ports for {switch.name} based on {len(mac_entries)} MAC entries")

        # Convert MAC entries to dict format expected by port_analysis_service
        mac_dicts = [
            {
                'port_name': entry.get('port'),
                'vlan_id': entry.get('vlan'),
                'mac_address': entry.get('mac')
            }
            for entry in mac_entries
            if entry.get('port') and entry.get('mac')
        ]

        port_results = port_analysis_service.analyze_port_statistics(mac_dicts)

        if not port_results:
            return {
                'switch_id': switch_id,
                'switch_ip': str(switch.ip_address),
                'switch_name': switch.name,
                'success': False,
                'message': f'Collected {len(mac_entries)} MAC entries but port analysis returned no results.',
                'ports_analyzed': 0,
                'mac_entries_collected': len(mac_entries)
            }

        # Step 3: Store port_analysis records (upsert)
        analyzed_at = datetime.now(timezone.utc)
        ports_updated = 0
        ports_created = 0

        for port_name, analysis in port_results.items():
            # Check if port_analysis record already exists
            result = await db.execute(
                select(PortAnalysis).where(
                    and_(
                        PortAnalysis.switch_id == switch_id,
                        PortAnalysis.port_name == port_name
                    )
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing record
                existing.mac_count = analysis['mac_count']
                existing.unique_vlans = analysis['unique_vlans']
                existing.port_type = analysis['port_type']
                existing.confidence_score = analysis['confidence']
                existing.is_trunk_by_name = 1 if analysis.get('is_trunk_by_name') else 0
                existing.is_access_by_name = 1 if analysis.get('is_access_by_name') else 0
                existing.analyzed_at = analyzed_at
                ports_updated += 1
            else:
                # Create new record
                port_analysis_record = PortAnalysis(
                    switch_id=switch_id,
                    port_name=port_name,
                    mac_count=analysis['mac_count'],
                    unique_vlans=analysis['unique_vlans'],
                    port_type=analysis['port_type'],
                    confidence_score=analysis['confidence'],
                    is_trunk_by_name=1 if analysis.get('is_trunk_by_name') else 0,
                    is_access_by_name=1 if analysis.get('is_access_by_name') else 0,
                    analyzed_at=analyzed_at
                )
                db.add(port_analysis_record)
                ports_created += 1

        await db.commit()

        logger.info(
            f"✅ Port analysis complete for {switch.name}: "
            f"{ports_created} created, {ports_updated} updated"
        )

        # Summarize results by port type
        port_types_summary = {}
        for port_name, analysis in port_results.items():
            port_type = analysis['port_type']
            if port_type not in port_types_summary:
                port_types_summary[port_type] = 0
            port_types_summary[port_type] += 1

        return {
            'switch_id': switch_id,
            'switch_ip': str(switch.ip_address),
            'switch_name': switch.name,
            'success': True,
            'message': f'Successfully analyzed {len(port_results)} ports',
            'ports_analyzed': len(port_results),
            'ports_created': ports_created,
            'ports_updated': ports_updated,
            'mac_entries_collected': len(mac_entries),
            'port_types_summary': port_types_summary,
            'analyzed_at': analyzed_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing ports for switch {switch_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze ports: {str(e)}"
        )

@router.get("/{switch_id}/optical-modules", response_model=Dict[str, Any])
async def get_switch_optical_modules(
    switch_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get optical module (SFP/QSFP) information for a specific switch"""
    try:
        # Verify switch exists
        result = await db.execute(
            select(Switch).where(Switch.id == switch_id)
        )
        switch = result.scalar_one_or_none()

        if not switch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Switch with ID {switch_id} not found"
            )

        # Get optical module entries
        result = await db.execute(
            select(OpticalModule)
            .where(OpticalModule.switch_id == switch_id)
            .order_by(OpticalModule.port_name)
        )
        modules = result.scalars().all()

        # Format response
        entries = []
        for module in modules:
            entries.append({
                'id': module.id,
                'port_name': module.port_name,
                'module_type': module.module_type,
                'model': module.model,
                'serial_number': module.serial_number,
                'vendor': module.vendor,
                'speed_gbps': module.speed_gbps,
                'collected_at': module.collected_at.isoformat() if module.collected_at else None,
                'first_seen': module.first_seen.isoformat() if module.first_seen else None,
                'last_seen': module.last_seen.isoformat() if module.last_seen else None
            })

        return {
            'switch_id': switch_id,
            'switch_name': switch.name,
            'switch_ip': str(switch.ip_address),
            'total_modules': len(entries),
            'entries': entries
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting optical modules for switch {switch_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get optical modules: {str(e)}"
        )


@router.post("/{switch_id}/collect/optical-modules", response_model=Dict[str, Any])
async def collect_switch_optical_modules(
    switch_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Manually collect optical module (SFP/QSFP) information from switch via SNMP or CLI"""
    try:
        # Verify switch exists
        result = await db.execute(
            select(Switch).where(Switch.id == switch_id)
        )
        switch = result.scalar_one_or_none()

        if not switch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Switch with ID {switch_id} not found"
            )

        logger.info(f"Manual optical module collection triggered for switch {switch.name} ({switch.ip_address})")

        collected_at = datetime.now(timezone.utc)
        modules = []
        collection_method = None

        # Try SNMP first if enabled
        if switch.snmp_enabled and switch.snmp_auth_password_encrypted:
            logger.info(f"Trying SNMP optical module collection for {switch.name}")
            try:
                snmp_config = {
                    'snmp_username': switch.snmp_username,
                    'snmp_auth_protocol': switch.snmp_auth_protocol,
                    'snmp_auth_password_encrypted': switch.snmp_auth_password_encrypted,
                    'snmp_priv_protocol': switch.snmp_priv_protocol,
                    'snmp_priv_password_encrypted': switch.snmp_priv_password_encrypted,
                    'snmp_port': switch.snmp_port
                }

                modules = await asyncio.wait_for(
                    snmp_service.collect_optical_modules(
                        str(switch.ip_address),
                        snmp_config
                    ),
                    timeout=60.0
                )

                if modules:
                    collection_method = 'SNMP'
                    logger.info(f"✅ Collected {len(modules)} optical modules via SNMP from {switch.name}")
                else:
                    logger.info(f"SNMP returned 0 modules, falling back to CLI for {switch.name}")

            except asyncio.TimeoutError:
                logger.warning(f"SNMP optical module collection timeout for {switch.name}, trying CLI")
            except Exception as e:
                logger.warning(f"SNMP optical module collection failed for {switch.name}: {str(e)}, trying CLI")

        # CLI fallback if SNMP didn't work or not enabled
        if not modules and switch.cli_enabled and switch.password_encrypted:
            logger.info(f"Trying CLI optical module collection for {switch.name}")
            try:
                cli_config = {
                    'username': switch.username,
                    'password_encrypted': switch.password_encrypted,
                    'enable_password_encrypted': switch.enable_password_encrypted,
                    'device_type': 'cisco_ios',
                    'ssh_port': switch.ssh_port,
                    'connection_timeout': switch.connection_timeout
                }

                # Set longer timeout for Alcatel/Nokia (needs to query each port individually)
                # Alcatel: 300s for 52 ports, Others: 90s
                timeout_seconds = 300.0 if switch.vendor and switch.vendor.lower() in ['alcatel', 'nokia'] else 90.0

                modules = await asyncio.wait_for(
                    asyncio.to_thread(
                        cli_service.collect_optical_modules_cli,
                        str(switch.ip_address),
                        cli_config,
                        switch.vendor or '',
                        switch.model or ''
                    ),
                    timeout=timeout_seconds
                )

                if modules:
                    collection_method = 'CLI'
                    logger.info(f"✅ Collected {len(modules)} optical modules via CLI from {switch.name}")

            except asyncio.TimeoutError:
                logger.error(f"CLI optical module collection timeout for {switch.name} after {timeout_seconds}s")
            except Exception as e:
                logger.error(f"CLI optical module collection failed for {switch.name}: {str(e)}")

        if not modules:
            return {
                'switch_id': switch_id,
                'switch_name': switch.name,
                'switch_ip': str(switch.ip_address),
                'total_modules': 0,
                'message': 'No optical modules found or device does not support optical module query',
                'collection_method': collection_method or 'None'
            }

        # Delete old entries for this switch
        await db.execute(
            OpticalModule.__table__.delete().where(OpticalModule.switch_id == switch_id)
        )

        # Insert new entries
        new_count = 0
        for module_data in modules:
            module = OpticalModule(
                switch_id=switch_id,
                switch_name=switch.name,  # Add denormalized switch_name
                switch_ip=switch.ip_address,  # Add denormalized switch_ip
                port_name=module_data['port_name'],
                module_type=module_data.get('module_type'),
                model=module_data.get('model'),
                part_number=module_data.get('part_number'),  # Add part_number
                serial_number=module_data.get('serial_number'),
                vendor=module_data.get('vendor'),
                speed_gbps=module_data.get('speed_gbps'),
                collected_at=collected_at,
                first_seen=collected_at,
                last_seen=collected_at
            )
            db.add(module)
            new_count += 1

        await db.commit()
        logger.info(f"Stored {new_count} optical modules for switch {switch.name}")

        return {
            'switch_id': switch_id,
            'switch_name': switch.name,
            'switch_ip': str(switch.ip_address),
            'total_modules': new_count,
            'message': f'Successfully collected {new_count} optical modules',
            'collection_method': collection_method,
            'collected_at': collected_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error collecting optical modules for switch {switch_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to collect optical modules: {str(e)}"
        )
