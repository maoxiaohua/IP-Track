from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.sql import func
from core.database import Base


class OpticalModule(Base):
    """Optical transceiver (SFP/QSFP) information from switches"""

    __tablename__ = "optical_modules"

    id = Column(Integer, primary_key=True, index=True)
    switch_id = Column(Integer, ForeignKey("switches.id", ondelete="CASCADE"), nullable=False, index=True)
    switch_name = Column(String(255), nullable=True, index=True)  # Denormalized for search
    switch_ip = Column(INET, nullable=True, index=True)  # Denormalized for search
    port_name = Column(String(50), nullable=False, index=True)
    module_type = Column(String(20), nullable=True)  # SFP, SFP+, QSFP, QSFP+, QSFP28
    model = Column(String(100), nullable=True, index=True)
    part_number = Column(String(100), nullable=True)
    serial_number = Column(String(100), nullable=True, index=True)
    vendor = Column(String(100), nullable=True, index=True)
    speed_gbps = Column(Integer, nullable=True)  # Speed in Gbps

    # Timestamps
    collected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    first_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Composite indexes
    __table_args__ = (
        Index('idx_optical_modules_switch', 'switch_id'),
        Index('idx_optical_modules_port', 'port_name'),
        Index('idx_optical_modules_serial', 'serial_number'),
        Index('idx_optical_modules_switch_name', 'switch_name'),
        Index('idx_optical_modules_switch_ip', 'switch_ip'),
        Index('idx_optical_modules_model', 'model'),
    )

    def __repr__(self):
        return f"<OpticalModule(id={self.id}, port='{self.port_name}', type='{self.module_type}', switch='{self.switch_name}')>"
