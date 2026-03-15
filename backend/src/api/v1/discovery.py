from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
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
import asyncio
import json
import uuid
import time
from sqlalchemy import select, cast, String
from sqlalchemy.dialects.postgresql import INET

router = APIRouter(prefix="/discovery", tags=["discovery"])

# Store discovered switches and progress
_discovery_cache = {}
_progress_queues = {}  # session_id -> asyncio.Queue


def _get_alcatel_model_via_cli(switch) -> str:
    """
    Connect to an Alcatel/Nokia switch via SSH, run 'show version',
    and extract the hardware model from 'Chassis Type' or 'System Type' field.
    Returns the model string or 'Unknown' on failure.
    Called synchronously in a thread pool executor.
    """
    try:
        from netmiko import ConnectHandler
        from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException
        from core.security import credential_encryption

        password = credential_encryption.decrypt(switch.password_encrypted)

        # Try Nokia SROS first, then Alcatel AOS
        device_types = ['nokia_sros', 'alcatel_aos', 'nokia_srlinux']

        for device_type in device_types:
            try:
                conn_params = {
                    'device_type': device_type,
                    'host': str(switch.ip_address),
                    'username': switch.username,
                    'password': password,
                    'port': switch.ssh_port or 22,
                    'timeout': 15,
                    'conn_timeout': 15,
                    'allow_agent': False,
                    'use_keys': False,
                    'ssh_strict': False,
                }
                with ConnectHandler(**conn_params) as conn:
                    output = conn.send_command('show version', read_timeout=15)
                    for line in output.splitlines():
                        ll = line.lower()
                        if ('chassis type' in ll or 'system type' in ll) and ':' in line:
                            parts = line.split(':', 1)
                            if len(parts) == 2 and parts[1].strip():
                                return parts[1].strip()
                        if 'product name' in ll and ':' in line:
                            parts = line.split(':', 1)
                            if len(parts) == 2 and parts[1].strip():
                                return parts[1].strip()
            except (NetmikoTimeoutException, NetmikoAuthenticationException):
                continue
            except Exception:
                continue

        return 'Unknown'

    except Exception:
        return 'Unknown'


