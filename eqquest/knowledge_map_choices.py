from __future__ import annotations

from dataclasses import dataclass

from .db import Database
from .locations import location_evidence_for_entity
from .world_entity_detail import build_world_entity_context_for_id
from .zone_authority import resolve_authoritative_zone


_RELATION_LABELS = {
    "started_by": "quest starter",
    "objective_speak": "speak target",
    "objective_kill": "kill target",
    "objective_source_creature": "loot source",
    "objective_turn_in_to": "turn-in NPC",
    "related_creature": "related creature",
}


@dataclass(frozen=True, slots=True)
class KnowledgeMapChoice:
    selected_entity_id: int
    location_entity_id: int
    location_entity_name: str
    origin: str
    relation: str
    relation_label: str
    zone_entity_id: int
    zone_name: str
    x: float
    y: float
    z: float | None
    evidence_count: int
    source_labels: tuple[str, ...]

    @property
    def map_label(self) -> str:
        if self.origin == "quest_actor" and self.relation_label:
            return f"{self.location_entity_name} ({self.relation_label})"
        return self.location_entity_name

    @property
    def loc_text(self) -> str:
        parts = [f"Y={self.y:g}", f"X={self.x:g}"]
        if self.z is not None:
            parts.append(f"Z={self.z:g}")
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class KnowledgeMapChoiceSet:
    status: str
    reason: str
    selected_entity_id: int
    selected_entity_name: str
    current_zone_entity_id: int | None
    current_zone_name: str
    choices: tuple[KnowledgeMapChoice, ...] = ()
    other_zone_choice_count: int = 0

    @property
    def ready(self) -> bool:
        return self.status == "ready" and bool(self.choices)


def _source_tuple(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if value))


def _group_direct_choices(db: Database, entity_id: int, zone_id: int, zone_name: str):
    rows = location_evidence_for_entity(db, entity_id)
    current = [
        row
        for row in rows
        if row.navigable and int(row.zone_entity_id) == int(zone_id)
    ]
    elsewhere = [
        row
        for row in rows
        if row.navigable and int(row.zone_entity_id) != int(zone_id)
    ]
    grouped: dict[tuple[float, float, float | None], list] = {}
    for row in current:
        assert row.x is not None and row.y is not None
        key = (
            float(row.x),
            float(row.y),
            float(row.z) if row.z is not None else None,
        )
        grouped.setdefault(key, []).append(row)

    entity = db.entity(entity_id)
    entity_name = str(entity["name"] or "") if entity is not None else ""
    choices: list[KnowledgeMapChoice] = []
    for (x, y, z), evidence_rows in grouped.items():
        choices.append(
            KnowledgeMapChoice(
                selected_entity_id=int(entity_id),
                location_entity_id=int(entity_id),
                location_entity_name=entity_name,
                origin="entity",
                relation="",
                relation_label="",
                zone_entity_id=int(zone_id),
                zone_name=zone_name,
                x=x,
                y=y,
                z=z,
                evidence_count=len(evidence_rows),
                source_labels=_source_tuple(row.source_label for row in evidence_rows),
            )
        )
    return choices, elsewhere, rows


def _quest_actor_choices(db: Database, entity_id: int, zone_id: int, zone_name: str):
    context = build_world_entity_context_for_id(db, entity_id)
    if context is None or context.kind != "quest":
        return [], [], []

    current = [
        row
        for row in context.related_locations
        if row.navigable and int(row.gameplay_zone_entity_id) == int(zone_id)
    ]
    elsewhere = [
        row
        for row in context.related_locations
        if row.navigable and int(row.gameplay_zone_entity_id) != int(zone_id)
    ]
    grouped: dict[tuple[int, str, float, float, float | None], list] = {}
    for row in current:
        assert row.x is not None and row.y is not None
        key = (
            int(row.entity_id),
            str(row.relation or ""),
            float(row.x),
            float(row.y),
            float(row.z) if row.z is not None else None,
        )
        grouped.setdefault(key, []).append(row)

    choices: list[KnowledgeMapChoice] = []
    for (actor_id, relation, x, y, z), evidence_rows in grouped.items():
        actor_name = evidence_rows[0].entity_name
        choices.append(
            KnowledgeMapChoice(
                selected_entity_id=int(entity_id),
                location_entity_id=actor_id,
                location_entity_name=actor_name,
                origin="quest_actor",
                relation=relation,
                relation_label=_RELATION_LABELS.get(
                    relation,
                    relation.replace("_", " "),
                ),
                zone_entity_id=int(zone_id),
                zone_name=zone_name,
                x=x,
                y=y,
                z=z,
                evidence_count=len(evidence_rows),
                source_labels=_source_tuple(row.source_label for row in evidence_rows),
            )
        )
    return choices, elsewhere, list(context.related_locations)


