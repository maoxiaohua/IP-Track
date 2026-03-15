"""
API endpoints for Switch Command Templates
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List
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


@router.get("/parsers", response_model=dict)
async def get_available_parsers():
    """Get all available parsers for ARP and MAC collection"""
    parsers = {
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
                "type": "cisco_ios",
                "name": "Cisco IOS/IOS-XE",
                "description": "Parser for Cisco IOS/IOS-XE ARP table output"
            },
            {
                "type": "juniper",
                "name": "Juniper JunOS",
                "description": "Parser for Juniper JunOS ARP table output"
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
                "type": "cisco_ios",
                "name": "Cisco IOS/IOS-XE",
                "description": "Parser for Cisco IOS/IOS-XE MAC table output"
            },
            {
                "type": "juniper",
                "name": "Juniper JunOS",
                "description": "Parser for Juniper JunOS MAC table output"
            }
        ]
    }
    return parsers


class TestConnectionRequest(BaseModel):
    """Request schema for testing command template"""
    switch_ip: str
    switch_username: str
    switch_password: str
    template_id: int
    test_type: str  # 'arp' or 'mac'


class TestConnectionResponse(BaseModel):
    """Response schema for test connection"""
    success: bool
    message: str
    entries_count: int = 0
    sample_output: str = ""
    error: str = ""


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
        'vendor': template.vendor,
        'model': template.model_pattern,
        'name': '',
        'ssh_port': 22,
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

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="test_type must be 'arp' or 'mac'"
            )

    except Exception as e:
        logger.error(f"Test connection failed: {str(e)}")
        return TestConnectionResponse(
            success=False,
            message="Connection test failed",
            error=str(e)
        )
