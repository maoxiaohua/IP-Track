"""未纳管邻居设备分类器 + 跨厂商端口键归一 + IPAM 档案关联。

分类器是纯函数：同一份判定同时用于拓扑节点与端口↔设备联动，
这里锁住判定优先级与阈值，避免两处结论漂移。
"""

import pytest

from services.device_classifier import MIN_CONFIDENCE, classify_unknown
from services.ipam_device_hints import _norm_ip, _norm_mac, lookup_ipam_profiles
from services.lldp_signals import is_network_vendor
from services.port_analysis_service import port_analysis_service


def classify(**kwargs):
    return classify_unknown(**kwargs)


# ---------- capability 权威 ----------

def test_bridge_capability_is_switch():
    result = classify(capabilities={'bridge'})
    assert result.device_class == 'switch'
    assert result.confidence == 95


def test_router_capability_is_router():
    result = classify(capabilities={'router'})
    assert result.device_class == 'router'


def test_repeater_capability_is_hub_kept_as_network_device():
    # HUB 属于网络设备，必须保留而不是被当成终端。
    result = classify(capabilities={'repeater'})
    assert result.device_class == 'hub'
    assert result.confidence == 90


def test_host_capability_is_host():
    result = classify(capabilities={'host'})
    assert result.device_class == 'host'


def test_capability_beats_conflicting_text():
    # capability 是权威信号，服务器描述不能把它翻成 host。
    result = classify(capabilities={'bridge'}, sys_desc='Windows Server 2019')
    assert result.device_class == 'switch'
    assert result.confidence == 95


# ---------- 文本信号 ----------

def test_server_hint_is_host():
    result = classify(sys_desc='Windows Server 2019', mac_count=2)
    assert result.device_class == 'host'


def test_switch_system_hint_is_switch():
    # 单 MAC 接入口 + 交换机操作系统标识（plan 中 access:1mac + Dell 词）。
    result = classify(sys_desc='Dell EMC Networking OS10', mac_count=1)
    assert result.device_class == 'switch'


def test_placeholder_text_is_treated_as_empty():
    result = classify(sys_name='Not Advertised', sys_desc='-')
    assert result.device_class == 'unknown'
    assert all('Not Advertised' not in reason for reason in result.reasons)


# ---------- 结构性证据加权 ----------

def test_dot1q_chassis_is_normalized_in_reasons():
    result = classify(chassis_id='0011.2233.4455')
    assert any('00:11:22:33:44:55' in reason for reason in result.reasons)


def test_many_macs_plus_sys_name_is_enough_for_switch():
    result = classify(mac_count=12, sys_name='edge-sw')
    assert result.device_class == 'switch'
    assert result.confidence >= MIN_CONFIDENCE


def test_self_chassis_learned_alone_stays_unknown():
    # 只证明对端是桥设备，不能单独排除 PC。
    result = classify(self_chassis_learned=True)
    assert result.device_class == 'unknown'


def test_no_evidence_is_unknown():
    result = classify()
    assert result.device_class == 'unknown'
    assert result.reasons == ('无可用判定证据',)


def test_confidence_is_monotonic_with_mac_count():
    none = classify(mac_count=0)
    few = classify(mac_count=2)
    many = classify(mac_count=50)
    assert none.confidence <= few.confidence <= many.confidence


# ---------- 跨厂商端口键归一 ----------

def test_normalize_port_key_merges_vendor_prefixes():
    normalize = port_analysis_service.normalize_port_key
    assert normalize('GigabitEthernet 1/1') == 'gi1/1'
    assert normalize('GE1/0/1') == 'gi1/0/1'
    assert normalize('ethernet-1/15') == 'et1/15'
    assert normalize('ethernet1/1/5') == 'et1/1/5'
    assert normalize('fortyGigE 1/31/1') == 'fo1/31/1'
    assert normalize('TenGigabitEthernet1/1') == 'te1/1'


def test_normalize_port_key_ignores_non_physical_ports():
    normalize = port_analysis_service.normalize_port_key
    assert normalize('Vlan100') == ''
    assert normalize('Loopback0') == ''
    assert normalize('cpu') == ''


# ---------- IPAM 档案补充依据 ----------

def test_ipam_windows_profile_is_host():
    result = classify(os_type='windows', ipam_matched_by='mac')
    assert result.device_class == 'host'
    assert result.confidence == 85
    assert any('IPAM 档案' in reason and 'chassis MAC' in reason
               for reason in result.reasons)


def test_ipam_linux_and_macos_profiles_are_host():
    assert classify(os_type='linux').device_class == 'host'
    assert classify(os_type='macos').device_class == 'host'


def test_ipam_network_os_is_switch():
    result = classify(os_type='network', ipam_matched_by='sys_name')
    assert result.device_class == 'switch'
    assert result.confidence == 75


def test_network_vendor_discredits_wrong_os_type():
    # 实测存在 Cisco 交换机在 IPAM 里被录成 linux，厂商为网络厂商时不得判 host。
    result = classify(os_type='linux', ipam_vendor='Cisco')
    assert result.device_class == 'unknown'
    assert any('不采信' in reason for reason in result.reasons)


