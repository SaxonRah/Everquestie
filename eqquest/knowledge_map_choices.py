from __future__ import annotations

from dataclasses import dataclass

from .db import Database
from .location_actionability import location_is_actionable, relationship_is_actionable
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

_RELATED_LOCATION_RELATIONS = {
    "item": {
        ("out", "drops_from"): "drops from",
        ("out", "turn_in_to"): "turn-in NPC",
        ("in", "sells"): "vendor",
    },
    "spell": {
        ("in", "teaches_spell"): "spell teacher",
    },
    "skill": {
        ("in", "trains_skill"): "trainer",
    },
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
        if self.origin != "entity" and self.relation_label:
            return f"{self.location_entity_name} ({self.relation_label})"
        return self.location_entity_name

    @property
    def loc_text(self) -> str:
        parts = [f"Y={self.y:g}", f"X={self.x:g}"]
        if self.z is not None:
            parts.append(f"Z={self.z:g}")
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class KnowledgeRouteChoice:
    selected_entity_id: int
    selected_entity_name: str
    zone_entity_id: int
    zone_name: str
    target_labels: tuple[str, ...]
    source_labels: tuple[str, ...]
    location_choice_count: int
    evidence_count: int

    @property
    def route_label(self) -> str:
        if len(self.target_labels) == 1:
            return self.target_labels[0]
        return f"{self.selected_entity_name} ({len(self.target_labels)} related locations)"


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
    other_zone_choices: tuple[KnowledgeMapChoice, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status == "ready" and bool(self.choices)

    @property
    def routeable(self) -> bool:
        return bool(self.other_zone_choices)


def _source_tuple(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if value))


def _choice_sort_key(row: KnowledgeMapChoice):
    return (
        0 if row.origin == "entity" else 1 if row.origin == "quest_actor" else 2,
        row.zone_name.casefold(),
        row.relation_label.casefold(),
        row.location_entity_name.casefold(),
        row.y,
        row.x,
        row.z if row.z is not None else 0.0,
    )


def _split_choices(
    choices: list[KnowledgeMapChoice],
    zone_id: int,
) -> tuple[list[KnowledgeMapChoice], list[KnowledgeMapChoice]]:
    current = [choice for choice in choices if int(choice.zone_entity_id) == int(zone_id)]
    elsewhere = [choice for choice in choices if int(choice.zone_entity_id) != int(zone_id)]
    current.sort(key=_choice_sort_key)
    elsewhere.sort(key=_choice_sort_key)
    return current, elsewhere


def _group_direct_choices(db: Database, entity_id: int, zone_id: int, zone_name: str):
    rows = location_evidence_for_entity(db, entity_id)
    actionable = [row for row in rows if location_is_actionable(row)]
    grouped: dict[tuple[int, str, float, float, float | None], list] = {}
    for row in actionable:
        assert row.zone_entity_id is not None and row.x is not None and row.y is not None
        row_zone_name = str(row.zone_name or "")
        if int(row.zone_entity_id) == int(zone_id) and not row_zone_name:
            row_zone_name = zone_name
        key = (
            int(row.zone_entity_id),
            row_zone_name,
            float(row.x),
            float(row.y),
            float(row.z) if row.z is not None else None,
        )
        grouped.setdefault(key, []).append(row)

    entity = db.entity(entity_id)
    entity_name = str(entity["name"] or "") if entity is not None else ""
    all_choices: list[KnowledgeMapChoice] = []
    for (choice_zone_id, choice_zone_name, x, y, z), evidence_rows in grouped.items():
        all_choices.append(
            KnowledgeMapChoice(
                selected_entity_id=int(entity_id),
                location_entity_id=int(entity_id),
                location_entity_name=entity_name,
                origin="entity",
                relation="",
                relation_label="",
                zone_entity_id=choice_zone_id,
                zone_name=choice_zone_name,
                x=x,
                y=y,
                z=z,
                evidence_count=len(evidence_rows),
                source_labels=_source_tuple(row.source_label for row in evidence_rows),
            )
        )
    current, elsewhere = _split_choices(all_choices, zone_id)
    return current, elsewhere, rows


def _quest_actor_choices(db: Database, entity_id: int, zone_id: int, zone_name: str):
    context = build_world_entity_context_for_id(db, entity_id)
    if context is None or context.kind != "quest":
        return [], [], []

    reviewed_by_actor: dict[int, list] = {}
    for fact in context.relationships:
        if (
            fact.direction == "out"
            and fact.other_kind == "npc"
            and fact.relation in _RELATION_LABELS
            and relationship_is_actionable(fact)
        ):
            reviewed_by_actor.setdefault(int(fact.other_entity_id), []).append(fact)

    actionable = [
        row
        for row in context.related_locations
        if location_is_actionable(row) and int(row.entity_id) in reviewed_by_actor
    ]
    grouped: dict[
        tuple[int, str, int, str, float, float, float | None],
        tuple[list, list[str]],
    ] = {}
    for row in actionable:
        assert (
            row.gameplay_zone_entity_id is not None
            and row.x is not None
            and row.y is not None
        )
        row_zone_name = str(row.gameplay_zone_name or "")
        if int(row.gameplay_zone_entity_id) == int(zone_id) and not row_zone_name:
            row_zone_name = zone_name
        for fact in reviewed_by_actor[int(row.entity_id)]:
            relation = str(fact.relation)
            key = (
                int(row.gameplay_zone_entity_id),
                row_zone_name,
                int(row.entity_id),
                relation,
                float(row.x),
                float(row.y),
                float(row.z) if row.z is not None else None,
            )
            evidence_rows, semantic_sources = grouped.setdefault(key, ([], []))
            evidence_rows.append(row)
            semantic_sources.append(fact.source_label)

    all_choices: list[KnowledgeMapChoice] = []
    for (
        choice_zone_id,
        choice_zone_name,
        actor_id,
        relation,
        x,
        y,
        z,
    ), (evidence_rows, semantic_sources) in grouped.items():
        actor_name = evidence_rows[0].entity_name
        all_choices.append(
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
                zone_entity_id=choice_zone_id,
                zone_name=choice_zone_name,
                x=x,
                y=y,
                z=z,
                evidence_count=len(evidence_rows),
                source_labels=_source_tuple(
                    [*semantic_sources, *(row.source_label for row in evidence_rows)]
                ),
            )
        )
    current, elsewhere = _split_choices(all_choices, zone_id)
    return current, elsewhere, list(context.related_locations)


