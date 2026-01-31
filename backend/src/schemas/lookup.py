from pydantic import BaseModel, Field, IPvAnyAddress
from typing import Optional
from datetime import datetime


class IPLookupRequest(BaseModel):
    """Schema for IP lookup request"""
    ip_address: IPvAnyAddress = Field(..., description="Target IP address to lookup")


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
    message: Optional[str] = None


class IPLookupResponse(BaseModel):
    """Schema for IP lookup response"""
    success: bool
    result: Optional[IPLookupResult] = None
    error: Optional[str] = None
