"""
API endpoints for vendor-specific SNMP OID overrides.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from api.deps import get_db
from models.snmp_oid_override import SnmpOidOverride
from schemas.snmp_oid_override import (
    SnmpOidOverrideCreate,
    SnmpOidOverrideUpdate,
    SnmpOidOverrideResponse,
)
from utils.logger import logger

router = APIRouter(prefix="/snmp-oid-overrides", tags=["snmp-oid-overrides"])

VALID_OID_ROLES = [
    "arp_ip",
    "arp_mac",
    "mac_address",
    "mac_port",
    "mac_vlan",
    "bridge_port_map",
]


@router.get("/roles")
async def get_valid_roles():
    """Get valid oid_role values for SNMP OID overrides."""
    return {"roles": VALID_OID_ROLES}


@router.get("", response_model=List[SnmpOidOverrideResponse])
async def list_oid_overrides(
    vendor: str = Query(None, description="Filter by vendor"),
    db: AsyncSession = Depends(get_db),
):
    """List all SNMP OID overrides, optionally filtered by vendor."""
    query = select(SnmpOidOverride).order_by(
        SnmpOidOverride.priority.desc(),
        SnmpOidOverride.vendor,
        SnmpOidOverride.oid_role,
    )
    if vendor:
        query = query.where(SnmpOidOverride.vendor == vendor.lower())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{override_id}", response_model=SnmpOidOverrideResponse)
async def get_oid_override(override_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific OID override."""
    result = await db.execute(
        select(SnmpOidOverride).where(SnmpOidOverride.id == override_id)
    )
    override = result.scalar_one_or_none()
    if not override:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OID override not found")
    return override


@router.post("", response_model=SnmpOidOverrideResponse, status_code=status.HTTP_201_CREATED)
async def create_oid_override(
    override: SnmpOidOverrideCreate, db: AsyncSession = Depends(get_db)
):
    """Create a new SNMP OID override."""
    if override.oid_role not in VALID_OID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid oid_role. Must be one of: {VALID_OID_ROLES}",
        )
    try:
        new_override = SnmpOidOverride(
            vendor=override.vendor.lower(),
            model_pattern=override.model_pattern,
            oid_role=override.oid_role,
            oid_value=override.oid_value,
            description=override.description,
            priority=override.priority,
            enabled=override.enabled,
            is_builtin=False,
        )
        db.add(new_override)
        await db.commit()
        await db.refresh(new_override)
        logger.info(f"Created SNMP OID override: {override.vendor} {override.oid_role}")
        return new_override
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create OID override: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create OID override: {str(e)}",
        )


@router.put("/{override_id}", response_model=SnmpOidOverrideResponse)
async def update_oid_override(
    override_id: int,
    override: SnmpOidOverrideUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing SNMP OID override."""
    result = await db.execute(
        select(SnmpOidOverride).where(SnmpOidOverride.id == override_id)
    )
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OID override not found")

    if override.oid_role is not None and override.oid_role not in VALID_OID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid oid_role. Must be one of: {VALID_OID_ROLES}",
        )

    try:
        update_data = override.model_dump(exclude_unset=True)
        if "vendor" in update_data:
            update_data["vendor"] = update_data["vendor"].lower()
        for key, value in update_data.items():
            setattr(existing, key, value)
        await db.commit()
        await db.refresh(existing)
        logger.info(f"Updated SNMP OID override: {override_id}")
        return existing
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update OID override: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update OID override: {str(e)}",
        )


@router.delete("/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_oid_override(override_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an SNMP OID override (cannot delete built-in overrides)."""
    result = await db.execute(
        select(SnmpOidOverride).where(SnmpOidOverride.id == override_id)
    )
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OID override not found")
    if existing.is_builtin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete built-in OID override. Disable it instead.",
        )
    try:
        await db.delete(existing)
        await db.commit()
        logger.info(f"Deleted SNMP OID override: {override_id}")
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete OID override: {str(e)}",
        )
