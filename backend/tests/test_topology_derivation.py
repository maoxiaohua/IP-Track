"""拓扑推导：身份解析、双向/单向配对、冲突、自环、stale、LAG 折叠、未知节点。"""

from types import SimpleNamespace

from services.topology_service import (
    _build_identity_index,
    _compute_links,
    _device_class,
    _parse_capabilities,
    _unknown_node_key,
)


def make_switch(switch_id, name=None, ip='10.0.0.1', sys_name=None,
                chassis_id=None, bridge_mac=None, vendor='cisco', status=None):
    return SimpleNamespace(
        id=switch_id,
        name=name or f'sw{switch_id}',
        ip_address=ip,
        sys_name=sys_name,
        chassis_id=chassis_id,
        bridge_mac=bridge_mac,
        vendor=vendor,
        last_topology_collection_status=status,
    )


def make_if(switch_id, if_index, if_name, lag_key=None):
    return SimpleNamespace(
        switch_id=switch_id,
        if_index=if_index,
        if_name=if_name,
        if_alias=None,
        lag_key=lag_key,
    )


def make_fact(switch_id, local_port, remote_port, protocol='lldp',
              remote_sys_name=None, remote_chassis_id=None, remote_mgmt_addr=None,
              remote_port_desc=None, remote_sys_desc=None):
    return SimpleNamespace(
        switch_id=switch_id,
        protocol=protocol,
        local_if_index=None,
        local_port_id=local_port,
        local_port_desc=None,
        remote_chassis_id=remote_chassis_id,
        remote_port_id=remote_port,
        remote_port_desc=remote_port_desc,
        remote_sys_name=remote_sys_name,
        remote_sys_desc=remote_sys_desc,
        remote_mgmt_addr=remote_mgmt_addr,
        remote_mgmt_addr_type=None,
        ttl=None,
        capability=None,
    )


def two_switches():
    return [
        make_switch(1, name='sw1', ip='10.0.0.1', sys_name='SW1'),
        make_switch(2, name='sw2', ip='10.0.0.2', sys_name='SW2'),
    ]


def paired_interfaces():
    return [
        make_if(1, 1, 'GigabitEthernet1/0/1'),
        make_if(2, 1, 'GigabitEthernet1/0/1'),
    ]


