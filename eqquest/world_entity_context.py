from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable

from .db import Database, normalize_name


QUEST_ACTOR_RELATIONS = {
    "started_by",
    "related_creature",
    "objective_kill",
    "objective_source_creature",
    "objective_turn_in_to",
    "objective_speak",
}


_OUT_LABELS = {
    "found_in": "Found in",
    "starts_in": "Starts in",
    "occurs_in": "Occurs in",
    "started_by": "Started by",
    "quest_item": "Quest item",
    "related_creature": "Related creature",
    "related_quest": "Related quest",
    "objective_kill": "Kill objective",
    "objective_loot": "Loot objective",
    "objective_source_creature": "Objective source creature",
    "objective_turn_in_item": "Turn-in item",
    "objective_turn_in_to": "Turn in to",
    "objective_speak": "Speak with",
    "drops_from": "Drops from",
    "turn_in_to": "Turn in to",
    "sells": "Sells",
    "teaches_spell": "Teaches spell",
    "trains_skill": "Trains skill",
}

_IN_LABELS = {
    "found_in": "Contains evidence for",
    "starts_in": "Quest starts here",
    "occurs_in": "Quest occurs here",
    "started_by": "Starts quest",
    "quest_item": "Used by quest",
    "related_creature": "Related to quest",
    "related_quest": "Related quest",
    "objective_kill": "Kill target for quest",
    "objective_loot": "Loot target for quest",
    "objective_source_creature": "Source creature for quest",
    "objective_turn_in_item": "Turn-in item for quest",
    "objective_turn_in_to": "Turn-in NPC for quest",
    "objective_speak": "Conversation target for quest",
    "drops_from": "Drops item",
    "turn_in_to": "Receives turn-in item",
    "sells": "Sold by",
    "teaches_spell": "Taught by",
    "trains_skill": "Trained by",
}


@dataclass(frozen=True, slots=True)
class EntityAlias:
    value: str
    alias_type: str


@dataclass(frozen=True, slots=True)
class EntityExternalIdentity:
    namespace: str
    external_id: str


@dataclass(frozen=True, slots=True)
class EntitySourceEvidence:
    source_page_id: int
    source_name: str
    source_kind: str
    source_key: str
    source_version: str
    url: str
    title: str
    role: str
    confidence: float | None

    @property
    def source_label(self) -> str:
        label = self.source_name or "EverQuestie knowledge"
        if self.source_version:
            label += f" {self.source_version}"
        return label


@dataclass(frozen=True, slots=True)
class EntityRelationshipFact:
    relationship_id: int
    relation: str
    direction: str
    entity_id: int
    other_entity_id: int
    other_kind: str
    other_name: str
    display_other_entity_id: int
    display_other_name: str
    zone_projection_status: str
    projected_from_zone_entity_id: int | None
    quantity: int | None
    evidence: str
    confidence: str
    derived_from: str
    preview: bool
    shown: int | None
    total: int | None
    source_page_id: int | None
    source_name: str
    source_kind: str
    source_key: str
    source_version: str
    data: dict[str, Any]

    @property
    def label(self) -> str:
        labels = _OUT_LABELS if self.direction == "out" else _IN_LABELS
        return labels.get(self.relation, self.relation.replace("_", " ").title())

    @property
    def source_label(self) -> str:
        label = self.source_name or "EverQuestie knowledge"
        if self.source_version:
            label += f" {self.source_version}"
        return label

    @property
    def preview_text(self) -> str:
        if not self.preview:
            return ""
        if self.shown is not None and self.total is not None:
            return f"preview {self.shown} of {self.total}"
        if self.total is not None:
            return f"preview of {self.total} total"
        if self.shown is not None:
            return f"preview showing {self.shown}"
        return "preview"


@dataclass(frozen=True, slots=True)
class EntityLocationFact:
    location_id: int
    entity_id: int
    entity_name: str
    entity_kind: str
    relation: str
    original_zone_entity_id: int | None
    original_zone_name: str
    gameplay_zone_entity_id: int | None
    gameplay_zone_name: str
    zone_projection_status: str
    y: float | None
    x: float | None
    z: float | None
    label: str
    evidence: str
    source_page_id: int | None
    source_name: str
    source_kind: str
    source_key: str
    source_version: str
    data: dict[str, Any]

    @property
    def navigable(self) -> bool:
        return (
            self.gameplay_zone_entity_id is not None
            and self.x is not None
            and self.y is not None
        )

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
    def source_label(self) -> str:
        label = self.source_name or "EverQuestie knowledge"
        if self.source_version:
            label += f" {self.source_version}"
        return label


