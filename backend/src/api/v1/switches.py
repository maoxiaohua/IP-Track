from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from datetime import datetime
from api.deps import get_db
from models.switch import Switch
from schemas.switch import SwitchCreate, SwitchUpdate, SwitchResponse, SwitchTestResponse
from core.security import credential_encryption
from services.switch_manager import switch_manager
from utils.logger import logger
from utils.network import ping_host, ping_multiple_hosts

router = APIRouter(prefix="/switches", tags=["switches"])


@router.post("", response_model=SwitchResponse, status_code=status.HTTP_201_CREATED)
async def create_switch(
    switch_data: SwitchCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new switch"""
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
            ssh_port=switch_data.ssh_port,
            username=switch_data.username,
            password_encrypted=password_encrypted,
            enable_password_encrypted=enable_password_encrypted,
            enabled=switch_data.enabled,
            connection_timeout=switch_data.connection_timeout
        )

        db.add(switch)
        await db.commit()
        await db.refresh(switch)

        logger.info(f"Created switch: {switch.name} ({switch.ip_address})")
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


@router.get("", response_model=List[SwitchResponse])
async def list_switches(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """List all switches"""
    try:
        result = await db.execute(
            select(Switch).offset(skip).limit(limit)
        )
        switches = result.scalars().all()
        return switches
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

        # Handle password encryption
        if 'password' in update_data:
            update_data['password_encrypted'] = credential_encryption.encrypt(update_data.pop('password'))

        if 'enable_password' in update_data:
            enable_pwd = update_data.pop('enable_password')
            if enable_pwd:
                update_data['enable_password_encrypted'] = credential_encryption.encrypt(enable_pwd)
            else:
                update_data['enable_password_encrypted'] = None

        # Update switch
        for key, value in update_data.items():
            if hasattr(switch, key):
                setattr(switch, key, value)

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
        return None

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
    """Test connection to a switch"""
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

        # Test connection (runs in thread pool to avoid blocking)
        test_result = switch_manager.test_connection(switch)

        return SwitchTestResponse(**test_result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing switch connection: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to test switch connection: {str(e)}"
        )


@router.post("/{switch_id}/ping")
async def ping_switch(
    switch_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Ping a switch to check if it's reachable"""
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

        # Ping the switch
        ping_result = await ping_host(str(switch.ip_address), timeout=2)

        # Update switch status
        switch.is_reachable = ping_result["reachable"]
        switch.last_check_at = datetime.utcnow()
        switch.response_time_ms = ping_result.get("response_time_ms")

        await db.commit()
        await db.refresh(switch)

        logger.info(f"Pinged switch {switch.name}: {'reachable' if ping_result['reachable'] else 'unreachable'}")

        return {
            "switch_id": switch.id,
            "switch_name": switch.name,
            "ip_address": str(switch.ip_address),
            "reachable": ping_result["reachable"],
            "response_time_ms": ping_result.get("response_time_ms"),
            "last_check_at": switch.last_check_at
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error pinging switch: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ping switch: {str(e)}"
        )


@router.post("/ping-all")
async def ping_all_switches(
    db: AsyncSession = Depends(get_db)
):
    """Ping all switches to check their status"""
    try:
        # Get all switches
        result = await db.execute(select(Switch))
        switches = result.scalars().all()

        if not switches:
            return {
                "total": 0,
                "reachable": 0,
                "unreachable": 0,
                "results": []
            }

        # Ping all switches concurrently
        switch_ips = {str(sw.ip_address): sw for sw in switches}
        ping_results = await ping_multiple_hosts(list(switch_ips.keys()), timeout=2)

        # Update all switches
        reachable_count = 0
        unreachable_count = 0
        results = []

        for ip, ping_result in ping_results.items():
            switch = switch_ips[ip]
            switch.is_reachable = ping_result["reachable"]
            switch.last_check_at = datetime.utcnow()
            switch.response_time_ms = ping_result.get("response_time_ms")

            if ping_result["reachable"]:
                reachable_count += 1
            else:
                unreachable_count += 1

            results.append({
                "switch_id": switch.id,
                "switch_name": switch.name,
                "ip_address": ip,
                "reachable": ping_result["reachable"],
                "response_time_ms": ping_result.get("response_time_ms")
            })

        await db.commit()

        logger.info(f"Pinged all switches: {reachable_count} reachable, {unreachable_count} unreachable")

        return {
            "total": len(switches),
            "reachable": reachable_count,
            "unreachable": unreachable_count,
            "results": results
        }

    except Exception as e:
        logger.error(f"Error pinging all switches: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ping all switches: {str(e)}"
        )

