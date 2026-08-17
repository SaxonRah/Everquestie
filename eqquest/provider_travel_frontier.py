from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from typing import Any, Iterable

from .provider_zone_travel import ProviderZoneTravelCatalog
from .zone_authority import prefer_eqclient_zone_resolution
from .zone_identity import ZoneIdentityIndex


# Keep the default frontier current-live only. Historical/retired identities such as
# North Freeport remain available through explicit --zone requests.
DEFAULT_PROVIDER_TRAVEL_FRONTIER_ZONES: tuple[str, ...] = (
    "Labyrinth of Spite",
)


@dataclass(frozen=True, slots=True)
class ProviderTravelRelationshipDiagnostic:
    relationship_id: int
    source_provider_entity_id: int
    source_provider_name: str
    target_provider_entity_id: int
    target_provider_name: str
    source_page_id: int | None
    source_name: str
    source_key: str
    source_url: str
    evidence: str
    direction_raw: str
    direction_mode: str
    direction_reversed: bool
    direction_bidirectional: bool
    canonical_source_entity_id: int | None
    canonical_source_name: str
    canonical_target_entity_id: int | None
    canonical_target_name: str
    interpreted_source_entity_id: int | None
    interpreted_source_name: str
    interpreted_target_entity_id: int | None
    interpreted_target_name: str
    classification: str
    reason: str
    compiled_edge_id: int | None

    @property
    def compiler_eligible(self) -> bool:
        return self.classification in {"compiled", "compiler_eligible_missing_edge"}

    def as_dict(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
            if field != "reason"
        } | {"reason": self.reason}


@dataclass(frozen=True, slots=True)
class ProviderTravelZoneDiagnostic:
    query: str
    resolution_status: str
    resolution_reason: str
    canonical_zone_entity_id: int | None
    canonical_zone_name: str
    classification: str
    reason: str
    bindings: tuple[dict[str, Any], ...]
    relationships: tuple[ProviderTravelRelationshipDiagnostic, ...]
    canonical_edges: tuple[dict[str, Any], ...]

    @property
    def outgoing_count(self) -> int:
        return sum(edge["direction"] == "outgoing" for edge in self.canonical_edges)

    @property
    def incoming_count(self) -> int:
        return sum(edge["direction"] == "incoming" for edge in self.canonical_edges)

    @property
    def provider_source_page_count(self) -> int:
        return sum(binding.get("source_page_id") is not None for binding in self.bindings)

    @property
    def binding_status_counts(self) -> dict[str, int]:
        return dict(
            sorted(
                Counter(str(binding.get("status") or "unknown") for binding in self.bindings).items()
            )
        )

    @property
    def relationship_status_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(row.classification for row in self.relationships).items()))

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "resolution_status": self.resolution_status,
            "resolution_reason": self.resolution_reason,
            "canonical_zone_entity_id": self.canonical_zone_entity_id,
            "canonical_zone_name": self.canonical_zone_name,
            "classification": self.classification,
            "reason": self.reason,
            "binding_count": len(self.bindings),
            "binding_status_counts": self.binding_status_counts,
            "provider_source_page_count": self.provider_source_page_count,
            "relationship_count": len(self.relationships),
            "relationship_status_counts": self.relationship_status_counts,
            "compiler_eligible_relationship_count": sum(
                relationship.compiler_eligible for relationship in self.relationships
            ),
            "outgoing_count": self.outgoing_count,
            "incoming_count": self.incoming_count,
            "bindings": list(self.bindings),
            "relationships": [relationship.as_dict() for relationship in self.relationships],
            "canonical_edges": list(self.canonical_edges),
        }


@dataclass(frozen=True, slots=True)
class ProviderTravelFrontierSummary:
    zones: tuple[ProviderTravelZoneDiagnostic, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status_counts": dict(sorted(Counter(zone.classification for zone in self.zones).items())),
            "zones": [zone.as_dict() for zone in self.zones],
        }