@router.post("/scan", response_model=SwitchDiscoveryResponse)
async def discover_switches(
    request: SwitchDiscoveryRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Scan an IP range to discover switches

    This endpoint will:
    1. Scan the specified IP range
    2. Try each credential set on each IP (with retry)
    3. Detect vendor, model, and role automatically
    4. Return list of discovered switches
    """
    try:
        logger.info(f"Starting switch discovery for range: {request.ip_range}")

        # Validate IP range format before proceeding
        try:
            temp_service = switch_discovery_service
            ip_list = temp_service._parse_ip_range(request.ip_range)
            if not ip_list:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="无法解析 IP 范围，请检查输入格式。支持格式：10.0.0.1-50、10.0.0.1-10.0.0.50 或 10.0.0.0/24"
                )
            total_scanned = len(ip_list)
            logger.info(f"Valid IP range: {total_scanned} addresses to scan")
        except ValueError as e:
            logger.error(f"Invalid IP range format: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        # Validate credentials
        if not request.credentials or len(request.credentials) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="至少需要提供一组认证信息"
            )

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

        # Validate at least one credential has username and password
        valid_creds = [c for c in credentials if c.get('username') and c.get('password')]
        if not valid_creds:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="至少需要一组完整的用户名和密码"
            )

        # Perform discovery
        discovered = await switch_discovery_service.discover_switches(
            request.ip_range,
            valid_creds
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
                ssh_port=sw['ssh_port'],
                username=sw['username']
            )
            for sw in discovered
        ]

        logger.info(f"Discovery completed: {len(discovered)} switches found out of {total_scanned} IPs")

        return SwitchDiscoveryResponse(
            total_scanned=total_scanned,
            discovered=len(discovered),
            switches=switches_response
        )

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except ValueError as e:
        # Handle validation errors from service layer
        logger.error(f"Validation error during switch discovery: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error during switch discovery: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"扫描交换机时发生错误，请检查网络连接和认证信息"
        )


@router.post("/scan-stream")
async def discover_switches_stream(
    request: SwitchDiscoveryRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Scan switches with real-time progress updates via SSE
    Returns a session_id for connecting to the progress stream
    """
    try:
        # Validate IP range
        try:
            temp_service = switch_discovery_service
            ip_list = temp_service._parse_ip_range(request.ip_range)
            if not ip_list:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="无法解析 IP 范围，请检查输入格式"
                )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        # Validate credentials
        credentials = [
            {
                'username': cred.username,
                'password': cred.password,
                'enable_password': cred.enable_password,
                'port': cred.port
            }
            for cred in request.credentials
        ]
        
        valid_creds = [c for c in credentials if c.get('username') and c.get('password')]
        if not valid_creds:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="至少需要一组完整的用户名和密码"
            )

        # Create session
        session_id = str(uuid.uuid4())
        progress_queue = asyncio.Queue()
        _progress_queues[session_id] = progress_queue

        # Start discovery in background
        async def run_discovery():
            try:
                # Convert snmp_config to dict if provided
                snmp_config_dict = None
                if request.snmp_config:
                    snmp_config_dict = {
                        'snmp_version': request.snmp_config.snmp_version,
                        'snmp_port': request.snmp_config.snmp_port,
                        'snmp_username': request.snmp_config.snmp_username,
                        'snmp_auth_protocol': request.snmp_config.snmp_auth_protocol,
                        'snmp_auth_password': request.snmp_config.snmp_auth_password,
                        'snmp_priv_protocol': request.snmp_config.snmp_priv_protocol,
                        'snmp_priv_password': request.snmp_config.snmp_priv_password,
                        'snmp_community': request.snmp_config.snmp_community,
                    }

                discovered = await switch_discovery_service.discover_switches(
                    request.ip_range,
                    valid_creds,
                    session_id=session_id,
                    progress_queue=progress_queue,
                    snmp_config=snmp_config_dict
                )

                # Store results in cache (for the REST fallback endpoint)
                _discovery_cache[session_id] = discovered

                # Embed switch list directly in the 'complete' event so the frontend
                # doesn't need a separate REST fetch — eliminates the race condition.
                switches_payload = [
                    {
                        'ip_address': sw['ip_address'],
                        'name': sw.get('name', sw['ip_address']),
                        'vendor': sw.get('vendor', 'unknown'),
                        'model': sw.get('model', 'Unknown'),
                        'ssh_port': sw.get('ssh_port', 22),
                        'username': sw.get('username', ''),
                    }
                    for sw in discovered
                ]
                await progress_queue.put({
                    'type': 'complete',
                    'total_found': len(discovered),
                    'total_scanned': len(discovered),
                    'session_id': session_id,
                    'switches': switches_payload,
                })
                
            except Exception as e:
                logger.error(f"Error in background discovery: {str(e)}", exc_info=True)
                await progress_queue.put({'type': 'error', 'message': str(e)})

        # Start discovery task
        asyncio.create_task(run_discovery())
        
        return {"session_id": session_id, "status": "started"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting scan stream: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/progress/{session_id}")
async def get_scan_progress(session_id: str):
    """
    Stream scan progress via Server-Sent Events
    """
    if session_id not in _progress_queues:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    progress_queue = _progress_queues[session_id]
    
    async def event_generator():
        try:
            while True:
                # Get progress event from queue
                event = await progress_queue.get()
                
                # Send SSE formatted message
                yield f"data: {json.dumps(event)}\n\n"
                
                # Check if scan is complete
                if event.get('type') in ['done', 'error', 'complete']:
                    break
                    
        except asyncio.CancelledError:
            logger.info(f"Progress stream cancelled for session {session_id}")
        finally:
            # Cleanup
            if session_id in _progress_queues:
                del _progress_queues[session_id]
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/result/{session_id}", response_model=SwitchDiscoveryResponse)
async def get_scan_result(session_id: str):
    """
    Get the final scan result after completion
    """
    if session_id not in _discovery_cache:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="扫描结果未找到或已过期"
        )
    
    discovered = _discovery_cache[session_id]
    
    # Convert to response format
    switches_response = [
        DiscoveredSwitch(
            ip_address=sw['ip_address'],
            name=sw['name'],
            vendor=sw['vendor'],
            model=sw['model'],
            ssh_port=sw['ssh_port'],
            username=sw['username']
        )
        for sw in discovered
    ]

    # Calculate total scanned (from cached data or estimate)
    total_scanned = len(discovered)  # This is a simplification

    return SwitchDiscoveryResponse(
        total_scanned=total_scanned,
        discovered=len(discovered),
        switches=switches_response
    )