def _related_entity_choices(db: Database, entity_id: int, zone_id: int, zone_name: str):
    """Project reviewed item/vendor/trainer relationships through reviewed locations.

    The relationship identifies *which NPC is relevant* and must carry its own reviewed
    provenance. It never supplies the coordinate itself. Coordinates remain independently
    sourced entity locations or linked map evidence and must pass the actionability gate.
    """
    context = build_world_entity_context_for_id(db, entity_id)
    if context is None:
        return [], [], []
    allowed = _RELATED_LOCATION_RELATIONS.get(context.kind, {})
    if not allowed:
        return [], [], []

    all_choices: list[KnowledgeMapChoice] = []
    all_locations: list = []
    for fact in context.relationships:
        relation_label = allowed.get((fact.direction, fact.relation))
        if (
            not relation_label
            or fact.other_kind != "npc"
            or not relationship_is_actionable(fact)
        ):
            continue
        locations = location_evidence_for_entity(db, fact.other_entity_id)
        all_locations.extend(locations)
        actionable = [row for row in locations if location_is_actionable(row)]
        grouped: dict[tuple[int, str, float, float, float | None], list] = {}
        for row in actionable:
            assert row.zone_entity_id is not None and row.x is not None and row.y is not None
            row_zone_name = str(row.zone_name or "")
            if int(row.zone_entity_id) == int(zone_id) and not row_zone_name:
                row_zone_name = zone_name
            key = (
                int(row.zone_entity_id),
                row_zone_name,
                float(row.x),
                float(row.y),
                float(row.z) if row.z is not None else None,
            )
            grouped.setdefault(key, []).append(row)
        for (choice_zone_id, choice_zone_name, x, y, z), evidence_rows in grouped.items():
            all_choices.append(
                KnowledgeMapChoice(
                    selected_entity_id=int(entity_id),
                    location_entity_id=int(fact.other_entity_id),
                    location_entity_name=str(fact.other_name),
                    origin="related_entity",
                    relation=str(fact.relation),
                    relation_label=relation_label,
                    zone_entity_id=choice_zone_id,
                    zone_name=choice_zone_name,
                    x=x,
                    y=y,
                    z=z,
                    evidence_count=len(evidence_rows),
                    source_labels=_source_tuple(
                        [fact.source_label, *(row.source_label for row in evidence_rows)]
                    ),
                )
            )
    current, elsewhere = _split_choices(all_choices, zone_id)
    return current, elsewhere, all_locations


