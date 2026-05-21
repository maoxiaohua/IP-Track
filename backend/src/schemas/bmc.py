"""
Pydantic schemas for BMC Reset feature.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ── Server Schemas ──────────────────────────────────────────────

class BMCServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Server display name")
    host: str = Field(..., min_length=1, max_length=255, description="IP address or hostname")
    username: str = Field(..., min_length=1, max_length=100, description="IPMI username")
    password: Optional[str] = Field(None, max_length=255, description="Per-server IPMI password (plaintext, encrypted at storage)")
    use_global_credentials: bool = Field(True, description="Use global IPMI credentials instead of per-server ones")
    credential_profile_id: Optional[int] = Field(None, description="Use a named credential profile (overrides use_global_credentials when set)")
    enabled: bool = Field(True, description="Enable this server for BMC reset")
    notes: Optional[str] = Field(None, description="Optional notes")


class BMCServerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    host: Optional[str] = Field(None, min_length=1, max_length=255)
    username: Optional[str] = Field(None, min_length=1, max_length=100)
    password: Optional[str] = Field(None, max_length=255)
    use_global_credentials: Optional[bool] = None
    credential_profile_id: Optional[int] = Field(None, description="Use a named credential profile (overrides use_global_credentials when set)")
    enabled: Optional[bool] = None
    notes: Optional[str] = None


class BMCServerResponse(BaseModel):
    id: int
    name: str
    host: str
    username: str
    use_global_credentials: bool
    credential_profile_id: Optional[int] = None
    credential_profile_name: Optional[str] = None
    enabled: bool
    notes: Optional[str] = None
    last_reset_at: Optional[datetime] = None
    last_reset_result: Optional[str] = None
    serial_number: Optional[str] = None
    bmc_firmware_version: Optional[str] = None
    bmc_info_updated_at: Optional[datetime] = None
    verified: bool = False
    verify_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BMCServerListResponse(BaseModel):
    items: List[BMCServerResponse]
    total: int


# ── Reset History Schemas ───────────────────────────────────────

class BMCResetHistoryResponse(BaseModel):
    id: int
    bmc_server_id: int
    server_name: str
    server_host: str
    status: str
    error_category: Optional[str] = None
    error_message: Optional[str] = None
    attempts_made: int = 1
    duration_ms: Optional[int] = None
    ipmi_command: Optional[str] = None
    triggered_by: str = "manual"
    created_at: datetime

    model_config = {"from_attributes": True}


class BMCResetHistoryListResponse(BaseModel):
    items: List[BMCResetHistoryResponse]
    total: int


# ── Reset Request Schemas ───────────────────────────────────────

class BMCResetRequest(BaseModel):
    server_ids: List[int] = Field(..., min_length=1, description="Server IDs to reset")


class BMCResetStartResponse(BaseModel):
    session_id: str
    message: str
    total_servers: int


# ── Global Credentials Schemas ──────────────────────────────────

class BMCGlobalCredentialsResponse(BaseModel):
    username: str
    password_set: bool


class BMCGlobalCredentialsUpdate(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: Optional[str] = Field(None, max_length=255, description="Leave empty to keep current password")


# ── BMC Info Schemas ─────────────────────────────────────────────

class BMCInfoResponse(BaseModel):
    """Result of querying BMC FRU and MC info via IPMI."""
    server_id: int
    serial_number: Optional[str] = None
    bmc_firmware_version: Optional[str] = None
    product_name: Optional[str] = None
    manufacturer: Optional[str] = None
    fru_raw: Optional[str] = None
    mc_info_raw: Optional[str] = None


# ── Batch Import Schemas ────────────────────────────────────────

class BMCBatchImportRequest(BaseModel):
    """Batch import servers from an IP range or list with shared credentials."""
    ip_start: Optional[str] = Field(None, description="Starting IP address, e.g. 10.57.135.1")
    ip_end: Optional[str] = Field(None, description="Ending IP address, e.g. 10.57.135.100")
    ips: Optional[str] = Field(None, description="Comma- or newline-separated list of IPs (takes priority over ip_start/ip_end)")
    username: str = Field(..., min_length=1, max_length=100, description="IPMI username for all servers")
    password: Optional[str] = Field(None, max_length=255, description="IPMI password (if empty, servers will use global credentials)")
    use_global_credentials: bool = Field(True, description="Use global credentials instead of the provided username/password")
    credential_profile_id: Optional[int] = Field(None, description="Use a named credential profile (overrides use_global_credentials when set)")
    enabled: bool = Field(True, description="Enable imported servers for BMC reset")


class BMCBatchImportResult(BaseModel):
    """Result of a batch import operation."""
    total: int
    created: int
    skipped: int
    errors: List[str] = []
    servers: List[BMCServerResponse] = []


# ── Credential Profile Schemas ──────────────────────────────────

class BMCCredentialProfileCreate(BaseModel):
    """Create a named credential profile."""
    name: str = Field(..., min_length=1, max_length=100)
    username: str = Field(..., min_length=1, max_length=100)
    password: Optional[str] = Field(None, max_length=255)


class BMCCredentialProfileUpdate(BaseModel):
    """Update a named credential profile."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    username: Optional[str] = Field(None, min_length=1, max_length=100)
    password: Optional[str] = Field(None, max_length=255, description="Leave empty to keep current password")


class BMCCredentialProfileResponse(BaseModel):
    """Credential profile for API response (password never exposed)."""
    id: int
    name: str
    username: str
    password_set: bool
    server_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
