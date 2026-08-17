from __future__ import annotations

from typing import Any


# Coordinate actionability is intentionally narrower than topology actionability.
# A provider page or curated manifest may prove that two zones connect without
# proving an exact source-zone /loc for the transition. At present, the only
# supported compiler that attaches X/Y/Z to a travel edge is the map-label
# compiler, where the coordinate and travel label are the same concrete source
# record. Requiring that record ID prevents a stale/manual row from becoming a
# waypoint merely by claiming source_kind='map_label'.
_ACTIONABLE_COORDINATE_SOURCE_KINDS = frozenset({"map_label"})


def travel_coordinate_source_owns_point(
    source_kind: str,
    x: float | None,
    y: float | None,
    source_record_id: int | None,
) -> bool:
    """Return whether one evidence record intrinsically owns the stored X/Y point.

    This deliberately says nothing about route direction. A reverse use of a
    bidirectional map-label edge may still carry a trustworthy coordinate, but that
    coordinate belongs to the opposite/source zone and is therefore not actionable
    from the requested zone.

    ``source_record_id`` is the concrete coordinate-bearing source row. For the
    current map-label compiler this is ``zone_travel_edges.label_id``. A source-kind
    string alone is not provenance.
    """
    kind = str(source_kind or "").strip().casefold()
    try:
        record_id = int(source_record_id) if source_record_id is not None else None
    except (TypeError, ValueError):
        record_id = None
    return bool(
        kind in _ACTIONABLE_COORDINATE_SOURCE_KINDS
        and record_id is not None
        and record_id > 0
        and x is not None
        and y is not None
    )


def travel_coordinate_is_actionable(connection: Any, zone_entity_id: int) -> bool:
    """Return whether one travel edge can safely become a local Map/Nearby point.

    Route connectivity and coordinate actionability are separate claims. The edge
    must be usable from the requested canonical zone, the coordinate must belong
    to that same source zone, X/Y must be present, and the coordinate must come
    from a compiler whose concrete source record intrinsically owns the point.

    Generic/provider topology therefore remains routeable and visible even if a
    legacy or manually edited row happens to contain X/Y/Z. A row that merely labels
    itself ``map_label`` without retaining its concrete label ID is also evidence-only.
    """
    try:
        coordinate_zone_id = int(connection.coordinate_zone_entity_id)
        requested_zone_id = int(zone_entity_id)
    except (AttributeError, TypeError, ValueError):
        return False

    return bool(
        getattr(connection, "usable_from_zone", False)
        and coordinate_zone_id == requested_zone_id
        and travel_coordinate_source_owns_point(
            str(getattr(connection, "source_kind", "") or ""),
            getattr(connection, "x", None),
            getattr(connection, "y", None),
            getattr(connection, "label_id", None),
        )
    )
