from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import INET, MACADDR
from sqlalchemy.sql import func
from core.database import Base


class QueryHistory(Base):
    """Query history model for tracking IP lookup queries"""

    __tablename__ = "query_history"

    id = Column(Integer, primary_key=True, index=True)
    target_ip = Column(INET, nullable=False, index=True)
    found_mac = Column(MACADDR, nullable=True, index=True)
    switch_id = Column(Integer, ForeignKey("switches.id", ondelete="SET NULL"), nullable=True)
    port_name = Column(String(50), nullable=True)
    vlan_id = Column(Integer, nullable=True)
    query_status = Column(String(20), nullable=False)  # 'success', 'not_found', 'error'
    error_message = Column(Text, nullable=True)
    query_time_ms = Column(Integer, nullable=True)
    queried_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    def __repr__(self):
        return f"<QueryHistory(id={self.id}, target_ip='{self.target_ip}', status='{self.query_status}')>"
