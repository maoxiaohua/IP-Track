from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.sql import func
from core.database import Base


class SnmpOidOverride(Base):
    """Per-vendor SNMP OID overrides for ARP/MAC table collection."""

    __tablename__ = "snmp_oid_overrides"

    id = Column(Integer, primary_key=True, index=True)
    vendor = Column(String(50), nullable=False, index=True)
    model_pattern = Column(String(100), nullable=True)
    oid_role = Column(String(30), nullable=False)
    oid_value = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    priority = Column(Integer, default=100)
    enabled = Column(Boolean, default=True, nullable=False)
    is_builtin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
