"""
拓扑采集/推导共用的纯函数（无数据库、无网络依赖）。

放在这里是因为 SNMP 采集、CLI 采集、推导服务都要用同一套归一化规则，
分开实现迟早会漂移（例如 SNMP 侧把 Port-Channel 归一成 portchannel，
CLI 侧却算成 po，LAG 就折叠不到一起）。
"""

import re
import zlib
from typing import Optional


# LAG 接口名前缀 -> 规范键。po / port-channel 是 Cisco 同一族的两种写法。
_LAG_PATTERN = re.compile(r'^(ae|lag|po|portchannel|bundle|bundleether)(\d+)$')


def normalize_lag_key(if_name: Optional[str]) -> Optional[str]:
    """把 ae0 / Port-Channel1 / Bundle-Ether10 等归一成同一个 LAG 键。"""
    if not if_name:
        return None
    compact = re.sub(r'[\s\-_./]', '', str(if_name).lower())
    match = _LAG_PATTERN.match(compact)
    if not match:
        return None
    alias = 'portchannel' if match.group(1) in ('po', 'portchannel') else match.group(1)
    return f'{alias}{match.group(2)}'


def normalize_mac(value: Optional[str]) -> Optional[str]:
    """把 0011.2233.4455 / 00-11-22-33-44-55 统一成 00:11:22:33:44:55。"""
    if not value:
        return None
    text = str(value).strip().lower()
    compact = text.replace(':', '').replace('-', '').replace('.', '')
    if len(compact) == 12 and re.fullmatch(r'[0-9a-f]{12}', compact):
        return ':'.join(compact[i:i + 2] for i in range(0, 12, 2))
    return text or None


def synthetic_if_index(if_name: Optional[str]) -> int:
    """
    CLI 采集拿不到真实 ifIndex 时，用接口名生成一个稳定的负数索引。

    负数保证不会和 SNMP 的正数 ifIndex 冲突（两种采集方式切换时不会互相覆盖）。
    """
    compact = str(if_name or '').strip().lower()
    return -(zlib.crc32(compact.encode('utf-8')) % 2_000_000_000) - 1


def looks_like_port(value: Optional[str]) -> bool:
    """
    判断一个 token 是否像接口名。

    需要覆盖：1/1/1、1/1/c1/1（Nokia）、Gi1/0/1、ae1、lag-1、
    Port-Channel10、xe-0/0/0.0（Juniper）、Ethernet1/1。
    不接受含空格或冒号的字符串（避免把 IP / IPv6 当端口）。
    """
    if not value:
        return False
    compact = str(value).strip().lower()
    if not compact or ' ' in compact or ':' in compact:
        return False
    # 纯点分数字是 IPv4，不是端口（Juniper 子接口形态 xe-0/0/0.0 带字母/斜杠，不受影响）。
    if re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}', compact):
        return False
    return bool(re.fullmatch(
        r'(?:[a-z][a-z\-]{0,15})?\d+(?:[/\-\.][a-z]{0,2}\d+)*', compact
    ))
