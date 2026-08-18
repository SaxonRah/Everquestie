from __future__ import annotations


def handoff_to_travel(app, zone_name: str) -> bool | None:
    """Hand one already-vetted canonical zone to the composed Travel owner.

    Candidate resolution, provenance, chooser policy, and caller-specific messaging
    remain with the calling surface. ``None`` means Travel is not connected; otherwise
    the boolean is exactly the Travel surface's route result.
    """
    travel = getattr(app, "travel_tab", None)
    if travel is None or not hasattr(travel, "route_to_zone"):
        return None
    app.notebook.select(travel)
    return bool(travel.route_to_zone(zone_name))
