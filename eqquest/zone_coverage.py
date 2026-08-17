from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .db import Database
from .travel_coordinate_actionability import travel_coordinate_source_owns_point


ZONE_COVERAGE_VERSION = "3"


@dataclass(frozen=True, slots=True)
class ZoneCoverageRow:
    entity_id: int
    name: str
    has_client_identity: bool
    has_level_data: bool
    map_bindings: int
    travel_outgoing: int
    travel_incoming: int
    route_outgoing: int
    route_outgoing_mappable: int
    source_count: int
    alias_count: int

    @property
    def has_map(self) -> bool:
        return self.map_bindings > 0

    @property
    def has_travel(self) -> bool:
        return self.travel_outgoing > 0 or self.travel_incoming > 0

    @property
    def has_route_outgoing(self) -> bool:
        return self.route_outgoing > 0

    @property
    def has_mappable_route_exit(self) -> bool:
        return self.route_outgoing_mappable > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "has_client_identity": self.has_client_identity,
            "has_level_data": self.has_level_data,
            "map_bindings": self.map_bindings,
            "travel_outgoing": self.travel_outgoing,
            "travel_incoming": self.travel_incoming,
            "route_outgoing": self.route_outgoing,
            "route_outgoing_mappable": self.route_outgoing_mappable,
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
    travel_edges_with_source_coordinates: int
    travel_edges_without_source_coordinates: int
    route_directions_linked: int
    route_directions_mappable: int
    route_directions_unmappable: int
    zones_with_mappable_route_exit: int
    route_zones: int
    route_weak_components: int
    largest_weak_route_component: int
    route_strong_components: int
    largest_strong_route_component: int
    zones_without_client_identity: tuple[str, ...]
    zones_without_maps: tuple[str, ...]
    zones_without_travel: tuple[str, ...]
    zones_with_route_but_no_mappable_exit: tuple[str, ...]
    route_sink_zones: tuple[str, ...]

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
            "travel_edges_with_source_coordinates": self.travel_edges_with_source_coordinates,
            "travel_edges_without_source_coordinates": self.travel_edges_without_source_coordinates,
            "route_directions_linked": self.route_directions_linked,
            "route_directions_mappable": self.route_directions_mappable,
            "route_directions_unmappable": self.route_directions_unmappable,
            "zones_with_mappable_route_exit": self.zones_with_mappable_route_exit,
            "route_zones": self.route_zones,
            "route_weak_components": self.route_weak_components,
            "largest_weak_route_component": self.largest_weak_route_component,
            "route_strong_components": self.route_strong_components,
            "largest_strong_route_component": self.largest_strong_route_component,
            "zones_without_client_identity": list(self.zones_without_client_identity),
            "zones_without_maps": list(self.zones_without_maps),
            "zones_without_travel": list(self.zones_without_travel),
            "zones_with_route_but_no_mappable_exit": list(
                self.zones_with_route_but_no_mappable_exit
            ),
            "route_sink_zones": list(self.route_sink_zones),
        }