@dataclass(frozen=True, slots=True)
class QuestStepFact:
    step_order: int
    description: str
    zone: str
    match: dict[str, Any]
    source_page_id: int | None
    source_name: str
    source_kind: str
    source_key: str
    source_version: str

    @property
    def source_label(self) -> str:
        label = self.source_name or "EverQuestie knowledge"
        if self.source_version:
            label += f" {self.source_version}"
        return label


@dataclass(frozen=True, slots=True)
class WorldEntityContext:
    entity_id: int
    kind: str
    name: str
    resolution_kind: str
    level_min: int | None
    level_max: int | None
    zone_text: str
    notes: str
    data: dict[str, Any]
    aliases: tuple[EntityAlias, ...]
    external_ids: tuple[EntityExternalIdentity, ...]
    sources: tuple[EntitySourceEvidence, ...]
    relationships: tuple[EntityRelationshipFact, ...]
    locations: tuple[EntityLocationFact, ...]
    related_locations: tuple[EntityLocationFact, ...]
    quest_steps: tuple[QuestStepFact, ...]

    @property
    def navigable_locations(self) -> tuple[EntityLocationFact, ...]:
        return tuple(row for row in self.locations if row.navigable)

    @property
    def navigable_related_locations(self) -> tuple[EntityLocationFact, ...]:
        return tuple(row for row in self.related_locations if row.navigable)


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


