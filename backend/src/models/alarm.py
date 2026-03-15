"""
Alarm Model

Centralized alarm/alert system for tracking failures and issues across all modules.
Supports de-duplication, auto-resolution, and detailed error tracking.
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Index, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from core.database import Base
from enum import Enum


class AlarmSeverity(str, Enum):
    """Alarm severity levels"""
    CRITICAL = 'critical'  # Red - service impacting
    ERROR = 'error'        # Orange - significant issues
    WARNING = 'warning'    # Yellow - potential problems
    INFO = 'info'          # Blue - informational


class AlarmStatus(str, Enum):
    """Alarm status"""
    ACTIVE = 'active'               # Currently active
    ACKNOWLEDGED = 'acknowledged'   # Seen but not resolved
    RESOLVED = 'resolved'           # Manually resolved
    AUTO_RESOLVED = 'auto_resolved' # Automatically resolved


class AlarmSourceType(str, Enum):
    """Source type for alarm"""
    COLLECTION = 'collection'  # Data collection process
    SWITCH = 'switch'         # Switch-specific
    BATCH = 'batch'           # Batch processing
    SYSTEM = 'system'         # System-level


class Alarm(Base):
    """Alarm model for centralized alert tracking"""

    __tablename__ = "alarms"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Severity and status
    severity = Column(
        SQLEnum(AlarmSeverity, name='alarm_severity', values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True
    )
    status = Column(
        SQLEnum(AlarmStatus, name='alarm_status', values_callable=lambda x: [e.value for e in x]),
        default=AlarmStatus.ACTIVE,
        nullable=False,
        index=True
    )

    # Core information
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    details = Column(JSONB, nullable=True)  # Structured error details

    # Source tracking
    source_type = Column(
        SQLEnum(AlarmSourceType, name='alarm_source_type', values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True
    )
    source_id = Column(Integer, nullable=True)  # FK to switch/batch/etc
    source_name = Column(String(200), nullable=True)  # Cached name for display

    # De-duplication (MD5 hash of source_type + source_id + title + severity)
    fingerprint = Column(String(64), nullable=False, index=True)

    # Occurrence tracking
    occurrence_count = Column(Integer, default=1, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    last_occurrence_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(String(100), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String(100), nullable=True)

    # Composite indexes for common queries
    __table_args__ = (
        Index('idx_alarm_fingerprint_status', 'fingerprint', 'status'),
        Index('idx_alarm_severity_status', 'severity', 'status'),
        Index('idx_alarm_source', 'source_type', 'source_id'),
        Index('idx_alarm_created_at', 'created_at'),
    )

    def __repr__(self):
        return f"<Alarm(id={self.id}, severity='{self.severity}', title='{self.title[:50]}...')>"
