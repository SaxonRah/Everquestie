from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ZoneIdentityAuditMember:
    entity_id: int
    name: str
    client_zone_ids: tuple[str, ...]
    external_ids: tuple[str, ...]
    sources: tuple[str, ...]
    alias_count: int
    relationships_out: int
    relationships_in: int
    locations_as_entity: int
    locations_as_zone: int
    map_bindings: int
    travel_out: int
    travel_in: int

    @property
    def client_backed(self) -> bool:
        return bool(self.client_zone_ids)

    @property
    def downstream_refs(self) -> int:
        return (
            self.relationships_out
            + self.relationships_in
            + self.locations_as_entity
            + self.locations_as_zone
            + self.map_bindings
            + self.travel_out
            + self.travel_in
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "client_backed": self.client_backed,
            "client_zone_ids": list(self.client_zone_ids),
            "external_ids": list(self.external_ids),
            "sources": list(self.sources),
            "alias_count": self.alias_count,
            "relationships_out": self.relationships_out,
            "relationships_in": self.relationships_in,
            "locations_as_entity": self.locations_as_entity,
            "locations_as_zone": self.locations_as_zone,
            "map_bindings": self.map_bindings,
            "travel_out": self.travel_out,
            "travel_in": self.travel_in,
            "downstream_refs": self.downstream_refs,
        }


@dataclass(frozen=True, slots=True)
class ZoneIdentityAuditGroup:
    normalized_name: str
    display_name: str
    classification: str
    members: tuple[ZoneIdentityAuditMember, ...]

    @property
    def client_members(self) -> tuple[ZoneIdentityAuditMember, ...]:
        return tuple(member for member in self.members if member.client_backed)

    @property
    def non_client_members(self) -> tuple[ZoneIdentityAuditMember, ...]:
        return tuple(member for member in self.members if not member.client_backed)

    @property
    def downstream_refs(self) -> int:
        return sum(member.downstream_refs for member in self.members)

    def as_dict(self) -> dict[str, Any]:
        return {
            "normalized_name": self.normalized_name,
            "display_name": self.display_name,
            "classification": self.classification,
            "member_count": len(self.members),
            "client_member_count": len(self.client_members),
            "downstream_refs": self.downstream_refs,
            "members": [member.as_dict() for member in self.members],
        }


@dataclass(frozen=True, slots=True)
class ZoneIdentityAuditSummary:
    zone_entities: int
    name_groups: int
    client_backed_entities: int
    provider_only_entities: int
    duplicate_name_groups: int
    entities_in_duplicate_groups: int
    client_authority_duplicate_groups: int
    client_authority_shadow_entities: int
    multi_client_collision_groups: int
    provider_only_duplicate_groups: int
    provider_only_unique_groups: int
    duplicate_groups_with_downstream_refs: int
    groups: tuple[ZoneIdentityAuditGroup, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "zone_entities": self.zone_entities,
            "name_groups": self.name_groups,
            "client_backed_entities": self.client_backed_entities,
            "provider_only_entities": self.provider_only_entities,
            "duplicate_name_groups": self.duplicate_name_groups,
            "entities_in_duplicate_groups": self.entities_in_duplicate_groups,
            "client_authority_duplicate_groups": self.client_authority_duplicate_groups,
            "client_authority_shadow_entities": self.client_authority_shadow_entities,
            "multi_client_collision_groups": self.multi_client_collision_groups,
            "provider_only_duplicate_groups": self.provider_only_duplicate_groups,
            "provider_only_unique_groups": self.provider_only_unique_groups,
            "duplicate_groups_with_downstream_refs": self.duplicate_groups_with_downstream_refs,
            "groups": [group.as_dict() for group in self.groups],
        }