def test_bidirectional_facts_become_confirmed_link():
    rows, fresh, folded = _compute_links(
        two_switches(),
        [
            make_fact(1, 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/1', remote_sys_name='SW2'),
            make_fact(2, 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/1', remote_sys_name='SW1'),
        ],
        paired_interfaces(),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row['status'] == 'confirmed'
    assert row['confidence'] == 90
    assert row['evidence'] == 'lldp'
    assert row['a_switch_id'] == 1 and row['b_switch_id'] == 2
    assert folded == 0
    assert list(fresh) == [row['link_key']]


def test_both_protocols_raise_confidence_to_100():
    rows, _, _ = _compute_links(
        two_switches(),
        [
            make_fact(1, 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/1', 'lldp', remote_sys_name='SW2'),
            make_fact(2, 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/1', 'lldp', remote_sys_name='SW1'),
            make_fact(1, 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/1', 'cdp', remote_sys_name='SW2'),
            make_fact(2, 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/1', 'cdp', remote_sys_name='SW1'),
        ],
        paired_interfaces(),
    )
    assert len(rows) == 1
    assert rows[0]['status'] == 'confirmed'
    assert rows[0]['confidence'] == 100
    assert rows[0]['evidence'] == 'both'


def test_one_sided_between_two_managed_switches():
    rows, _, _ = _compute_links(
        two_switches(),
        [make_fact(1, 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/1', remote_sys_name='SW2')],
        paired_interfaces(),
    )
    assert len(rows) == 1
    assert rows[0]['status'] == 'one_sided'
    assert rows[0]['confidence'] == 70


def test_one_sided_to_unmanaged_neighbor_is_unknown_node():
    rows, _, _ = _compute_links(
        two_switches(),
        [make_fact(1, 'GigabitEthernet1/0/1', 'Gi0/1', remote_sys_name='UNMANAGED')],
        paired_interfaces(),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row['status'] == 'one_sided'
    assert row['confidence'] == 60
    assert row['ep_b']['kind'] == 'unknown'
    assert row['ep_b']['node_key'] == 'name:unmanaged'


def test_same_port_with_two_neighbors_is_conflict_not_guess():
    switches = two_switches() + [make_switch(3, name='sw3', ip='10.0.0.3', sys_name='SW3')]
    rows, _, _ = _compute_links(
        switches,
        [
            make_fact(1, 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/1', remote_sys_name='SW2'),
            make_fact(1, 'GigabitEthernet1/0/1', 'GigabitEthernet2/0/1', remote_sys_name='SW3'),
        ],
        [
            make_if(1, 1, 'GigabitEthernet1/0/1'),
            make_if(2, 1, 'GigabitEthernet1/0/1'),
            make_if(3, 1, 'GigabitEthernet2/0/1'),
        ],
    )
    assert len(rows) == 2
    for row in rows:
        assert row['status'] == 'unresolved'
        assert row['confidence'] == 40
        assert 'multiple neighbors' in row['conflict_reason']


def test_self_loop_on_same_port_is_dropped():
    rows, _, _ = _compute_links(
        two_switches(),
        [make_fact(1, 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/1', remote_sys_name='SW1')],
        paired_interfaces(),
    )
    assert rows == []


def test_self_loop_on_different_port_is_flagged():
    rows, _, _ = _compute_links(
        two_switches(),
        [make_fact(1, 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/2', remote_sys_name='SW1')],
        paired_interfaces() + [make_if(1, 2, 'GigabitEthernet1/0/2')],
    )
    assert len(rows) == 1
    assert rows[0]['status'] == 'unresolved'
    assert rows[0]['confidence'] == 40
    assert 'self loop' in rows[0]['conflict_reason']
    assert rows[0]['a_switch_id'] == rows[0]['b_switch_id'] == 1


def test_failed_collection_marks_link_stale_instead_of_deleting():
    switches = two_switches()
    switches[1] = make_switch(2, name='sw2', ip='10.0.0.2', sys_name='SW2', status='failed')
    rows, _, _ = _compute_links(
        switches,
        [
            make_fact(1, 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/1', remote_sys_name='SW2'),
            make_fact(2, 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/1', remote_sys_name='SW1'),
        ],
        paired_interfaces(),
    )
    assert len(rows) == 1
    assert rows[0]['status'] == 'stale'
    assert rows[0]['conflict_reason'] == 'no fresh collection for one or both endpoints'


def test_lag_members_are_folded_into_one_link():
    rows, _, folded = _compute_links(
        two_switches(),
        [
            make_fact(1, 'Ethernet1', 'Ethernet1', remote_sys_name='SW2'),
            make_fact(2, 'Ethernet1', 'Ethernet1', remote_sys_name='SW1'),
            make_fact(1, 'Ethernet2', 'Ethernet2', remote_sys_name='SW2'),
            make_fact(2, 'Ethernet2', 'Ethernet2', remote_sys_name='SW1'),
        ],
        [
            make_if(1, 1, 'Ethernet1', lag_key='ae0'),
            make_if(1, 2, 'Ethernet2', lag_key='ae0'),
            make_if(2, 1, 'Ethernet1', lag_key='ae0'),
            make_if(2, 2, 'Ethernet2', lag_key='ae0'),
        ],
    )
    assert folded == 1
    assert len(rows) == 1
    assert rows[0]['is_lag'] is True
    assert rows[0]['status'] == 'confirmed'


def test_duplicate_sys_name_does_not_merge_switches():
    switches = [
        make_switch(1, name='sw1', ip='10.0.0.1', sys_name='DUP'),
        make_switch(2, name='sw2', ip='10.0.0.2', sys_name='DUP'),
    ]
    ip_index, name_index = _build_identity_index(switches)
    assert name_index['dup'] is None
    rows, _, _ = _compute_links(
        switches,
        [make_fact(1, 'GigabitEthernet1/0/1', 'Gi0/1', remote_sys_name='DUP')],
        [make_if(1, 1, 'GigabitEthernet1/0/1')],
    )
    assert len(rows) == 1
    # 有歧义 -> 不合并，落到未知节点
    assert rows[0]['ep_b']['kind'] == 'unknown'


def test_identity_index_prefers_ip_then_chassis_mac_then_sysname():
    switches = two_switches()
    switches[1].chassis_id = 'aabb.ccdd.ee02'
    ip_index, name_index = _build_identity_index(switches)
    assert ip_index == {'10.0.0.1': 1, '10.0.0.2': 2}
    assert name_index['aa:bb:cc:dd:ee:02'] == 2
    assert name_index['sw2'] == 2


def test_unknown_node_key_priority():
    assert _unknown_node_key(make_fact(
        1, 'g1', 'r1', remote_mgmt_addr='10.0.0.9',
        remote_chassis_id='aabb.ccdd.ee09', remote_sys_name='sw9',
    )) == 'ip:10.0.0.9'
    assert _unknown_node_key(make_fact(
        1, 'g1', 'r1', remote_mgmt_addr='127.0.0.1',
        remote_chassis_id='aabb.ccdd.ee09', remote_sys_name='sw9',
    )) == 'mac:aa:bb:cc:dd:ee:09'
    assert _unknown_node_key(make_fact(1, 'g1', 'r1', remote_sys_name='SW9')) == 'name:sw9'
    assert _unknown_node_key(make_fact(1, 'g1', 'r1')) is None


def test_parse_capabilities_hex_one_and_two_octets():
    # BITS 从最高位编号：bridge=position 2。
    assert _parse_capabilities('20') == {'bridge'}
    assert _parse_capabilities('2000') == {'bridge'}
    # router=position 4，1 字节 0x08 / 2 字节 0x0800。
    assert _parse_capabilities('08') == {'router'}
    assert _parse_capabilities('0800') == {'router'}
    # host(station)=position 7，1 字节 0x01 / 2 字节 0x0100。
    assert _parse_capabilities('01') == {'host'}
    assert _parse_capabilities('0100') == {'host'}


def test_parse_capabilities_text_and_empty():
    assert _parse_capabilities('Bridge Router') == {'bridge', 'router'}
    assert _parse_capabilities('repeater,bridge,router') == {'repeater', 'bridge', 'router'}
    assert _parse_capabilities(None) == set()
    assert _parse_capabilities('Not Advertised') == set()


def test_device_class_prefers_capability():
    assert _device_class({'bridge'}) == 'switch'
    # 三层交换机同时报 bridge + router，按交换机归类；只有 router 才算路由器。
    assert _device_class({'router', 'bridge'}) == 'switch'
    assert _device_class({'router'}) == 'router'
    assert _device_class({'repeater'}) == 'hub'
    assert _device_class({'host'}) == 'host'


def test_device_class_text_fallback():
    assert _device_class(set(), 'Windows 10 Pro') == 'host'
    assert _device_class(set(), 'Cisco IOS Software, C3560') == 'switch'
    # NOKIA SR Linux 不是 Linux 主机，必须判成交换机。
    assert _device_class(set(), 'SRLinux-v24.7.2') == 'switch'
    assert _device_class(set(), 'cnhzrf0267') == 'unknown'
