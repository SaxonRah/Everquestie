from __future__ import annotations

from .eqmap import normalize_map_name
from .zone_authority import canonical_name_tokens, resolve_authoritative_zone
from .zone_identity import ZoneResolution


def resolve_runtime_zone(
    db,
    value: str,
    *,
    include_map_bindings: bool = True,
    include_derived_map_short_names: bool = True,
) -> ZoneResolution:
    """Resolve a live/runtime zone token using the shared EQ-client authority rule."""
    return resolve_authoritative_zone(
        db,
        value,
        include_map_bindings=include_map_bindings,
        include_derived_map_short_names=include_derived_map_short_names,
    )


def ambiguous_candidates_share_canonical_name(resolution: ZoneResolution, value: str) -> bool:
    """Return True only when every ambiguous candidate literally owns this display name."""
    if resolution.status != "ambiguous" or not resolution.candidates:
        return False
    raw_key = normalize_map_name(" ".join((value or "").split()).strip())
    if not raw_key:
        return False
    return all(raw_key in canonical_name_tokens(identity) for identity in resolution.candidates)
