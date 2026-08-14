from __future__ import annotations

from dataclasses import dataclass

from .db import normalize_name
from .eqmap import ZoneMap, normalize_map_name
from .local_search import map_label_terms, parse_local_query


@dataclass(frozen=True, slots=True)
class MapLabelHit:
    layer: int
    text: str
    x: float
    y: float
    z: float
    source_line: int
    score: tuple
    reason: str


def _query_zone_matches(zone_map: ZoneMap, current_zone: str | None, requested_zone: str | None) -> bool:
    if not requested_zone:
        return True
    requested = requested_zone
    if requested.casefold() == "current":
        requested = current_zone or ""
    if not requested:
        return False
    wanted = normalize_map_name(requested)
    current = normalize_map_name(current_zone or "")
    stem = normalize_map_name(zone_map.stem)
    return bool(wanted and (wanted == current or wanted == stem))


def find_map_label_hits(
    zone_map: ZoneMap | None,
    raw_query: str,
    *,
    current_zone: str | None = None,
    enabled_layers: list[int] | tuple[int, ...] | None = None,
    limit: int = 40,
) -> list[MapLabelHit]:
    """Search selectable P-record labels from the currently loaded local map.

    Map labels are evidence, not normalized knowledge entities. Structured filters are
    accepted so a query copied from Knowledge/Search can still surface a map candidate.
    ``type:`` is intentionally not asserted against the label because map files do not
    encode entity type.
    """
    if zone_map is None:
        return []
    query = parse_local_query(raw_query)
    if not _query_zone_matches(zone_map, current_zone, query.zone):
        return []
    if query.source:
        source = normalize_name(query.source)
        if not any(token in source for token in ("map", "good", "brewall", "everquest")):
            return []

    text = query.text.strip()
    if not text:
        # For an ordinary unstructured lookup parse_local_query preserves the text.
        return []
    needles = [normalize_name(value) for value in map_label_terms(text) if value]
    needles = [value for value in needles if value]
    if not needles:
        return []

    wanted_layers = set(enabled_layers) if enabled_layers is not None else set(zone_map.layers)
    hits: list[MapLabelHit] = []
    for layer_no in sorted(wanted_layers):
        layer = zone_map.layers.get(layer_no)
        if layer is None:
            continue
        for point in layer.points:
            variants = [normalize_name(value) for value in map_label_terms(point.display_text) if value]
            variants = [value for value in variants if value]
            if not variants:
                continue

            best: tuple | None = None
            reason = ""
            for needle in needles:
                if needle in variants:
                    candidate = (0, len(point.display_text), layer_no, point.source_line)
                    candidate_reason = "map label exact"
                elif any(value.startswith(needle) or needle.startswith(value) for value in variants):
                    candidate = (1, len(point.display_text), layer_no, point.source_line)
                    candidate_reason = "map label prefix"
                elif any(needle in value or value in needle for value in variants):
                    candidate = (2, len(point.display_text), layer_no, point.source_line)
                    candidate_reason = "map label contains"
                else:
                    continue
                if best is None or candidate < best:
                    best = candidate
                    reason = candidate_reason
            if best is None:
                continue
            if query.kinds:
                reason += " · type unclassified"
            hits.append(
                MapLabelHit(
                    layer=layer_no,
                    text=point.display_text,
                    x=float(point.x),
                    y=float(point.y),
                    z=float(point.z),
                    source_line=int(point.source_line),
                    score=best,
                    reason=reason,
                )
            )

    hits.sort(key=lambda hit: hit.score)
    return hits[: max(1, int(limit))]
