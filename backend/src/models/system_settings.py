from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.sql import func
from core.database import Base


class SystemSettings(Base):
    """System-wide configuration settings stored in database"""

    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    data_type = Column(String(20), nullable=False, default='string')
    description = Column(Text, nullable=True)
    is_configurable = Column(Boolean, default=True, nullable=False)
    is_sensitive = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<SystemSettings(key='{self.key}', value='{self.value}')>"
