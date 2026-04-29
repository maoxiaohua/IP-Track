from pydantic import BaseModel, Field, IPvAnyAddress, field_serializer
from typing import Optional, List, Dict, Any
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

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        # Convert IP objects to strings
        if "network" in data and data["network"] is not None:
            data["network"] = str(data["network"])
        if "gateway" in data and data["gateway"] is not None:
            data["gateway"] = str(data["gateway"])
        return data
    



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
    hostname_source: Optional[str] = None
    dns_name: Optional[str] = None
    system_name: Optional[str] = None
    machine_type: Optional[str] = None
    vendor: Optional[str] = None
    contact: Optional[str] = None
    location: Optional[str] = None
    os_type: Optional[str]
    os_name: Optional[str]
    os_version: Optional[str]
    os_vendor: Optional[str]
    switch_id: Optional[int]
    switch_port: Optional[str]
    vlan_id: Optional[int]
    last_seen_at: Optional[datetime]
    last_boot_time: Optional[datetime]
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


class IPAddressListResponse(BaseModel):
    """Paginated IP address list response"""
    items: List[IPAddressDetailResponse]
    total: int


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
    os_version: Optional[str] = None
    os_vendor: Optional[str] = None
    switch_id: Optional[int]
    switch_port: Optional[str]
    vlan_id: Optional[int]
    status_changed: bool
    hostname_changed: bool
    os_changed: bool
    mac_changed: bool
    switch_changed: bool
    port_changed: bool
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
    subnet_id: Optional[int] = None
    subnet_last_scan_at: Optional[datetime] = None
    total_scanned: int
    reachable: int
    unreachable: int
    new_devices: int
    changed_devices: int
    scan_duration: float
    results: List[IPScanResult] = Field(default_factory=list)
    message: Optional[str] = None  # Optional message for async scan status


class IPAMScanStatusResponse(BaseModel):
    """Live status snapshot for an IPAM scan."""
    running: bool
    session_id: Optional[str] = None
    source: Optional[str] = None
    scan_type: Optional[str] = None
    current_phase: str
    phase_label: str
    message: Optional[str] = None
    error: Optional[str] = None
    subnet_id: Optional[int] = None
    subnet_name: Optional[str] = None
    subnet_network: Optional[str] = None
    current_subnet_index: int = 0
    total_subnets: int = 0
    completed_subnets: int = 0
    current_subnet_total_ips: int = 0
    current_subnet_completed_ips: int = 0
    current_subnet_pending_ips: int = 0
    current_subnet_reachable_ips: int = 0
    current_subnet_unreachable_ips: int = 0
    current_subnet_enrichment_total: int = 0
    current_subnet_enrichment_completed: int = 0
    current_subnet_last_scan_at: Optional[datetime] = None
    total_ips_scanned: int = 0
    started_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_completed_at: Optional[datetime] = None
    summary: Optional[Dict[str, Any]] = None


class IPAMScanStartResponse(BaseModel):
    """Response returned when an async IPAM scan is launched."""
    session_id: str
    message: str
    status: IPAMScanStatusResponse


# Statistics Schemas
class IPSubnetStatistics(BaseModel):
    """Schema for IP subnet statistics"""
    subnet_id: int
    subnet_name: str
    network: str
    description: Optional[str] = None
    vlan_id: Optional[int] = None
    gateway: Optional[str] = None
    dns_servers: Optional[str] = None
    enabled: bool = True
    auto_scan: bool = True
    scan_interval: int = 3600
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


# Batch Import Schemas
class IPSubnetBatchItem(BaseModel):
    """Schema for single subnet in batch import"""
    name: str = Field(..., min_length=1, max_length=100, description="Subnet name")
    network: str = Field(..., description="Network in CIDR format, e.g., 10.0.0.0/24")
    description: Optional[str] = Field(None, description="Subnet description")
    vlan_id: Optional[int] = Field(None, ge=1, le=4094, description="VLAN ID")
    gateway: Optional[str] = Field(None, description="Gateway IP address")
    dns_servers: Optional[str] = Field(None, description="Comma-separated DNS servers")
    enabled: bool = Field(default=True, description="Enable subnet")
    auto_scan: bool = Field(default=True, description="Enable auto scan")
    scan_interval: int = Field(default=3600, ge=300, le=86400, description="Scan interval in seconds")


class IPSubnetBatchImportRequest(BaseModel):
    """Schema for batch import request"""
    subnets: List[IPSubnetBatchItem] = Field(..., min_items=1, max_items=100, description="List of subnets to import (max 100)")
    skip_existing: bool = Field(default=True, description="Skip subnets with duplicate network addresses")


class IPSubnetBatchImportResult(BaseModel):
    """Schema for batch import result"""
    total: int = Field(..., description="Total number of subnets to import")
    success: int = Field(..., description="Number of successfully imported subnets")
    failed: int = Field(..., description="Number of failed imports")
    skipped: int = Field(..., description="Number of skipped subnets (duplicates)")
    errors: List[dict] = Field(default=[], description="List of errors with details")
    imported_ids: List[int] = Field(default=[], description="List of successfully imported subnet IDs")


# Network Search Schemas
class NetworkSearchRequest(BaseModel):
    """Schema for network search request"""
    network: str = Field(..., description="Network in CIDR format, e.g., 10.101.63.0/24")


class NetworkSearchIPResult(BaseModel):
    """Individual IP result in network search"""
    ip_address: str
    status: IPStatus
    is_reachable: Optional[bool] = None
    hostname: Optional[str] = None
    mac_address: Optional[str] = None
    switch_name: Optional[str] = None
    switch_port: Optional[str] = None
    description: Optional[str] = None
    last_seen_at: Optional[datetime] = None


class NetworkSearchResponse(BaseModel):
    """Schema for network search response"""
    network: str
    network_address: str
    broadcast_address: str
    netmask: str
    total_ips: int
    usable_ips: int
    first_usable: str
    last_usable: str
    ips: List[NetworkSearchIPResult]
    in_ipam: bool = Field(..., description="Whether this network is managed in IPAM")
    subnet_id: Optional[int] = None
    subnet_name: Optional[str] = None


# Subnet Calculator Schemas
class SubnetCalculatorRequest(BaseModel):
    """Schema for subnet calculator request"""
    ip_address: str = Field(..., description="IP address (e.g., 10.101.63.25)")
    netmask: Optional[str] = Field(None, description="Subnet mask (e.g., 255.255.255.0) or CIDR prefix (e.g., 24)")


class SubnetCalculatorResponse(BaseModel):
    """Schema for subnet calculator response"""
    ip_address: str
    cidr: str
    network_address: str
    broadcast_address: str
    netmask: str
    wildcard_mask: str
    first_usable_ip: str
    last_usable_ip: str
    total_hosts: int
    usable_hosts: int
    ip_class: str
    is_private: bool
    binary_netmask: str
    binary_ip: str
    hex_ip: str
