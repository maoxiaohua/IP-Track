from pydantic import BaseModel, Field, IPvAnyAddress
from typing import Optional, Literal
from datetime import datetime


class IPLookupRequest(BaseModel):
    """Schema for IP lookup request"""
    ip_address: IPvAnyAddress = Field(..., description="Target IP address to lookup")
    mode: Literal['auto', 'cache', 'realtime'] = Field(
        default='cache',
        description="Query mode: 'auto' (cache then realtime), 'cache' (database only, fast), 'realtime' (SSH query, slow but accurate)"
    )


class IPLookupResult(BaseModel):
    """Schema for IP lookup result"""
    target_ip: str
    found: bool
    mac_address: Optional[str] = None
    switch_id: Optional[int] = None
    switch_name: Optional[str] = None
    switch_ip: Optional[str] = None
    port_name: Optional[str] = None
    vlan_id: Optional[int] = None
    query_time_ms: int
    query_mode: Optional[str] = None  # 'cache', 'realtime', 'auto_fallback'
    data_age_seconds: Optional[int] = None  # Only for cache mode - how old is the data
    last_seen: Optional[str] = None  # Only for cache mode - when was the data last collected
    message: Optional[str] = None


class IPLookupResponse(BaseModel):
    """Schema for IP lookup response"""
    success: bool
    result: Optional[IPLookupResult] = None
    error: Optional[str] = None
