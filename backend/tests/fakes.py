"""Shared fakes for DB-free unit tests.

FakeDB dispatches `db.execute(query)` by inspecting the compiled SQL table
name, so tests drive each query path by configuring a dict of FakeResult
objects. This keeps tests fast (no real DB) and decoupled from query ordering.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from services.port_analysis_service import port_analysis_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


def make_switch(switch_id: int = 1, name: str = "test-sw", ip: str = "10.0.0.1") -> SimpleNamespace:
    return SimpleNamespace(
        id=switch_id,
        name=name,
        ip_address=ip,
        last_collection_status="success",
        last_collection_message=None,
        is_reachable=True,
    )


def make_arp(mac: str = "00:13:3b:0f:52:de", interface: str = "Te 1/3",
             vlan_id: int = 100, switch_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        mac_address=mac,
        interface=interface,
        vlan_id=vlan_id,
        switch_id=switch_id,
        last_seen=_now(),
    )


def make_mac(mac: str = "00:13:3b:0f:52:de", port_name: str = "Te 1/3",
             vlan_id: int = 100, switch_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        mac_address=mac,
        port_name=port_name,
        vlan_id=vlan_id,
        switch_id=switch_id,
        last_seen=_now(),
    )


def make_pa(port_name: str, port_type: str, override: str = None, switch_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        switch_id=switch_id,
        port_name=port_name,
        port_type=port_type,
        lookup_policy_override=override,
    )


class _Scalars:
    def __init__(self, items):
        self._items = list(items)

    def all(self):
        return self._items

    def one_or_none(self):
        return self._items[0] if self._items else None

    def one(self):
        if not self._items:
            raise ValueError("No rows returned")
        return self._items[0]


class FakeResult:
    def __init__(self, first=None, scalar_one=None, scalars_all=None, all_rows=None):
        self._first = first
        self._scalar_one = scalar_one
        self._scalars_all = scalars_all if scalars_all is not None else []
        self._all = all_rows if all_rows is not None else []

    def first(self):
        return self._first

    def scalar_one_or_none(self):
        return self._scalar_one

    def scalar(self):
        return self._scalar_one

    def scalars(self):
        return _Scalars(self._scalars_all)

    def all(self):
        return self._all

    def mappings(self):
        return self._all


class FakeDB:
    """Minimal AsyncSession stand-in. Configure `results` keyed by table name."""

    def __init__(self, results):
        self.results = results
        self.added_objects = []
        self.committed = 0
        self.rolled_back = 0
        self.flushed = 0

    def _lookup(self, sql):
        if "arp_table" in sql:
            return self.results["arp"]
        if "port_analysis" in sql:
            return self.results["pa"]
        if "mac_address_cache" in sql:
            return self.results["cache"]
        if "mac_table" in sql:
            if "switches" in sql:
                return self.results["mac_with_switch"]
            return self.results["mac"]
        if "switches" in sql:
            return self.results["switch"]
        raise AssertionError(f"Unexpected query: {sql}")

    async def execute(self, query):
        return self._lookup(str(query).lower())

    async def stream(self, query):
        return self._lookup(str(query).lower())

    def add(self, obj):
        self.added_objects.append(obj)

    def add_all(self, objs):
        self.added_objects.extend(objs)

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1

    async def flush(self):
        self.flushed += 1

    async def close(self):
        pass


def default_results(**overrides) -> dict:
    """Default FakeDB results where every query returns empty, overridable per key."""
    base = {
        "arp": FakeResult(),
        "mac": FakeResult(),
        "mac_with_switch": FakeResult(),
        "pa": FakeResult(),
        "switch": FakeResult(),
        "cache": FakeResult(),
    }
    base.update(overrides)
    return base
