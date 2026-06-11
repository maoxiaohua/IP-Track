"""
BMC Service

Core service for BMC cold reset operations via IPMI.
Handles ipmitool execution, error classification, credential resolution,
and integrates with the alarm system for failure tracking.
"""

import asyncio
import re
import shutil
import time
from typing import List, Optional, Tuple, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, cast, String
from sqlalchemy.orm import selectinload

from core.database import AsyncSessionLocal
from core.security import credential_encryption
from models.bmc_server import BMCServer
from models.bmc_reset_history import BMCResetHistory
from models.bmc_credential_profile import BMCCredentialProfile
from models.alarm import AlarmSeverity, AlarmSourceType
from services.settings_service import settings_service
from services.alarm_service import alarm_service
from services.bmc_reset_status import bmc_reset_status_service
from utils.logger import logger


# Module-level background task tracking to prevent GC of asyncio tasks.
# asyncio.create_task returns a Task that must be kept alive; without a
# reference the task can be garbage-collected before it executes.
_background_tasks: "set[asyncio.Task]" = set()


def _schedule_bg(coro) -> asyncio.Task:
    """Schedule a coroutine as a background task, keeping a reference to prevent GC."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


class BMCService:
    """Service for BMC cold reset operations"""

    IPMI_COMBOS = [
        ("lanplus", "ADMINISTRATOR", None),     # default cipher negotiation
        ("lanplus", "ADMINISTRATOR", "3"),      # legacy cipher suite 3 (RAKP-HMAC-SHA1)
        ("lanplus", "USER", None),
        ("lanplus", "USER", "3"),
        ("lan", "ADMINISTRATOR", None),
        ("lan", "USER", None),
    ]

    MAX_ATTEMPTS_PER_COMBO = 2

    def __init__(self):
        self._reset_lock = asyncio.Lock()

    ERROR_PATTERNS = [
        ("ipmitool_not_found", None),  # handled before execution
        ("auth_failure", re.compile(
            r"RAKP 2 message indicates an error|Invalid user name"
            r"|Authentication failure|authentication disabled"
            r"|session privilege level|Unknown user",
            re.IGNORECASE,
        )),
        ("cipher_mismatch", re.compile(
            r"Cipher suite|no matching cipher|RMCP\+.*error"
            r"|Unsupported cipher",
            re.IGNORECASE,
        )),
        ("ip_unreachable", re.compile(
            r"Unable to establish IPMI|Connection refused|socket error"
            r"|No route to host|cannot connect|connect fail",
            re.IGNORECASE,
        )),
        ("timeout", re.compile(
            r"timeout|timed out|no response",
            re.IGNORECASE,
        )),
    ]

    def _classify_error(self, stderr: str) -> str:
        """Classify ipmitool error output into a category."""
        if not stderr:
            return "unknown"
        for category, pattern in self.ERROR_PATTERNS:
            if pattern is None:
                continue
            if pattern.search(stderr):
                return category
        return "unknown"

    async def _quick_verify(self, host: str, username: str, password: str, timeout: int) -> dict:
        """Quick connectivity check: try ipmitool mc info across IPMI combos.

        Tries the same interface/privilege combos as the reset logic,
        stopping on first success. Returns {ok, error_category, error_message}.
        """
        last_stderr = ""
        for interface, privilege, cipher_suite in self.IPMI_COMBOS:
            exit_code, stdout, stderr = await self._run_ipmi_command(
                host, username, password, interface, privilege,
                ["mc", "info"], min(timeout, 5), cipher_suite=cipher_suite
            )
            if exit_code == -2:
                return {"ok": False, "error_category": "ipmitool_not_found", "error_message": "ipmitool not found"}
            if exit_code == 0 and stdout:
                return {"ok": True, "error_category": None, "error_message": None}
            if stderr:
                last_stderr = stderr
        return {
            "ok": False,
            "error_category": self._classify_error(last_stderr),
            "error_message": last_stderr[:200] if last_stderr else "All IPMI combos failed",
        }

    async def _get_credentials(
        self, db: AsyncSession, server: BMCServer
    ) -> Tuple[str, str]:
        """Resolve effective IPMI credentials for a server.

        Priority: credential_profile > use_global_credentials > per-server credentials.
        """
        # 1. Named credential profile (highest priority)
        if server.credential_profile_id:
            profile = await db.get(BMCCredentialProfile, server.credential_profile_id)
            if profile:
                username = profile.username
                password = (
                    credential_encryption.decrypt(profile.password_encrypted)
                    if profile.password_encrypted else ""
                )
                return username, password

        # 2. Global credentials
        if server.use_global_credentials:
            username = await settings_service.get_setting(
                db, "bmc_global_username", default=""
            )
            encrypted_password = await settings_service.get_setting(
                db, "bmc_global_password", default=""
            )
            password = credential_encryption.decrypt(encrypted_password) if encrypted_password else ""
            return username, password
        else:
            # 3. Per-server credentials
            username = server.username
            password = (
                credential_encryption.decrypt(server.password_encrypted)
                if server.password_encrypted
                else ""
            )
        return username, password

    async def _run_ipmi_command(
        self,
        host: str,
        user: str,
        password: str,
        interface: str,
        privilege: str,
        command: list,
        timeout: int,
        cipher_suite: Optional[str] = None,
    ) -> Tuple[int, str, str]:
        """Execute an arbitrary ipmitool command and return (exit_code, stdout, stderr)."""
        cmd = [
            "ipmitool",
            "-I", interface,
            "-N", "5",        # BMC auto-expires session after 5s idle
            "-R", "1",        # single retry, reduces session churn
        ]
        if cipher_suite:
            cmd.extend(["-C", cipher_suite])
        cmd.extend([
            "-L", privilege,
            "-H", host,
            "-U", user,
            "-P", password,
        ])
        cmd.extend(command)
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return (
                proc.returncode or 0,
                stdout.decode(errors="replace").strip(),
                stderr.decode(errors="replace").strip(),
            )
        except asyncio.TimeoutError:
            if proc is not None:
                proc.kill()
                await proc.wait()
            return (-1, "", "timeout: command exceeded time limit")
        except FileNotFoundError:
            return (-2, "", "ipmitool: command not found")
        except Exception as e:
            if proc is not None:
                proc.kill()
                await proc.wait()
            return (-3, "", str(e))

    async def _try_reset_one_server(
        self, server: BMCServer, username: str, password: str, timeout: int
    ) -> Dict[str, Any]:
        """Try all IPMI interface/privilege combos on a single server."""
        start_time = time.monotonic()
        total_attempts = 0
        last_error = ""
        last_stderr = ""
        last_command = ""

        for interface, privilege, cipher_suite in self.IPMI_COMBOS:
            for attempt in range(1, self.MAX_ATTEMPTS_PER_COMBO + 1):
                total_attempts += 1
                await bmc_reset_status_service.update_progress(
                    server_index=0,
                    server_name=server.name,
                    server_host=server.host,
                    attempt=total_attempts,
                    interface=f"{interface}/{privilege}{' -C ' + cipher_suite if cipher_suite else ''}",
                )
                exit_code, stdout, stderr = await self._run_ipmi_command(
                    server.host, username, password, interface, privilege,
                    ["mc", "reset", "cold"], timeout, cipher_suite=cipher_suite
                )
                cs = f" -C {cipher_suite}" if cipher_suite else ""
                last_command = f"ipmitool -I {interface}{cs} -L {privilege} -H {server.host} -U {username} -P *** mc reset cold"

                if exit_code == -2:
                    return {
                        "status": "failure",
                        "error_category": "ipmitool_not_found",
                        "error_message": "ipmitool command not found on server",
                        "attempts_made": total_attempts,
                        "duration_ms": int((time.monotonic() - start_time) * 1000),
                        "ipmi_command": "ipmitool: not found",
                    }

                if exit_code == 0 and not stderr:
                    return {
                        "status": "success",
                        "error_category": None,
                        "error_message": None,
                        "attempts_made": total_attempts,
                        "duration_ms": int((time.monotonic() - start_time) * 1000),
                        "ipmi_command": last_command,
                    }

                last_error = self._classify_error(stderr)
                last_stderr = stderr
                logger.debug(
                    f"BMC reset attempt {total_attempts} for {server.name} ({server.host}) "
                    f"via {interface}/{privilege}: exit={exit_code}, category={last_error}"
                )

        return {
            "status": "failure",
            "error_category": last_error or "unknown",
            "error_message": last_stderr[:1000] if last_stderr else "Unknown error",
            "attempts_made": total_attempts,
            "duration_ms": int((time.monotonic() - start_time) * 1000),
            "ipmi_command": last_command,
        }

    async def _execute_resets(
        self,
        session_id: str,
        server_ids: List[int],
        timeout: int,
        triggered_by: str,
    ) -> None:
        """Background task: execute resets on all target servers."""
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(BMCServer).where(
                        and_(
                            BMCServer.id.in_(server_ids),
                            BMCServer.enabled == True,
                        )
                    )
                )
                servers = result.scalars().all()

                for idx, server in enumerate(servers, 1):
                    try:
                        username, password = await self._get_credentials(db, server)
                    except ValueError as e:
                        outcome = {
                            "status": "failure",
                            "error_category": "unknown",
                            "error_message": str(e),
                            "attempts_made": 0,
                            "duration_ms": 0,
                            "ipmi_command": None,
                        }
                        await self._record_result(db, server, outcome, triggered_by)
                        await bmc_reset_status_service.server_complete(
                            server_id=server.id,
                            server_name=server.name,
                            server_host=server.host,
                            status="failure",
                            error_category="unknown",
                            error_message=str(e),
                            attempts_made=0,
                            duration_ms=0,
                        )
                        continue

                    outcome = await self._try_reset_one_server(
                        server, username, password, timeout
                    )
                    outcome["server_index"] = idx

                    await self._record_result(
                        db, server, outcome, triggered_by
                    )

                    await bmc_reset_status_service.server_complete(
                        server_id=server.id,
                        server_name=server.name,
                        server_host=server.host,
                        status=outcome["status"],
                        error_category=outcome.get("error_category"),
                        error_message=outcome.get("error_message"),
                        attempts_made=outcome.get("attempts_made", 0),
                        duration_ms=outcome.get("duration_ms", 0),
                    )

            await bmc_reset_status_service.complete_reset()

        except Exception as e:
            logger.error(f"BMC reset session {session_id} failed: {e}")
            await bmc_reset_status_service.fail_reset(error=str(e))

    async def _record_result(
        self,
        db: AsyncSession,
        server: BMCServer,
        outcome: Dict[str, Any],
        triggered_by: str,
    ) -> None:
        """Record reset result, update server status, and create/resolve alarms."""
        history = BMCResetHistory(
            bmc_server_id=server.id,
            server_name=server.name,
            server_host=server.host,
            status=outcome["status"],
            error_category=outcome.get("error_category"),
            error_message=outcome.get("error_message"),
            attempts_made=outcome.get("attempts_made", 0),
            duration_ms=outcome.get("duration_ms"),
            ipmi_command=outcome.get("ipmi_command"),
            triggered_by=triggered_by,
        )
        db.add(history)

        server.last_reset_at = func.now()
        server.last_reset_result = outcome["status"]

        if outcome["status"] == "failure":
            category = outcome.get("error_category", "unknown")
            msg = outcome.get("error_message", "")[:500]
            await alarm_service.create_alarm(
                db=db,
                severity=AlarmSeverity.ERROR,
                title=f"BMC Reset Failed: {server.name}",
                message=(
                    f"BMC cold reset failed for {server.name} ({server.host}). "
                    f"Error [{category}]: {msg}"
                ),
                source_type=AlarmSourceType.SYSTEM,
                source_id=server.id,
                source_name=f"bmc:{server.name}",
                details={
                    "server_id": server.id,
                    "server_host": server.host,
                    "error_category": category,
                    "attempts_made": outcome.get("attempts_made"),
                },
            )
        else:
            await alarm_service.auto_resolve_alarms(
                db=db,
                source_type=AlarmSourceType.SYSTEM,
                source_id=server.id,
            )

        await db.commit()
        await db.refresh(server)

    async def reset_servers(
        self,
        db: AsyncSession,
        server_ids: List[int],
        triggered_by: str = "manual",
    ) -> Tuple[str, int]:
        """Start a batch BMC reset and return (session_id, total_servers).

        The reset runs in the background. Subscribe to SSE for progress.
        Raises RuntimeError if a reset is already in progress.
        """
        if self._reset_lock.locked():
            raise RuntimeError("A BMC reset is already in progress")

        async with self._reset_lock:
            timeout_raw = await settings_service.get_setting(
                db, "bmc_reset_timeout_seconds", default=30
            )
            timeout = int(timeout_raw)

            result = await db.execute(
                select(BMCServer).where(
                    and_(
                        BMCServer.id.in_(server_ids),
                        BMCServer.enabled == True,
                    )
                )
            )
            servers = result.scalars().all()

            if not servers:
                raise ValueError("No enabled servers found matching the provided IDs")

            server_names = [s.name for s in servers]
            message = f"Starting BMC cold reset for {len(servers)} server(s): {', '.join(server_names[:5])}{'...' if len(server_names) > 5 else ''}"

            session_id = await bmc_reset_status_service.start_reset(
                total_servers=len(servers),
                message=message,
            )

            _schedule_bg(
                self._execute_resets(session_id, server_ids, timeout, triggered_by)
            )

            logger.info(
                f"BMC reset session {session_id} started for {len(servers)} servers (triggered_by={triggered_by})"
            )
            return session_id, len(servers)

    # ── CRUD ─────────────────────────────────────────────────────

    async def list_servers(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        enabled_only: bool = False,
        verified: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[BMCServer], int]:
        conditions = [True]
        if enabled_only:
            conditions.append(BMCServer.enabled == True)
        if verified is True:
            conditions.append(BMCServer.verified == True)
        elif verified is False:
            conditions.append(BMCServer.verified == False)
        if search:
            pattern = f"%{search}%"
            conditions.append(
                or_(BMCServer.host.ilike(pattern), BMCServer.name.ilike(pattern))
            )

        count_q = select(func.count(BMCServer.id)).where(and_(*conditions))
        total = (await db.execute(count_q)).scalar() or 0

        q = (
            select(BMCServer)
            .where(and_(*conditions))
            .order_by(BMCServer.name)
            .offset(skip)
            .limit(limit)
        )
        servers = (await db.execute(q)).scalars().all()
        return list(servers), total

    async def get_server(self, db: AsyncSession, server_id: int) -> Optional[BMCServer]:
        result = await db.execute(
            select(BMCServer).where(BMCServer.id == server_id)
        )
        return result.scalar_one_or_none()

    async def get_stale_unverified_ids(self, db: AsyncSession) -> list[int]:
        """Return IDs of servers that have verified=False and verify_error=NULL
        — meaning background verification never ran for them."""
        result = await db.execute(
            select(BMCServer.id).where(
                BMCServer.verified == False,
                BMCServer.verify_error.is_(None),
            )
        )
        return [r[0] for r in result.all()]

    async def get_servers_for_export(
        self, db: AsyncSession, verified_filter: Optional[bool] = None
    ) -> list[BMCServer]:
        """Return all servers matching the given verified filter, no pagination."""
        stmt = select(BMCServer).options(selectinload(BMCServer.credential_profile))
        if verified_filter is not None:
            stmt = stmt.where(BMCServer.verified == verified_filter)
        stmt = stmt.order_by(BMCServer.host)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def create_server(
        self, db: AsyncSession, data: "BMCServerCreate"
    ) -> BMCServer:
        # Check for duplicate host
        existing = await db.execute(
            select(BMCServer.id).where(BMCServer.host == data.host)
        )
        if existing.scalar():
            raise ValueError(f"Server with host {data.host} already exists — skipped")

        server = BMCServer(
            name=data.name,
            host=data.host,
            username=data.username,
            use_global_credentials=data.use_global_credentials,
            credential_profile_id=data.credential_profile_id,
            enabled=data.enabled,
            notes=data.notes,
        )
        if data.password:
            server.password_encrypted = credential_encryption.encrypt(data.password)
        db.add(server)
        await db.commit()
        await db.refresh(server)

        # Collect BMC info (SN, firmware) in background — completes within ~60s
        _schedule_bg(self._bg_collect_info(server.id))

        logger.info(f"BMC server created: {server.name} ({server.host})")
        return server

    async def update_server(
        self, db: AsyncSession, server_id: int, data: "BMCServerUpdate"
    ) -> Optional[BMCServer]:
        server = await self.get_server(db, server_id)
        if not server:
            return None
        update_data = data.model_dump(exclude_unset=True)
        if "password" in update_data:
            password = update_data.pop("password")
            if password:
                server.password_encrypted = credential_encryption.encrypt(password)
        for key, value in update_data.items():
            setattr(server, key, value)
        await db.commit()
        await db.refresh(server)
        logger.info(f"BMC server updated: {server.name} ({server.host})")
        return server

    async def batch_toggle_enabled(
        self, db: AsyncSession, server_ids: list, enabled: bool
    ) -> dict:
        """Batch enable or disable BMC servers."""
        updated = 0
        not_found = 0
        for sid in server_ids:
            server = await self.get_server(db, sid)
            if not server:
                not_found += 1
                continue
            server.enabled = enabled
            updated += 1
        await db.commit()
        logger.info(f"BMC batch toggle: set enabled={enabled} for {updated} servers ({not_found} not found)")
        return {"updated": updated, "not_found": not_found}

    async def delete_server(self, db: AsyncSession, server_id: int) -> bool:
        server = await self.get_server(db, server_id)
        if not server:
            return False
        await db.delete(server)
        await db.commit()
        logger.info(f"BMC server deleted: {server.name} ({server.host})")
        return True

    # ── History ──────────────────────────────────────────────────

    async def get_reset_history(
        self,
        db: AsyncSession,
        server_id: Optional[int] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[BMCResetHistory], int]:
        conditions = [True]
        if server_id is not None:
            conditions.append(BMCResetHistory.bmc_server_id == server_id)
        if status:
            conditions.append(BMCResetHistory.status == status)

        count_q = select(func.count(BMCResetHistory.id)).where(and_(*conditions))
        total = (await db.execute(count_q)).scalar() or 0

        q = (
            select(BMCResetHistory)
            .where(and_(*conditions))
            .order_by(BMCResetHistory.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = (await db.execute(q)).scalars().all()
        return list(rows), total

    # ── Global Credentials ───────────────────────────────────────

    async def get_global_credentials(
        self, db: AsyncSession
    ) -> Dict[str, Any]:
        username = await settings_service.get_setting(db, "bmc_global_username", default="")
        encrypted = await settings_service.get_setting(db, "bmc_global_password", default="")
        return {
            "username": username,
            "password_set": bool(encrypted),
        }

    async def update_global_credentials(
        self, db: AsyncSession, username: str, password: Optional[str]
    ) -> None:
        await settings_service.set_setting(db, "bmc_global_username", username, "string")
        if password:
            encrypted = credential_encryption.encrypt(password)
            await settings_service.set_setting(db, "bmc_global_password", encrypted, "string")
        logger.info("BMC global credentials updated")

    # ── Credential Profiles ──────────────────────────────────────

    async def list_credential_profiles(
        self, db: AsyncSession
    ) -> List[Dict[str, Any]]:
        """List all credential profiles with server counts."""
        from sqlalchemy import func as sa_func

        q = (
            select(
                BMCCredentialProfile,
                sa_func.count(BMCServer.id).label("server_count"),
            )
            .outerjoin(BMCServer, BMCServer.credential_profile_id == BMCCredentialProfile.id)
            .group_by(BMCCredentialProfile.id)
            .order_by(BMCCredentialProfile.name)
        )
        rows = (await db.execute(q)).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "username": p.username,
                "password_set": bool(p.password_encrypted),
                "server_count": count,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
            for p, count in rows
        ]

    async def get_credential_profile(
        self, db: AsyncSession, profile_id: int
    ) -> Optional[BMCCredentialProfile]:
        return await db.get(BMCCredentialProfile, profile_id)

    async def create_credential_profile(
        self, db: AsyncSession, name: str, username: str, password: Optional[str]
    ) -> BMCCredentialProfile:
        profile = BMCCredentialProfile(name=name, username=username)
        if password:
            profile.password_encrypted = credential_encryption.encrypt(password)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        logger.info(f"BMC credential profile created: {profile.name}")
        return profile

    async def update_credential_profile(
        self, db: AsyncSession, profile_id: int,
        name: Optional[str], username: Optional[str], password: Optional[str]
    ) -> Optional[BMCCredentialProfile]:
        profile = await db.get(BMCCredentialProfile, profile_id)
        if not profile:
            return None
        if name is not None:
            profile.name = name
        if username is not None:
            profile.username = username
        if password:
            profile.password_encrypted = credential_encryption.encrypt(password)
        await db.commit()
        await db.refresh(profile)
        logger.info(f"BMC credential profile updated: {profile.name}")
        return profile

    async def delete_credential_profile(
        self, db: AsyncSession, profile_id: int
    ) -> bool:
        profile = await db.get(BMCCredentialProfile, profile_id)
        if not profile:
            return False
        await db.delete(profile)
        await db.commit()
        logger.info(f"BMC credential profile deleted: {profile.name}")
        return True

    async def get_schedule_settings(self, db: AsyncSession) -> Dict[str, Any]:
        return {
            "enabled": await settings_service.get_setting(db, "bmc_monthly_reset_enabled", default=False),
            "day": int(await settings_service.get_setting(db, "bmc_monthly_reset_day", default=1)),
            "hour": int(await settings_service.get_setting(db, "bmc_monthly_reset_hour", default=2)),
            "timeout": int(await settings_service.get_setting(db, "bmc_reset_timeout_seconds", default=30)),
        }

    async def update_schedule_setting(
        self, db: AsyncSession, key: str, value: Any, data_type: str = "string"
    ) -> None:
        await settings_service.set_setting(db, key, value, data_type)

    # ── BMC Info Query ────────────────────────────────────────────

    @staticmethod
    def _friendly_error(category: str, raw_stderr: str) -> str:
        """Convert an error category into a human-readable message."""
        messages = {
            "ipmitool_not_found": "ipmitool not found on server",
            "ip_unreachable": "IP unreachable or IPMI service not responding",
            "auth_failure": "Authentication failed — check username/password",
            "cipher_mismatch": "Cipher suite mismatch — BMC may need IPMI 1.5 enabled or firmware update",
            "timeout": "Connection timed out — IP unreachable or BMC not responding",
        }
        prefix = messages.get(category, "Unknown error")
        # Append a snippet of raw stderr for technical detail (trimmed)
        if raw_stderr:
            short = raw_stderr.strip()[:120]
            return f"{prefix}: {short}"
        return prefix

    async def query_bmc_info(
        self, db: AsyncSession, server_id: int
    ) -> Dict[str, Any]:
        """Query BMC for serial number (FRU) and firmware version (MC Info).

        On success, sets verified=True, serial_number, bmc_firmware_version.
        On failure, sets verified=False with a human-readable verify_error.
        """
        server = await self.get_server(db, server_id)
        if not server:
            raise ValueError("Server not found")

        username, password = await self._get_credentials(db, server)
        timeout = int(await settings_service.get_setting(db, "bmc_reset_timeout_seconds", default=30))

        serial_number = None
        product_name = None
        manufacturer = None
        bmc_firmware_version = None
        fru_raw = None
        mc_info_raw = None
        last_error_category = None
        last_error_stderr = ""

        # Query FRU for serial number — try all combos
        for interface, privilege, cipher_suite in self.IPMI_COMBOS:
            exit_code, stdout, stderr = await self._run_ipmi_command(
                server.host, username, password, interface, privilege,
                ["fru"], min(timeout, 5), cipher_suite=cipher_suite
            )
            if stdout:
                fru_raw = stdout[:2000]
                for line in stdout.split("\n"):
                    line_stripped = line.strip()
                    if "Product Serial" in line_stripped:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            val = parts[1].strip()
                            if val and val != "N/A" and val != "Unknown":
                                serial_number = val
                                break
                    if "Product Name" in line_stripped:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            product_name = parts[1].strip()
                    if "Product Manufacturer" in line_stripped or "Board Mfg" in line_stripped:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            manufacturer = parts[1].strip()
                break  # got a response, stop trying combos
            if stderr:
                last_error_stderr = stderr
                last_error_category = self._classify_error(stderr)

        # Query MC Info for firmware version — try all combos
        for interface, privilege, cipher_suite in self.IPMI_COMBOS:
            exit_code, stdout, stderr = await self._run_ipmi_command(
                server.host, username, password, interface, privilege,
                ["mc", "info"], min(timeout, 5), cipher_suite=cipher_suite
            )
            if stdout:
                mc_info_raw = stdout[:2000]
                for line in stdout.split("\n"):
                    if "Firmware Revision" in line:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            bmc_firmware_version = parts[1].strip()
                            break
                break  # got a response, stop trying combos
            if stderr:
                last_error_stderr = stderr
                last_error_category = self._classify_error(stderr)

        # Update server record
        if fru_raw or mc_info_raw:
            # Success: got IPMI data back
            if serial_number or bmc_firmware_version:
                server.serial_number = serial_number
                server.bmc_firmware_version = bmc_firmware_version
                server.bmc_info_updated_at = func.now()
            server.verified = True
            server.verify_error = None
        else:
            # Failure: no response from any combo
            server.verified = False
            server.verify_error = self._friendly_error(
                last_error_category or "timeout", last_error_stderr
            )
        await db.commit()
        await db.refresh(server)

        return {
            "server_id": server.id,
            "serial_number": serial_number,
            "bmc_firmware_version": bmc_firmware_version,
            "product_name": product_name,
            "manufacturer": manufacturer,
            "fru_raw": fru_raw,
            "mc_info_raw": mc_info_raw,
        }

    async def _bg_collect_info(self, server_id: int) -> None:
        """Background task: collect BMC info (SN, firmware) for a newly created server.

        Runs within 60s. Sets verified=True on success, or verified=False with
        a human-readable verify_error on failure.
        """
        try:
            async with AsyncSessionLocal() as bg_db:
                await self.query_bmc_info(bg_db, server_id)
        except ValueError:
            pass  # server deleted before we could collect
        except Exception as e:
            logger.warning(f"Background BMC info collection failed for server {server_id}: {e}")

    async def _collect_bmc_info_for_server(
        self, db: AsyncSession, server: BMCServer, username: str, password: str
    ) -> None:
        """Collect BMC info (SN, firmware) for a server with explicit credentials.

        Tries all IPMI combos. On success updates serial_number, bmc_firmware_version,
        verified=True. On failure sets verified=False with human-readable verify_error.
        Commits changes to the given session (caller owns the session).
        """
        timeout = int(await settings_service.get_setting(db, "bmc_reset_timeout_seconds", default=30))
        serial_number = None
        bmc_firmware_version = None
        fru_raw = None
        mc_info_raw = None
        last_error_category = None
        last_error_stderr = ""

        # Query FRU for serial number
        for interface, privilege, cipher_suite in self.IPMI_COMBOS:
            exit_code, stdout, stderr = await self._run_ipmi_command(
                server.host, username, password, interface, privilege,
                ["fru"], min(timeout, 5), cipher_suite=cipher_suite
            )
            if stdout:
                fru_raw = stdout[:2000]
                for line in stdout.split("\n"):
                    if "Product Serial" in line:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            val = parts[1].strip()
                            if val and val != "N/A" and val != "Unknown":
                                serial_number = val
                                break
                break
            if stderr:
                last_error_stderr = stderr
                last_error_category = self._classify_error(stderr)

        # Query MC Info for firmware version
        for interface, privilege, cipher_suite in self.IPMI_COMBOS:
            exit_code, stdout, stderr = await self._run_ipmi_command(
                server.host, username, password, interface, privilege,
                ["mc", "info"], min(timeout, 5), cipher_suite=cipher_suite
            )
            if stdout:
                mc_info_raw = stdout[:2000]
                for line in stdout.split("\n"):
                    if "Firmware Revision" in line:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            bmc_firmware_version = parts[1].strip()
                            break
                break
            if stderr:
                last_error_stderr = stderr
                last_error_category = self._classify_error(stderr)

        if fru_raw or mc_info_raw:
            if serial_number or bmc_firmware_version:
                server.serial_number = serial_number
                server.bmc_firmware_version = bmc_firmware_version
                server.bmc_info_updated_at = func.now()
            server.verified = True
            server.verify_error = None
        else:
            server.verified = False
            server.verify_error = self._friendly_error(
                last_error_category or "timeout", last_error_stderr
            )
        await db.commit()

    # ── Batch Import ──────────────────────────────────────────────

    async def _batch_verify(
        self, server_ids: List[int], data: "BMCBatchImportRequest"
    ) -> None:
        """Background task: verify and collect BMC info for batch-imported servers."""
        async with AsyncSessionLocal() as bg_db:
            for server_id in server_ids:
                try:
                    server = await bg_db.get(BMCServer, server_id)
                    if not server:
                        continue
                    v_user, v_pass = await self._get_credentials(bg_db, server)
                    # Fallback to the credentials provided in the import request
                    if not v_user:
                        v_user = data.username
                        v_pass = data.password or ""
                    if not v_user:
                        server.verified = False
                        server.verify_error = "No IPMI credentials configured"
                        await bg_db.commit()
                    else:
                        # Use query_bmc_info for full collection (SN + firmware + verify)
                        # It handles its own commit and error classification
                        await self._collect_bmc_info_for_server(bg_db, server, v_user, v_pass)
                except Exception as e:
                    logger.warning(f"Background verify failed for server {server_id}: {e}")
                    try:
                        server = await bg_db.get(BMCServer, server_id)
                        if server:
                            server.verified = False
                            server.verify_error = str(e)[:200]
                            await bg_db.commit()
                    except Exception:
                        pass
            logger.info(f"Background batch verify complete: {len(server_ids)} servers")

    async def batch_create_servers(
        self, db: AsyncSession, data: "BMCBatchImportRequest"
    ) -> Dict[str, Any]:
        """Create BMC server entries from an IP range or list."""
        import ipaddress
        import re

        # Resolve IP list: ips field (comma/newline separated) takes priority
        hosts: list[str] = []
        if data.ips:
            raw = data.ips.replace(",", "\n")
            candidates = [h.strip() for h in raw.split("\n") if h.strip()]
            for h in candidates:
                try:
                    ipaddress.IPv4Address(h)
                    hosts.append(h)
                except ValueError:
                    pass  # skip invalid IPs silently
            if not hosts:
                raise ValueError("No valid IP addresses found in input")
        elif data.ip_start and data.ip_end:
            try:
                start_ip = ipaddress.IPv4Address(data.ip_start)
                end_ip = ipaddress.IPv4Address(data.ip_end)
            except ValueError as e:
                raise ValueError(f"Invalid IP address: {e}")
            if start_ip > end_ip:
                raise ValueError("ip_start must be <= ip_end")
            current = start_ip
            while current <= end_ip:
                hosts.append(str(current))
                current += 1
        else:
            raise ValueError("Provide either an IP list (ips) or a range (ip_start/ip_end)")

        if len(hosts) > 1000:
            hosts = hosts[:1000]

        # Check for duplicates
        result = await db.execute(select(BMCServer.host))
        existing_hosts = {r[0] for r in result.all()}

        created = []
        skipped = 0
        errors = []

        for host in hosts:
            try:
                if host in existing_hosts:
                    skipped += 1
                else:
                    server = BMCServer(
                        name=host,
                        host=host,
                        username=data.username,
                        use_global_credentials=data.use_global_credentials,
                        credential_profile_id=data.credential_profile_id,
                        enabled=data.enabled,
                    )
                    if data.password:
                        server.password_encrypted = credential_encryption.encrypt(data.password)
                    db.add(server)
                    await db.flush()
                    created.append(server)
            except Exception as e:
                errors.append(f"{host}: {e}")

        if created:
            await db.commit()
            server_ids = []
            for s in created:
                await db.refresh(s)
                server_ids.append(s.id)

            # Verify connectivity in background (avoids 504 on large batches)
            _schedule_bg(self._batch_verify(server_ids, data))

        logger.info(f"BMC batch import: {len(created)} created, {skipped} skipped")
        return {
            "total": len(created) + skipped,
            "created": len(created),
            "skipped": skipped,
            "errors": errors,
            "servers": created,
        }


bmc_service = BMCService()
