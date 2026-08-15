from __future__ import annotations

from dataclasses import dataclass

from .db import Database
from .zone_context import ZoneContext, build_zone_context


_RELATION_ROLES = {
    "found_in": {
        "npc": "Known NPC",
        "item": "Known item",
    },
    "starts_in": {
        "quest": "Quest starts here",
    },
    "occurs_in": {
        "quest": "Quest occurs here",
    },
}

_KIND_ORDER = {
    "quest": 0,
    "npc": 1,
    "item": 2,
    "zone": 3,
}


@dataclass(frozen=True, slots=True)
class CurrentZoneEntitySummary:
    entity_id: int
    name: str
    kind: str
    roles: tuple[str, ...]
    source_labels: tuple[str, ...]
    relationship_ids: tuple[int, ...]
    location_count: int
    preview_fact_count: int

    @property
    def located(self) -> bool:
        return self.location_count > 0

    @property
    def role_text(self) -> str:
        return ", ".join(self.roles)

    @property
    def source_text(self) -> str:
        return ", ".join(self.source_labels)


@dataclass(frozen=True, slots=True)
class CurrentZoneExitSummary:
    edge_id: int
    zone_entity_id: int
    zone_name: str
    connection_kind: str
    direction: str
    usable: bool
    source_owned_coordinate: bool
    source_label: str
    evidence: str

    @property
    def role_text(self) -> str:
        kind = self.connection_kind.replace("_", " ").strip() or "travel"
        if self.direction == "bidirectional":
            return f"Two-way {kind}"
        if self.usable:
            return f"Exit via {kind}"
        return f"Incoming-only {kind}"


@dataclass(frozen=True, slots=True)
class CurrentZoneDashboard:
    context: ZoneContext
    entities: tuple[CurrentZoneEntitySummary, ...]
    exits: tuple[CurrentZoneExitSummary, ...]

    @property
    def zone_entity_id(self) -> int:
        return self.context.identity.entity_id

    @property
    def zone_name(self) -> str:
        return self.context.identity.name

    @property
    def provider_fact_count(self) -> int:
        return len(self.context.provider_metadata)

    @property
    def map_binding_count(self) -> int:
        return len(self.context.maps)

    @property
    def usable_exit_count(self) -> int:
        return sum(1 for row in self.exits if row.usable)

    @property
    def mappable_exit_count(self) -> int:
        return sum(1 for row in self.exits if row.usable and row.source_owned_coordinate)

    @property
    def located_entity_count(self) -> int:
        return sum(1 for row in self.entities if row.located)


def _unique(values) -> tuple:
    return tuple(dict.fromkeys(values))


def _relation_role(relation: str, kind: str) -> str:
    role = _RELATION_ROLES.get(relation, {}).get(kind)
    if role:
        return role
    return relation.replace("_", " ").strip().title() or "Known here"


