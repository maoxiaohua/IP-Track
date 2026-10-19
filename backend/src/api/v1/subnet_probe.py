"""
Standalone Subnet Probe API (temporary subnet liveness sweeper).

Mounted under /api/v1/subnet-probe and deliberately separate from /api/v1/ipam:
this tool never touches the IPAM tables, subnets or scan scheduler.
"""
from typing import List

from fastapi import APIRouter, HTTPException, status

from schemas.subnet_probe import (
    ProbeStatus,
    SubnetProbeParseRequest,
    SubnetProbeParseResponse,
    SubnetProbeResultResponse,
    SubnetProbeStartRequest,
    SubnetProbeStartResponse,
    SubnetProbeStatusResponse,
    SubnetProbeTaskBrief,
)
from services.subnet_probe_service import (
    ProbeConflictError,
    SubnetParseError,
    parse_subnet_text,
    subnet_probe_service,
)
from utils.logger import logger

router = APIRouter(prefix="/subnet-probe", tags=["subnet-probe"])


@router.post("/parse", response_model=SubnetProbeParseResponse)
async def parse_subnets(payload: SubnetProbeParseRequest):
    """Dry-run parse so the page can show counts and invalid lines before scanning."""
    try:
        subnets, invalid, total_hosts = parse_subnet_text(payload.subnets)
    except SubnetParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": exc.message, "invalid": exc.invalid},
        )
    return SubnetProbeParseResponse(subnets=subnets, total_hosts=total_hosts, invalid=invalid)


@router.post("/start", response_model=SubnetProbeStartResponse)
async def start_probe(payload: SubnetProbeStartRequest):
    """Accept a sweep and run it in the background; poll /status for progress."""
    try:
        subnets, invalid, total_hosts = parse_subnet_text(payload.subnets)
    except SubnetParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": exc.message, "invalid": exc.invalid},
        )

    try:
        result = subnet_probe_service.start_probe(
            subnets=subnets,
            total_hosts=total_hosts,
            mode=payload.mode,
            concurrency=payload.concurrency,
            timeout=payload.timeout,
            gateway_first=payload.gateway_first,
        )
    except ProbeConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": exc.message, "running_task_id": exc.running_task_id},
        )

    logger.info("Subnet probe request accepted: %s (%d subnets)", result.task_id[:8], len(subnets))
    return result


@router.get("/status/{task_id}", response_model=SubnetProbeStatusResponse)
async def get_status(task_id: str):
    """Lightweight progress snapshot; the page polls this while a run is active."""
    snapshot = subnet_probe_service.build_status(task_id)
    if not snapshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "任务不存在或已过期（服务可能已重启），请重新发起探测"},
        )
    return snapshot


@router.get("/result/{task_id}", response_model=SubnetProbeResultResponse)
async def get_result(task_id: str):
    """Full per-subnet detail, used for the summary table and the Excel export."""
    result = subnet_probe_service.build_result(task_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "任务不存在或已过期（服务可能已重启），请重新发起探测"},
        )
    return result


@router.post("/cancel/{task_id}", response_model=SubnetProbeStatusResponse)
async def cancel_probe(task_id: str):
    """Stop a running sweep (in-flight ping processes are terminated)."""
    if not await subnet_probe_service.cancel_probe(task_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "任务不在运行中，无法取消"},
        )
    snapshot = subnet_probe_service.build_status(task_id)
    if not snapshot:  # pragma: no cover - task cannot vanish between the two calls
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "任务不存在或已过期"},
        )
    return snapshot


@router.get("/tasks", response_model=List[SubnetProbeTaskBrief])
async def list_tasks():
    """Recent sweeps kept in memory (newest first), for the page's history strip."""
    return subnet_probe_service.list_tasks()


@router.get("/running")
async def get_running_task():
    """Currently running task id, if any — lets a reloaded page re-attach to a live sweep."""
    for brief in subnet_probe_service.list_tasks():
        if brief.status == ProbeStatus.RUNNING:
            return {"task_id": brief.task_id}
    return {"task_id": None}
