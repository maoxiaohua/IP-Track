from typing import Any, Dict, Optional, Tuple

from sqlalchemy import and_, or_, select


LOOKUP_POLICY_INCLUDE = "include"
LOOKUP_POLICY_EXCLUDE = "exclude"
VALID_LOOKUP_POLICY_OVERRIDES = {LOOKUP_POLICY_INCLUDE, LOOKUP_POLICY_EXCLUDE}


def normalize_lookup_policy_override(value: Optional[str]) -> Optional[str]:
    """Normalize a lookup policy override value."""
    if value is None:
        return None

    normalized = value.strip().lower()
    if not normalized:
        return None

    if normalized not in VALID_LOOKUP_POLICY_OVERRIDES:
        raise ValueError(
            f"Invalid lookup policy override '{value}'. "
            f"Expected one of: {', '.join(sorted(VALID_LOOKUP_POLICY_OVERRIDES))}"
        )

    return normalized


def resolve_lookup_policy(
    port_type: Optional[str],
    lookup_policy_override: Optional[str],
    has_analysis: bool = True
) -> Dict[str, Any]:
    """
    Resolve whether a port should participate in IP lookup style matching.

    Policy order:
    1. Manual include
    2. Manual exclude
    3. No analysis record => include as fallback
    4. Auto include only for access ports
    """
    override = normalize_lookup_policy_override(lookup_policy_override)

    if override == LOOKUP_POLICY_INCLUDE:
        return {
            "included": True,
            "status": "included",
            "reason": "manual_include"
        }

    if override == LOOKUP_POLICY_EXCLUDE:
        return {
            "included": False,
            "status": "excluded",
            "reason": "manual_exclude"
        }

    if not has_analysis or not port_type:
        return {
            "included": True,
            "status": "included",
            "reason": "no_analysis"
        }

    included = port_type == "access"
    return {
        "included": included,
        "status": "included" if included else "excluded",
        "reason": f"auto_{port_type}"
    }


def build_lookup_eligible_clause(port_analysis_model):
    """
    SQLAlchemy clause for ports that are eligible for lookup matching.

    - No analysis row yet: allow as fallback
    - Manual include: always allow
    - Manual exclude: always deny
    - Auto mode: only allow access ports
    """
    return or_(
        port_analysis_model.id.is_(None),
        port_analysis_model.lookup_policy_override == LOOKUP_POLICY_INCLUDE,
        and_(
            port_analysis_model.lookup_policy_override.is_(None),
            port_analysis_model.port_type == "access"
        )
    )


def serialize_lookup_policy(port_analysis) -> Dict[str, Any]:
    """Serialize effective lookup policy fields for API responses."""
    resolved = resolve_lookup_policy(
        port_type=getattr(port_analysis, "port_type", None),
        lookup_policy_override=getattr(port_analysis, "lookup_policy_override", None),
        has_analysis=port_analysis is not None
    )

    return {
        "lookup_policy_override": getattr(port_analysis, "lookup_policy_override", None),
        "lookup_policy_note": getattr(port_analysis, "lookup_policy_note", None),
        "lookup_policy_updated_at": (
            port_analysis.lookup_policy_updated_at.isoformat()
            if getattr(port_analysis, "lookup_policy_updated_at", None)
            else None
        ),
        "effective_lookup_status": resolved["status"],
        "effective_lookup_reason": resolved["reason"],
        "lookup_included": resolved["included"]
    }


def _normalize_lookup_port_name(port_name: Optional[str]) -> str:
    """Return the normalized physical port name, or empty string if non-physical."""
    from services.port_analysis_service import port_analysis_service

    if not port_name:
        return ''
    return port_analysis_service.normalize_port_name(port_name)


async def load_port_lookup_policy_map(db, switch_ids):
    """Preload lookup policy info for ports on the given switches.

    Keys use NORMALIZED port names so lookups stay correct even when the raw
    MAC-table port name differs from the stored analysis name (e.g. raw
    ``TenGigabitEthernet 1/50`` vs stored ``Te 1/50``).
    """
    from models.port_analysis import PortAnalysis

    if not switch_ids:
        return {}

    result = await db.execute(
        select(PortAnalysis).where(PortAnalysis.switch_id.in_(list(switch_ids)))
    )
    rows = result.scalars().all()
    return {
        (p.switch_id, _normalize_lookup_port_name(p.port_name)): {
            'port_type': p.port_type,
            'lookup_policy_override': p.lookup_policy_override,
        }
        for p in rows
    }


def resolve_port_lookup_from_map(
    port_map: Dict[Tuple[int, str], Dict[str, Any]],
    switch_id: int,
    port_name: Optional[str]
) -> Tuple[bool, str]:
    """Resolve lookup eligibility for a port against a preloaded policy map.

    Normalizes the port name before matching so raw vendor names (e.g.
    ``TenGigabitEthernet 1/50``) resolve to the same analysis row as the
    normalized name (``Te 1/50``). Ports with no analysis record fall back to
    include (existing behavior for not-yet-analyzed switches).
    """
    if not port_name:
        return False, 'no_port_name'

    normalized = _normalize_lookup_port_name(port_name)
    if not normalized:
        return False, 'non_physical_port'

    info = port_map.get((switch_id, normalized))
    if info is None:
        policy = resolve_lookup_policy(None, None, has_analysis=False)
        return policy['included'], policy['reason']

    policy = resolve_lookup_policy(
        port_type=info['port_type'],
        lookup_policy_override=info['lookup_policy_override'],
        has_analysis=True
    )
    return policy['included'], policy['reason']


async def is_port_lookup_eligible(
    db,
    switch_id: int,
    port_name: Optional[str]
) -> Tuple[bool, str]:
    """Resolve whether a single port on a switch may be used as an IP location.

    Applies the effective lookup policy using the NORMALIZED port name, so
    trunk/uplink ports are never used as a lookup result. No-analysis ports
    fall back to include.
    """
    port_map = await load_port_lookup_policy_map(db, [switch_id])
    return resolve_port_lookup_from_map(port_map, switch_id, port_name)
