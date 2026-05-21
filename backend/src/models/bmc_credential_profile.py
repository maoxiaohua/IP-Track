"""
BMC Credential Profile Model

Named credential sets that multiple BMC servers can reference.
"""

from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from core.database import Base


class BMCCredentialProfile(Base):
    """Named credential profile for BMC/IPMI authentication"""

    __tablename__ = "bmc_credential_profiles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    username = Column(String(100), nullable=False)
    password_encrypted = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<BMCCredentialProfile(id={self.id}, name='{self.name}', username='{self.username}')>"
