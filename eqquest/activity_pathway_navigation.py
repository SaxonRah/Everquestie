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


def _reviewed_contact_ids(db, quest_id: int, relation: str) -> frozenset[int]:
    rows = db.conn.execute(
        """
        SELECT DISTINCT r.target_entity_id AS npc_id
        FROM entity_relationships r
        JOIN entities n ON n.id=r.target_entity_id AND n.kind='npc'
        WHERE r.source_entity_id=?
          AND r.relation=?
          AND r.source_page_id IS NOT NULL
        """,
        (int(quest_id), str(relation)),
    ).fetchall()
    return frozenset(int(row["npc_id"]) for row in rows)


def _contact_choices(
    choice_set: KnowledgeMapChoiceSet,
    relation: str,
    allowed_ids: frozenset[int],
) -> tuple[tuple[KnowledgeMapChoice, ...], tuple[KnowledgeMapChoice, ...]]:
    current = tuple(
        choice
        for choice in choice_set.choices
        if choice.origin == "quest_actor"
        and choice.relation == relation
        and int(choice.location_entity_id) in allowed_ids
    )
    remote = tuple(
        choice
        for choice in choice_set.other_zone_choices
        if choice.origin == "quest_actor"
        and choice.relation == relation
        and int(choice.location_entity_id) in allowed_ids
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
    """Return reviewed safe Map/Travel choices for a suggested quest contact.

    A reviewed quest starter is preferred because a pathway is not assumed to be owned
    yet. If no navigable reviewed starter is known, a reviewed explicit turn-in NPC is
    offered as useful context. Objective mobs and arbitrary quest locations are not
    substituted for those roles.

    General Knowledge projection intentionally includes broader relationship facts for
    inspection. This specialized player action therefore records the exact NPC IDs from
    source-backed contact relationships and filters every already-safe map/route choice
    back to that reviewed set. Location safety, provider-zone reconciliation, and
    coordinate provenance remain delegated to ``knowledge_map_choices``.
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
        allowed_ids = _reviewed_contact_ids(db, int(quest_id), relation)
        if not allowed_ids:
            continue
        current, remote = _contact_choices(choice_set, relation, allowed_ids)
        if not current and not remote:
            continue
        routes = _route_choices_for(choice_set, current, remote)
        if current:
            reason = (
                f"{len(current)} reviewed safe {label} location choice(s) are available in "
                f"the current zone {choice_set.current_zone_name}."
            )
            status = "map_ready"
        else:
            remote_zones = len({choice.zone_entity_id for choice in remote})
            reason = (
                f"The reviewed {label} is outside the current zone; "
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
            f"No safely mapped reviewed quest starter or turn-in NPC is currently known for "
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
