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


def _authoritative_zone_index(
    db,
    *,
    include_map_bindings: bool = True,
    include_derived_map_short_names: bool = True,
) -> ZoneIdentityIndex:
    """Return the canonical zone index appropriate for this database.

    Builder databases remain uncached because imports can change zone identities while
    the process is running.

    Runtime knowledge is immutable. Rebuilding the complete zone identity index for
    every profile/location/quest-zone lookup is both unnecessary and catastrophic for
    the Tk live path on a large release snapshot.
    """
    if getattr(db, "knowledge_writable", True):
        return ZoneIdentityIndex(
            db,
            include_map_bindings=include_map_bindings,
            include_derived_map_short_names=include_derived_map_short_names,
        )

    key = (
        bool(include_map_bindings),
        bool(include_derived_map_short_names),
    )

    cache = getattr(
        db,
        "_authoritative_zone_identity_indexes",
        None,
    )
    if cache is None:
        cache = {}
        setattr(
            db,
            "_authoritative_zone_identity_indexes",
            cache,
        )

    cached = cache.get(key)
    if cached is not None:
        return cached

    # Zone Opportunities already owns a runtime cache from the earlier large-DB
    # optimization. For the normal runtime policy, reuse that exact object rather
    # than constructing a second identical index.
    if key == (True, True):
        shared = getattr(
            db,
            "_zone_opportunity_identity_index",
            None,
        )
        if shared is not None:
            cache[key] = shared
            return shared

    cached = ZoneIdentityIndex(
        db,
        include_map_bindings=include_map_bindings,
        include_derived_map_short_names=include_derived_map_short_names,
    )
    cache[key] = cached
    return cached


def resolve_authoritative_zone(
    db,
    value: str,
    *,
    include_map_bindings: bool = True,
    include_derived_map_short_names: bool = True,
) -> ZoneResolution:
    """Resolve one exact zone token using the EQ-client authority rule when safe."""
    index = _authoritative_zone_index(
        db,
        include_map_bindings=include_map_bindings,
        include_derived_map_short_names=include_derived_map_short_names,
    )
    return prefer_eqclient_zone_resolution(
        index.resolve(value),
        value,
    )


def authoritative_zones_match(
    db,
    left: str | None,
    right: str | None,
    *,
    include_map_bindings: bool = True,
    include_derived_map_short_names: bool = True,
) -> bool:
    """Return whether two explicit zone tokens resolve to one authoritative identity.

    Literal display text is compared after case/whitespace normalization first. When
    the literals differ, both values must independently resolve through the normal
    EQ-client authority policy to the same canonical zone entity. Missing, unresolved,
    or ambiguous geography never matches.
    """
    left_text = " ".join(str(left or "").split()).strip()
    right_text = " ".join(str(right or "").split()).strip()
    if not left_text or not right_text:
        return False
    if left_text.casefold() == right_text.casefold():
        return True

    left_resolution = resolve_authoritative_zone(
        db,
        left_text,
        include_map_bindings=include_map_bindings,
        include_derived_map_short_names=include_derived_map_short_names,
    )
    right_resolution = resolve_authoritative_zone(
        db,
        right_text,
        include_map_bindings=include_map_bindings,
        include_derived_map_short_names=include_derived_map_short_names,
    )
    return bool(
        left_resolution.identity is not None
        and right_resolution.identity is not None
        and int(left_resolution.identity.entity_id)
        == int(right_resolution.identity.entity_id)
    )
