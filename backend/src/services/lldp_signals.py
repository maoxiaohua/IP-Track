"""
LLDP 邻居信号词表与 capability 解析。

从 topology_service 抽出，供拓扑派生与端口↔设备联动共用，避免两套判定。
"""

import re
from typing import Any, Set

# IEEE 802.1AB lldpRemSysCapSupported 位（BITS 从最高位编号）；SNMP 侧存 hex，
# CLI 侧存文本，两种格式都要认。按字节数换算位掩码，1/2 字节编码都能解。
CAPABILITY_POSITIONS = (
    ('repeater', 1),
    ('bridge', 2),
    ('wlan-ap', 3),
    ('router', 4),
    ('phone', 5),
    ('docsis', 6),
    ('host', 7),
)
CAPABILITY_WORDS = (
    ('access point', 'wlan-ap'),
    ('wlan', 'wlan-ap'),
    ('router', 'router'),
    ('bridge', 'bridge'),
    ('switch', 'bridge'),
    ('repeater', 'repeater'),
    ('telephone', 'phone'),
    ('phone', 'phone'),
    ('station', 'host'),
    ('host', 'host'),
    ('docsis', 'docsis'),
)
# 文本兜底：只在没有 capability 时使用，宁可判 unknown 也不乱归类。
SERVER_HINTS = (
    'windows', 'linux', 'vmware', 'esxi', 'hyper-v', 'server', 'workstation',
    'ubuntu', 'debian', 'centos', 'red hat', 'mac os', 'iphone', 'ipad',
    'android', 'printer', 'camera', 'apc ', 'ups ',
)
ROUTER_HINTS = ('router', 'gateway', 'firewall', 'srx', 'fortigate')
SWITCH_HINTS = (
    # 'ios' 会误命中服务器 BIOS，网络系统已可由 cisco/nx-os/comware 等词覆盖，故不单列。
    'switch', 'catalyst', 'nexus', 'nx-os', 'comware', 'sros', 'sr os', 'srlinux',
    'alcatel', 'nokia', 'h3c', 'huawei', 'cisco', 'juniper', 'aruba',
    'procurve', 'quidway', 'omniswitch', 'edge-core', 'dell',
)


# IPAM 档案（跨表关联得到）的 OS 类型词表。LLDP 本身不带系统信息，
# 但 IPAM 扫描记录了 os_type，可作为补充依据。
HOST_OS_TYPES = ('windows', 'linux', 'macos')

# 命中这些厂商说明 IPAM 的 os_type 不可信（实测本库有 Cisco 交换机被录成 linux）。
NETWORK_VENDOR_HINTS = (
    'cisco', 'juniper', 'huawei', 'h3c', 'nokia', 'alcatel', 'arista',
    'aruba', 'procurve', 'fortinet', 'extreme', 'mikrotik', 'palo alto',
    'paloalto', 'zyxel', 'ruckus', 'edge-core', 'quidway', 'omniswitch',
    'dell emc', 'dell networking',
)

# IPAM 关联通的线索类型 -> 展示文案。
MATCH_LABELS = {
    'mac': 'chassis MAC',
    'mgmt_ip': '管理 IP',
    'sys_name': '系统名',
}


def is_network_vendor(vendor: Any) -> bool:
    """IPAM 记录的厂商是否明显是网络设备厂商。"""
    text = str(vendor or '').strip().lower()
    if not text:
        return False
    return any(hint in text for hint in NETWORK_VENDOR_HINTS)


def parse_capabilities(value: Any) -> Set[str]:
    """把 capability（SNMP hex / CLI 文本）归一为类别集合。"""
    text = str(value or '').strip().lower()
    if not text:
        return set()
    hex_text = text[2:] if text.startswith('0x') else text
    if re.fullmatch(r'[0-9a-f]{2,}', hex_text) and len(hex_text) % 2 == 0:
        try:
            bits = int(hex_text, 16)
        except ValueError:
            bits = 0
        total = len(hex_text) * 4  # 每个 hex 字符 4 位
        found = {
            name for name, position in CAPABILITY_POSITIONS
            if position < total and bits & (1 << (total - 1 - position))
        }
        if found:
            return found
    found: Set[str] = set()
    padded = f' {text} '
    for word, name in CAPABILITY_WORDS:
        if re.search(rf'(?<![a-z]){re.escape(word)}(?![a-z])', padded):
            found.add(name)
    return found
