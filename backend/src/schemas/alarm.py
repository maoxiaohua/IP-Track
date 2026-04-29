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
    current_switch_is_reachable: Optional[bool] = None
    current_switch_collection_status: Optional[str] = None
    current_switch_collection_message: Optional[str] = None
    current_freshness_status: Optional[str] = None
    current_freshness_warning: Optional[str] = None

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


class SwitchAlarmGroupResponse(BaseModel):
    """Aggregated alarm view for a single switch."""
    switch_id: int
    switch_name: str
    switch_ip: Optional[str] = None
    active_count: int
    acknowledged_count: int
    resolved_count: int
    open_count: int
    total_alarm_records: int
    total_occurrences: int
    highest_active_severity: Optional[str] = None
    latest_alarm_id: Optional[int] = None
    latest_alarm_title: Optional[str] = None
    latest_alarm_message: Optional[str] = None
    latest_alarm_status: Optional[str] = None
    latest_event_at: Optional[datetime] = None
    current_switch_is_reachable: Optional[bool] = None
    current_switch_collection_status: Optional[str] = None
    current_switch_collection_message: Optional[str] = None
    current_freshness_status: Optional[str] = None
    current_freshness_warning: Optional[str] = None


class SwitchAlarmGroupListResponse(BaseModel):
    items: List[SwitchAlarmGroupResponse]
    total: int


class SwitchAlarmTimelineEventResponse(BaseModel):
    timestamp: datetime
    event_type: str
    alarm_id: int
    severity: str
    status: str
    title: str
    message: str
    occurrence_count: int
    actor: Optional[str] = None
    note: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class SwitchAlarmTimelineResponse(BaseModel):
    switch_id: int
    switch_name: str
    switch_ip: Optional[str] = None
    active_count: int
    acknowledged_count: int
    resolved_count: int
    open_count: int
    total_alarm_records: int
    total_occurrences: int
    current_switch_is_reachable: Optional[bool] = None
    current_switch_collection_status: Optional[str] = None
    current_switch_collection_message: Optional[str] = None
    current_freshness_status: Optional[str] = None
    current_freshness_warning: Optional[str] = None
    events: List[SwitchAlarmTimelineEventResponse]
