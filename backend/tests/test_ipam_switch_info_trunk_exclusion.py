"""Regression tests for IPAMService._update_switch_info (subnet scan path).

Guards the fix that stops a trunk/uplink port from being written back to an
IP address's switch_port during a scan, while keeping access ports working.
"""
from types import SimpleNamespace

import pytest

from fakes import (
    FakeDB,
    FakeResult,
    default_results,
    make_arp,
    make_mac,
    make_pa,
    make_switch,
)
from services.ipam_service import ipam_service


def make_ip_addr() -> SimpleNamespace:
    return SimpleNamespace(
        ip_address="10.106.195.47",
        mac_address="00:13:3b:0f:52:de",
        switch_id=None,
        switch_port=None,
        vlan_id=None,
    )


@pytest.mark.asyncio
async def test_trunk_mac_port_not_written():
    """A MAC learned only on a trunk port must not set switch_port, even when
    the raw MAC-table name differs from the stored (normalized) analysis name."""
    switch = make_switch(295, "sw-295")
    mac_trunk = make_mac(port_name="TenGigabitEthernet 1/46", vlan_id=998, switch_id=295)
    arp_entry = make_arp(interface="Te 1/46", vlan_id=998, switch_id=295)
    pa_trunk = make_pa("Te 1/46", "trunk", switch_id=295)

    db = FakeDB(default_results(
        mac_with_switch=FakeResult(all_rows=[(mac_trunk, switch)]),
        arp=FakeResult(first=(arp_entry, switch)),
        mac=FakeResult(scalars_all=[mac_trunk]),
        pa=FakeResult(scalars_all=[pa_trunk]),
    ))

    ip_addr = make_ip_addr()
    await ipam_service._update_switch_info(db, ip_addr, "00:13:3b:0f:52:de")

    assert ip_addr.switch_id == 295          # ARP still identifies the switch
    assert ip_addr.switch_port is None       # but the trunk port is NOT claimed


@pytest.mark.asyncio
async def test_access_mac_port_written():
    """An access-port MAC candidate must be written as the switch/port."""
    switch = make_switch(295, "sw-295")
    mac_access = make_mac(port_name="TenGigabitEthernet 1/3", vlan_id=100, switch_id=295)
    pa_access = make_pa("Te 1/3", "access")

    db = FakeDB(default_results(
        mac_with_switch=FakeResult(all_rows=[(mac_access, switch)]),
        pa=FakeResult(scalars_all=[pa_access]),
    ))

    ip_addr = make_ip_addr()
    await ipam_service._update_switch_info(db, ip_addr, "00:13:3b:0f:52:de")

    assert ip_addr.switch_id == 295
    assert ip_addr.switch_port == "TenGigabitEthernet 1/3"
    assert ip_addr.vlan_id == 100


@pytest.mark.asyncio
async def test_uplink_same_switch_mac_not_written():
    """Same-switch fallback must also exclude uplink ports."""
    switch = make_switch(8, "sw-8")
    mac_trunk = make_mac(port_name="Fo 1/1", vlan_id=200, switch_id=8)
    arp_entry = make_arp(interface="Fo 1/1", vlan_id=200, switch_id=8)
    pa_uplink = make_pa("Fo 1/1", "uplink", switch_id=8)

    db = FakeDB(default_results(
        mac_with_switch=FakeResult(all_rows=[(mac_trunk, switch)]),
        arp=FakeResult(first=(arp_entry, switch)),
        mac=FakeResult(scalars_all=[mac_trunk]),
        pa=FakeResult(scalars_all=[pa_uplink]),
    ))

    ip_addr = make_ip_addr()
    await ipam_service._update_switch_info(db, ip_addr, "00:13:3b:0f:52:de")

    assert ip_addr.switch_id == 8
    assert ip_addr.switch_port is None
