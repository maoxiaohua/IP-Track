"""Regression tests for IPLookupService.lookup_ip.

Verifies that a MAC learned only on trunk/uplink ports is NOT reported as an
IP's location (the bug that was fixed), and that an access-port MAC still
resolves normally. Uses a FakeDB that dispatches on the query's table name,
so no real database or network is needed.
"""
from unittest.mock import AsyncMock

import pytest

import services.ip_lookup as ip_lookup_module
from fakes import (
    FakeDB,
    FakeResult,
    default_results,
    make_arp,
    make_mac,
    make_pa,
    make_switch,
)
from services.ip_lookup import ip_lookup_service
from services.settings_service import settings_service


@pytest.fixture
def db_harness(monkeypatch):
    """Patch settings lookup + freshness builder, return the service."""
    monkeypatch.setattr(settings_service, "get_setting", AsyncMock(return_value=24))
    monkeypatch.setattr(
        ip_lookup_module,
        "build_lookup_result_freshness",
        lambda *a, **k: {"status": "fresh", "reason": "fresh"},
    )
    return ip_lookup_service


@pytest.mark.asyncio
async def test_trunk_port_never_reported_as_location(db_harness):
    """MAC only seen on a trunk port (raw name vs normalized analysis name)
    must not be reported as the IP's port location."""
    switch = make_switch(295, "sw-295")
    arp_entry = make_arp(interface="TenGigabitEthernet 1/46", vlan_id=998, switch_id=295)
    mac_candidate = make_mac(port_name="TenGigabitEthernet 1/46", switch_id=295)
    pa_trunk = make_pa("Te 1/46", "trunk", switch_id=295)  # stored analysis uses normalized name

    db = FakeDB(default_results(
        arp=FakeResult(first=(arp_entry, switch)),
        mac=FakeResult(scalars_all=[mac_candidate]),
        pa=FakeResult(scalar_one=pa_trunk, scalars_all=[pa_trunk]),
    ))

    result = await db_harness.lookup_ip(db, "10.106.195.47")

    assert result["found"] is False
    assert result.get("port_name") is None
    assert "port information not available" in result["message"]


@pytest.mark.asyncio
async def test_access_port_reported_as_location(db_harness):
    """MAC seen on an access port must resolve to that physical port, even
    when the ARP interface is an unusable SVI name."""
    switch = make_switch(295, "sw-295")
    arp_entry = make_arp(interface="Vlan998", vlan_id=100, switch_id=295)
    mac_candidate = make_mac(port_name="Te 1/3", vlan_id=100, switch_id=295)
    pa_access = make_pa("Te 1/3", "access")

    db = FakeDB(default_results(
        arp=FakeResult(first=(arp_entry, switch)),
        mac=FakeResult(scalars_all=[mac_candidate]),
        pa=FakeResult(scalar_one=pa_access, scalars_all=[pa_access]),
        switch=FakeResult(scalar_one=switch),
    ))

    result = await db_harness.lookup_ip(db, "10.101.51.162")

    assert result["found"] is True
    assert result["port_name"] == "Te 1/3"
    assert result["switch_id"] == 295
    assert result["switch_name"] == "sw-295"


@pytest.mark.asyncio
async def test_arp_interface_trunk_excluded_as_last_resort(db_harness):
    """When there is no usable MAC-table entry at all, the ARP interface is
    still checked against the lookup policy and a trunk interface is excluded."""
    switch = make_switch(295, "sw-295")
    arp_entry = make_arp(interface="Te 1/46", vlan_id=998, switch_id=295)
    pa_trunk = make_pa("Te 1/46", "trunk", switch_id=295)

    db = FakeDB(default_results(
        arp=FakeResult(first=(arp_entry, switch)),
        mac=FakeResult(scalars_all=[]),  # no MAC-table candidates
        pa=FakeResult(scalars_all=[pa_trunk]),
    ))

    result = await db_harness.lookup_ip(db, "10.106.195.47")

    assert result["found"] is False
    assert result.get("port_name") is None


@pytest.mark.asyncio
async def test_arp_interface_access_used_when_mac_table_missing(db_harness):
    """A usable access ARP interface is used as the port location only when no
    MAC-table entry exists and the interface is lookup-eligible."""
    switch = make_switch(7, "sw-7")
    arp_entry = make_arp(interface="Gi 0/12", vlan_id=10, switch_id=7)
    pa_access = make_pa("Gi 0/12", "access")

    db = FakeDB(default_results(
        arp=FakeResult(first=(arp_entry, switch)),
        mac=FakeResult(scalars_all=[]),
        pa=FakeResult(scalar_one=pa_access, scalars_all=[pa_access]),
        cache=FakeResult(),
    ))

    result = await db_harness.lookup_ip(db, "10.0.0.55")

    assert result["found"] is True
    assert result["port_name"] == "Gi 0/12"
    assert result["switch_id"] == 7


@pytest.mark.asyncio
async def test_unusable_arp_interface_not_used(db_harness):
    """SVI/IRB-style ARP interfaces are never used as the location port."""
    switch = make_switch(7, "sw-7")
    arp_entry = make_arp(interface="irb.10", vlan_id=10, switch_id=7)

    db = FakeDB(default_results(
        arp=FakeResult(first=(arp_entry, switch)),
        mac=FakeResult(scalars_all=[]),
    ))

    result = await db_harness.lookup_ip(db, "10.0.0.55")

    assert result["found"] is False
    assert result.get("port_name") is None
