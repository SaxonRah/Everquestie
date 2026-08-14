from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from .db import Database
from .eqmap import map_to_game
from .locations import LocationEvidence
from .zone_catalog import ZoneMapBinding, ZoneMapCatalog
from .zone_identity import ZoneIdentity, ZoneIdentityIndex


@dataclass(frozen=True, slots=True)
class ZoneConnection:
    """One confirmed topology edge touching the requested canonical zone.

    ``direction`` is relative to the requested zone. Coordinates remain attached to
    the source zone of the underlying evidence; this matters for directed edges and
    prevents an incoming portal coordinate from being displayed on the wrong map.
    """

    edge_id: int
    neighbor_zone_entity_id: int
    neighbor_zone_name: str
    connection_kind: str
    direction: str
    bidirectional: bool
    usable_from_zone: bool
    source_name: str
    source_kind: str
    source_key: str
    source_version: str
    evidence: str
    coordinate_zone_entity_id: int
    x: float | None
    y: float | None
    z: float | None

    @property
    def loc_text(self) -> str:
        parts: list[str] = []
        if self.y is not None:
            parts.append(f"Y={self.y:g}")
        if self.x is not None:
            parts.append(f"X={self.x:g}")
        if self.z is not None:
            parts.append(f"Z={self.z:g}")
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class ZoneLocatedEntity:
    """One canonical entity plus one confirmed location-evidence statement."""

    entity_id: int
    name: str
    kind: str
    location: LocationEvidence


@dataclass(frozen=True, slots=True)
class ZoneContext:
    """Read-only projection of all canonical knowledge attached to one zone."""

    identity: ZoneIdentity
    resolution_kind: str
    resolution_reason: str
    level_min: int | None
    level_max: int | None
    data: dict
    maps: tuple[ZoneMapBinding, ...]
    connections: tuple[ZoneConnection, ...]
    locations: tuple[ZoneLocatedEntity, ...]

    @property
    def entity_count(self) -> int:
        return len({row.entity_id for row in self.locations})

    @property
    def usable_connections(self) -> tuple[ZoneConnection, ...]:
        return tuple(row for row in self.connections if row.usable_from_zone)


def _relation_exists(db: Database, name: str) -> bool:
    return db.conn.execute(
        """
        SELECT 1 FROM sqlite_temp_master
        WHERE type IN ('table','view') AND name=?
        UNION ALL
        SELECT 1 FROM sqlite_master
        WHERE type IN ('table','view') AND name=?
        LIMIT 1
        """,
        (name, name),
    ).fetchone() is not None


def _connections_for_zone(db: Database, zone_entity_id: int) -> list[ZoneConnection]:
    if not _relation_exists(db, "zone_travel_edges"):
        return []
    rows = db.conn.execute(
        """
        SELECT e.*,
               source_zone.name AS source_zone_name,
               target_zone.name AS target_zone_name
        FROM zone_travel_edges e
        JOIN entities source_zone ON source_zone.id=e.source_zone_entity_id
        JOIN entities target_zone ON target_zone.id=e.target_zone_entity_id
        WHERE e.status='linked' AND e.target_zone_entity_id IS NOT NULL
          AND (e.source_zone_entity_id=? OR e.target_zone_entity_id=?)
        ORDER BY e.connection_kind,e.source_zone_entity_id,e.target_zone_entity_id,
                 e.source_kind,e.source_name,e.source_key,e.id
        """,
        (int(zone_entity_id), int(zone_entity_id)),
    ).fetchall()

    result: list[ZoneConnection] = []
    for row in rows:
        source_id = int(row["source_zone_entity_id"])
        target_id = int(row["target_zone_entity_id"])
        bidirectional = bool(row["bidirectional"])
        if source_id == int(zone_entity_id):
            neighbor_id = target_id
            neighbor_name = str(row["target_zone_name"])
            direction = "bidirectional" if bidirectional else "outgoing"
            usable = True
        else:
            neighbor_id = source_id
            neighbor_name = str(row["source_zone_name"])
            direction = "bidirectional" if bidirectional else "incoming"
            usable = bidirectional
        result.append(
            ZoneConnection(
                edge_id=int(row["id"]),
                neighbor_zone_entity_id=neighbor_id,
                neighbor_zone_name=neighbor_name,
                connection_kind=str(row["connection_kind"] or "travel"),
                direction=direction,
                bidirectional=bidirectional,
                usable_from_zone=usable,
                source_name=str(row["source_name"] or ""),
                source_kind=str(row["source_kind"] or ""),
                source_key=str(row["source_key"] or ""),
                source_version=str(row["source_version"] or ""),
                evidence=str(row["evidence"] or ""),
                coordinate_zone_entity_id=source_id,
                x=(float(row["x"]) if row["x"] is not None else None),
                y=(float(row["y"]) if row["y"] is not None else None),
                z=(float(row["z"]) if row["z"] is not None else None),
            )
        )
    return result


