from __future__ import annotations

from .db import Database
from .location_actionability import location_actionability_note
from .vendor import VENDOR_RELATIONS
from .world_entity_context import (
    QUEST_ACTOR_RELATIONS,
    WorldEntityContext,
    _aliases,
    _external_ids,
    _json_dict,
    _locations,
    _quest_steps,
    _relationships,
    _sources,
)


def build_world_entity_context_for_id(
    db: Database,
    entity_id: int,
    *,
    location_limit: int = 250,
    related_location_limit: int = 500,
) -> WorldEntityContext | None:
    """Build world context for an already-selected canonical entity ID.

    Knowledge UI has already resolved identity through its tree/search result. Reusing
    that ID is both cheaper and safer than resolving the display name again, especially
    when distinct provider/client entities intentionally share a name.
    """
    entity = db.entity(int(entity_id))
    if entity is None:
        return None

    canonical_id = int(entity["id"])
    kind = str(entity["kind"] or "")
    name = str(entity["name"] or "")
    relationships = _relationships(db, canonical_id)
    locations = _locations(
        db,
        canonical_id,
        name,
        kind,
        limit=max(1, int(location_limit)),
    )

    relation_by_entity: dict[int, str] = {}
    if kind == "quest":
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
            canonical_id,
            name,
            kind,
            relation_by_entity=relation_by_entity,
            limit=max(1, int(related_location_limit)),
        )
        if relation_by_entity
        else ()
    )

    return WorldEntityContext(
        entity_id=canonical_id,
        kind=kind,
        name=name,
        resolution_kind="selected_entity_id",
        level_min=(int(entity["level_min"]) if entity["level_min"] is not None else None),
        level_max=(int(entity["level_max"]) if entity["level_max"] is not None else None),
        zone_text=str(entity["zone"] or ""),
        notes=str(entity["notes"] or ""),
        data=_json_dict(entity["data_json"]),
        aliases=_aliases(db, canonical_id),
        external_ids=_external_ids(db, canonical_id),
        sources=_sources(db, canonical_id),
        relationships=relationships,
        locations=locations,
        related_locations=related_locations,
        quest_steps=_quest_steps(db, canonical_id) if kind == "quest" else (),
    )


def _location_summary(row) -> str:
    zone = row.gameplay_zone_name or row.original_zone_name or "unknown zone"
    details = [zone]
    if row.loc_text:
        details.append(f"/loc {row.loc_text}")
    if row.label:
        details.append(row.label)
    details.append(row.source_label)
    actionability_note = location_actionability_note(row)
    if actionability_note:
        details.append(actionability_note)
    elif not row.navigable and row.original_zone_entity_id is not None:
        details.append(f"{row.zone_projection_status}; not map-targetable")
    return " | ".join(details)


def knowledge_world_detail_lines(
    db: Database,
    entity_id: int,
    *,
    relationship_limit: int = 100,
    location_limit: int = 50,
) -> list[str]:
    """Render knowledge-only world sections for Knowledge detail.

    Player progress is intentionally absent. Quest steps come directly from immutable
    knowledge through ``WorldEntityContext.quest_steps``; the Live tab remains the
    owner of tracked progress/completion state.
    """
    context = build_world_entity_context_for_id(
        db,
        entity_id,
        location_limit=max(1, int(location_limit)),
        related_location_limit=max(1, int(location_limit)) * 4,
    )
    if context is None:
        return []

    lines: list[str] = []
    relationships = tuple(
        fact
        for fact in context.relationships
        if fact.relation not in VENDOR_RELATIONS
    )
    if relationships:
        lines += ["", "World relationships (evidence-backed; not exhaustive):"]
        for fact in relationships[: max(1, int(relationship_limit))]:
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
        lines += ["", "World locations:"]
        for row in context.locations[: max(1, int(location_limit))]:
            lines.append("  • " + _location_summary(row))

    if context.quest_steps:
        lines += ["", "Knowledge quest steps:"]
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
            lines.append(
                f"  • [{row.entity_kind}] {row.entity_name} | " + _location_summary(row)
            )

    return lines
