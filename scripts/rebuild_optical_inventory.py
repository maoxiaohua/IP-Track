#!/usr/bin/env python3
"""
Rebuild optical inventory from live switches without deleting historical rows.

Run with:
  DEBUG=false PYTHONPATH=backend/src ./venv/bin/python scripts/rebuild_optical_inventory.py
"""

import asyncio
import json

from core.database import AsyncSessionLocal
from services.network_data_collector import network_data_collector


async def main() -> None:
    async with AsyncSessionLocal() as db:
        summary = await network_data_collector.collect_optical_modules_from_all_switches(db)
        await db.commit()
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
