from __future__ import annotations

from .db import Database
from .route_guidance import (
    RouteGuidanceResult,
    _hop_from_edge,
    route_guidance_text as _base_route_guidance_text,
)
from .world_profiles import (
    active_world_profile_id,
    build_profiled_route_result,
    world_profile,
)


def build_profiled_route_guidance(
    db: Database,
    source_text: str,
    target_text: str,
) -> RouteGuidanceResult:
    profile_id = active_world_profile_id(db)
    route = build_profiled_route_result(db, source_text, target_text, profile_id)
    if not route.ok or len(route.path) < 2:
        return RouteGuidanceResult(route=route, hops=())
    hops = tuple(
        _hop_from_edge(db, source_id, target_id)
        for source_id, target_id in zip(route.path, route.path[1:])
    )
    return RouteGuidanceResult(route=route, hops=hops)


def profiled_route_guidance_text(db: Database, guidance: RouteGuidanceResult) -> str:
    """Render routes without appending unrestricted diagnostics to profile refusals."""
    profile = world_profile(active_world_profile_id(db))
    if not guidance.route.ok:
        # build_profiled_route_result already distinguishes unavailable endpoints,
        # profile-blocked paths, and genuinely missing compiled topology.
        return guidance.route.text
    if not guidance.hops:
        return guidance.route.text
    return f"Gameplay profile: {profile.label}\n\n{_base_route_guidance_text(db, guidance)}"