def _provider_locations_in_zone(
    db: Database,
    zone_entity_id: int,
    *,
    limit: int,
) -> list[ZoneLocatedEntity]:
    rows = db.conn.execute(
        """
        SELECT l.entity_id,l.zone_entity_id,l.x,l.y,l.z,l.label,l.source_page_id,l.evidence,
               e.name AS entity_name,e.kind AS entity_kind,z.name AS zone_name,
               sp.source_name,sp.source_version,sp.source_key,sp.url
        FROM entity_locations l
        JOIN entities e ON e.id=l.entity_id
        JOIN entities z ON z.id=l.zone_entity_id
        LEFT JOIN source_pages sp ON sp.id=l.source_page_id
        WHERE l.zone_entity_id=?
        ORDER BY e.kind,e.name,l.id
        LIMIT ?
        """,
        (int(zone_entity_id), max(1, int(limit))),
    ).fetchall()
    result: list[ZoneLocatedEntity] = []
    for row in rows:
        location = LocationEvidence(
            entity_id=int(row["entity_id"]),
            zone_entity_id=int(row["zone_entity_id"]),
            zone_name=str(row["zone_name"] or ""),
            x=(float(row["x"]) if row["x"] is not None else None),
            y=(float(row["y"]) if row["y"] is not None else None),
            z=(float(row["z"]) if row["z"] is not None else None),
            label=str(row["label"] or ""),
            evidence_type="entity_location",
            source_name=str(row["source_name"] or "EverQuestie knowledge"),
            source_version=str(row["source_version"] or ""),
            source_key=str(row["source_key"] or row["url"] or ""),
            source_page_id=(
                int(row["source_page_id"])
                if row["source_page_id"] is not None
                else None
            ),
            evidence=str(row["evidence"] or ""),
        )
        result.append(
            ZoneLocatedEntity(
                entity_id=int(row["entity_id"]),
                name=str(row["entity_name"]),
                kind=str(row["entity_kind"]),
                location=location,
            )
        )
    return result


