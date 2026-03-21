from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SNMPProfileBase(BaseModel):
    """Base SNMP profile schema"""
    name: str = Field(..., min_length=1, max_length=100, description="Profile name")
    version: str = Field(default='v3', description="SNMP version: v2c or v3")

    # SNMPv3 Authentication
    username: Optional[str] = Field(None, max_length=100, description="SNMPv3 username")
    auth_protocol: Optional[str] = Field(None, description="Auth protocol: MD5, SHA, SHA-224, SHA-256, SHA-384, SHA-512")
    auth_password: Optional[str] = Field(None, description="Auth password (will be encrypted)")

    # SNMPv3 Privacy
    priv_protocol: Optional[str] = Field(None, description="Privacy protocol: DES, AES, AES-192, AES-256")
    priv_password: Optional[str] = Field(None, description="Privacy password (will be encrypted)")

    # SNMPv2c Community
    community: Optional[str] = Field(None, description="SNMPv2c community string (will be encrypted)")

    # Common settings
    port: int = Field(default=161, ge=1, le=65535, description="SNMP port")
    timeout: int = Field(default=5, ge=1, le=60, description="Timeout in seconds")
    retries: int = Field(default=3, ge=0, le=10, description="Number of retries")

    description: Optional[str] = Field(None, description="Profile description")
    enabled: bool = Field(default=True, description="Whether this profile is enabled")


class SNMPProfileCreate(SNMPProfileBase):
    """Schema for creating a new SNMP profile"""
    pass


class SNMPProfileUpdate(BaseModel):
    """Schema for updating an SNMP profile"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    version: Optional[str] = None
    username: Optional[str] = None
    auth_protocol: Optional[str] = None
    auth_password: Optional[str] = None
    priv_protocol: Optional[str] = None
    priv_password: Optional[str] = None
    community: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    timeout: Optional[int] = Field(None, ge=1, le=60)
    retries: Optional[int] = Field(None, ge=0, le=10)
    description: Optional[str] = None
    enabled: Optional[bool] = None


class SNMPProfileResponse(BaseModel):
    """Schema for SNMP profile response"""
    id: int
    name: str
    version: str
    username: Optional[str] = None
    auth_protocol: Optional[str] = None
    priv_protocol: Optional[str] = None
    port: int
    timeout: int
    retries: int
    description: Optional[str] = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    # Count of associated subnets
    subnet_count: Optional[int] = 0

    class Config:
        from_attributes = True


class SNMPProfileListResponse(BaseModel):
    """Schema for SNMP profile list response"""
    items: list[SNMPProfileResponse]
    total: int
    page: int
    page_size: int


class SNMPTestRequest(BaseModel):
    """Schema for testing SNMP connection"""
    target_ip: str = Field(..., description="IP address to test")
    profile_id: Optional[int] = Field(None, description="Existing profile ID to use")

    # Or provide credentials directly for testing
    username: Optional[str] = None
    auth_protocol: Optional[str] = None
    auth_password: Optional[str] = None
    priv_protocol: Optional[str] = None
    priv_password: Optional[str] = None
    community: Optional[str] = None
    version: Optional[str] = Field(default='v3')
    port: Optional[int] = Field(default=161)
    timeout: Optional[int] = Field(default=5)


class SNMPTestResponse(BaseModel):
    """Schema for SNMP test response"""
    success: bool
    message: str
    data: Optional[dict] = None
    error: Optional[str] = None