def knowledge_map_choices(
    db: Database,
    entity_id: int,
    current_zone: str | None,
) -> KnowledgeMapChoiceSet:
    """Return only safe, canonical current-zone choices for a Knowledge selection.

    Direct entity locations and explicit quest-actor locations are eligible. The
    function never chooses among distinct coordinates and never exposes provider
    candidate/unresolved coordinates as choices.
    """
    entity = db.entity(int(entity_id))
    if entity is None:
        return KnowledgeMapChoiceSet(
            "missing_entity",
            "Selected knowledge entity no longer exists.",
            int(entity_id),
            "",
            None,
            "",
        )
    entity_name = str(entity["name"] or "")

    zone_text = " ".join(str(current_zone or "").split()).strip()
    if not zone_text:
        return KnowledgeMapChoiceSet(
            "no_current_zone",
            "Current zone is not known from the log yet.",
            int(entity_id),
            entity_name,
            None,
            "",
        )
    resolution = resolve_authoritative_zone(db, zone_text)
    if resolution.identity is None:
        status = (
            "current_zone_ambiguous"
            if resolution.status == "ambiguous"
            else "current_zone_unresolved"
        )
        reason = (
            f"Current canonical zone identity is ambiguous for {zone_text}; EverQuestie will not guess a map target."
            if status == "current_zone_ambiguous"
            else f"Current canonical zone identity is not known for {zone_text}."
        )
        return KnowledgeMapChoiceSet(
            status,
            reason,
            int(entity_id),
            entity_name,
            None,
            zone_text,
        )

    zone_id = int(resolution.identity.entity_id)
    zone_name = str(resolution.identity.name or zone_text)
    direct, direct_elsewhere, direct_all = _group_direct_choices(
        db, int(entity_id), zone_id, zone_name
    )
    actor, actor_elsewhere, actor_all = _quest_actor_choices(
        db, int(entity_id), zone_id, zone_name
    )
    choices = direct + actor
    choices.sort(
        key=lambda row: (
            0 if row.origin == "entity" else 1,
            row.relation_label.casefold(),
            row.location_entity_name.casefold(),
            row.y,
            row.x,
            row.z if row.z is not None else 0.0,
        )
    )

    if choices:
        return KnowledgeMapChoiceSet(
            "ready",
            (
                f"{len(choices)} safe current-zone location choice(s) are available for {entity_name}."
            ),
            int(entity_id),
            entity_name,
            zone_id,
            zone_name,
            tuple(choices),
            len(direct_elsewhere) + len(actor_elsewhere),
        )

    if direct_elsewhere or actor_elsewhere:
        return KnowledgeMapChoiceSet(
            "not_in_current_zone",
            f"{entity_name} has safe mapped location evidence, but none is in the current zone {zone_name}.",
            int(entity_id),
            entity_name,
            zone_id,
            zone_name,
            (),
            len(direct_elsewhere) + len(actor_elsewhere),
        )
    if direct_all or actor_all:
        return KnowledgeMapChoiceSet(
            "no_navigable_location",
            f"Location evidence exists for {entity_name}, but none has both a safe gameplay-zone identity and explicit X/Y coordinates.",
            int(entity_id),
            entity_name,
            zone_id,
            zone_name,
        )
    return KnowledgeMapChoiceSet(
        "no_location",
        f"No confirmed location evidence is known for {entity_name}.",
        int(entity_id),
        entity_name,
        zone_id,
        zone_name,
    )
