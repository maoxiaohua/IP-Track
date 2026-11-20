"""拓扑解析器：SNMP 索引/标识格式化、各厂商 LLDP/CDP/接口文本解析、模板回退。"""

from config.collection_strategy import TOPOLOGY_CLI_DEFAULTS
from services.cli_service import CLIService
from services.snmp_service import SNMPService


CISCO_LLDP = """
------------------------------------------------
Local Intf: GigabitEthernet1/0/1
Chassis id: aabb.ccdd.ee02
Port id: GigabitEthernet1/0/2
Port Description: uplink to core
System Name: SW2
System Description: Cisco IOS Software, C2960 Software
Time remaining: 95 seconds
------------------------------------------------
Local Intf: GigabitEthernet1/0/3
Chassis id: 0011.2233.4455
Port id: Gi0/3
System Name: SW3
IP: 10.0.0.3
"""

CISCO_CDP = """
-------------------------
Device ID: SW2
Entry address(es):
  IP address: 10.0.0.2
Platform: cisco WS-C2960,  Capabilities: Switch
Interface: GigabitEthernet1/0/1,  Port ID (outgoing port): GigabitEthernet1/0/2
Holdtime : 145 sec
"""

DELL_LLDP = """
Local Interface    Remote Device ID    Remote Port ID
Gi1/0/1            SW2                 Gi1/0/2
Te1/0/1            SW3                 Te1/0/1
"""

GENERIC_CDP = """
Device ID        Local Intrfce     Holdtme    Capability  Platform  Port ID
SW2              Gi1/0/1           150        S I         WS-C2960  Gi1/0/2
"""

CISCO_INTERFACES = """
Port      Name               Status       Vlan       Duplex  Speed Type
Gi1/0/1   uplink             connected    trunk      a-full  a-1000 10/100/1000BaseTX
Gi1/0/2                      notconnect   1          auto    auto   10/100/1000BaseTX
"""

NOKIA_INTERFACES = """
===============================================================================
Port          Admin Link  SFP  Cfg  LAG  Oper
------------------------------------------------------------------------------
1/1/1         Up    Yes   No   Up   1/1  Up
1/1/2         Up    No    -    Up   -    Down
"""

GENERIC_INTERFACES = """
Interface     Status    Speed
Ethernet1     up        1000 Mbps
Ethernet2     down      1000 Mbps
"""


def test_cisco_lldp_detail_parses_two_neighbors():
    entries = CLIService()._parse_cisco_lldp_neighbors(CISCO_LLDP)
    assert len(entries) == 2
    first = entries[0]
    assert first['protocol'] == 'lldp'
    assert first['local_port_id'] == 'GigabitEthernet1/0/1'
    assert first['remote_chassis_id'] == 'aa:bb:cc:dd:ee:02'
    assert first['remote_port_id'] == 'GigabitEthernet1/0/2'
    assert first['remote_sys_name'] == 'SW2'
    second = entries[1]
    assert second['remote_chassis_id'] == '00:11:22:33:44:55'
    assert second['remote_mgmt_addr'] == '10.0.0.3'
    assert second['remote_mgmt_addr_type'] == 'ipv4'


def test_cisco_lldp_capability_letters_are_normalized():
    output = """
Local Intf: TenGigabitEthernet1/0/1
Chassis id: e4f0.0428.7d01
Port id: GigabitEthernet1/0/1
System Name: PC-WIN10
System Capabilities: S
Enabled Capabilities: S
Local Intf: TenGigabitEthernet1/0/2
Chassis id: e4f0.0428.7d02
Port id: GigabitEthernet0/1
System Name: SW-CORE
System Capabilities: B,R
Enabled Capabilities: B,R
"""
    entries = CLIService()._parse_cisco_lldp_neighbors(output)
    assert entries[0]['capability'] == 'station'
    assert entries[1]['capability'] == 'bridge,router'


