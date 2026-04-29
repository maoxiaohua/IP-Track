from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config.collection_strategy import CollectionMethod, CollectionStrategy
from services.network_data_collector import NetworkDataCollector


def _build_switch() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        name="test-switch",
        ip_address="10.0.0.1",
        vendor="cisco",
        model="WS-C4506",
        username="admin",
        cli_enabled=True,
        cli_transport="telnet",
        ssh_port=23,
        password_encrypted="encrypted-password",
        enable_password_encrypted=None,
        connection_timeout=30,
        snmp_enabled=True,
        snmp_auth_password_encrypted="encrypted-snmp-auth",
        mac_collection_method="snmp",
        mac_method_override=True,
        arp_collection_method="snmp",
        arp_method_override=True,
        mac_collection_success_count=0,
        mac_collection_fail_count=0,
        arp_collection_success_count=0,
        arp_collection_fail_count=0,
        last_collection_status=None,
        last_collection_message=None,
        last_mac_collection_at=None,
        last_arp_collection_at=None,
        is_reachable=True,
    )


@pytest.mark.asyncio
async def test_collect_mac_single_switch_uses_global_cli_policy(monkeypatch):
    collector = NetworkDataCollector()
    switch = _build_switch()
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(collector, "_load_command_templates", AsyncMock(return_value=[]))
    monkeypatch.setattr(collector, "_store_mac_entries_bulk", AsyncMock())
    monkeypatch.setattr(
        collector,
        "refresh_port_analysis_for_switch",
        AsyncMock(return_value={"ports_analyzed": 1}),
    )
    monkeypatch.setattr(
        "services.network_data_collector.asyncio.to_thread",
        AsyncMock(return_value=[{"mac_address": "aa:bb:cc:dd:ee:ff", "port_name": "Gi1/0/1", "vlan_id": 10, "is_dynamic": 1}]),
    )
    snmp_mock = AsyncMock(return_value=[{"mac_address": "should-not-be-used"}])
    monkeypatch.setattr("services.network_data_collector.snmp_service.collect_mac_table_async", snmp_mock)

    result = await collector.collect_mac_single_switch(db, switch)

    assert len(result) == 1
    assert switch.mac_collection_method == "cli"
    assert switch.mac_method_override is False
    snmp_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_collect_arp_single_switch_uses_global_cli_policy(monkeypatch):
    collector = NetworkDataCollector()
    switch = _build_switch()
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(collector, "_load_command_templates", AsyncMock(return_value=[]))
    monkeypatch.setattr(collector, "_store_arp_entries_bulk", AsyncMock())
    monkeypatch.setattr(
        "services.network_data_collector.asyncio.to_thread",
        AsyncMock(return_value=[{"ip_address": "10.0.0.10", "mac_address": "aa:bb:cc:dd:ee:ff", "vlan_id": 10, "interface": "Vlan10", "age_seconds": None}]),
    )
    snmp_mock = AsyncMock(return_value=[{"ip_address": "should-not-be-used"}])
    monkeypatch.setattr("services.network_data_collector.snmp_service.collect_arp_table_async", snmp_mock)

    result = await collector.collect_arp_single_switch(db, switch)

    assert len(result) == 1
    assert switch.arp_collection_method == "cli"
    assert switch.arp_method_override is False
    snmp_mock.assert_not_awaited()


def test_collection_strategy_enforces_global_cli_for_l2_tables():
    assert CollectionStrategy.get_l2_table_method() == CollectionMethod.CLI_ONLY
    assert CollectionStrategy.get_l2_table_primary_method() == "CLI only (global)"
