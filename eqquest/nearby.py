from __future__ import annotations

from dataclasses import dataclass
import math

from .db import Database
from .location_actionability import location_is_actionable
from .zone_context import ZoneContext, build_zone_context


@dataclass(frozen=True, slots=True)
class NearbyPoint:
    """One reviewed point ranked from the player's observed EQ /loc.

    Distance is deliberately geometric rather than pathfinding: ``horizontal_distance``
    is straight-line distance in normalized EverQuest X/Y and ``vertical_delta`` is
    reported separately. EverQuestie does not infer walkability, floors, doors or
    navmesh paths from this value.
    """

    point_type: str
    name: str
    kind: str
    x: float
    y: float
    z: float | None
    horizontal_distance: float
    vertical_delta: float | None
    delta_x: float
    delta_y: float
    source_name: str
    source_version: str
    source_key: str
    evidence: str
    entity_id: int | None = None
    neighbor_zone_entity_id: int | None = None

    @property
    def source_label(self) -> str:
        source = self.source_name or "EverQuestie knowledge"
        if self.source_version:
            source += f" {self.source_version}"
        return source

    @property
    def loc_text(self) -> str:
        parts = [f"Y={self.y:g}", f"X={self.x:g}"]
        if self.z is not None:
            parts.append(f"Z={self.z:g}")
        return " ".join(parts)

    @property
    def distance_text(self) -> str:
        text = f"{self.horizontal_distance:.1f} horizontal"
        if self.vertical_delta is not None:
            text += f" | ΔZ {self.vertical_delta:+.1f}"
        return text


def _point_distance(
    player_location: tuple[float, float, float],
    x: float,
    y: float,
    z: float | None,
) -> tuple[float, float | None, float, float]:
    player_x, player_y, player_z = (float(v) for v in player_location)
    delta_x = float(x) - player_x
    delta_y = float(y) - player_y
    horizontal = math.hypot(delta_x, delta_y)
    vertical = float(z) - player_z if z is not None else None
    return horizontal, vertical, delta_x, delta_y


def _entity_points(
    context: ZoneContext,
    player_location: tuple[float, float, float],
) -> list[NearbyPoint]:
    result: list[NearbyPoint] = []
    for row in context.locations:
        location = row.location
        if not location_is_actionable(location):
            continue
        assert location.x is not None and location.y is not None
        horizontal, vertical, delta_x, delta_y = _point_distance(
            player_location,
            float(location.x),
            float(location.y),
            location.z,
        )
        result.append(
            NearbyPoint(
                point_type="entity",
                name=row.name,
                kind=row.kind,
                x=float(location.x),
                y=float(location.y),
                z=(float(location.z) if location.z is not None else None),
                horizontal_distance=horizontal,
                vertical_delta=vertical,
                delta_x=delta_x,
                delta_y=delta_y,
                source_name=location.source_name,
                source_version=location.source_version,
                source_key=location.source_key,
                evidence=location.evidence,
                entity_id=row.entity_id,
            )
        )
    return result


def _travel_points(
    context: ZoneContext,
    player_location: tuple[float, float, float],
) -> list[NearbyPoint]:
    result: list[NearbyPoint] = []
    for connection in context.connections:
        # A coordinate on a topology edge always belongs to the edge's source zone.
        # Only show it as navigable from this zone when the edge can actually be used
        # from here and that coordinate is known to lie in the requested zone.
        if not connection.usable_from_zone:
            continue
        if connection.coordinate_zone_entity_id != context.identity.entity_id:
            continue
        if connection.x is None or connection.y is None:
            continue
        horizontal, vertical, delta_x, delta_y = _point_distance(
            player_location,
            float(connection.x),
            float(connection.y),
            connection.z,
        )
        result.append(
            NearbyPoint(
                point_type="travel",
                name=connection.neighbor_zone_name,
                kind=connection.connection_kind,
                x=float(connection.x),
                y=float(connection.y),
                z=(float(connection.z) if connection.z is not None else None),
                horizontal_distance=horizontal,
                vertical_delta=vertical,
                delta_x=delta_x,
                delta_y=delta_y,
                source_name=connection.source_name,
                source_version=connection.source_version,
                source_key=connection.source_key,
                evidence=connection.evidence,
                neighbor_zone_entity_id=connection.neighbor_zone_entity_id,
            )
        )
    return result


