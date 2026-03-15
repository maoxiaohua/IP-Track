from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import MACADDR
from sqlalchemy.sql import func
from core.database import Base


class MACTable(Base):
    """MAC address table from switches (MAC-Port mappings)"""

    __tablename__ = "mac_table"

    id = Column(Integer, primary_key=True, index=True)
    switch_id = Column(Integer, ForeignKey("switches.id", ondelete="CASCADE"), nullable=False, index=True)
    mac_address = Column(MACADDR, nullable=False, index=True)
    port_name = Column(String(50), nullable=False, index=True)
    vlan_id = Column(Integer, nullable=True, index=True)
    is_dynamic = Column(Integer, default=1, nullable=False)  # 1=dynamic, 0=static

    # Timestamps
    collected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    first_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Composite indexes
    __table_args__ = (
        Index('idx_mac_switch_port', 'switch_id', 'port_name'),
        Index('idx_mac_address_switch', 'mac_address', 'switch_id'),
        Index('idx_mac_collected', 'collected_at'),
    )

    def __repr__(self):
        return f"<MACTable(id={self.id}, mac='{self.mac_address}', port='{self.port_name}', switch_id={self.switch_id})>"
