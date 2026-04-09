from pydantic import BaseModel, Field
from typing import Optional, Any


class SettingResponse(BaseModel):
    """Single setting response"""
    key: str
    value: Any
    data_type: str
    description: Optional[str] = None
    is_configurable: bool

    class Config:
        from_attributes = True


class SettingUpdate(BaseModel):
    """Update a setting"""
    value: Any = Field(..., description="New value for the setting")

    class Config:
        from_attributes = True


class IPLookupSettingsResponse(BaseModel):
    """IP Lookup specific settings response"""
    cache_hours: int = Field(..., description="Cache hours for IP lookup")
    cache_hours_min: int = Field(..., description="Minimum allowed cache hours")
    cache_hours_max: int = Field(..., description="Maximum allowed cache hours")


class AllSettingsResponse(BaseModel):
    """All user-configurable settings"""
    settings: list[SettingResponse]
    total: int
