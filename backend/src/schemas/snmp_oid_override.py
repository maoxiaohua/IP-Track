from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SnmpOidOverrideBase(BaseModel):
    vendor: str = Field(..., max_length=50)
    model_pattern: Optional[str] = Field(None, max_length=100)
    oid_role: str = Field(..., max_length=30)
    oid_value: str = Field(..., max_length=255)
    description: Optional[str] = None
    priority: int = Field(100, ge=0, le=1000)
    enabled: bool = True


class SnmpOidOverrideCreate(SnmpOidOverrideBase):
    pass


class SnmpOidOverrideUpdate(BaseModel):
    vendor: Optional[str] = Field(None, max_length=50)
    model_pattern: Optional[str] = Field(None, max_length=100)
    oid_role: Optional[str] = Field(None, max_length=30)
    oid_value: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    priority: Optional[int] = Field(None, ge=0, le=1000)
    enabled: Optional[bool] = None


class SnmpOidOverrideResponse(SnmpOidOverrideBase):
    id: int
    is_builtin: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
