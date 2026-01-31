from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.sql import func
from core.database import Base


class Switch(Base):
    """Switch model for storing network switch information"""

    __tablename__ = "switches"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    ip_address = Column(INET, nullable=False, unique=True, index=True)
    vendor = Column(String(50), nullable=False)  # 'cisco', 'dell', 'alcatel'
    model = Column(String(100), nullable=True)
    role = Column(String(20), default='access', nullable=False)  # 'core', 'aggregation', 'access'
    priority = Column(Integer, default=50, nullable=False, index=True)  # 1-100, lower = higher priority
    ssh_port = Column(Integer, default=22, nullable=False)
    username = Column(String(100), nullable=False)
    password_encrypted = Column(Text, nullable=False)
    enable_password_encrypted = Column(Text, nullable=True)  # For Cisco enable mode
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    connection_timeout = Column(Integer, default=30, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<Switch(id={self.id}, name='{self.name}', ip='{self.ip_address}', role='{self.role}', priority={self.priority})>"
