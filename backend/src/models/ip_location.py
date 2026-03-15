from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import INET, MACADDR
from sqlalchemy.sql import func
from core.database import Base


class IPLocation(Base):
    """IP location mapping - final results of IP-to-switch-port matching"""

    __tablename__ = "ip_location"

    id = Column(Integer, primary_key=True, index=True)
    ip_address = Column(INET, nullable=False, unique=True, index=True)
    mac_address = Column(MACADDR, nullable=False, index=True)

    # Location information
    switch_id = Column(Integer, ForeignKey("switches.id", ondelete="CASCADE"), nullable=False, index=True)
    port_name = Column(String(50), nullable=False)
    vlan_id = Column(Integer, nullable=True)

    # Analysis metadata
    confidence_score = Column(Float, default=0.0, nullable=False, index=True)  # 0-100
    detection_method = Column(String(50), nullable=False)  # 'snmp_arp_mac', 'manual', etc.
    port_mac_count = Column(Integer, nullable=True)  # Number of MACs on this port
    appears_on_switches = Column(Integer, default=1, nullable=False)  # How many switches see this MAC

    # Timestamps
    first_detected = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_confirmed = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, index=True)
    last_arp_seen = Column(DateTime(timezone=True), nullable=True)  # Last time seen in ARP table
    last_mac_seen = Column(DateTime(timezone=True), nullable=True)  # Last time seen in MAC table

    # Composite indexes
    __table_args__ = (
        Index('idx_location_switch_port', 'switch_id', 'port_name'),
        Index('idx_location_mac', 'mac_address'),
        Index('idx_location_confidence', 'confidence_score'),
    )

    def __repr__(self):
        return f"<IPLocation(id={self.id}, ip='{self.ip_address}', port='{self.port_name}', confidence={self.confidence_score:.1f})>"