class ZoneIdentityAudit:
    """Read-only audit of exact-name zone identity fragmentation.

    EverQuestie's gameplay resolver may prefer one unique EQ-client-backed identity when
    provider records share the same literal zone name. That is a safe *join policy*, but
    it is not enough evidence to destructively merge provider entities: provider pages
    can represent historical or instance-specific records with the same display name.

    This projection makes that boundary measurable. It classifies exact normalized-name
    groups and inventories downstream references that a future canonicalization pass
    would have to rewire. It never changes entity IDs or provenance.
    """

    def __init__(self, db):
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

    def _count_by_entity(self, sql: str) -> dict[int, int]:
        return {
            int(row["entity_id"]): int(row["n"] or 0)
            for row in self.db.conn.execute(sql).fetchall()
        }

    def summary(self, *, duplicate_example_limit: int = 100) -> ZoneIdentityAuditSummary:
        rows = self.db.conn.execute(
            "SELECT id,name,normalized_name FROM entities WHERE kind='zone' ORDER BY normalized_name,id"
        ).fetchall()
        zone_ids = {int(row["id"]) for row in rows}
        if not rows:
            return ZoneIdentityAuditSummary(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ())

        client_ids: dict[int, list[str]] = defaultdict(list)
        external_ids: dict[int, list[str]] = defaultdict(list)
        for row in self.db.conn.execute(
            """
            SELECT x.entity_id,x.namespace,x.external_id
            FROM entity_external_ids x
            JOIN entities e ON e.id=x.entity_id
            WHERE e.kind='zone'
            ORDER BY x.entity_id,x.namespace,x.external_id
            """
        ).fetchall():
            entity_id = int(row["entity_id"])
            token = f"{row['namespace']}:{row['external_id']}"
            external_ids[entity_id].append(token)
            if str(row["namespace"] or "") == "eqclient:zone":
                client_ids[entity_id].append(str(row["external_id"]))

        sources: dict[int, list[str]] = defaultdict(list)
        if self._object_exists("entity_sources") and self._object_exists("source_pages"):
            for row in self.db.conn.execute(
                """
                SELECT es.entity_id,sp.source_name,sp.source_kind
                FROM entity_sources es
                JOIN source_pages sp ON sp.id=es.source_page_id
                JOIN entities e ON e.id=es.entity_id
                WHERE e.kind='zone'
                GROUP BY es.entity_id,sp.source_name,sp.source_kind
                ORDER BY es.entity_id,sp.source_name,sp.source_kind
                """
            ).fetchall():
                sources[int(row["entity_id"])].append(
                    f"{row['source_name']} [{row['source_kind']}]"
                )

        alias_counts = self._count_by_entity(
            """
            SELECT ea.entity_id,COUNT(*) AS n
            FROM entity_aliases ea JOIN entities e ON e.id=ea.entity_id
            WHERE e.kind='zone' GROUP BY ea.entity_id
            """
        )
        rel_out = self._count_by_entity(
            """
            SELECT r.source_entity_id AS entity_id,COUNT(*) AS n
            FROM entity_relationships r JOIN entities e ON e.id=r.source_entity_id
            WHERE e.kind='zone' GROUP BY r.source_entity_id
            """
        )
        rel_in = self._count_by_entity(
            """
            SELECT r.target_entity_id AS entity_id,COUNT(*) AS n
            FROM entity_relationships r JOIN entities e ON e.id=r.target_entity_id
            WHERE e.kind='zone' GROUP BY r.target_entity_id
            """
        )
        loc_entity = self._count_by_entity(
            """
            SELECT l.entity_id,COUNT(*) AS n
            FROM entity_locations l JOIN entities e ON e.id=l.entity_id
            WHERE e.kind='zone' GROUP BY l.entity_id
            """
        )
        loc_zone = self._count_by_entity(
            """
            SELECT l.zone_entity_id AS entity_id,COUNT(*) AS n
            FROM entity_locations l JOIN entities e ON e.id=l.zone_entity_id
            WHERE l.zone_entity_id IS NOT NULL AND e.kind='zone' GROUP BY l.zone_entity_id
            """
        )

        map_bindings: dict[int, int] = {}
        if self._object_exists("zone_map_bindings"):
            map_bindings = self._count_by_entity(
                """
                SELECT zone_entity_id AS entity_id,COUNT(*) AS n
                FROM zone_map_bindings
                WHERE zone_entity_id IS NOT NULL GROUP BY zone_entity_id
                """
            )
        travel_out: dict[int, int] = {}
        travel_in: dict[int, int] = {}
        if self._object_exists("zone_travel_edges"):
            travel_out = self._count_by_entity(
                """
                SELECT source_zone_entity_id AS entity_id,COUNT(*) AS n
                FROM zone_travel_edges GROUP BY source_zone_entity_id
                """
            )
            travel_in = self._count_by_entity(
                """
                SELECT target_zone_entity_id AS entity_id,COUNT(*) AS n
                FROM zone_travel_edges
                WHERE target_zone_entity_id IS NOT NULL GROUP BY target_zone_entity_id
                """
            )

        members_by_name: dict[str, list[ZoneIdentityAuditMember]] = defaultdict(list)
        for row in rows:
            entity_id = int(row["id"])
            member = ZoneIdentityAuditMember(
                entity_id=entity_id,
                name=str(row["name"]),
                client_zone_ids=tuple(client_ids.get(entity_id, ())),
                external_ids=tuple(external_ids.get(entity_id, ())),
                sources=tuple(sources.get(entity_id, ())),
                alias_count=int(alias_counts.get(entity_id, 0)),
                relationships_out=int(rel_out.get(entity_id, 0)),
                relationships_in=int(rel_in.get(entity_id, 0)),
                locations_as_entity=int(loc_entity.get(entity_id, 0)),
                locations_as_zone=int(loc_zone.get(entity_id, 0)),
                map_bindings=int(map_bindings.get(entity_id, 0)),
                travel_out=int(travel_out.get(entity_id, 0)),
                travel_in=int(travel_in.get(entity_id, 0)),
            )
            members_by_name[str(row["normalized_name"])].append(member)

        groups: list[ZoneIdentityAuditGroup] = []
        for normalized_name, members_list in members_by_name.items():
            members = tuple(members_list)
            client_count = sum(member.client_backed for member in members)
            if len(members) == 1:
                classification = "unique_client" if client_count == 1 else "provider_only_unique"
            elif client_count == 1:
                classification = "client_authority_duplicate"
            elif client_count > 1:
                classification = "multi_client_collision"
            else:
                classification = "provider_only_duplicate"
            groups.append(
                ZoneIdentityAuditGroup(
                    normalized_name=normalized_name,
                    display_name=members[0].name,
                    classification=classification,
                    members=members,
                )
            )

        groups.sort(key=lambda group: (group.display_name.casefold(), group.normalized_name))
        duplicates = [group for group in groups if len(group.members) > 1]
        client_authority = [
            group for group in duplicates if group.classification == "client_authority_duplicate"
        ]
        multi_client = [
            group for group in duplicates if group.classification == "multi_client_collision"
        ]
        provider_duplicates = [
            group for group in duplicates if group.classification == "provider_only_duplicate"
        ]
        provider_unique = [
            group for group in groups if group.classification == "provider_only_unique"
        ]

        client_backed_count = sum(bool(client_ids.get(entity_id)) for entity_id in zone_ids)
        examples = tuple(duplicates[: max(0, int(duplicate_example_limit))])
        return ZoneIdentityAuditSummary(
            zone_entities=len(rows),
            name_groups=len(groups),
            client_backed_entities=client_backed_count,
            provider_only_entities=len(rows) - client_backed_count,
            duplicate_name_groups=len(duplicates),
            entities_in_duplicate_groups=sum(len(group.members) for group in duplicates),
            client_authority_duplicate_groups=len(client_authority),
            client_authority_shadow_entities=sum(len(group.non_client_members) for group in client_authority),
            multi_client_collision_groups=len(multi_client),
            provider_only_duplicate_groups=len(provider_duplicates),
            provider_only_unique_groups=len(provider_unique),
            duplicate_groups_with_downstream_refs=sum(group.downstream_refs > 0 for group in duplicates),
            groups=examples,
        )


