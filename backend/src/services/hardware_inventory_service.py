"""IPAM 硬件资产（SN / 设备型号）采集服务。

职责：
- 解析候选 SNMP 凭据：子网绑定的 SNMP 模板 → 全局默认 community
- 按凭据顺序采集 SN / 型号 / 硬件厂商，任一凭据拿到 SN 即停止
- 硬件盘点全局设置的读写（默认 community、WMI 口令一律 Fernet 加密存储）
- 判断某个 IP 本轮是否需要采集（在线 + 还没有 SN + 已过重试窗口）

安全约定：
- 加密字段一律走 *_encrypted 键名，读出来只在构造认证对象时短暂解密
- 本模块的日志、返回值都不包含明文或密文凭据
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import decrypt_password, encrypt_password
from models.system_settings import SystemSettings
from services.settings_service import settings_service
from services.snmp_service import (
    build_ipam_snmp_profile,
    build_snmp_auth,
    snmp_service,
)
from utils.logger import logger


# system_settings 键名（迁移 038 写入）
SETTING_ENABLED = 'hardware_inventory_enabled'
SETTING_RETRY_HOURS = 'hardware_inventory_retry_hours'
SETTING_WMI_CONCURRENCY = 'hardware_inventory_wmi_concurrency'
SETTING_WMI_MAX_PER_SWEEP = 'hardware_inventory_wmi_max_per_sweep'
SETTING_DEFAULT_COMMUNITY = 'snmp_default_community_encrypted'
SETTING_WMI_DOMAIN = 'wmi_domain'
SETTING_WMI_USERNAME = 'wmi_username'
SETTING_WMI_PASSWORD = 'wmi_password_encrypted'

_HARDWARE_FIELDS = ('serial_number', 'device_model', 'hardware_vendor', 'hardware_source')


async def _read_raw_setting(db: AsyncSession, key: str, default: Any = None) -> Any:
    """
    直接读 system_settings 原始值，不经过 settings_service。

    口令类字段必须走这里：settings_service 会在 debug 日志里回显读到的值，
    密文也不该出现在日志里。
    """
    try:
        result = await db.execute(
            select(SystemSettings).where(SystemSettings.key == key)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return default
        return row.value
    except Exception as e:
        logger.error(f"Failed to read raw setting '{key}': {e}")
        return default


async def _write_raw_setting(db: AsyncSession, key: str, value: str) -> bool:
    """
    直接写 system_settings 的密文值，不经过 settings_service。

    理由：settings_service 会把写入值打 info 日志，密文同样不该入日志。
    """
    try:
        result = await db.execute(
            select(SystemSettings).where(SystemSettings.key == key)
        )
        row = result.scalar_one_or_none()
        if row is None:
            db.add(SystemSettings(
                key=key,
                value=value,
                data_type='string',
                description='',
                is_configurable=False,
                is_sensitive=True,
            ))
        else:
            row.value = value
            # 保持敏感标记，避免被通用设置页读取
            row.is_sensitive = True
            row.is_configurable = False
        await db.commit()
        return True
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to write sensitive setting '{key}': {e}")
        return False


async def is_enabled(db: AsyncSession) -> bool:
    """硬件盘点总开关，异常时按关闭处理，绝不因设置读不到就误采。"""
    value = await settings_service.get_setting(db, SETTING_ENABLED, True)
    return bool(value)


async def get_retry_hours(db: AsyncSession) -> int:
    value = await settings_service.get_setting(db, SETTING_RETRY_HOURS, 24)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 24


async def resolve_snmp_attempts(
    db: AsyncSession,
    profile: Any = None,
) -> List[Dict[str, Any]]:
    """
    解析候选 SNMP 凭据，按优先级返回（最多 2 条）。

    ① 子网绑定的 SNMP 模板（v2c/v3）
    ② 全局默认 community（设置 → 环境变量兜底），仅在与①重复时跳过

    传入的是已加载的 SNMPProfile 对象（不是 subnet），避免在异步上下文里触发懒加载。
    返回的字典仍是密文形式，解密只发生在构造认证对象时。
    """
    attempts: List[Dict[str, Any]] = []
    known_communities = set()

    if profile is not None and getattr(profile, 'enabled', True):
        config = build_ipam_snmp_profile(profile)
        if config:
            attempts.append(config)
            if config.get('snmp_version') == '2c':
                try:
                    known_communities.add(
                        decrypt_password(config.get('snmp_auth_password_encrypted') or '')
                    )
                except Exception:
                    pass

    community = None
    ciphertext = await _read_raw_setting(db, SETTING_DEFAULT_COMMUNITY, '')
    if ciphertext:
        try:
            community = decrypt_password(ciphertext)
        except Exception as e:
            logger.warning(f"Default SNMP community stored in settings cannot be decrypted: {e}")
            community = None

    if not community:
        # 环境变量只读兜底（老部署习惯）
        community = settings.SNMP_COMMUNITY or None

    if community and community not in known_communities:
        attempts.append({
            'snmp_version': '2c',
            'snmp_username': None,
            'snmp_auth_protocol': None,
            'snmp_auth_password_encrypted': encrypt_password(community),
            'snmp_priv_protocol': None,
            'snmp_priv_password_encrypted': None,
            'snmp_port': 161,
            'timeout': 5,
            'retries': 1,
        })

    return attempts


def build_auth_for_attempt(attempt: Optional[Dict[str, Any]]) -> Any:
    """把一条候选凭据解密成 pysnmp 认证对象；解不开就返回 None（不抛异常）。"""
    if not attempt:
        return None
    try:
        encrypted = attempt.get('snmp_auth_password_encrypted')
        password = decrypt_password(encrypted) if encrypted else None
        if not password:
            return None

        priv_password = None
        if attempt.get('snmp_priv_password_encrypted'):
            priv_password = decrypt_password(attempt['snmp_priv_password_encrypted'])

        return build_snmp_auth(
            username=attempt.get('snmp_username'),
            auth_protocol=attempt.get('snmp_auth_protocol'),
            auth_password=password,
            priv_protocol=attempt.get('snmp_priv_protocol'),
            priv_password=priv_password,
            snmp_version=attempt.get('snmp_version'),
        )
    except Exception as e:
        logger.debug(f"SNMP credential setup failed: {e}")
        return None


async def collect_hardware(
    ip: str,
    attempts: List[Dict[str, Any]],
    sys_descr: Optional[str] = None,
) -> Dict[str, Any]:
    """
    依次尝试候选凭据采集硬件信息。

    返回 serial_number/device_model/hardware_vendor/hardware_source（取到才算）
    与 hardware_attempted_at（本轮尝试时间，用于失败退避）。
    """
    result: Dict[str, Any] = {
        'serial_number': None,
        'device_model': None,
        'hardware_vendor': None,
        'hardware_source': None,
        'hardware_attempted_at': datetime.now(timezone.utc),
    }

    for attempt in attempts or []:
        auth_data = build_auth_for_attempt(attempt)
        if not auth_data:
            continue
        port = int(attempt.get('snmp_port') or 161)
        # 先做一次短超时 sysDescr 预检：没有 SNMP agent 的主机（多数 Windows PC）
        # 若不预检会进 ENTITY-MIB 全表 walk，单个 IP 空等近一分钟。
        probed = await snmp_service.probe_sys_descr(ip, auth_data, port=port)
        if not probed:
            continue
        try:
            hardware = await snmp_service.get_host_hardware(
                ip,
                auth_data,
                port=port,
                timeout=min(int(attempt.get('timeout') or 5), 10),
                sys_descr=sys_descr or probed,
            )
        except Exception as e:
            logger.debug(f"Hardware collection failed for {ip}: {e}")
            continue

        if not hardware:
            continue

        for field in _HARDWARE_FIELDS:
            if hardware.get(field) and not result[field]:
                result[field] = hardware[field]

        if result['serial_number']:
            break

    return result


def collect_hardware_sync(
    ip: str,
    attempts: List[Dict[str, Any]],
    sys_descr: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    同步包装，供在线程池里执行的 _enrich_single_ip 调用。

    attempts 为空直接返回 None（本轮不采集），调用方据此跳过落库。
    """
    if not attempts:
        return None
    try:
        return asyncio.run(collect_hardware(ip, attempts, sys_descr))
    except Exception as e:
        logger.debug(f"Hardware collection wrapper failed for {ip}: {e}")
        return None


