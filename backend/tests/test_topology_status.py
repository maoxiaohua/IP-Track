"""拓扑采集状态：模板已明确不适用的协议（如非 Cisco 的 CDP）不应拖累整台设备。"""

import asyncio
from types import SimpleNamespace

from services import topology_service
from services.cli_service import CLIService


def test_unsupported_dataset_skips_snmp_and_cli():
    """协议不适用时直接 unsupported，不再探测 SNMP（否则错误会被判成采集失败）。"""
    calls = []

    async def snmp_fn(*args, **kwargs):
        calls.append('snmp')
        return {'status': 'error', 'entries': [], 'message': 'Wrong SNMP PDU digest'}

    def cli_fn(*args, **kwargs):
        calls.append('cli')
        return {'status': 'unsupported', 'entries': [], 'message': 'cdp CLI not enabled'}

    result = asyncio.run(topology_service._run_dataset(
        SimpleNamespace(ip_address='192.0.2.1'), 'cdp', snmp_fn, cli_fn,
        {'community': 'public'}, {'username': 'admin'}, None, None, False,
    ))

    assert result['status'] == 'unsupported'
    assert calls == []


def test_unsupported_dataset_keeps_unsupported_when_supported_unknown():
    """supported=None 时必须保持原逻辑：SNMP error + CLI unsupported 仍是 error。"""
    async def snmp_fn(*args, **kwargs):
        return {'status': 'error', 'entries': [], 'message': 'Wrong SNMP PDU digest'}

    def cli_fn(*args, **kwargs):
        return {'status': 'unsupported', 'entries': [], 'message': 'cdp CLI not enabled'}

    result = asyncio.run(topology_service._run_dataset(
        SimpleNamespace(ip_address='192.0.2.1'), 'cdp', snmp_fn, cli_fn,
        {'community': 'public'}, {'username': 'admin'}, None, None, None,
    ))

    assert result['status'] == 'error'


def test_cdp_declared_unsupported_for_non_cisco_device_types():
    service = CLIService()
    for vendor, model in (('Dell', 'S3148'), ('Dell', 'S4148F-ON'), ('alcatel', '7220 IXR-D2')):
        assert service.topology_dataset_supported(
            {'vendor': vendor, 'model': model, 'name': ''}, None, 'cdp'
        ) is False
    # Cisco 的 CDP 必须保持可用，不能被误关。
    assert service.topology_dataset_supported(
        {'vendor': 'Cisco', 'model': 'C9300', 'name': ''}, None, 'cdp'
    ) is True


def test_empty_snmp_ok_falls_back_to_cli():
    """SNMP 报「支持但 0 条」时不能短路 CLI：实测 Cisco 的 SNMP remote 表为空但 CLI 有邻居。"""
    async def snmp_fn(*args, **kwargs):
        return {'status': 'ok', 'entries': [], 'method': 'snmp', 'message': None}

    def cli_fn(*args, **kwargs):
        return {'status': 'ok', 'entries': [{'protocol': 'lldp'}], 'message': None}

    result = asyncio.run(topology_service._run_dataset(
        SimpleNamespace(ip_address='192.0.2.1'), 'lldp', snmp_fn, cli_fn,
        {'community': 'public'}, {'username': 'admin'}, None, None,
    ))

    assert result['status'] == 'ok'
    assert result['method'] == 'cli'
    assert len(result['entries']) == 1


def test_empty_snmp_ok_kept_when_cli_fails():
    """CLI 交叉校验失败时，SNMP 的「支持但无邻居」仍是成功，不能改判 error 清空旧事实。"""
    async def snmp_fn(*args, **kwargs):
        return {'status': 'ok', 'entries': [], 'method': 'snmp', 'message': None}

    def cli_fn(*args, **kwargs):
        raise RuntimeError('ssh timeout')

    result = asyncio.run(topology_service._run_dataset(
        SimpleNamespace(ip_address='192.0.2.1'), 'lldp', snmp_fn, cli_fn,
        {'community': 'public'}, {'username': 'admin'}, None, None,
    ))

    assert result['status'] == 'ok'
    assert result['method'] == 'snmp'
    assert result['entries'] == []


def test_non_empty_snmp_ok_skips_cli():
    """SNMP 有数据时保持原行为，不再多建一条 SSH 连接。"""
    calls = []

    async def snmp_fn(*args, **kwargs):
        return {'status': 'ok', 'entries': [{'protocol': 'lldp'}], 'method': 'snmp', 'message': None}

    def cli_fn(*args, **kwargs):
        calls.append('cli')
        return {'status': 'ok', 'entries': [], 'message': None}

    result = asyncio.run(topology_service._run_dataset(
        SimpleNamespace(ip_address='192.0.2.1'), 'lldp', snmp_fn, cli_fn,
        {'community': 'public'}, {'username': 'admin'}, None, None,
    ))

    assert result['method'] == 'snmp'
    assert calls == []


def test_cisco_empty_cdp_output_counts_as_ok(monkeypatch):
    """Cisco 无邻居时输出 "Total cdp entries displayed : 0"（冒号前有空格），必须判 ok。"""
    from services import cli_service as cli_module

    service = CLIService()
    monkeypatch.setattr(cli_module, 'decrypt_password', lambda value: 'secret')
    monkeypatch.setattr(service, '_create_cli_connection', lambda **kwargs: object())
    monkeypatch.setattr(
        service, '_execute_command',
        lambda *args, **kwargs: '\nTotal cdp entries displayed : 0\n',
    )
    result = service._collect_topology_facts_cli(
        '192.0.2.1',
        {'username': 'admin', 'password_encrypted': 'x', 'vendor': 'Cisco',
         'model': 'C3650', 'name': ''},
        None,
        'cdp',
    )
    assert result['status'] == 'ok'
    assert result['entries'] == []
