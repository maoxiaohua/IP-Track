"""
交换机配置备份服务（严格只读）

核心约束：
- 只执行各厂商的 show/display 类**只读**命令取 running-config，
  绝不调用 save_config / config_mode，也绝不下发 copy running-config startup-config、
  write memory 等写配置命令；
- 正文按 sha256 内容寻址存入 config_blobs，内容未变不新增版本；
- 同时落盘到 CONFIG_BACKUP_DIR/switch_<id>/<sha256>.cfg，便于离线导出；
- 每一次备份尝试（成功或失败）都在 config_backups 留一行，供模块页/详情页展示。

日志里只记录大小/哈希/耗时，绝不打印配置正文（可能含口令、密钥）。
"""

import asyncio
import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import AsyncSessionLocal
from models.config_backup import ConfigBackup, ConfigBlob
from models.switch import Switch
from services.cli_service import cli_service
from services.settings_service import SettingsService
from utils.logger import logger

# system_settings 键（迁移 035 已插入初始值）
INTERVAL_SETTING_KEY = 'config_backup_interval_minutes'
RETENTION_SETTING_KEY = 'config_backup_retention_versions'
DEFAULT_INTERVAL_MINUTES = 1440
DEFAULT_RETENTION_VERSIONS = 30

# 同机 running 记录超过该时长视为进程中断，可重新备份
RUNNING_STALE_MINUTES = 10
# 低于该字节数的输出基本不可能是完整配置
MIN_CONFIG_BYTES = 100

# vendor -> (netmiko device_type, 只读备份命令)
# 参考 Oxidized 的 per-OS 命令表，仅借用命令，不引入其运行时。
VENDOR_PRESETS: Dict[str, Tuple[str, str]] = {
    'cisco': ('cisco_ios', 'show running-config'),
    'arista': ('arista_eos', 'show running-config'),
    'juniper': ('juniper_junos', 'show configuration | display set'),
    'huawei': ('huawei', 'display current-configuration'),
    'h3c': ('hp_comware', 'display current-configuration'),
    'hpe': ('hp_comware', 'display current-configuration'),
    # MD-CLI 设备（7220 IXR-D1/D2 等）用 info flat，输出统一的 "set /" 逐条格式；
    # 经典 CLI 设备由 VENDOR_FALLBACK_TARGETS 回退到 admin display-config。
    'alcatel': ('nokia_sros', 'info flat'),
    'dell': ('dell_force10', 'show running-config'),
    'fortinet': ('fortinet', 'show full-configuration'),
    'extreme': ('extreme_exos', 'show configuration'),
    'aruba': ('hp_procurve', 'show running-config'),
    'mikrotik': ('mikrotik_routeros', '/export'),
    'paloalto': ('paloalto_panos', 'show config running'),
}

# 同一厂商不同 NOS 的备份目标和命令不一致时的候选组合（按顺序尝试，第一个校验通过即采用）。
# Dell：dell_force10 驱动 + show running-config 在 OS9(FTOS) 与 OS10(10.5.x) 上均实测可行，
# 所以默认先试它；OS10 另有 show running-configuration（dell_os10 驱动）作为后备。
# 不能先试 dell_os10：OS9 机器上提示符不匹配，要白等约 90~130 秒才超时。
# Nokia SR OS：MD-CLI 用 info flat（set / 格式，默认），经典 CLI 回退 admin display-config，
# 最后才用 info。统一优先 info flat，避免同一厂商备份出两种文本格式。
VENDOR_FALLBACK_TARGETS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    'dell': (
        ('dell_os10', 'show running-configuration'),
    ),
    'alcatel': (
        ('nokia_sros', 'admin display-config'),
        ('nokia_sros', 'info'),
    ),
}

# 命令执行失败的典型输出特征（小写匹配）
_INVALID_MARKERS = (
    '% invalid input',
    '% error',
    '% incomplete command',
    '% unrecognized',
    'unrecognized command',
    'invalid syntax',
    'error: unrecognized',
    'syntax error',
    'parsing error',
    'unknown command',
)


