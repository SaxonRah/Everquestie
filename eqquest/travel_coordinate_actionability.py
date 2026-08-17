from __future__ import annotations

from typing import Any


# Coordinate actionability is intentionally narrower than topology actionability.
# A provider page or curated manifest may prove that two zones connect without
# proving an exact source-zone /loc for the transition. At present, the only
# supported compiler that attaches X/Y/Z to a travel edge is the map-label
# compiler, where the coordinate and travel label are the same source record.
_ACTIONABLE_COORDINATE_SOURCE_KINDS = frozenset({"map_label"})


def travel_coordinate_source_owns_point(
    source_kind: str,
    x: float | None,
    y: float | None,
) -> bool:
    """Return whether one evidence kind intrinsically owns the stored X/Y point.

    This deliberately says nothing about route direction. A reverse use of a
    bidirectional map-label edge may still carry a trustworthy coordinate, but that
    coordinate belongs to the opposite/source zone and is therefore not actionable
    from the requested zone.
    """
    kind = str(source_kind or "").strip().casefold()
    return bool(
        kind in _ACTIONABLE_COORDINATE_SOURCE_KINDS
        and x is not None
        and y is not None
    )


def travel_coordinate_is_actionable(connection: Any, zone_entity_id: int) -> bool:
    """Return whether one travel edge can safely become a local Map/Nearby point.

    Route connectivity and coordinate actionability are separate claims. The edge
    must be usable from the requested canonical zone, the coordinate must belong
    to that same source zone, X/Y must be present, and the coordinate must come
    from a compiler whose source record intrinsically owns the point.

    Generic/provider topology therefore remains routeable and visible even if a
    legacy or manually edited row happens to contain X/Y/Z; those coordinates are
    evidence-only until a dedicated coordinate-bearing provider compiler exists.
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
        )
    )
