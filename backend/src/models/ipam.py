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


class HostnameSource(str, enum.Enum):
    """Hostname source - priority: SNMP > DNS > ARP > MANUAL"""
    SNMP = "SNMP"        # From SNMP sysName (OID 1.3.6.1.2.1.1.5.0)
    DNS = "DNS"          # From DNS reverse lookup (PTR record)
    ARP = "ARP"          # From switch ARP table
    MANUAL = "MANUAL"    # Manually entered by user


class SNMPProfile(Base):
    """SNMP profile for device identification and monitoring"""

    __tablename__ = "snmp_profiles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    version = Column(String(10), default='v3', nullable=False)  # v2c or v3

    # SNMPv3 Authentication
    username = Column(String(100), nullable=True)
    auth_protocol = Column(String(20), nullable=True)  # MD5, SHA, SHA-256, etc.
    auth_password_encrypted = Column(Text, nullable=True)

    # SNMPv3 Privacy
    priv_protocol = Column(String(20), nullable=True)  # DES, AES, AES-256, etc.
    priv_password_encrypted = Column(Text, nullable=True)

    # SNMPv2c Community
    community_encrypted = Column(Text, nullable=True)

    # Common settings
    port = Column(Integer, default=161, nullable=False)
    timeout = Column(Integer, default=5, nullable=False)
    retries = Column(Integer, default=3, nullable=False)

    # Metadata
    description = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    subnets = relationship("IPSubnet", back_populates="snmp_profile")

    def __repr__(self):
        return f"<SNMPProfile(id={self.id}, name='{self.name}', version='{self.version}')>"


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
    snmp_profile_id = Column(Integer, ForeignKey("snmp_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    last_scan_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    ip_addresses = relationship("IPAddress", back_populates="subnet", cascade="all, delete-orphan")
    snmp_profile = relationship("SNMPProfile", back_populates="subnets")

    def __repr__(self):
        return f"<IPSubnet(id={self.id}, name='{self.name}', network='{self.network}')>"


class IPAddress(Base):
    """IP address model for IPAM - SolarWinds-style"""

    __tablename__ = "ip_addresses"

    id = Column(Integer, primary_key=True, index=True)
    subnet_id = Column(Integer, ForeignKey("ip_subnets.id", ondelete="CASCADE"), nullable=False, index=True)
    ip_address = Column(INET, nullable=False, unique=True, index=True)
    status = Column(
        SQLEnum(IPStatus, values_callable=lambda x: [e.value for e in x], name='ipstatus', native_enum=True, create_constraint=False),
        default=IPStatus.AVAILABLE,
        nullable=False,
        index=True
    )

    # Hostname information (SolarWinds-style)
    hostname = Column(String(255), nullable=True)  # Best hostname (from hostname_source priority)
    hostname_source = Column(String(20), nullable=True, index=True)
    dns_name = Column(String(255), nullable=True, index=True)  # From DNS PTR lookup
    system_name = Column(String(255), nullable=True, index=True)  # From SNMP sysName

    # Device information
    mac_address = Column(MACADDR, nullable=True, index=True)
    vendor = Column(String(100), nullable=True)  # MAC vendor or device vendor
    description = Column(Text, nullable=True)
    contact = Column(String(255), nullable=True)  # From SNMP sysContact
    location = Column(String(255), nullable=True)  # From SNMP sysLocation
    machine_type = Column(String(255), nullable=True)  # From SNMP or OS detection (increased from 100)

    # Network information
    is_reachable = Column(Boolean, default=False, nullable=False)
    response_time = Column(Integer, nullable=True)  # Ping 响应时间（毫秒）

    # Operating system information
    os_type = Column(String(50), nullable=True)  # windows, linux, macos, etc.
    os_name = Column(String(100), nullable=True)  # Windows 11, Ubuntu 22.04, etc.
    os_version = Column(String(100), nullable=True)
    os_vendor = Column(String(100), nullable=True)  # Microsoft, Red Hat, etc.

    # 交换机关联
    switch_id = Column(Integer, ForeignKey("switches.id", ondelete="SET NULL"), nullable=True, index=True)
    switch_port = Column(String(50), nullable=True)
    vlan_id = Column(Integer, nullable=True)

    # Timing information (SolarWinds-style)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)  # Last successful ping - CRITICAL for "Last Response"
    last_boot_time = Column(DateTime(timezone=True), nullable=True)  # From SNMP sysUpTime
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
