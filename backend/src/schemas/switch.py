from pydantic import BaseModel, Field, IPvAnyAddress, validator
from typing import Optional, List
from datetime import datetime


class SwitchBase(BaseModel):
    """Base switch schema"""
    name: str = Field(..., min_length=1, max_length=100)
    ip_address: IPvAnyAddress
    vendor: str = Field(..., pattern="^(cisco|dell|alcatel|juniper)$")
    model: Optional[str] = Field(None, max_length=100)
    enabled: bool = True

    # CLI/SSH fields
    cli_enabled: bool = False
    ssh_port: Optional[int] = Field(default=22, ge=1, le=65535)
    username: Optional[str] = Field(None, max_length=100)
    connection_timeout: Optional[int] = Field(default=30, ge=5, le=300)

    # Data collection settings
    auto_collect_arp: bool = True
    auto_collect_mac: bool = True


class SwitchCreate(SwitchBase):
    """Schema for creating a switch with SNMP authentication"""
    # SSH credentials (optional)
    password: Optional[str] = None
    enable_password: Optional[str] = None
    
    # SNMP credentials (required)
    snmp_enabled: bool = True
    snmp_version: str = Field(default="3", pattern="^(2c|3)$")
    snmp_port: int = Field(default=161, ge=1, le=65535)
    
    # SNMPv3 fields
    snmp_username: str = Field(..., min_length=1, max_length=100)
    snmp_auth_protocol: str = Field(default="SHA", pattern="^(MD5|SHA|SHA256)$")
    snmp_auth_password: str = Field(..., min_length=8, description="At least 8 characters")
    snmp_priv_protocol: str = Field(default="AES128", pattern="^(DES|AES|AES128|AES192|AES256)$")
    snmp_priv_password: str = Field(..., min_length=8, description="At least 8 characters")
    
    # SNMPv2c field
    snmp_community: Optional[str] = None
    
    @validator('snmp_username')
    def validate_snmp_username(cls, v, values):
        if values.get('snmp_version') == '3' and not v:
            raise ValueError('snmp_username is required for SNMPv3')
        return v
    
    @validator('snmp_auth_password')
    def validate_snmp_auth_password(cls, v, values):
        if values.get('snmp_version') == '3' and (not v or len(v) < 8):
            raise ValueError('snmp_auth_password must be at least 8 characters for SNMPv3')
        return v
    
    @validator('snmp_priv_password')
    def validate_snmp_priv_password(cls, v, values):
        if values.get('snmp_version') == '3' and (not v or len(v) < 8):
            raise ValueError('snmp_priv_password must be at least 8 characters for SNMPv3')
        return v
    
    @validator('snmp_community')
    def validate_snmp_community(cls, v, values):
        if values.get('snmp_version') == '2c' and not v:
            raise ValueError('snmp_community is required for SNMPv2c')
        return v


class SwitchUpdate(BaseModel):
    """Schema for updating a switch"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    ip_address: Optional[IPvAnyAddress] = None
    vendor: Optional[str] = Field(None, pattern="^(cisco|dell|alcatel)$")
    model: Optional[str] = Field(None, max_length=100)
    cli_enabled: Optional[bool] = None
    ssh_port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = Field(None, min_length=1, max_length=100)
    password: Optional[str] = Field(None, min_length=1)
    enable_password: Optional[str] = None
    connection_timeout: Optional[int] = Field(None, ge=5, le=300)
    enabled: Optional[bool] = None

    # Data collection settings
    auto_collect_arp: Optional[bool] = None
    auto_collect_mac: Optional[bool] = None

    # SNMP fields
    snmp_enabled: Optional[bool] = None
    snmp_version: Optional[str] = Field(None, pattern="^(2c|3)$")
    snmp_port: Optional[int] = Field(None, ge=1, le=65535)
    snmp_username: Optional[str] = None
    snmp_auth_protocol: Optional[str] = None
    snmp_auth_password: Optional[str] = None
    snmp_priv_protocol: Optional[str] = None
    snmp_priv_password: Optional[str] = None
    snmp_community: Optional[str] = None

    # Manual trunk-review workflow
    trunk_review_completed: Optional[bool] = None
    trunk_review_note: Optional[str] = Field(None, max_length=1000)


class SwitchResponse(SwitchBase):
    """Schema for switch response"""
    id: int
    created_at: datetime
    updated_at: datetime

    # CLI status
    cli_enabled: bool = False

    # SNMP status
    snmp_enabled: bool = False
    snmp_version: Optional[str] = None
    snmp_username: Optional[str] = None
    has_snmp_credentials: bool = False

    # Connection status fields
    is_reachable: Optional[bool] = None
    response_time_ms: Optional[float] = None
    last_check_at: Optional[datetime] = None

    # Data collection status
    auto_collect_arp: bool = True
    auto_collect_mac: bool = True
    last_arp_collection_at: Optional[datetime] = None
    last_mac_collection_at: Optional[datetime] = None
    last_collection_status: Optional[str] = None
    last_collection_message: Optional[str] = None
    trunk_review_completed: bool = False
    trunk_review_completed_at: Optional[datetime] = None
    trunk_review_note: Optional[str] = None

    class Config:
        from_attributes = True


class SwitchTestResponse(BaseModel):
    """Schema for switch connection test response"""
    success: bool
    message: str
    details: Optional[dict] = None


class SwitchListResponse(BaseModel):
    """Schema for paginated switch list response"""
    items: List[SwitchResponse]
    total: int