def test_cisco_lldp_capability_falls_back_to_enabled():
    output = """
Local Intf: GigabitEthernet1/0/9
Chassis id: 0011.2233.4455
System Name: PHONE1
Enabled Capabilities: T
"""
    entries = CLIService()._parse_cisco_lldp_neighbors(output)
    assert entries[0]['capability'] == 'phone'


def test_dell_detail_capability_long_words_are_kept():
    output = """
Remote Chassis ID: 00:11:22:33:44:55
Remote Port ID: Ethernet1/1
Remote System Name: SW-AGG
System Capabilities : Bridge, Router
Enabled Capabilities: Bridge, Router
"""
    entries = CLIService()._parse_lldp_detail_blocks(output)
    assert entries[0]['capability'] == 'bridge,router'


def test_generic_lldp_table_parses_dell_output():
    entries = CLIService()._parse_generic_lldp_table(DELL_LLDP)
    assert len(entries) == 2
    assert entries[0]['local_port_id'] == 'Gi1/0/1'
    assert entries[0]['remote_sys_name'] == 'SW2'
    assert entries[0]['remote_port_id'] == 'Gi1/0/2'


def test_cisco_cdp_detail_parses_ports_and_platform():
    entries = CLIService()._parse_cisco_cdp_neighbors(CISCO_CDP)
    assert len(entries) == 1
    entry = entries[0]
    assert entry['protocol'] == 'cdp'
    assert entry['remote_sys_name'] == 'SW2'
    assert entry['remote_mgmt_addr'] == '10.0.0.2'
    assert entry['local_port_id'] == 'GigabitEthernet1/0/1'
    assert entry['remote_port_id'] == 'GigabitEthernet1/0/2'
    assert entry['remote_sys_desc'] == 'cisco WS-C2960'


def test_generic_cdp_table_parses_short_format():
    entries = CLIService()._parse_generic_cdp_table(GENERIC_CDP)
    assert len(entries) == 1
    assert entries[0]['remote_sys_name'] == 'SW2'
    assert entries[0]['local_port_id'] == 'Gi1/0/1'
    assert entries[0]['remote_port_id'] == 'Gi1/0/2'


def test_cisco_interfaces_parse_status_and_speed():
    entries = CLIService()._parse_cisco_interfaces(CISCO_INTERFACES)
    assert len(entries) == 2
    assert entries[0]['if_name'] == 'Gi1/0/1'
    assert entries[0]['if_descr'] == 'uplink'
    assert entries[0]['oper_status'] == 'up'
    assert entries[0]['speed_mbps'] == 1000
    assert entries[1]['oper_status'] == 'down'
    assert entries[0]['if_index'] < 0


def test_nokia_interfaces_parse_link_column():
    entries = CLIService()._parse_nokia_interfaces(NOKIA_INTERFACES)
    assert len(entries) == 2
    assert entries[0]['if_name'] == '1/1/1'
    assert entries[0]['oper_status'] == 'up'
    assert entries[1]['oper_status'] == 'down'


def test_generic_interfaces_parse_status_and_speed():
    entries = CLIService()._parse_generic_interfaces(GENERIC_INTERFACES)
    assert len(entries) == 2
    assert entries[0]['oper_status'] == 'up'
    assert entries[0]['speed_mbps'] == 1000
    assert entries[1]['oper_status'] == 'down'


def test_lldp_identifier_formats_by_subtype():
    service = SNMPService()
    # subtype 4 = macAddress
    assert service._format_lldp_identifier(b'\xaa\xbb\xcc\xdd\xee\x02', 4) == 'aa:bb:cc:dd:ee:02'
    # subtype 5 = networkAddress：1 字节族 + IPv4 4 字节 / IPv6 16 字节
    assert service._format_lldp_identifier(b'\x01\x0a\x00\x00\x01', 5) == '10.0.0.1'
    ipv6 = bytes.fromhex('02' + '20010db8000000000000000000000001')
    assert service._format_lldp_identifier(ipv6, 5) == '2001:db8::1'
    # subtype 7 = locallyAssigned：按可打印文本
    assert service._format_lldp_identifier(b'sw-core-1', 7) == 'sw-core-1'
    # 不可打印且非已知子类型 -> hex，不猜
    assert service._format_lldp_identifier(b'\x00\x01\x02', 7) == '000102'
    assert service._format_lldp_identifier(None, 4) is None