def _json_dict(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _maybe_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_exact_entity(
    db: Database,
    token: str,
    kind: str | None,
):
    """Resolve only exact canonical names or exact aliases; never substring-guess."""
    norm = normalize_name(token)
    if not norm:
        return None, "missing"
    args: list[Any] = [norm]
    kind_sql = ""
    if kind:
        kind_sql = " AND kind=?"
        args.append(kind)
    exact = db.conn.execute(
        f"SELECT * FROM entities WHERE normalized_name=?{kind_sql} ORDER BY id LIMIT 3",
        args,
    ).fetchall()
    if len(exact) == 1:
        return exact[0], "exact"
    if len(exact) > 1:
        return None, "ambiguous"

    args = [norm]
    kind_sql = ""
    if kind:
        kind_sql = " AND e.kind=?"
        args.append(kind)
    aliases = db.conn.execute(
        f"""
        SELECT DISTINCT e.*
        FROM entity_aliases a
        JOIN entities e ON e.id=a.entity_id
        WHERE a.normalized_alias=?{kind_sql}
        ORDER BY e.id LIMIT 3
        """,
        args,
    ).fetchall()
    if len(aliases) == 1:
        return aliases[0], "alias"
    if len(aliases) > 1:
        return None, "ambiguous"
    return None, "missing"


def _zone_projection(
    db: Database,
    zone_entity_id: int | None,
) -> tuple[int | None, str, str, int | None]:
    """Return gameplay ID/name, status, and provider source ID for one stored zone."""
    if zone_entity_id is None:
        return None, "", "unknown_zone", None
    zone = db.entity(int(zone_entity_id))
    if zone is None:
        return None, "", "unknown_zone", None
    zone_name = str(zone["name"] or "")

    if _relation_exists(db, "entity_external_ids"):
        client = db.conn.execute(
            """
            SELECT 1 FROM entity_external_ids
            WHERE entity_id=? AND namespace='eqclient:zone' LIMIT 1
            """,
            (int(zone_entity_id),),
        ).fetchone()
        if client is not None:
            return int(zone_entity_id), zone_name, "canonical", None

    if _relation_exists(db, "zone_provider_bindings"):
        binding = db.conn.execute(
            """
            SELECT status,gameplay_zone_entity_id,gameplay_zone_name
            FROM zone_provider_bindings
            WHERE provider_zone_entity_id=?
            """,
            (int(zone_entity_id),),
        ).fetchone()
        if binding is not None:
            status = str(binding["status"] or "unresolved")
            if status == "linked" and binding["gameplay_zone_entity_id"] is not None:
                return (
                    int(binding["gameplay_zone_entity_id"]),
                    str(binding["gameplay_zone_name"] or zone_name),
                    "linked_provider",
                    int(zone_entity_id),
                )
            return None, "", f"provider_{status}", int(zone_entity_id)

    return None, "", "provider_unmapped", int(zone_entity_id)


def _aliases(db: Database, entity_id: int) -> tuple[EntityAlias, ...]:
    if not _relation_exists(db, "entity_aliases"):
        return ()
    rows = db.conn.execute(
        "SELECT alias,alias_type FROM entity_aliases WHERE entity_id=? ORDER BY alias_type,alias",
        (int(entity_id),),
    ).fetchall()
    return tuple(EntityAlias(str(r["alias"]), str(r["alias_type"] or "")) for r in rows)


def _external_ids(db: Database, entity_id: int) -> tuple[EntityExternalIdentity, ...]:
    if not _relation_exists(db, "entity_external_ids"):
        return ()
    rows = db.conn.execute(
        """
        SELECT namespace,external_id FROM entity_external_ids
        WHERE entity_id=? ORDER BY namespace,external_id
        """,
        (int(entity_id),),
    ).fetchall()
    return tuple(
        EntityExternalIdentity(str(r["namespace"]), str(r["external_id"]))
        for r in rows
    )


def _sources(db: Database, entity_id: int) -> tuple[EntitySourceEvidence, ...]:
    if not all(_relation_exists(db, name) for name in ("entity_sources", "source_pages")):
        return ()
    rows = db.conn.execute(
        """
        SELECT sp.id,sp.source_name,sp.source_kind,sp.source_key,sp.source_version,
               sp.url,sp.title,es.role,es.confidence
        FROM entity_sources es
        JOIN source_pages sp ON sp.id=es.source_page_id
        WHERE es.entity_id=?
        ORDER BY CASE es.role WHEN 'primary' THEN 0 ELSE 1 END,
                 sp.source_name,sp.source_key,sp.id
        """,
        (int(entity_id),),
    ).fetchall()
    return tuple(
        EntitySourceEvidence(
            source_page_id=int(r["id"]),
            source_name=str(r["source_name"] or ""),
            source_kind=str(r["source_kind"] or ""),
            source_key=str(r["source_key"] or ""),
            source_version=str(r["source_version"] or ""),
            url=str(r["url"] or ""),
            title=str(r["title"] or ""),
            role=str(r["role"] or ""),
            confidence=(float(r["confidence"]) if r["confidence"] is not None else None),
        )
        for r in rows
    )


def _relationships(db: Database, entity_id: int) -> tuple[EntityRelationshipFact, ...]:
    if not _relation_exists(db, "entity_relationships"):
        return ()
    rows = db.conn.execute(
        """
        SELECT r.id,r.source_entity_id,r.target_entity_id,r.relation,r.quantity,
               r.evidence,r.data_json,
               s.kind AS source_entity_kind,s.name AS source_entity_name,
               t.kind AS target_entity_kind,t.name AS target_entity_name,
               sp.id AS source_page_id,sp.source_name,sp.source_kind,sp.source_key,
               sp.source_version,sp.url
        FROM entity_relationships r
        JOIN entities s ON s.id=r.source_entity_id
        JOIN entities t ON t.id=r.target_entity_id
        LEFT JOIN source_pages sp ON sp.id=r.source_page_id
        WHERE r.source_entity_id=? OR r.target_entity_id=?
        ORDER BY r.relation,r.source_entity_id,r.target_entity_id,
                 COALESCE(sp.source_name,''),COALESCE(sp.source_key,''),r.id
        """,
        (int(entity_id), int(entity_id)),
    ).fetchall()

    result: list[EntityRelationshipFact] = []
    for row in rows:
        outgoing = int(row["source_entity_id"]) == int(entity_id)
        other_id = int(row["target_entity_id"] if outgoing else row["source_entity_id"])
        other_kind = str(row["target_entity_kind"] if outgoing else row["source_entity_kind"])
        other_name = str(row["target_entity_name"] if outgoing else row["source_entity_name"])
        display_id = other_id
        display_name = other_name
        zone_status = "not_zone"
        projected_from = None
        if other_kind == "zone":
            gameplay_id, gameplay_name, zone_status, projected_from = _zone_projection(db, other_id)
            if gameplay_id is not None:
                display_id = gameplay_id
                display_name = gameplay_name

        data = _json_dict(row["data_json"])
        result.append(
            EntityRelationshipFact(
                relationship_id=int(row["id"]),
                relation=str(row["relation"] or ""),
                direction="out" if outgoing else "in",
                entity_id=int(entity_id),
                other_entity_id=other_id,
                other_kind=other_kind,
                other_name=other_name,
                display_other_entity_id=display_id,
                display_other_name=display_name,
                zone_projection_status=zone_status,
                projected_from_zone_entity_id=projected_from,
                quantity=(int(row["quantity"]) if row["quantity"] is not None else None),
                evidence=str(row["evidence"] or ""),
                confidence=str(data.get("confidence") or ""),
                derived_from=str(data.get("derived_from") or ""),
                preview=bool(data.get("preview", False)),
                shown=_maybe_int(data.get("shown")),
                total=_maybe_int(data.get("total")),
                source_page_id=(
                    int(row["source_page_id"])
                    if row["source_page_id"] is not None
                    else None
                ),
                source_name=str(row["source_name"] or ""),
                source_kind=str(row["source_kind"] or ""),
                source_key=str(row["source_key"] or row["url"] or ""),
                source_version=str(row["source_version"] or ""),
                data=data,
            )
        )
    return tuple(result)


def _location_rows(
    db: Database,
    entity_ids: Iterable[int],
    *,
    limit: int,
):
    ids = tuple(dict.fromkeys(int(value) for value in entity_ids))
    if not ids or not _relation_exists(db, "entity_locations"):
        return []
    placeholders = ",".join("?" for _ in ids)
    return db.conn.execute(
        f"""
        SELECT l.id,l.entity_id,l.zone_entity_id,l.y,l.x,l.z,l.label,l.evidence,l.data_json,
               e.name AS entity_name,e.kind AS entity_kind,
               z.name AS zone_name,
               sp.id AS source_page_id,sp.source_name,sp.source_kind,sp.source_key,
               sp.source_version,sp.url
        FROM entity_locations l
        JOIN entities e ON e.id=l.entity_id
        LEFT JOIN entities z ON z.id=l.zone_entity_id
        LEFT JOIN source_pages sp ON sp.id=l.source_page_id
        WHERE l.entity_id IN ({placeholders})
        ORDER BY e.kind,e.name,l.id
        LIMIT ?
        """,
        (*ids, max(1, int(limit))),
    ).fetchall()


def _locations(
    db: Database,
    entity_id: int,
    entity_name: str,
    entity_kind: str,
    *,
    relation_by_entity: dict[int, str] | None = None,
    limit: int,
) -> tuple[EntityLocationFact, ...]:
    ids = (int(entity_id),) if relation_by_entity is None else tuple(relation_by_entity)
    rows = _location_rows(db, ids, limit=limit)
    result: list[EntityLocationFact] = []
    for row in rows:
        stored_zone_id = (
            int(row["zone_entity_id"])
            if row["zone_entity_id"] is not None
            else None
        )
        gameplay_id, gameplay_name, zone_status, _projected_from = _zone_projection(
            db, stored_zone_id
        )
        data = _json_dict(row["data_json"])
        located_entity_id = int(row["entity_id"])
        result.append(
            EntityLocationFact(
                location_id=int(row["id"]),
                entity_id=located_entity_id,
                entity_name=str(row["entity_name"] or entity_name),
                entity_kind=str(row["entity_kind"] or entity_kind),
                relation=(
                    "self"
                    if relation_by_entity is None
                    else relation_by_entity.get(located_entity_id, "related")
                ),
                original_zone_entity_id=stored_zone_id,
                original_zone_name=str(row["zone_name"] or ""),
                gameplay_zone_entity_id=gameplay_id,
                gameplay_zone_name=gameplay_name,
                zone_projection_status=zone_status,
                y=(float(row["y"]) if row["y"] is not None else None),
                x=(float(row["x"]) if row["x"] is not None else None),
                z=(float(row["z"]) if row["z"] is not None else None),
                label=str(row["label"] or ""),
                evidence=str(row["evidence"] or ""),
                source_page_id=(
                    int(row["source_page_id"])
                    if row["source_page_id"] is not None
                    else None
                ),
                source_name=str(row["source_name"] or ""),
                source_kind=str(row["source_kind"] or ""),
                source_key=str(row["source_key"] or row["url"] or ""),
                source_version=str(row["source_version"] or ""),
                data=data,
            )
        )
    return tuple(result)


def _quest_steps(db: Database, quest_entity_id: int) -> tuple[QuestStepFact, ...]:
    if not _relation_exists(db, "quest_steps"):
        return ()
    rows = db.conn.execute(
        """
        SELECT qs.step_order,qs.description,qs.zone,qs.match_json,
               sp.id AS source_page_id,sp.source_name,sp.source_kind,sp.source_key,
               sp.source_version
        FROM quest_steps qs
        LEFT JOIN source_pages sp ON sp.id=qs.source_page_id
        WHERE qs.quest_entity_id=?
        ORDER BY qs.step_order
        """,
        (int(quest_entity_id),),
    ).fetchall()
    return tuple(
        QuestStepFact(
            step_order=int(row["step_order"]),
            description=str(row["description"] or ""),
            zone=str(row["zone"] or ""),
            match=_json_dict(row["match_json"]),
            source_page_id=(
                int(row["source_page_id"])
                if row["source_page_id"] is not None
                else None
            ),
            source_name=str(row["source_name"] or ""),
            source_kind=str(row["source_kind"] or ""),
            source_key=str(row["source_key"] or ""),
            source_version=str(row["source_version"] or ""),
        )
        for row in rows
    )


def build_world_entity_context(
    db: Database,
    entity_token: str,
    kind: str | None = None,
    *,
    location_limit: int = 250,
    related_location_limit: int = 500,
) -> tuple[WorldEntityContext | None, str]:
    """Build a conservative read-only NPC/quest/item world projection.

    Resolution accepts only exact canonical names or exact aliases. Provider zone IDs
    on relationships/locations are projected into gameplay identity only through
    finalized linked bindings. No reconciliation, parser, user-state lookup, or write
    occurs here.
    """
    entity, resolution = _resolve_exact_entity(db, entity_token, kind)
    if entity is None:
        return None, resolution

    entity_id = int(entity["id"])
    entity_kind = str(entity["kind"] or "")
    entity_name = str(entity["name"] or "")
    data = _json_dict(entity["data_json"])
    relationships = _relationships(db, entity_id)
    locations = _locations(
        db,
        entity_id,
        entity_name,
        entity_kind,
        limit=location_limit,
    )

    relation_by_entity: dict[int, str] = {}
    if entity_kind == "quest":
        for fact in relationships:
            if (
                fact.direction == "out"
                and fact.relation in QUEST_ACTOR_RELATIONS
                and fact.other_kind == "npc"
            ):
                relation_by_entity.setdefault(fact.other_entity_id, fact.relation)
    related_locations = (
        _locations(
            db,
            entity_id,
            entity_name,
            entity_kind,
            relation_by_entity=relation_by_entity,
            limit=related_location_limit,
        )
        if relation_by_entity
        else ()
    )

    return (
        WorldEntityContext(
            entity_id=entity_id,
            kind=entity_kind,
            name=entity_name,
            resolution_kind=resolution,
            level_min=(int(entity["level_min"]) if entity["level_min"] is not None else None),
            level_max=(int(entity["level_max"]) if entity["level_max"] is not None else None),
            zone_text=str(entity["zone"] or ""),
            notes=str(entity["notes"] or ""),
            data=data,
            aliases=_aliases(db, entity_id),
            external_ids=_external_ids(db, entity_id),
            sources=_sources(db, entity_id),
            relationships=relationships,
            locations=locations,
            related_locations=related_locations,
            quest_steps=_quest_steps(db, entity_id) if entity_kind == "quest" else (),
        ),
        resolution,
    )


def _metadata_lines(context: WorldEntityContext) -> list[str]:
    data = context.data
    lines: list[str] = []
    if context.level_min is not None or context.level_max is not None:
        lo = str(context.level_min) if context.level_min is not None else "?"
        hi = str(context.level_max) if context.level_max is not None else "?"
        lines.append(f"Level range: {lo}-{hi}")
    if context.kind == "npc":
        fields = (
            ("Type", "npc_type"),
            ("Expansion", "expansion"),
            ("Added", "npc_added"),
            ("Last updated", "npc_last_updated"),
        )
    elif context.kind == "quest":
        fields = (
            ("Quest type", "quest_type"),
            ("Repeatable", "repeatable"),
            ("Group size", "group_size"),
            ("Minimum players", "min_players"),
            ("Maximum players", "max_players"),
        )
    elif context.kind == "item":
        fields = (
            ("Item type", "item_type"),
            ("Required level", "required_level"),
            ("Recommended level", "recommended_level"),
            ("Merchant value", "merchant_value"),
        )
    else:
        fields = ()
    for label, key in fields:
        value = data.get(key)
        if value not in (None, "", [], {}):
            lines.append(f"{label}: {value}")
    return lines


def _location_line(row: EntityLocationFact) -> str:
    zone = row.gameplay_zone_name or row.original_zone_name or "unknown zone"
    details = [zone]
    if row.loc_text:
        details.append(f"/loc {row.loc_text}")
    if row.label:
        details.append(row.label)
    details.append(row.source_label)
    if not row.navigable and row.original_zone_entity_id is not None:
        details.append(f"{row.zone_projection_status}; not map-targetable")
    return " | ".join(details)


def world_entity_context_text(
    db: Database,
    entity_token: str,
    kind: str | None = None,
    *,
    relationship_limit: int = 50,
    location_limit: int = 25,
) -> str:
    context, status = build_world_entity_context(
        db,
        entity_token,
        kind,
        location_limit=max(1, int(location_limit)) * 4,
        related_location_limit=max(1, int(location_limit)) * 8,
    )
    if context is None:
        if status == "ambiguous":
            return f"ENTITY | {entity_token} | ambiguous exact identity"
        return f"ENTITY | {entity_token} | no exact entity identity"

    lines = [
        f"ENTITY | [{context.kind}] {context.name}",
        f"Resolved by: {context.resolution_kind}",
    ]
    lines.extend(_metadata_lines(context))

    if context.sources:
        lines += ["", "Sources:"]
        for source in context.sources:
            role = f" | {source.role}" if source.role else ""
            lines.append(f"  • {source.source_label}{role}")

    if context.relationships:
        lines += ["", "Evidence-backed relationships (not exhaustive):"]
        for fact in context.relationships[: max(1, int(relationship_limit))]:
            details = [fact.source_label]
            if fact.quantity is not None:
                details.append(f"quantity {fact.quantity}")
            if fact.preview_text:
                details.append(fact.preview_text)
            if fact.confidence:
                details.append(fact.confidence)
            if fact.derived_from:
                details.append(f"derived from {fact.derived_from}")
            if fact.other_kind == "zone" and fact.zone_projection_status.startswith("provider_"):
                details.append(fact.zone_projection_status)
            lines.append(
                f"  • {fact.label}: [{fact.other_kind}] {fact.display_other_name} | "
                + " | ".join(details)
            )

    if context.locations:
        lines += ["", "Known locations:"]
        for row in context.locations[: max(1, int(location_limit))]:
            lines.append("  • " + _location_line(row))

    if context.quest_steps:
        lines += ["", "Structured quest steps:"]
        for step in context.quest_steps:
            details = [step.description]
            if step.zone:
                details.append(f"zone {step.zone}")
            if step.source_name:
                details.append(step.source_label)
            lines.append(f"  {step.step_order}. " + " | ".join(details))

    if context.related_locations:
        lines += ["", "Quest actor locations (explicit evidence):"]
        for row in context.related_locations[: max(1, int(location_limit))]:
            relation = _OUT_LABELS.get(row.relation, row.relation.replace("_", " ").title())
            lines.append(
                f"  • {relation}: [npc] {row.entity_name} | " + _location_line(row)
            )

    return "\n".join(lines)
