"""
Schemas for the standalone Subnet Probe tool (subnet liveness sweep).

This tool is intentionally independent from IPAM: no DB models, no persistence.
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class ProbeMode(str, Enum):
    """How thorough a subnet probe run is."""
    FAST = "fast"   # stop a subnet as soon as one live host is found
    FULL = "full"   # probe every usable host in the subnet for an exact count


class ProbeStatus(str, Enum):
    """Lifecycle of a subnet probe task."""
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SubnetProbeParseRequest(BaseModel):
    """Input for the dry-run parser used by the UI to preview what will be probed."""
    subnets: str = Field(
        ...,
        description="Pasted text: one CIDR (10.1.0.0/24) or single IP per line; "
                    "spaces/commas also accepted, '#' starts a comment"
    )


class SubnetProbeParseResponse(BaseModel):
    """Result of parsing pasted subnets without running any probe."""
    subnets: List[str] = Field(default_factory=list, description="Normalized, de-duplicated CIDR list")
    total_hosts: int = Field(0, description="Total usable host addresses across all subnets")
    invalid: List[str] = Field(default_factory=list, description="Rejected input tokens (up to 20 shown)")


class SubnetProbeStartRequest(BaseModel):
    """Input for launching a subnet probe run."""
    subnets: str = Field(
        ...,
        description="Pasted text: one CIDR (10.1.0.0/24) or single IP per line; "
                    "spaces/commas also accepted, '#' starts a comment"
    )
    mode: ProbeMode = Field(ProbeMode.FAST, description="fast = stop at first live host, full = count all")
    concurrency: Optional[int] = Field(
        None, ge=1, le=2000, description="In-flight pings; defaults to the server setting when omitted"
    )
    timeout: Optional[float] = Field(
        None, ge=0.2, le=10.0, description="Per-ping timeout in seconds; defaults to the server setting"
    )
    gateway_first: bool = Field(
        True, description="In fast mode, probe .1/.254/.2/.3 first (early exit only, same verdict)"
    )


class SubnetProbeStartResponse(BaseModel):
    """Returned immediately after a run is accepted (the scan continues in the background)."""
    task_id: str
    status: ProbeStatus
    total_subnets: int
    total_hosts: int
    mode: ProbeMode
    concurrency: int
    timeout: float


class AliveHost(BaseModel):
    """A host that answered ICMP."""
    ip: str
    response_time_ms: Optional[float] = None


class SubnetProbeEntry(BaseModel):
    """Per-subnet probe outcome."""
    subnet: str
    has_live: bool = Field(False, description="True when at least one host answered")
    alive_count: int = Field(0, description="Number of live hosts; exact only in full mode")
    alive_ips: List[AliveHost] = Field(default_factory=list)
    probed_hosts: int = Field(0, description="How many addresses were actually pinged")
    total_hosts: int = Field(0, description="Usable addresses in this subnet")
    truncated: bool = Field(False, description="True when the live-host list was capped")
    duration_ms: int = 0
    error: Optional[str] = None


class SubnetProbeSummary(BaseModel):
    """Aggregate counters for a finished (or running) run."""
    total_subnets: int = 0
    checked_subnets: int = 0
    alive_subnets: int = 0
    dead_subnets: int = 0
    alive_hosts: int = 0
    pings_sent: int = 0


class SubnetProbeStatusResponse(BaseModel):
    """Lightweight progress payload; polled by the UI (no per-subnet details)."""
    task_id: str
    status: ProbeStatus
    mode: ProbeMode
    progress_percent: float = 0.0
    summary: SubnetProbeSummary
    elapsed_seconds: float = 0.0
    eta_seconds: Optional[float] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    message: Optional[str] = None


class SubnetProbeResultResponse(BaseModel):
    """Full per-subnet result; fetched once when the run finishes."""
    task_id: str
    status: ProbeStatus
    mode: ProbeMode
    concurrency: int
    timeout: float
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    elapsed_seconds: float = 0.0
    summary: SubnetProbeSummary
    results: List[SubnetProbeEntry] = Field(default_factory=list)


class SubnetProbeTaskBrief(BaseModel):
    """Recent task entry shown on the page."""
    task_id: str
    status: ProbeStatus
    mode: ProbeMode
    total_subnets: int
    alive_subnets: int
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
