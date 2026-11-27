"""
未纳管邻居（LLDP/CDP 对端）的设备分类器。

纯函数、零 IO、无新依赖：同一份判定逻辑既用于拓扑节点，也用于
「IP 在哪个交换机哪个端口」的端口↔设备联动，保证两处结论一致。

判定优先级：
1. LLDP capability 权威（bridge/router/wlan-ap/phone/host/repeater）；
2. 描述文本（网络操作系统标识 / 终端系统标识）；
3. IPAM 档案 os_type（跨表关联得到，仅作补充：终端→host、network→switch，
   厂商为网络厂商时该 os_type 不可信）；
4. 端口 MAC 学习数等结构性证据加权，达到阈值才落类，否则 unknown。
任何证据都不足以定类时返回 unknown —— 拓扑侧 unknown 仍然可见。
"""

from dataclasses import dataclass
from typing import Any, Iterable, Optional, Tuple

from services.lldp_signals import (
    HOST_OS_TYPES,
    MATCH_LABELS,
    ROUTER_HINTS,
    SERVER_HINTS,
    SWITCH_HINTS,
    is_network_vendor,
    parse_capabilities,
)
from services.topology_utils import normalize_mac

# 无 capability 时，结构性证据总分达到该阈值才落类。
MIN_CONFIDENCE = 60

# LLDP 字段里的假空值（各厂商写法不同）。
_PLACEHOLDERS = {
    '', '-', '--', '---', 'n/a', 'na', 'none', 'null', 'unknown',
    'not advertised', 'not-present', 'not present',
}

# 端口描述里会出现的上联/级联关键字。
_UPLINK_PORT_HINTS = ('uplink', 'trunk', 'cascade', 'peer-link', 'stack')

# capability -> (设备类别, 置信度)
_CAPABILITY_CLASSES = (
    ('bridge', 'switch', 95),
    ('router', 'router', 95),
    ('wlan-ap', 'wlan-ap', 95),
    ('phone', 'phone', 95),
    ('host', 'host', 95),
    ('repeater', 'hub', 90),
)


@dataclass(frozen=True)
class DeviceClassification:
    device_class: str
    confidence: int
    reasons: Tuple[str, ...]


def clean_text(value: Any) -> str:
    """去掉占位符与 NUL，返回小写文本；无有效内容返回空串。"""
    text = str(value or '').replace('\x00', '').strip()
    if not text or text.lower() in _PLACEHOLDERS:
        return ''
    return text


def _longest_hint(blob: str, hints: Iterable[str]) -> Optional[str]:
    """返回 blob 命中的最长关键字（越具体越可信），未命中返回 None。"""
    matched = [hint for hint in hints if hint in blob]
    if not matched:
        return None
    return max(matched, key=len)


def _ipam_reason(os_type: Any, vendor: Any, matched_by: Any) -> str:
    """把 IPAM 档案线索转成可展示的依据文本；无有效 os_type 返回空串。"""
    ipam_os = clean_text(os_type)
    if not ipam_os:
        return ''
    label = MATCH_LABELS.get(str(matched_by or '').strip(), '档案')
    if is_network_vendor(vendor):
        return f'IPAM 档案（{label}）记录 os_type={ipam_os}，但厂商为网络厂商（不采信该 os_type）'
    return f'IPAM 档案（{label}）记录 os_type={ipam_os}'


def _classify_by_ipam(os_type: Any, vendor: Any) -> Optional[tuple]:
    """
    用 IPAM 档案作补充依据。

    只对明确的终端 os_type 判 host、明确 network 判 switch；厂商为网络厂商时
    不采信 os_type（实测存在 Cisco 交换机被录成 linux 的情况）。
    """
    ipam_os = clean_text(os_type)
    if not ipam_os:
        return None
    if ipam_os == 'network':
        return ('switch', 75)
    if ipam_os in HOST_OS_TYPES and not is_network_vendor(vendor):
        return ('host', 85)
    return None


def classify_unknown(
    capabilities: Iterable[str] = (),
    sys_name: Any = None,
    sys_desc: Any = None,
    chassis_id: Any = None,
    mgmt_ip: Any = None,
    mac_count: Optional[int] = None,
    self_chassis_learned: bool = False,
    port_desc: Any = None,
    os_type: Any = None,
    ipam_vendor: Any = None,
    ipam_matched_by: Any = None,
) -> DeviceClassification:
    """按 capability → 文本 → IPAM 档案 → 端口结构性证据的顺序给出设备类别与判定依据。"""
    caps = set(capabilities or ())
    for cap, device_class, confidence in _CAPABILITY_CLASSES:
        if cap in caps:
            return DeviceClassification(device_class, confidence, (f'LLDP capability 含 {cap}',))

    name = clean_text(sys_name)
    desc = clean_text(sys_desc)
    ip = clean_text(mgmt_ip)
    pdesc = clean_text(port_desc)
    blob = ' '.join(t.lower() for t in (name, desc, pdesc) if t)

    router_hit = _longest_hint(blob, ROUTER_HINTS)
    switch_hit = _longest_hint(blob, SWITCH_HINTS)
    server_hit = _longest_hint(blob, SERVER_HINTS)
    reasons = []

    # 网络系统标识优先；用最长命中消歧（如 SRLinux 同时含 srlinux 与 linux）。
    if router_hit and len(router_hit) >= len(switch_hit or ''):
        return DeviceClassification('router', 80, (f'描述含网络系统标识 “{router_hit}”',))
    if switch_hit and len(switch_hit) >= len(server_hit or ''):
        return DeviceClassification('switch', 80, (f'描述含网络系统标识 “{switch_hit}”',))
    if server_hit and len(server_hit) > len(switch_hit or ''):
        return DeviceClassification('host', 80, (f'描述含终端系统标识 “{server_hit}”',))

    ipam_reason = _ipam_reason(os_type, ipam_vendor, ipam_matched_by)
    ipam_decision = _classify_by_ipam(os_type, ipam_vendor)
    if ipam_decision:
        return DeviceClassification(ipam_decision[0], ipam_decision[1], (ipam_reason,))
    if ipam_reason:
        reasons.append(ipam_reason)

    score = 0
    if mac_count is not None:
        if mac_count >= 10:
            score += 50
            reasons.append(f'端口学习 {mac_count} 个 MAC（疑似级联桥）')
        elif mac_count >= 2:
            score += 25
            reasons.append(f'端口学习 {mac_count} 个 MAC')
        else:
            reasons.append(f'端口仅学习 {mac_count} 个 MAC')
    if name:
        score += 10
        reasons.append(f'有系统名 “{name}”')
    if ip:
        score += 10
        reasons.append(f'有管理 IP {ip}')
    if pdesc and any(hint in pdesc.lower() for hint in _UPLINK_PORT_HINTS):
        score += 5
        reasons.append('端口描述为上联/级联')
    if self_chassis_learned:
        # 只证明对端是桥设备，不能单独排除 PC，故仅作加分。
        score += 5
        reasons.append('对端 chassis 出现在本机 MAC 表')

    if score >= MIN_CONFIDENCE:
        return DeviceClassification('switch', min(score, 90), tuple(reasons))

    normalized_chassis = normalize_mac(str(chassis_id)) if clean_text(chassis_id) else None
    if normalized_chassis:
        reasons.append(f'chassis {normalized_chassis}')
    if not reasons:
        reasons.append('无可用判定证据')
    return DeviceClassification('unknown', max(score, 0), tuple(reasons))
