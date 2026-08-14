from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .db import Database
from .eqmap import discover_local_base_maps, normalize_map_name, resolve_map_for_zone
from .runtime_zone_identity import (
    ambiguous_candidates_share_canonical_name,
    resolve_runtime_zone,
)
from .zone_catalog import ZoneMapCatalog
from .zone_identity import ZoneIdentity, ZoneResolution


@dataclass(frozen=True, slots=True)
class MapResolution:
    path: Path | None
    reason: str
    candidates: tuple[Path, ...] = ()


def _local_paths_by_stem(root: Path) -> dict[str, list[Path]]:
    by_norm: dict[str, list[Path]] = {}
    for path in discover_local_base_maps(root):
        by_norm.setdefault(normalize_map_name(path.stem), []).append(path)
    return by_norm


def _ordered_paths(paths) -> tuple[Path, ...]:
    return tuple(
        sorted(
            dict.fromkeys(Path(path) for path in paths),
            key=lambda p: (p.name.casefold(), str(p.parent).casefold()),
        )
    )


def _name_variants(value: str) -> tuple[str, ...]:
    value = " ".join((value or "").split()).strip()
    if not value:
        return ()
    values = [value]
    if value.casefold().startswith("the ") and len(value) > 4:
        values.append(value[4:])
    return tuple(dict.fromkeys(values))


def _identity_stems(identity: ZoneIdentity, *, zone_name: str = "", hinted_stem: str = "") -> set[str]:
    values: list[str] = []
    values.extend(_name_variants(identity.name))
    values.extend(identity.short_names)
    values.extend(identity.map_stems)
    if zone_name:
        values.extend(_name_variants(zone_name))
    if hinted_stem:
        values.append(hinted_stem)
    return {normalize_map_name(value) for value in values if normalize_map_name(value)}


def _paths_for_stems(by_norm: dict[str, list[Path]], stems: set[str]) -> tuple[Path, ...]:
    paths: list[Path] = []
    for stem in sorted(stems):
        paths.extend(by_norm.get(stem, ()))
    return _ordered_paths(paths)


def _shared_ambiguous_map_paths(
    resolution: ZoneResolution,
    zone_name: str,
    by_norm: dict[str, list[Path]],
) -> tuple[Path, ...]:
    """Return local geometry shared by duplicate literal zone-name identities only."""
    if not ambiguous_candidates_share_canonical_name(resolution, zone_name):
        return ()
    stem_sets = [_identity_stems(identity) for identity in resolution.candidates]
    if not stem_sets:
        return ()
    common = set(stem_sets[0])
    for stems in stem_sets[1:]:
        common.intersection_update(stems)
    return _paths_for_stems(by_norm, common)


def resolve_catalog_map_for_zone(
    db: Database,
    zone_name: str,
    root: str | Path,
    *,
    bound_stem: str | None = None,
    hinted_stem: str | None = None,
) -> MapResolution:
    """Resolve a local rendering file using shipped canonical map identity first.

    The catalog is global knowledge; the selected map-pack directory is only a local
    rendering asset. A player may select either one concrete pack or the parent
    EverQuest ``maps`` collection containing several packs. A player's explicit
    binding always wins when that stem identifies one local file. Otherwise canonical
    map stems are intersected with files actually present in the chosen local
    collection.

    Runtime zone names normally come from the EQ client log. Provider-only duplicate
    zone entities therefore do not block a unique EQ-client-backed identity. If truly
    distinct client identities share the same literal display name, knowledge identity
    remains ambiguous; the Map tab may still render geometry only when every candidate
    agrees on the same canonical local map signal. Alias ambiguity is never broken by
    filename guessing.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        return MapResolution(None, "map root does not exist")

    # Explicit player override remains authoritative and survives knowledge upgrades.
    if bound_stem:
        bound = resolve_map_for_zone(
            zone_name,
            root_path,
            bound_stem=bound_stem,
            hinted_stem=None,
        )
        if bound is not None:
            return MapResolution(bound, "user map binding", (bound,))

    by_norm = _local_paths_by_stem(root_path)
    zone_resolution = resolve_runtime_zone(db, zone_name, include_map_bindings=True)
    if zone_resolution.status == "ambiguous":
        shared = _shared_ambiguous_map_paths(zone_resolution, zone_name, by_norm)
        if len(shared) == 1:
            return MapResolution(
                shared[0],
                "duplicate canonical zone identities share one local map geometry",
                shared,
            )
        if len(shared) > 1:
            return MapResolution(
                None,
                "duplicate canonical zone identities share multiple local map-pack copies",
                shared,
            )
        names = ", ".join(identity.name for identity in zone_resolution.candidates[:6])
        suffix = f": {names}" if names else ""
        return MapResolution(
            None,
            "canonical zone identity is ambiguous" + suffix,
        )

    if zone_resolution.identity is not None:
        identity = zone_resolution.identity
        candidates: dict[Path, None] = {}
        for binding in ZoneMapCatalog(db).maps_for_zone(identity.entity_id):
            if binding.status != "linked":
                continue
            for path in by_norm.get(normalize_map_name(binding.map_stem), []):
                candidates[path] = None
        ordered = _ordered_paths(candidates)
        if len(ordered) == 1:
            return MapResolution(ordered[0], "shipped canonical zone/map binding", ordered)
        if len(ordered) > 1:
            if hinted_stem:
                hinted_paths = [
                    path
                    for path in by_norm.get(normalize_map_name(hinted_stem), [])
                    if path in candidates
                ]
                if len(hinted_paths) == 1:
                    return MapResolution(
                        hinted_paths[0],
                        "explicit canonical map short-name hint",
                        ordered,
                    )
            return MapResolution(
                None,
                "multiple shipped canonical map variants exist in the selected pack collection",
                ordered,
            )

        # Use exact local identity signals only when runtime actually resolved a prior
        # canonical collision. Ordinary unique zones retain the historic legacy
        # fallback ordering/reason below, avoiding unrelated behavior changes.
        if len(zone_resolution.candidates) > 1:
            exact_local = _paths_for_stems(
                by_norm,
                _identity_stems(identity, zone_name=zone_name, hinted_stem=hinted_stem or ""),
            )
            if len(exact_local) == 1:
                return MapResolution(
                    exact_local[0],
                    "canonical runtime zone identity local map match",
                    exact_local,
                )
            if len(exact_local) > 1:
                return MapResolution(
                    None,
                    "multiple local map-pack copies match the canonical runtime zone identity",
                    exact_local,
                )

    # Broad legacy fallback remains useful for old/incomplete knowledge snapshots, but
    # only after canonical runtime identity failed to provide a direct local signal.
    fallback = resolve_map_for_zone(
        zone_name,
        root_path,
        bound_stem=None,
        hinted_stem=hinted_stem,
    )
    if fallback is not None:
        return MapResolution(fallback, "legacy unique filename fallback", (fallback,))
    return MapResolution(None, "no unique local map-file match")
