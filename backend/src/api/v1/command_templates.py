"""
API endpoints for Switch Command Templates
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Literal
from api.deps import get_db
from models.switch_command_template import SwitchCommandTemplate
from schemas.switch_command_template import (
    SwitchCommandTemplateCreate,
    SwitchCommandTemplateUpdate,
    SwitchCommandTemplateResponse
)
from utils.logger import logger
from pydantic import BaseModel

router = APIRouter(prefix="/command-templates", tags=["command-templates"])


class ParserInfo(BaseModel):
    """Parser information"""
    type: str
    name: str
    description: str


class DeviceTypeInfo(BaseModel):
    """Supported Netmiko device type information"""
    type: str
    name: str
    description: str


class CommandTemplateOptionsResponse(BaseModel):
    """Supported device types and parser types for command templates"""
    device_types: List[DeviceTypeInfo]
    arp: List[ParserInfo]
    mac: List[ParserInfo]
    lldp: List[ParserInfo]
    cdp: List[ParserInfo]
    interfaces: List[ParserInfo]


@router.get("/parsers", response_model=CommandTemplateOptionsResponse)
async def get_available_parsers():
    """Get supported device types and parsers for command template editing."""
    return {
        "device_types": [
            {
                "type": "nokia_srl",
                "name": "Nokia SR Linux",
                "description": "Used for Nokia/Alcatel 7220 IXR series"
            },
            {
                "type": "nokia_sros",
                "name": "Nokia SR OS",
                "description": "Used for Nokia/Alcatel 7250 and WBX series"
            },
            {
                "type": "dell_force10",
                "name": "Dell Force10 / DNOS9",
                "description": "Used for Dell Force10, DNOS9, and Z9100 platforms"
            },
            {
                "type": "dell_os10",
                "name": "Dell OS10",
                "description": "Used for Dell OS10 platforms such as S5232F-ON"
            },
            {
                "type": "cisco_ios",
                "name": "Cisco IOS / IOS-XE",
                "description": "Used for Cisco Catalyst and IOS-XE devices"
            },
            {
                "type": "cisco_nxos",
                "name": "Cisco NX-OS",
                "description": "Used for Cisco Nexus and NX-OS devices"
            },
            {
                "type": "juniper_junos",
                "name": "Juniper JunOS",
                "description": "Used for Juniper switches"
            },
            {
                "type": "arista_eos",
                "name": "Arista EOS",
                "description": "Used for Arista switches running EOS"
            },
            {
                "type": "hpe_procurve",
                "name": "HPE ProCurve / ArubaOS-Switch",
                "description": "Used for HPE ProCurve and ArubaOS-Switch devices"
            },
            {
                "type": "huawei_vrp",
                "name": "Huawei VRP",
                "description": "Used for Huawei VRP switches"
            },
            {
                "type": "hp_comware",
                "name": "H3C / HP Comware",
                "description": "Used for H3C and HP Comware (V5/V7) switches"
            }
        ],
        "arp": [
            {
                "type": "nokia_7220",
                "name": "Nokia 7220 SR Linux",
                "description": "Parser for Nokia 7220 ARP table output"
            },
            {
                "type": "nokia_7250",
                "name": "Nokia 7250 SR Linux",
                "description": "Parser for Nokia 7250 ARP table output"
            },
            {
                "type": "dell_os10",
                "name": "Dell OS10",
                "description": "Parser for Dell OS10 ARP table output"
            },
            {
                "type": "dell_force10",
                "name": "Dell Force10 / DNOS9",
                "description": "Parser for Dell Force10 and DNOS9 ARP output"
            },
            {
                "type": "cisco_ios",
                "name": "Cisco IOS/IOS-XE",
                "description": "Parser for Cisco IOS/IOS-XE ARP table output"
            },
            {
                "type": "cisco_nxos",
                "name": "Cisco NX-OS",
                "description": "Parser for Cisco NX-OS ARP table output"
            },
            {
                "type": "juniper",
                "name": "Juniper JunOS",
                "description": "Parser for Juniper JunOS ARP table output"
            },
            {
                "type": "arista_eos",
                "name": "Arista EOS",
                "description": "Parser for Arista EOS ARP table output"
            },
            {
                "type": "hpe_procurve",
                "name": "HPE ProCurve",
                "description": "Parser for HPE ProCurve ARP table output"
            },
            {
                "type": "huawei_vrp",
                "name": "Huawei VRP",
                "description": "Parser for Huawei VRP ARP table output"
            },
            {
                "type": "h3c_comware",
                "name": "H3C / Comware",
                "description": "Parser for H3C Comware 'display arp' output"
            }
        ],
        "mac": [
            {
                "type": "nokia_7220",
                "name": "Nokia 7220 SR Linux",
                "description": "Parser for Nokia 7220 MAC table output"
            },
            {
                "type": "nokia_7250",
                "name": "Nokia 7250 SR Linux",
                "description": "Parser for Nokia 7250 MAC table output"
            },
            {
                "type": "dell_os10",
                "name": "Dell OS10",
                "description": "Parser for Dell OS10 MAC table output"
            },
            {
                "type": "dell_force10",
                "name": "Dell Force10 / DNOS9",
                "description": "Parser for Dell Force10 and DNOS9 MAC table output"
            },
            {
                "type": "cisco_ios",
                "name": "Cisco IOS/IOS-XE",
                "description": "Parser for Cisco IOS/IOS-XE MAC table output"
            },
            {
                "type": "cisco_nxos",
                "name": "Cisco NX-OS",
                "description": "Parser for Cisco NX-OS MAC table output"
            },
            {
                "type": "juniper",
                "name": "Juniper JunOS",
                "description": "Parser for Juniper JunOS MAC table output"
            },
            {
                "type": "arista_eos",
                "name": "Arista EOS",
                "description": "Parser for Arista EOS MAC table output"
            },
            {
                "type": "hpe_procurve",
                "name": "HPE ProCurve",
                "description": "Parser for HPE ProCurve MAC table output"
            },
            {
                "type": "huawei_vrp",
                "name": "Huawei VRP",
                "description": "Parser for Huawei VRP MAC table output"
            },
            {
                "type": "h3c_comware",
                "name": "H3C / Comware",
                "description": "Parser for H3C Comware 'display mac-address' output"
            }
        ],
        "lldp": [
            {
                "type": "cisco_ios",
                "name": "Cisco IOS/IOS-XE",
                "description": "Parser for 'show lldp neighbors detail' output"
            },
            {
                "type": "cisco_nxos",
                "name": "Cisco NX-OS",
                "description": "Parser for 'show lldp neighbors detail' output (NX-OS)"
            },
            {
                "type": "nokia_sros",
                "name": "Nokia SR OS",
                "description": "Parser for 'show system lldp neighbor' output"
            },
            {
                "type": "dell_os10",
                "name": "Dell OS10",
                "description": "Parser for 'show lldp remote-system' output"
            },
            {
                "type": "generic",
                "name": "Generic neighbor table",
                "description": "Parser for a table with local port / remote device / remote port columns"
            },
            {
                "type": "arista_eos",
                "name": "Arista EOS",
                "description": "Parser for 'show lldp neighbors detail' output (EOS)"
            },
            {
                "type": "hpe_procurve",
                "name": "HPE ProCurve",
                "description": "Parser for HPE ProCurve LLDP neighbor output"
            },
            {
                "type": "huawei_vrp",
                "name": "Huawei VRP",
                "description": "Parser for Huawei VRP LLDP neighbor output"
            },
            {
                "type": "h3c_comware",
                "name": "H3C / Comware",
                "description": "Parser for 'display lldp neighbor-information' output"
            }
        ],
        "cdp": [
            {
                "type": "cisco_ios",
                "name": "Cisco IOS/IOS-XE",
                "description": "Parser for 'show cdp neighbors detail' output"
            },
            {
                "type": "cisco_nxos",
                "name": "Cisco NX-OS",
                "description": "Parser for 'show cdp neighbors detail' output (NX-OS)"
            },
            {
                "type": "generic",
                "name": "Generic neighbor table",
                "description": "Parser for a table with local port / remote device / remote port columns"
            },
            {
                "type": "arista_eos",
                "name": "Arista EOS",
                "description": "Parser for 'show cdp neighbors detail' output (EOS)"
            }
        ],
        "interfaces": [
            {
                "type": "cisco_ios",
                "name": "Cisco IOS/IOS-XE",
                "description": "Parser for 'show interfaces status' output"
            },
            {
                "type": "cisco_nxos",
                "name": "Cisco NX-OS",
                "description": "Parser for 'show interface status' output (NX-OS)"
            },
            {
                "type": "nokia_sros",
                "name": "Nokia SR OS",
                "description": "Parser for 'show port' output"
            },
            {
                "type": "dell_os10",
                "name": "Dell OS10",
                "description": "Parser for 'show interface status' output"
            },
            {
                "type": "generic",
                "name": "Generic interface table",
                "description": "Parser for a table with interface name / status / speed columns"
            },
            {
                "type": "arista_eos",
                "name": "Arista EOS",
                "description": "Parser for 'show interfaces status' output (EOS)"
            },
            {
                "type": "hpe_procurve",
                "name": "HPE ProCurve",
                "description": "Parser for HPE ProCurve interface status output"
            },
            {
                "type": "huawei_vrp",
                "name": "Huawei VRP",
                "description": "Parser for Huawei VRP interface brief output"
            },
            {
                "type": "h3c_comware",
                "name": "H3C / Comware",
                "description": "Parser for 'display interface brief' output"
            }
        ]
    }


class TestConnectionRequest(BaseModel):
    """Request schema for testing command template"""
    switch_ip: str
    switch_username: str
    switch_password: str
    switch_enable_password: str | None = None
    switch_port: int | None = None
    cli_transport: Literal['ssh', 'telnet'] = 'ssh'
    template_id: int
    test_type: Literal['arp', 'mac', 'lldp', 'cdp', 'interfaces']


class TestConnectionResponse(BaseModel):
    """Response schema for test connection"""
    success: bool
    message: str
    entries_count: int = 0
    sample_output: str = ""
    error: str = ""


class TemplateMatchPreviewRequest(BaseModel):
    """Preview which command template would match a switch identity."""
    vendor: str
    model: str
    name: str = ""


class TemplateMatchPreviewResponse(BaseModel):
    """Template match preview response."""
    matched: bool
    source: str | None = None
    template_id: int | None = None
    vendor: str | None = None
    model_pattern: str | None = None
    name_pattern: str | None = None
    device_type: str | None = None
    priority: int | None = None
    description: str | None = None
    arp_command: str | None = None
    arp_parser_type: str | None = None
    mac_command: str | None = None
    mac_parser_type: str | None = None
    lldp_command: str | None = None
    lldp_parser_type: str | None = None
    cdp_command: str | None = None
    cdp_parser_type: str | None = None
    interfaces_command: str | None = None
    interfaces_parser_type: str | None = None
    is_builtin: bool | None = None
    message: str


@router.get("", response_model=List[SwitchCommandTemplateResponse])
async def list_command_templates(
    enabled_only: bool = Query(False, description="Only return enabled templates"),
    db: AsyncSession = Depends(get_db)
):
    """List all command templates"""
    query = select(SwitchCommandTemplate).order_by(
        SwitchCommandTemplate.priority.desc(),
        SwitchCommandTemplate.vendor,
        SwitchCommandTemplate.model_pattern
    )

    if enabled_only:
        query = query.where(SwitchCommandTemplate.enabled == True)

    result = await db.execute(query)
    templates = result.scalars().all()
    return templates


@router.get("/{template_id}", response_model=SwitchCommandTemplateResponse)
async def get_command_template(
    template_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific command template"""
    result = await db.execute(
        select(SwitchCommandTemplate).where(SwitchCommandTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Command template {template_id} not found"
        )

    return template


@router.post("", response_model=SwitchCommandTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_command_template(
    template: SwitchCommandTemplateCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new command template"""
    try:
        new_template = SwitchCommandTemplate(
            vendor=template.vendor.lower(),
            model_pattern=template.model_pattern,
            name_pattern=template.name_pattern,
            device_type=template.device_type,
            arp_command=template.arp_command,
            arp_parser_type=template.arp_parser_type,
            arp_enabled=template.arp_enabled,
            mac_command=template.mac_command,
            mac_parser_type=template.mac_parser_type,
            mac_enabled=template.mac_enabled,
            lldp_command=template.lldp_command,
            lldp_parser_type=template.lldp_parser_type,
            lldp_enabled=template.lldp_enabled,
            cdp_command=template.cdp_command,
            cdp_parser_type=template.cdp_parser_type,
            cdp_enabled=template.cdp_enabled,
            interfaces_command=template.interfaces_command,
            interfaces_parser_type=template.interfaces_parser_type,
            interfaces_enabled=template.interfaces_enabled,
            priority=template.priority,
            description=template.description,
            enabled=template.enabled,
            is_builtin=False  # User-created templates are never builtin
        )

        db.add(new_template)
        await db.commit()
        await db.refresh(new_template)

        logger.info(f"Created command template: {template.vendor} {template.model_pattern}")
        return new_template

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create command template: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create command template: {str(e)}"
        )


@router.post("/match-preview", response_model=TemplateMatchPreviewResponse)
async def preview_command_template_match(
    match_request: TemplateMatchPreviewRequest,
    db: AsyncSession = Depends(get_db)
):
    """Preview which template would match a vendor/model/name combination."""
    from services.cli_service import cli_service

    query = select(SwitchCommandTemplate).where(
        SwitchCommandTemplate.enabled == True
    ).order_by(
        SwitchCommandTemplate.priority.desc(),
        SwitchCommandTemplate.vendor,
        SwitchCommandTemplate.model_pattern
    )
    result = await db.execute(query)
    templates = result.scalars().all()

    template_dicts = [
        {
            'id': t.id,
            'vendor': t.vendor,
            'model_pattern': t.model_pattern,
            'name_pattern': t.name_pattern,
            'device_type': t.device_type,
            'arp_command': t.arp_command,
            'arp_parser_type': t.arp_parser_type,
            'arp_enabled': t.arp_enabled,
            'mac_command': t.mac_command,
            'mac_parser_type': t.mac_parser_type,
            'mac_enabled': t.mac_enabled,
            'lldp_command': t.lldp_command,
            'lldp_parser_type': t.lldp_parser_type,
            'lldp_enabled': t.lldp_enabled,
            'cdp_command': t.cdp_command,
            'cdp_parser_type': t.cdp_parser_type,
            'cdp_enabled': t.cdp_enabled,
            'interfaces_command': t.interfaces_command,
            'interfaces_parser_type': t.interfaces_parser_type,
            'interfaces_enabled': t.interfaces_enabled,
            'priority': t.priority,
            'enabled': t.enabled,
            'description': t.description,
            'is_builtin': t.is_builtin,
        }
        for t in templates
    ]

    match_details = cli_service.preview_template_match(
        vendor=match_request.vendor,
        model=match_request.model,
        name=match_request.name,
        templates=template_dicts,
    )

    if not match_details:
        return TemplateMatchPreviewResponse(
            matched=False,
            message="未找到匹配的命令模板"
        )

    matched_template = match_details['template']
    source = match_details['source']
    return TemplateMatchPreviewResponse(
        matched=True,
        source=source,
        template_id=matched_template.get('id'),
        vendor=matched_template.get('vendor'),
        model_pattern=matched_template.get('model_pattern'),
        name_pattern=matched_template.get('name_pattern'),
        device_type=matched_template.get('device_type'),
        priority=matched_template.get('priority'),
        description=matched_template.get('description'),
        arp_command=matched_template.get('arp_command'),
        arp_parser_type=matched_template.get('arp_parser_type'),
        mac_command=matched_template.get('mac_command'),
        mac_parser_type=matched_template.get('mac_parser_type'),
        lldp_command=matched_template.get('lldp_command'),
        lldp_parser_type=matched_template.get('lldp_parser_type'),
        cdp_command=matched_template.get('cdp_command'),
        cdp_parser_type=matched_template.get('cdp_parser_type'),
        interfaces_command=matched_template.get('interfaces_command'),
        interfaces_parser_type=matched_template.get('interfaces_parser_type'),
        is_builtin=bool(matched_template.get('is_builtin', source == 'builtin')),
        message=(
            f"已匹配{'数据库' if source == 'database' else '内置'}模板: "
            f"{matched_template.get('vendor')} / {matched_template.get('model_pattern')}"
        )
    )


@router.put("/{template_id}", response_model=SwitchCommandTemplateResponse)
async def update_command_template(
    template_id: int,
    template_update: SwitchCommandTemplateUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update a command template"""
    result = await db.execute(
        select(SwitchCommandTemplate).where(SwitchCommandTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Command template {template_id} not found"
        )

    # Update fields
    update_data = template_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == 'vendor' and value:
            value = value.lower()
        setattr(template, field, value)

    try:
        await db.commit()
        await db.refresh(template)
        logger.info(f"Updated command template: {template.vendor} {template.model_pattern}")
        return template

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update command template: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update command template: {str(e)}"
        )


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_command_template(
    template_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Delete a command template (built-in templates cannot be deleted)"""
    result = await db.execute(
        select(SwitchCommandTemplate).where(SwitchCommandTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Command template {template_id} not found"
        )

    if template.is_builtin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Built-in templates cannot be deleted. You can disable them instead."
        )

    try:
        await db.delete(template)
        await db.commit()
        logger.info(f"Deleted command template: {template.vendor} {template.model_pattern}")

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete command template: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete command template: {str(e)}"
        )


@router.post("/test", response_model=TestConnectionResponse)
async def test_command_template(
    test_request: TestConnectionRequest,
    db: AsyncSession = Depends(get_db)
):
    """Test a command template against a switch"""
    from services.cli_service import cli_service
    from core.security import encrypt_password

    # Get template
    result = await db.execute(
        select(SwitchCommandTemplate).where(SwitchCommandTemplate.id == test_request.template_id)
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Command template {test_request.template_id} not found"
        )

    # Build switch config
    encrypted_password = encrypt_password(test_request.switch_password)
    switch_config = {
        'username': test_request.switch_username,
        'password_encrypted': encrypted_password,
        'enable_password_encrypted': encrypt_password(test_request.switch_enable_password) if test_request.switch_enable_password else None,
        'vendor': template.vendor,
        'model': template.model_pattern,
        'name': '',
        'cli_transport': test_request.cli_transport,
        'ssh_port': test_request.switch_port,
        'connection_timeout': 30
    }

    # Convert template to dict
    template_dict = {
        'vendor': template.vendor,
        'model_pattern': template.model_pattern,
        'device_type': template.device_type,
        'arp_command': template.arp_command,
        'arp_parser_type': template.arp_parser_type,
        'arp_enabled': template.arp_enabled,
        'mac_command': template.mac_command,
        'mac_parser_type': template.mac_parser_type,
        'mac_enabled': template.mac_enabled,
        'lldp_command': template.lldp_command,
        'lldp_parser_type': template.lldp_parser_type,
        'lldp_enabled': template.lldp_enabled,
        'cdp_command': template.cdp_command,
        'cdp_parser_type': template.cdp_parser_type,
        'cdp_enabled': template.cdp_enabled,
        'interfaces_command': template.interfaces_command,
        'interfaces_parser_type': template.interfaces_parser_type,
        'interfaces_enabled': template.interfaces_enabled,
        'priority': template.priority,
        'enabled': template.enabled
    }

    try:
        if test_request.test_type == 'arp':
            if not template.arp_enabled or not template.arp_command:
                return TestConnectionResponse(
                    success=False,
                    message="ARP collection is not enabled for this template",
                    error="ARP disabled"
                )

            entries = cli_service.collect_arp_table_cli(
                test_request.switch_ip,
                switch_config,
                [template_dict]
            )

            return TestConnectionResponse(
                success=True,
                message=f"Successfully collected {len(entries)} ARP entries",
                entries_count=len(entries),
                sample_output=str(entries[:3]) if entries else "No entries found"
            )

        elif test_request.test_type == 'mac':
            if not template.mac_enabled or not template.mac_command:
                return TestConnectionResponse(
                    success=False,
                    message="MAC collection is not enabled for this template",
                    error="MAC disabled"
                )

            entries = cli_service.collect_mac_table_cli(
                test_request.switch_ip,
                switch_config,
                [template_dict]
            )

            return TestConnectionResponse(
                success=True,
                message=f"Successfully collected {len(entries)} MAC entries",
                entries_count=len(entries),
                sample_output=str(entries[:3]) if entries else "No entries found"
            )

        elif test_request.test_type in ('lldp', 'cdp', 'interfaces'):
            enabled = getattr(template, f'{test_request.test_type}_enabled', True)
            command = getattr(template, f'{test_request.test_type}_command', None)
            if not enabled or not command:
                return TestConnectionResponse(
                    success=False,
                    message=f"{test_request.test_type.upper()} collection is not enabled for this template",
                    error=f"{test_request.test_type.upper()} disabled"
                )

            collector = {
                'lldp': cli_service.collect_lldp_neighbors_cli,
                'cdp': cli_service.collect_cdp_neighbors_cli,
                'interfaces': cli_service.collect_interfaces_cli,
            }[test_request.test_type]
            result = collector(
                test_request.switch_ip,
                switch_config,
                [template_dict]
            ) or {}
            entries = result.get('entries') or []
            collect_status = result.get('status') or 'ok'
            return TestConnectionResponse(
                success=collect_status != 'error',
                message=(
                    f"{test_request.test_type.upper()} collection {collect_status}: "
                    f"{len(entries)} entries"
                ),
                entries_count=len(entries),
                sample_output=str(entries[:3]) if entries else (result.get('message') or "No entries found"),
                error=(result.get('message') or "") if collect_status == 'error' else ""
            )

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="test_type must be 'arp', 'mac', 'lldp', 'cdp' or 'interfaces'"
            )

    except Exception as e:
        logger.error(f"Test connection failed: {str(e)}")
        return TestConnectionResponse(
            success=False,
            message="Connection test failed",
            error=str(e)
        )