def nearby_points(
    db: Database,
    zone_token: str,
    player_location: tuple[float, float, float] | None,
    *,
    limit: int = 25,
    max_horizontal: float | None = None,
    include_entities: bool = True,
    include_travel: bool = True,
) -> tuple[list[NearbyPoint], str]:
    """Rank reviewed current-zone points around one observed player /loc.

    This is a read projection over shipped knowledge. It never writes observed player
    coordinates into the knowledge database. Unprovenanced entity-location rows remain
    visible elsewhere as Knowledge evidence but cannot become Nearby/Map targets. Multiple
    reviewed source statements for the same entity remain separate points because they
    may represent distinct spawns/locations rather than duplicate records.
    """
    if player_location is None:
        return [], "location_unknown"

    context, status = build_zone_context(db, zone_token, location_limit=5000)
    if context is None:
        return [], status

    points: list[NearbyPoint] = []
    if include_entities:
        points.extend(_entity_points(context, player_location))
    if include_travel:
        points.extend(_travel_points(context, player_location))

    if max_horizontal is not None:
        radius = max(0.0, float(max_horizontal))
        points = [point for point in points if point.horizontal_distance <= radius]

    points.sort(
        key=lambda point: (
            point.horizontal_distance,
            abs(point.vertical_delta) if point.vertical_delta is not None else math.inf,
            0 if point.point_type == "travel" else 1,
            point.kind.casefold(),
            point.name.casefold(),
            point.source_name.casefold(),
            point.source_key.casefold(),
        )
    )
    return points[: max(1, int(limit))], "linked"


def nearby_text(
    db: Database,
    zone_token: str,
    player_location: tuple[float, float, float] | None,
    *,
    limit: int = 25,
    max_horizontal: float | None = None,
) -> str:
    """Render nearby reviewed points without implying pathfinding distance."""
    points, status = nearby_points(
        db,
        zone_token,
        player_location,
        limit=limit,
        max_horizontal=max_horizontal,
    )
    if status == "location_unknown":
        return (
            f"NEARBY | {zone_token} | player /loc unknown\n"
            "EverQuestie needs an observed /loc in the current zone before ranking points."
        )
    if status == "ambiguous":
        return f"NEARBY | {zone_token} | ambiguous canonical zone identity"
    if status != "linked":
        return f"NEARBY | {zone_token} | no canonical zone identity"

    player_x, player_y, player_z = (float(v) for v in player_location or (0.0, 0.0, 0.0))
    lines = [
        f"NEARBY | {zone_token}",
        f"Player /loc: Y={player_y:g} X={player_x:g} Z={player_z:g}",
        "Distance: straight-line horizontal X/Y; ΔZ shown separately (not pathfinding).",
    ]
    if max_horizontal is not None:
        lines.append(f"Radius: {max(0.0, float(max_horizontal)):g} horizontal units")
    if not points:
        lines += ["", "No reviewed coordinate-bearing points match this view."]
        return "\n".join(lines)

    lines += ["", f"Nearest reviewed points: {len(points)}"]
    for index, point in enumerate(points, start=1):
        if point.point_type == "travel":
            label = f"[travel:{point.kind.replace('_', ' ')}] → {point.name}"
        else:
            label = f"[{point.kind}] {point.name}"
        lines.append(
            f"  {index}. {label} | {point.distance_text} | {point.loc_text} | {point.source_label}"
        )
    return "\n".join(lines)