def zone_identity_audit_text(db, *, duplicate_example_limit: int = 40) -> str:
    summary = ZoneIdentityAudit(db).summary(duplicate_example_limit=duplicate_example_limit)
    lines = [
        "EverQuestie canonical zone identity audit",
        "",
        "Read-only exact-name collision analysis. No entity IDs or provenance are changed.",
        "",
        f"Zone entities: {summary.zone_entities:,}",
        f"Exact normalized-name groups: {summary.name_groups:,}",
        f"EQ-client-backed entities: {summary.client_backed_entities:,}",
        f"Provider-only entities: {summary.provider_only_entities:,}",
        "",
        f"Duplicate exact-name groups: {summary.duplicate_name_groups:,}",
        f"Entities inside duplicate groups: {summary.entities_in_duplicate_groups:,}",
        f"Unique-client authority duplicate groups: {summary.client_authority_duplicate_groups:,}",
        f"  non-client shadow entities in those groups: {summary.client_authority_shadow_entities:,}",
        f"Multi-client same-name collision groups: {summary.multi_client_collision_groups:,}",
        f"Provider-only duplicate groups: {summary.provider_only_duplicate_groups:,}",
        f"Provider-only unique groups: {summary.provider_only_unique_groups:,}",
        f"Duplicate groups with downstream graph/map/travel refs: {summary.duplicate_groups_with_downstream_refs:,}",
        "",
        "Interpretation:",
        "  • unique-client authority duplicates are safe for gameplay joins, but are not automatically merge-safe;",
        "  • multi-client collisions may represent genuine same-name instances and remain ambiguous;",
        "  • provider-only duplicates require provider-specific reconciliation evidence;",
        "  • downstream refs show how much knowledge a future canonicalization pass must rewire transactionally.",
    ]

    if summary.groups:
        lines += ["", f"Duplicate group examples (up to {duplicate_example_limit}):"]
        for group in summary.groups:
            lines.append(
                f"  {group.display_name} | {group.classification} | "
                f"members={len(group.members)} | downstream refs={group.downstream_refs}"
            )
            for member in group.members:
                client = ",".join(member.client_zone_ids) or "-"
                source_text = "; ".join(member.sources) or "no source link"
                lines.append(
                    f"    entity {member.entity_id}: client IDs={client} | refs={member.downstream_refs} | {source_text}"
                )

    return "\n".join(lines)
