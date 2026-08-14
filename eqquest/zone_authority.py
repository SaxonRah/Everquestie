from __future__ import annotations

from .eqmap import normalize_map_name
from .zone_identity import ZoneIdentity, ZoneIdentityIndex, ZoneResolution


def canonical_name_tokens(identity: ZoneIdentity) -> set[str]:
    """Normalized literal display-name tokens owned by one zone identity."""
    name = " ".join((identity.name or "").split()).strip()
    if not name:
        return set()
    values = [name]
    if name.casefold().startswith("the ") and len(name) > 4:
        values.append(name[4:])
    return {normalize_map_name(value) for value in values if normalize_map_name(value)}


def prefer_eqclient_zone_resolution(
    resolution: ZoneResolution,
    value: str,
) -> ZoneResolution:
    """Apply EverQuestie's authoritative zone-identity policy to an exact collision.

    The strict canonical index intentionally preserves provider collisions for audits
    and provenance.  Player-facing navigation and builder joins need one deterministic
    canonical target when the installed EverQuest client provides stronger identity
    evidence, though.  For an exact literal display-name collision:

    * a literal canonical name outranks another candidate that only exposes the token
      as an alias/short name/map stem;
    * when several candidates literally own the same display name, exactly one
      ``eqclient:zone``-backed identity wins;
    * alias collisions and multiple client-backed same-name instances remain
      ambiguous.

    No entities are merged, deleted, or rewritten by this projection.
    """
    if resolution.status != "ambiguous" or not resolution.candidates:
        return resolution

    raw_key = normalize_map_name(" ".join((value or "").split()).strip())
    if not raw_key:
        return resolution

    canonical = tuple(
        identity
        for identity in resolution.candidates
        if raw_key in canonical_name_tokens(identity)
    )

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
                "duplicate canonical zone names; unique EverQuest client identity preferred",
                chosen,
                resolution.candidates,
            )

    return resolution


def resolve_authoritative_zone(
    db,
    value: str,
    *,
    include_map_bindings: bool = True,
    include_derived_map_short_names: bool = True,
) -> ZoneResolution:
    """Resolve one exact zone token using the EQ-client authority rule when safe."""
    index = ZoneIdentityIndex(
        db,
        include_map_bindings=include_map_bindings,
        include_derived_map_short_names=include_derived_map_short_names,
    )
    return prefer_eqclient_zone_resolution(index.resolve(value), value)
