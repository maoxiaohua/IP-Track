"""
Collection Job Model

Persistent job queue for MAC/ARP/Optical module collection.
Allows tracking, debugging, and recovery from crashes.
"""

from sqlalchemy import Column, Integer, String, DateTime, Float, Text, ForeignKey, Index
from sqlalchemy.sql import func
from core.database import Base
import enum


class JobType(str, enum.Enum):
    """Collection job types"""
    MAC = "mac"
    ARP = "arp"
    OPTICAL = "optical"
    ALL = "all"  # Combined MAC+ARP+Optical collection


class JobStatus(str, enum.Enum):
    """Job execution status"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class CollectionJob(Base):
    """Persistent collection job queue"""

    __tablename__ = 'collection_jobs'

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Job identification
    switch_id = Column(Integer, ForeignKey('switches.id'), nullable=False, index=True)
    job_type = Column(String(20), nullable=False, index=True)  # Use String instead of SQLEnum

    # Job status tracking
    status = Column(String(20), nullable=False, default='pending', index=True)  # Use String instead of SQLEnum
    worker_id = Column(String(50))  # Which worker is processing this job

    # Timing information
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Float)

    # Execution details
    collection_method = Column(String(10))  # 'snmp' or 'cli' - which method was used
    entries_collected = Column(Integer, default=0)  # Number of MAC/ARP/Optical entries
    error_message = Column(Text)  # Error details if failed
    retry_count = Column(Integer, default=0)  # How many times retried

    # Performance tracking
    snmp_duration_seconds = Column(Float)  # Time spent on SNMP attempt
    cli_duration_seconds = Column(Float)   # Time spent on CLI attempt

    # Batch tracking (optional, for grouping related jobs)
    batch_id = Column(String(50), index=True)  # UUID for batch collection
    priority = Column(Integer, default=0)  # Higher = higher priority

    # Indexes for efficient querying
    __table_args__ = (
        Index('idx_jobs_status_created', 'status', 'created_at'),
        Index('idx_jobs_switch_type', 'switch_id', 'job_type'),
        Index('idx_jobs_batch', 'batch_id'),
    )

    def __repr__(self):
        return f"<CollectionJob {self.id} switch={self.switch_id} type={self.job_type} status={self.status}>"
