"""拓扑共用的纯函数：LAG 归一、MAC 归一、合成 ifIndex、端口名判定。"""

from services.topology_utils import (
    looks_like_port,
    normalize_lag_key,
    normalize_mac,
    synthetic_if_index,
)


def test_normalize_lag_key_uses_one_spelling_for_same_lag():
    assert normalize_lag_key('ae0') == 'ae0'
    assert normalize_lag_key('port-channel 10') == 'portchannel10'
    assert normalize_lag_key('Port-Channel10') == 'portchannel10'
    assert normalize_lag_key('po10') == 'portchannel10'
    assert normalize_lag_key('Bundle-Ether10') == 'bundleether10'


def test_normalize_lag_key_ignores_non_lag_ports():
    assert normalize_lag_key('GigabitEthernet1/0/1') is None
    assert normalize_lag_key('ethernet 1/1') is None
    assert normalize_lag_key('') is None
    assert normalize_lag_key(None) is None


def test_normalize_mac_accepts_dot_dash_and_colon_forms():
    expected = '00:11:22:33:44:55'
    assert normalize_mac('0011.2233.4455') == expected
    assert normalize_mac('00-11-22-33-44-55') == expected
    assert normalize_mac('00:11:22:33:44:55') == expected
    assert normalize_mac('AA:BB:CC:DD:EE:FF') == 'aa:bb:cc:dd:ee:ff'


def test_normalize_mac_keeps_non_mac_text_lowercased():
    assert normalize_mac('node-1') == 'node-1'
    assert normalize_mac(None) is None


def test_synthetic_if_index_is_stable_and_negative():
    first = synthetic_if_index('GigabitEthernet1/0/1')
    second = synthetic_if_index('gigabitethernet1/0/1')
    assert first == second
    assert first < 0
    # 不会和 SNMP 正数 ifIndex 冲突
    assert synthetic_if_index('TenGigabitEthernet1/0/2') != first


def test_looks_like_port_covers_vendor_spellings():
    for name in ('1/1/1', '1/1/c1/1', 'Gi1/0/1', 'ae1', 'lag-1', 'Port-Channel10', 'xe-0/0/0.0', 'Ethernet1/1'):
        assert looks_like_port(name), name


def test_looks_like_port_rejects_addresses_and_headers():
    for name in ('', None, '10.0.0.1', 'fe80::1', 'Local Intf', 'Chassis'):
        assert not looks_like_port(name), name
