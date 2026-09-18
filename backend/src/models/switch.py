from typing import Any, Optional

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float, ForeignKey
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base

# 必须在这里显式导入 SNMPProfile，否则下面 relationship('SNMPProfile') 里的字符串
# 在本进程的 mapper registry 里找不到对应类，第一次查询时抛 InvalidRequestError。
# models/__init__.py 是空的，各进程按需导入模型子集：只导入 models.switch 的进程
# （例如某些采集/测试路径）此前根本不会加载 models.ipam。
# 方向是安全的：models/ipam.py 里引用 Switch 用的是字符串 relationship("Switch")，
# 不反向 import 本模块，所以这里不构成循环导入。
from models.ipam import SNMPProfile  # noqa: F401


class Switch(Base):
    """Switch model for storing network switch information"""

    __tablename__ = "switches"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    ip_address = Column(INET, nullable=False, unique=True, index=True)
    vendor = Column(String(50), nullable=False)  # 'cisco', 'dell', 'alcatel'
    model = Column(String(100), nullable=True)
    serial_number = Column(String(200), nullable=True)  # Chassis serial from SNMP ENTITY-MIB

    # SSH/CLI fields
    cli_enabled = Column(Boolean, default=False, nullable=False)  # Enable CLI/SSH authentication
    cli_transport = Column(String(10), default='ssh', nullable=False)
    ssh_port = Column(Integer, default=22, nullable=True)
    username = Column(String(100), nullable=True)
    password_encrypted = Column(Text, nullable=True)
    enable_password_encrypted = Column(Text, nullable=True)
    connection_timeout = Column(Integer, default=30, nullable=True)

    enabled = Column(Boolean, default=True, nullable=False, index=True)

    # Ping status fields
    is_reachable = Column(Boolean, nullable=True, index=True)  # NULL = not checked yet
    last_check_at = Column(DateTime(timezone=True), nullable=True, index=True)
    response_time_ms = Column(Float, nullable=True)  # Ping response time in milliseconds

    # SNMP configuration fields (primary authentication method)
    snmp_enabled = Column(Boolean, default=True, nullable=False)
    snmp_version = Column(String(10), default='3', nullable=False)  # '2c' or '3'
    snmp_port = Column(Integer, default=161, nullable=False)
    snmp_username = Column(String(100), nullable=True)  # For SNMPv3
    snmp_auth_protocol = Column(String(20), nullable=True)  # MD5, SHA, SHA256, etc.
    snmp_auth_password_encrypted = Column(Text, nullable=True)
    snmp_priv_protocol = Column(String(20), nullable=True)  # DES, AES, AES128, etc.
    snmp_priv_password_encrypted = Column(Text, nullable=True)
    snmp_community = Column(String(100), nullable=True)  # For SNMPv2c

    # 引用的 SNMP 凭据模板。非空时这台交换机的 SNMP 凭据**整体以模板为准**，
    # 上面的 snmp_username/snmp_auth_protocol/*_encrypted 列被忽略（但保留不动，
    # 便于随时解绑回退）。目的是让口令只在模板上维护一处 —— 200 多台各存一份时，
    # 改口令漏改一台的症状是设备侧回 WrongDigest，和「口令配错」完全一样，极难查。
    snmp_profile_id = Column(
        Integer,
        ForeignKey('snmp_profiles.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    # lazy='selectin'：采集/测试都是异步会话，惰性加载会在属性访问的那一刻抛
    # MissingGreenlet。这里随父对象一起预加载，代价只是一条 JOIN。
    snmp_profile = relationship('SNMPProfile', lazy='selectin')

    # Data collection settings
    auto_collect_arp = Column(Boolean, default=True, nullable=False)  # Auto collect ARP table
    auto_collect_mac = Column(Boolean, default=True, nullable=False)  # Auto collect MAC table
    last_arp_collection_at = Column(DateTime(timezone=True), nullable=True)  # Last ARP collection time
    last_mac_collection_at = Column(DateTime(timezone=True), nullable=True)  # Last MAC collection time
    last_optical_collection_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_optical_success_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_successful_collection_at = Column(DateTime(timezone=True), nullable=True, index=True)  # Last successful ARP/MAC collection time
    last_collection_status = Column(String(50), nullable=True)  # success, failed, partial
    last_collection_message = Column(Text, nullable=True)  # Collection result message
    last_optical_collection_status = Column(String(50), nullable=True)
    last_optical_collection_message = Column(Text, nullable=True)
    last_optical_modules_count = Column(Integer, nullable=True)

    # Collection method preferences (ARP/MAC use per-vendor auto-detection with SNMP/CLI fallback;
    # optical modules can still learn per-device SNMP/CLI preference)
    mac_collection_method = Column(String(10), default='auto')
    arp_collection_method = Column(String(10), default='auto')
    optical_collection_method = Column(String(10), default='auto')  # 'snmp', 'cli', 'auto', 'manual'

    # Manual override flags (set by admin via UI)
    mac_method_override = Column(Boolean, default=False)  # True if admin manually set method
    arp_method_override = Column(Boolean, default=False)
    optical_method_override = Column(Boolean, default=False)

    # Collection performance metrics
    mac_collection_success_count = Column(Integer, default=0)
    arp_collection_success_count = Column(Integer, default=0)
    optical_collection_success_count = Column(Integer, default=0)
    mac_collection_fail_count = Column(Integer, default=0)
    arp_collection_fail_count = Column(Integer, default=0)
    optical_collection_fail_count = Column(Integer, default=0)

    # Manual trunk-review workflow
    trunk_review_completed = Column(Boolean, default=False, nullable=False, index=True)
    trunk_review_completed_at = Column(DateTime(timezone=True), nullable=True)
    trunk_review_note = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<Switch(id={self.id}, name='{self.name}', ip='{self.ip_address}')>"

    @property
    def has_snmp_credentials(self) -> bool:
        """
        SNMP 已启用且凭据可用（本机自带的口令，或引用模板上带的口令）。

        注意不能简化成 `self.snmp_auth_password_encrypted` —— 引用模板的交换机
        这一列是空的，那样判断会让界面上所有引用模板的交换机都显示「未配置凭据」。
        """
        if not self.snmp_enabled:
            return False
        if self.snmp_profile_id:
            profile = _safe_profile(self)
            return bool(profile and (profile.auth_password_encrypted or profile.community_encrypted))
        return bool(self.snmp_auth_password_encrypted)

    @property
    def snmp_profile_name(self) -> Optional[str]:
        """
        引用的 SNMP 模板名字，供列表页/详情页显示「凭据来源」。

        只暴露模板**名字**，绝不带口令。关系取不到时返回 None 而不是抛异常 ——
        刚创建还没 flush 的对象、或走裸 SQL 拿到的行，关系可能尚未加载，异步上下文
        里直接访问会抛 MissingGreenlet，那会把整个列表接口打挂。
        """
        profile = _safe_profile(self)
        return getattr(profile, 'name', None) if profile is not None else None


def _safe_profile(switch: Any) -> Any:
    """
    安全地取出交换机引用的 SNMP 模板，取不到一律返回 None。

    关系用 lazy='selectin' 声明，正常查询出来的交换机都是预加载好的；但刚创建还没
    flush 的对象、或走裸 SQL 拿到的行，关系可能尚未加载，异步上下文里直接访问会抛
    MissingGreenlet。这里统一兜住，退化成「未引用模板」。
    """
    if not getattr(switch, 'snmp_profile_id', None):
        return None
    try:
        return getattr(switch, 'snmp_profile', None)
    except Exception:
        return None
