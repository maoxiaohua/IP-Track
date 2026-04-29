#!/usr/bin/env python3
"""
Refresh Windows hostnames for a subnet using the current IPAM scan pipeline.

Usage examples:
  cd /opt/IP-Track
  PYTHONPATH=/opt/IP-Track/backend/src ./venv/bin/python scripts/refresh_windows_hostnames.py --subnet-id 176
  PYTHONPATH=/opt/IP-Track/backend/src ./venv/bin/python scripts/refresh_windows_hostnames.py --network 10.106.195.0/24
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"

if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

# Some operator environments override DEBUG with non-boolean values such as
# "release", which breaks pydantic settings parsing. Force a safe default here.
os.environ["DEBUG"] = os.environ.get("DEBUG", "false").lower() if os.environ.get("DEBUG", "").lower() in {"true", "false", "1", "0"} else "false"

from core.database import AsyncSessionLocal  # noqa: E402
from services.ip_scan import ip_scan_service  # noqa: E402


async def resolve_subnet_id(db, subnet_id: int | None, network: str | None) -> int:
    if subnet_id is not None:
        return subnet_id

    row = (
        await db.execute(
            text("select id from ip_subnets where network = :network"),
            {"network": network},
        )
    ).first()
    if not row:
        raise ValueError(f"Subnet not found for network {network}")
    return int(row[0])


async def refresh_windows_hostnames(subnet_id: int, dns_servers: list[str] | None, concurrency: int) -> dict:
    async with AsyncSessionLocal() as db:
        subnet_row = (
            await db.execute(
                text(
                    """
                    select network, dns_servers
                    from ip_subnets
                    where id = :subnet_id
                    """
                ),
                {"subnet_id": subnet_id},
            )
        ).first()
        if not subnet_row:
            raise ValueError(f"Subnet {subnet_id} not found")

        subnet_network = str(subnet_row[0])
        subnet_dns_servers = [
            item.strip()
            for item in (subnet_row[1] or "").split(",")
            if item.strip()
        ]
        effective_dns_servers = dns_servers or subnet_dns_servers or None

        rows = (
            await db.execute(
                text(
                    """
                    select id, host(ip_address)::text as ip
                    from ip_addresses
                    where subnet_id = :subnet_id
                      and os_type = :os_type
                    order by ip_address
                    """
                ),
                {"subnet_id": subnet_id, "os_type": "windows"},
            )
        ).mappings().all()

        if not rows:
            return {
                "subnet_id": subnet_id,
                "network": subnet_network,
                "windows_total": 0,
                "updated": 0,
                "with_hostname": 0,
                "dns_servers": effective_dns_servers or [],
            }

        semaphore = asyncio.Semaphore(concurrency)

        async def scan_one(ip: str):
            async with semaphore:
                return await ip_scan_service.scan_ip_async(
                    ip,
                    scan_type="full",
                    snmp_profile=None,
                    dns_servers=effective_dns_servers,
                )

        results = await asyncio.gather(*(scan_one(row["ip"]) for row in rows))
        now = datetime.now(timezone.utc)
        with_hostname = 0

        for row, result in zip(rows, results):
            await db.execute(
                text(
                    """
                    update ip_addresses
                    set is_reachable = :is_reachable,
                        response_time = :response_time,
                        hostname = :hostname,
                        hostname_source = :hostname_source,
                        dns_name = :dns_name,
                        os_type = :os_type,
                        os_name = :os_name,
                        os_version = :os_version,
                        os_vendor = :os_vendor,
                        last_scan_at = :last_scan_at,
                        last_seen_at = case when :is_reachable then :last_seen_at else last_seen_at end,
                        scan_count = coalesce(scan_count, 0) + 1
                    where id = :id
                    """
                ),
                {
                    "id": row["id"],
                    "is_reachable": result.get("is_reachable"),
                    "response_time": result.get("response_time"),
                    "hostname": result.get("hostname"),
                    "hostname_source": result.get("hostname_source"),
                    "dns_name": result.get("dns_name"),
                    "os_type": result.get("os_type"),
                    "os_name": result.get("os_name"),
                    "os_version": result.get("os_version"),
                    "os_vendor": result.get("os_vendor"),
                    "last_scan_at": now,
                    "last_seen_at": now if result.get("is_reachable") else None,
                },
            )
            if result.get("hostname"):
                with_hostname += 1

        await db.commit()

        return {
            "subnet_id": subnet_id,
            "network": subnet_network,
            "windows_total": len(rows),
            "updated": len(rows),
            "with_hostname": with_hostname,
            "dns_servers": effective_dns_servers or [],
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh Windows hostnames for one subnet.")
    parser.add_argument("--subnet-id", type=int, help="IPAM subnet ID")
    parser.add_argument("--network", help="Subnet CIDR, for example 10.106.195.0/24")
    parser.add_argument(
        "--dns-server",
        action="append",
        dest="dns_servers",
        help="Optional DNS server override. May be provided more than once.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=20,
        help="Concurrent hostname probes. Default: 20",
    )
    args = parser.parse_args()
    if args.subnet_id is None and not args.network:
        parser.error("either --subnet-id or --network is required")
    return args


async def async_main() -> None:
    args = parse_args()
    async with AsyncSessionLocal() as db:
        subnet_id = await resolve_subnet_id(db, args.subnet_id, args.network)

    summary = await refresh_windows_hostnames(
        subnet_id=subnet_id,
        dns_servers=args.dns_servers,
        concurrency=args.concurrency,
    )
    print(summary)


if __name__ == "__main__":
    asyncio.run(async_main())
