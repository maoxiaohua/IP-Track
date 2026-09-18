from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# SNMP 协议取值清单。
#
# 同一份清单在系统里有三处：数据库 CHECK 约束（snmp_profiles 表，见迁移 029 与
# database/init/09_enhance_ipam_solarwinds.sql）、这里、以及前端
# views/SNMPProfiles.vue 的下拉框。三处必须一致。
#
# 之前就是数据库那份漏了 AES-128，而界面上下拉框的第一项恰好是「AES-128
# (Recommended)」，用户在界面上正常选一项、保存，撞的是数据库约束，收到的是一句
# 500 加一整段 SQL，看不出是自己选错了还是系统坏了。在这里拦一道，同样的输入
# 会变成一条说得清的 422。
#
# 刻意写得和数据库**严格相等**：既不分大小写、也不接受 AES128 这种省掉连字符的
# 写法。数据库那一列的比较就是区分大小写、区分连字符的，这里放宽只会把同一个错误
# 推迟到数据库再炸一次，那就白拦了。
AUTH_PROTOCOLS = ('MD5', 'SHA', 'SHA-224', 'SHA-256', 'SHA-384', 'SHA-512')
PRIV_PROTOCOLS = ('DES', 'AES', 'AES-128', 'AES-192', 'AES-256')

AUTH_PROTOCOL_PATTERN = r'^(' + '|'.join(AUTH_PROTOCOLS) + r')$'
PRIV_PROTOCOL_PATTERN = r'^(' + '|'.join(PRIV_PROTOCOLS) + r')$'


class SNMPProfileBase(BaseModel):
    """Base SNMP profile schema"""
    name: str = Field(..., min_length=1, max_length=100, description="Profile name")
    version: str = Field(default='v3', description="SNMP version: v2c or v3")

    # SNMPv3 Authentication
    username: Optional[str] = Field(None, max_length=100, description="SNMPv3 username")
    auth_protocol: Optional[str] = Field(
        None, pattern=AUTH_PROTOCOL_PATTERN,
        description="Auth protocol: " + ", ".join(AUTH_PROTOCOLS),
    )
    auth_password: Optional[str] = Field(None, description="Auth password (will be encrypted)")

    # SNMPv3 Privacy
    priv_protocol: Optional[str] = Field(
        None, pattern=PRIV_PROTOCOL_PATTERN,
        description="Privacy protocol: " + ", ".join(PRIV_PROTOCOLS),
    )
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
    # 协议字段的 pattern 必须和 SNMPProfileBase 保持一致：更新走的是这个模型，
    # 只在 Base 上加校验的话，改模板时照样能把非法值送到数据库。
    auth_protocol: Optional[str] = Field(None, pattern=AUTH_PROTOCOL_PATTERN)
    auth_password: Optional[str] = None
    priv_protocol: Optional[str] = Field(None, pattern=PRIV_PROTOCOL_PATTERN)
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

    # 引用了这个模板的交换机台数。模板列表页要显示它：删模板前的守卫看这个数，
    # 改口令前也该看这个数 —— 「这一改会影响多少台」是操作前必须先知道的事。
    switch_count: Optional[int] = 0

    class Config:
        from_attributes = True


class SNMPProfileAdoptRequest(BaseModel):
    """把已有交换机改挂到某个模板上（一次性迁移）"""

    # 默认只统计不写库。历史设备是几百台规模，批量改凭据来源这种事必须先看清楚
    # 会动到哪些台、有几台不匹配，再决定要不要真做。
    dry_run: bool = Field(default=True, description="Only report what would change, do not write")

    # 留空 = 处理所有未引用模板的交换机；给了就只处理这些
    switch_ids: Optional[list[int]] = Field(None, description="Limit to these switch IDs")


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