def test_ipam_os_does_not_override_capability():
    result = classify(capabilities={'bridge'}, os_type='windows')
    assert result.device_class == 'switch'
    assert result.confidence == 95


def test_ipam_os_does_not_override_switch_text_hint():
    result = classify(sys_desc='Dell EMC Networking OS10', os_type='windows')
    assert result.device_class == 'switch'
    assert result.confidence == 80


def test_unknown_ipam_os_only_adds_reason():
    result = classify(os_type='other', mac_count=1)
    assert result.device_class == 'unknown'
    assert any('os_type=other' in reason for reason in result.reasons)


def test_norm_mac_accepts_all_vendor_formats():
    expected = '00:11:22:33:44:55'
    assert _norm_mac('00:11:22:33:44:55') == expected
    assert _norm_mac('00-11-22-33-44-55') == expected
    assert _norm_mac('0011.2233.4455') == expected
    assert _norm_mac('-') is None
    assert _norm_mac('not a mac') is None


def test_norm_ip_rejects_invalid_values():
    assert _norm_ip('10.0.0.1') == '10.0.0.1'
    assert _norm_ip('10.0.0.1/32') == '10.0.0.1'
    assert _norm_ip('0.0.0.0') == '0.0.0.0'
    assert _norm_ip('Not Advertised') is None
    assert _norm_ip('') is None


def test_is_network_vendor():
    assert is_network_vendor('Cisco Systems, Inc.') is True
    assert is_network_vendor('HUAWEI') is True
    assert is_network_vendor('Microsoft Corporation') is False
    assert is_network_vendor(None) is False


# ---------- IPAM 关联查询（假 DB，验证匹配优先级） ----------

def _row(ip=None, hostname=None, mac=None, os_type=None, vendor=None):
    from types import SimpleNamespace
    return SimpleNamespace(ip=ip, hostname=hostname, mac=mac,
                           os_type=os_type, vendor=vendor)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    """按 SQL 里的过滤列名筛选行，模拟 ip_addresses / arp_table 两次查询。"""

    def __init__(self, ip_rows=(), arp_rows=()):
        self.ip_rows = list(ip_rows)
        self.arp_rows = list(arp_rows)
        self.queries = []

    async def execute(self, statement, params=None):
        sql = ' '.join(str(statement).split())
        keys = set(params.get('keys') or [])
        self.queries.append(sql)
        if 'arp_table' in sql:
            return _FakeResult([r for r in self.arp_rows if r.mac in keys])
        if 'WHERE lower(hostname)' in sql:
            return _FakeResult([r for r in self.ip_rows if r.hostname in keys])
        if 'WHERE mac_address' in sql:
            return _FakeResult([r for r in self.ip_rows if r.mac in keys])
        return _FakeResult([r for r in self.ip_rows if r.ip in keys])


@pytest.mark.asyncio
async def test_lookup_matches_by_mac_first():
    db = _FakeDB(ip_rows=[_row(ip='10.0.0.9', hostname='pc-9',
                               mac='00:11:22:33:44:55', os_type='windows')])
    result = await lookup_ipam_profiles(db, [{
        'key': 'n1', 'mgmt_ip': '10.0.0.10',
        'sys_name': 'pc-9', 'chassis_id': '0011.2233.4455',
    }])
    assert result['n1']['matched_by'] == 'mac'
    assert result['n1']['os_type'] == 'windows'


@pytest.mark.asyncio
async def test_lookup_falls_back_to_mgmt_ip_then_sys_name():
    db = _FakeDB(ip_rows=[
        _row(ip='10.0.0.1', hostname='sw-a', os_type='network'),
        _row(ip='10.0.0.2', hostname='pc-b', os_type='windows'),
    ])
    result = await lookup_ipam_profiles(db, [
        {'key': 'a', 'mgmt_ip': '10.0.0.1', 'sys_name': None, 'chassis_id': None},
        {'key': 'b', 'mgmt_ip': 'Not Advertised', 'sys_name': 'PC-B', 'chassis_id': '-'},
    ])
    assert result['a']['matched_by'] == 'mgmt_ip'
    assert result['b']['matched_by'] == 'sys_name'
    assert result['b']['os_type'] == 'windows'


@pytest.mark.asyncio
async def test_lookup_uses_arp_table_when_profile_has_no_mac():
    db = _FakeDB(
        ip_rows=[_row(ip='10.0.0.20', hostname='pc-20', os_type='windows')],
        arp_rows=[_row(ip='10.0.0.20', mac='aa:bb:cc:dd:ee:ff')],
    )
    result = await lookup_ipam_profiles(db, [{
        'key': 'x', 'mgmt_ip': None, 'sys_name': None,
        'chassis_id': 'aa:bb:cc:dd:ee:ff',
    }])
    assert result['x']['matched_by'] == 'mac'
    assert result['x']['hostname'] == 'pc-20'


@pytest.mark.asyncio
async def test_lookup_returns_empty_without_probes():
    db = _FakeDB()
    assert await lookup_ipam_profiles(db, []) == {}
    assert db.queries == []
