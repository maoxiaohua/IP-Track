from __future__ import annotations

import asyncio
import copy
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BMCResetStatusService:
    """Tracks the currently active BMC reset session and broadcasts live progress."""

    PHASE_LABELS = {
        "idle": "Idle",
        "running": "Resetting",
        "completed": "Completed",
        "error": "Error",
    }

    def __init__(self) -> None:
        self._listeners: set[asyncio.Queue] = set()
        self._status: Dict[str, Any] = self._make_idle_status()
        self._lock = asyncio.Lock()
        self._last_broadcast_at = 0.0
        self._throttle_interval = 0.25
        self._pending_payload: Optional[Dict[str, Any]] = None
        self._throttle_task: Optional[asyncio.Task] = None

    def _make_idle_status(self) -> Dict[str, Any]:
        return {
            "running": False,
            "session_id": None,
            "current_phase": "idle",
            "phase_label": self.PHASE_LABELS["idle"],
            "message": None,
            "error": None,
            "current_server_index": 0,
            "total_servers": 0,
            "completed_servers": 0,
            "success_count": 0,
            "failure_count": 0,
            "current_server_name": None,
            "current_server_host": None,
            "current_attempt": 0,
            "current_interface": None,
            "results": [],
            "started_at": None,
            "updated_at": _utcnow_iso(),
            "last_completed_at": None,
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

    async def _do_broadcast(self, payload: Dict[str, Any]) -> None:
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

    async def _broadcast(self, payload: Dict[str, Any]) -> None:
        now = time.monotonic()
        if now - self._last_broadcast_at < self._throttle_interval:
            self._pending_payload = payload
            if self._throttle_task is None or self._throttle_task.done():
                self._throttle_task = asyncio.create_task(self._delayed_broadcast())
            return
        self._last_broadcast_at = now
        await self._do_broadcast(payload)

    async def _delayed_broadcast(self) -> None:
        await asyncio.sleep(self._throttle_interval)
        payload = self._pending_payload
        self._pending_payload = None
        if payload is None:
            return
        self._last_broadcast_at = time.monotonic()
        await self._do_broadcast(payload)

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

    async def start_reset(self, *, total_servers: int, message: str) -> str:
        session_id = str(uuid.uuid4())
        previous_completed_at = self._status.get("last_completed_at")
        await self._update(
            "start",
            running=True,
            session_id=session_id,
            current_phase="running",
            message=message,
            error=None,
            current_server_index=0,
            total_servers=total_servers,
            completed_servers=0,
            success_count=0,
            failure_count=0,
            current_server_name=None,
            current_server_host=None,
            current_attempt=0,
            current_interface=None,
            results=[],
            started_at=_utcnow_iso(),
            last_completed_at=previous_completed_at,
        )
        return session_id

    async def update_progress(
        self,
        *,
        server_index: int,
        server_name: str,
        server_host: str,
        attempt: int,
        interface: str,
    ) -> None:
        message = f"Resetting {server_name} ({server_host}) — attempt {attempt} via {interface}"
        await self._update(
            "progress",
            current_server_index=server_index,
            current_server_name=server_name,
            current_server_host=server_host,
            current_attempt=attempt,
            current_interface=interface,
            message=message,
        )

    async def server_complete(
        self,
        *,
        server_id: int,
        server_name: str,
        server_host: str,
        status: str,
        error_category: Optional[str],
        error_message: Optional[str],
        attempts_made: int,
        duration_ms: int,
    ) -> None:
        async with self._lock:
            results: list = self._status.get("results", [])
            results.append({
                "server_id": server_id,
                "server_name": server_name,
                "server_host": server_host,
                "status": status,
                "error_category": error_category,
                "error_message": error_message[:200] if error_message else None,
                "attempts_made": attempts_made,
                "duration_ms": duration_ms,
            })
            completed = len(results)
            success_count = sum(1 for r in results if r["status"] == "success")
            failure_count = sum(1 for r in results if r["status"] == "failure")

        message = f"Completed {completed}/{self._status.get('total_servers', 0)} — {success_count} success, {failure_count} failed"
        await self._update(
            "server_complete",
            completed_servers=completed,
            success_count=success_count,
            failure_count=failure_count,
            results=results,
            message=message,
        )

    async def complete_reset(self, *, message: Optional[str] = None) -> None:
        async with self._lock:
            success = self._status.get("success_count", 0)
            failure = self._status.get("failure_count", 0)
        default_msg = f"BMC reset complete — {success} success, {failure} failed"
        await self._update(
            "complete",
            running=False,
            current_phase="completed",
            message=message or default_msg,
            error=None,
            last_completed_at=_utcnow_iso(),
        )

    async def fail_reset(self, *, error: str, message: Optional[str] = None) -> None:
        await self._update(
            "error",
            running=False,
            current_phase="error",
            message=message or error,
            error=error,
            last_completed_at=_utcnow_iso(),
        )


bmc_reset_status_service = BMCResetStatusService()
