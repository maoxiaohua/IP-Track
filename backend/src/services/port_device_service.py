"""
端口 ↔ 设备联动服务。

给定「交换机 + 端口」，回答这个端口对面接的是什么设备（交换机/路由器/HUB/
AP/PC/话机/未知），并给出置信度与判定依据。同一份 classify_unknown 既用于
拓扑派生，也用于「IP 在哪个交换机哪个端口」的展示，保证两处结论一致。

数据来源全部是既有事实表（Switch / SwitchInterface / LldpNeighbor），不发起
任何 HTTP 调用 —— core / ipam / collector 共用一个数据库，直接查表即可。
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.switch import Switch
from models.topology import LldpNeighbor, SwitchInterface
from services.device_classifier import classify_unknown
from services.ipam_device_hints import lookup_ipam_profiles
from services.lldp_signals import parse_capabilities
from services.port_analysis_service import port_analysis_service
from services.topology_utils import normalize_mac
from utils.logger import logger

# 「单一设备」判定阈值：低于该值只说明有邻居，不能断言端口对面是什么。
SINGLE_DEVICE_MIN_CONFIDENCE = 70

# 排序用：同等置信度下，网络设备优先于终端，终端优先于未知，结果稳定可复现。
_CLASS_ORDER = {
    'switch': 0, 'router': 1, 'hub': 2, 'wlan-ap': 3,
    'unknown': 4, 'host': 5, 'phone': 6,
}


def port_key(port_name: Any) -> str:
    """跨表匹配用的端口键（与拓扑派生使用同一套归一化）。"""
    return port_analysis_service.normalize_port_key(str(port_name or ''))


def _norm_ip(value: Any) -> Optional[str]:
    text = str(value or '').strip().lower()
    if not text or text in ('0.0.0.0', '-', 'n/a', 'not advertised'):
        return None
    return text


def _build_managed_index(switches: List[Switch]) -> Dict[str, Dict[str, Any]]:
    """已纳管交换机的身份索引：管理 IP / chassis / bridge MAC / sysName。"""
    index: Dict[str, Dict[str, Any]] = {'ips': {}, 'macs': {}, 'names': {}}
    for sw in switches:
        name = sw.sys_name or sw.name
        for ip in (getattr(sw, 'ip_address', None), getattr(sw, 'mgmt_ip', None)):
            key = _norm_ip(ip)
            if key:
                index['ips'][key] = sw.id
        for value in (sw.chassis_id, sw.bridge_mac):
            mac = normalize_mac(str(value)) if value else None
            if mac:
                index['macs'][mac] = sw.id
        sys_name = str(sw.sys_name or '').strip().lower()
        if len(sys_name) >= 3:
            index['names'][sys_name] = sw.id
    return index


def _match_managed(
    fact: LldpNeighbor,
    index: Dict[str, Dict[str, Any]],
    self_switch_id: int,
) -> Optional[Switch]:
    """邻居是否就是某台已纳管交换机；命中返回该交换机 id（排除本机）。"""
    ip = _norm_ip(fact.remote_mgmt_addr)
    if ip and ip in index['ips']:
        matched = index['ips'][ip]
        if matched != self_switch_id:
            return matched
    mac = normalize_mac(str(fact.remote_chassis_id)) if fact.remote_chassis_id else None
    if mac and mac in index['macs']:
        matched = index['macs'][mac]
        if matched != self_switch_id:
            return matched
    sys_name = str(fact.remote_sys_name or '').strip().lower()
    if len(sys_name) >= 3 and sys_name in index['names']:
        matched = index['names'][sys_name]
        if matched != self_switch_id:
            return matched
    return None


def _classify_fact(
    fact: LldpNeighbor,
    switch_names: Dict[int, str],
    index: Dict[str, Dict[str, Any]],
    self_switch_id: int,
    ipam_hint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    matched_id = _match_managed(fact, index, self_switch_id)
    if matched_id is not None:
        name = switch_names.get(matched_id, f'#{matched_id}')
        return {
            'device_class': 'switch',
            'confidence': 100,
            'reasons': [f'匹配已纳管交换机 “{name}”'],
            'managed': True,
            'sys_name': fact.remote_sys_name,
            'mgmt_ip': fact.remote_mgmt_addr,
        }
    hint = ipam_hint or {}
    result = classify_unknown(
        capabilities=parse_capabilities(fact.capability),
        sys_name=fact.remote_sys_name,
        sys_desc=fact.remote_sys_desc,
        chassis_id=fact.remote_chassis_id,
        mgmt_ip=fact.remote_mgmt_addr,
        port_desc=fact.remote_port_desc,
        os_type=hint.get('os_type'),
        ipam_vendor=hint.get('vendor'),
        ipam_matched_by=hint.get('matched_by'),
    )
    return {
        'device_class': result.device_class,
        'confidence': result.confidence,
        'reasons': list(result.reasons),
        'managed': False,
        'sys_name': fact.remote_sys_name,
        'mgmt_ip': fact.remote_mgmt_addr,
    }


async def _load_ipam_hints(
    db: AsyncSession,
    facts: List[LldpNeighbor],
) -> Dict[int, Dict[str, Any]]:
    """批量把 LLDP 邻居关联到 IPAM 档案，取 os_type 作补充依据。

    键用内存对象 id（同一批对象内唯一），关联失败等价于没有补充依据。
    """
    if not facts:
        return {}
    try:
        return await lookup_ipam_profiles(db, [
            {
                'key': id(fact),
                'mgmt_ip': fact.remote_mgmt_addr,
                'sys_name': fact.remote_sys_name,
                'chassis_id': fact.remote_chassis_id,
            }
            for fact in facts
        ])
    except Exception as e:
        logger.warning(f"IPAM profile hints unavailable for port devices: {e}")
        return {}


def _empty_record() -> Dict[str, Any]:
    return {
        'status': 'none',
        'candidates': 0,
        'port_device': None,
        'port_device_class': None,
        'port_device_confidence': None,
        'port_device_reasons': None,
    }


def _build_record(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candidates:
        return _empty_record()
    ranked = sorted(
        candidates,
        key=lambda c: (
            -int(c['confidence']),
            _CLASS_ORDER.get(c['device_class'], 9),
            str(c.get('sys_name') or ''),
        ),
    )
    best = ranked[0]
    unique_best = (
        len(ranked) == 1
        or ranked[1]['confidence'] < best['confidence']
        or ranked[1]['device_class'] != best['device_class']
    )
    if best['confidence'] >= SINGLE_DEVICE_MIN_CONFIDENCE and unique_best:
        status = 'single'
    elif len(ranked) > 1:
        status = 'multiple'
    else:
        status = 'none'
    return {
        'status': status,
        'candidates': len(ranked),
        'port_device': best,
        'port_device_class': best['device_class'],
        'port_device_confidence': best['confidence'],
        'port_device_reasons': '；'.join(best['reasons']),
    }


async def load_port_devices(
    db: AsyncSession,
    pairs: Set[Tuple[int, str]],
) -> Dict[Tuple[int, str], Dict[str, Any]]:
    """批量查询若干 (switch_id, port_name) 端口的对端设备。

    返回键是 (switch_id, normalize_port_key(port_name))；没有 LLDP/CDP 邻居的
    端口不出现在结果里，调用方用 _empty_record 的语义兜底。
    """
    normalized: Dict[Tuple[int, str], Tuple[int, str]] = {}
    for switch_id, port_name in pairs:
        if switch_id is None:
            continue
        key = port_key(port_name)
        if key:
            normalized[(int(switch_id), key)] = (int(switch_id), str(port_name))
    if not normalized:
        return {}

    switch_ids = sorted({sid for sid, _ in normalized})

    iface_rows = await db.execute(
        select(SwitchInterface.switch_id, SwitchInterface.if_index, SwitchInterface.if_name)
        .where(SwitchInterface.switch_id.in_(switch_ids))
    )
    name_by_index: Dict[Tuple[int, int], str] = {}
    for switch_id, if_index, if_name in iface_rows.all():
        if if_name:
            name_by_index[(switch_id, int(if_index))] = if_name

    facts = (
        await db.execute(
            select(LldpNeighbor).where(LldpNeighbor.switch_id.in_(switch_ids))
        )
    ).scalars().all()

    switches = (
        await db.execute(select(Switch).where(Switch.id.in_(switch_ids)))
    ).scalars().all()
    switch_names = {sw.id: (sw.sys_name or sw.name) for sw in switches}

    # 已纳管身份要覆盖全部交换机（对端可能是本次没查询的交换机）。
    all_switches = (await db.execute(select(Switch))).scalars().all()
    managed_index = _build_managed_index(list(all_switches))

    ipam_hints = await _load_ipam_hints(db, list(facts))

    grouped: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
    for fact in facts:
        local_name = None
        if fact.local_if_index is not None:
            local_name = name_by_index.get((fact.switch_id, int(fact.local_if_index)))
        key = port_key(local_name or fact.local_port_id)
        if not key:
            continue
        bucket = grouped.setdefault((fact.switch_id, key), [])
        bucket.append(_classify_fact(
            fact, switch_names, managed_index, fact.switch_id, ipam_hints.get(id(fact))
        ))

    return {pair: _build_record(grouped.get(pair, [])) for pair in normalized}


def compact_port_device(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把 load_port_devices 的记录压成 API/前端直接可用的一份设备描述。"""
    best = record.get('port_device')
    if not best:
        return None
    return {
        'device_class': best['device_class'],
        'confidence': best['confidence'],
        'reasons': list(best['reasons']),
        'managed': best['managed'],
        'sys_name': best['sys_name'],
        'mgmt_ip': best['mgmt_ip'],
        'status': record.get('status'),
        'candidates': record.get('candidates'),
    }