class ProviderTravelFrontierAudit:
    """Read-only explanation of stored provider topology at the compiler boundary."""

    def __init__(self, db):
        self.db = db
        self.compiler = ProviderZoneTravelCatalog(db)

    def _exists(self, name: str) -> bool:
        return self.db.conn.execute(
            """
            SELECT 1 FROM sqlite_temp_master WHERE type IN ('table','view') AND name=?
            UNION ALL
            SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?
            LIMIT 1
            """,
            (name, name),
        ).fetchone() is not None

    def _zone_names(self) -> dict[int, str]:
        if not self._exists("entities"):
            return {}
        return {
            int(row["id"]): str(row["name"] or "")
            for row in self.db.conn.execute(
                "SELECT id,name FROM entities WHERE kind='zone' ORDER BY id"
            ).fetchall()
        }

    def _client_ids(self) -> set[int]:
        if not self._exists("entity_external_ids"):
            return set()
        return {
            int(row["entity_id"])
            for row in self.db.conn.execute(
                "SELECT DISTINCT entity_id FROM entity_external_ids WHERE namespace='eqclient:zone'"
            ).fetchall()
        }

    def _binding_map(self) -> dict[int, int]:
        if not self._exists("zone_provider_bindings"):
            return {}
        return {
            int(row["provider_zone_entity_id"]): int(row["gameplay_zone_entity_id"])
            for row in self.db.conn.execute(
                """
                SELECT provider_zone_entity_id,gameplay_zone_entity_id
                FROM zone_provider_bindings
                WHERE status='linked' AND gameplay_zone_entity_id IS NOT NULL
                """
            ).fetchall()
        }

    @staticmethod
    def _canonical(entity_id: int, client_ids: set[int], bindings: dict[int, int]) -> int | None:
        return int(entity_id) if int(entity_id) in client_ids else bindings.get(int(entity_id))

    def _compiled_relationships(self) -> dict[int, int]:
        if not self._exists("zone_travel_edges"):
            return {}
        result: dict[int, int] = {}
        for row in self.db.conn.execute(
            """
            SELECT id,data_json FROM zone_travel_edges
            WHERE source_kind='provider_zone_relationship' AND status='linked'
            ORDER BY id
            """
        ).fetchall():
            try:
                payload = json.loads(row["data_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("provider_relationship_id") is not None:
                result[int(payload["provider_relationship_id"])] = int(row["id"])
        return result

    def _bindings(self, canonical_zone_id: int) -> tuple[dict[str, Any], ...]:
        if not self._exists("zone_provider_bindings"):
            return ()
        has_pages = self._exists("source_pages")
        join = "LEFT JOIN entities pe ON pe.id=b.provider_zone_entity_id"
        if has_pages:
            join += " LEFT JOIN source_pages sp ON sp.id=pe.source_page_id"
        page_cols = (
            "sp.id AS source_page_id,sp.source_name,sp.source_kind,sp.source_key,"
            "sp.source_version,sp.url AS source_url"
            if has_pages
            else "NULL AS source_page_id,'' AS source_name,'' AS source_kind,'' AS source_key,"
            "'' AS source_version,'' AS source_url"
        )
        rows = self.db.conn.execute(
            f"""
            SELECT b.provider_zone_entity_id,b.gameplay_zone_entity_id,
                   b.provider_zone_name,b.gameplay_zone_name,b.status,b.reason,
                   b.corroboration_count,{page_cols}
            FROM zone_provider_bindings b {join}
            WHERE b.gameplay_zone_entity_id=?
            ORDER BY b.provider_zone_entity_id
            """,
            (int(canonical_zone_id),),
        ).fetchall()
        return tuple(
            {
                "provider_zone_entity_id": int(row["provider_zone_entity_id"]),
                "provider_zone_name": str(row["provider_zone_name"] or ""),
                "gameplay_zone_entity_id": int(row["gameplay_zone_entity_id"]),
                "gameplay_zone_name": str(row["gameplay_zone_name"] or ""),
                "status": str(row["status"] or ""),
                "reason": str(row["reason"] or ""),
                "corroboration_count": int(row["corroboration_count"] or 0),
                "source_page_id": int(row["source_page_id"]) if row["source_page_id"] is not None else None,
                "source_name": str(row["source_name"] or ""),
                "source_kind": str(row["source_kind"] or ""),
                "source_key": str(row["source_key"] or ""),
                "source_version": str(row["source_version"] or ""),
                "source_url": str(row["source_url"] or ""),
            }
            for row in rows
        )

    def _relationships(
        self,
        provider_ids: Iterable[int],
        *,
        names: dict[int, str],
        client_ids: set[int],
        bindings: dict[int, int],
        compiled: dict[int, int],
    ) -> tuple[ProviderTravelRelationshipDiagnostic, ...]:
        ids = tuple(sorted({int(value) for value in provider_ids}))
        if not ids or not self._exists("entity_relationships"):
            return ()
        marks = ",".join("?" for _ in ids)
        has_pages = self._exists("source_pages")
        join = "LEFT JOIN source_pages sp ON sp.id=r.source_page_id" if has_pages else ""
        page_cols = (
            "sp.id AS source_page_id,sp.source_name,sp.source_key,sp.url AS source_url"
            if has_pages
            else "NULL AS source_page_id,'' AS source_name,'' AS source_key,'' AS source_url"
        )
        rows = self.db.conn.execute(
            f"""
            SELECT r.id AS relationship_id,r.source_entity_id,r.target_entity_id,
                   r.evidence,r.data_json AS relationship_data_json,
                   se.name AS source_name_entity,te.name AS target_name,{page_cols}
            FROM entity_relationships r
            JOIN entities se ON se.id=r.source_entity_id
            JOIN entities te ON te.id=r.target_entity_id
            {join}
            WHERE r.relation='connected_to'
              AND (r.source_entity_id IN ({marks}) OR r.target_entity_id IN ({marks}))
            ORDER BY r.id
            """,
            ids + ids,
        ).fetchall()
        out: list[ProviderTravelRelationshipDiagnostic] = []
        for row in rows:
            relationship_id = int(row["relationship_id"])
            structured = self.compiler._structured_provider_relationship(row)
            direction = self.compiler._direction_semantics(row)
            provider_source = int(row["source_entity_id"])
            provider_target = int(row["target_entity_id"])
            canonical_source = self._canonical(provider_source, client_ids, bindings)
            canonical_target = self._canonical(provider_target, client_ids, bindings)
            interpreted_source, interpreted_target = canonical_source, canonical_target
            if direction.reverse:
                interpreted_source, interpreted_target = canonical_target, canonical_source
            edge_id = compiled.get(relationship_id)
            if not structured:
                classification, reason = "ignored_unstructured", "not source-owned structured topology"
            elif canonical_source is None:
                classification, reason = "blocked_source", "source provider zone lacks a linked canonical binding"
            elif canonical_target is None:
                classification, reason = "blocked_target", "target provider zone lacks a linked canonical binding"
            elif canonical_source == canonical_target:
                classification, reason = "self_edge", "both provider endpoints project to the same gameplay zone"
            elif edge_id is None:
                classification, reason = (
                    "compiler_eligible_missing_edge",
                    "row is compiler-eligible but no finalized provider travel edge references it",
                )
            else:
                classification, reason = "compiled", "finalized provider travel edge references this row"
            out.append(
                ProviderTravelRelationshipDiagnostic(
                    relationship_id=relationship_id,
                    source_provider_entity_id=provider_source,
                    source_provider_name=str(row["source_name_entity"] or ""),
                    target_provider_entity_id=provider_target,
                    target_provider_name=str(row["target_name"] or ""),
                    source_page_id=int(row["source_page_id"]) if row["source_page_id"] is not None else None,
                    source_name=str(row["source_name"] or ""),
                    source_key=str(row["source_key"] or ""),
                    source_url=str(row["source_url"] or ""),
                    evidence=str(row["evidence"] or ""),
                    direction_raw=direction.raw,
                    direction_mode=direction.mode,
                    direction_reversed=direction.reverse,
                    direction_bidirectional=direction.bidirectional,
                    canonical_source_entity_id=canonical_source,
                    canonical_source_name=names.get(canonical_source or -1, ""),
                    canonical_target_entity_id=canonical_target,
                    canonical_target_name=names.get(canonical_target or -1, ""),
                    interpreted_source_entity_id=interpreted_source,
                    interpreted_source_name=names.get(interpreted_source or -1, ""),
                    interpreted_target_entity_id=interpreted_target,
                    interpreted_target_name=names.get(interpreted_target or -1, ""),
                    classification=classification,
                    reason=reason,
                    compiled_edge_id=edge_id,
                )
            )
        return tuple(out)

    def _edges(self, zone_id: int, names: dict[int, str]) -> tuple[dict[str, Any], ...]:
        if not self._exists("zone_travel_edges"):
            return ()
        rows = self.db.conn.execute(
            """
            SELECT id,source_zone_entity_id,target_zone_entity_id,bidirectional,
                   connection_kind,source_name,source_kind,source_key
            FROM zone_travel_edges
            WHERE status='linked' AND (source_zone_entity_id=? OR target_zone_entity_id=?)
            ORDER BY id
            """,
            (int(zone_id), int(zone_id)),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            source = int(row["source_zone_entity_id"])
            target = int(row["target_zone_entity_id"])
            directions: list[tuple[str, int]] = []
            if source == zone_id:
                directions.append(("outgoing", target))
                if row["bidirectional"]:
                    directions.append(("incoming", target))
            if target == zone_id:
                directions.append(("incoming", source))
                if row["bidirectional"]:
                    directions.append(("outgoing", source))
            for direction, neighbor in directions:
                out.append(
                    {
                        "edge_id": int(row["id"]),
                        "direction": direction,
                        "neighbor_entity_id": neighbor,
                        "neighbor_name": names.get(neighbor, ""),
                        "bidirectional": bool(row["bidirectional"]),
                        "connection_kind": str(row["connection_kind"] or ""),
                        "source_name": str(row["source_name"] or ""),
                        "source_kind": str(row["source_kind"] or ""),
                        "source_key": str(row["source_key"] or ""),
                    }
                )
        return tuple(out)

    def zone(self, query: str) -> ProviderTravelZoneDiagnostic:
        text = " ".join(str(query or "").split()).strip()
        resolution = prefer_eqclient_zone_resolution(ZoneIdentityIndex(self.db).resolve(text), text)
        if resolution.status != "linked" or resolution.identity is None:
            return ProviderTravelZoneDiagnostic(
                text,
                resolution.status,
                resolution.reason,
                None,
                "",
                "ambiguous_zone" if resolution.status == "ambiguous" else "unresolved_zone",
                "zone does not resolve to one authoritative canonical gameplay identity",
                (),
                (),
                (),
            )

        zone_id = int(resolution.identity.entity_id)
        names = self._zone_names()
        bindings = self._bindings(zone_id)
        relationships = self._relationships(
            (binding["provider_zone_entity_id"] for binding in bindings),
            names=names,
            client_ids=self._client_ids(),
            bindings=self._binding_map(),
            compiled=self._compiled_relationships(),
        )
        edges = self._edges(zone_id, names)
        relationship_classes = {row.classification for row in relationships}
        if "compiler_eligible_missing_edge" in relationship_classes:
            classification = "provider_rows_uncompiled"
            reason = "stored provider topology is compiler-eligible but a canonical edge is missing"
        elif "compiled" in relationship_classes:
            classification = "compiled"
            reason = "provider connected-zone evidence compiled into canonical travel"
        elif relationship_classes & {"blocked_source", "blocked_target"}:
            classification = "provider_rows_identity_blocked"
            reason = "structured provider connected-zone rows exist but a canonical endpoint binding is blocked"
        elif relationship_classes == {"ignored_unstructured"}:
            classification = "provider_rows_unstructured"
            reason = "connected-zone rows exist, but none are source-owned structured travel evidence"
        elif relationships:
            classification = "provider_rows_blocked"
            reason = "provider connected-zone rows exist but none currently compile"
        elif bindings and any(binding.get("source_page_id") is not None for binding in bindings):
            classification = "provider_page_no_connected_rows"
            reason = "provider zone page/binding exists but no stored connected-zone row references it"
        elif bindings:
            classification = "provider_zone_missing_source_page"
            reason = "provider zone binding exists, but its provider entity has no stored source page"
        elif edges:
            classification = "non_provider_topology_only"
            reason = "canonical travel exists, but no provider-zone binding is associated with this zone"
        else:
            classification = "no_provider_zone"
            reason = "no provider-zone binding or canonical travel edge is associated with this zone"
        return ProviderTravelZoneDiagnostic(
            text,
            resolution.status,
            resolution.reason,
            zone_id,
            str(resolution.identity.name),
            classification,
            reason,
            bindings,
            relationships,
            edges,
        )

    def summary(
        self,
        zones: Iterable[str] = DEFAULT_PROVIDER_TRAVEL_FRONTIER_ZONES,
    ) -> ProviderTravelFrontierSummary:
        return ProviderTravelFrontierSummary(tuple(self.zone(zone) for zone in zones))


def provider_travel_frontier_text(
    db,
    zones: Iterable[str] = DEFAULT_PROVIDER_TRAVEL_FRONTIER_ZONES,
) -> str:
    summary = ProviderTravelFrontierAudit(db).summary(zones)
    lines = [
        "EverQuestie provider travel frontier audit",
        "",
        "Read-only projection over finalized provider bindings, connected-zone relationships and travel edges.",
        "No mirror folders, map folders or network sources are scanned.",
    ]
    for zone in summary.zones:
        lines += [
            "",
            f"{zone.query}: {zone.classification}",
            f"  canonical: {zone.canonical_zone_name or '(unresolved)'}"
            + (f" [{zone.canonical_zone_entity_id}]" if zone.canonical_zone_entity_id is not None else ""),
            f"  reason: {zone.reason}",
            f"  provider bindings / source pages / connected rows: "
            f"{len(zone.bindings)} / {zone.provider_source_page_count} / {len(zone.relationships)}",
            f"  canonical outgoing / incoming: {zone.outgoing_count} / {zone.incoming_count}",
        ]
        if zone.binding_status_counts:
            lines.append(
                "  binding states: "
                + ", ".join(f"{key}={value}" for key, value in zone.binding_status_counts.items())
            )
        if zone.relationship_status_counts:
            lines.append(
                "  relationship decisions: "
                + ", ".join(
                    f"{key}={value}" for key, value in zone.relationship_status_counts.items()
                )
            )
        for binding in zone.bindings:
            page = f" | page={binding['source_key']}" if binding["source_key"] else " | page=(missing)"
            lines.append(
                f"    binding {binding['provider_zone_name']} [{binding['provider_zone_entity_id']}] "
                f"{binding['status']}: {binding['reason']}{page}"
            )
        for relation in zone.relationships:
            interpreted = ""
            if relation.interpreted_source_entity_id is not None and relation.interpreted_target_entity_id is not None:
                interpreted = f" | {relation.interpreted_source_name} -> {relation.interpreted_target_name}"
                if relation.direction_bidirectional:
                    interpreted += " (two-way)"
            lines.append(
                f"    relationship {relation.relationship_id}: {relation.classification} "
                f"| {relation.source_provider_name} -> {relation.target_provider_name} "
                f"| direction={relation.direction_raw or '(blank)'} / {relation.direction_mode}{interpreted}"
            )
            if relation.classification != "compiled":
                lines.append(f"      {relation.reason}")
        for edge in zone.canonical_edges:
            lines.append(
                f"    edge {edge['edge_id']}: {edge['direction']} {edge['neighbor_name']} "
                f"| {edge['connection_kind']} | {edge['source_name']}/{edge['source_kind']}"
            )
    return "\n".join(lines)