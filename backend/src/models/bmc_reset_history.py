"""
BMC Reset History Model

Tracks every BMC cold reset attempt with detailed error classification.
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base


class BMCResetHistory(Base):
    """Reset history model for tracking BMC cold reset results"""

    __tablename__ = "bmc_reset_history"

    id = Column(Integer, primary_key=True, index=True)
    bmc_server_id = Column(Integer, ForeignKey("bmc_servers.id", ondelete="CASCADE"), nullable=False, index=True)
    server_name = Column(String(200), nullable=False)
    server_host = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, index=True)
    error_category = Column(String(50), nullable=True, index=True)
    error_message = Column(Text, nullable=True)
    attempts_made = Column(Integer, default=1)
    duration_ms = Column(Integer, nullable=True)
    ipmi_command = Column(Text, nullable=True)
    triggered_by = Column(String(50), default="manual")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    server = relationship("BMCServer", back_populates="reset_history")

    def __repr__(self):
        return f"<BMCResetHistory(id={self.id}, server='{self.server_name}', status='{self.status}')>"
