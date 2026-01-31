from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import INET, MACADDR
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from core.database import Base
import enum


class IPStatus(str, enum.Enum):
    """IP address status"""
    AVAILABLE = "available"      # 可用（未分配）
    USED = "used"               # 已使用
    RESERVED = "reserved"       # 保留
    OFFLINE = "offline"         # 离线


class IPSubnet(Base):
    """IP subnet model for IPAM"""

    __tablename__ = "ip_subnets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    network = Column(INET, nullable=False, unique=True, index=True)  # 网络地址，如 10.0.0.0/24
    description = Column(Text, nullable=True)
    vlan_id = Column(Integer, nullable=True)
    gateway = Column(INET, nullable=True)
    dns_servers = Column(String(200), nullable=True)  # 逗号分隔
    enabled = Column(Boolean, default=True, nullable=False)
    auto_scan = Column(Boolean, default=True, nullable=False)  # 是否自动扫描
    scan_interval = Column(Integer, default=3600, nullable=False)  # 扫描间隔（秒）
    last_scan_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    ip_addresses = relationship("IPAddress", back_populates="subnet", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<IPSubnet(id={self.id}, name='{self.name}', network='{self.network}')>"


class IPAddress(Base):
    """IP address model for IPAM"""

    __tablename__ = "ip_addresses"

    id = Column(Integer, primary_key=True, index=True)
    subnet_id = Column(Integer, ForeignKey("ip_subnets.id", ondelete="CASCADE"), nullable=False, index=True)
    ip_address = Column(INET, nullable=False, unique=True, index=True)
    status = Column(SQLEnum(IPStatus), default=IPStatus.AVAILABLE, nullable=False, index=True)

    # 基本信息
    hostname = Column(String(255), nullable=True)
    mac_address = Column(MACADDR, nullable=True, index=True)
    description = Column(Text, nullable=True)

    # 网络信息
    is_reachable = Column(Boolean, default=False, nullable=False)
    response_time = Column(Integer, nullable=True)  # Ping 响应时间（毫秒）

    # 操作系统信息
    os_type = Column(String(50), nullable=True)  # windows, linux, macos, etc.
    os_name = Column(String(100), nullable=True)  # Windows 11, Ubuntu 22.04, etc.
    os_version = Column(String(100), nullable=True)
    os_vendor = Column(String(100), nullable=True)  # Microsoft, Red Hat, etc.

    # 交换机关联
    switch_id = Column(Integer, ForeignKey("switches.id", ondelete="SET NULL"), nullable=True, index=True)
    switch_port = Column(String(50), nullable=True)
    vlan_id = Column(Integer, nullable=True)

    # 扫描信息
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_scan_at = Column(DateTime(timezone=True), nullable=True)
    scan_count = Column(Integer, default=0, nullable=False)

    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    subnet = relationship("IPSubnet", back_populates="ip_addresses")
    switch = relationship("Switch")
    scan_history = relationship("IPScanHistory", back_populates="ip_address", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<IPAddress(id={self.id}, ip='{self.ip_address}', status='{self.status}')>"


class IPScanHistory(Base):
    """IP scan history for tracking changes"""

    __tablename__ = "ip_scan_history"

    id = Column(Integer, primary_key=True, index=True)
    ip_address_id = Column(Integer, ForeignKey("ip_addresses.id", ondelete="CASCADE"), nullable=False, index=True)

    # 扫描结果
    is_reachable = Column(Boolean, nullable=False)
    response_time = Column(Integer, nullable=True)
    hostname = Column(String(255), nullable=True)
    mac_address = Column(MACADDR, nullable=True)
    os_type = Column(String(50), nullable=True)
    os_name = Column(String(100), nullable=True)

    # 变化检测
    status_changed = Column(Boolean, default=False, nullable=False)
    hostname_changed = Column(Boolean, default=False, nullable=False)
    os_changed = Column(Boolean, default=False, nullable=False)

    scanned_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    # Relationships
    ip_address = relationship("IPAddress", back_populates="scan_history")

    def __repr__(self):
        return f"<IPScanHistory(id={self.id}, ip_address_id={self.ip_address_id}, reachable={self.is_reachable})>"
