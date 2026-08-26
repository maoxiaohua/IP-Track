"""Regression tests for the port lookup policy core.

Guards the fix that stopped trunk/uplink ports from being reported as an
IP's location: the policy resolver and the vendor port-name normalizer are
the two pieces every lookup path now goes through, so they get the most
direct tests.
"""
import pytest

from fakes import FakeDB, FakeResult, default_results, make_pa
from services.port_analysis_service import port_analysis_service
from services.port_lookup_policy_service import (
    is_port_lookup_eligible,
    resolve_lookup_policy,
    resolve_port_lookup_from_map,
)


# ---------- resolve_lookup_policy ----------

def test_manual_include_always_wins():
    policy = resolve_lookup_policy("trunk", "include", has_analysis=True)
    assert policy["included"] is True
    assert policy["reason"] == "manual_include"


def test_manual_exclude_always_wins():
    policy = resolve_lookup_policy("access", "exclude", has_analysis=True)
    assert policy["included"] is False
    assert policy["reason"] == "manual_exclude"


def test_no_analysis_falls_back_to_include():
    policy = resolve_lookup_policy(None, None, has_analysis=False)
    assert policy["included"] is True
    assert policy["reason"] == "no_analysis"


def test_access_port_included_by_default():
    policy = resolve_lookup_policy("access", None, has_analysis=True)
    assert policy["included"] is True
    assert policy["reason"] == "auto_access"


@pytest.mark.parametrize("port_type", ["trunk", "uplink"])
def test_trunk_and_uplink_excluded(port_type):
    policy = resolve_lookup_policy(port_type, None, has_analysis=True)
    assert policy["included"] is False
    assert policy["reason"] == f"auto_{port_type}"


def test_invalid_override_raises():
    with pytest.raises(ValueError):
        resolve_lookup_policy("access", "bogus", has_analysis=True)


# ---------- port name normalization ----------

@pytest.mark.parametrize("raw,expected", [
    ("TenGigabitEthernet 1/50", "Te 1/50"),
    ("TenGigabitEthernet1/46", "Te 1/46"),
    ("Te1/50", "Te 1/50"),
    ("GigabitEthernet 0/24", "Gi 0/24"),
    ("FastEthernet 0/1", "Fa 0/1"),
    ("FortyGigabitEthernet 1/1", "Fo 1/1"),
    ("HundredGigabitEthernet 1/1", "Hu 1/1"),
    ("  TenGigabitEthernet   1/50  ", "Te 1/50"),
])
def test_physical_port_names_normalized(raw, expected):
    assert port_analysis_service.normalize_port_name(raw) == expected


@pytest.mark.parametrize("raw", [
    "Vlan998", "vlan998", "Loopback0", "Cpu", "mgmt0",
    "", None,
])
def test_non_physical_port_names_emptied(raw):
    assert port_analysis_service.normalize_port_name(raw) == ""


# ---------- resolve_port_lookup_from_map ----------

def test_trunk_in_map_excluded_even_with_raw_name():
    # Stored analysis name is normalized ("Te 1/46") while the raw MAC-table
    # name may be "TenGigabitEthernet 1/46". The map lookup must normalize
    # before matching, otherwise the trunk row is missed (the original bug).
    port_map = {(1, "Te 1/46"): {"port_type": "trunk", "lookup_policy_override": None}}
    included, reason = resolve_port_lookup_from_map(port_map, 1, "TenGigabitEthernet 1/46")
    assert included is False
    assert reason == "auto_trunk"
    included, _ = resolve_port_lookup_from_map(port_map, 1, "Te 1/46")
    assert included is False


def test_access_in_map_included():
    port_map = {(1, "Te 1/3"): {"port_type": "access", "lookup_policy_override": None}}
    included, reason = resolve_port_lookup_from_map(port_map, 1, "Te 1/3")
    assert included is True
    assert reason == "auto_access"


def test_port_without_analysis_falls_back_to_include():
    port_map = {(1, "Te 1/3"): {"port_type": "access", "lookup_policy_override": None}}
    included, reason = resolve_port_lookup_from_map(port_map, 1, "Gi 1/10")
    assert included is True
    assert reason == "no_analysis"


def test_empty_port_name_rejected():
    port_map = {}
    included, reason = resolve_port_lookup_from_map(port_map, 1, None)
    assert included is False
    assert reason == "no_port_name"


# ---------- is_port_lookup_eligible (db-backed wrapper) ----------

@pytest.mark.asyncio
async def test_eligible_wrapper_excludes_trunk():
    db = FakeDB(default_results(pa=FakeResult(scalars_all=[make_pa("Te 1/46", "trunk")])))
    included, reason = await is_port_lookup_eligible(db, 1, "TenGigabitEthernet 1/46")
    assert included is False
    assert reason == "auto_trunk"


@pytest.mark.asyncio
async def test_eligible_wrapper_includes_access():
    db = FakeDB(default_results(pa=FakeResult(scalars_all=[make_pa("Te 1/3", "access")])))
    included, reason = await is_port_lookup_eligible(db, 1, "Te 1/3")
    assert included is True
    assert reason == "auto_access"


@pytest.mark.asyncio
async def test_eligible_wrapper_no_analysis_falls_back_to_include():
    db = FakeDB(default_results())
    included, reason = await is_port_lookup_eligible(db, 1, "Te 1/10")
    assert included is True
    assert reason == "no_analysis"
