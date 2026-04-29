from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, or_, and_, cast, String, case, delete
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
from services.snmp_service import snmp_service
from services.port_analysis_service import port_analysis_service
from services.port_lookup_policy_service import build_lookup_eligible_clause
from services.data_freshness_service import (
    build_optical_inventory_freshness,
    build_optical_module_freshness,
)
from services.network_data_collector import network_data_collector
from services.status_checker import switch_status_checker
from utils.logger import logger
from utils.network import ping_host, ping_multiple_hosts

router = APIRouter(prefix="/switches", tags=["switches"])


def _is_usable_arp_interface(interface_name: str | None) -> bool:
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


def _normalize_cli_transport_and_port(
    transport: str | None,
    port: int | None,
    *,
    port_was_explicit: bool
) -> tuple[str, int]:
    """Keep CLI transport and port defaults consistent across API entry points."""
    return cli_service.normalize_cli_connection_settings(
        transport,
        port,
        port_was_explicit=port_was_explicit
    )


@router.get("/status-checker", response_model=Dict[str, Any])
async def get_status_checker_status():
    """Get lightweight switch reachability checker runtime status."""
    return switch_status_checker.get_status()


@router.post("/status-checker/run", response_model=Dict[str, Any])
async def run_status_checker_once():
    """Manually trigger one lightweight reachability sweep."""
    return await switch_status_checker.check_all_switches()


