from __future__ import annotations

import asyncio
import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IPAMScanStatusService:
    """Tracks the currently active IPAM scan and broadcasts live progress."""

    PHASE_LABELS = {
        "idle": "空闲",
        "queued": "排队中",
        "quick_scan": "快速扫描",
        "enrichment": "识别主机信息",
        "completed": "已完成",
        "error": "异常结束",
    }

    def __init__(self) -> None:
        self._listeners: set[asyncio.Queue] = set()
        self._status: Dict[str, Any] = self._make_idle_status()
        self._lock = asyncio.Lock()

    def _make_idle_status(self) -> Dict[str, Any]:
        return {
            "running": False,
            "session_id": None,
            "source": None,
            "scan_type": None,
            "current_phase": "idle",
            "phase_label": self.PHASE_LABELS["idle"],
            "message": None,
            "error": None,
            "subnet_id": None,
            "subnet_name": None,
            "subnet_network": None,
            "current_subnet_index": 0,
            "total_subnets": 0,
            "completed_subnets": 0,
            "current_subnet_total_ips": 0,
            "current_subnet_completed_ips": 0,
            "current_subnet_pending_ips": 0,
            "current_subnet_reachable_ips": 0,
            "current_subnet_unreachable_ips": 0,
            "current_subnet_enrichment_total": 0,
            "current_subnet_enrichment_completed": 0,
            "current_subnet_last_scan_at": None,
            "total_ips_scanned": 0,
            "started_at": None,
            "updated_at": _utcnow_iso(),
            "last_completed_at": None,
            "summary": None,
        }

    def get_status(self) -> Dict[str, Any]:
        return copy.deepcopy(self._status)

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._listeners.add(queue)
            snapshot = {
                "type": "snapshot",
                **copy.deepcopy(self._status),
            }
        await queue.put(snapshot)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._listeners.discard(queue)

    async def _broadcast(self, payload: Dict[str, Any]) -> None:
        async with self._lock:
            listeners = list(self._listeners)

        stale_listeners = []
        for queue in listeners:
            try:
                queue.put_nowait(copy.deepcopy(payload))
            except Exception:
                stale_listeners.append(queue)

        if stale_listeners:
            async with self._lock:
                for queue in stale_listeners:
                    self._listeners.discard(queue)

    async def _update(self, event_type: str, **updates: Any) -> Dict[str, Any]:
        async with self._lock:
            self._status.update(updates)
            phase = self._status.get("current_phase") or "idle"
            self._status["phase_label"] = self.PHASE_LABELS.get(phase, phase)
            self._status["updated_at"] = _utcnow_iso()
            payload = {
                "type": event_type,
                **copy.deepcopy(self._status),
            }

        await self._broadcast(payload)
        return payload

    async def start_scan(
        self,
        *,
        source: str,
        scan_type: str,
        total_subnets: int,
        message: str,
    ) -> str:
        session_id = str(uuid.uuid4())
        previous_completed_at = self._status.get("last_completed_at")
        await self._update(
            "start",
            running=True,
            session_id=session_id,
            source=source,
            scan_type=scan_type,
            current_phase="queued",
            message=message,
            error=None,
            subnet_id=None,
            subnet_name=None,
            subnet_network=None,
            current_subnet_index=0,
            total_subnets=total_subnets,
            completed_subnets=0,
            current_subnet_total_ips=0,
            current_subnet_completed_ips=0,
            current_subnet_pending_ips=0,
            current_subnet_reachable_ips=0,
            current_subnet_unreachable_ips=0,
            current_subnet_enrichment_total=0,
            current_subnet_enrichment_completed=0,
            current_subnet_last_scan_at=None,
            total_ips_scanned=0,
            started_at=_utcnow_iso(),
            last_completed_at=previous_completed_at,
            summary=None,
        )
        return session_id

    async def begin_subnet(
        self,
        *,
        subnet_id: int,
        subnet_name: Optional[str],
        subnet_network: Optional[str],
        subnet_index: int,
        total_ips: int,
        total_subnets: Optional[int] = None,
    ) -> None:
        message = f"正在快速扫描子网 {subnet_network or subnet_name or subnet_id}"
        await self._update(
            "subnet",
            subnet_id=subnet_id,
            subnet_name=subnet_name,
            subnet_network=subnet_network,
            current_subnet_index=subnet_index,
            total_subnets=total_subnets if total_subnets is not None else self._status.get("total_subnets", 0),
            current_phase="quick_scan",
            message=message,
            current_subnet_total_ips=total_ips,
            current_subnet_completed_ips=0,
            current_subnet_pending_ips=total_ips,
            current_subnet_reachable_ips=0,
            current_subnet_unreachable_ips=0,
            current_subnet_enrichment_total=0,
            current_subnet_enrichment_completed=0,
            current_subnet_last_scan_at=None,
        )

    async def update_quick_progress(
        self,
        *,
        completed_ips: int,
        total_ips: int,
        reachable_ips: int,
    ) -> None:
        pending_ips = max(total_ips - completed_ips, 0)
        unreachable_ips = max(completed_ips - reachable_ips, 0)
        subnet_label = self._status.get("subnet_network") or self._status.get("subnet_name") or self._status.get("subnet_id")
        message = (
            f"正在快速扫描 {subnet_label}，已完成 {completed_ips}/{total_ips}，"
            f"等待 {pending_ips} 个节点回复"
        )
        await self._update(
            "progress",
            current_phase="quick_scan",
            message=message,
            current_subnet_completed_ips=completed_ips,
            current_subnet_pending_ips=pending_ips,
            current_subnet_reachable_ips=reachable_ips,
            current_subnet_unreachable_ips=unreachable_ips,
        )

    async def update_enrichment_progress(
        self,
        *,
        completed_hosts: int,
        total_hosts: int,
        reachable_ips: int,
        subnet_last_scan_at: Optional[str] = None,
    ) -> None:
        subnet_label = self._status.get("subnet_network") or self._status.get("subnet_name") or self._status.get("subnet_id")
        message = (
            f"正在识别 {subnet_label} 的在线主机信息，"
            f"已完成 {completed_hosts}/{total_hosts}"
        )
        await self._update(
            "progress",
            current_phase="enrichment",
            message=message,
            current_subnet_reachable_ips=reachable_ips,
            current_subnet_enrichment_total=total_hosts,
            current_subnet_enrichment_completed=completed_hosts,
            current_subnet_last_scan_at=subnet_last_scan_at,
        )

    async def finish_subnet_quick_phase(
        self,
        *,
        subnet_last_scan_at: Optional[str],
        total_ips_scanned_delta: int,
        reachable_ips: int,
        total_ips: int,
    ) -> None:
        completed_subnets = self._status.get("completed_subnets", 0)
        total_ips_scanned = self._status.get("total_ips_scanned", 0) + total_ips_scanned_delta
        subnet_label = self._status.get("subnet_network") or self._status.get("subnet_name") or self._status.get("subnet_id")
        unreachable_ips = max(total_ips - reachable_ips, 0)
        await self._update(
            "progress",
            current_phase="enrichment" if reachable_ips > 0 else "quick_scan",
            message=(
                f"子网 {subnet_label} 快速扫描完成，"
                f"在线 {reachable_ips}，离线 {unreachable_ips}"
            ),
            completed_subnets=completed_subnets,
            total_ips_scanned=total_ips_scanned,
            current_subnet_completed_ips=total_ips,
            current_subnet_pending_ips=0,
            current_subnet_reachable_ips=reachable_ips,
            current_subnet_unreachable_ips=unreachable_ips,
            current_subnet_last_scan_at=subnet_last_scan_at,
        )

    async def complete_subnet(self, *, message: Optional[str] = None) -> None:
        completed_subnets = min(
            self._status.get("completed_subnets", 0) + 1,
            self._status.get("total_subnets", 0),
        )
        await self._update(
            "progress",
            completed_subnets=completed_subnets,
            message=message or self._status.get("message"),
        )

    async def consume_scan_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Translate subnet-scan callbacks into user-facing status updates."""
        if event_type == "subnet_start":
            await self.begin_subnet(
                subnet_id=payload["subnet_id"],
                subnet_name=payload.get("subnet_name"),
                subnet_network=payload.get("subnet_network"),
                subnet_index=payload.get("subnet_index", 1),
                total_ips=payload.get("total_ips", 0),
                total_subnets=payload.get("total_subnets"),
            )
            return

        if event_type == "quick_progress":
            await self.update_quick_progress(
                completed_ips=payload.get("completed_ips", 0),
                total_ips=payload.get("total_ips", 0),
                reachable_ips=payload.get("reachable_ips", 0),
            )
            return

        if event_type == "quick_complete":
            await self.finish_subnet_quick_phase(
                subnet_last_scan_at=payload.get("subnet_last_scan_at"),
                total_ips_scanned_delta=payload.get("total_ips_scanned", 0),
                reachable_ips=payload.get("reachable_ips", 0),
                total_ips=payload.get("total_ips_scanned", 0),
            )
            return

        if event_type == "enrichment_progress":
            await self.update_enrichment_progress(
                completed_hosts=payload.get("completed_hosts", 0),
                total_hosts=payload.get("total_hosts", 0),
                reachable_ips=payload.get("reachable_ips", 0),
                subnet_last_scan_at=payload.get("subnet_last_scan_at"),
            )
            return

        if event_type == "subnet_complete":
            summary = payload.get("summary") or {}
            subnet_label = self._status.get("subnet_network") or self._status.get("subnet_name") or self._status.get("subnet_id")
            await self.complete_subnet(
                message=(
                    f"子网 {subnet_label} 扫描完成，"
                    f"在线 {summary.get('reachable', 0)}，离线 {summary.get('unreachable', 0)}"
                )
            )

    async def complete_scan(self, *, summary: Optional[Dict[str, Any]] = None, message: Optional[str] = None) -> None:
        await self._update(
            "complete",
            running=False,
            current_phase="completed",
            message=message or "IPAM 扫描完成",
            error=None,
            completed_subnets=self._status.get("total_subnets", 0),
            summary=summary,
            last_completed_at=_utcnow_iso(),
        )

    async def fail_scan(self, *, error: str, message: Optional[str] = None) -> None:
        await self._update(
            "error",
            running=False,
            current_phase="error",
            message=message or error,
            error=error,
            last_completed_at=_utcnow_iso(),
        )


ipam_scan_status_service = IPAMScanStatusService()