def is_hardware_eligible(
    ip_addr: Any,
    retry_hours: int,
    now: Optional[datetime] = None,
    reachable: Optional[bool] = None,
) -> bool:
    """
    判断某个 IP 本轮是否要采集硬件信息。

    条件：在线、还没有 SN、且距上次尝试已超过重试窗口。
    已有 SN 的不再重复采集；开关关闭由调用方判断。
    reachable 显式传入时以调用方（本轮扫描结果）为准，因为库里的
    is_reachable 可能还是上一轮的旧值。
    """
    if reachable is None:
        reachable = getattr(ip_addr, 'is_reachable', False)
    if not reachable:
        return False
    if getattr(ip_addr, 'serial_number', None):
        return False

    attempted = getattr(ip_addr, 'hardware_attempted_at', None)
    if attempted is None:
        return True

    if attempted.tzinfo is None:
        attempted = attempted.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - attempted) >= timedelta(hours=max(1, retry_hours))


def build_hardware_attempts_map(
    ip_records: List[Any],
    attempts: List[Dict[str, Any]],
    retry_hours: int,
    reachable_ips: Optional[set] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """只为符合条件的 IP 建映射，其余 IP 不进入采集路径（省掉空等待）。"""
    if not attempts:
        return {}
    now = datetime.now(timezone.utc)
    # INET 列转字符串可能带 /32、/128 后缀，统一去掉后再比对
    reachable_set = (
        {str(item).split('/')[0] for item in reachable_ips}
        if reachable_ips is not None else None
    )
    mapping: Dict[str, List[Dict[str, Any]]] = {}
    for ip_addr in ip_records:
        ip_str = str(ip_addr.ip_address).split('/')[0]
        reachable = (ip_str in reachable_set) if reachable_set is not None else None
        if is_hardware_eligible(ip_addr, retry_hours, now, reachable):
            mapping[ip_str] = attempts
    return mapping


async def get_inventory_settings(db: AsyncSession) -> Dict[str, Any]:
    """硬件盘点设置（对外只暴露是否已配置，不回显凭据）。"""
    ciphertext = await _read_raw_setting(db, SETTING_DEFAULT_COMMUNITY, '')
    wmi_password_ciphertext = await _read_raw_setting(db, SETTING_WMI_PASSWORD, '')

    return {
        'enabled': await is_enabled(db),
        'retry_hours': await get_retry_hours(db),
        'wmi_concurrency': await _get_int(db, SETTING_WMI_CONCURRENCY, 1),
        'wmi_max_per_sweep': await _get_int(db, SETTING_WMI_MAX_PER_SWEEP, 50),
        'default_community_configured': bool(ciphertext) or bool(settings.SNMP_COMMUNITY),
        'wmi_domain': await _get_str(db, SETTING_WMI_DOMAIN, ''),
        'wmi_username': await _get_str(db, SETTING_WMI_USERNAME, ''),
        'wmi_password_configured': bool(wmi_password_ciphertext),
    }


async def update_inventory_settings(db: AsyncSession, payload: Any) -> bool:
    """
    更新硬件盘点设置。

    口令类字段只有传了非空值才覆盖（避免前端留空把已有口令清掉）。
    """
    updates = []

    if payload.enabled is not None:
        updates.append((SETTING_ENABLED, payload.enabled, 'boolean'))
    if payload.retry_hours is not None:
        updates.append((SETTING_RETRY_HOURS, payload.retry_hours, 'integer'))
    if payload.wmi_concurrency is not None:
        updates.append((SETTING_WMI_CONCURRENCY, payload.wmi_concurrency, 'integer'))
    if payload.wmi_max_per_sweep is not None:
        updates.append((SETTING_WMI_MAX_PER_SWEEP, payload.wmi_max_per_sweep, 'integer'))
    if payload.wmi_domain is not None:
        updates.append((SETTING_WMI_DOMAIN, payload.wmi_domain, 'string'))
    if payload.wmi_username is not None:
        updates.append((SETTING_WMI_USERNAME, payload.wmi_username, 'string'))

    ok = True
    for key, value, data_type in updates:
        success = await settings_service.set_setting(db, key, value, data_type)
        ok = ok and success

    # 敏感字段单独走原始写入，避免密文进入通用设置日志
    if payload.default_community:
        ok = await _write_raw_setting(
            db, SETTING_DEFAULT_COMMUNITY, encrypt_password(payload.default_community)
        ) and ok
    if payload.wmi_password:
        ok = await _write_raw_setting(
            db, SETTING_WMI_PASSWORD, encrypt_password(payload.wmi_password)
        ) and ok

    if updates or payload.default_community or payload.wmi_password:
        changed = [item[0] for item in updates]
        if payload.default_community:
            changed.append('default_community')
        if payload.wmi_password:
            changed.append('wmi_password')
        logger.info(f"Hardware inventory settings updated: {changed}")
    return ok


async def get_wmi_credentials(db: AsyncSession) -> Optional[Dict[str, str]]:
    """读取并解密 WMI 凭据；未配置时返回 None。明文只交给采集函数，不落日志。"""
    ciphertext = await _read_raw_setting(db, SETTING_WMI_PASSWORD, '')
    username = await _get_str(db, SETTING_WMI_USERNAME, '')
    if not ciphertext or not username:
        return None
    try:
        password = decrypt_password(ciphertext)
    except Exception as e:
        logger.warning(f"WMI password cannot be decrypted: {e}")
        return None
    if not password:
        return None
    return {
        'domain': await _get_str(db, SETTING_WMI_DOMAIN, ''),
        'username': username,
        'password': password,
    }


def _windows_collectors() -> List[Any]:
    """当前可用的 Windows 远程采集器，顺序即回退顺序（WMI 优先，WinRM 兜底）。"""
    from services import wmi_inventory_service, winrm_inventory_service

    collectors: List[Any] = []
    if wmi_inventory_service.is_available():
        collectors.append(wmi_inventory_service.collect_wmi)
    if winrm_inventory_service.is_available():
        collectors.append(winrm_inventory_service.collect_winrm)
    return collectors


def _merge_hardware(
    base: Optional[Dict[str, Any]],
    extra: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """合并两条通路的采集结果；hardware_source 跟随真正提供 SN 的通路。"""
    if not extra:
        return base
    if not base:
        return dict(extra)

    merged = dict(base)
    for field in ('serial_number', 'device_model', 'hardware_vendor'):
        if not merged.get(field) and extra.get(field):
            merged[field] = extra[field]
    if extra.get('serial_number') and not base.get('serial_number'):
        merged['hardware_source'] = extra.get('hardware_source') or merged.get('hardware_source')
    if extra.get('hardware_attempted_at') and not merged.get('hardware_attempted_at'):
        merged['hardware_attempted_at'] = extra['hardware_attempted_at']
    return merged


async def collect_windows_hardware(
    ip: str,
    creds: Optional[Dict[str, str]],
    collectors: Optional[List[Any]] = None,
    timeout_seconds: int = 30,
) -> Optional[Dict[str, Any]]:
    """
    依次尝试 WMI / WinRM，任一通路拿到 SN 即停止。

    collectors 显式传入可避免每台重复探测依赖；为空表示两条通路都不可用。
    """
    if not creds:
        return None
    if collectors is None:
        collectors = _windows_collectors()
    if not collectors:
        return None

    merged: Optional[Dict[str, Any]] = None
    for collect in collectors:
        try:
            hardware = await asyncio.wait_for(
                asyncio.to_thread(collect, ip, creds),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.debug(f"Windows hardware query timed out for {ip}")
            hardware = None
        merged = _merge_hardware(merged, hardware)
        if merged and merged.get('serial_number'):
            break
    return merged


async def collect_for_ips(
    db: AsyncSession,
    ip_address_ids: Optional[List[int]] = None,
    subnet_id: Optional[int] = None,
    force: bool = True,
) -> int:
    """
    手动触发硬件采集（同步执行结束后返回实际处理的 IP 数量）。

    force=True 时不看重试窗口；但已在线且有 SN 的默认仍会重采（前端显式触发）。
    采集顺序：SNMP → （os_type=windows 且未拿到 SN）WMI → WinRM。
    采集失败只记 debug，不影响其它 IP。
    """
    from models.ipam import IPAddress, IPSubnet, SNMPProfile

    if not ip_address_ids and not subnet_id:
        return 0

    query = select(IPAddress).where(IPAddress.is_reachable == True)
    if ip_address_ids:
        query = query.where(IPAddress.id.in_(ip_address_ids))
    if subnet_id:
        query = query.where(IPAddress.subnet_id == subnet_id)

    result = await db.execute(query)
    targets = result.scalars().all()
    if not targets:
        return 0

    # 同一子网只解析一次候选凭据
    subnet_ids = {ip.subnet_id for ip in targets}
    attempts_by_subnet: Dict[int, List[Dict[str, Any]]] = {}
    for current_subnet_id in subnet_ids:
        snmp_profile_id = (await db.execute(
            select(IPSubnet.snmp_profile_id).where(IPSubnet.id == current_subnet_id)
        )).scalar_one_or_none()

        profile = None
        if snmp_profile_id:
            profile = (await db.execute(
                select(SNMPProfile).where(SNMPProfile.id == snmp_profile_id)
            )).scalar_one_or_none()

        attempts_by_subnet[current_subnet_id] = await resolve_snmp_attempts(db, profile)

    # Windows 远程补采（WMI/WinRM）：SNMP 拿不到 SN 时兜底，凭据与自动采集共用
    windows_creds = await get_wmi_credentials(db)
    windows_collectors = _windows_collectors() if windows_creds else []

    queued = 0
    now = datetime.now(timezone.utc)
    for ip_addr in targets:
        attempts = attempts_by_subnet.get(ip_addr.subnet_id) or []
        ip_str = str(ip_addr.ip_address).split('/')[0]
        hardware = None
        if attempts:
            hardware = await asyncio.to_thread(collect_hardware_sync, ip_str, attempts)
        if (windows_collectors
                and getattr(ip_addr, 'os_type', None) == 'windows'
                and not (hardware and hardware.get('serial_number'))):
            windows_hardware = await collect_windows_hardware(
                ip_str, windows_creds, windows_collectors
            )
            hardware = _merge_hardware(hardware, windows_hardware)
        if not hardware:
            continue

        for field in _HARDWARE_FIELDS:
            if hardware.get(field):
                setattr(ip_addr, field, hardware[field])
        if hardware.get('serial_number'):
            ip_addr.hardware_collected_at = now
        ip_addr.hardware_attempted_at = hardware.get('hardware_attempted_at') or now
        queued += 1

    if queued:
        await db.commit()
    return queued


async def run_wmi_sweep(db: AsyncSession) -> int:
    """
    Windows 硬件补采一轮（WMI 优先、WinRM 兜底，与手动采集同一条路径）。

    只处理：在线 + os_type='windows' + 还没有 SN + 已过重试窗口的 IP。
    串行度默认 1（避免账号锁定），单轮上限由 hardware_inventory_wmi_max_per_sweep 控制。
    失败也记录 hardware_attempted_at，靠重试窗口退避，避免每轮重试。
    """
    from models.ipam import IPAddress

    if not await is_enabled(db):
        return 0

    creds = await get_wmi_credentials(db)
    if not creds:
        logger.debug("WMI sweep skipped: credentials not configured")
        return 0

    collectors = _windows_collectors()
    if not collectors:
        logger.warning("Windows sweep skipped: neither impacket nor pywinrm is installed")
        return 0

    retry_hours = await get_retry_hours(db)
    max_per_sweep = max(1, await _get_int(db, SETTING_WMI_MAX_PER_SWEEP, 50))
    concurrency = max(1, await _get_int(db, SETTING_WMI_CONCURRENCY, 1))

    result = await db.execute(
        select(IPAddress).where(
            IPAddress.is_reachable == True,
            IPAddress.os_type == 'windows',
            IPAddress.serial_number.is_(None),
        ).order_by(IPAddress.hardware_attempted_at.asc().nullsfirst())
    )
    candidates = [
        ip for ip in result.scalars().all()
        if is_hardware_eligible(ip, retry_hours, reachable=True)
    ]
    if not candidates:
        return 0
    if len(candidates) > max_per_sweep:
        logger.info(f"WMI sweep limited to {max_per_sweep} of {len(candidates)} candidates")
        candidates = candidates[:max_per_sweep]

    semaphore = asyncio.Semaphore(concurrency)
    now = datetime.now(timezone.utc)
    timeout_seconds = 30

    async def _one(ip_addr: Any) -> bool:
        ip_str = str(ip_addr.ip_address).split('/')[0]
        async with semaphore:
            hardware = await collect_windows_hardware(
                ip_str, creds, collectors, timeout_seconds=timeout_seconds
            )
        ip_addr.hardware_attempted_at = now
        if not hardware:
            return False
        for field in _HARDWARE_FIELDS:
            if hardware.get(field):
                setattr(ip_addr, field, hardware[field])
        if hardware.get('serial_number'):
            ip_addr.hardware_collected_at = now
            return True
        return False

    results = await asyncio.gather(*[_one(ip) for ip in candidates], return_exceptions=True)
    collected = sum(1 for item in results if item is True)
    failures = sum(1 for item in results if isinstance(item, Exception))
    if failures:
        logger.debug(f"WMI sweep had {failures} unexpected error(s)")

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"WMI sweep commit failed: {e}")
        return 0

    logger.info(f"WMI sweep finished: {collected}/{len(candidates)} IPs got serial number")
    return collected


async def _get_int(db: AsyncSession, key: str, default: int) -> int:
    value = await settings_service.get_setting(db, key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def _get_str(db: AsyncSession, key: str, default: str) -> str:
    value = await settings_service.get_setting(db, key, default)
    return '' if value is None else str(value)