class ZoneCoverageCatalog:
    """Measure how much canonical zone knowledge each build can actually support.

    This is deliberately an audit/projection over existing canonical tables rather
    than another zone database. A zone remains one ``entities(kind='zone')`` row;
    client IDs, map bindings, travel topology, aliases, level data and future source
    evidence accumulate around that same entity.

    Travel evidence rows and player-usable route directions are intentionally audited
    separately. One bidirectional evidence row creates two traversable directions, but
    its stored X/Y belongs only to the row's canonical source zone. A route direction
    becomes mappable only when the coordinate is also owned by a coordinate-bearing
    source compiler, currently the exact map-label record that supplied the travel point.
    Merely populating X/Y on generic provider topology never upgrades it to map evidence.

    Route connectivity is also measured separately from raw edge counts. Weakly
    connected components expose disconnected navigation islands while strongly
    connected components expose mutual reachability under the graph's actual directed
    semantics. Neither metric invents reverse travel for a one-way edge.
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

    def _route_direction_sets(self) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
        routes: dict[int, set[int]] = {}
        mappable: dict[int, set[int]] = {}
        if not self._object_exists("zone_travel_edges"):
            return routes, mappable

        rows = self.db.conn.execute(
            """
            SELECT source_zone_entity_id,target_zone_entity_id,bidirectional,
                   source_kind,x,y
            FROM zone_travel_edges
            WHERE status='linked' AND target_zone_entity_id IS NOT NULL
            """
        ).fetchall()
        for row in rows:
            source_id = int(row["source_zone_entity_id"])
            target_id = int(row["target_zone_entity_id"])
            routes.setdefault(source_id, set()).add(target_id)
            if travel_coordinate_source_owns_point(
                str(row["source_kind"] or ""),
                row["x"],
                row["y"],
            ):
                # Source-owned travel coordinates belong only to the stored edge source.
                mappable.setdefault(source_id, set()).add(target_id)
            if bool(row["bidirectional"]):
                # Topology is usable in reverse, but the stored coordinate is not.
                routes.setdefault(target_id, set()).add(source_id)
        return routes, mappable

    @staticmethod
    def _route_graph_metrics(
        route_targets: dict[int, set[int]],
    ) -> tuple[set[int], list[set[int]], list[set[int]], set[int]]:
        """Return route nodes, weak components, strong components and directed sinks."""
        nodes: set[int] = set(route_targets)
        for targets in route_targets.values():
            nodes.update(targets)
        if not nodes:
            return set(), [], [], set()

        directed = {node: set(route_targets.get(node, ())) for node in nodes}
        reverse = {node: set() for node in nodes}
        weak = {node: set() for node in nodes}
        for source, targets in directed.items():
            for target in targets:
                reverse[target].add(source)
                weak[source].add(target)
                weak[target].add(source)

        weak_components: list[set[int]] = []
        seen: set[int] = set()
        for start in sorted(nodes):
            if start in seen:
                continue
            component: set[int] = set()
            stack = [start]
            seen.add(start)
            while stack:
                node = stack.pop()
                component.add(node)
                for neighbor in weak[node]:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
            weak_components.append(component)

        # Kosaraju without recursion so a future zone corpus cannot hit Python's
        # recursion limit merely because one route chain grows very long.
        finish_order: list[int] = []
        seen.clear()
        for start in sorted(nodes):
            if start in seen:
                continue
            stack: list[tuple[int, bool]] = [(start, False)]
            while stack:
                node, expanded = stack.pop()
                if expanded:
                    finish_order.append(node)
                    continue
                if node in seen:
                    continue
                seen.add(node)
                stack.append((node, True))
                for neighbor in sorted(directed[node], reverse=True):
                    if neighbor not in seen:
                        stack.append((neighbor, False))

        strong_components: list[set[int]] = []
        seen.clear()
        for start in reversed(finish_order):
            if start in seen:
                continue
            component: set[int] = set()
            stack = [start]
            seen.add(start)
            while stack:
                node = stack.pop()
                component.add(node)
                for neighbor in reverse[node]:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
            strong_components.append(component)

        sinks = {
            node
            for node in nodes
            if reverse[node] and not directed[node]
        }
        return nodes, weak_components, strong_components, sinks

    def rows(self) -> list[ZoneCoverageRow]:
        map_available = self._object_exists("zone_map_bindings")
        travel_available = self._object_exists("zone_travel_edges")
        route_targets, mappable_targets = self._route_direction_sets()

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
            entity_id = int(row["id"])
            result.append(
                ZoneCoverageRow(
                    entity_id=entity_id,
                    name=str(row["name"]),
                    has_client_identity=bool(row["has_client_identity"]),
                    has_level_data=row["level_min"] is not None or row["level_max"] is not None,
                    map_bindings=int(row["map_bindings"] or 0),
                    travel_outgoing=int(row["travel_outgoing"] or 0),
                    travel_incoming=int(row["travel_incoming"] or 0),
                    route_outgoing=len(route_targets.get(entity_id, ())),
                    route_outgoing_mappable=len(mappable_targets.get(entity_id, ())),
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

    def _travel_coordinate_counts(self) -> tuple[int, int]:
        if not self._object_exists("zone_travel_edges"):
            return 0, 0
        rows = self.db.conn.execute(
            """
            SELECT source_kind,x,y
            FROM zone_travel_edges
            WHERE status='linked' AND target_zone_entity_id IS NOT NULL
            """
        ).fetchall()
        present = sum(
            travel_coordinate_source_owns_point(
                str(row["source_kind"] or ""),
                row["x"],
                row["y"],
            )
            for row in rows
        )
        return int(present), max(0, len(rows) - int(present))

    def summary(self) -> ZoneCoverageSummary:
        rows = self.rows()
        maps = self._status_counts("zone_map_bindings")
        travel = self._status_counts("zone_travel_edges")
        coordinate_present, coordinate_missing = self._travel_coordinate_counts()
        route_targets, mappable_targets = self._route_direction_sets()
        route_nodes, weak_components, strong_components, sink_ids = self._route_graph_metrics(
            route_targets
        )
        route_directions = sum(len(targets) for targets in route_targets.values())
        mappable_directions = sum(len(targets) for targets in mappable_targets.values())
        no_client = tuple(row.name for row in rows if not row.has_client_identity)
        no_maps = tuple(row.name for row in rows if not row.has_map)
        no_travel = tuple(row.name for row in rows if not row.has_travel)
        route_coordinate_gaps = tuple(
            row.name
            for row in rows
            if row.has_route_outgoing and not row.has_mappable_route_exit
        )
        name_by_id = {row.entity_id: row.name for row in rows}
        sink_names = tuple(
            sorted(name_by_id[entity_id] for entity_id in sink_ids if entity_id in name_by_id)
        )
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
            travel_edges_with_source_coordinates=coordinate_present,
            travel_edges_without_source_coordinates=coordinate_missing,
            route_directions_linked=route_directions,
            route_directions_mappable=mappable_directions,
            route_directions_unmappable=max(0, route_directions - mappable_directions),
            zones_with_mappable_route_exit=sum(row.has_mappable_route_exit for row in rows),
            route_zones=len(route_nodes),
            route_weak_components=len(weak_components),
            largest_weak_route_component=max((len(component) for component in weak_components), default=0),
            route_strong_components=len(strong_components),
            largest_strong_route_component=max((len(component) for component in strong_components), default=0),
            zones_without_client_identity=no_client,
            zones_without_maps=no_maps,
            zones_without_travel=no_travel,
            zones_with_route_but_no_mappable_exit=route_coordinate_gaps,
            route_sink_zones=sink_names,
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
        f"Zones with mappable route exit: {summary.zones_with_mappable_route_exit}/{summary.zones}",
        f"Zones with neither map nor travel evidence: {summary.isolated}/{summary.zones}",
        "",
        "Map evidence: "
        f"linked={summary.map_bindings_linked}, "
        f"ambiguous={summary.map_bindings_ambiguous}, "
        f"unresolved={summary.map_bindings_unresolved}",
        "Travel evidence rows: "
        f"linked={summary.travel_edges_linked}, "
        f"ambiguous={summary.travel_edges_ambiguous}, "
        f"unresolved={summary.travel_edges_unresolved}",
        "Linked travel edge source-owned coordinates: "
        f"present={summary.travel_edges_with_source_coordinates}, "
        f"missing/unreviewed={summary.travel_edges_without_source_coordinates}",
        "Canonical route directions: "
        f"linked={summary.route_directions_linked}, "
        f"mappable={summary.route_directions_mappable}, "
        f"without reviewed source coordinate={summary.route_directions_unmappable}",
        "Route graph: "
        f"zones={summary.route_zones}/{summary.zones}, "
        f"weak components={summary.route_weak_components}, "
        f"largest weak component={summary.largest_weak_route_component}, "
        f"strong components={summary.route_strong_components}, "
        f"largest mutually reachable component={summary.largest_strong_route_component}",
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
    add_gap(
        "Zones with confirmed outgoing route but no mappable reviewed source coordinate",
        summary.zones_with_route_but_no_mappable_exit,
    )
    add_gap(
        "Directed route sinks (incoming route but no outgoing direction; some may be legitimate one-way destinations)",
        summary.route_sink_zones,
    )
    return "\n".join(lines)
