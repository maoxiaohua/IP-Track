"""
交换机配置备份模型

两张表：
- ConfigBlob：正文按 sha256 内容寻址，内容相同的备份共用一行，避免重复存储；
- ConfigBackup：每一次备份尝试（含失败）一行，用于状态展示与版本历史。
"""

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Index
)
from sqlalchemy.sql import func
from core.database import Base


class ConfigBlob(Base):
    """配置正文（内容寻址，sha256 为主键）"""

    __tablename__ = 'config_blobs'

    sha256 = Column(String(64), primary_key=True)
    content = Column(Text, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<ConfigBlob sha256={self.sha256[:12]} size={self.size_bytes}>"


class ConfigBackup(Base):
    """一次配置备份尝试（成功/失败都记录）"""

    __tablename__ = 'config_backups'

    id = Column(Integer, primary_key=True, index=True)
    switch_id = Column(
        Integer, ForeignKey('switches.id', ondelete='CASCADE'),
        nullable=False, index=True
    )
    status = Column(String(20), nullable=False)          # running | success | failed | unsupported
    trigger_source = Column(String(20), nullable=False)  # manual | scheduled
    sha256 = Column(String(64), ForeignKey('config_blobs.sha256', ondelete='SET NULL'))
    size_bytes = Column(Integer)
    file_path = Column(Text)
    device_type = Column(String(50))
    command = Column(String(200))
    message = Column(Text)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    duration_ms = Column(Integer)

    __table_args__ = (
        Index('idx_config_backups_switch_started', 'switch_id', 'started_at'),
        Index('idx_config_backups_status_started', 'status', 'started_at'),
    )

    def __repr__(self):
        return f"<ConfigBackup switch={self.switch_id} status={self.status}>"