def _map_locations_in_zone(
    db: Database,
    zone_entity_id: int,
    *,
    limit: int,
) -> list[ZoneLocatedEntity]:
    if not all(
        _relation_exists(db, table)
        for table in ("map_labels", "map_sources", "zone_map_bindings")
    ):
        return []
    try:
        rows = db.conn.execute(
            """
            SELECT ml.id,ml.linked_entity_id,ml.map_stem,ml.layer,ml.source_line,
                   ml.raw_text,ml.x,ml.y,ml.z,ml.link_reason,
                   e.name AS entity_name,e.kind AS entity_kind,
                   ms.source_name,ms.source_version,ms.source_key,
                   zmb.zone_entity_id,zmb.zone_name
            FROM map_labels ml
            JOIN map_sources ms ON ms.id=ml.source_id
            JOIN zone_map_bindings zmb
              ON zmb.source_name=ms.source_name
             AND zmb.map_stem=ml.map_stem
             AND zmb.status='linked'
            JOIN entities e ON e.id=ml.linked_entity_id
            WHERE zmb.zone_entity_id=?
              AND ml.link_status='linked'
              AND ml.linked_entity_id IS NOT NULL
            ORDER BY e.kind,e.name,ms.source_name,ml.map_stem,ml.layer,ml.source_line
            LIMIT ?
            """,
            (int(zone_entity_id), max(1, int(limit))),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    result: list[ZoneLocatedEntity] = []
    for row in rows:
        game_x, game_y, game_z = map_to_game(
            float(row["x"]), float(row["y"]), float(row["z"])
        )
        location = LocationEvidence(
            entity_id=int(row["linked_entity_id"]),
            zone_entity_id=int(row["zone_entity_id"]),
            zone_name=str(row["zone_name"] or ""),
            x=game_x,
            y=game_y,
            z=game_z,
            label=str(row["raw_text"] or ""),
            evidence_type="map_label",
            source_name=str(row["source_name"] or "Map catalog"),
            source_version=str(row["source_version"] or ""),
            source_key=str(row["source_key"] or ""),
            evidence=str(row["link_reason"] or "linked map catalog evidence"),
            map_label_id=int(row["id"]),
            map_stem=str(row["map_stem"] or ""),
            layer=int(row["layer"]),
            source_line=int(row["source_line"]),
        )
        result.append(
            ZoneLocatedEntity(
                entity_id=int(row["linked_entity_id"]),
                name=str(row["entity_name"]),
                kind=str(row["entity_kind"]),
                location=location,
            )
        )
    return result


def _locations_for_zone(
    db: Database,
    zone_entity_id: int,
    *,
    limit: int,
) -> list[ZoneLocatedEntity]:
    # Apply the final limit after combining sources so one high-volume source cannot
    # entirely hide evidence from the other projection.
    per_source = max(1, int(limit))
    rows = _provider_locations_in_zone(db, zone_entity_id, limit=per_source)
    rows.extend(_map_locations_in_zone(db, zone_entity_id, limit=per_source))
    rows.sort(
        key=lambda row: (
            row.kind.casefold(),
            row.name.casefold(),
            0 if row.location.evidence_type == "entity_location" else 1,
            row.location.source_name.casefold(),
            row.location.label.casefold(),
            row.location.source_line or 0,
        )
    )
    return rows[:per_source]


def build_zone_context(
    db: Database,
    zone_token: str,
    *,
    location_limit: int = 500,
) -> tuple[ZoneContext | None, str]:
    """Resolve one canonical zone and project its attached shipped knowledge.

    No rows are written and no source-specific builder is invoked. The same function
    therefore works against both the writable builder database and finalized packaged
    ``RuntimeDatabase`` views.
    """
    resolution = ZoneIdentityIndex(db).resolve(zone_token)
    if resolution.identity is None:
        return None, resolution.status

    identity = resolution.identity
    entity = db.entity(identity.entity_id)
    if entity is None:
        return None, "unresolved"
    try:
        data = json.loads(entity["data_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    maps = tuple(ZoneMapCatalog(db).maps_for_zone(identity.entity_id))
    connections = tuple(_connections_for_zone(db, identity.entity_id))
    locations = tuple(
        _locations_for_zone(
            db,
            identity.entity_id,
            limit=max(1, int(location_limit)),
        )
    )
    return (
        ZoneContext(
            identity=identity,
            resolution_kind=resolution.match_kind,
            resolution_reason=resolution.reason,
            level_min=(
                int(entity["level_min"])
                if entity["level_min"] is not None
                else None
            ),
            level_max=(
                int(entity["level_max"])
                if entity["level_max"] is not None
                else None
            ),
            data=data,
            maps=maps,
            connections=connections,
            locations=locations,
        ),
        "linked",
    )


def zone_context_text(
    db: Database,
    zone_token: str,
    *,
    location_limit: int = 25,
) -> str:
    """Compact text rendering suitable for future UI/guidance surfaces."""
    context, status = build_zone_context(
        db,
        zone_token,
        location_limit=max(1, int(location_limit)),
    )
    if context is None:
        if status == "ambiguous":
            return f"ZONE | {zone_token} | ambiguous canonical zone identity"
        return f"ZONE | {zone_token} | no canonical zone identity"

    identity = context.identity
    lines = [
        f"ZONE | {identity.name}",
        f"Resolved by: {context.resolution_reason}",
    ]
    if identity.client_zone_ids:
        lines.append("EQ zone ID: " + ", ".join(identity.client_zone_ids))
    if context.level_min is not None or context.level_max is not None:
        lines.append(
            "Level range: "
            f"{context.level_min if context.level_min is not None else '?'} - "
            f"{context.level_max if context.level_max is not None else '?'}"
        )
    if identity.aliases:
        lines.append("Aliases: " + ", ".join(identity.aliases))

    if context.maps:
        lines += ["", "Map bindings:"]
        for binding in context.maps:
            version = f" {binding.source_version}" if binding.source_version else ""
            lines.append(f"  • {binding.source_name}{version}: {binding.map_stem}")

    if context.connections:
        lines += ["", "Travel connections:"]
        arrows = {"outgoing": "→", "incoming": "←", "bidirectional": "↔"}
        for connection in context.connections:
            arrow = arrows.get(connection.direction, "-")
            usability = "" if connection.usable_from_zone else " | incoming only"
            source = connection.source_name or connection.source_kind or "knowledge"
            lines.append(
                f"  • {arrow} {connection.neighbor_zone_name} | "
                f"{connection.connection_kind.replace('_', ' ')} | {source}{usability}"
            )

    if context.locations:
        lines += ["", f"Confirmed located entities: {context.entity_count}"]
        for row in context.locations[: max(1, int(location_limit))]:
            loc = row.location.loc_text or "location known"
            source = row.location.source_label
            lines.append(f"  • [{row.kind}] {row.name} | {loc} | {source}")

    return "\n".join(lines)