@router.get("/refresh-hostnames")
async def refresh_all_hostnames(db: AsyncSession = Depends(get_db)):
    """
    Refresh hostnames for all enabled switches using SNMP only
    Returns real-time progress via Server-Sent Events (SSE)
    """
    async def generate_progress():
        try:
            logger.info("Starting hostname refresh for all switches")

            # Get all enabled switches with SNMP configured
            result = await db.execute(
                select(Switch).where(
                    Switch.enabled == True,
                    Switch.snmp_enabled == True,
                    Switch.snmp_auth_password_encrypted.isnot(None)
                )
            )
            switches = list(result.scalars().all())
            total = len(switches)

            if total == 0:
                yield f"data: {json.dumps({'type': 'complete', 'total': 0, 'updated': 0, 'failed': 0, 'results': []})}\n\n"
                return

            # Send initial start event
            yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"

            updated_count = 0
            failed_count = 0
            results = []
            start_time = time.time()

            # Import SNMP service
            from services.snmp_service import snmp_service

            for index, switch in enumerate(switches, 1):
                current_time = time.time()
                elapsed = current_time - start_time
                avg_time_per_switch = elapsed / index if index > 0 else 0
                remaining_switches = total - index
                estimated_remaining_time = int(avg_time_per_switch * remaining_switches)

                # Send progress update before processing
                progress_data = {
                    'type': 'progress',
                    'current': index,
                    'total': total,
                    'current_switch': {
                        'name': switch.name,
                        'ip': str(switch.ip_address)
                    },
                    'completed': index - 1,
                    'updated': updated_count,
                    'failed': failed_count,
                    'estimated_remaining_seconds': estimated_remaining_time
                }
                yield f"data: {json.dumps(progress_data)}\n\n"

                try:
                    hostname = None
                    error_detail = None

                    # Use SNMP only (no SSH fallback)
                    if switch.snmp_auth_password_encrypted:
                        try:
                            snmp_config = {
                                'snmp_username': switch.snmp_username,
                                'snmp_auth_protocol': switch.snmp_auth_protocol,
                                'snmp_auth_password_encrypted': switch.snmp_auth_password_encrypted,
                                'snmp_priv_protocol': switch.snmp_priv_protocol,
                                'snmp_priv_password_encrypted': switch.snmp_priv_password_encrypted,
                                'snmp_port': switch.snmp_port or 161
                            }
                            hostname = await snmp_service.get_hostname(str(switch.ip_address), snmp_config)

                            if hostname:
                                logger.info(f"Got hostname for {switch.ip_address} via SNMP: {hostname}")
                            else:
                                error_detail = 'SNMP GET returned None (timeout or no response)'
                        except Exception as e:
                            error_detail = f'SNMP error: {str(e)}'
                            logger.error(f"SNMP hostname fetch failed for {switch.ip_address}: {str(e)}")
                    else:
                        error_detail = 'No SNMP credentials configured'

                    # Update switch if hostname was obtained
                    if hostname and hostname != str(switch.ip_address):
                        old_name = switch.name
                        switch.name = hostname
                        updated_count += 1
                        results.append({
                            'ip': str(switch.ip_address),
                            'old_name': old_name,
                            'new_name': hostname,
                            'method': 'snmp',
                            'status': 'updated'
                        })
                        logger.info(f"Updated hostname for {switch.ip_address}: {old_name} -> {hostname}")
                    elif hostname:
                        results.append({
                            'ip': str(switch.ip_address),
                            'name': switch.name,
                            'method': 'snmp',
                            'status': 'unchanged'
                        })
                    else:
                        failed_count += 1
                        results.append({
                            'ip': str(switch.ip_address),
                            'name': switch.name,
                            'status': 'failed',
                            'error': error_detail or 'Could not retrieve hostname via SNMP'
                        })

                except Exception as e:
                    failed_count += 1
                    results.append({
                        'ip': str(switch.ip_address),
                        'name': switch.name,
                        'status': 'failed',
                        'error': str(e)
                    })
                    logger.error(f"Failed to refresh hostname for {switch.ip_address}: {str(e)}")

            # Commit all changes
            await db.commit()

            logger.info(f"Hostname refresh complete: {updated_count} updated, {failed_count} failed")

            # Send final complete event
            final_data = {
                'type': 'complete',
                'total': total,
                'updated': updated_count,
                'failed': failed_count,
                'results': results,
                'elapsed_seconds': int(time.time() - start_time)
            }
            yield f"data: {json.dumps(final_data)}\n\n"

        except Exception as e:
            await db.rollback()
            logger.error(f"Error refreshing hostnames: {str(e)}", exc_info=True)
            error_data = {
                'type': 'error',
                'error': str(e)
            }
            yield f"data: {json.dumps(error_data)}\n\n"

    return StreamingResponse(
        generate_progress(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/refresh-device-info")
async def refresh_all_device_info(db: AsyncSession = Depends(get_db)):
    """
    Refresh hostname, vendor, and model for all SNMP-enabled switches via SNMP.
    Uses sysName, sysDescr, and sysObjectID OIDs.
    Returns real-time progress via Server-Sent Events (SSE).
    """
    async def generate_progress():
        try:
            logger.info("Starting device info refresh for all switches")

            result = await db.execute(
                select(Switch).where(
                    Switch.enabled == True,
                    Switch.snmp_enabled == True,
                    Switch.snmp_auth_password_encrypted.isnot(None)
                )
            )
            switches = list(result.scalars().all())
            total = len(switches)

            if total == 0:
                yield f"data: {json.dumps({'type': 'complete', 'total': 0, 'updated': 0, 'failed': 0, 'results': []})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"

            from services.snmp_service import snmp_service
            from services.switch_discovery import switch_discovery_service

            updated_count = 0
            failed_count = 0
            results = []
            start_time = time.time()

            for index, switch in enumerate(switches, 1):
                elapsed = time.time() - start_time
                avg_per_switch = elapsed / index if index > 0 else 0
                estimated_remaining = int(avg_per_switch * (total - index))

                progress_data = {
                    'type': 'progress',
                    'current': index,
                    'total': total,
                    'current_switch': {'name': switch.name, 'ip': str(switch.ip_address)},
                    'completed': index - 1,
                    'updated': updated_count,
                    'failed': failed_count,
                    'estimated_remaining_seconds': estimated_remaining
                }
                yield f"data: {json.dumps(progress_data)}\n\n"

                try:
                    snmp_config = {
                        'snmp_username': switch.snmp_username,
                        'snmp_auth_protocol': switch.snmp_auth_protocol,
                        'snmp_auth_password_encrypted': switch.snmp_auth_password_encrypted,
                        'snmp_priv_protocol': switch.snmp_priv_protocol,
                        'snmp_priv_password_encrypted': switch.snmp_priv_password_encrypted,
                        'snmp_port': switch.snmp_port or 161
                    }

                    device_info = await snmp_service.get_device_info(
                        str(switch.ip_address), snmp_config
                    )

                    if device_info:
                        changes = {}

                        # Update hostname/name
                        hostname = device_info.get('hostname')
                        if hostname and hostname != str(switch.ip_address):
                            if switch.name != hostname:
                                changes['name'] = (switch.name, hostname)
                                switch.name = hostname

                        # Use vendor detection from switch_discovery_service
                        sys_object_id = device_info.get('sys_object_id')
                        sys_descr = device_info.get('sys_descr')

                        vendor = switch_discovery_service._detect_vendor_from_oid(sys_object_id)
                        if not vendor and sys_descr:
                            vendor = switch_discovery_service._detect_vendor_from_descr(sys_descr)

                        if vendor and vendor != 'unknown' and switch.vendor != vendor:
                            changes['vendor'] = (switch.vendor, vendor)
                            switch.vendor = vendor

                        # Extract model from sysDescr using SNMP-specific parser
                        if sys_descr:
                            current_vendor = vendor or switch.vendor
                            model = switch_discovery_service._extract_model_from_sysdescr(sys_descr, current_vendor)
                            if model and model != 'Unknown' and switch.model != model:
                                changes['model'] = (switch.model, model)
                                switch.model = model

                        # If sysDescr gave us nothing useful, try ENTITY-MIB chassis description.
                        # Nokia SR Linux sysDescr often only has OS version; the hardware model
                        # (e.g. "Nokia 7220 IXR-D2") is available in entPhysicalDescr[chassis].
                        entity_phys_descr = device_info.get('entity_phys_descr')
                        current_model = switch.model
                        if (entity_phys_descr
                                and current_model in (None, '', 'Unknown', 'unknown', 'SR Linux')
                                and 'model' not in changes):
                            current_vendor = vendor or switch.vendor
                            entity_model = switch_discovery_service._extract_model_from_sysdescr(
                                entity_phys_descr, current_vendor
                            )
                            if entity_model and entity_model not in ('Unknown', 'SR Linux'):
                                changes['model'] = (switch.model, entity_model)
                                switch.model = entity_model
                                logger.info(
                                    f"Got model from ENTITY-MIB for {switch.ip_address}: {entity_model}"
                                )

                        # SSH fallback for Alcatel: if model still Unknown and CLI enabled,
                        # run "show version" and parse Chassis Type / System Type
                        current_vendor_for_ssh = vendor or switch.vendor
                        if (switch.model in (None, '', 'Unknown', 'unknown')
                                and 'model' not in changes
                                and current_vendor_for_ssh == 'alcatel'
                                and switch.cli_enabled
                                and switch.password_encrypted):
                            try:
                                cli_model = await asyncio.get_event_loop().run_in_executor(
                                    None,
                                    _get_alcatel_model_via_cli,
                                    switch
                                )
                                if cli_model and cli_model != 'Unknown':
                                    changes['model'] = (switch.model, cli_model)
                                    switch.model = cli_model
                                    logger.info(f"Got Alcatel model via CLI for {switch.ip_address}: {cli_model}")
                            except Exception as cli_err:
                                logger.debug(f"CLI model fallback failed for {switch.ip_address}: {cli_err}")

                        if changes:
                            updated_count += 1
                            results.append({
                                'ip': str(switch.ip_address),
                                'name': switch.name,
                                'changes': {k: {'from': v[0], 'to': v[1]} for k, v in changes.items()},
                                'status': 'updated'
                            })
                            logger.info(f"Updated device info for {switch.ip_address}: {changes}")
                        else:
                            results.append({
                                'ip': str(switch.ip_address),
                                'name': switch.name,
                                'status': 'unchanged'
                            })
                    else:
                        failed_count += 1
                        results.append({
                            'ip': str(switch.ip_address),
                            'name': switch.name,
                            'status': 'failed',
                            'error': 'SNMP 无响应或认证失败'
                        })

                except Exception as e:
                    failed_count += 1
                    results.append({
                        'ip': str(switch.ip_address),
                        'name': switch.name,
                        'status': 'failed',
                        'error': str(e)
                    })
                    logger.error(f"Device info refresh failed for {switch.ip_address}: {str(e)}")

            await db.commit()
            logger.info(f"Device info refresh complete: {updated_count} updated, {failed_count} failed")

            final_data = {
                'type': 'complete',
                'total': total,
                'updated': updated_count,
                'failed': failed_count,
                'results': results,
                'elapsed_seconds': int(time.time() - start_time)
            }
            yield f"data: {json.dumps(final_data)}\n\n"

        except Exception as e:
            await db.rollback()
            logger.error(f"Error refreshing device info: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        generate_progress(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/batch-add", response_model=List[SwitchResponse])
async def batch_add_switches(
    discovered_switches: List[SwitchCreate],
    db: AsyncSession = Depends(get_db)
):
    """
    Batch add discovered switches to the database
    """
    try:
        logger.info(f"Batch-add request received with {len(discovered_switches) if discovered_switches else 0} switches")

        if not discovered_switches or len(discovered_switches) == 0:
            logger.warning("Batch-add called with empty switch list")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="没有要添加的交换机"
            )

        added_switches = []
        skipped_count = 0
        batch_ips = set()  # Track IPs in current batch to detect duplicates
        logger.info(f"Starting to process {len(discovered_switches)} switches for batch add")

        for idx, switch_data in enumerate(discovered_switches, 1):
            try:
                # Check for duplicate in current batch
                if str(switch_data.ip_address) in batch_ips:
                    logger.warning(f"Switch {switch_data.ip_address} appears multiple times in batch, skipping duplicate")
                    skipped_count += 1
                    continue

                # Check if switch already exists - use cast to ensure type compatibility
                result = await db.execute(
                    select(Switch).where(
                        cast(Switch.ip_address, String) == str(switch_data.ip_address)
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    logger.warning(f"Switch {switch_data.ip_address} already exists, skipping")
                    skipped_count += 1
                    continue

                # Add to batch tracking
                batch_ips.add(str(switch_data.ip_address))

                # Encrypt credentials
                password_encrypted = credential_encryption.encrypt(switch_data.password)
                enable_password_encrypted = None
                if switch_data.enable_password:
                    enable_password_encrypted = credential_encryption.encrypt(switch_data.enable_password)

                # Encrypt SNMP credentials
                snmp_auth_password_encrypted = None
                snmp_priv_password_encrypted = None
                if switch_data.snmp_auth_password:
                    snmp_auth_password_encrypted = credential_encryption.encrypt(switch_data.snmp_auth_password)
                if switch_data.snmp_priv_password:
                    snmp_priv_password_encrypted = credential_encryption.encrypt(switch_data.snmp_priv_password)

                # Create switch - IP will be stored as INET type
                switch = Switch(
                    name=switch_data.name,
                    ip_address=str(switch_data.ip_address),  # SQLAlchemy will convert to INET
                    vendor=switch_data.vendor,
                    model=switch_data.model,
                    ssh_port=switch_data.ssh_port,
                    username=switch_data.username,
                    password_encrypted=password_encrypted,
                    enable_password_encrypted=enable_password_encrypted,
                    enabled=switch_data.enabled,
                    connection_timeout=switch_data.connection_timeout,
                    cli_enabled=switch_data.cli_enabled,
                    auto_collect_arp=switch_data.auto_collect_arp,
                    auto_collect_mac=switch_data.auto_collect_mac,
                    snmp_enabled=switch_data.snmp_enabled,
                    snmp_version=switch_data.snmp_version,
                    snmp_port=switch_data.snmp_port,
                    snmp_username=switch_data.snmp_username,
                    snmp_auth_protocol=switch_data.snmp_auth_protocol,
                    snmp_auth_password_encrypted=snmp_auth_password_encrypted,
                    snmp_priv_protocol=switch_data.snmp_priv_protocol,
                    snmp_priv_password_encrypted=snmp_priv_password_encrypted,
                    snmp_community=switch_data.snmp_community,
                )

                db.add(switch)
                added_switches.append(switch)
                
            except Exception as e:
                logger.error(f"Error processing switch {switch_data.ip_address}: {str(e)}")
                # Continue with other switches even if one fails
                continue

        # Commit all successful additions
        if added_switches:
            try:
                await db.commit()

                # Refresh all switches to get IDs
                for switch in added_switches:
                    await db.refresh(switch)

            except Exception as commit_error:
                # Handle duplicate key errors gracefully
                if "duplicate key" in str(commit_error).lower() or "unique constraint" in str(commit_error).lower():
                    logger.warning(f"Some switches were already added by another process, attempting individual commits")
                    await db.rollback()

                    # Try to commit switches individually
                    successfully_added = []
                    for switch in added_switches:
                        try:
                            db.add(switch)
                            await db.commit()
                            await db.refresh(switch)
                            successfully_added.append(switch)
                        except Exception as individual_error:
                            if "duplicate key" in str(individual_error).lower():
                                logger.warning(f"Switch {switch.ip_address} was already added, skipping")
                                await db.rollback()
                                skipped_count += 1
                            else:
                                logger.error(f"Error committing switch {switch.ip_address}: {str(individual_error)}")
                                await db.rollback()

                    added_switches = successfully_added
                else:
                    # Re-raise if it's not a duplicate key error
                    raise

        message = f"成功添加 {len(added_switches)} 个交换机"
        if skipped_count > 0:
            message += f"，跳过 {skipped_count} 个已存在的交换机"
        logger.info(message)
        
        return added_switches

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error batch adding switches: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"批量添加交换机失败: {str(e)}"
        )
