from __future__ import annotations

import json

from .knowledge_map_choices import KnowledgeMapChoice, KnowledgeRouteChoice
from .loot_source_navigation import loot_source_navigation
from .quest_objective_navigation import QuestObjectiveNavigationResult
from .zone_authority import resolve_authoritative_zone


def _rule(step) -> dict:
    try:
        value = json.loads(step["match_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _step(db, quest_id: int, step_order: int | None):
    if step_order is None:
        return None
    return next(
        (
            row
            for row in db.quest_steps(int(quest_id))
            if int(row["step_order"]) == int(step_order)
        ),
        None,
    )


def _quest_map_choice(
    base: QuestObjectiveNavigationResult,
    choice: KnowledgeMapChoice,
) -> KnowledgeMapChoice:
    return KnowledgeMapChoice(
        selected_entity_id=int(base.quest_id),
        location_entity_id=int(choice.location_entity_id),
        location_entity_name=str(choice.location_entity_name),
        origin="quest_objective_reviewed_item_source",
        relation="objective_source_creature",
        relation_label="reviewed loot source",
        zone_entity_id=int(choice.zone_entity_id),
        zone_name=str(choice.zone_name),
        x=float(choice.x),
        y=float(choice.y),
        z=float(choice.z) if choice.z is not None else None,
        evidence_count=int(choice.evidence_count),
        source_labels=tuple(choice.source_labels),
    )


def _quest_route_choice(
    base: QuestObjectiveNavigationResult,
    choice: KnowledgeRouteChoice,
) -> KnowledgeRouteChoice:
    return KnowledgeRouteChoice(
        selected_entity_id=int(base.quest_id),
        selected_entity_name=str(base.quest_name),
        zone_entity_id=int(choice.zone_entity_id),
        zone_name=str(choice.zone_name),
        target_labels=tuple(choice.target_labels),
        source_labels=tuple(choice.source_labels),
        location_choice_count=int(choice.location_choice_count),
        evidence_count=int(choice.evidence_count),
    )


def augment_objective_with_reviewed_item_sources(
    db,
    base: QuestObjectiveNavigationResult,
    current_zone: str | None,
) -> QuestObjectiveNavigationResult:
    """Improve exact loot-objective navigation with reviewed global drop evidence.

    The base quest-objective projection remains authoritative. This augmentation applies
    only when all of the following are true:

    * the structured step exists and retains ``source_page_id`` provenance;
    * the compiled match rule is explicitly a ``loot`` event;
    * the rule contains an exact canonical ``item_entity_id``;
    * the item exists canonically;
    * source NPCs come from reviewed ``item -> NPC : drops_from`` relationships;
    * NPC coordinates independently survive the existing safe Map/Travel projection.

    If the step names a canonical objective zone, reviewed sources are constrained to
    that zone. If the step-zone token is present but unresolved/ambiguous, the original
    result is preserved rather than allowing a global drop table to override the quest's
    geographic uncertainty.
    """
    if base.map_ready:
        return base
    if base.status in {
        "missing_quest",
        "no_active_step",
        "no_current_zone",
        "current_zone_ambiguous",
        "current_zone_unresolved",
    }:
        return base

    step = _step(db, int(base.quest_id), base.step_order)
    if step is None or step["source_page_id"] is None:
        return base

    rule = _rule(step)
    if str(rule.get("event") or "").strip().casefold() != "loot":
        return base
    raw_item_id = rule.get("item_entity_id")
    if raw_item_id is None:
        return base
    try:
        item_id = int(raw_item_id)
    except (TypeError, ValueError):
        return base

    item = db.entity(item_id)
    if item is None or str(item["kind"] or "") != "item":
        return base
    item_name = str(item["name"] or f"item {item_id}")

    step_zone_text = " ".join(str(step["zone"] or "").split()).strip()
    step_zone_id: int | None = None
    if step_zone_text:
        resolution = resolve_authoritative_zone(db, step_zone_text)
        if resolution.identity is None:
            return base
        step_zone_id = int(resolution.identity.entity_id)

    source = loot_source_navigation(db, item_id, current_zone)

    map_choices = tuple(
        _quest_map_choice(base, choice)
        for choice in source.map_choices
        if step_zone_id is None or int(choice.zone_entity_id) == step_zone_id
    )
    if map_choices:
        return QuestObjectiveNavigationResult(
            "map_ready",
            (
                f"Exact loot objective item {item_name} has {len(map_choices)} reviewed "
                "source NPC location choice(s) in the current objective zone."
            ),
            int(base.quest_id),
            str(base.quest_name),
            base.step_order,
            str(base.objective_text),
            base.current_zone_entity_id,
            str(base.current_zone_name),
            map_choices,
            (),
        )

    route_choices = tuple(
        _quest_route_choice(base, choice)
        for choice in source.route_choices
        if step_zone_id is None or int(choice.zone_entity_id) == step_zone_id
    )
    if route_choices:
        return QuestObjectiveNavigationResult(
            "route_ready",
            (
                f"Exact loot objective item {item_name} has reviewed source NPC locations "
                f"in {len(route_choices)} canonical destination zone(s); Travel can route "
                "to the source zone."
            ),
            int(base.quest_id),
            str(base.quest_name),
            base.step_order,
            str(base.objective_text),
            base.current_zone_entity_id,
            str(base.current_zone_name),
            (),
            route_choices,
        )

    return base
