from pydantic import BaseModel, Field, IPvAnyAddress, model_validator
from typing import Optional, List, Literal
from datetime import datetime


class SwitchBase(BaseModel):
    """Base switch schema"""
    name: str = Field(..., min_length=1, max_length=100)
    ip_address: IPvAnyAddress
    vendor: str = Field(..., pattern="^(cisco|dell|alcatel|juniper|arista|hpe|huawei|h3c)$")
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
    auto_collect_topology: bool = True


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
    # 长度下限不能写在 Field 上：前端引用模板时这些字段会传空串，Field 约束
    # 在下面的条件校验器之前执行，会先报 min_length 错误。改为完全由校验器判断。
    snmp_username: Optional[str] = Field(None, max_length=100)
    snmp_auth_protocol: str = Field(default="SHA", pattern="^(MD5|SHA|SHA1|SHA-?224|SHA-?256|SHA-?384|SHA-?512)$")
    snmp_auth_password: Optional[str] = Field(None, description="At least 8 characters")
    snmp_priv_protocol: Optional[str] = Field(default="AES128", pattern="^(DES|AES|AES-?128|AES-?192|AES-?256)$")
    snmp_priv_password: Optional[str] = Field(None, description="At least 8 characters")

    # SNMPv2c field
    snmp_community: Optional[str] = None

    @model_validator(mode='after')
    def validate_snmp_credentials(self):
        """SNMP 凭据只在「这台设备确实要用 SNMP」时才必填。

        原来四条按字段拆开的校验只看 snmp_version，不看 snmp_enabled，
        导致 SNMP 关闭时仍要求填 SNMPv3 用户名/口令。
        这里按整体语义收敛成同一条规则，与 api/routes/snmp_config.py 保持一致：
        1. snmp_enabled=False —— 不用 SNMP，凭据一律不校验；
        2. 引用了凭据模板 —— 凭据以模板为准，逐台字段不校验；
        3. 否则按版本要求必填项。
        """
        if not self.snmp_enabled or self.snmp_profile_id:
            return self

        if self.snmp_version == '3':
            if not self.snmp_username:
                raise ValueError('snmp_username is required for SNMPv3 when SNMP is enabled')
            if not self.snmp_auth_password or len(self.snmp_auth_password) < 8:
                raise ValueError('snmp_auth_password must be at least 8 characters for SNMPv3 when SNMP is enabled')
            if self.snmp_priv_password and len(self.snmp_priv_password) < 8:
                raise ValueError('snmp_priv_password must be at least 8 characters')
        elif self.snmp_version == '2c':
            if not self.snmp_community:
                raise ValueError('snmp_community is required for SNMPv2c when SNMP is enabled')
        return self


class SwitchUpdate(BaseModel):
    """Schema for updating a switch"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    ip_address: Optional[IPvAnyAddress] = None
    vendor: Optional[str] = Field(None, pattern="^(cisco|dell|alcatel|juniper|arista|hpe|huawei|h3c)$")
    model: Optional[str] = Field(None, max_length=100)
    cli_enabled: Optional[bool] = None
    cli_transport: Optional[Literal['ssh', 'telnet']] = None
    ssh_port: Optional[int] = Field(None, ge=1, le=65535)
    # 更新接口里这些凭据字段都是「可选，留空则不改」。长度下限不能写在 Field 上：
    # 前端把留空的输入框当空串发过来时，Field 约束会先报
    # "String should have at least 1 character"，根本轮不到接口里的真值判断去忽略它。
    username: Optional[str] = Field(None, max_length=100)
    password: Optional[str] = None
    enable_password: Optional[str] = None
    connection_timeout: Optional[int] = Field(None, ge=5, le=300)
    enabled: Optional[bool] = None

    # Data collection settings
    auto_collect_arp: Optional[bool] = None
    auto_collect_mac: Optional[bool] = None
    auto_collect_topology: Optional[bool] = None

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

    @model_validator(mode='after')
    def validate_snmp_changes(self):
        """更新是部分更新：只校验这次「确实传了值」的 SNMP 字段。

        空串表示「留空不改」（接口层会忽略它），所以长度检查只看非空值；
        关闭 SNMP 或改为引用模板时，逐台口令没有意义，直接跳过，
        与创建接口的规则保持一致。
        """
        if self.snmp_enabled is False or self.snmp_profile_id:
            return self
        if self.snmp_auth_password and len(self.snmp_auth_password) < 8:
            raise ValueError('snmp_auth_password must be at least 8 characters')
        if self.snmp_priv_password and len(self.snmp_priv_password) < 8:
            raise ValueError('snmp_priv_password must be at least 8 characters')
        return self

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

    # Topology collection status
    sys_name: Optional[str] = None
    chassis_id: Optional[str] = None
    bridge_mac: Optional[str] = None
    topology_collection_method: Optional[str] = None
    last_topology_collection_at: Optional[datetime] = None
    last_topology_success_at: Optional[datetime] = None
    last_topology_collection_status: Optional[str] = None
    last_topology_collection_message: Optional[str] = None
    last_topology_neighbors_count: Optional[int] = None
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
