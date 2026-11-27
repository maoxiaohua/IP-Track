"""
自动网络拓扑：采集编排 + 链路推导。

设计原则（精准优先）：
- 只有 LLDP / CDP 邻居事实可以建链。STP / 桥 MAC / MAC 表只在身份解析里做
  辅助判断，绝不单独产生链路。
- 采集失败 / 设备不支持 / 无邻居 三种状态严格区分：前两种保留旧事实（不删），
  **只有完整的 walk 才允许清理本轮未出现的事实**，避免一次超时把拓扑清空。
"""

import asyncio
import hashlib
import ipaddress
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.alarm import AlarmSeverity, AlarmSourceType
from models.mac_table import MACTable
from models.switch import Switch
from models.topology import (
    LldpNeighbor,
    SwitchInterface,
    TopologyLink,
    TopologyUnknownNode,
)
from services.network_data_collector import network_data_collector
from services.snmp_service import (
    build_switch_snmp_config,
    snmp_service,
    switch_has_snmp_credentials,
)
from services.cli_service import cli_service
from services.alarm_service import alarm_service
from services.topology_utils import normalize_lag_key, normalize_mac
from services.lldp_signals import parse_capabilities
from services.device_classifier import classify_unknown
from services.ipam_device_hints import lookup_ipam_profiles
from services.port_analysis_service import port_analysis_service
from utils.logger import logger


# 单个数据源的超时。超时按「采集失败」处理（保留旧事实），不会被当成空结果。
SNMP_SOURCE_TIMEOUT = 180.0
CLI_SOURCE_TIMEOUT = 150.0

_MIN_RESOLVE_SCORE = 70
_EVIDENCE_PROTOCOLS = ('lldp', 'cdp')

# 厂商 -> sysDesc / sysName 里常见的标识片段。仅用于「+5 置信度」，不参与建链。
_VENDOR_HINTS: Dict[str, Tuple[str, ...]] = {
    'cisco': ('cisco', 'ios', 'nx-os', 'nxos', 'nexus'),
    'dell': ('dell', 'force10', 'os10', 'networking'),
    'alcatel': ('nokia', 'alcatel', 'sr os', 'sros', 'sr linux', 'srl'),
    'juniper': ('juniper', 'junos'),
    'arista': ('arista', 'eos'),
    'hpe': ('hpe', 'aruba', 'procurve', 'hp '),
    'huawei': ('huawei', 'vrp', 'cloudengine'),
    'h3c': ('h3c', 'comware', 'hp comware'),
}

_MISSING = object()


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.utcnow()


def _trunc(value: Any, length: Optional[int] = None) -> Optional[str]:
    if value is None:
        return None
    # 设备输出可能夹带 NUL 等控制字符，PG 的 text 列不接受 \x00；
    # 写入失败会让整个采集事务回滚，连失败告警一起丢掉。
    text = str(value).replace('\x00', '').strip()
    if not text:
        return None
    return text if length is None else text[:length]


