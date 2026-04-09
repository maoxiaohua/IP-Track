from typing import Optional, Any, Dict
import json
import time
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models.system_settings import SystemSettings
from utils.logger import logger


class SettingsService:
    """Service for managing system settings from database"""

    # In-memory cache (TTL should be short for dynamic config)
    _cache: Dict[str, tuple[Any, float]] = {}
    CACHE_TTL_SECONDS = 5  # 5 second TTL for dynamic settings

    @classmethod
    async def get_setting(
        cls,
        db: AsyncSession,
        key: str,
        default: Any = None
    ) -> Any:
        """
        Get a setting value from database with type conversion

        Args:
            db: Database session
            key: Setting key
            default: Default value if not found

        Returns:
            Setting value converted to appropriate type
        """
        try:
            # Check in-memory cache first
            if key in cls._cache:
                value, timestamp = cls._cache[key]
                if time.time() - timestamp < cls.CACHE_TTL_SECONDS:
                    logger.debug(f"Setting '{key}' loaded from cache: {value}")
                    return value

            # Query database
            result = await db.execute(
                select(SystemSettings).where(SystemSettings.key == key)
            )
            setting = result.scalar_one_or_none()

            if not setting:
                logger.debug(f"Setting '{key}' not found, using default: {default}")
                return default

            # Convert value based on data_type
            converted_value = cls._convert_value(setting.value, setting.data_type)

            # Cache the result
            cls._cache[key] = (converted_value, time.time())

            logger.debug(f"Setting '{key}' loaded from database: {converted_value}")
            return converted_value

        except Exception as e:
            logger.error(f"Error loading setting '{key}': {str(e)}")
            return default

    @classmethod
    async def set_setting(
        cls,
        db: AsyncSession,
        key: str,
        value: Any,
        data_type: str = 'string',
        description: str = None,
        is_configurable: bool = True
    ) -> bool:
        """
        Set a setting value in database

        Args:
            db: Database session
            key: Setting key
            value: Setting value
            data_type: Data type (string, integer, float, boolean, json)
            description: Setting description
            is_configurable: Whether user can modify this setting

        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if setting exists
            result = await db.execute(
                select(SystemSettings).where(SystemSettings.key == key)
            )
            setting = result.scalar_one_or_none()

            # Convert value to string for storage
            str_value = cls._serialize_value(value, data_type)

            if setting:
                # Update existing setting
                setting.value = str_value
                setting.data_type = data_type
                if description:
                    setting.description = description
                setting.is_configurable = is_configurable
            else:
                # Create new setting
                setting = SystemSettings(
                    key=key,
                    value=str_value,
                    data_type=data_type,
                    description=description,
                    is_configurable=is_configurable
                )
                db.add(setting)

            await db.commit()

            # Invalidate cache
            if key in cls._cache:
                del cls._cache[key]

            logger.info(f"Setting '{key}' updated to '{value}'")
            return True

        except Exception as e:
            logger.error(f"Error updating setting '{key}': {str(e)}")
            await db.rollback()
            return False

    @classmethod
    def _convert_value(cls, value: str, data_type: str) -> Any:
        """Convert string value to appropriate type"""
        try:
            if data_type == 'integer':
                return int(value)
            elif data_type == 'float':
                return float(value)
            elif data_type == 'boolean':
                return value.lower() in ('true', '1', 'yes', 'on')
            elif data_type == 'json':
                return json.loads(value)
            else:  # string
                return value
        except Exception as e:
            logger.error(f"Error converting value '{value}' to type '{data_type}': {str(e)}")
            return value

    @classmethod
    def _serialize_value(cls, value: Any, data_type: str) -> str:
        """Convert value to string for storage"""
        if data_type == 'json':
            return json.dumps(value)
        return str(value)

    @classmethod
    async def get_all_configurable_settings(cls, db: AsyncSession) -> list:
        """Get all user-configurable settings"""
        try:
            result = await db.execute(
                select(SystemSettings)
                .where(
                    (SystemSettings.is_configurable == True) &
                    (SystemSettings.is_sensitive == False)
                )
                .order_by(SystemSettings.key)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error loading configurable settings: {str(e)}")
            return []


# Singleton instance
settings_service = SettingsService()
