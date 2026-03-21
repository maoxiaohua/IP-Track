from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from typing import List, Optional
from api.deps import get_db
from schemas.snmp import (
    SNMPProfileCreate,
    SNMPProfileUpdate,
    SNMPProfileResponse,
    SNMPProfileListResponse,
    SNMPTestRequest,
    SNMPTestResponse
)
from models.ipam import SNMPProfile, IPSubnet
from core.security import encrypt_password, decrypt_password
from services.snmp_service import snmp_service
from utils.logger import logger

router = APIRouter(prefix="/snmp-profiles", tags=["snmp-profiles"])


@router.post("", response_model=SNMPProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_snmp_profile(
    profile: SNMPProfileCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new SNMP profile

    Creates a new SNMP profile with encrypted credentials.
    Supports both SNMPv2c (community string) and SNMPv3 (username/password).
    """
    try:
        # Check if profile name already exists
        result = await db.execute(
            select(SNMPProfile).where(SNMPProfile.name == profile.name)
        )
        existing = result.scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"SNMP profile with name '{profile.name}' already exists"
            )

        # Validate version
        if profile.version not in ['v2c', 'v3']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Version must be 'v2c' or 'v3'"
            )

        # Validate required fields based on version
        if profile.version == 'v3':
            if not profile.username:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username is required for SNMPv3"
                )
            if not profile.auth_password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Auth password is required for SNMPv3"
                )
        elif profile.version == 'v2c':
            if not profile.community:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Community string is required for SNMPv2c"
                )

        # Create new profile with encrypted credentials
        new_profile = SNMPProfile(
            name=profile.name,
            version=profile.version,
            username=profile.username,
            auth_protocol=profile.auth_protocol,
            auth_password_encrypted=encrypt_password(profile.auth_password) if profile.auth_password else None,
            priv_protocol=profile.priv_protocol,
            priv_password_encrypted=encrypt_password(profile.priv_password) if profile.priv_password else None,
            community_encrypted=encrypt_password(profile.community) if profile.community else None,
            port=profile.port,
            timeout=profile.timeout,
            retries=profile.retries,
            description=profile.description,
            enabled=profile.enabled
        )

        db.add(new_profile)
        await db.commit()
        await db.refresh(new_profile)

        # Get subnet count
        subnet_count_result = await db.execute(
            select(func.count(IPSubnet.id)).where(IPSubnet.snmp_profile_id == new_profile.id)
        )
        subnet_count = subnet_count_result.scalar() or 0

        logger.info(f"Created SNMP profile: {new_profile.name} (ID: {new_profile.id})")

        return SNMPProfileResponse(
            **{k: v for k, v in new_profile.__dict__.items() if not k.startswith('_')},
            subnet_count=subnet_count
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating SNMP profile: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create SNMP profile: {str(e)}"
        )


@router.get("", response_model=SNMPProfileListResponse)
async def list_snmp_profiles(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    enabled_only: bool = Query(False, description="Show only enabled profiles"),
    db: AsyncSession = Depends(get_db)
):
    """
    List all SNMP profiles

    Returns a paginated list of SNMP profiles with subnet counts.
    """
    try:
        # Build query
        query = select(SNMPProfile)
        if enabled_only:
            query = query.where(SNMPProfile.enabled == True)

        # Get total count
        count_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar() or 0

        # Get paginated results
        query = query.order_by(SNMPProfile.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        profiles = result.scalars().all()

        # Get subnet counts for each profile
        profile_responses = []
        for profile in profiles:
            subnet_count_result = await db.execute(
                select(func.count(IPSubnet.id)).where(IPSubnet.snmp_profile_id == profile.id)
            )
            subnet_count = subnet_count_result.scalar() or 0

            profile_responses.append(
                SNMPProfileResponse(
                    **{k: v for k, v in profile.__dict__.items() if not k.startswith('_')},
                    subnet_count=subnet_count
                )
            )

        return SNMPProfileListResponse(
            items=profile_responses,
            total=total,
            page=page,
            page_size=page_size
        )

    except Exception as e:
        logger.error(f"Error listing SNMP profiles: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list SNMP profiles"
        )


@router.get("/{profile_id}", response_model=SNMPProfileResponse)
async def get_snmp_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific SNMP profile by ID"""
    result = await db.execute(
        select(SNMPProfile).where(SNMPProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SNMP profile {profile_id} not found"
        )

    # Get subnet count
    subnet_count_result = await db.execute(
        select(func.count(IPSubnet.id)).where(IPSubnet.snmp_profile_id == profile.id)
    )
    subnet_count = subnet_count_result.scalar() or 0

    return SNMPProfileResponse(
        **{k: v for k, v in profile.__dict__.items() if not k.startswith('_')},
        subnet_count=subnet_count
    )


@router.put("/{profile_id}", response_model=SNMPProfileResponse)
async def update_snmp_profile(
    profile_id: int,
    profile_update: SNMPProfileUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Update an SNMP profile

    Updates profile settings. Passwords are re-encrypted if provided.
    """
    try:
        # Get existing profile
        result = await db.execute(
            select(SNMPProfile).where(SNMPProfile.id == profile_id)
        )
        profile = result.scalar_one_or_none()

        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SNMP profile {profile_id} not found"
            )

        # Check if new name conflicts with another profile
        if profile_update.name and profile_update.name != profile.name:
            result = await db.execute(
                select(SNMPProfile).where(
                    SNMPProfile.name == profile_update.name,
                    SNMPProfile.id != profile_id
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"SNMP profile with name '{profile_update.name}' already exists"
                )

        # Update fields
        update_data = profile_update.model_dump(exclude_unset=True)

        # Handle password encryption
        if 'auth_password' in update_data and update_data['auth_password']:
            update_data['auth_password_encrypted'] = encrypt_password(update_data.pop('auth_password'))

        if 'priv_password' in update_data and update_data['priv_password']:
            update_data['priv_password_encrypted'] = encrypt_password(update_data.pop('priv_password'))

        if 'community' in update_data and update_data['community']:
            update_data['community_encrypted'] = encrypt_password(update_data.pop('community'))

        # Apply updates
        for key, value in update_data.items():
            setattr(profile, key, value)

        await db.commit()
        await db.refresh(profile)

        # Get subnet count
        subnet_count_result = await db.execute(
            select(func.count(IPSubnet.id)).where(IPSubnet.snmp_profile_id == profile.id)
        )
        subnet_count = subnet_count_result.scalar() or 0

        logger.info(f"Updated SNMP profile: {profile.name} (ID: {profile.id})")

        return SNMPProfileResponse(
            **{k: v for k, v in profile.__dict__.items() if not k.startswith('_')},
            subnet_count=subnet_count
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating SNMP profile: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update SNMP profile: {str(e)}"
        )


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snmp_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete an SNMP profile

    Cannot delete if the profile is being used by any subnets.
    """
    try:
        # Check if profile exists
        result = await db.execute(
            select(SNMPProfile).where(SNMPProfile.id == profile_id)
        )
        profile = result.scalar_one_or_none()

        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SNMP profile {profile_id} not found"
            )

        # Check if profile is being used
        subnet_count_result = await db.execute(
            select(func.count(IPSubnet.id)).where(IPSubnet.snmp_profile_id == profile_id)
        )
        subnet_count = subnet_count_result.scalar() or 0

        if subnet_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete profile: it is used by {subnet_count} subnet(s). Remove profile from subnets first."
            )

        # Delete profile
        await db.delete(profile)
        await db.commit()

        logger.info(f"Deleted SNMP profile: {profile.name} (ID: {profile_id})")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting SNMP profile: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete SNMP profile"
        )


@router.post("/test", response_model=SNMPTestResponse)
async def test_snmp_connection(
    test_request: SNMPTestRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Test SNMP connection to a device

    Can use an existing profile or provide credentials directly.
    """
    try:
        snmp_profile = None

        if test_request.profile_id:
            # Use existing profile
            result = await db.execute(
                select(SNMPProfile).where(SNMPProfile.id == test_request.profile_id)
            )
            profile = result.scalar_one_or_none()

            if not profile:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"SNMP profile {test_request.profile_id} not found"
                )

            snmp_profile = {
                'username': profile.username,
                'auth_protocol': profile.auth_protocol,
                'auth_password_encrypted': profile.auth_password_encrypted,
                'priv_protocol': profile.priv_protocol,
                'priv_password_encrypted': profile.priv_password_encrypted,
                'port': profile.port,
                'timeout': profile.timeout
            }
        else:
            # Use provided credentials
            if not test_request.username or not test_request.auth_password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username and auth_password are required for SNMP test"
                )

            snmp_profile = {
                'username': test_request.username,
                'auth_protocol': test_request.auth_protocol or 'SHA',
                'auth_password_encrypted': encrypt_password(test_request.auth_password),
                'priv_protocol': test_request.priv_protocol or 'AES',
                'priv_password_encrypted': encrypt_password(test_request.priv_password) if test_request.priv_password else None,
                'port': test_request.port,
                'timeout': test_request.timeout
            }

        # Test SNMP connection
        result = await snmp_service.get_device_identification(
            test_request.target_ip,
            snmp_profile
        )

        if result:
            return SNMPTestResponse(
                success=True,
                message=f"Successfully connected to {test_request.target_ip}",
                data=result
            )
        else:
            return SNMPTestResponse(
                success=False,
                message=f"Failed to get SNMP data from {test_request.target_ip}",
                error="No data returned from device"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing SNMP connection: {str(e)}")
        return SNMPTestResponse(
            success=False,
            message="SNMP test failed",
            error=str(e)
        )
