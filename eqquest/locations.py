from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from .db import Database
from .eqmap import map_to_game
from .location_actionability import location_actionability_note


@dataclass(frozen=True, slots=True)
class LocationEvidence:
    """One provenance-bearing statement that an entity is at a location.

    Coordinates are always exposed in EverQuestie's normalized game coordinate
    system (X, Y, Z). EverQuest prints those as `/loc Y, X, Z`.

    ``zone_entity_id`` is a canonical gameplay-zone ID only when the stored source
    zone can be projected safely. ``source_zone_entity_id`` preserves the original
    provider-zone ID for provenance/debugging. A provider location can therefore
    remain visible evidence without becoming a map/navigation target.
    """

    entity_id: int
    zone_entity_id: int | None
    zone_name: str
    x: float | None
    y: float | None
    z: float | None
    label: str
    evidence_type: str
    source_name: str
    source_version: str
    source_key: str
    source_page_id: int | None = None
    evidence: str = ""
    map_label_id: int | None = None
    map_stem: str = ""
    layer: int | None = None
    source_line: int | None = None
    source_zone_entity_id: int | None = None
    source_zone_name: str = ""
    zone_projection_status: str = ""

    @property
    def source_label(self) -> str:
        source = self.source_name or (
            "Map catalog" if self.evidence_type == "map_label" else "Knowledge"
        )
        if self.source_version:
            source += f" {self.source_version}"
        return source

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

    @property
    def navigable(self) -> bool:
        return self.zone_entity_id is not None and self.x is not None and self.y is not None


def _relation_exists(db: Database, name: str) -> bool:
    """Probe both builder main tables and RuntimeDatabase TEMP knowledge views."""
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


def _project_source_zone(
    db: Database,
    zone_entity_id: int | None,
    source_zone_name: str,
) -> tuple[int | None, str, str, int | None]:
    """Project one stored zone into gameplay identity without guessing.

    Returns ``(gameplay_zone_id, display_zone_name, status, source_zone_id)``.
    ``source_zone_id`` is set only when the stored zone is a non-canonical provider
    entity, including candidate/unresolved cases.
    """
    if zone_entity_id is None:
        return None, source_zone_name, "unknown_zone", None

    zone_id = int(zone_entity_id)
    zone = db.entity(zone_id)
    zone_name = str(zone["name"] or source_zone_name) if zone is not None else source_zone_name

    if _relation_exists(db, "entity_external_ids"):
        client = db.conn.execute(
            """
            SELECT 1 FROM entity_external_ids
            WHERE entity_id=? AND namespace='eqclient:zone'
            LIMIT 1
            """,
            (zone_id,),
        ).fetchone()
        if client is not None:
            return zone_id, zone_name, "canonical", None

    if _relation_exists(db, "zone_provider_bindings"):
        binding = db.conn.execute(
            """
            SELECT status,gameplay_zone_entity_id,gameplay_zone_name
            FROM zone_provider_bindings
            WHERE provider_zone_entity_id=?
            """,
            (zone_id,),
        ).fetchone()
        if binding is not None:
            status = str(binding["status"] or "unresolved")
            if status == "linked" and binding["gameplay_zone_entity_id"] is not None:
                return (
                    int(binding["gameplay_zone_entity_id"]),
                    str(binding["gameplay_zone_name"] or zone_name),
                    "linked_provider",
                    zone_id,
                )
            return None, zone_name, f"provider_{status}", zone_id

    # A zone without client identity and without a finalized provider binding is still
    # valid source evidence, but it is not safe gameplay identity.
    return None, zone_name, "provider_unmapped", zone_id


def _provider_locations(db: Database, entity_id: int) -> list[LocationEvidence]:
    rows = db.conn.execute(
        """
        SELECT l.id,l.entity_id,l.zone_entity_id,l.x,l.y,l.z,l.label,
               l.source_page_id,l.evidence,
               z.name AS zone_name,
               sp.source_name,sp.source_version,sp.source_key,sp.url
        FROM entity_locations l
        LEFT JOIN entities z ON z.id=l.zone_entity_id
        LEFT JOIN source_pages sp ON sp.id=l.source_page_id
        WHERE l.entity_id=?
        ORDER BY CASE WHEN l.zone_entity_id IS NULL THEN 1 ELSE 0 END,
                 z.name,l.id
        """,
        (int(entity_id),),
    ).fetchall()
    result: list[LocationEvidence] = []
    for row in rows:
        stored_zone_id = (
            int(row["zone_entity_id"])
            if row["zone_entity_id"] is not None
            else None
        )
        stored_zone_name = str(row["zone_name"] or "")
        gameplay_zone_id, display_zone_name, status, source_zone_id = _project_source_zone(
            db,
            stored_zone_id,
            stored_zone_name,
        )
        source_key = str(row["source_key"] or row["url"] or "")
        result.append(
            LocationEvidence(
                entity_id=int(row["entity_id"]),
                zone_entity_id=gameplay_zone_id,
                zone_name=display_zone_name,
                x=(float(row["x"]) if row["x"] is not None else None),
                y=(float(row["y"]) if row["y"] is not None else None),
                z=(float(row["z"]) if row["z"] is not None else None),
                label=str(row["label"] or ""),
                evidence_type="entity_location",
                source_name=str(row["source_name"] or "EverQuestie knowledge"),
                source_version=str(row["source_version"] or ""),
                source_key=source_key,
                source_page_id=(
                    int(row["source_page_id"])
                    if row["source_page_id"] is not None
                    else None
                ),
                evidence=str(row["evidence"] or ""),
                source_zone_entity_id=source_zone_id,
                source_zone_name=(stored_zone_name if source_zone_id is not None else ""),
                zone_projection_status=status,
            )
        )
    return result


