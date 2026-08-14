from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .db import Database


ZONE_COVERAGE_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ZoneCoverageRow:
    entity_id: int
    name: str
    has_client_identity: bool
    has_level_data: bool
    map_bindings: int
    travel_outgoing: int
    travel_incoming: int
    source_count: int
    alias_count: int

    @property
    def has_map(self) -> bool:
        return self.map_bindings > 0

    @property
    def has_travel(self) -> bool:
        return self.travel_outgoing > 0 or self.travel_incoming > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "has_client_identity": self.has_client_identity,
            "has_level_data": self.has_level_data,
            "map_bindings": self.map_bindings,
            "travel_outgoing": self.travel_outgoing,
            "travel_incoming": self.travel_incoming,
            "source_count": self.source_count,
            "alias_count": self.alias_count,
        }


@dataclass(frozen=True, slots=True)
class ZoneCoverageSummary:
    zones: int
    client_identity: int
    level_data: int
    mapped: int
    travel_connected: int
    isolated: int
    map_bindings_linked: int
    map_bindings_ambiguous: int
    map_bindings_unresolved: int
    travel_edges_linked: int
    travel_edges_ambiguous: int
    travel_edges_unresolved: int
    zones_without_client_identity: tuple[str, ...]
    zones_without_maps: tuple[str, ...]
    zones_without_travel: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "coverage_version": ZONE_COVERAGE_VERSION,
            "zones": self.zones,
            "client_identity": self.client_identity,
            "level_data": self.level_data,
            "mapped": self.mapped,
            "travel_connected": self.travel_connected,
            "isolated": self.isolated,
            "map_bindings_linked": self.map_bindings_linked,
            "map_bindings_ambiguous": self.map_bindings_ambiguous,
            "map_bindings_unresolved": self.map_bindings_unresolved,
            "travel_edges_linked": self.travel_edges_linked,
            "travel_edges_ambiguous": self.travel_edges_ambiguous,
            "travel_edges_unresolved": self.travel_edges_unresolved,
            "zones_without_client_identity": list(self.zones_without_client_identity),
            "zones_without_maps": list(self.zones_without_maps),
            "zones_without_travel": list(self.zones_without_travel),
        }


