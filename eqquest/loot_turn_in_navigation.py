from __future__ import annotations

from dataclasses import dataclass

from .knowledge_map_choices import (
    KnowledgeMapChoice,
    KnowledgeMapChoiceSet,
    KnowledgeRouteChoice,
    knowledge_map_choices,
    knowledge_route_choices,
)


@dataclass(frozen=True, slots=True)
class LootTurnInNavigation:
    status: str
    reason: str
    quest_id: int
    quest_name: str
    map_choices: tuple[KnowledgeMapChoice, ...] = ()
    route_choices: tuple[KnowledgeRouteChoice, ...] = ()

    @property
    def map_ready(self) -> bool:
        return bool(self.map_choices)

    @property
    def route_ready(self) -> bool:
        return bool(self.route_choices)

    @property
    def navigable(self) -> bool:
        return self.map_ready or self.route_ready


def _source_backed_turn_in_contacts(db, quest_id: int):
    return db.conn.execute(
        """
        SELECT DISTINCT r.target_entity_id AS npc_id, n.name AS npc_name
        FROM entity_relationships r
        JOIN entities n ON n.id=r.target_entity_id AND n.kind='npc'
        WHERE r.source_entity_id=?
          AND r.relation='objective_turn_in_to'
          AND r.source_page_id IS NOT NULL
        ORDER BY n.name COLLATE NOCASE, n.id
        """,
        (int(quest_id),),
    ).fetchall()


def loot_turn_in_navigation(
    db,
    quest_id: int,
    current_zone: str | None,
) -> LootTurnInNavigation:
    """Project reviewed exact turn-in contacts through safe Map/Travel logic.

    Quest relevance and navigation remain separate claims. This function first requires
    source-backed ``objective_turn_in_to`` relationships and records their exact NPC
    identities. General Knowledge projection may expose additional quest-actor facts for
    inspection, including unprovenanced relationships, so this specialized action filters
    every returned Map/Travel choice back to the reviewed NPC ID set before it can become
    actionable. Coordinates and gameplay-zone identity must still independently survive
    ``knowledge_map_choices``.
    """
    quest = db.entity(int(quest_id))
    if quest is None or str(quest["kind"]) != "quest":
        return LootTurnInNavigation(
            "missing_quest",
            "The selected quest is no longer present in canonical knowledge.",
            int(quest_id),
            "",
        )
    quest_name = str(quest["name"])

    contacts = _source_backed_turn_in_contacts(db, int(quest_id))
    if not contacts:
        return LootTurnInNavigation(
            "no_explicit_turn_in_contact",
            f"{quest_name} has no reviewed source-backed turn-in NPC relationship yet.",
            int(quest_id),
            quest_name,
        )
    allowed_ids = {int(row["npc_id"]) for row in contacts}

    base = knowledge_map_choices(db, int(quest_id), current_zone)
    current = tuple(
        choice
        for choice in base.choices
        if choice.origin == "quest_actor"
        and choice.relation == "objective_turn_in_to"
        and int(choice.location_entity_id) in allowed_ids
    )
    remote = tuple(
        choice
        for choice in base.other_zone_choices
        if choice.origin == "quest_actor"
        and choice.relation == "objective_turn_in_to"
        and int(choice.location_entity_id) in allowed_ids
    )

    filtered = KnowledgeMapChoiceSet(
        status="ready" if current else base.status,
        reason=base.reason,
        selected_entity_id=base.selected_entity_id,
        selected_entity_name=base.selected_entity_name,
        current_zone_entity_id=base.current_zone_entity_id,
        current_zone_name=base.current_zone_name,
        choices=current,
        other_zone_choice_count=len(remote),
        other_zone_choices=remote,
    )
    routes = knowledge_route_choices(filtered)

    if current:
        names = ", ".join(dict.fromkeys(choice.location_entity_name for choice in current))
        return LootTurnInNavigation(
            "map_ready",
            f"Reviewed explicit turn-in contact {names} has a safe location in the current zone.",
            int(quest_id),
            quest_name,
            map_choices=current,
            route_choices=routes,
        )
    if routes:
        zones = ", ".join(choice.zone_name for choice in routes)
        return LootTurnInNavigation(
            "route_ready",
            f"Reviewed explicit turn-in contact is safely located outside the current zone: {zones}.",
            int(quest_id),
            quest_name,
            route_choices=routes,
        )

    if base.status in {
        "no_current_zone",
        "current_zone_ambiguous",
        "current_zone_unresolved",
    }:
        return LootTurnInNavigation(
            base.status,
            base.reason,
            int(quest_id),
            quest_name,
        )

    contact_names = ", ".join(str(row["npc_name"]) for row in contacts)
    return LootTurnInNavigation(
        "contact_location_unavailable",
        (
            f"Reviewed turn-in contact is known for {quest_name} ({contact_names}), but no safe canonical "
            "Map/Travel location is currently compiled for that exact contact."
        ),
        int(quest_id),
        quest_name,
    )
