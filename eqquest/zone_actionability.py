from __future__ import annotations

from dataclasses import dataclass

from .db import Database
from .zone_context import ZoneConnection, ZoneContext, build_zone_context, zone_context_text


@dataclass(frozen=True, slots=True)
class ZoneRouteDirection:
    """One canonical route direction usable from the requested zone.

    Multiple provenance rows can describe the same source→neighbor direction. The
    representative row follows the same actionability precedence used by route
    guidance: direct evidence beats reverse two-way evidence, and an X/Y-bearing
    direct row beats a coordinate-less direct row.
    """

    source_zone_entity_id: int
    source_zone_name: str
    neighbor_zone_entity_id: int
    neighbor_zone_name: str
    connection_kind: str
    bidirectional: bool
    uses_reverse_evidence: bool
    evidence_count: int
    source_name: str
    source_kind: str
    source_key: str
    source_version: str
    evidence: str
    coordinate_owner_entity_id: int
    x: float | None
    y: float | None
    z: float | None

    @property
    def mappable(self) -> bool:
        return (
            not self.uses_reverse_evidence
            and self.coordinate_owner_entity_id == self.source_zone_entity_id
            and self.x is not None
            and self.y is not None
        )

    @property
    def source_label(self) -> str:
        base = self.source_name or self.source_kind or "EverQuestie knowledge"
        return f"{base} {self.source_version}".strip()

    @property
    def loc_text(self) -> str:
        if not self.mappable:
            return ""
        parts = [f"Y={float(self.y):g}", f"X={float(self.x):g}"]
        if self.z is not None:
            parts.append(f"Z={float(self.z):g}")
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class ZoneActionabilityContext:
    context: ZoneContext
    route_directions: tuple[ZoneRouteDirection, ...]

    @property
    def usable_route_directions(self) -> int:
        return len(self.route_directions)

    @property
    def mappable_route_directions(self) -> int:
        return sum(direction.mappable for direction in self.route_directions)

    @property
    def unmappable_route_directions(self) -> tuple[ZoneRouteDirection, ...]:
        return tuple(direction for direction in self.route_directions if not direction.mappable)


def _connection_rank(zone_entity_id: int, connection: ZoneConnection) -> tuple:
    direct = connection.coordinate_zone_entity_id == zone_entity_id
    has_xy = connection.x is not None and connection.y is not None
    return (
        0 if direct else 1,
        0 if direct and has_xy else 1,
        connection.source_kind.casefold(),
        connection.source_name.casefold(),
        connection.source_key.casefold(),
        connection.edge_id,
    )


def _route_directions(context: ZoneContext) -> tuple[ZoneRouteDirection, ...]:
    zone_id = context.identity.entity_id
    grouped: dict[int, list[ZoneConnection]] = {}
    for connection in context.connections:
        if not connection.usable_from_zone:
            continue
        grouped.setdefault(connection.neighbor_zone_entity_id, []).append(connection)

    directions: list[ZoneRouteDirection] = []
    for neighbor_id, rows in grouped.items():
        chosen = min(rows, key=lambda row: _connection_rank(zone_id, row))
        direct = chosen.coordinate_zone_entity_id == zone_id
        directions.append(
            ZoneRouteDirection(
                source_zone_entity_id=zone_id,
                source_zone_name=context.identity.name,
                neighbor_zone_entity_id=neighbor_id,
                neighbor_zone_name=chosen.neighbor_zone_name,
                connection_kind=chosen.connection_kind,
                bidirectional=chosen.bidirectional,
                uses_reverse_evidence=not direct,
                evidence_count=len(rows),
                source_name=chosen.source_name,
                source_kind=chosen.source_kind,
                source_key=chosen.source_key,
                source_version=chosen.source_version,
                evidence=chosen.evidence,
                coordinate_owner_entity_id=chosen.coordinate_zone_entity_id,
                x=chosen.x,
                y=chosen.y,
                z=chosen.z,
            )
        )
    directions.sort(key=lambda row: (row.neighbor_zone_name.casefold(), row.neighbor_zone_entity_id))
    return tuple(directions)


def build_zone_actionability(
    db: Database,
    zone_token: str,
    *,
    location_limit: int = 500,
) -> tuple[ZoneActionabilityContext | None, str]:
    context, status = build_zone_context(db, zone_token, location_limit=location_limit)
    if context is None:
        return None, status
    return ZoneActionabilityContext(context=context, route_directions=_route_directions(context)), "linked"


def zone_actionability_text(
    db: Database,
    zone_token: str,
    *,
    location_limit: int = 25,
) -> str:
    view, status = build_zone_actionability(
        db,
        zone_token,
        location_limit=max(1, int(location_limit)),
    )
    base = zone_context_text(db, zone_token, location_limit=location_limit)
    if view is None:
        return base

    lines = [
        base,
        "",
        "Route map actionability:",
        (
            f"  Mappable exits: {view.mappable_route_directions}/"
            f"{view.usable_route_directions} usable canonical route direction(s)"
        ),
    ]
    if not view.route_directions:
        lines.append("  No confirmed route direction is usable from this zone.")
        return "\n".join(lines)

    for direction in view.route_directions:
        kind = direction.connection_kind.replace("_", " ")
        if direction.mappable:
            action = f"map target available | {direction.loc_text}"
        elif direction.uses_reverse_evidence:
            action = (
                "no source-side coordinate | selected topology evidence is stored from the opposite zone"
            )
        else:
            action = "no source-side coordinate"
        evidence_count = (
            f" | {direction.evidence_count} evidence rows"
            if direction.evidence_count > 1
            else ""
        )
        lines.append(
            f"  • → {direction.neighbor_zone_name} | {kind} | {action} | "
            f"source: {direction.source_label}{evidence_count}"
        )
    return "\n".join(lines)
