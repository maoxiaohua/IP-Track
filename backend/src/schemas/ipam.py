from pydantic import BaseModel, Field, IPvAnyAddress
from typing import Optional, List
from datetime import datetime
from enum import Enum


class IPStatus(str, Enum):
    """IP address status"""
    AVAILABLE = "available"
    USED = "used"
    RESERVED = "reserved"
    OFFLINE = "offline"


# IP Subnet Schemas
class IPSubnetBase(BaseModel):
    """Base IP subnet schema"""
    name: str = Field(..., min_length=1, max_length=100)
    network: str = Field(..., description="Network in CIDR format, e.g., 10.0.0.0/24")
    description: Optional[str] = None
    vlan_id: Optional[int] = Field(None, ge=1, le=4094)
    gateway: Optional[IPvAnyAddress] = None
    dns_servers: Optional[str] = Field(None, description="Comma-separated DNS servers")
    enabled: bool = True
    auto_scan: bool = True
    scan_interval: int = Field(default=3600, ge=300, le=86400, description="Scan interval in seconds")


class IPSubnetCreate(IPSubnetBase):
    """Schema for creating IP subnet"""
    pass


class IPSubnetUpdate(BaseModel):
    """Schema for updating IP subnet"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    vlan_id: Optional[int] = Field(None, ge=1, le=4094)
    gateway: Optional[IPvAnyAddress] = None
    dns_servers: Optional[str] = None
    enabled: Optional[bool] = None
    auto_scan: Optional[bool] = None
    scan_interval: Optional[int] = Field(None, ge=300, le=86400)


class IPSubnetResponse(IPSubnetBase):
    """Schema for IP subnet response"""
    id: int
    last_scan_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    total_ips: Optional[int] = None
    used_ips: Optional[int] = None
    available_ips: Optional[int] = None

    class Config:
        from_attributes = True


# IP Address Schemas
class IPAddressBase(BaseModel):
    """Base IP address schema"""
    ip_address: IPvAnyAddress
    status: IPStatus = IPStatus.AVAILABLE
    hostname: Optional[str] = Field(None, max_length=255)
    mac_address: Optional[str] = None
    description: Optional[str] = None


class IPAddressCreate(IPAddressBase):
    """Schema for creating IP address"""
    subnet_id: int


class IPAddressUpdate(BaseModel):
    """Schema for updating IP address"""
    status: Optional[IPStatus] = None
    hostname: Optional[str] = Field(None, max_length=255)
    mac_address: Optional[str] = None
    description: Optional[str] = None


class IPAddressResponse(IPAddressBase):
    """Schema for IP address response"""
    id: int
    subnet_id: int
    is_reachable: bool
    response_time: Optional[int]
    os_type: Optional[str]
    os_name: Optional[str]
    os_version: Optional[str]
    os_vendor: Optional[str]
    switch_id: Optional[int]
    switch_port: Optional[str]
    vlan_id: Optional[int]
    last_seen_at: Optional[datetime]
    last_scan_at: Optional[datetime]
    scan_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class IPAddressDetailResponse(IPAddressResponse):
    """Detailed IP address response with relationships"""
    subnet_name: Optional[str] = None
    switch_name: Optional[str] = None


# IP Scan History Schemas
class IPScanHistoryResponse(BaseModel):
    """Schema for IP scan history response"""
    id: int
    ip_address_id: int
    is_reachable: bool
    response_time: Optional[int]
    hostname: Optional[str]
    mac_address: Optional[str]
    os_type: Optional[str]
    os_name: Optional[str]
    status_changed: bool
    hostname_changed: bool
    os_changed: bool
    scanned_at: datetime

    class Config:
        from_attributes = True


# Scan Request Schemas
class IPScanRequest(BaseModel):
    """Schema for IP scan request"""
    subnet_id: Optional[int] = None
    ip_addresses: Optional[List[str]] = None
    scan_type: str = Field(default="full", pattern="^(quick|full)$")


class IPScanResult(BaseModel):
    """Schema for IP scan result"""
    ip_address: str
    is_reachable: bool
    response_time: Optional[int]
    hostname: Optional[str]
    mac_address: Optional[str]
    os_type: Optional[str]
    os_name: Optional[str]
    os_version: Optional[str]
    os_vendor: Optional[str]
    switch_name: Optional[str]
    switch_port: Optional[str]
    vlan_id: Optional[int]


class IPScanSummary(BaseModel):
    """Schema for IP scan summary"""
    total_scanned: int
    reachable: int
    unreachable: int
    new_devices: int
    changed_devices: int
    scan_duration: float
    results: List[IPScanResult]


# Statistics Schemas
class IPSubnetStatistics(BaseModel):
    """Schema for IP subnet statistics"""
    subnet_id: int
    subnet_name: str
    network: str
    total_ips: int
    available_ips: int
    used_ips: int
    reserved_ips: int
    offline_ips: int
    utilization_percent: float
    reachable_count: int
    last_scan_at: Optional[datetime]


class IPAMDashboard(BaseModel):
    """Schema for IPAM dashboard"""
    total_subnets: int
    total_ips: int
    used_ips: int
    available_ips: int
    offline_ips: int
    overall_utilization: float
    subnets: List[IPSubnetStatistics]
    recent_changes: List[IPScanHistoryResponse]