def _normalize_addr(value: Any) -> Optional[str]:
    """规范化管理地址；loopback / link-local / 组播不参与身份判定。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith('[') and text.endswith(']'):
        text = text[1:-1]
    if '%' in text:
        text = text.split('%', 1)[0]
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    if addr.is_loopback or addr.is_link_local or addr.is_unspecified or addr.is_multicast:
        return None
    return str(addr)


def _switch_ip(switch: Switch) -> Optional[str]:
    return _normalize_addr(switch.ip_address)


def _is_mac_like(value: Optional[str]) -> bool:
    normalized = normalize_mac(value)
    return bool(normalized and re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', normalized))


def _compact_port(value: Any) -> str:
    return re.sub(r'[\s\-_]+', '', str(value or '').strip().lower())


def _vendor_hint(*texts: Optional[str]) -> Optional[str]:
    blob = ' '.join(str(t).lower() for t in texts if t)
    if not blob:
        return None
    for vendor, hints in _VENDOR_HINTS.items():
        if any(hint in blob for hint in hints):
            return vendor
    return None


def _vendor_matches(vendor: Optional[str], *texts: Optional[str]) -> bool:
    if not vendor:
        return False
    hints = _VENDOR_HINTS.get(str(vendor).lower())
    if not hints:
        return False
    blob = ' '.join(str(t).lower() for t in texts if t)
    return any(hint in blob for hint in hints)


# capability 词表与解析已抽到 services/lldp_signals.py，拓扑与端口联动共用。
_parse_capabilities = parse_capabilities


def _device_class(capabilities: Set[str], *texts: Optional[str]) -> str:
    """未纳管节点的设备类别（兼容旧签名，判定逻辑统一在 device_classifier）。"""
    cleaned = [str(t) for t in texts if t]
    return classify_unknown(
        capabilities=capabilities,
        sys_name=cleaned[0] if cleaned else None,
        sys_desc=' '.join(cleaned[1:]) or None,
    ).device_class


def _build_cli_config(switch: Switch) -> Dict:
    return {
        'username': switch.username,
        'password_encrypted': switch.password_encrypted,
        'vendor': switch.vendor,
        'model': switch.model,
        'name': switch.name,
        'cli_transport': switch.cli_transport,
        'ssh_port': switch.ssh_port,
        'connection_timeout': switch.connection_timeout,
        'enable_password_encrypted': switch.enable_password_encrypted,
        # 慢链路/并发登录时放宽 Netmiko 握手，避免误报认证超时
        'handshake_timeout': settings.CLI_HANDSHAKE_TIMEOUT_SECONDS,
    }


def _has_cli_credentials(switch: Switch) -> bool:
    return bool(switch.cli_enabled and switch.username and switch.password_encrypted)


def _link_key(*endpoint_keys: str) -> str:
    raw = '|'.join(sorted(k for k in endpoint_keys if k))
    if len(raw) > 480:
        return 'h:' + hashlib.sha1(raw.encode('utf-8')).hexdigest()
    return raw


# ---------------------------------------------------------------------------
# 采集：单台交换机
# ---------------------------------------------------------------------------

async def _run_dataset(
    switch: Switch,
    data_type: str,
    snmp_fn,
    cli_fn,
    snmp_config: Optional[Dict],
    cli_config: Optional[Dict],
    oid_overrides: Optional[Dict[str, str]],
    templates: Optional[List[Dict]],
    supported: Optional[bool] = None,
) -> Dict:
    """
    采集一类事实。SNMP 优先，失败或设备不支持时回退 CLI。
    返回 {'status', 'entries', 'method', 'message'}。

    supported=False 表示模板已明确该设备类型不适用此协议（例如 Dell / Nokia
    没有 CDP）：直接判 unsupported，不再探测 SNMP，避免把「协议不适用」误记成
    采集失败而拖累整台设备的采集状态。
    """
    if supported is False:
        return {
            'status': 'unsupported',
            'entries': [],
            'method': None,
            'message': f'{data_type} is not supported for this device type',
        }

    attempts: List[Tuple[str, Dict]] = []
    switch_ip = str(switch.ip_address)
    snmp_empty_ok: Optional[Dict] = None

    if snmp_config:
        try:
            result = await asyncio.wait_for(
                snmp_fn(switch_ip, snmp_config, oid_overrides), timeout=SNMP_SOURCE_TIMEOUT
            )
        except Exception as exc:  # 超时 / 未预期异常
            result = {'status': 'error', 'entries': [], 'message': f'SNMP {data_type}: {exc}'}
        attempts.append(('snmp', result or {}))
        if result and result.get('status') == 'ok':
            if (result.get('entries') or []) or not cli_config:
                return {
                    'status': 'ok',
                    'entries': result.get('entries') or [],
                    'method': 'snmp',
                    'message': None,
                }
            # SNMP 报「支持但 0 条」并不总是真的：实测 Cisco C3650 的 SNMP 代理
            # remote 表为空，CLI 却有邻居。0 条不能短路 CLI，否则会漏采邻居。
            snmp_empty_ok = result

    if cli_config:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(cli_fn, switch_ip, cli_config, templates),
                timeout=CLI_SOURCE_TIMEOUT,
            )
        except Exception as exc:
            result = {'status': 'error', 'entries': [], 'message': f'CLI {data_type}: {exc}'}
        attempts.append(('cli', result or {}))
        if result and result.get('status') == 'ok':
            return {
                'status': 'ok',
                'entries': result.get('entries') or [],
                'method': 'cli',
                'message': None,
            }
        # CLI 交叉校验失败不推翻 SNMP 的「支持但无邻居」结论，保持成功、保留旧事实。
        if snmp_empty_ok is not None:
            return {
                'status': 'ok',
                'entries': [],
                'method': 'snmp',
                'message': None,
            }

    if not attempts:
        return {
            'status': 'skipped',
            'entries': [],
            'method': None,
            'message': 'no SNMP or CLI credentials available',
        }

    statuses = [r.get('status') for _, r in attempts]
    if all(s in ('unsupported', 'skipped') for s in statuses):
        status = 'unsupported'
    else:
        # 只要有一路是 error，就无法确认该数据源的真实状态 —— 按失败处理，
        # 保留旧事实，绝不当作「没有邻居」清空。
        status = 'error'

    message_parts = []
    for method, res in attempts:
        text = res.get('message') or res.get('status') or 'unknown'
        message_parts.append(f'{method}: {text}')
    return {
        'status': status,
        'entries': [],
        'method': None,
        'message': '; '.join(message_parts)[:1000],
    }


async def _gather_facts(
    switch: Switch,
    templates: Optional[List[Dict]],
    all_oid_overrides: Optional[List[Dict]],
) -> Dict[str, Dict]:
    """网络采集阶段：不写数据库，便于并发调用。"""
    has_snmp = switch_has_snmp_credentials(switch)
    has_cli = _has_cli_credentials(switch)

    snmp_config = build_switch_snmp_config(switch) if has_snmp else None
    cli_config = _build_cli_config(switch) if has_cli else None

    oid_overrides = None
    if snmp_config and all_oid_overrides:
        oid_overrides = snmp_service.resolve_oid_overrides(
            all_oid_overrides, switch.vendor or '', switch.model or ''
        )
        if not oid_overrides:
            oid_overrides = None

    # 模板已明确不适用的协议（如非 Cisco 设备的 CDP）先判 unsupported，
    # 否则 SNMP 探测报错 + CLI「未启用」会被 _run_dataset 判成 error。
    template_config = _build_cli_config(switch)
    supported = {
        data_type: cli_service.topology_dataset_supported(template_config, templates, data_type)
        for data_type in ('interfaces', 'lldp', 'cdp')
    }

    facts = {
        'interfaces': await _run_dataset(
            switch, 'interfaces', snmp_service.collect_interfaces, cli_service.collect_interfaces_cli,
            snmp_config, cli_config, oid_overrides, templates, supported['interfaces'],
        ),
        'lldp': await _run_dataset(
            switch, 'lldp', snmp_service.collect_lldp_neighbors, cli_service.collect_lldp_neighbors_cli,
            snmp_config, cli_config, oid_overrides, templates, supported['lldp'],
        ),
        'cdp': await _run_dataset(
            switch, 'cdp', snmp_service.collect_cdp_neighbors, cli_service.collect_cdp_neighbors_cli,
            snmp_config, cli_config, oid_overrides, templates, supported['cdp'],
        ),
    }

    identity = None
    if snmp_config:
        try:
            identity = await asyncio.wait_for(
                snmp_service.get_topology_identity(str(switch.ip_address), snmp_config),
                timeout=SNMP_SOURCE_TIMEOUT,
            )
        except Exception as exc:
            logger.debug(f"Topology identity fetch failed for {switch.name}: {exc}")
            identity = None

    facts['identity'] = identity
    return facts


def _aggregate_status(facts: Dict[str, Dict]) -> str:
    evidence = [facts.get(p, {}).get('status') for p in _EVIDENCE_PROTOCOLS]
    if any(s == 'ok' for s in evidence) and all(s in ('ok', 'unsupported', 'skipped') for s in evidence):
        return 'success'
    if any(s == 'ok' for s in evidence):
        return 'partial'
    if all(s in ('unsupported', 'skipped') for s in evidence):
        return 'unsupported'
    return 'failed'


def _collection_method(facts: Dict[str, Dict]) -> Optional[str]:
    methods = {facts[key].get('method') for key in ('interfaces', 'lldp', 'cdp')}
    methods.discard(None)
    if not methods:
        return None
    return '+'.join(sorted(methods))[:20]


# 必须与 collection_worker.TOPOLOGY_ALARM_PREFIX 一致：
# 队列路径按 title_prefix 自动恢复告警，前缀不同会导致告警永远无法消除。
_TOPOLOGY_ALARM_PREFIX = "Topology collection "


async def _sync_topology_alarm(
    db: AsyncSession,
    switch: Switch,
    status: str,
    message: Optional[str],
    datasets: Dict[str, Optional[str]],
) -> None:
    """把批量采集结果同步到告警页，口径与 collection_worker 的队列路径一致。"""
    if status == 'failed':
        text = (message or 'topology collection failed')[:2000]
        lower = text.lower()
        # 判定顺序必须与 collection_worker 一致：认证失败信息里也含 "connection failed"，
        # 先判 connect 会把 ERROR 误降级成 WARNING，同一设备出现 error+warning 两条告警。
        severity = AlarmSeverity.ERROR
        if 'auth' in lower or 'password' in lower:
            severity = AlarmSeverity.ERROR
        elif 'connect' in lower or 'unreachable' in lower:
            severity = AlarmSeverity.WARNING
        alarm = await alarm_service.create_alarm(
            db=db,
            severity=severity,
            title=f"{_TOPOLOGY_ALARM_PREFIX}failed: {switch.name}"[:200],
            message=text,
            source_type=AlarmSourceType.SWITCH,
            source_id=switch.id,
            source_name=switch.name,
            details={
                'status': status,
                'datasets': datasets,
                'switch_ip': str(switch.ip_address) if switch.ip_address else None,
                'vendor': switch.vendor,
                'model': switch.model,
            },
        )
        # severity 跳变会产生新 fingerprint，旧告警不会自动消失，这里收掉旧的。
        await alarm_service.auto_resolve_alarms(
            db=db,
            source_type=AlarmSourceType.SWITCH,
            source_id=switch.id,
            title_prefix=_TOPOLOGY_ALARM_PREFIX,
            exclude_id=alarm.id,
        )
    elif status in ('success', 'partial', 'unsupported'):
        # partial/unsupported 不阻断采集（设备不支持 LLDP 属正常），按「已恢复」处理。
        await alarm_service.auto_resolve_alarms(
            db=db,
            source_type=AlarmSourceType.SWITCH,
            source_id=switch.id,
            title_prefix=_TOPOLOGY_ALARM_PREFIX,
        )


async def _upsert_interfaces(
    db: AsyncSession, switch_id: int, entries: Iterable[Dict], complete: bool, now: datetime
) -> int:
    from services.topology_utils import synthetic_if_index

    seen: Dict[int, Dict] = {}
    for entry in entries:
        if_name = _trunc(entry.get('if_name'), 128)
        if_index = entry.get('if_index')
        if if_index is None:
            if not if_name:
                continue
            if_index = synthetic_if_index(if_name)
        seen[int(if_index)] = entry

    existing = {}
    if seen or complete:
        rows = (await db.execute(
            select(SwitchInterface).where(SwitchInterface.switch_id == switch_id)
        )).scalars().all()
        existing = {int(row.if_index): row for row in rows}

    for if_index, entry in seen.items():
        row = existing.get(if_index)
        if row is None:
            row = SwitchInterface(
                switch_id=switch_id,
                if_index=if_index,
                first_seen=now,
                last_seen=now,
                collected_at=now,
            )
            db.add(row)
            existing[if_index] = row
        row.if_name = _trunc(entry.get('if_name'), 128)
        row.if_descr = _trunc(entry.get('if_descr'), 255)
        row.if_alias = _trunc(entry.get('if_alias'), 255)
        row.if_type = entry.get('if_type')
        row.admin_status = _trunc(entry.get('admin_status'), 16)
        row.oper_status = _trunc(entry.get('oper_status'), 16)
        row.speed_mbps = entry.get('speed_mbps')
        row.phys_address = _trunc(entry.get('phys_address'), 32)
        row.lag_key = _trunc(entry.get('lag_key'), 128) or normalize_lag_key(row.if_name)
        # ifLastChange 只有 SNMP 能采到；CLI 回退那轮 entry 里没有这两个键，
        # 此时保留库里旧值，避免一次 CLI 采集就把闲置时长清空。
        if entry.get('last_change_ticks') is not None:
            row.last_change_ticks = entry.get('last_change_ticks')
            row.last_change_at = entry.get('last_change_at')
        row.last_seen = now
        row.collected_at = now

    if complete:
        for if_index, row in existing.items():
            if if_index not in seen:
                await db.delete(row)

    return len(seen)


_NEGOTIABLE_FIELDS = (
    'local_port_id', 'local_port_desc',
    'remote_chassis_id', 'remote_chassis_id_subtype',
    'remote_port_id', 'remote_port_id_subtype', 'remote_port_desc',
    'remote_sys_name', 'remote_sys_desc',
    'remote_mgmt_addr', 'remote_mgmt_addr_type',
    'capability',
)
_FIELD_LIMITS = {
    'local_port_id': 255, 'local_port_desc': 255,
    'remote_chassis_id': 255, 'remote_chassis_id_subtype': 32,
    'remote_port_id': 255, 'remote_port_id_subtype': 32, 'remote_port_desc': 255,
    'remote_sys_name': 255, 'remote_sys_desc': None,
    'remote_mgmt_addr': 64, 'remote_mgmt_addr_type': 16,
    'capability': 255,
}


async def _upsert_neighbors(
    db: AsyncSession, switch_id: int, protocol: str, entries: Iterable[Dict],
    complete: bool, now: datetime
) -> int:
    """按业务键合并。唯一约束包含可空列，PG 对 NULL 不去重，所以必须在服务层合并。"""
    batch: Dict[Tuple, Dict] = {}
    for entry in entries:
        if not entry.get('remote_sys_name') and not entry.get('remote_chassis_id'):
            continue
        key = (
            entry.get('local_if_index'),
            _trunc(entry.get('remote_chassis_id'), 255),
            _trunc(entry.get('remote_port_id'), 255),
        )
        batch[key] = entry

    rows = (await db.execute(
        select(LldpNeighbor).where(
            LldpNeighbor.switch_id == switch_id,
            LldpNeighbor.protocol == protocol,
        )
    )).scalars().all()
    existing: Dict[Tuple, LldpNeighbor] = {
        (row.local_if_index, row.remote_chassis_id, row.remote_port_id): row for row in rows
    }

    for key, entry in batch.items():
        row = existing.get(key)
        if row is None:
            row = LldpNeighbor(
                switch_id=switch_id,
                protocol=protocol,
                local_if_index=entry.get('local_if_index'),
                remote_chassis_id=_trunc(entry.get('remote_chassis_id'), 255),
                remote_port_id=_trunc(entry.get('remote_port_id'), 255),
                last_seen=now,
                collected_at=now,
            )
            db.add(row)
            existing[key] = row
        for field in _NEGOTIABLE_FIELDS:
            if field in ('remote_chassis_id', 'remote_port_id'):
                continue
            limit = _FIELD_LIMITS.get(field)
            value = entry.get(field)
            setattr(row, field, _trunc(value, limit))
        if entry.get('ttl') is not None:
            row.ttl = entry.get('ttl')
        row.local_if_index = entry.get('local_if_index')
        row.last_seen = now
        row.collected_at = now

    if complete:
        for key, row in existing.items():
            if key not in batch:
                await db.delete(row)

    return len(batch)


async def _persist_facts(db: AsyncSession, switch: Switch, facts: Dict[str, Dict], now: datetime) -> Dict[str, int]:
    counts = {'interfaces': 0, 'lldp': 0, 'cdp': 0}

    interfaces = facts.get('interfaces') or {}
    if interfaces.get('status') == 'ok':
        counts['interfaces'] = await _upsert_interfaces(
            db, switch.id, interfaces.get('entries') or [], complete=True, now=now
        )

    for protocol in _EVIDENCE_PROTOCOLS:
        result = facts.get(protocol) or {}
        if result.get('status') == 'ok':
            counts[protocol] = await _upsert_neighbors(
                db, switch.id, protocol, result.get('entries') or [], complete=True, now=now
            )

    return counts


async def collect_switch_topology(
    db: AsyncSession,
    switch: Switch,
    templates: Optional[List[Dict]] = None,
    all_oid_overrides: Optional[List[Dict]] = None,
    now: Optional[datetime] = None,
) -> Dict:
    """采集并入库一台交换机的拓扑事实（不 commit，由调用方决定事务边界）。"""
    now = now or _now()
    if templates is None:
        templates = await network_data_collector._load_command_templates(db)
    if all_oid_overrides is None:
        all_oid_overrides = await network_data_collector._load_oid_overrides(db)

    facts = await _gather_facts(switch, templates, all_oid_overrides)
    counts = await _persist_facts(db, switch, facts, now)

    status = _aggregate_status(facts)
    method = _collection_method(facts)

    switch.last_topology_collection_at = now
    switch.topology_collection_method = method
    switch.last_topology_collection_status = status
    if status in ('success', 'partial'):
        switch.last_topology_success_at = now

    if any(facts.get(p, {}).get('status') == 'ok' for p in _EVIDENCE_PROTOCOLS):
        switch.last_topology_neighbors_count = counts['lldp'] + counts['cdp']

    identity = facts.get('identity') or {}
    if identity.get('status') == 'ok':
        if identity.get('sys_name'):
            switch.sys_name = _trunc(identity.get('sys_name'), 255)
        if identity.get('chassis_id'):
            switch.chassis_id = _trunc(identity.get('chassis_id'), 255)
        if identity.get('bridge_mac'):
            switch.bridge_mac = _trunc(identity.get('bridge_mac'), 32)

    message_parts = []
    for key in ('interfaces', 'lldp', 'cdp'):
        result = facts.get(key) or {}
        text = f"{key}: {result.get('status')}"
        if result.get('message'):
            text += f" ({result.get('message')})"
        message_parts.append(text)
    switch.last_topology_collection_message = _trunc('; '.join(message_parts), 2000)

    await db.flush()

    return {
        'switch_id': switch.id,
        'name': switch.name,
        'status': status,
        'method': method,
        'counts': counts,
        'datasets': {k: facts[k].get('status') for k in ('interfaces', 'lldp', 'cdp')},
    }


async def collect_switches_topology(
    db: AsyncSession,
    switches: Optional[Iterable[Switch]] = None,
    concurrency: Optional[int] = None,
) -> List[Dict]:
    """
    批量采集：网络阶段并发，数据库阶段串行。

    AsyncSession 不能并发复用，所以 gather 只拿数据，入库统一在收集完成后进行。
    """
    if switches is None:
        switches = (await db.execute(
            select(Switch).where(
                Switch.enabled == True,  # noqa: E712
                Switch.auto_collect_topology == True,  # noqa: E712
            )
        )).scalars().all()
    switch_list = list(switches)
    if not switch_list:
        return []

    templates = await network_data_collector._load_command_templates(db)
    all_oid_overrides = await network_data_collector._load_oid_overrides(db)

    limit = concurrency or int(getattr(settings, 'TOPOLOGY_MAX_COLLECT_CONCURRENCY', 5) or 5)
    semaphore = asyncio.Semaphore(max(1, limit))
    now = _now()

    async def gather_one(item: Switch):
        async with semaphore:
            try:
                return item, await _gather_facts(item, templates, all_oid_overrides)
            except Exception as exc:
                logger.error(f"Topology facts collection failed for {item.name}: {exc}")
                return item, {
                    'interfaces': {'status': 'error', 'entries': [], 'method': None, 'message': str(exc)},
                    'lldp': {'status': 'error', 'entries': [], 'method': None, 'message': str(exc)},
                    'cdp': {'status': 'error', 'entries': [], 'method': None, 'message': str(exc)},
                    'identity': None,
                }

    gathered = await asyncio.gather(*(gather_one(item) for item in switch_list))

    summaries = []
    for item, facts in gathered:
        counts = await _persist_facts(db, item, facts, now)
        status = _aggregate_status(facts)
        method = _collection_method(facts)
        item.last_topology_collection_at = now
        item.topology_collection_method = method
        item.last_topology_collection_status = status
        if status in ('success', 'partial'):
            item.last_topology_success_at = now
        if any(facts.get(p, {}).get('status') == 'ok' for p in _EVIDENCE_PROTOCOLS):
            item.last_topology_neighbors_count = counts['lldp'] + counts['cdp']
        identity = facts.get('identity') or {}
        if identity.get('status') == 'ok':
            if identity.get('sys_name'):
                item.sys_name = _trunc(identity.get('sys_name'), 255)
            if identity.get('chassis_id'):
                item.chassis_id = _trunc(identity.get('chassis_id'), 255)
            if identity.get('bridge_mac'):
                item.bridge_mac = _trunc(identity.get('bridge_mac'), 32)
        message_parts = []
        for key in ('interfaces', 'lldp', 'cdp'):
            result = facts.get(key) or {}
            text = f"{key}: {result.get('status')}"
            if result.get('message'):
                text += f" ({result.get('message')})"
            message_parts.append(text)
        item.last_topology_collection_message = _trunc('; '.join(message_parts), 2000)
        datasets = {k: facts[k].get('status') for k in ('interfaces', 'lldp', 'cdp')}
        # 定时批量采集原来只写交换机字段、不进告警页，失败原因用户看不到。
        await _sync_topology_alarm(
            db, item, status, item.last_topology_collection_message, datasets
        )
        summaries.append({
            'switch_id': item.id,
            'name': item.name,
            'status': status,
            'method': method,
            'counts': counts,
            'datasets': datasets,
        })

    await db.flush()
    return summaries


# ---------------------------------------------------------------------------
# 推导：身份索引 / 配对 / 冲突 / LAG / stale / 未知节点
# ---------------------------------------------------------------------------

class _Endpoints:
    """把一台交换机的接口表整理成「端口名 -> ifIndex」的查询结构。"""

    def __init__(self, switches: List[Switch], interfaces: List[SwitchInterface]):
        self.switches = {s.id: s for s in switches}
        self.by_index: Dict[Tuple[int, int], SwitchInterface] = {}
        self.by_name: Dict[Tuple[int, str], int] = {}
        self.by_compact: Dict[Tuple[int, str], int] = {}
        for row in interfaces:
            self.by_index[(row.switch_id, int(row.if_index))] = row
            if row.if_name:
                self.by_name.setdefault((row.switch_id, row.if_name.strip().lower()), int(row.if_index))
                self.by_compact.setdefault((row.switch_id, _compact_port(row.if_name)), int(row.if_index))

    def lookup(self, switch_id: int, port_name: Optional[str]) -> Optional[int]:
        if not port_name:
            return None
        key = str(port_name).strip().lower()
        found = self.by_name.get((switch_id, key))
        if found is not None:
            return found
        return self.by_compact.get((switch_id, _compact_port(port_name)))

    def resolve(self, switch_id: int, if_index: Optional[int], port_name: Optional[str]):
        """返回 (side_key, resolved_if_index, interface_row)。"""
        resolved = if_index
        if resolved is None and port_name:
            resolved = self.lookup(switch_id, port_name)
        if resolved is not None:
            return f'i{resolved}', resolved, self.by_index.get((switch_id, resolved))
        if port_name:
            return 'n' + _compact_port(port_name), None, None
        return None, None, None


def _build_identity_index(switches: List[Switch]) -> Tuple[Dict[str, int], Dict[str, int]]:
    """返回 (地址索引, 名称/序列号索引)。重复键标记为 None = 有歧义，不参与解析。"""
    ip_index: Dict[str, Any] = {}
    name_index: Dict[str, Any] = {}

    def add(index: Dict[str, Any], key: Optional[str], switch_id: int) -> None:
        if not key:
            return
        current = index.get(key, _MISSING)
        if current is _MISSING:
            index[key] = switch_id
        elif current != switch_id:
            index[key] = None

    for switch in switches:
        add(ip_index, _switch_ip(switch), switch.id)
        # switches.name 有唯一约束；sys_name 来自设备，两者都作为名称线索。
        add(name_index, (switch.sys_name or '').strip().lower() or None, switch.id)
        add(name_index, (switch.name or '').strip().lower() or None, switch.id)
        for identity in (switch.chassis_id, switch.bridge_mac):
            if not identity:
                continue
            if _is_mac_like(identity):
                add(name_index, normalize_mac(identity), switch.id)
            else:
                add(name_index, str(identity).strip().lower(), switch.id)
    return ip_index, name_index


def _resolve_remote(
    switches_by_id: Dict[int, Switch],
    src_id: int,
    fact: LldpNeighbor,
    endpoints: _Endpoints,
    ip_index: Dict[str, Any],
    name_index: Dict[str, Any],
) -> Tuple[Optional[int], int, Optional[str]]:
    """
    给一条邻居事实解析对端交换机，返回 (switch_id, score, 说明)。
    switch_id 为 None 表示未解析（无证据或有歧义）。
    """
    scores: Dict[int, int] = {}

    def bump(switch_id: Optional[int], score: int) -> None:
        if switch_id is None or switch_id == src_id:
            return
        if score > scores.get(switch_id, -1):
            scores[switch_id] = score

    address = _normalize_addr(fact.remote_mgmt_addr)
    if address:
        bump(ip_index.get(address), 100)

    chassis = fact.remote_chassis_id
    if chassis:
        if _is_mac_like(chassis):
            bump(name_index.get(normalize_mac(chassis)), 95)
        else:
            bump(name_index.get(str(chassis).strip().lower()), 95)

    sys_name = (fact.remote_sys_name or '').strip().lower()
    if sys_name:
        bump(name_index.get(sys_name), 70)

    if not scores:
        return None, 0, 'no matching managed switch (mgmt IP / chassis / sysName)'

    # 只做加分，不改变「必须已有名字/地址证据」的前提。
    for switch_id in list(scores):
        target = switches_by_id.get(switch_id)
        if target is None:
            continue
        if _vendor_matches(target.vendor, fact.remote_sys_desc, fact.remote_sys_name):
            scores[switch_id] += 5
        if fact.remote_port_desc and endpoints.lookup(switch_id, fact.remote_port_desc) is not None:
            scores[switch_id] += 5

    best = max(scores.values())
    winners = [sid for sid, score in scores.items() if score == best]

    if best < _MIN_RESOLVE_SCORE:
        return None, best, 'identity evidence too weak to merge automatically'
    if len(winners) > 1:
        names = ', '.join(sorted(str(switches_by_id[sid].name) for sid in winners if sid in switches_by_id))
        return None, best, f'ambiguous target, candidates: {names}'
    return winners[0], best, None


def _is_self_fact(
    src: Switch,
    fact: LldpNeighbor,
    ip_index: Dict[str, Any],
    name_index: Dict[str, Any],
) -> bool:
    """
    判断一条邻居事实是否指向本机。

    `_resolve_remote` 会主动排除自身，所以不能再靠 `target_id == src.id` 判自环，
    必须在解析前用身份索引单独比对。只认「唯一映射到本机」的键：
    两台同名交换机共享 sysName 时索引为 None，不会被误判成自环而丢掉真实链路。
    """
    address = _normalize_addr(fact.remote_mgmt_addr)
    if address and ip_index.get(address) == src.id:
        return True

    chassis = fact.remote_chassis_id
    if chassis:
        key = normalize_mac(chassis) if _is_mac_like(chassis) else str(chassis).strip().lower()
        if key and name_index.get(key) == src.id:
            return True

    sys_name = (fact.remote_sys_name or '').strip().lower()
    if sys_name and name_index.get(sys_name) == src.id:
        return True
    return False


def _unknown_node_key(fact: LldpNeighbor) -> Optional[str]:
    address = _normalize_addr(fact.remote_mgmt_addr)
    if address:
        return f'ip:{address}'
    chassis = fact.remote_chassis_id
    if chassis:
        if _is_mac_like(chassis):
            return f'mac:{normalize_mac(chassis)}'
        return f'chassis:{str(chassis).strip().lower()[:200]}'
    sys_name = (fact.remote_sys_name or '').strip().lower()
    if sys_name:
        return f'name:{sys_name[:200]}'
    return None


def _switch_endpoint(
    switch: Switch,
    endpoints: _Endpoints,
    side_key: str,
    resolved_index: Optional[int],
    port_name: Optional[str],
    iface: Optional[SwitchInterface],
) -> Dict:
    display = (iface.if_name if iface and iface.if_name else port_name)
    if not display and resolved_index is not None:
        display = f'ifIndex {resolved_index}'
    lag = None
    if iface is not None:
        lag = iface.lag_key or normalize_lag_key(iface.if_name)
    else:
        lag = normalize_lag_key(port_name)
    return {
        'kind': 'switch',
        'key': f'sw:{switch.id}:{side_key}',
        'switch_id': switch.id,
        'if_index': resolved_index,
        'port_name': _trunc(display, 128),
        'sys_name': _trunc(switch.sys_name or switch.name, 255),
        'mgmt_ip': _trunc(_switch_ip(switch), 64),
        'chassis_id': switch.chassis_id,
        'node_key': None,
        'lag_key': lag,
    }


async def _load_port_mac_stats(
    db: AsyncSession,
    switch_ids: Iterable[int],
) -> Dict[Tuple[int, str], Dict]:
    """按 (switch_id, 端口键) 汇总 MAC 学习数，作为 unknown 节点的结构性证据。

    一次查询、Python 侧归键；任何失败都返回空表（只降级为 unknown，不影响派生）。
    """
    ids = {int(sid) for sid in switch_ids if sid is not None}
    if not ids:
        return {}
    rows = await db.execute(
        select(MACTable.switch_id, MACTable.port_name, MACTable.mac_address)
        .where(MACTable.switch_id.in_(ids))
    )
    stats: Dict[Tuple[int, str], Dict] = {}
    for switch_id, port_name, mac_address in rows.all():
        key = port_analysis_service.normalize_port_key(port_name)
        if not key:
            continue
        entry = stats.setdefault((switch_id, key), {'mac_count': 0, 'macs': set()})
        mac = normalize_mac(str(mac_address)) if mac_address else None
        if mac:
            entry['macs'].add(mac)
    for entry in stats.values():
        entry['mac_count'] = len(entry['macs'])
    return stats


def _port_structural(
    src: Switch,
    fact: LldpNeighbor,
    src_iface: Optional[SwitchInterface],
    port_stats: Optional[Dict],
) -> Optional[Dict]:
    """从本端端口的 MAC 学习情况推导结构性证据，无数据返回 None。"""
    if not port_stats:
        return None
    raw_name = src_iface.if_name if src_iface is not None and src_iface.if_name else fact.local_port_id
    key = port_analysis_service.normalize_port_key(raw_name)
    if not key:
        return None
    entry = port_stats.get((src.id, key))
    if entry is None:
        return None
    chassis = normalize_mac(str(fact.remote_chassis_id)) if fact.remote_chassis_id else None
    return {
        'mac_count': entry['mac_count'],
        'self_chassis_learned': bool(chassis and chassis in entry['macs']),
    }


def _unknown_endpoint(
    fact: LldpNeighbor,
    node_key: str,
    structural: Optional[Dict] = None,
) -> Dict:
    return {
        'kind': 'unknown',
        'key': f'un:{node_key}',
        'switch_id': None,
        'if_index': None,
        'port_name': _trunc(fact.remote_port_id, 128),
        'sys_name': _trunc(fact.remote_sys_name, 255),
        'mgmt_ip': _trunc(_normalize_addr(fact.remote_mgmt_addr), 64),
        'chassis_id': _trunc(fact.remote_chassis_id, 255),
        'node_key': node_key,
        'lag_key': None,
        'capabilities': _parse_capabilities(fact.capability),
        'sys_desc': _trunc(fact.remote_sys_desc, 255),
        'structural': structural,
    }


def _link_row(ep_a: Dict, ep_b: Dict) -> Dict:
    return {
        'a_switch_id': ep_a['switch_id'],
        'a_if_index': ep_a['if_index'],
        'a_port_name': ep_a['port_name'],
        'a_sys_name': ep_a['sys_name'],
        'a_mgmt_ip': ep_a['mgmt_ip'],
        'b_switch_id': ep_b['switch_id'],
        'b_if_index': ep_b['if_index'],
        'b_port_name': ep_b['port_name'],
        'b_sys_name': ep_b['sys_name'],
        'b_mgmt_ip': ep_b['mgmt_ip'],
    }


def _compute_links(
    switches: List[Switch],
    facts: List[LldpNeighbor],
    interfaces: List[SwitchInterface],
    port_stats: Optional[Dict] = None,
) -> Tuple[List[Dict], Dict[str, Dict], int]:
    switches_by_id = {s.id: s for s in switches}
    endpoints = _Endpoints(switches, interfaces)
    ip_index, name_index = _build_identity_index(switches)

    stale_ids = {
        s.id for s in switches
        if s.last_topology_collection_status in ('failed', 'unsupported')
    }

    buckets: Dict[str, Dict] = {}

    for fact in facts:
        src = switches_by_id.get(fact.switch_id)
        if src is None:
            continue

        src_key, src_index, src_iface = endpoints.resolve(
            src.id, fact.local_if_index, fact.local_port_id
        )
        if src_key is None:
            continue
        src_ep = _switch_endpoint(src, endpoints, src_key, src_index, fact.local_port_id, src_iface)
        src_fresh = src.id not in stale_ids

        target_id, score, reason = _resolve_remote(
            switches_by_id, src.id, fact, endpoints, ip_index, name_index
        )

        if _is_self_fact(src, fact, ip_index, name_index):
            # 自环：同一端口指向自己 = 无意义，丢弃；不同端口 = 真实环路，标记待人工确认。
            dst_key, _, _ = endpoints.resolve(src.id, None, fact.remote_port_id)
            if dst_key is not None and dst_key == src_key:
                continue
            dst_ep = _switch_endpoint(src, endpoints, dst_key or 'nself', None, fact.remote_port_id, None)
            key = _link_key(src_ep['key'], dst_ep['key'])
            bucket = buckets.setdefault(key, {'ep_a': src_ep, 'ep_b': dst_ep, 'dirs': {}, 'flag': None})
            bucket['dirs'].setdefault(
                (src_ep['key'], dst_ep['key']), {'protocols': set(), 'fresh': False}
            )['protocols'].add(fact.protocol)
            bucket['dirs'][(src_ep['key'], dst_ep['key'])]['fresh'] |= src_fresh
            bucket['flag'] = {'status': 'unresolved', 'confidence': 40, 'reason': 'self loop detected on same switch'}
            continue

        if target_id is not None:
            target = switches_by_id[target_id]
            dst_key, dst_index, dst_iface = endpoints.resolve(
                target_id, None, fact.remote_port_id or fact.remote_port_desc
            )
            if dst_key is None:
                dst_key = 'p?'
            dst_ep = _switch_endpoint(target, endpoints, dst_key, dst_index, fact.remote_port_id, dst_iface)
        else:
            node_key = _unknown_node_key(fact)
            if not node_key:
                continue
            dst_ep = _unknown_endpoint(
                fact, node_key, _port_structural(src, fact, src_iface, port_stats)
            )

        key = _link_key(src_ep['key'], dst_ep['key'])
        bucket = buckets.setdefault(key, {'ep_a': src_ep, 'ep_b': dst_ep, 'dirs': {}, 'flag': None})
        direction = bucket['dirs'].setdefault(
            (src_ep['key'], dst_ep['key']), {'protocols': set(), 'fresh': False}
        )
        direction['protocols'].add(fact.protocol)
        direction['fresh'] |= src_fresh

        if target_id is None and 'ambiguous' in (reason or ''):
            bucket['flag'] = {'status': 'unresolved', 'confidence': 40, 'reason': reason}

    # 同一个端口指向多个对端：物理上不可能，标为冲突，不猜测。
    # 对端标识必须精确到「对端接口」，否则同一台交换机的两个接口不会被判为冲突。
    port_peers: Dict[str, Set[str]] = defaultdict(set)
    for bucket in buckets.values():
        for (src_key, dst_key) in bucket['dirs']:
            port_peers[src_key].add(dst_key)
    for bucket in buckets.values():
        conflicted = [
            key for key in bucket['dirs']
            if key[0].startswith('sw:') and len(port_peers.get(key[0], ())) > 1
        ]
        if conflicted:
            peers = sorted(port_peers[conflicted[0][0]])
            bucket['flag'] = {
                'status': 'unresolved',
                'confidence': 40,
                'reason': f"port reports multiple neighbors: {', '.join(peers[:5])}",
            }

    rows: List[Dict] = []
    for bucket in buckets.values():
        ep_a, ep_b = bucket['ep_a'], bucket['ep_b']
        # 端点顺序固定（按 key 排序），避免每轮 a/b 互换。
        if ep_a['key'] > ep_b['key']:
            ep_a, ep_b = ep_b, ep_a

        protocols: Set[str] = set()
        for direction in bucket['dirs'].values():
            protocols |= direction['protocols']
        # 只要有一端本轮没采到（failed / unsupported），链路就不能算新鲜：
        # 另一端看到的是上一次的事实，必须降级为 stale 而不是 confirmed。
        fresh = all(direction['fresh'] for direction in bucket['dirs'].values())

        flag = bucket.get('flag')
        if flag:
            status = flag['status']
            confidence = flag['confidence']
            reason = flag['reason']
        else:
            reverse_exists = any(
                (dst_key, src_key) in bucket['dirs']
                for (src_key, dst_key) in bucket['dirs']
            )
            if reverse_exists:
                status = 'confirmed'
                confidence = 100 if len(protocols) > 1 else 90
            else:
                status = 'one_sided'
                confidence = 70 if (ep_a['switch_id'] and ep_b['switch_id']) else 60
            reason = None

        if not fresh:
            status = 'stale'
            reason = reason or 'no fresh collection for one or both endpoints'

        evidence = 'both' if len(protocols) > 1 else next(iter(protocols), None)

        row = _link_row(ep_a, ep_b)
        row.update({
            'link_key': _link_key(ep_a['key'], ep_b['key']),
            'status': status,
            'confidence': confidence,
            'evidence': evidence,
            'is_lag': False,
            'conflict_reason': reason,
            'ep_a': ep_a,
            'ep_b': ep_b,
        })
        rows.append(row)

    # LAG 折叠：同 lag_key 指向同一对端的多条成员链路合并成一条。
    groups: Dict[Tuple, List[Dict]] = defaultdict(list)
    for row in rows:
        if row['status'] not in ('confirmed', 'one_sided'):
            continue
        lag_a = (row['ep_a'] or {}).get('lag_key')
        lag_b = (row['ep_b'] or {}).get('lag_key')
        if not lag_a and not lag_b:
            continue
        group_key = (
            row['ep_a'].get('switch_id'), lag_a,
            row['ep_b'].get('switch_id'), lag_b,
        )
        groups[group_key].append(row)

    folded: Set[str] = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        keep = max(members, key=lambda r: (r['status'] == 'confirmed', r['confidence']))
        keep['is_lag'] = True
        for member in members:
            if member is not keep:
                folded.add(member['link_key'])

    rows = [row for row in rows if row['link_key'] not in folded]
    return rows, {row['link_key']: row for row in rows}, len(folded)


async def derive_links(db: AsyncSession, now: Optional[datetime] = None) -> Dict:
    """从原始邻居事实重建派生链路 / 未知节点。不 commit。"""
    now = now or _now()

    switches = (await db.execute(select(Switch))).scalars().all()
    facts = (await db.execute(select(LldpNeighbor))).scalars().all()
    interfaces = (await db.execute(select(SwitchInterface))).scalars().all()

    # 端口 MAC 学习数只作结构性佐证；事实量过大或查询失败时降级为空表。
    port_stats: Dict = {}
    if len(facts) <= 20000:
        try:
            port_stats = await _load_port_mac_stats(db, [s.id for s in switches])
        except Exception as exc:  # noqa: BLE001 - 证据缺失只影响分类精度
            logger.warning(f"Load port MAC stats failed, classification degrades to unknown: {exc}")

    rows, fresh_map, lag_folded = _compute_links(
        list(switches), list(facts), list(interfaces), port_stats
    )
    stale_ids = {
        s.id for s in switches
        if s.last_topology_collection_status in ('failed', 'unsupported')
    }

    existing_rows = (await db.execute(select(TopologyLink))).scalars().all()
    existing = {row.link_key: row for row in existing_rows}

    for link_key, computed in fresh_map.items():
        row = existing.get(link_key)
        if row is None:
            row = TopologyLink(link_key=link_key, first_seen=now, last_seen=now, collected_at=now)
            db.add(row)
            existing[link_key] = row
        for field in (
            'a_switch_id', 'a_if_index', 'a_port_name', 'a_sys_name', 'a_mgmt_ip',
            'b_switch_id', 'b_if_index', 'b_port_name', 'b_sys_name', 'b_mgmt_ip',
        ):
            setattr(row, field, computed[field])
        row.status = computed['status']
        row.confidence = computed['confidence']
        row.evidence = computed['evidence']
        row.is_lag = computed['is_lag']
        row.conflict_reason = computed['conflict_reason']
        row.last_seen = now
        row.collected_at = now

    removed = 0
    for link_key, row in list(existing.items()):
        if link_key in fresh_map:
            continue
        touches_stale = (row.a_switch_id in stale_ids) or (row.b_switch_id in stale_ids)
        if touches_stale:
            # 该链路的一端本轮没采到，不能因为「没看到」就删掉，保留但标 stale。
            row.status = 'stale'
            row.conflict_reason = row.conflict_reason or 'endpoint collection failed this round'
        else:
            await db.delete(row)
            removed += 1

    # 未知节点：只保留本轮仍然出现在链路里的，累加 seen_count。
    node_info: Dict[str, Dict] = {}
    for computed in fresh_map.values():
        for side in (computed['ep_a'], computed['ep_b']):
            if side['kind'] != 'unknown' or not side.get('node_key'):
                continue
            node_key = side['node_key']
            info = node_info.get(node_key)
            if info is None:
                info = {
                    'display_name': side['sys_name'] or side['mgmt_ip'] or side['chassis_id'] or node_key,
                    'mgmt_ip': side['mgmt_ip'],
                    'chassis_id': side['chassis_id'],
                    'sys_name': side['sys_name'],
                    'sys_desc': side.get('sys_desc'),
                    'capabilities': set(side.get('capabilities') or ()),
                    'mac_count': (side.get('structural') or {}).get('mac_count'),
                    'self_chassis_learned': bool(
                        (side.get('structural') or {}).get('self_chassis_learned')
                    ),
                }
                node_info[node_key] = info
                continue
            # 同一节点可能被多台交换机看到：合并 capability，缺失字段用后到的补齐。
            info['capabilities'] |= set(side.get('capabilities') or ())
            info['sys_desc'] = info['sys_desc'] or side.get('sys_desc')
            info['sys_name'] = info['sys_name'] or side['sys_name']
            info['chassis_id'] = info['chassis_id'] or side['chassis_id']
            info['mgmt_ip'] = info['mgmt_ip'] or side['mgmt_ip']
            mac_count = (side.get('structural') or {}).get('mac_count')
            if mac_count is not None:
                info['mac_count'] = max(info.get('mac_count') or 0, mac_count)
            info['self_chassis_learned'] = info['self_chassis_learned'] or bool(
                (side.get('structural') or {}).get('self_chassis_learned')
            )

    # 跨表关联本系统 IPAM 档案，补充 os_type 等 LLDP 拿不到的依据。
    # 关联失败只降级为「没有补充依据」，不影响派生。
    try:
        ipam_hints = await lookup_ipam_profiles(db, [
            {
                'key': node_key,
                'mgmt_ip': info.get('mgmt_ip'),
                'sys_name': info.get('sys_name'),
                'chassis_id': info.get('chassis_id'),
            }
            for node_key, info in node_info.items()
        ])
    except Exception as e:
        logger.warning(f"IPAM profile hints unavailable: {e}")
        ipam_hints = {}

    existing_nodes = {
        node.node_key: node
        for node in (await db.execute(select(TopologyUnknownNode))).scalars().all()
    }
    for node_key, info in node_info.items():
        node = existing_nodes.get(node_key)
        if node is None:
            node = TopologyUnknownNode(node_key=node_key, first_seen=now, last_seen=now, seen_count=1)
            db.add(node)
        else:
            node.seen_count = (node.seen_count or 0) + 1
            node.last_seen = now
        node.display_name = _trunc(info['display_name'], 255)
        node.mgmt_ip = _trunc(info['mgmt_ip'], 64)
        node.chassis_id = _trunc(info['chassis_id'], 255)
        node.sys_name = _trunc(info['sys_name'], 255)
        node.vendor_hint = _trunc(
            _vendor_hint(info['sys_name'], info['chassis_id'], info.get('sys_desc')), 100
        )
        hint = ipam_hints.get(node_key) or {}
        classification = classify_unknown(
            capabilities=info['capabilities'],
            sys_name=info['sys_name'],
            sys_desc=info.get('sys_desc'),
            chassis_id=info['chassis_id'],
            mgmt_ip=info['mgmt_ip'],
            mac_count=info.get('mac_count'),
            self_chassis_learned=info.get('self_chassis_learned', False),
            os_type=hint.get('os_type'),
            ipam_vendor=hint.get('vendor'),
            ipam_matched_by=hint.get('matched_by'),
        )
        node.device_class = _trunc(classification.device_class, 20)
        node.device_confidence = classification.confidence
        node.device_reasons = list(classification.reasons)

    for node_key, node in existing_nodes.items():
        if node_key not in node_info:
            await db.delete(node)

    await db.flush()

    summary = {
        'links': len(fresh_map),
        'confirmed': sum(1 for r in fresh_map.values() if r['status'] == 'confirmed'),
        'one_sided': sum(1 for r in fresh_map.values() if r['status'] == 'one_sided'),
        'unresolved': sum(1 for r in fresh_map.values() if r['status'] == 'unresolved'),
        'stale': sum(1 for r in fresh_map.values() if r['status'] == 'stale'),
        'lag_folded': lag_folded,
        'unknown_nodes': len(node_info),
        'removed': removed,
    }
    logger.info(f"Topology derived: {summary}")
    return summary
