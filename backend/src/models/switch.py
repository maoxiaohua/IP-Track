from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.sql import func
from core.database import Base


class Switch(Base):
    """Switch model for storing network switch information"""

    __tablename__ = "switches"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    ip_address = Column(INET, nullable=False, unique=True, index=True)
    vendor = Column(String(50), nullable=False)  # 'cisco', 'dell', 'alcatel'
    model = Column(String(100), nullable=True)

    # SSH/CLI fields
    cli_enabled = Column(Boolean, default=False, nullable=False)  # Enable CLI/SSH authentication
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

    # Data collection settings
    auto_collect_arp = Column(Boolean, default=True, nullable=False)  # Auto collect ARP table
    auto_collect_mac = Column(Boolean, default=True, nullable=False)  # Auto collect MAC table
    last_arp_collection_at = Column(DateTime(timezone=True), nullable=True)  # Last ARP collection time
    last_mac_collection_at = Column(DateTime(timezone=True), nullable=True)  # Last MAC collection time
    last_collection_status = Column(String(50), nullable=True)  # success, failed, partial
    last_collection_message = Column(Text, nullable=True)  # Collection result message

    # Collection method preferences (learned from successful collections)
    mac_collection_method = Column(String(10), default='auto')  # 'snmp', 'cli', 'auto', 'manual'
    arp_collection_method = Column(String(10), default='auto')  # 'snmp', 'cli', 'auto', 'manual'
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

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<Switch(id={self.id}, name='{self.name}', ip='{self.ip_address}')>"
