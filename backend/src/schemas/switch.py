from pydantic import BaseModel, Field, IPvAnyAddress, validator
from typing import Optional, List, Literal
from datetime import datetime


class SwitchBase(BaseModel):
    """Base switch schema"""
    name: str = Field(..., min_length=1, max_length=100)
    ip_address: IPvAnyAddress
    vendor: str = Field(..., pattern="^(cisco|dell|alcatel|juniper|arista|hpe|huawei)$")
    model: Optional[str] = Field(None, max_length=100)
    serial_number: Optional[str] = Field(None, max_length=200)
    enabled: bool = True

    # CLI/SSH fields
    cli_enabled: bool = False
    cli_transport: Literal['ssh', 'telnet'] = 'ssh'
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
    
    # SNMP credentials
    snmp_enabled: bool = True
    snmp_version: str = Field(default="3", pattern="^(2c|3)$")
    snmp_port: int = Field(default=161, ge=1, le=65535)

    # 引用的 SNMP 凭据模板。填了就表示这台交换机的 SNMP 凭据整体取自模板，
    # 下面那些逐台填的用户名/口令都可以留空 —— 各校验器都据此放行。
    snmp_profile_id: Optional[int] = Field(None, ge=1)

    # SNMPv3 fields
    # 协议名允许带连字符：snmp_profiles 表按 RFC 7860 存 'SHA-256'/'AES-192'，
    # 而 switches 表历史上存 'SHA256'/'AES128'，两种写法都得收得下。
    snmp_username: Optional[str] = Field(None, min_length=1, max_length=100)
    snmp_auth_protocol: str = Field(default="SHA", pattern="^(MD5|SHA|SHA1|SHA-?224|SHA-?256|SHA-?384|SHA-?512)$")
    snmp_auth_password: Optional[str] = Field(None, min_length=8, description="At least 8 characters")
    snmp_priv_protocol: Optional[str] = Field(default="AES128", pattern="^(DES|AES|AES-?128|AES-?192|AES-?256)$")
    snmp_priv_password: Optional[str] = Field(None, min_length=8, description="At least 8 characters")

    # SNMPv2c field
    snmp_community: Optional[str] = None

    @validator('snmp_username')
    def validate_snmp_username(cls, v, values):
        # 引用模板时用户名来自模板，这里不再强制
        if values.get('snmp_version') == '3' and not values.get('snmp_profile_id') and not v:
            raise ValueError('snmp_username is required for SNMPv3')
        return v

    @validator('snmp_auth_password')
    def validate_snmp_auth_password(cls, v, values):
        # 引用模板时认证口令来自模板，这里不再强制
        if values.get('snmp_version') == '3' and not values.get('snmp_profile_id'):
            if not v or len(v) < 8:
                raise ValueError('snmp_auth_password must be at least 8 characters for SNMPv3')
        return v

    @validator('snmp_priv_password')
    def validate_snmp_priv_password(cls, v, values):
        if values.get('snmp_version') == '3' and v and len(v) < 8:
            raise ValueError('snmp_priv_password must be at least 8 characters for SNMPv3')
        return v

    @validator('snmp_community')
    def validate_snmp_community(cls, v, values):
        # 引用模板时团体字来自模板，这里不再强制
        if values.get('snmp_version') == '2c' and not values.get('snmp_profile_id') and not v:
            raise ValueError('snmp_community is required for SNMPv2c')
        return v


class SwitchUpdate(BaseModel):
    """Schema for updating a switch"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    ip_address: Optional[IPvAnyAddress] = None
    vendor: Optional[str] = Field(None, pattern="^(cisco|dell|alcatel|juniper)$")
    model: Optional[str] = Field(None, max_length=100)
    cli_enabled: Optional[bool] = None
    cli_transport: Optional[Literal['ssh', 'telnet']] = None
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
    # 显式传 null 表示解绑模板，改回用本机自带的凭据
    snmp_profile_id: Optional[int] = Field(None, ge=1)
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

    # Identifiers
    serial_number: Optional[str] = None

    # SNMP status
    snmp_enabled: bool = False
    snmp_version: Optional[str] = None
    snmp_port: Optional[int] = None
    snmp_username: Optional[str] = None
    snmp_auth_protocol: Optional[str] = None
    snmp_priv_protocol: Optional[str] = None
    has_snmp_credentials: bool = False

    # 引用的 SNMP 凭据模板（列表/详情页显示「凭据来源」用）。
    # snmp_profile_name 由 Switch 模型上的同名 property 提供，取不到模板时为 None，
    # 不会因为关系没预加载而抛异常。注意它只暴露模板**名字**，绝不带口令。
    snmp_profile_id: Optional[int] = None
    snmp_profile_name: Optional[str] = None

    # Connection status fields
    is_reachable: Optional[bool] = None
    response_time_ms: Optional[float] = None
    last_check_at: Optional[datetime] = None

    # Data collection status
    auto_collect_arp: bool = True
    auto_collect_mac: bool = True
    last_arp_collection_at: Optional[datetime] = None
    last_mac_collection_at: Optional[datetime] = None
    last_optical_collection_at: Optional[datetime] = None
    last_optical_success_at: Optional[datetime] = None
    last_successful_collection_at: Optional[datetime] = None  # True last success time (only advances on success)
    last_collection_status: Optional[str] = None
    last_collection_message: Optional[str] = None
    last_optical_collection_status: Optional[str] = None
    last_optical_collection_message: Optional[str] = None
    last_optical_modules_count: Optional[int] = None
    trunk_review_completed: bool = False
    trunk_review_completed_at: Optional[datetime] = None
    trunk_review_note: Optional[str] = None

    # Collection method per data type
    mac_collection_method: Optional[str] = None
    arp_collection_method: Optional[str] = None
    optical_collection_method: Optional[str] = None

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
