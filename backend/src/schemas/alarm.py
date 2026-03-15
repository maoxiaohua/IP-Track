"""
Alarm Schemas

Pydantic models for API request/response validation.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from models.alarm import AlarmSeverity, AlarmStatus, AlarmSourceType


class AlarmBase(BaseModel):
    """Base alarm schema with common fields"""
    severity: AlarmSeverity
    title: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1)
    source_type: AlarmSourceType
    source_id: Optional[int] = None
    source_name: Optional[str] = Field(None, max_length=200)
    details: Optional[Dict[str, Any]] = None


class AlarmCreate(AlarmBase):
    """Schema for creating an alarm"""
    pass


class AlarmUpdate(BaseModel):
    """Schema for updating an alarm - all fields optional"""
    severity: Optional[AlarmSeverity] = None
    status: Optional[AlarmStatus] = None
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    message: Optional[str] = Field(None, min_length=1)
    source_type: Optional[AlarmSourceType] = None
    source_id: Optional[int] = None
    source_name: Optional[str] = Field(None, max_length=200)
    details: Optional[Dict[str, Any]] = None


class AlarmResponse(AlarmBase):
    """Schema for alarm response"""
    id: int
    status: AlarmStatus
    fingerprint: str
    occurrence_count: int
    created_at: datetime
    last_occurrence_at: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None

    class Config:
        from_attributes = True


class AlarmListResponse(BaseModel):
    """Schema for paginated alarm list response"""
    items: List[AlarmResponse]
    total: int


class AlarmStatsResponse(BaseModel):
    """Schema for alarm statistics"""
    total_active: int
    total_acknowledged: int
    total_resolved: int
    by_severity: Dict[str, int]
    by_source_type: Dict[str, int]
    top_failing_switches: Optional[List[Dict[str, Any]]] = None
