from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import INET, MACADDR
from sqlalchemy.sql import func
from core.database import Base


class ARPTable(Base):
    """ARP table records from switches (IP-MAC mappings)"""

    __tablename__ = "arp_table"

    id = Column(Integer, primary_key=True, index=True)
    switch_id = Column(Integer, ForeignKey("switches.id", ondelete="CASCADE"), nullable=False, index=True)
    ip_address = Column(INET, nullable=False, index=True)
    mac_address = Column(MACADDR, nullable=False, index=True)
    vlan_id = Column(Integer, nullable=True)
    interface = Column(String(50), nullable=True)  # Interface name where ARP was learned
    age_seconds = Column(Integer, nullable=True)  # ARP entry age in seconds

    # Timestamps
    collected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    first_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Composite indexes for better query performance
    __table_args__ = (
        Index('idx_arp_ip_mac', 'ip_address', 'mac_address'),
        Index('idx_arp_switch_ip', 'switch_id', 'ip_address'),
        Index('idx_arp_collected', 'collected_at'),
    )

    def __repr__(self):
        return f"<ARPTable(id={self.id}, ip='{self.ip_address}', mac='{self.mac_address}', switch_id={self.switch_id})>"