def test_network_address_rejects_unknown_family_or_length():
    assert SNMPService._format_network_address(b'\x01\x0a\x00\x00\x01') == '10.0.0.1'
    assert SNMPService._format_network_address(b'\x02' + bytes(16)) == '::'
    assert SNMPService._format_network_address(b'\x03\x0a\x00\x00\x01') is None
    assert SNMPService._format_network_address(b'\x01\x0a\x00\x00') is None


def test_man_addr_from_variable_length_index():
    # lldpRemManAddrTable 索引里的地址是变长的，必须整体还原
    assert SNMPService._man_addr_from_index(1, ['10', '0', '0', '1']) == ('10.0.0.1', 'ipv4')
    ipv6_parts = [str(b) for b in bytes.fromhex('20010db8' + '00' * 11 + '01')]
    assert len(ipv6_parts) == 16
    assert SNMPService._man_addr_from_index(2, ipv6_parts) == ('2001:db8::1', 'ipv6')
    # 子类型与字节数不匹配时不做拼接
    assert SNMPService._man_addr_from_index(1, ipv6_parts) == (None, None)
    assert SNMPService._man_addr_from_index(2, ['1', '2', '3']) == (None, None)


def test_parser_map_exposes_topology_parsers_per_vendor():
    service = CLIService()
    assert service._get_parser('cisco_ios', 'lldp') == service._parse_cisco_lldp_neighbors
    assert service._get_parser('cisco_nxos', 'cdp') == service._parse_cisco_cdp_neighbors
    assert service._get_parser('dell_os10', 'lldp') == service._parse_generic_lldp_table
    assert service._get_parser('nokia_7250', 'interfaces') == service._parse_nokia_interfaces
    # 命令模板页宣传的两个别名必须与实际注册一致，否则手选后采集直接报「解析器不存在」。
    assert service._get_parser('nokia_sros', 'lldp') == service._parse_generic_lldp_table
    assert service._get_parser('nokia_sros', 'interfaces') == service._parse_nokia_interfaces
    assert service._get_parser('generic', 'lldp') == service._parse_generic_lldp_table
    assert service._get_parser('generic', 'cdp') == service._parse_generic_lldp_table
    assert service._get_parser('generic', 'interfaces') == service._parse_generic_interfaces
    # Dell / Nokia 没有 CDP；缺失必须返回 None，由调用方报 unsupported，而不是猜一个解析器。
    assert service._get_parser('dell_os10', 'cdp') is None
    assert service._get_parser('nokia_7220', 'cdp') is None
    assert service._get_parser('nokia_sros', 'cdp') is None


def test_builtin_topology_defaults_cover_all_supported_device_types():
    for device_type in ('nokia_srl', 'nokia_sros', 'dell_force10', 'dell_os10',
                        'cisco_ios', 'cisco_nxos', 'juniper_junos',
                        'arista_eos', 'hp_procurve', 'huawei'):
        assert device_type in TOPOLOGY_CLI_DEFAULTS, device_type
    cisco = TOPOLOGY_CLI_DEFAULTS['cisco_ios']
    assert cisco['lldp_enabled'] is True and cisco['lldp_command']
    assert cisco['cdp_enabled'] is True and cisco['cdp_command']
    assert cisco['interfaces_enabled'] is True and cisco['interfaces_command']
    # CDP 是 Cisco 私有协议：非 Cisco 设备必须默认关闭，避免每轮采集都失败
    assert TOPOLOGY_CLI_DEFAULTS['nokia_srl']['cdp_command'] is None
    assert TOPOLOGY_CLI_DEFAULTS['nokia_srl']['cdp_enabled'] is False


