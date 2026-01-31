from pydantic import BaseModel, Field
from typing import List, Optional


class CredentialSet(BaseModel):
    """Credential set for switch discovery"""
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    enable_password: Optional[str] = None
    port: int = Field(default=22, ge=1, le=65535)


class SwitchDiscoveryRequest(BaseModel):
    """Request schema for switch discovery"""
    ip_range: str = Field(..., description="IP range: 10.0.0.1-10.0.0.254 or 10.0.0.0/24")
    credentials: List[CredentialSet] = Field(..., min_items=1, description="List of credentials to try")


class DiscoveredSwitch(BaseModel):
    """Schema for a discovered switch"""
    ip_address: str
    name: str
    vendor: str
    model: str
    role: str
    priority: int
    ssh_port: int
    username: str
    # Note: password is not included in response for security


class SwitchDiscoveryResponse(BaseModel):
    """Response schema for switch discovery"""
    total_scanned: int
    discovered: int
    switches: List[DiscoveredSwitch]


class BatchSwitchCreateRequest(BaseModel):
    """Request schema for batch creating switches"""
    switches: List[int] = Field(..., description="List of discovered switch indices to add")
    discovery_session_id: Optional[str] = None  # For future session management
