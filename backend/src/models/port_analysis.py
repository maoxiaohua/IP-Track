from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, Index, Text
from sqlalchemy.sql import func
from core.database import Base


class PortAnalysis(Base):
    """Port analysis results - MAC count and port type classification"""

    __tablename__ = "port_analysis"

    id = Column(Integer, primary_key=True, index=True)
    switch_id = Column(Integer, ForeignKey("switches.id", ondelete="CASCADE"), nullable=False, index=True)
    port_name = Column(String(50), nullable=False, index=True)

    # Analysis results
    mac_count = Column(Integer, default=0, nullable=False)  # Number of MACs learned on this port
    unique_vlans = Column(Integer, default=0, nullable=False)  # Number of VLANs on this port
    port_type = Column(String(20), nullable=False, index=True)  # 'access', 'trunk', 'uplink', 'unknown'
    confidence_score = Column(Float, default=0.0, nullable=False)  # 0-100

    # Port naming hints
    is_trunk_by_name = Column(Integer, default=0, nullable=False)  # 1 if name suggests trunk (Gi, Te, etc.)
    is_access_by_name = Column(Integer, default=0, nullable=False)  # 1 if name suggests access (Fa, etc.)

    # Manual lookup policy overrides
    lookup_policy_override = Column(String(20), nullable=True, index=True)  # 'include' | 'exclude' | NULL(auto)
    lookup_policy_note = Column(Text, nullable=True)
    lookup_policy_updated_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    analyzed_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Composite indexes
    __table_args__ = (
        Index('idx_port_switch_port', 'switch_id', 'port_name', unique=True),
        Index('idx_port_type', 'port_type'),
        Index('idx_port_lookup_policy_override', 'lookup_policy_override'),
    )

    def __repr__(self):
        return f"<PortAnalysis(id={self.id}, port='{self.port_name}', type='{self.port_type}', mac_count={self.mac_count})>"
