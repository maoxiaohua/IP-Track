from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from api.deps import get_db
from models.system_settings import SystemSettings
from schemas.settings import (
    SettingResponse, SettingUpdate, IPLookupSettingsResponse, AllSettingsResponse
)
from services.settings_service import settings_service
from utils.logger import logger

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/lookup", response_model=IPLookupSettingsResponse)
async def get_lookup_settings(db: AsyncSession = Depends(get_db)):
    """Get IP Lookup configuration settings"""
    try:
        cache_hours = await settings_service.get_setting(
            db, 'ip_lookup_cache_hours', 24
        )
        cache_hours_min = await settings_service.get_setting(
            db, 'ip_lookup_cache_hours_min', 1
        )
        cache_hours_max = await settings_service.get_setting(
            db, 'ip_lookup_cache_hours_max', 168
        )

        return IPLookupSettingsResponse(
            cache_hours=int(cache_hours),
            cache_hours_min=int(cache_hours_min),
            cache_hours_max=int(cache_hours_max)
        )
    except Exception as e:
        logger.error(f"Error retrieving lookup settings: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve settings"
        )


@router.put("/lookup/cache-hours", response_model=SettingResponse)
async def update_lookup_cache_hours(
    update: SettingUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update IP Lookup cache hours setting"""
    try:
        cache_hours = int(update.value)

        # Validate range (1-168 hours = 7 days)
        if cache_hours < 1 or cache_hours > 168:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cache hours must be between 1 and 168"
            )

        # Update setting
        success = await settings_service.set_setting(
            db, 'ip_lookup_cache_hours', cache_hours, 'integer'
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update setting"
            )

        # Return updated setting
        result = await db.execute(
            select(SystemSettings).where(
                SystemSettings.key == 'ip_lookup_cache_hours'
            )
        )
        setting = result.scalar_one()

        return SettingResponse(
            key=setting.key,
            value=int(setting.value),
            data_type=setting.data_type,
            description=setting.description,
            is_configurable=setting.is_configurable
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating lookup cache hours: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update setting"
        )


@router.get("/all", response_model=AllSettingsResponse)
async def get_all_settings(db: AsyncSession = Depends(get_db)):
    """Get all user-configurable settings"""
    try:
        settings_list = await settings_service.get_all_configurable_settings(db)

        settings_response = [
            SettingResponse(
                key=s.key,
                value=settings_service._convert_value(s.value, s.data_type),
                data_type=s.data_type,
                description=s.description,
                is_configurable=s.is_configurable
            )
            for s in settings_list
        ]

        return AllSettingsResponse(
            settings=settings_response,
            total=len(settings_response)
        )
    except Exception as e:
        logger.error(f"Error retrieving all settings: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve settings"
        )
