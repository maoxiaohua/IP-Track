"""
LLDP 邻居 ↔ 本系统 IPAM 档案关联。

用途：LLDP 只带 chassis / sysName / 管理 IP，多数 Windows 终端不发 capability，
单靠能力位判不出「这是 PC」。但 IPAM 扫描时已经记录了这些 IP 的 os_type /
hostname / mac_address，做一次跨表关联就能拿到补充依据。

匹配优先级：chassis MAC → 管理 IP → 系统名（MAC 是硬件唯一标识，最可信；
系统名最弱）。MAC 在 ip_addresses 里找不到时，再用 arp_table 反查一次 IP。

只读、批量、零 HTTP：collector / core / ipam 共用一个库，直接查询。
"""

import ipaddress
import re
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.topology_utils import normalize_mac

# 单次关联的探针上限，避免异常输入把 SQL 参数撑爆。
_MAX_PROBES = 2000

_MAC_PATTERN = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$')


def _clean(value: Any) -> Optional[str]:
    candidate = str(value or '').strip()
    if not candidate or candidate.lower() in ('-', 'n/a', 'na', 'none', 'null', 'unknown'):
        return None
    return candidate


def _norm_ip(value: Any) -> Optional[str]:
    """只接受合法 IP（INET 数组参数必须能安全 CAST，非法值直接丢弃）。"""
    candidate = _clean(value)
    if not candidate:
        return None
    try:
        return str(ipaddress.ip_address(candidate.split('/')[0]))
    except ValueError:
        return None


def _norm_mac(value: Any) -> Optional[str]:
    """归一成 aa:bb:cc:dd:ee:ff；接受冒号/短横线/dot1q 三种写法。"""
    candidate = _clean(value)
    if not candidate:
        return None
    normalized = normalize_mac(candidate)
    if not normalized or not _MAC_PATTERN.match(normalized):
        return None
    return normalized


async def _fetch_ip_profiles(
    db: AsyncSession,
    ips: Iterable[str],
    names: Iterable[str],
    macs: Iterable[str],
) -> List[Any]:
    """按 IP / 系统名 / MAC 三路各查一次 ip_addresses，命中任意一路即返回。"""
    rows: List[Any] = []
    if ips:
        rows.extend((await db.execute(
            text(
                "SELECT host(ip_address) AS ip, lower(hostname) AS hostname, "
                "mac_address::text AS mac, os_type, vendor "
                "FROM ip_addresses WHERE ip_address = ANY(CAST(:keys AS inet[]))"
            ),
            {'keys': list(ips)},
        )).all())
    if names:
        rows.extend((await db.execute(
            text(
                "SELECT host(ip_address) AS ip, lower(hostname) AS hostname, "
                "mac_address::text AS mac, os_type, vendor "
                "FROM ip_addresses WHERE lower(hostname) = ANY(:keys)"
            ),
            {'keys': list(names)},
        )).all())
    if macs:
        rows.extend((await db.execute(
            text(
                "SELECT host(ip_address) AS ip, lower(hostname) AS hostname, "
                "mac_address::text AS mac, os_type, vendor "
                "FROM ip_addresses WHERE mac_address = ANY(CAST(:keys AS macaddr[]))"
            ),
            {'keys': list(macs)},
        )).all())
    return rows


async def _fetch_arp_ips(db: AsyncSession, macs: Iterable[str]) -> Dict[str, str]:
    """chassis MAC → ARP 表里的 IP（ip_addresses 没记 MAC 时的补充通路）。"""
    if not macs:
        return {}
    rows = (await db.execute(
        text(
            "SELECT host(ip_address) AS ip, mac_address::text AS mac "
            "FROM arp_table WHERE mac_address = ANY(CAST(:keys AS macaddr[]))"
        ),
        {'keys': list(macs)},
    )).all()
    mapping: Dict[str, str] = {}
    for row in rows:
        mac = _norm_mac(getattr(row, 'mac', None))
        ip = _norm_ip(getattr(row, 'ip', None))
        if mac and ip and mac not in mapping:
            mapping[mac] = ip
    return mapping