# ---------------------------------------------------------------------------
# 真机取证样本（2026-11 实测）：
# - Nokia SR Linux `show system lldp neighbor` / `show interface brief` 是 `|` 框线表
# - Dell OS10 / FTOS 不支持 `show lldp remote-system`，只有 `show lldp neighbors detail`
# ---------------------------------------------------------------------------

SRLINUX_LLDP = """
  +---------------+-------------------+-------------------------------------------------+---------------------+------------------------+----------------------+----------------+
  |     Name      |     Neighbor      |              Neighbor System Name               | Neighbor Chassis ID | Neighbor First Message | Neighbor Last Update | Neighbor Port  |
  +===============+===================+=================================================+=====================+========================+======================+================+
  | ethernet-1/52 | CC:48:3A:F2:02:5A | CNHZ-L3-DXB2F-QC9G9-1-U17-Hubroom1-S4148-RF-SW1 | CC:48:3A:F2:02:5A   | 2 days ago             | 2 seconds ago        | ethernet1/1/48 |
  +---------------+-------------------+-------------------------------------------------+---------------------+------------------------+----------------------+----------------+
"""

SRLINUX_INTERFACES = """
+---------------------+-------------+------------+-------+-------+
|        Port         | Admin State | Oper State | Speed | Type  |
+=====================+=============+============+=======+=======+
| ethernet-1/1        | enable      | down       | 1G    |       |
| ethernet-1/2        | enable      | up         | 10M   |       |
| ethernet-1/49       | enable      | up         | 100G  |       |
+---------------------+-------------+------------+-------+-------+
"""

DELL_OS10_LLDP_DETAIL = """
Remote Chassis ID Subtype: Mac address (4)
Remote Chassis ID: ac:8f:f8:3e:9d:7d
Remote Port Subtype: Interface name (5)
Remote Port ID: ethernet-1/51
Remote Port Description: Not Advertised
Local Port ID: ethernet1/1/1
Remote TTL: 120
Remote System Name: CNHZ-L3-DXB2F-2PA04-7220D1-Mtor1
Remote System Desc: SRLinux-v24.7.2 CNHZ-L3-DXB2F-2PA04-7220D1-Mtor1
---------------------------------------------------------------------------

Remote Chassis ID Subtype: Mac address (4)
Remote Chassis ID: ac:8f:f8:3e:a3:7d
Remote Port ID: ethernet-1/51
Local Port ID: ethernet1/1/2
Remote System Name: CNHZ-L3-DXB2F-2PA12-7220D1-Mtor1
---------------------------------------------------------------------------
"""

DELL_FTOS_LLDP_DETAIL = """
========================================================================
 Local Interface Gi 1/17 has 1 neighbor
  Total Frames Out: 5510
  The neighbors are given below:
    Remote Chassis ID Subtype: Mac address (4)
    Remote Chassis ID:  00:0e:c6:66:4d:e7
    Remote Port Subtype:  Mac address (3)
    Remote Port ID:  00:0e:c6:66:4d:e7
    Local Port ID: GigabitEthernet 1/17
    Remote System Name:  ToR-SW1
    MAC PHY Configuration:
      Auto-neg supported: 1
   ---------------------------------------------------------------------------
========================================================================
 Local Interface Gi 1/18 has 1 neighbor
    Remote Chassis ID:  00:0e:c6:66:4d:e8
    Remote Port ID:  Te 1/1
    Local Port ID: GigabitEthernet 1/18
    Remote System Name:  ToR-SW2
   ---------------------------------------------------------------------------
"""


def test_srlinux_lldp_pipe_table_parses_neighbor_columns():
    entries = CLIService()._parse_srlinux_lldp_neighbors(SRLINUX_LLDP)
    assert len(entries) == 1
    entry = entries[0]
    assert entry['local_port_id'] == 'ethernet-1/52'
    assert entry['remote_chassis_id'] == 'cc:48:3a:f2:02:5a'
    assert entry['remote_port_id'] == 'ethernet1/1/48'
    assert entry['remote_sys_name'] == 'CNHZ-L3-DXB2F-QC9G9-1-U17-Hubroom1-S4148-RF-SW1'


