from typing import Any, Dict, Optional

from sqlalchemy import and_, or_


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