@router.post("", response_model=SwitchResponse, status_code=status.HTTP_201_CREATED)
async def create_switch(
    switch_data: SwitchCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new switch with SNMP authentication"""
    try:
        cli_transport, ssh_port = _normalize_cli_transport_and_port(
            switch_data.cli_transport,
            switch_data.ssh_port,
            port_was_explicit='ssh_port' in switch_data.model_fields_set
        )

        # Check if switch with same IP already exists
        result = await db.execute(
            select(Switch).where(Switch.ip_address == switch_data.ip_address)
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
            if switch_data.snmp_priv_password:
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
            enabled=switch_data.enabled,
            
            # SSH fields (optional)
            cli_enabled=switch_data.cli_enabled,
            cli_transport=cli_transport,
            ssh_port=ssh_port,
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
            snmp_priv_protocol=switch_data.snmp_priv_protocol if switch_data.snmp_priv_password else None,
            snmp_priv_password_encrypted=snmp_priv_password_encrypted,
            snmp_community=switch_data.snmp_community
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
    trunk_review_completed: bool | None = Query(None),
    sort_by: str = Query("id"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
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

        if trunk_review_completed is not None:
            query = query.where(Switch.trunk_review_completed == trunk_review_completed)

        # Get total count
        count_query = select(Switch.id)
        if search:
            count_query = count_query.where(search_filter)
        if trunk_review_completed is not None:
            count_query = count_query.where(Switch.trunk_review_completed == trunk_review_completed)
        count_result = await db.execute(count_query)
        total = len(count_result.all())

        collection_time_expr = func.coalesce(
            func.greatest(
                Switch.last_arp_collection_at,
                Switch.last_mac_collection_at,
                Switch.last_optical_collection_at
            ),
            Switch.last_arp_collection_at,
            Switch.last_mac_collection_at,
            Switch.last_optical_collection_at
        )
        connection_status_expr = case(
            (Switch.is_reachable == False, 0),
            (Switch.is_reachable.is_(None), 1),
            else_=2
        )

        sort_columns = {
            "id": Switch.id,
            "name": Switch.name,
            "ip_address": Switch.ip_address,
            "model": Switch.model,
            "last_collection_time": collection_time_expr,
            "connection_status": connection_status_expr,
        }
        sort_expr = sort_columns.get(sort_by, Switch.id)
        ordered_expr = sort_expr.desc() if sort_order == "desc" else sort_expr.asc()
        query = query.order_by(ordered_expr.nulls_last(), Switch.name.asc(), Switch.id.asc())

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
            update_data['snmp_priv_password_encrypted'] = None
            update_data['snmp_priv_protocol'] = None

        if 'snmp_community' in update_data and update_data['snmp_community']:
            # Store community in auth_password field for v2c
            update_data['snmp_auth_password_encrypted'] = credential_encryption.encrypt(update_data.pop('snmp_community'))
        elif 'snmp_community' in update_data:
            update_data.pop('snmp_community')

        if update_data.get('snmp_version') == '2c':
            update_data['snmp_username'] = None
            update_data['snmp_auth_protocol'] = None
            update_data['snmp_priv_protocol'] = None
            update_data['snmp_priv_password_encrypted'] = None
        elif update_data.get('snmp_version') == '3':
            if (
                'snmp_priv_protocol' in update_data and
                'snmp_priv_password_encrypted' not in update_data and
                not switch.snmp_priv_password_encrypted
            ):
                update_data['snmp_priv_protocol'] = None

        if 'trunk_review_completed' in update_data:
            update_data['trunk_review_completed_at'] = (
                datetime.now(timezone.utc) if update_data['trunk_review_completed'] else None
            )

        transport_updated = 'cli_transport' in switch_data.model_fields_set
        port_updated = 'ssh_port' in switch_data.model_fields_set
        if transport_updated or port_updated:
            cli_transport, ssh_port = _normalize_cli_transport_and_port(
                update_data.get('cli_transport', switch.cli_transport),
                update_data.get('ssh_port'),
                port_was_explicit=port_updated
            )
            update_data['cli_transport'] = cli_transport
            update_data['ssh_port'] = ssh_port

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
                if priv_password:
                    priv_proto = priv_map.get(switch.snmp_priv_protocol, usmAesCfb128Protocol)
                    auth_data = UsmUserData(
                        switch.snmp_username,
                        authKey=auth_password,
                        privKey=priv_password,
                        authProtocol=auth_proto,
                        privProtocol=priv_proto
                    )
                else:
                    auth_data = UsmUserData(
                        switch.snmp_username,
                        authKey=auth_password,
                        authProtocol=auth_proto
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
            ping_result = await ping_host(str(switch.ip_address), timeout=5)
            is_reachable = ping_result["reachable"]
            response_time = ping_result.get("response_time_ms")
            
            if is_reachable:
                return SwitchTestResponse(
                    success=True,
                    message=f"Switch is reachable (ping: {response_time:.2f}ms)" if response_time is not None else "Switch is reachable",
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
            cli_transport, ssh_port = _normalize_cli_transport_and_port(
                switch_data.cli_transport,
                switch_data.ssh_port,
                port_was_explicit='ssh_port' in switch_data.model_fields_set
            )

            # Check if switch with same IP already exists
            result = await db.execute(
                select(Switch).where(Switch.ip_address == switch_data.ip_address)
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
                if switch_data.snmp_priv_password:
                    snmp_priv_password_encrypted = credential_encryption.encrypt(switch_data.snmp_priv_password)
            elif switch_data.snmp_version == '2c' and switch_data.snmp_community:
                snmp_auth_password_encrypted = credential_encryption.encrypt(switch_data.snmp_community)

            # Create switch
            switch = Switch(
                name=switch_data.name,
                ip_address=str(switch_data.ip_address),
                vendor=switch_data.vendor,
                model=switch_data.model,
                cli_enabled=switch_data.cli_enabled,
                cli_transport=cli_transport,
                ssh_port=ssh_port,
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
                snmp_priv_protocol=switch_data.snmp_priv_protocol if switch_data.snmp_priv_password else None,
                snmp_priv_password_encrypted=snmp_priv_password_encrypted,
                snmp_community=switch_data.snmp_community
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

        mac_result = await db.execute(
            select(MACTable)
            .where(MACTable.switch_id == switch_id)
            .order_by(desc(MACTable.last_seen))
        )
        latest_mac_by_address = {}
        for mac_entry in mac_result.scalars():
            mac_key = str(mac_entry.mac_address).lower()
            if mac_key not in latest_mac_by_address:
                latest_mac_by_address[mac_key] = mac_entry

        # Format response
        entries = []
        for entry in arp_entries:
            resolved_mac_entry = latest_mac_by_address.get(str(entry.mac_address).lower())
            display_interface = None
            interface_source = 'unknown'
            if resolved_mac_entry:
                display_interface = resolved_mac_entry.port_name
                interface_source = 'mac_table'
            elif _is_usable_arp_interface(entry.interface):
                display_interface = entry.interface
                interface_source = 'arp_table'

            entries.append({
                'id': entry.id,
                'ip_address': str(entry.ip_address),
                'mac_address': str(entry.mac_address),
                'vlan_id': entry.vlan_id,
                'interface': display_interface,
                'raw_interface': entry.interface,
                'interface_source': interface_source,
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

        # Get MAC entries that are currently eligible for endpoint/device lookup.
        # Raw MAC collection remains unchanged; this only filters the displayed
        # set to honor manual lookup policy overrides and the shared auto policy.

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
            .where(build_lookup_eligible_clause(PortAnalysis))
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
    """Manually collect ARP table from switch via the global CLI-only policy."""
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
            'cli_transport': switch.cli_transport,
            'ssh_port': switch.ssh_port,
            'connection_timeout': switch.connection_timeout
        }

        arp_entries = []
        collection_method = None

        from config.collection_strategy import CollectionStrategy

        logger.info(
            f"Collecting ARP via {CollectionStrategy.get_l2_table_primary_method()} for {switch.name}"
        )
        if switch.cli_enabled and switch.password_encrypted:
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
        else:
            logger.warning(f"CLI ARP collection skipped for {switch.name}: CLI credentials are not configured")

        if not arp_entries:
            return {
                'switch_id': switch_id,
                'switch_name': switch.name,
                'switch_ip': str(switch.ip_address),
                'total_entries': 0,
                'collection_method': None,
                'message': 'Failed to collect ARP table via CLI (global policy)',
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
    """Manually collect MAC table from switch via the global CLI-only policy."""
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
            'cli_transport': switch.cli_transport,
            'ssh_port': switch.ssh_port,
            'connection_timeout': switch.connection_timeout
        }

        mac_entries = []
        collection_method = None

        from config.collection_strategy import CollectionStrategy

        logger.info(
            f"Collecting MAC via {CollectionStrategy.get_l2_table_primary_method()} for {switch.name}"
        )
        if switch.cli_enabled and switch.password_encrypted:
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
        else:
            logger.warning(f"CLI MAC collection skipped for {switch.name}: CLI credentials are not configured")

        if not mac_entries:
            return {
                'switch_id': switch_id,
                'switch_name': switch.name,
                'switch_ip': str(switch.ip_address),
                'total_entries': 0,
                'collection_method': None,
                'message': 'Failed to collect MAC table via CLI (global policy)',
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
            'enable_password_encrypted': switch.enable_password_encrypted,
            'vendor': switch.vendor,
            'model': switch.model,
            'name': switch.name,
            'cli_transport': switch.cli_transport,
            'ssh_port': switch.ssh_port,
            'connection_timeout': switch.connection_timeout
        }
        cli_config['device_type'] = cli_service._resolve_device_type(
            switch.vendor or '',
            switch.model or '',
            switch.name or ''
        )

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
    1. Collects MAC table from the switch via the global CLI-only policy
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

        # Reuse the same MAC collection path as the scheduled worker pool so the
        # manual "analyze ports" action behaves the same way as automatic runs.
        mac_entries = await network_data_collector.collect_mac_single_switch(db, switch)
        if not mac_entries:
            return {
                'switch_id': switch_id,
                'switch_ip': str(switch.ip_address),
                'switch_name': switch.name,
                'success': False,
                'message': switch.last_collection_message or 'No MAC entries collected.',
                'ports_analyzed': 0,
                'collection_methods_tried': ['CLI'] if switch.cli_enabled else []
            }

        await db.commit()

        refreshed_result = await db.execute(
            select(PortAnalysis.port_type, func.count(PortAnalysis.id))
            .where(PortAnalysis.switch_id == switch_id)
            .group_by(PortAnalysis.port_type)
        )
        port_types_summary = {row[0]: row[1] for row in refreshed_result.all()}
        total_ports = sum(port_types_summary.values())

        logger.info(
            f"✅ Port analysis refreshed for {switch.name}: "
            f"{total_ports} ports available after MAC snapshot update"
        )

        return {
            'switch_id': switch_id,
            'switch_ip': str(switch.ip_address),
            'switch_name': switch.name,
            'success': True,
            'message': f"Successfully refreshed port analysis from latest MAC snapshot ({total_ports} ports)",
            'ports_analyzed': total_ports,
            'mac_entries_collected': len(mac_entries),
            'port_types_summary': port_types_summary,
            'analyzed_at': datetime.now(timezone.utc).isoformat()
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

        freshness = build_optical_inventory_freshness(switch)

        # Format response
        entries = []
        present_modules = 0
        for module in modules:
            module_freshness = build_optical_module_freshness(switch, module.last_seen)
            if module_freshness["is_present"]:
                present_modules += 1

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
                'last_seen': module.last_seen.isoformat() if module.last_seen else None,
                'presence_status': module_freshness["presence_status"],
                'is_present': module_freshness["is_present"],
                'freshness_status': module_freshness["status"],
                'freshness_warning': module_freshness["warning"],
            })

        return {
            'switch_id': switch_id,
            'switch_name': switch.name,
            'switch_ip': str(switch.ip_address),
            'total_modules': len(entries),
            'present_modules': present_modules,
            'historical_modules': len(entries) - present_modules,
            'freshness': freshness,
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

        modules = await network_data_collector.collect_optical_single_switch(db, switch)
        await db.commit()
        await db.refresh(switch)

        return {
            'switch_id': switch_id,
            'switch_name': switch.name,
            'switch_ip': str(switch.ip_address),
            'total_modules': len(modules),
            'message': switch.last_optical_collection_message or 'Optical collection completed',
            'collection_method': switch.optical_collection_method,
            'collection_status': switch.last_optical_collection_status,
            'collected_at': switch.last_optical_collection_at.isoformat() if switch.last_optical_collection_at else None,
            'historical_inventory_preserved': True
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error collecting optical modules for switch {switch_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to collect optical modules: {str(e)}"
        )
