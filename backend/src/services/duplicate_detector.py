"""
Duplicate switch detection service.

Compares hostname and serial_number across switches to detect
switches that may represent the same physical device with different management IPs.
"""

from typing import Dict, List, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_
from models.switch import Switch
from utils.logger import logger


async def detect_duplicate_switches(
    db: AsyncSession,
    switch: Switch
) -> List[Dict[str, Any]]:
    """
    After device info collection, check if this switch appears to be a duplicate
    of other switches already in the database.

    Detection rules:
    - Serial match (high confidence): Same non-NULL serial_number -> definitive duplicate
    - Hostname match (medium confidence): Same name -> likely the same switch

    Returns list of duplicate info dicts.
    """
    if not switch.name:
        return []

    matches: List[Dict[str, Any]] = []

    or_conditions = []
    if switch.serial_number:
        or_conditions.append(Switch.serial_number == switch.serial_number)
    or_conditions.append(Switch.name == switch.name)

    result = await db.execute(
        select(Switch).where(
            and_(
                Switch.id != switch.id,
                or_(*or_conditions)
            )
        )
    )
    potential_duplicates = result.scalars().all()

    for other in potential_duplicates:
        match_type: Optional[str] = None
        confidence: Optional[str] = None

        if switch.serial_number and other.serial_number and other.serial_number == switch.serial_number:
            match_type = 'serial_match'
            confidence = 'high'
        elif other.name == switch.name:
            match_type = 'hostname_match'
            confidence = 'medium'

        if match_type:
            matches.append({
                'duplicate_switch_id': other.id,
                'duplicate_switch_name': other.name,
                'duplicate_switch_ip': str(other.ip_address),
                'match_type': match_type,
                'confidence': confidence,
                'shared_serial': switch.serial_number if match_type == 'serial_match' else None,
                'shared_hostname': switch.name if match_type == 'hostname_match' else None,
            })

    if matches:
        for dup in matches:
            logger.warning(
                f"Duplicate switch detected: {switch.name} ({switch.ip_address}) "
                f"matches {dup['duplicate_switch_name']} ({dup['duplicate_switch_ip']}) "
                f"via {dup['match_type']} (confidence: {dup['confidence']})"
            )

    return matches
