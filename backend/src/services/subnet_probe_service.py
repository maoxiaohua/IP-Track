"""
Standalone Subnet Probe service.

Answers one operational question quickly: "which of these ~1000 /24 segments still
have anything alive in them?" — used before reclaiming/cleaning up address space.

Deliberately independent from IPAM (see CLAUDE.md): no database models, no migrations,
no IPAM tables. Task state lives in memory only and is dropped on restart.

Liveness is ICMP-only, reusing `utils.network.ping_host`.
"""
import asyncio
import ipaddress
import itertools
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.config import settings
from schemas.subnet_probe import (
    AliveHost,
    ProbeMode,
    ProbeStatus,
    SubnetProbeEntry,
    SubnetProbeResultResponse,
    SubnetProbeStartResponse,
    SubnetProbeStatusResponse,
    SubnetProbeSummary,
    SubnetProbeTaskBrief,
)
from utils.logger import logger
from utils.network import ping_host

# Tokens separated by whitespace, commas or semicolons
_TOKEN_SPLIT = re.compile(r"[\s,;]+")
# Gateway-ish addresses probed first in fast mode (early exit only, never changes the verdict)
_GATEWAY_CANDIDATES = (1, 254, 2, 3)
# Cap on live IPs kept per subnet (fast mode stops at the first hit anyway)
_MAX_ALIVE_IPS_KEPT = 256
_MAX_INVALID_REPORTED = 20


def _host_count(net: ipaddress.IPv4Network) -> int:
    """Usable host count, matching ipaddress .hosts() semantics (RFC 3021 for /31, single host for /32)."""
    if net.prefixlen >= 31:
        return net.num_addresses
    return max(0, net.num_addresses - 2)


class SubnetParseError(Exception):
    """Raised when the pasted subnet list cannot be probed as a whole."""

    def __init__(self, message: str, invalid: Optional[List[str]] = None):
        super().__init__(message)
        self.message = message
        self.invalid = invalid or []