def _describe_fetch_error(exc: Exception) -> str:
    """把 Netmiko 异常转成可读原因（页面直接展示）。"""
    name = type(exc).__name__
    text = str(exc)
    first_line = (text.strip().splitlines() or [''])[0]
    # paramiko 在 auth_timeout 到期时抛 AuthenticationException("Authentication timeout.")，
    # 真正的凭据拒绝是 "Authentication failed."，两者必须区分开。
    if 'Authentication' in name:
        if 'Authentication timeout' in text:
            return 'SSH 登录响应超时（网络慢/设备响应慢，并非密码错误）'
        return f'认证失败，请检查用户名/密码或 enable 密码（{first_line or name}）'
    if 'Timeout' in name or 'timed out' in first_line.lower():
        return f'连接超时或设备无响应（{first_line or name}）'
    return f'{name}: {first_line}' if first_line else name


def _cli_port(transport: Optional[str], port: Optional[int]) -> int:
    _, resolved = cli_service.normalize_cli_connection_settings(
        transport, port, port_was_explicit=bool(port)
    )
    return resolved


async def _tcp_reachable(ip: str, port: int, timeout: float = 3.0) -> bool:
    """轻量 TCP 探测（不登录设备），用于判断网络是否恢复可达。"""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
    except Exception:
        return False
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass
    return True


