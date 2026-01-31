from pydantic import BaseModel, Field, IPvAnyAddress
from typing import Optional
from datetime import datetime


class SwitchBase(BaseModel):
    """Base switch schema"""
    name: str = Field(..., min_length=1, max_length=100)
    ip_address: IPvAnyAddress
    vendor: str = Field(..., pattern="^(cisco|dell|alcatel)$")
    model: Optional[str] = Field(None, max_length=100)
    role: str = Field(default='access', pattern="^(core|aggregation|access)$")
    priority: int = Field(default=50, ge=1, le=100, description="1=highest priority, 100=lowest")
    ssh_port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(..., min_length=1, max_length=100)
    connection_timeout: int = Field(default=30, ge=5, le=300)
    enabled: bool = True


class SwitchCreate(SwitchBase):
    """Schema for creating a switch"""
    password: str = Field(..., min_length=1)
    enable_password: Optional[str] = None


class SwitchUpdate(BaseModel):
    """Schema for updating a switch"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    ip_address: Optional[IPvAnyAddress] = None
    vendor: Optional[str] = Field(None, pattern="^(cisco|dell|alcatel)$")
    model: Optional[str] = Field(None, max_length=100)
    role: Optional[str] = Field(None, pattern="^(core|aggregation|access)$")
    priority: Optional[int] = Field(None, ge=1, le=100)
    ssh_port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = Field(None, min_length=1, max_length=100)
    password: Optional[str] = Field(None, min_length=1)
    enable_password: Optional[str] = None
    connection_timeout: Optional[int] = Field(None, ge=5, le=300)
    enabled: Optional[bool] = None


class SwitchResponse(SwitchBase):
    """Schema for switch response"""
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SwitchTestResponse(BaseModel):
    """Schema for switch connection test response"""
    success: bool
    message: str
    details: Optional[dict] = None