class ZoneCoverageCatalog:
    """Measure how much canonical zone knowledge each build can actually support.

    This is deliberately an audit/projection over existing canonical tables rather
    than another zone database. A zone remains one ``entities(kind='zone')`` row;
    client IDs, map bindings, travel topology, aliases, level data and future source
    evidence accumulate around that same entity.
    """

    def __init__(self, db: Database):
        self.db = db

    def _object_exists(self, name: str) -> bool:
        return self.db.conn.execute(
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

    def rows(self) -> list[ZoneCoverageRow]:
        map_available = self._object_exists("zone_map_bindings")
        travel_available = self._object_exists("zone_travel_edges")

        map_expr = (
            "(SELECT COUNT(*) FROM zone_map_bindings zmb "
            " WHERE zmb.zone_entity_id=e.id AND zmb.status='linked')"
            if map_available
            else "0"
        )
        outgoing_expr = (
            "(SELECT COUNT(*) FROM zone_travel_edges zte "
            " WHERE zte.source_zone_entity_id=e.id AND zte.status='linked' "
            "   AND zte.target_zone_entity_id IS NOT NULL)"
            if travel_available
            else "0"
        )
        incoming_expr = (
            "(SELECT COUNT(*) FROM zone_travel_edges zte "
            " WHERE zte.target_zone_entity_id=e.id AND zte.status='linked')"
            if travel_available
            else "0"
        )

        result = []
        for row in self.db.conn.execute(
            f"""
            SELECT e.id,e.name,e.level_min,e.level_max,
                   EXISTS(
                       SELECT 1 FROM entity_external_ids x
                       WHERE x.entity_id=e.id AND x.namespace='eqclient:zone'
                   ) AS has_client_identity,
                   {map_expr} AS map_bindings,
                   {outgoing_expr} AS travel_outgoing,
                   {incoming_expr} AS travel_incoming,
                   (SELECT COUNT(*) FROM entity_sources es WHERE es.entity_id=e.id) AS source_count,
                   (SELECT COUNT(*) FROM entity_aliases ea WHERE ea.entity_id=e.id) AS alias_count
            FROM entities e
            WHERE e.kind='zone'
            ORDER BY e.name,e.id
            """
        ).fetchall():
            result.append(
                ZoneCoverageRow(
                    entity_id=int(row["id"]),
                    name=str(row["name"]),
                    has_client_identity=bool(row["has_client_identity"]),
                    has_level_data=row["level_min"] is not None or row["level_max"] is not None,
                    map_bindings=int(row["map_bindings"] or 0),
                    travel_outgoing=int(row["travel_outgoing"] or 0),
                    travel_incoming=int(row["travel_incoming"] or 0),
                    source_count=int(row["source_count"] or 0),
                    alias_count=int(row["alias_count"] or 0),
                )
            )
        return result

    def _status_counts(self, table: str) -> dict[str, int]:
        if not self._object_exists(table):
            return {"linked": 0, "ambiguous": 0, "unresolved": 0}
        rows = self.db.conn.execute(
            f"SELECT status,COUNT(*) AS count FROM {table} GROUP BY status"
        ).fetchall()
        counts = {"linked": 0, "ambiguous": 0, "unresolved": 0}
        for row in rows:
            status = str(row["status"] or "")
            if status in counts:
                counts[status] = int(row["count"] or 0)
        return counts

    def summary(self) -> ZoneCoverageSummary:
        rows = self.rows()
        maps = self._status_counts("zone_map_bindings")
        travel = self._status_counts("zone_travel_edges")
        no_client = tuple(row.name for row in rows if not row.has_client_identity)
        no_maps = tuple(row.name for row in rows if not row.has_map)
        no_travel = tuple(row.name for row in rows if not row.has_travel)
        return ZoneCoverageSummary(
            zones=len(rows),
            client_identity=sum(row.has_client_identity for row in rows),
            level_data=sum(row.has_level_data for row in rows),
            mapped=sum(row.has_map for row in rows),
            travel_connected=sum(row.has_travel for row in rows),
            isolated=sum(not row.has_map and not row.has_travel for row in rows),
            map_bindings_linked=maps["linked"],
            map_bindings_ambiguous=maps["ambiguous"],
            map_bindings_unresolved=maps["unresolved"],
            travel_edges_linked=travel["linked"],
            travel_edges_ambiguous=travel["ambiguous"],
            travel_edges_unresolved=travel["unresolved"],
            zones_without_client_identity=no_client,
            zones_without_maps=no_maps,
            zones_without_travel=no_travel,
        )

    def compile_summary(self) -> ZoneCoverageSummary:
        """Persist release coverage metadata without creating another zone identity table."""
        if not getattr(self.db, "knowledge_writable", True):
            raise RuntimeError("zone coverage compilation is builder-only")
        summary = self.summary()
        self.db.set_meta("zone_coverage_version", ZONE_COVERAGE_VERSION)
        self.db.set_meta(
            "zone_catalog_coverage",
            json.dumps(summary.as_dict(), ensure_ascii=False, sort_keys=True),
        )
        return summary


def zone_coverage_audit_text(db: Database, *, detail_limit: int = 30) -> str:
    summary = ZoneCoverageCatalog(db).summary()
    lines = [
        f"Zone coverage v{ZONE_COVERAGE_VERSION}",
        "",
        f"Canonical zones: {summary.zones}",
        f"EQ-client identities: {summary.client_identity}/{summary.zones}",
        f"Zones with client level fields: {summary.level_data}/{summary.zones}",
        f"Zones with confirmed map binding: {summary.mapped}/{summary.zones}",
        f"Zones connected to confirmed travel: {summary.travel_connected}/{summary.zones}",
        f"Zones with neither map nor travel evidence: {summary.isolated}/{summary.zones}",
        "",
        "Map evidence: "
        f"linked={summary.map_bindings_linked}, "
        f"ambiguous={summary.map_bindings_ambiguous}, "
        f"unresolved={summary.map_bindings_unresolved}",
        "Travel evidence: "
        f"linked={summary.travel_edges_linked}, "
        f"ambiguous={summary.travel_edges_ambiguous}, "
        f"unresolved={summary.travel_edges_unresolved}",
    ]

    def add_gap(label: str, names: tuple[str, ...]) -> None:
        if not names:
            return
        visible = names[: max(0, int(detail_limit))]
        suffix = f" (+{len(names) - len(visible)} more)" if len(visible) < len(names) else ""
        lines.append("")
        lines.append(f"{label} ({len(names)}): " + ", ".join(visible) + suffix)

    add_gap("Zones without EQ-client identity", summary.zones_without_client_identity)
    add_gap("Zones without confirmed map binding", summary.zones_without_maps)
    add_gap("Zones without confirmed travel", summary.zones_without_travel)
    return "\n".join(lines)