async def _set_backup_unreachable(db: AsyncSession, switch_id: int, value: bool) -> None:
    """标记/解除“网络不可达”，计划备份据此暂停或恢复。失败不影响本次备份流程。"""
    try:
        await db.execute(
            update(Switch).where(Switch.id == switch_id).values(backup_unreachable=value)
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning(f"更新网络可达状态失败 switch={switch_id}: {exc}")


def resolve_backup_target(switch: Switch) -> Tuple[Optional[str], Optional[str], str]:
    """解析该交换机的 (device_type, 备份命令, 说明)。

    优先级：人工覆盖字段 -> 厂商预设 -> 无法确定时返回不支持说明。
    """
    vendor = (switch.vendor or '').strip().lower()
    device_type = (switch.backup_device_type or '').strip() or None
    command = (switch.backup_config_command or '').strip() or None
    preset = VENDOR_PRESETS.get(vendor)

    if preset:
        preset_device_type, preset_command = preset
        # Dell 同一厂商有两种 CLI 驱动，按型号提示切换
        if vendor == 'dell' and not (switch.backup_device_type or '').strip():
            model = (switch.model or '').lower()
            if 'force10' in model or 'powerconnect' in model or 'ftos' in model:
                preset_device_type, preset_command = 'dell_force10', 'show running-config'
        if not device_type:
            device_type = preset_device_type
        if not command:
            command = preset_command

    if not device_type or not command:
        return None, None, '该品牌未内置备份命令，请在“备份设置”中填写 CLI 驱动与备份命令'
    return device_type, command, ''


def _ensure_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# 设备回显的装饰行，如 SR OS 的 --{ [OLD RESCUE] running }--[  ]--
_BANNER_RE = re.compile(r'^[-=*~_\s]*\{[^{}]*\}[-=*~_\s]*(?:\[[^\[\]]*\])?[-=*~_\s]*$')
# 纯提示符行：SW1# / user@host> / <SW1>
_PROMPT_ONLY_RE = re.compile(r'^\S+[#>]$|^<[^<>]+>$')


def _is_preamble_line(line: str, command: str) -> bool:
    """判断是否为命令回显/提示符/banner 等非配置正文行。"""
    s = line.strip()
    if not s:
        return True
    if _BANNER_RE.match(s) or _PROMPT_ONLY_RE.match(s):
        return True
    if s == command.strip():
        return True
    # 提示符 + 回显命令，命令后可能紧跟 banner：
    # A:SW1# admin display-config--{ [OLD RESCUE] running }--[  ]--
    if re.match(r'^.*[#>]\s*' + re.escape(command.strip()), s):
        return True
    return False


def clean_config_output(output: str, command: str) -> str:
    """去掉命令回显、末尾提示符与空行，统一为 LF 换行。"""
    text = (output or '').replace('\x00', '').replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')
    # 只清理开头的回显区（限前 10 行），避免误伤正文；
    # 设备在无配置/报错时可能只剩回显，清理后应得到空文本。
    idx = 0
    limit = min(len(lines), 10)
    while idx < limit and _is_preamble_line(lines[idx], command):
        idx += 1
    lines = lines[idx:]
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and (_PROMPT_ONLY_RE.match(lines[-1].strip()) or _BANNER_RE.match(lines[-1].strip())):
        lines.pop()
    return '\n'.join(lines).strip() + '\n'


def validate_config_text(text: str) -> Optional[str]:
    """完整性校验，返回失败原因；合格返回 None。"""
    if not text or not text.strip():
        return '设备未返回配置内容'
    size = len(text.encode('utf-8'))
    if size < MIN_CONFIG_BYTES:
        return f'返回内容过短（{size} 字节），可能不是完整配置'
    lowered = text.lower()
    for marker in _INVALID_MARKERS:
        if marker in lowered:
            return f'命令执行报错（输出包含 “{marker}”），未保存为有效版本'
    return None


def _backup_file_path(switch_id: int, sha256: str) -> Path:
    return Path(settings.CONFIG_BACKUP_DIR) / f'switch_{switch_id}' / f'{sha256}.cfg'


def _write_backup_file(switch_id: int, sha256: str, content: str) -> Path:
    path = _backup_file_path(switch_id, sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.cfg.tmp')
    tmp.write_text(content, encoding='utf-8', errors='replace')
    tmp.replace(path)
    return path


def _remove_backup_file(switch_id: int, sha256: str) -> None:
    try:
        _backup_file_path(switch_id, sha256).unlink(missing_ok=True)
    except Exception as exc:  # 文件清理失败不影响记录清理
        logger.warning(f"删除备份文件失败 switch={switch_id} sha={sha256[:12]}: {exc}")


async def get_global_interval_minutes(db: AsyncSession) -> int:
    value = await SettingsService.get_setting(db, INTERVAL_SETTING_KEY, DEFAULT_INTERVAL_MINUTES)
    try:
        return max(5, int(value))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_MINUTES


async def get_retention_versions(db: AsyncSession) -> int:
    value = await SettingsService.get_setting(db, RETENTION_SETTING_KEY, DEFAULT_RETENTION_VERSIONS)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_VERSIONS


async def _has_active_running_backup(db: AsyncSession, switch_id: int) -> bool:
    """同机已有进行中的备份则拒绝重入；超时的僵尸 running 记录就地判失败。"""
    rows = (await db.execute(
        select(ConfigBackup).where(
            ConfigBackup.switch_id == switch_id,
            ConfigBackup.status == 'running',
        )
    )).scalars().all()
    if not rows:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=RUNNING_STALE_MINUTES)
    active = False
    for row in rows:
        started = _ensure_aware(row.started_at)
        if started and started > cutoff:
            active = True
        else:
            row.status = 'failed'
            row.message = '备份进程异常中断（超时未完成）'
            row.finished_at = datetime.now(timezone.utc)
    await db.commit()
    return active


async def backup_switch_config(
    db: AsyncSession,
    switch: Switch,
    trigger: str = 'manual',
) -> Dict[str, Any]:
    """对单台交换机做一次只读配置备份，失败也落库，绝不向调度器抛异常。"""
    # 先快照需要的属性：后续 commit/rollback 可能让 switch 对象过期，
    # 异步会话里再惰性加载会抛 MissingGreenlet。
    switch_id = switch.id
    switch_ip = str(switch.ip_address)
    switch_config = {
        'username': switch.username,
        'password_encrypted': switch.password_encrypted,
        'vendor': switch.vendor,
        'model': switch.model,
        'name': switch.name,
        'cli_transport': switch.cli_transport,
        'ssh_port': switch.ssh_port,
        'connection_timeout': switch.connection_timeout,
        'enable_password_encrypted': switch.enable_password_encrypted,
        # 慢链路下放宽 SSH banner/认证超时（Netmiko 默认 15s 会被误判成认证失败）
        'handshake_timeout': settings.CONFIG_BACKUP_HANDSHAKE_TIMEOUT_SECONDS,
    }
    cli_ready = bool(switch.cli_enabled and switch.username and switch.password_encrypted)
    was_unreachable = bool(getattr(switch, 'backup_unreachable', False))

    device_type, command, reason = resolve_backup_target(switch)
    if not device_type or not command:
        return {'status': 'unsupported', 'message': reason, 'backup_id': None}
    if not cli_ready:
        return {'status': 'skipped', 'message': '该交换机未启用 CLI 或缺少 SSH 凭据', 'backup_id': None}

    if await _has_active_running_backup(db, switch_id):
        return {'status': 'skipped', 'message': '该交换机已有备份任务正在执行', 'backup_id': None}

    record = ConfigBackup(
        switch_id=switch_id,
        status='running',
        trigger_source=trigger,
        device_type=device_type,
        command=command,
        message='正在备份',
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    backup_id = record.id
    started_at = _ensure_aware(record.started_at) or datetime.now(timezone.utc)
    timer = time.monotonic()

    try:
        # 人工填写了命令就只用它；否则按厂商候选 (驱动, 命令) 依次尝试
        # （如 Dell OS10/OS9 驱动与命令都不同，Nokia 经典 CLI 与 MD-CLI 命令不同）
        targets = [(device_type, command)]
        if not (switch.backup_config_command or '').strip():
            for alt_dt, alt_cmd in VENDOR_FALLBACK_TARGETS.get((switch.vendor or '').strip().lower(), ()):
                if (alt_dt, alt_cmd) not in targets:
                    targets.append((alt_dt, alt_cmd))

        content = ''
        command_used = command
        device_type_used = device_type
        errors = []
        for dt, cmd in targets:
            attempt_timer = time.monotonic()
            try:
                raw = await asyncio.to_thread(
                    cli_service.fetch_running_config,
                    switch_ip,
                    switch_config,
                    dt,
                    cmd,
                )
            except Exception as cmd_exc:
                errors.append(f'{cmd}: {_describe_fetch_error(cmd_exc)}')
                name = type(cmd_exc).__name__
                elapsed = time.monotonic() - attempt_timer
                slow_threshold = settings.CONFIG_BACKUP_SLOW_CONNECT_SECONDS
                # 登录阶段超时（paramiko "Authentication timeout."）是网络慢，不是密码错
                auth_timeout_hit = 'Authentication timeout' in str(cmd_exc)
                # 只有“连接/登录阶段”的失败才需要判定网络；命令/解析类错误可换命令重试。
                # 必须 raise 不能 break：break 会跳过 for/else 的抛错，
                # 导致空内容被当作成功备份（0 字节）。
                if 'Timeout' in name or 'Authentication' in name or elapsed >= slow_threshold:
                    port = _cli_port(switch_config.get('cli_transport'), switch_config.get('ssh_port'))
                    tcp_ok = await _tcp_reachable(switch_ip, port)
                    if not tcp_ok:
                        # TCP 都不通才是真不可达：暂停计划备份，等探测恢复
                        errors[-1] = f'网络不可达（TCP {switch_ip}:{port} 探测失败）'
                        await _set_backup_unreachable(db, switch_id, True)
                    elif 'Authentication' in name and not auth_timeout_hit and elapsed < slow_threshold:
                        # TCP 可达且很快被拒：真正的凭据/AAA 拒绝
                        if was_unreachable:
                            await _set_backup_unreachable(db, switch_id, False)
                    else:
                        # TCP 可达但登录超时：网络慢/设备响应慢，不是认证问题
                        errors[-1] = (
                            f'网络慢：SSH 登录在 {elapsed:.0f}s 内未完成'
                            f'（TCP 可达，非凭据问题）'
                        )
                        if was_unreachable:
                            await _set_backup_unreachable(db, switch_id, False)
                    raise RuntimeError('; '.join(errors)[:2000]) from cmd_exc
                continue
            candidate = clean_config_output(raw, cmd)
            invalid = validate_config_text(candidate)
            if invalid:
                errors.append(f'{cmd}: {invalid}')
                continue
            content = candidate
            command_used = cmd
            device_type_used = dt
            break
        else:
            raise RuntimeError('; '.join(errors)[:2000] or '未获取到有效配置')

        encoded = content.encode('utf-8')
        sha256 = hashlib.sha256(encoded).hexdigest()
        size_bytes = len(encoded)

        blob = await db.get(ConfigBlob, sha256)
        if not blob:
            db.add(ConfigBlob(sha256=sha256, content=content, size_bytes=size_bytes))
            # 先提交 blob：config_backups.sha256 有外键，同一次 flush 里插入顺序
            # 不保证（两个模型之间没有 ORM relationship），必须先确保 blob 存在。
            await db.commit()

        # 文件写失败按整次备份失败处理（与 DB 双写语义一致）
        file_path = _write_backup_file(switch_id, sha256, content)

        unchanged = (await db.execute(
            select(func.count(ConfigBackup.id)).where(
                ConfigBackup.switch_id == switch_id,
                ConfigBackup.status == 'success',
                ConfigBackup.sha256 == sha256,
            )
        )).scalar() or 0

        record = await db.get(ConfigBackup, backup_id)
        record.status = 'success'
        record.command = command_used
        record.device_type = device_type_used
        record.sha256 = sha256
        record.size_bytes = size_bytes
        record.file_path = str(file_path)
        record.message = '配置内容未变化，已确认与上次一致' if unchanged else '备份成功'
        record.finished_at = datetime.now(timezone.utc)
        record.duration_ms = int((time.monotonic() - timer) * 1000)
        await db.commit()

        # 本次成功说明网络已可达：解除暂停标记
        if was_unreachable:
            await _set_backup_unreachable(db, switch_id, False)

        await _enforce_retention(db, switch_id)
        logger.info(
            f"配置备份成功 switch={switch_id} ip={switch_ip} "
            f"size={size_bytes} sha={sha256[:12]} unchanged={bool(unchanged)} "
            f"duration={record.duration_ms}ms"
        )
        return {
            'status': 'success',
            'message': record.message,
            'backup_id': backup_id,
            'sha256': sha256,
            'size_bytes': size_bytes,
            'duration_ms': record.duration_ms,
        }

    except Exception as exc:
        await db.rollback()
        message = f'{type(exc).__name__}: {exc}'[:2000]
        logger.error(f"配置备份失败 switch={switch_id} ip={switch_ip}: {message}")
        try:
            record = await db.get(ConfigBackup, backup_id)
            if record:
                record.status = 'failed'
                record.message = message
                record.finished_at = datetime.now(timezone.utc)
                record.duration_ms = int((time.monotonic() - timer) * 1000)
                await db.commit()
        except Exception as record_err:
            logger.error(f"写入备份失败状态出错 switch={switch_id}: {record_err}")
        return {'status': 'failed', 'message': message, 'backup_id': backup_id}


async def _enforce_retention(db: AsyncSession, switch_id: int) -> int:
    """只保留该机最近 N 个不同内容版本，删除更旧记录、文件与无引用的 blob。"""
    retention = await get_retention_versions(db)
    rows = (await db.execute(
        select(ConfigBackup.sha256, func.max(ConfigBackup.started_at).label('last_at'))
        .where(
            ConfigBackup.switch_id == switch_id,
            ConfigBackup.status == 'success',
            ConfigBackup.sha256.isnot(None),
        )
        .group_by(ConfigBackup.sha256)
        .order_by(func.max(ConfigBackup.started_at).desc())
    )).all()
    dropped = [row[0] for row in rows[retention:]]
    if not dropped:
        return 0

    await db.execute(
        delete(ConfigBackup).where(
            ConfigBackup.switch_id == switch_id,
            ConfigBackup.sha256.in_(dropped),
        )
    )
    await db.commit()

    for sha256 in dropped:
        _remove_backup_file(switch_id, sha256)
        still_used = (await db.execute(
            select(func.count(ConfigBackup.id)).where(ConfigBackup.sha256 == sha256)
        )).scalar() or 0
        if not still_used:
            await db.execute(delete(ConfigBlob).where(ConfigBlob.sha256 == sha256))
    await db.commit()
    logger.info(f"清理旧版本 switch={switch_id} 删除 {len(dropped)} 个版本")
    return len(dropped)


async def _fail_stale_running(db: AsyncSession) -> int:
    """把进程中断遗留的 running 记录统一判失败，避免页面一直显示“运行中”。"""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=RUNNING_STALE_MINUTES)
    result = await db.execute(
        update(ConfigBackup)
        .where(ConfigBackup.status == 'running', ConfigBackup.started_at < cutoff)
        .values(
            status='failed',
            message='备份进程异常中断（超时未完成）',
            finished_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    count = result.rowcount or 0
    if count:
        logger.warning(f"配置备份：清理中断的 running 记录 {count} 条")
    return count


async def run_due_backups(db: AsyncSession) -> Dict[str, int]:
    """扫描到期交换机并执行备份（供 5 分钟 tick 调用）。"""
    if not settings.CONFIG_BACKUP_ENABLED:
        return {'due': 0, 'success': 0, 'failed': 0, 'skipped': 0}

    await _fail_stale_running(db)
    global_interval = await get_global_interval_minutes(db)

    switches = (await db.execute(
        select(Switch).where(
            Switch.enabled.is_(True),
            Switch.cli_enabled.is_(True),
            Switch.backup_enabled.is_(True),
            Switch.username.isnot(None),
            Switch.password_encrypted.isnot(None),
        )
    )).scalars().all()

    last_success_rows = (await db.execute(
        select(ConfigBackup.switch_id, func.max(ConfigBackup.started_at))
        .where(ConfigBackup.status == 'success')
        .group_by(ConfigBackup.switch_id)
    )).all()
    last_success_map = {sid: _ensure_aware(ts) for sid, ts in last_success_rows}

    last_attempt_rows = (await db.execute(
        select(ConfigBackup.switch_id, func.max(ConfigBackup.started_at))
        .group_by(ConfigBackup.switch_id)
    )).all()
    last_attempt_map = {sid: _ensure_aware(ts) for sid, ts in last_attempt_rows}
    retry_delay = timedelta(minutes=max(1, settings.CONFIG_BACKUP_RETRY_MINUTES))

    now = datetime.now(timezone.utc)

    # 先快照后续需要的字段：下面会把“网络恢复”的标记写库并 commit，
    # commit 会让 ORM 对象过期，之后再访问 sw.xxx 会触发异步惰性加载（MissingGreenlet）。
    plan = []
    for sw in switches:
        _, command, _ = resolve_backup_target(sw)
        if not command:
            continue
        plan.append((
            sw.id,
            sw.backup_interval_minutes,
            bool(getattr(sw, 'backup_unreachable', False)),
            str(sw.ip_address),
            sw.cli_transport,
            sw.ssh_port,
        ))

    # 网络不可达的交换机默认跳过；每轮先做轻量 TCP 探测，恢复可达才重新纳入计划备份。
    paused = [p for p in plan if p[2]]
    recovered = set()
    if paused:
        results = await asyncio.gather(*(
            _tcp_reachable(p[3], _cli_port(p[4], p[5])) for p in paused
        ))
        recovered = {p[0] for p, ok in zip(paused, results) if ok}
        for sid in recovered:
            await _set_backup_unreachable(db, sid, False)
        logger.info(
            f"配置备份：{len(paused)} 台此前网络不可达，探测恢复 {len(recovered)} 台"
        )

    due_ids = []
    paused_count = 0
    for sid, interval_override, unreachable_flag, *_ in plan:
        if unreachable_flag and sid not in recovered:
            paused_count += 1
            continue
        interval = interval_override or global_interval
        # 到期判断以上次“成功”为准：失败不应让设备荒废一整个间隔
        last_ok = last_success_map.get(sid)
        if last_ok and now - last_ok < timedelta(minutes=interval):
            continue
        # 到期但上次尝试刚刚失败：按重试间隔退避，避免每 5 分钟 tick 反复打慢设备
        last_try = last_attempt_map.get(sid)
        if last_try and (not last_ok or last_try > last_ok) and now - last_try < retry_delay:
            continue
        due_ids.append(sid)

    if not due_ids:
        return {'due': 0, 'success': 0, 'failed': 0, 'skipped': paused_count}

    logger.info(f"配置备份：本轮到期 {len(due_ids)} 台，网络不可达暂停 {paused_count} 台")
    semaphore = asyncio.Semaphore(max(1, settings.CONFIG_BACKUP_MAX_CONCURRENCY))
    counters = {'due': len(due_ids), 'success': 0, 'failed': 0, 'skipped': paused_count}

    async def _run_one(switch_id: int) -> None:
        async with semaphore:
            try:
                async with AsyncSessionLocal() as task_db:
                    sw = await task_db.get(Switch, switch_id)
                    if not sw:
                        counters['skipped'] += 1
                        return
                    result = await backup_switch_config(task_db, sw, 'scheduled')
            except Exception as exc:
                logger.error(f"配置备份任务异常 switch={switch_id}: {exc}")
                counters['failed'] += 1
                return
            status = result.get('status')
            if status == 'success':
                counters['success'] += 1
            elif status == 'failed':
                counters['failed'] += 1
            else:
                counters['skipped'] += 1

    await asyncio.gather(*(_run_one(sid) for sid in due_ids))
    logger.info(
        f"配置备份：完成 成功 {counters['success']} / 失败 {counters['failed']} / "
        f"跳过 {counters['skipped']}"
    )
    return counters
