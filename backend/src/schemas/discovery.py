from pydantic import BaseModel, Field
from typing import List, Optional, Literal


class CredentialSet(BaseModel):
    """Credential set for switch discovery"""
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    enable_password: Optional[str] = None
    transport: Literal['ssh', 'telnet'] = 'ssh'
    port: int = Field(default=22, ge=1, le=65535)


class SNMPDiscoveryConfig(BaseModel):
    """SNMP configuration for device identity discovery"""
    snmp_version: str = Field(default='3', pattern='^(2c|3)$')
    snmp_port: int = Field(default=161, ge=1, le=65535)
    # SNMPv3 fields
    snmp_username: Optional[str] = None
    snmp_auth_protocol: Optional[str] = None   # SHA, MD5, SHA256
    snmp_auth_password: Optional[str] = None
    snmp_priv_protocol: Optional[str] = None   # AES128, AES256, DES
    snmp_priv_password: Optional[str] = None
    # SNMPv2c fields
    snmp_community: Optional[str] = None


class SwitchDiscoveryRequest(BaseModel):
    """Request schema for switch discovery"""
    ip_range: str = Field(..., description="IP range: 10.0.0.1-10.0.0.254 or 10.0.0.0/24")
    credentials: List[CredentialSet] = Field(..., min_length=1, description="CLI credentials to try")
    snmp_config: Optional[SNMPDiscoveryConfig] = None  # SNMP for hostname/vendor/model identity


class DiscoveredSwitch(BaseModel):
    """Schema for a discovered switch"""
    ip_address: str
    name: str
    vendor: str
    model: str
    cli_transport: Literal['ssh', 'telnet'] = 'ssh'
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