async def describe_port_devices(
    db: AsyncSession,
    switch_id: int,
    port_name: str,
) -> Dict[str, Any]:
    """单个端口的对端设备；无邻居时返回 none 状态而不是报错。"""
    key = port_key(port_name)
    if key is None or not key:
        return _empty_record()
    records = await load_port_devices(db, {(int(switch_id), str(port_name))})
    return records.get((int(switch_id), key)) or _empty_record()


async def load_switch_port_devices(
    db: AsyncSession,
    switch_id: int,
) -> List[Dict[str, Any]]:
    """一台交换机所有端口的对端设备，按接口清单顺序返回。

    端口清单页一次取齐，避免逐端口请求；无邻居的端口返回 none 状态。
    """
    switch_id = int(switch_id)
    interfaces = (await db.execute(
        select(SwitchInterface)
        .where(SwitchInterface.switch_id == switch_id)
        .order_by(
            SwitchInterface.if_name.asc().nullslast(),
            SwitchInterface.if_index.asc(),
        )
    )).scalars().all()
    facts = (await db.execute(
        select(LldpNeighbor.local_port_id, LldpNeighbor.local_if_index)
        .where(LldpNeighbor.switch_id == switch_id)
    )).all()

    pairs: Set[Tuple[int, str]] = set()
    for iface in interfaces:
        for value in (iface.if_name, iface.if_descr):
            if value:
                pairs.add((switch_id, str(value)))
    for local_port_id, _ in facts:
        if local_port_id:
            pairs.add((switch_id, str(local_port_id)))

    records = await load_port_devices(db, pairs) if pairs else {}

    items: List[Dict[str, Any]] = []
    for iface in interfaces:
        record = None
        for value in (iface.if_name, iface.if_descr):
            if value:
                record = records.get((switch_id, port_key(value)))
                if record:
                    break
        record = record or _empty_record()
        items.append({
            'if_index': iface.if_index,
            'if_name': iface.if_name,
            'if_alias': iface.if_alias,
            'admin_status': iface.admin_status,
            'oper_status': iface.oper_status,
            'status': record['status'],
            'candidates': record['candidates'],
            'port_device': compact_port_device(record),
            'port_device_class': record['port_device_class'],
            'port_device_confidence': record['port_device_confidence'],
            'port_device_reasons': record['port_device_reasons'],
        })
    return items
