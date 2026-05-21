"""
BMC Server Model

Server inventory for BMC/IPMI cold reset operations.
Each server represents a managed device with BMC capability.
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
from typing import Optional


class BMCServer(Base):
    """Server model for BMC management"""

    __tablename__ = "bmc_servers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    host = Column(String(255), nullable=False, index=True)
    username = Column(String(100), nullable=False)
    password_encrypted = Column(Text, nullable=True)
    use_global_credentials = Column(Boolean, default=True, nullable=False)
    credential_profile_id = Column(
        Integer, ForeignKey("bmc_credential_profiles.id", ondelete="SET NULL"), nullable=True
    )
    enabled = Column(Boolean, default=True, nullable=False)
    notes = Column(Text, nullable=True)
    last_reset_at = Column(DateTime(timezone=True), nullable=True)
    last_reset_result = Column(String(20), nullable=True)
    serial_number = Column(String(200), nullable=True)
    bmc_firmware_version = Column(String(100), nullable=True)
    bmc_info_updated_at = Column(DateTime(timezone=True), nullable=True)
    verified = Column(Boolean, default=False, nullable=False)
    verify_error = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    reset_history = relationship(
        "BMCResetHistory",
        back_populates="server",
        order_by="BMCResetHistory.created_at.desc()",
        cascade="all, delete-orphan"
    )

    credential_profile = relationship(
        "BMCCredentialProfile",
        backref="servers",
        lazy="selectin"
    )

    @property
    def credential_profile_name(self) -> Optional[str]:
        return self.credential_profile.name if self.credential_profile else None

    def __repr__(self):
        return f"<BMCServer(id={self.id}, name='{self.name}', host='{self.host}')>"
