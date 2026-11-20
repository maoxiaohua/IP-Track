"""
Schemas for Switch Command Templates
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SwitchCommandTemplateBase(BaseModel):
    """Base schema for switch command template"""
    vendor: str = Field(..., max_length=50, description="Switch vendor (e.g., 'alcatel', 'dell', 'cisco')")
    model_pattern: str = Field(..., max_length=100, description="Model pattern to match (e.g., '7220', 'os10')")
    name_pattern: Optional[str] = Field(None, max_length=100, description="Optional switch name pattern to match")
    device_type: str = Field(..., max_length=50, description="NetMiko device type (e.g., 'nokia_srl', 'dell_os10')")

    arp_command: Optional[str] = Field(None, description="CLI command to collect ARP table")
    arp_parser_type: Optional[str] = Field(None, max_length=50, description="Parser type for ARP output")
    arp_enabled: bool = Field(True, description="Enable ARP collection via CLI")

    mac_command: Optional[str] = Field(None, description="CLI command to collect MAC table")
    mac_parser_type: Optional[str] = Field(None, max_length=50, description="Parser type for MAC output")
    mac_enabled: bool = Field(True, description="Enable MAC collection via CLI")

    lldp_command: Optional[str] = Field(None, description="CLI command to collect LLDP neighbors")
    lldp_parser_type: Optional[str] = Field(None, max_length=50, description="Parser type for LLDP output")
    lldp_enabled: bool = Field(True, description="Enable LLDP neighbor collection via CLI")

    cdp_command: Optional[str] = Field(None, description="CLI command to collect CDP neighbors")
    cdp_parser_type: Optional[str] = Field(None, max_length=50, description="Parser type for CDP output")
    cdp_enabled: bool = Field(True, description="Enable CDP neighbor collection via CLI")

    interfaces_command: Optional[str] = Field(None, description="CLI command to list interfaces")
    interfaces_parser_type: Optional[str] = Field(None, max_length=50, description="Parser type for interface output")
    interfaces_enabled: bool = Field(True, description="Enable interface inventory collection via CLI")

    priority: int = Field(100, ge=0, le=1000, description="Priority (higher = match first)")
    description: Optional[str] = Field(None, description="Template description")
    enabled: bool = Field(True, description="Enable this template")


class SwitchCommandTemplateCreate(SwitchCommandTemplateBase):
    """Schema for creating a new command template"""
    pass


class SwitchCommandTemplateUpdate(BaseModel):
    """Schema for updating a command template"""
    vendor: Optional[str] = Field(None, max_length=50)
    model_pattern: Optional[str] = Field(None, max_length=100)
    name_pattern: Optional[str] = Field(None, max_length=100)
    device_type: Optional[str] = Field(None, max_length=50)

    arp_command: Optional[str] = None
    arp_parser_type: Optional[str] = Field(None, max_length=50)
    arp_enabled: Optional[bool] = None

    mac_command: Optional[str] = None
    mac_parser_type: Optional[str] = Field(None, max_length=50)
    mac_enabled: Optional[bool] = None

    lldp_command: Optional[str] = None
    lldp_parser_type: Optional[str] = Field(None, max_length=50)
    lldp_enabled: Optional[bool] = None

    cdp_command: Optional[str] = None
    cdp_parser_type: Optional[str] = Field(None, max_length=50)
    cdp_enabled: Optional[bool] = None

    interfaces_command: Optional[str] = None
    interfaces_parser_type: Optional[str] = Field(None, max_length=50)
    interfaces_enabled: Optional[bool] = None

    priority: Optional[int] = Field(None, ge=0, le=1000)
    description: Optional[str] = None
    enabled: Optional[bool] = None


class SwitchCommandTemplateResponse(SwitchCommandTemplateBase):
    """Schema for command template response"""
    id: int
    is_builtin: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
