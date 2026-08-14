from __future__ import annotations

from .eqmap import normalize_map_name
from .zone_identity import ZoneIdentity, ZoneIdentityIndex, ZoneResolution


def _canonical_name_tokens(identity: ZoneIdentity) -> set[str]:
    name = " ".join((identity.name or "").split()).strip()
    if not name:
        return set()
    values = [name]
    if name.casefold().startswith("the ") and len(name) > 4:
        values.append(name[4:])
    return {normalize_map_name(value) for value in values if normalize_map_name(value)}


def resolve_runtime_zone(
    db,
    value: str,
    *,
    include_map_bindings: bool = True,
    include_derived_map_short_names: bool = True,
) -> ZoneResolution:
    """Resolve a live/runtime zone token without weakening canonical ambiguity globally.

    The canonical identity index intentionally preserves collisions. Runtime zone names,
    however, normally originate in the EverQuest client log. When an exact token
    collision contains one candidate whose *canonical name* matches the token and that
    candidate is uniquely backed by an ``eqclient:zone`` ID, that client identity is
    stronger evidence for the live zone than a provider-only duplicate.

    Alias/short-name collisions are never broken this way. If several client-backed
    zones genuinely share the same display name (for example instance variants), the
    result remains ambiguous and map rendering may separately decide whether all
    candidates safely share one local geometry.
    """
    index = ZoneIdentityIndex(
        db,
        include_map_bindings=include_map_bindings,
        include_derived_map_short_names=include_derived_map_short_names,
    )
    resolution = index.resolve(value)
    if resolution.status != "ambiguous" or not resolution.candidates:
        return resolution

    raw_key = normalize_map_name(" ".join((value or "").split()).strip())
    if not raw_key:
        return resolution

    canonical = tuple(
        identity
        for identity in resolution.candidates
        if raw_key in _canonical_name_tokens(identity)
    )

    # A literal canonical name outranks another entity that happens to expose the same
    # token only as an alias, map stem or short name.
    if len(canonical) == 1:
        chosen = canonical[0]
        return ZoneResolution(
            "linked",
            "canonical_name",
            "exact canonical zone name outranks another exact identity signal",
            chosen,
            resolution.candidates,
        )

    if len(canonical) > 1:
        client_backed = tuple(identity for identity in canonical if identity.client_zone_ids)
        if len(client_backed) == 1:
            chosen = client_backed[0]
            return ZoneResolution(
                "linked",
                "canonical_name",
                "duplicate canonical zone names; unique EverQuest client identity preferred at runtime",
                chosen,
                resolution.candidates,
            )

    return resolution


def ambiguous_candidates_share_canonical_name(resolution: ZoneResolution, value: str) -> bool:
    """Return True only when every ambiguous candidate literally owns this display name."""
    if resolution.status != "ambiguous" or not resolution.candidates:
        return False
    raw_key = normalize_map_name(" ".join((value or "").split()).strip())
    if not raw_key:
        return False
    return all(raw_key in _canonical_name_tokens(identity) for identity in resolution.candidates)
