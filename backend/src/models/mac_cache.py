from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import INET, MACADDR
from sqlalchemy.sql import func
from core.database import Base


class MACAddressCache(Base):
    """MAC address cache model for storing MAC-to-port mappings"""

    __tablename__ = "mac_address_cache"
    __table_args__ = (
        UniqueConstraint('mac_address', 'switch_id', 'port_name', name='uq_mac_switch_port'),
    )

    id = Column(Integer, primary_key=True, index=True)
    mac_address = Column(MACADDR, nullable=False, index=True)
    ip_address = Column(INET, nullable=True, index=True)
    switch_id = Column(Integer, ForeignKey("switches.id", ondelete="CASCADE"), nullable=False)
    port_name = Column(String(50), nullable=False)
    vlan_id = Column(Integer, nullable=True)
    first_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, index=True)

    def __repr__(self):
        return f"<MACAddressCache(id={self.id}, mac='{self.mac_address}', port='{self.port_name}')>"