def _map_locations(db: Database, entity_id: int) -> list[LocationEvidence]:
    if not (_relation_exists(db, "map_labels") and _relation_exists(db, "map_sources")):
        return []

    has_zone_bindings = _relation_exists(db, "zone_map_bindings")
    if has_zone_bindings:
        sql = """
            SELECT ml.id,ml.linked_entity_id,ml.map_stem,ml.zone_name,ml.layer,
                   ml.source_line,ml.raw_text,ml.x,ml.y,ml.z,ml.link_reason,
                   ms.source_name,ms.source_version,ms.source_key,
                   zmb.zone_entity_id AS canonical_zone_entity_id,
                   zmb.zone_name AS canonical_zone_name
            FROM map_labels ml
            JOIN map_sources ms ON ms.id=ml.source_id
            LEFT JOIN zone_map_bindings zmb
              ON zmb.source_name=ms.source_name
             AND zmb.map_stem=ml.map_stem
             AND zmb.status='linked'
            WHERE ml.linked_entity_id=? AND ml.link_status='linked'
            ORDER BY COALESCE(zmb.zone_name,ml.zone_name),
                     ms.source_name,ml.map_stem,ml.layer,ml.source_line
        """
    else:
        sql = """
            SELECT ml.id,ml.linked_entity_id,ml.map_stem,ml.zone_name,ml.layer,
                   ml.source_line,ml.raw_text,ml.x,ml.y,ml.z,ml.link_reason,
                   ms.source_name,ms.source_version,ms.source_key,
                   NULL AS canonical_zone_entity_id,
                   '' AS canonical_zone_name
            FROM map_labels ml
            JOIN map_sources ms ON ms.id=ml.source_id
            WHERE ml.linked_entity_id=? AND ml.link_status='linked'
            ORDER BY ml.zone_name,ms.source_name,ml.map_stem,ml.layer,ml.source_line
        """

    try:
        rows = db.conn.execute(sql, (int(entity_id),)).fetchall()
    except sqlite3.OperationalError:
        # Old development databases may predate one of the portable map columns.
        # They remain usable through entity_locations rather than causing WHERE/entity
        # details to fail altogether.
        return []

    result: list[LocationEvidence] = []
    for row in rows:
        game_x, game_y, game_z = map_to_game(
            float(row["x"]), float(row["y"]), float(row["z"])
        )
        canonical_zone_id = (
            int(row["canonical_zone_entity_id"])
            if row["canonical_zone_entity_id"] is not None
            else None
        )
        zone_name = str(row["canonical_zone_name"] or row["zone_name"] or row["map_stem"])
        result.append(
            LocationEvidence(
                entity_id=int(row["linked_entity_id"]),
                zone_entity_id=canonical_zone_id,
                zone_name=zone_name,
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
                zone_projection_status=("canonical_map" if canonical_zone_id is not None else "map_unresolved"),
            )
        )
    return result


def location_evidence_for_entity(
    db: Database,
    entity_id: int,
    *,
    include_provider: bool = True,
    include_maps: bool = True,
) -> list[LocationEvidence]:
    """Return all confirmed location evidence for one canonical entity.

    Ambiguous/unresolved map labels are intentionally excluded. Provider/importer
    locations remain visible even when their zone cannot be projected, but only
    safely canonicalized locations expose ``zone_entity_id`` / ``navigable=True``.
    """
    result: list[LocationEvidence] = []
    if include_provider:
        result.extend(_provider_locations(db, entity_id))
    if include_maps:
        result.extend(_map_locations(db, entity_id))
    return sorted(
        result,
        key=lambda loc: (
            1 if not loc.zone_name else 0,
            loc.zone_name.casefold(),
            0 if loc.evidence_type == "entity_location" else 1,
            loc.source_name.casefold(),
            loc.label.casefold(),
            loc.source_line or 0,
        ),
    )


