from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class QueryHistoryResponse(BaseModel):
    """Schema for query history response"""
    id: int
    target_ip: str
    found_mac: Optional[str] = None
    switch_id: Optional[int] = None
    port_name: Optional[str] = None
    vlan_id: Optional[int] = None
    query_status: str
    error_message: Optional[str] = None
    query_time_ms: Optional[int] = None
    queried_at: datetime

    class Config:
        from_attributes = True


class QueryHistoryListResponse(BaseModel):
    """Schema for paginated query history list"""
    total: int
    page: int
    page_size: int
    items: list[QueryHistoryResponse]