def test_srlinux_interfaces_pipe_table_parses_state_and_speed():
    entries = CLIService()._parse_srlinux_interfaces(SRLINUX_INTERFACES)
    assert len(entries) == 3
    assert entries[0]['if_name'] == 'ethernet-1/1'
    assert entries[0]['oper_status'] == 'down'
    assert entries[0]['admin_status'] == 'up'
    assert entries[0]['speed_mbps'] == 1000
    assert entries[1]['oper_status'] == 'up'
    assert entries[1]['speed_mbps'] == 10
    assert entries[2]['speed_mbps'] == 100000


def test_dell_os10_lldp_detail_parses_blocks():
    entries = CLIService()._parse_generic_lldp_table(DELL_OS10_LLDP_DETAIL)
    assert len(entries) == 2
    assert entries[0]['local_port_id'] == 'ethernet1/1/1'
    assert entries[0]['remote_chassis_id'] == 'ac:8f:f8:3e:9d:7d'
    assert entries[0]['remote_port_id'] == 'ethernet-1/51'
    assert entries[0]['remote_sys_name'] == 'CNHZ-L3-DXB2F-2PA04-7220D1-Mtor1'
    # 设备广告的 "Not Advertised" 不是端口描述，不能当事实存。
    assert entries[0]['remote_port_desc'] is None


def test_dell_ftos_lldp_detail_parses_indented_blocks():
    entries = CLIService()._parse_generic_lldp_table(DELL_FTOS_LLDP_DETAIL)
    assert len(entries) == 2
    assert entries[0]['local_port_id'] == 'GigabitEthernet 1/17'
    assert entries[0]['remote_chassis_id'] == '00:0e:c6:66:4d:e7'
    assert entries[0]['remote_sys_name'] == 'ToR-SW1'
    assert entries[1]['local_port_id'] == 'GigabitEthernet 1/18'
    assert entries[1]['remote_sys_name'] == 'ToR-SW2'


def test_generic_parser_is_fallback_when_vendor_parser_misses_output():
    # 登记为 cisco 的设备实际输出 Dell FTOS 块格式：厂商解析器 0 条，通用解析器可识别，
    # _collect_topology_facts_cli 因此会回退到通用解析器而不是直接报解析失败。
    service = CLIService()
    assert service._parse_cisco_lldp_neighbors(DELL_FTOS_LLDP_DETAIL) == []
    assert len(service._parse_generic_lldp_table(DELL_FTOS_LLDP_DETAIL)) == 2


def test_parser_map_uses_dedicated_srlinux_parsers_and_dell_detail_command():
    service = CLIService()
    assert service._get_parser('nokia_7220', 'lldp') == service._parse_srlinux_lldp_neighbors
    assert service._get_parser('nokia_7220', 'interfaces') == service._parse_srlinux_interfaces
    # Dell 真机只接受 detail 命令；parser_type 不变，仍走通用解析器（已兼容 detail）。
    for device_type in ('dell_os10', 'dell_force10'):
        assert TOPOLOGY_CLI_DEFAULTS[device_type]['lldp_command'] == 'show lldp neighbors detail'


DELL_FTOS_INTERFACES = """
Port                 Description  Status Speed        Duplex Vlan
Gi 1/1                            Up     1000 Mbit    Full   214
Gi 1/2                            Down   Auto         Auto   214
Te 1/50              CNHZ-L3-DXB  Up     10000 Mbit   Full   214
"""


def test_dell_ftos_interfaces_split_port_name_is_parsed():
    # FTOS 把接口名拆成 "Gi 1/1" 两列，不能因为含空格就丢弃整行。
    entries = CLIService()._parse_generic_interfaces(DELL_FTOS_INTERFACES)
    assert [e['if_name'] for e in entries] == ['Gi1/1', 'Gi1/2', 'Te1/50']
    assert entries[0]['oper_status'] == 'up'
    assert entries[0]['speed_mbps'] == 1000
    assert entries[2]['speed_mbps'] == 10000
