from pydantic import BaseModel, field_validator, field_serializer
from typing import Optional, Any
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address


class QueryHistoryResponse(BaseModel):
    """Schema for query history response"""
    id: int
    target_ip: str
    found_mac: Optional[str] = None
    switch_id: Optional[int] = None
    switch_name: Optional[str] = None  # Denormalized switch name
    port_name: Optional[str] = None
    vlan_id: Optional[int] = None
    query_status: str
    error_message: Optional[str] = None
    query_time_ms: Optional[int] = None
    queried_at: datetime

    @field_validator('target_ip', mode='before')
    @classmethod
    def convert_ip_to_string(cls, v: Any) -> str:
        """Convert IPv4Address/IPv6Address to string before validation"""
        if isinstance(v, (IPv4Address, IPv6Address)):
            return str(v)
        return v

    class Config:
        from_attributes = True


class QueryHistoryListResponse(BaseModel):
    """Schema for paginated query history list"""
    total: int
    page: int
    page_size: int
    items: list[QueryHistoryResponse]