def location_evidence_for_term(
    db: Database,
    term: str,
    *,
    kind: str | None = None,
) -> tuple[object | None, str, list[LocationEvidence]]:
    """Resolve a canonical entity and return its unified locations.

    The return shape mirrors ``Database.resolve_entity``: ``(entity, status, rows)``.
    Ambiguous/missing terms return no location rows rather than guessing an identity.
    """
    entity, status = db.resolve_entity(term, kind)
    if entity is None:
        return None, status, []
    return entity, status, location_evidence_for_entity(db, int(entity["id"]))


def _display_label(value: str) -> str:
    return " ".join((value or "").replace("_", " ").split()).strip()


def _location_line(location: LocationEvidence, *, prefix: str = "") -> str:
    zone = location.zone_name or "unknown zone"
    coordinate = location.loc_text or "location known"
    label = _display_label(location.label)
    details = [zone, coordinate]
    if label:
        details.append(label)
    if location.source_label:
        details.append(location.source_label)
    actionability_note = location_actionability_note(location)
    if actionability_note:
        details.append(actionability_note)
    elif not location.navigable and location.zone_projection_status in {
        "provider_candidate",
        "provider_ambiguous",
        "provider_unresolved",
        "provider_unmapped",
        "map_unresolved",
    }:
        details.append(f"{location.zone_projection_status}; not map-targetable")
    return prefix + " | ".join(details)


def where_text(db: Database, entity_id: int, current_zone: str | None = None) -> str:
    """Render WHERE using every confirmed location source through one API.

    Provider locations are projected into canonical gameplay zones only through
    finalized linked provider-zone bindings. Candidate/unresolved provider facts remain
    visible and sourced but cannot masquerade as map/navigation targets. Canonical
    coordinates without reviewed provenance remain visible as evidence-only rows.
    """
    entity = db.entity(entity_id)
    if not entity:
        return "Entity not found."

    lines = [f"WHERE | [{entity['kind']}] {entity['name']}"]
    locations = location_evidence_for_entity(db, entity_id)

    if entity["kind"] == "zone":
        lines.append(f"Zone: {entity['name']}")
        for target in db.relationship_targets(entity_id, "connected_to"):
            try:
                rel_data = json.loads(target["relationship_data_json"] or "{}")
            except json.JSONDecodeError:
                rel_data = {}
            direction = rel_data.get("direction")
            lines.append(
                f"Connects: {target['name']}" + (f" | {direction}" if direction else "")
            )
    elif entity["zone"]:
        lines.append(f"Zone: {entity['zone']}")

    for location in locations:
        lines.append(_location_line(location))

    if entity["kind"] == "item":
        for relation, preferred_label in (
            ("drops_from", "quest target"),
            ("turn_in_to", "turn-in"),
        ):
            relation_name = "Drops from" if relation == "drops_from" else "Turn in to"
            for target in db.relationship_targets(entity_id, relation):
                target_locations = location_evidence_for_entity(db, int(target["id"]))
                preferred = [
                    location
                    for location in target_locations
                    if location.label.casefold() == preferred_label
                ]
                if preferred:
                    target_locations = preferred
                if target_locations:
                    for location in target_locations:
                        lines.append(
                            _location_line(
                                location,
                                prefix=f"{relation_name}: {target['name']} | ",
                            )
                        )
                else:
                    try:
                        rel_data = json.loads(target["relationship_data_json"] or "{}")
                    except json.JSONDecodeError:
                        rel_data = {}
                    zone = rel_data.get("zone")
                    lines.append(
                        f"{relation_name}: {target['name']}" + (f" | {zone}" if zone else "")
                    )

        direct_zones = [
            zone["name"] for zone in db.relationship_targets(entity_id, "found_in")
        ]
        if direct_zones:
            lines.append("Found in zones: " + ", ".join(dict.fromkeys(direct_zones)))

    if entity["kind"] == "quest":
        for starter in db.relationship_targets(entity_id, "started_by"):
            starter_locations = location_evidence_for_entity(db, int(starter["id"]))
            preferred = [
                location
                for location in starter_locations
                if location.label.casefold() == "quest starter"
            ]
            if preferred:
                starter_locations = preferred
            for location in starter_locations:
                lines.append(
                    _location_line(
                        location,
                        prefix=f"Starter: {starter['name']} | ",
                    )
                )

    if len(lines) == 1:
        zones: list[str] = []
        for relation in db.relationships_for_entity(entity_id):
            if relation["relation"] != "occurs_in":
                continue
            zone_name = (
                relation["target_name"]
                if relation["direction"] == "out"
                else relation["source_name"]
            )
            zones.append(zone_name)
        if zones:
            lines.append("Related zone: " + ", ".join(dict.fromkeys(zones)))
        else:
            lines.append("No confirmed location is known yet.")

    if current_zone:
        lines.append(f"Current zone: {current_zone}")

    return "\n".join(lines)