"""
Collection Job Schemas
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime
from models.collection_job import JobType, JobStatus


class CollectionJobCreate(BaseModel):
    """Create a new collection job"""
    switch_id: int
    job_type: JobType
    priority: Optional[int] = 0


class CollectionJobResponse(BaseModel):
    """Collection job response"""
    id: int
    switch_id: int
    job_type: JobType
    status: JobStatus
    worker_id: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]
    collection_method: Optional[str]
    entries_collected: int
    error_message: Optional[str]
    retry_count: int
    batch_id: Optional[str]

    class Config:
        from_attributes = True


class WorkerStatus(BaseModel):
    """Individual worker status"""
    worker_id: str
    is_running: bool
    jobs_processed: int
    jobs_succeeded: int
    jobs_failed: int
    current_job_id: Optional[int]


class WorkerPoolStatusResponse(BaseModel):
    """Worker pool status"""
    is_running: bool
    max_workers: int
    active_workers: int
    pending_jobs: int
    running_jobs: int
    workers: List[WorkerStatus]


class CollectionStatsResponse(BaseModel):
    """Collection statistics"""
    window_hours: int
    status_counts: Dict[str, int]
    avg_duration_seconds: float
    success_rate: float