def knowledge_route_choices(
    choice_set: KnowledgeMapChoiceSet,
) -> tuple[KnowledgeRouteChoice, ...]:
    """Collapse reviewed remote map choices into explicit route destinations.

    Route selection is about the destination canonical zone, not which spawn point in
    that zone will eventually be mapped. Multiple coordinate choices in one remote zone
    therefore collapse into one route choice while retaining semantic labels and
    provenance. Candidate/ambiguous provider zones and unreviewed coordinates cannot
    enter because ``other_zone_choices`` contains only already-actionable locations.
    """
    grouped: dict[int, list[KnowledgeMapChoice]] = {}
    for choice in choice_set.other_zone_choices:
        grouped.setdefault(int(choice.zone_entity_id), []).append(choice)

    result: list[KnowledgeRouteChoice] = []
    for zone_id, choices in grouped.items():
        first = choices[0]
        result.append(
            KnowledgeRouteChoice(
                selected_entity_id=int(choice_set.selected_entity_id),
                selected_entity_name=str(choice_set.selected_entity_name),
                zone_entity_id=zone_id,
                zone_name=str(first.zone_name),
                target_labels=_source_tuple(choice.map_label for choice in choices),
                source_labels=_source_tuple(
                    source
                    for choice in choices
                    for source in choice.source_labels
                ),
                location_choice_count=len(choices),
                evidence_count=sum(int(choice.evidence_count) for choice in choices),
            )
        )
    return tuple(
        sorted(
            result,
            key=lambda choice: (
                choice.zone_name.casefold(),
                choice.target_labels,
            ),
        )
    )


def knowledge_map_choices(
    db: Database,
    entity_id: int,
    current_zone: str | None,
) -> KnowledgeMapChoiceSet:
    """Return reviewed current-zone and remote action choices for Knowledge.

    Direct locations, explicit quest-actor locations, and supported related-NPC
    locations remain visible as Knowledge even when unreviewed. A Map/Travel choice is
    stricter: the coordinate must have reviewed provenance, and a related-NPC choice also
    needs a reviewed relationship explaining why that NPC is relevant. Current-zone
    choices may be handed to Map; remote choices may only become explicit Travel
    destinations. Provider candidate/unresolved coordinates remain evidence-only.
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
    related, related_elsewhere, related_all = _related_entity_choices(
        db, int(entity_id), zone_id, zone_name
    )
    choices = direct + actor + related
    choices.sort(key=_choice_sort_key)
    other_choices = direct_elsewhere + actor_elsewhere + related_elsewhere
    other_choices.sort(key=_choice_sort_key)

    all_locations = direct_all + actor_all + related_all
    if choices:
        return KnowledgeMapChoiceSet(
            "ready",
            (
                f"{len(choices)} reviewed current-zone location choice(s) are available for {entity_name}."
            ),
            int(entity_id),
            entity_name,
            zone_id,
            zone_name,
            tuple(choices),
            len(other_choices),
            tuple(other_choices),
        )

    if other_choices:
        remote_zones = len({choice.zone_entity_id for choice in other_choices})
        zone_word = "zone" if remote_zones == 1 else "zones"
        return KnowledgeMapChoiceSet(
            "not_in_current_zone",
            (
                f"{entity_name} has {len(other_choices)} reviewed mapped location choice(s) in "
                f"{remote_zones} other canonical {zone_word}, but none is in the current zone {zone_name}."
            ),
            int(entity_id),
            entity_name,
            zone_id,
            zone_name,
            (),
            len(other_choices),
            tuple(other_choices),
        )
    if all_locations:
        return KnowledgeMapChoiceSet(
            "no_navigable_location",
            (
                f"Location evidence exists for {entity_name}, but none is fully actionable with "
                "reviewed provenance, a safe gameplay-zone identity, and explicit X/Y coordinates."
            ),
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
