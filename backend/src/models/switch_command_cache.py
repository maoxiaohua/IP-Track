"""
Switch Successful Command Cache Model

Stores the successful CLI commands for each switch to optimize future collections.
Implements self-learning mechanism to avoid trying multiple command variations.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from core.database import Base


class SwitchSuccessfulCommand(Base):
    """Model for caching successful CLI commands per switch"""

    __tablename__ = "switch_successful_commands"

    id = Column(Integer, primary_key=True, index=True)
    switch_id = Column(Integer, ForeignKey("switches.id", ondelete="CASCADE"), nullable=False, index=True)
    command_type = Column(String(20), nullable=False, index=True)  # 'arp' or 'mac'
    successful_command = Column(Text, nullable=False)
    parser_type = Column(String(50))
    success_count = Column(Integer, default=1)
    last_used_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<SwitchSuccessfulCommand(switch_id={self.switch_id}, type='{self.command_type}', command='{self.successful_command}')>"