def build_current_zone_dashboard(
    db: Database,
    zone_token: str,
    *,
    relationship_limit: int = 2000,
    location_limit: int = 1000,
) -> tuple[CurrentZoneDashboard | None, str]:
    """Aggregate one canonical zone into a compact, exact-ID player dashboard.

    This is a read projection over ``ZoneContext``. It does not infer completeness,
    synthesize locations, promote incoming-only travel edges, or mutate knowledge.
    """
    context, status = build_zone_context(
        db,
        zone_token,
        relationship_limit=max(1, int(relationship_limit)),
        location_limit=max(1, int(location_limit)),
    )
    if context is None:
        return None, status

    grouped: dict[int, dict[str, object]] = {}
    for fact in context.related_entities:
        item = grouped.setdefault(
            int(fact.entity_id),
            {
                "name": str(fact.name),
                "kind": str(fact.kind),
                "roles": [],
                "sources": [],
                "relationships": [],
                "locations": 0,
                "previews": 0,
            },
        )
        item["roles"].append(_relation_role(str(fact.relation), str(fact.kind)))
        item["sources"].append(fact.source_label)
        item["relationships"].append(int(fact.relationship_id))
        if fact.preview:
            item["previews"] = int(item["previews"]) + 1

    # Independent location evidence may cover an entity that has no zone relationship
    # row in the current snapshot. Keep that useful fact visible without inventing a
    # stronger semantic role than "Located here".
    for located in context.locations:
        item = grouped.setdefault(
            int(located.entity_id),
            {
                "name": str(located.name),
                "kind": str(located.kind),
                "roles": [],
                "sources": [],
                "relationships": [],
                "locations": 0,
                "previews": 0,
            },
        )
        item["locations"] = int(item["locations"]) + 1
        item["roles"].append("Located here")
        item["sources"].append(located.location.source_label)

    entities: list[CurrentZoneEntitySummary] = []
    for entity_id, item in grouped.items():
        entities.append(
            CurrentZoneEntitySummary(
                entity_id=entity_id,
                name=str(item["name"]),
                kind=str(item["kind"]),
                roles=_unique(str(value) for value in item["roles"]),
                source_labels=_unique(str(value) for value in item["sources"]),
                relationship_ids=_unique(int(value) for value in item["relationships"]),
                location_count=int(item["locations"]),
                preview_fact_count=int(item["previews"]),
            )
        )
    entities.sort(
        key=lambda row: (
            _KIND_ORDER.get(row.kind, 9),
            row.name.casefold(),
            row.entity_id,
        )
    )

    exits = tuple(
        CurrentZoneExitSummary(
            edge_id=int(connection.edge_id),
            zone_entity_id=int(connection.neighbor_zone_entity_id),
            zone_name=str(connection.neighbor_zone_name),
            connection_kind=str(connection.connection_kind),
            direction=str(connection.direction),
            usable=bool(connection.usable_from_zone),
            source_owned_coordinate=bool(
                connection.usable_from_zone
                and int(connection.coordinate_zone_entity_id) == int(context.identity.entity_id)
                and connection.x is not None
                and connection.y is not None
            ),
            source_label=(
                str(connection.source_name or connection.source_kind or "EverQuestie knowledge")
                + (f" {connection.source_version}" if connection.source_version else "")
            ),
            evidence=str(connection.evidence or ""),
        )
        for connection in context.connections
    )

    return CurrentZoneDashboard(context=context, entities=tuple(entities), exits=exits), "linked"


def current_zone_dashboard_text(db: Database, zone_token: str) -> str:
    dashboard, status = build_current_zone_dashboard(db, zone_token)
    if dashboard is None:
        if status == "ambiguous":
            return f"WHAT'S HERE | {zone_token} | ambiguous canonical zone identity"
        return f"WHAT'S HERE | {zone_token} | no canonical zone identity"

    lines = [
        f"WHAT'S HERE | {dashboard.zone_name}",
        f"Known entities: {len(dashboard.entities)} | located: {dashboard.located_entity_count}",
        f"Confirmed travel edges: {len(dashboard.exits)} | usable exits: {dashboard.usable_exit_count} | mappable exits: {dashboard.mappable_exit_count}",
        f"Map bindings: {dashboard.map_binding_count} | provider zone fact sources: {dashboard.provider_fact_count}",
        "",
        "Evidence-backed entities (not exhaustive):",
    ]
    for row in dashboard.entities:
        details = [row.role_text or "Known here", row.source_text or "EverQuestie knowledge"]
        if row.location_count:
            details.append(f"{row.location_count} location evidence row(s)")
        if row.preview_fact_count:
            details.append(f"{row.preview_fact_count} preview fact(s)")
        lines.append(f"  • [{row.kind}] {row.name} | " + " | ".join(details))

    if dashboard.exits:
        lines += ["", "Confirmed neighboring-zone evidence:"]
        for row in dashboard.exits:
            suffix = " | source-side coordinate" if row.source_owned_coordinate else ""
            lines.append(
                f"  • [zone] {row.zone_name} | {row.role_text} | {row.source_label}{suffix}"
            )
    return "\n".join(lines)
