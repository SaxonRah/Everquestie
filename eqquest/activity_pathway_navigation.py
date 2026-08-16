from __future__ import annotations

from dataclasses import dataclass

from .knowledge_map_choices import (
    KnowledgeMapChoice,
    KnowledgeMapChoiceSet,
    KnowledgeRouteChoice,
    knowledge_map_choices,
    knowledge_route_choices,
)


_CONTACT_PRIORITY = (
    ("started_by", "quest starter"),
    ("objective_turn_in_to", "turn-in NPC"),
)


@dataclass(frozen=True, slots=True)
class PathwayContactNavigation:
    quest_id: int
    quest_name: str
    status: str
    reason: str
    contact_kind: str = ""
    map_choices: tuple[KnowledgeMapChoice, ...] = ()
    route_choices: tuple[KnowledgeRouteChoice, ...] = ()
    current_zone_name: str = ""

    @property
    def map_ready(self) -> bool:
        return bool(self.map_choices)

    @property
    def route_ready(self) -> bool:
        return bool(self.route_choices)


def _contact_choices(
    choice_set: KnowledgeMapChoiceSet,
    relation: str,
) -> tuple[tuple[KnowledgeMapChoice, ...], tuple[KnowledgeMapChoice, ...]]:
    current = tuple(
        choice
        for choice in choice_set.choices
        if choice.origin == "quest_actor" and choice.relation == relation
    )
    remote = tuple(
        choice
        for choice in choice_set.other_zone_choices
        if choice.origin == "quest_actor" and choice.relation == relation
    )
    return current, remote


def _route_choices_for(
    choice_set: KnowledgeMapChoiceSet,
    current: tuple[KnowledgeMapChoice, ...],
    remote: tuple[KnowledgeMapChoice, ...],
) -> tuple[KnowledgeRouteChoice, ...]:
    filtered = KnowledgeMapChoiceSet(
        status="ready" if current else "not_in_current_zone",
        reason=choice_set.reason,
        selected_entity_id=choice_set.selected_entity_id,
        selected_entity_name=choice_set.selected_entity_name,
        current_zone_entity_id=choice_set.current_zone_entity_id,
        current_zone_name=choice_set.current_zone_name,
        choices=current,
        other_zone_choice_count=len(remote),
        other_zone_choices=remote,
    )
    return knowledge_route_choices(filtered)


def pathway_contact_navigation(
    db,
    quest_id: int,
    current_zone: str | None,
) -> PathwayContactNavigation:
    """Return safe Map/Travel choices for a suggested quest contact.

    A quest starter is the preferred contact because a pathway is not assumed to be
    owned yet. If no navigable starter is known, an explicit turn-in NPC is offered as
    useful context. Objective mobs and arbitrary quest locations are deliberately not
    substituted for those roles.

    All location safety, provider-zone reconciliation, and coordinate provenance are
    delegated to ``knowledge_map_choices``. This function only filters its already-safe
    quest-actor results by reviewed relationship semantics.
    """
    quest = db.entity(int(quest_id))
    if quest is None or str(quest["kind"] or "") != "quest":
        return PathwayContactNavigation(
            int(quest_id),
            str(quest["name"] or "") if quest is not None else "",
            "missing_quest",
            "Suggested quest is no longer present in local knowledge.",
        )

    quest_name = str(quest["name"] or "")
    choice_set = knowledge_map_choices(db, int(quest_id), current_zone)
    if choice_set.current_zone_entity_id is None:
        return PathwayContactNavigation(
            int(quest_id),
            quest_name,
            choice_set.status,
            choice_set.reason,
            current_zone_name=choice_set.current_zone_name,
        )

    for relation, label in _CONTACT_PRIORITY:
        current, remote = _contact_choices(choice_set, relation)
        if not current and not remote:
            continue
        routes = _route_choices_for(choice_set, current, remote)
        if current:
            reason = (
                f"{len(current)} safe {label} location choice(s) are available in "
                f"the current zone {choice_set.current_zone_name}."
            )
            status = "map_ready"
        else:
            remote_zones = len({choice.zone_entity_id for choice in remote})
            reason = (
                f"The known {label} is outside the current zone; "
                f"{len(remote)} safe location choice(s) span {remote_zones} canonical "
                f"zone{'s' if remote_zones != 1 else ''}."
            )
            status = "route_ready" if routes else "no_route_choice"
        return PathwayContactNavigation(
            int(quest_id),
            quest_name,
            status,
            reason,
            contact_kind=label,
            map_choices=current,
            route_choices=routes,
            current_zone_name=choice_set.current_zone_name,
        )

    if choice_set.status in {
        "no_navigable_location",
        "not_in_current_zone",
        "ready",
    }:
        reason = (
            f"No safely mapped quest starter or turn-in NPC is currently known for "
            f"{quest_name}."
        )
    else:
        reason = choice_set.reason
    return PathwayContactNavigation(
        int(quest_id),
        quest_name,
        "no_contact_location",
        reason,
        current_zone_name=choice_set.current_zone_name,
    )