def _as_hint(row: Any, matched_by: str) -> Dict[str, Any]:
    return {
        'os_type': (str(getattr(row, 'os_type', '') or '').strip().lower() or None),
        'vendor': getattr(row, 'vendor', None),
        'hostname': getattr(row, 'hostname', None),
        'matched_by': matched_by,
    }


async def lookup_ipam_profiles(
    db: AsyncSession,
    probes: Iterable[Dict[str, Any]],
) -> Dict[Any, Dict[str, Any]]:
    """
    批量把 LLDP 邻居关联到 IPAM 档案。

    probes: [{'key': <任意标识>, 'mgmt_ip': .., 'sys_name': .., 'chassis_id': ..}]
    返回:   {key: {'os_type', 'vendor', 'hostname', 'matched_by'}}
    未关联到的 key 不出现在结果里。异常不抛给调用方，关联失败等价于没有依据。
    """
    items = [p for p in probes or [] if p.get('key') is not None][:_MAX_PROBES]
    if not items:
        return {}

    ips: List[str] = []
    names: List[str] = []
    macs: List[str] = []
    for probe in items:
        ip = _norm_ip(probe.get('mgmt_ip'))
        if ip:
            ips.append(ip)
        name = _clean(probe.get('sys_name'))
        if name and len(name) >= 3:
            names.append(name.lower())
        mac = _norm_mac(probe.get('chassis_id'))
        if mac:
            macs.append(mac)

    rows = await _fetch_ip_profiles(db, ips, names, macs)

    by_mac: Dict[str, Any] = {}
    by_ip: Dict[str, Any] = {}
    by_name: Dict[str, Any] = {}
    for row in rows:
        mac = _norm_mac(getattr(row, 'mac', None))
        if mac and mac not in by_mac:
            by_mac[mac] = row
        ip = _norm_ip(getattr(row, 'ip', None))
        if ip and ip not in by_ip:
            by_ip[ip] = row
        name = str(getattr(row, 'hostname', '') or '').strip().lower()
        if name and name not in by_name:
            by_name[name] = row

    # 第一轮：MAC → 管理 IP → 系统名
    matched: Dict[Any, Dict[str, Any]] = {}
    unresolved: List[Dict[str, Any]] = []
    for probe in items:
        mac = _norm_mac(probe.get('chassis_id'))
        if mac and mac in by_mac:
            matched[probe['key']] = _as_hint(by_mac[mac], 'mac')
            continue
        ip = _norm_ip(probe.get('mgmt_ip'))
        if ip and ip in by_ip:
            matched[probe['key']] = _as_hint(by_ip[ip], 'mgmt_ip')
            continue
        name = _clean(probe.get('sys_name'))
        if name and name.lower() in by_name:
            matched[probe['key']] = _as_hint(by_name[name.lower()], 'sys_name')
            continue
        unresolved.append(probe)

    # 第二轮：chassis MAC 去 ARP 表反查 IP，再匹配一次
    pending_macs = [m for m in (
        _norm_mac(p.get('chassis_id')) for p in unresolved
    ) if m and m not in by_mac]
    if pending_macs:
        arp_map = await _fetch_arp_ips(db, pending_macs)
        arp_ips = sorted({ip for ip in arp_map.values() if ip})
        if arp_ips:
            extra_rows = (await db.execute(
                text(
                    "SELECT host(ip_address) AS ip, lower(hostname) AS hostname, "
                    "mac_address::text AS mac, os_type, vendor "
                    "FROM ip_addresses WHERE ip_address = ANY(CAST(:keys AS inet[]))"
                ),
                {'keys': arp_ips},
            )).all()
            for row in extra_rows:
                ip = _norm_ip(getattr(row, 'ip', None))
                if ip and ip not in by_ip:
                    by_ip[ip] = row
        for probe in unresolved:
            mac = _norm_mac(probe.get('chassis_id'))
            if not mac:
                continue
            ip = arp_map.get(mac)
            if ip and ip in by_ip:
                matched[probe['key']] = _as_hint(by_ip[ip], 'mac')

    return matched
