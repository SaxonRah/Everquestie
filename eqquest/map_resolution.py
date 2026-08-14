from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .db import Database
from .eqmap import discover_base_maps, normalize_map_name, resolve_map_for_zone
from .zone_catalog import ZoneMapCatalog


@dataclass(frozen=True, slots=True)
class MapResolution:
    path: Path | None
    reason: str
    candidates: tuple[Path, ...] = ()


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
    rendering asset. A player's explicit binding always wins. Otherwise canonical map
    stems are intersected with files actually present in the chosen local pack. Broad
    legacy filename heuristics are used only when the shipped catalog has no usable
    local candidate.
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

    zone_row, _ = db.resolve_entity(zone_name, "zone")
    if zone_row is not None:
        by_norm = {
            normalize_map_name(path.stem): path
            for path in discover_base_maps(root_path)
        }
        candidates: dict[Path, None] = {}
        for binding in ZoneMapCatalog(db).maps_for_zone(int(zone_row["id"])):
            if binding.status != "linked":
                continue
            path = by_norm.get(normalize_map_name(binding.map_stem))
            if path is not None:
                candidates[path] = None
        ordered = tuple(sorted(candidates, key=lambda p: p.name.casefold()))
        if len(ordered) == 1:
            return MapResolution(ordered[0], "shipped canonical zone/map binding", ordered)
        if len(ordered) > 1:
            if hinted_stem:
                hinted = by_norm.get(normalize_map_name(hinted_stem))
                if hinted in candidates:
                    return MapResolution(
                        hinted,
                        "explicit canonical map short-name hint",
                        ordered,
                    )
            return MapResolution(
                None,
                "multiple shipped canonical map variants exist in the selected pack",
                ordered,
            )

    fallback = resolve_map_for_zone(
        zone_name,
        root_path,
        bound_stem=None,
        hinted_stem=hinted_stem,
    )
    if fallback is not None:
        return MapResolution(fallback, "legacy unique filename fallback", (fallback,))
    return MapResolution(None, "no unique local map-file match")