class ProbeConflictError(Exception):
    """Raised when another probe run is already in progress."""

    def __init__(self, message: str, running_task_id: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.running_task_id = running_task_id


def parse_subnet_text(text: str) -> Tuple[List[str], List[str], int]:
    """
    Parse free-form pasted text into a normalized CIDR list.

    Accepts one CIDR ("10.1.0.0/24") or bare IP ("10.1.0.5", treated as /32) per token,
    separated by newlines/spaces/commas/semicolons; "#" starts a comment.

    Returns (subnets, invalid_tokens, total_hosts). Raises SubnetParseError when the
    overall request is out of bounds (too many subnets / too many hosts / unusable input).
    """
    min_prefix = settings.SUBNET_PROBE_MIN_PREFIX
    max_subnets = settings.SUBNET_PROBE_MAX_SUBNETS
    max_total_hosts = settings.SUBNET_PROBE_MAX_TOTAL_HOSTS

    tokens: List[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.split("#", 1)[0]
        tokens.extend(t for t in _TOKEN_SPLIT.split(line.strip()) if t)

    subnets: List[str] = []
    invalid: List[str] = []
    seen = set()

    for token in tokens:
        try:
            net = ipaddress.ip_network(token.strip(), strict=False)
        except ValueError:
            invalid.append(token)
            continue
        if net.version != 4:
            invalid.append(f"{token}(仅支持IPv4)")
            continue
        if net.prefixlen < min_prefix:
            invalid.append(f"{token}(网段过大,最小/{min_prefix})")
            continue
        normalized = str(net)
        if normalized in seen:
            continue
        seen.add(normalized)
        subnets.append(normalized)

    if not tokens:
        raise SubnetParseError("请输入至少一个网段，例如 10.1.0.0/24")
    if not subnets:
        raise SubnetParseError(
            f"没有可用的网段（共 {len(invalid)} 条无法识别）", invalid[:_MAX_INVALID_REPORTED]
        )
    if len(subnets) > max_subnets:
        raise SubnetParseError(
            f"网段数量 {len(subnets)} 超过上限 {max_subnets}，请分批探测"
        )

    total_hosts = 0
    for cidr in subnets:
        total_hosts += _host_count(ipaddress.ip_network(cidr))
    if total_hosts > max_total_hosts:
        raise SubnetParseError(
            f"待探测地址总数 {total_hosts} 超过上限 {max_total_hosts}，请减少网段或改用更小的范围"
        )

    return subnets, invalid[:_MAX_INVALID_REPORTED], total_hosts


class SubnetProbeService:
    """In-memory registry of subnet probe tasks; one running task at a time."""

    def __init__(self) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}
        # Monotonic creation counter, so eviction always drops the oldest task
        self._seq = itertools.count()

    # ------------------------------------------------------------------ helpers

    def _evict_old_tasks(self) -> None:
        """Keep the registry bounded by dropping the oldest finished tasks."""
        limit = settings.SUBNET_PROBE_MAX_TASKS
        if len(self._tasks) <= limit:
            return
        finished = [
            (tid, t) for tid, t in self._tasks.items()
            if t["status"] != ProbeStatus.RUNNING
        ]
        # Oldest first
        finished.sort(key=lambda item: item[1]["created_seq"])
        for tid, _ in finished[: max(0, len(self._tasks) - limit)]:
            self._tasks.pop(tid, None)

    def _find_running_task_id(self) -> Optional[str]:
        for tid, task in self._tasks.items():
            if task["status"] == ProbeStatus.RUNNING:
                return tid
        return None

    # ------------------------------------------------------------------- public

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(task_id)

    def list_tasks(self) -> List[SubnetProbeTaskBrief]:
        briefs = [
            SubnetProbeTaskBrief(
                task_id=tid,
                status=task["status"],
                mode=task["mode"],
                total_subnets=task["summary"].total_subnets,
                alive_subnets=task["summary"].alive_subnets,
                started_at=task["started_at"],
                finished_at=task["finished_at"],
            )
            for tid, task in self._tasks.items()
        ]
        briefs.sort(key=lambda b: b.started_at or "", reverse=True)
        return briefs

    def start_probe(
        self,
        subnets: List[str],
        total_hosts: int,
        mode: ProbeMode,
        concurrency: Optional[int],
        timeout: Optional[float],
        gateway_first: bool = True,
    ) -> SubnetProbeStartResponse:
        """Validate limits, register the task and launch it in the background."""
        running = self._find_running_task_id()
        if running:
            raise ProbeConflictError(
                "已有一个探测任务正在运行，请先等待完成或点击停止", running
            )

        effective_concurrency = min(
            concurrency or settings.SUBNET_PROBE_DEFAULT_CONCURRENCY,
            settings.SUBNET_PROBE_MAX_CONCURRENCY,
        )
        effective_timeout = timeout or settings.SUBNET_PROBE_DEFAULT_TIMEOUT

        task_id = uuid.uuid4().hex
        summary = SubnetProbeSummary(total_subnets=len(subnets))
        task: Dict[str, Any] = {
            "task_id": task_id,
            "status": ProbeStatus.RUNNING,
            "mode": mode,
            "concurrency": effective_concurrency,
            "timeout": effective_timeout,
            "subnets": subnets,
            "total_hosts": total_hosts,
            # Never larger than the concurrency, otherwise a subnet could wait forever
            # for slots it can never get.
            "chunk_size": max(1, min(settings.SUBNET_PROBE_CHUNK_SIZE, effective_concurrency)),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None,
            "created_seq": next(self._seq),
            "summary": summary,
            "results": [None] * len(subnets),
            "elapsed": 0.0,
            "message": None,
            "asyncio_task": None,
        }
        self._tasks[task_id] = task
        self._evict_old_tasks()

        task["asyncio_task"] = asyncio.create_task(
            self._run_probe(task, gateway_first=gateway_first)
        )
        logger.info(
            "Subnet probe %s started: %d subnets / %d hosts, concurrency=%d, timeout=%.2fs, mode=%s",
            task_id[:8], len(subnets), total_hosts, effective_concurrency, effective_timeout, mode.value,
        )

        return SubnetProbeStartResponse(
            task_id=task_id,
            status=ProbeStatus.RUNNING,
            total_subnets=len(subnets),
            total_hosts=total_hosts,
            mode=mode,
            concurrency=effective_concurrency,
            timeout=effective_timeout,
        )

    async def cancel_probe(self, task_id: str) -> bool:
        """Cancel a running task and wait until it has actually stopped."""
        task = self._tasks.get(task_id)
        if not task or task["status"] != ProbeStatus.RUNNING:
            return False
        asyncio_task = task.get("asyncio_task")
        if asyncio_task and not asyncio_task.done():
            asyncio_task.cancel()
            try:
                # _run_probe swallows the cancellation and records CANCELLED itself,
                # so by the time this returns the status is up to date.
                await asyncio_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - _run_probe handles its own errors
                logger.warning("Subnet probe %s cancel raised: %s", task_id[:8], exc)
        return True

    async def shutdown(self) -> None:
        """Cancel every running probe so no ping subprocess outlives the service."""
        running = [t for t in self._tasks.values() if t["status"] == ProbeStatus.RUNNING]
        pending = []
        for task in running:
            asyncio_task = task.get("asyncio_task")
            if asyncio_task and not asyncio_task.done():
                asyncio_task.cancel()
                pending.append(asyncio_task)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            logger.info("Subnet probe service stopped %d running task(s)", len(pending))

    # ------------------------------------------------------------------ probing

    async def _probe_one(
        self,
        cidr: str,
        index: int,
        task: Dict[str, Any],
        semaphore: asyncio.Semaphore,
        gateway_first: bool,
    ) -> None:
        """Probe a single subnet and store its entry; never raises."""
        summary: SubnetProbeSummary = task["summary"]
        mode: ProbeMode = task["mode"]
        timeout: float = task["timeout"]
        started = time.monotonic()

        try:
            net = ipaddress.ip_network(cidr)
            total_hosts = _host_count(net)
            alive: List[AliveHost] = []
            probed = 0
            capped = False

            async def probe(ip: str) -> Optional[AliveHost]:
                async with semaphore:
                    result = await ping_host(ip, timeout=timeout)
                if result.get("reachable"):
                    return AliveHost(ip=ip, response_time_ms=result.get("response_time_ms"))
                return None

            async def gather_alive(ips: List[str]) -> List[AliveHost]:
                nonlocal probed
                probed += len(ips)
                # Keep the live progress counters honest while the run is still going
                summary.pings_sent += len(ips)
                outcome = await asyncio.gather(*(probe(ip) for ip in ips), return_exceptions=True)
                return [item for item in outcome if isinstance(item, AliveHost)]

            # Explicit, one-shot enumeration: hosts() yields nothing for /31 and /32
            # on some builds and is not a one-shot iterator on others, so the chunk
            # loop below must never rely on bare exhaustion.
            if net.prefixlen >= 31:
                host_iter: Any = (net.network_address + offset for offset in range(net.num_addresses))
            else:
                host_iter: Any = (ip for ip in net.hosts())

            if mode == ProbeMode.FAST and gateway_first:
                # Cheap early exit on the usual suspects; a miss here just falls through
                gateway_ips = []
                for offset in _GATEWAY_CANDIDATES:
                    candidate = net.network_address + offset
                    if candidate not in net:
                        continue
                    if net.prefixlen < 31 and candidate in (net.network_address, net.broadcast_address):
                        continue  # never ping the network/broadcast address
                    gateway_ips.append(str(candidate))
                if gateway_ips:
                    hits = await gather_alive(gateway_ips)
                    if hits:
                        alive = hits[:_MAX_ALIVE_IPS_KEPT]
                    else:
                        # Do not ping the gateway addresses twice
                        already = set(gateway_ips)
                        host_iter = (ip for ip in net.hosts() if str(ip) not in already)

            if not alive:
                chunk_size = task["chunk_size"]
                # Hard bound: never probe more addresses than the subnet actually has
                budget = total_hosts
                while budget > 0:
                    chunk = [
                        str(ip)
                        for ip in itertools.islice(host_iter, min(chunk_size, budget))
                    ]
                    if not chunk:
                        break
                    budget -= len(chunk)
                    hits = await gather_alive(chunk)
                    if hits:
                        alive.extend(hits)
                        if mode == ProbeMode.FAST:
                            break
                        if len(alive) >= _MAX_ALIVE_IPS_KEPT:
                            capped = True
                            break

            entry = SubnetProbeEntry(
                subnet=cidr,
                has_live=bool(alive),
                alive_count=len(alive),
                alive_ips=alive[:_MAX_ALIVE_IPS_KEPT],
                probed_hosts=probed,
                total_hosts=total_hosts,
                truncated=capped,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # one bad subnet must not kill the whole run
            logger.warning("Subnet probe %s failed on %s: %s", task["task_id"][:8], cidr, exc)
            entry = SubnetProbeEntry(
                subnet=cidr,
                has_live=False,
                probed_hosts=0,
                total_hosts=0,
                duration_ms=int((time.monotonic() - started) * 1000),
                error=str(exc),
            )

        task["results"][index] = entry
        summary.checked_subnets += 1
        if not entry.error:
            if entry.has_live:
                summary.alive_subnets += 1
                summary.alive_hosts += entry.alive_count
            else:
                summary.dead_subnets += 1

    async def _run_probe(self, task: Dict[str, Any], gateway_first: bool) -> None:
        """Run subnets through a small worker pool; handle cancel/failure."""
        started = time.monotonic()
        semaphore = asyncio.Semaphore(task["concurrency"])
        workers: List[asyncio.Task] = []
        try:
            subnets = task["subnets"]
            # One subnet needs roughly one chunk of slots at a time, so the number of
            # subnets in flight is capped rather than launching all of them at once.
            # Otherwise every subnet advances one chunk in lockstep and no subnet is
            # ever finished until the very end (progress stuck at 0, useless ETA).
            worker_count = max(1, min(len(subnets), task["concurrency"] // task["chunk_size"]))
            pending: List[Tuple[int, str]] = list(enumerate(subnets))

            async def worker() -> None:
                while pending:
                    index, cidr = pending.pop(0)
                    await self._probe_one(cidr, index, task, semaphore, gateway_first)

            workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
            await asyncio.gather(*workers)
            task["status"] = ProbeStatus.COMPLETED
        except asyncio.CancelledError:
            for pending_worker in workers:
                pending_worker.cancel()
            # Wait for children so their ping subprocesses are killed and reaped
            await asyncio.gather(*workers, return_exceptions=True)
            task["status"] = ProbeStatus.CANCELLED
            task["message"] = "任务已取消"
            logger.info(
                "Subnet probe %s cancelled after %d/%d subnets",
                task["task_id"][:8], task["summary"].checked_subnets, task["summary"].total_subnets,
            )
        except Exception as exc:
            task["status"] = ProbeStatus.FAILED
            task["message"] = str(exc)
            logger.error("Subnet probe %s failed: %s", task["task_id"][:8], exc, exc_info=True)
        finally:
            task["elapsed"] = time.monotonic() - started
            task["finished_at"] = datetime.now().isoformat(timespec="seconds")
            task["asyncio_task"] = None

            # Counters are summed live by each subnet coroutine, but keep them truthful
            # for subnets that never ran (cancelled runs).
            entries = [e for e in task["results"] if e is not None]
            summary: SubnetProbeSummary = task["summary"]
            summary.checked_subnets = len(entries)
            summary.alive_subnets = sum(1 for e in entries if e.has_live and not e.error)
            summary.dead_subnets = sum(1 for e in entries if not e.has_live and not e.error)
            summary.alive_hosts = sum(e.alive_count for e in entries if not e.error)
            summary.pings_sent = sum(e.probed_hosts for e in entries)

    # ------------------------------------------------------------------ payloads

    def build_status(self, task_id: str) -> Optional[SubnetProbeStatusResponse]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        total = task["summary"].total_subnets
        checked = task["summary"].checked_subnets
        elapsed = task["elapsed"] if task["status"] != ProbeStatus.RUNNING else 0.0
        if task["status"] == ProbeStatus.RUNNING:
            elapsed = (datetime.now() - datetime.fromisoformat(task["started_at"])).total_seconds()
        eta = None
        if task["status"] == ProbeStatus.RUNNING and checked > 0 and total > 0:
            eta = max(0.0, elapsed / checked * (total - checked))
        progress = round(checked / total * 100, 1) if total else 0.0
        return SubnetProbeStatusResponse(
            task_id=task_id,
            status=task["status"],
            mode=task["mode"],
            progress_percent=progress if task["status"] == ProbeStatus.RUNNING else 100.0,
            summary=task["summary"],
            elapsed_seconds=round(elapsed, 1),
            eta_seconds=round(eta, 1) if eta is not None else None,
            started_at=task["started_at"],
            finished_at=task["finished_at"],
            message=task["message"],
        )

    def build_result(self, task_id: str) -> Optional[SubnetProbeResultResponse]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        elapsed = task["elapsed"]
        if task["status"] == ProbeStatus.RUNNING:
            elapsed = (datetime.now() - datetime.fromisoformat(task["started_at"])).total_seconds()
        entries = [e for e in task["results"] if e is not None]
        return SubnetProbeResultResponse(
            task_id=task_id,
            status=task["status"],
            mode=task["mode"],
            concurrency=task["concurrency"],
            timeout=task["timeout"],
            started_at=task["started_at"],
            finished_at=task["finished_at"],
            elapsed_seconds=round(elapsed, 1),
            summary=task["summary"],
            results=entries,
        )


subnet_probe_service = SubnetProbeService()
