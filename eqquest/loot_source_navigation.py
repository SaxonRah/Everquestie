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
class LootSourceNavigation:
    status: str
    reason: str
    item_id: int
    item_name: str
    source_npc_ids: tuple[int, ...] = ()
    source_npc_names: tuple[str, ...] = ()
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


def _reviewed_source_npcs(db, item_id: int):
    """Return exact NPC identities backed by reviewed item -> NPC drop evidence."""
    return db.conn.execute(
        """
        SELECT DISTINCT n.id AS npc_id, n.name AS npc_name
        FROM entity_relationships r
        JOIN entities n ON n.id=r.target_entity_id AND n.kind='npc'
        WHERE r.source_entity_id=?
          AND r.relation='drops_from'
          AND r.source_page_id IS NOT NULL
        ORDER BY n.name COLLATE NOCASE, n.id
        """,
        (int(item_id),),
    ).fetchall()


def loot_source_navigation(
    db,
    item_id: int,
    current_zone: str | None,
) -> LootSourceNavigation:
    """Project reviewed exact item sources through existing safe Map/Travel rules.

    The drop relationship selects which NPCs count as sources; it never supplies a
    coordinate. NPC locations must independently survive ``knowledge_map_choices`` and
    therefore retain a canonical gameplay zone plus explicit navigable X/Y evidence.

    Only source-backed ``item -> NPC : drops_from`` relationships are eligible. Vendors,
    turn-in contacts, prose mentions, provider candidates and unrelated item locations
    are deliberately excluded from this action.
    """
    item = db.entity(int(item_id))
    if item is None or str(item["kind"] or "") != "item":
        return LootSourceNavigation(
            "missing_item",
            "The selected item is no longer present in canonical knowledge.",
            int(item_id),
            "",
        )
    item_name = str(item["name"] or "")

    sources = _reviewed_source_npcs(db, int(item_id))
    if not sources:
        return LootSourceNavigation(
            "no_reviewed_source",
            (
                f"No reviewed source-backed drop NPC is compiled for {item_name}. "
                "That is a knowledge gap, not a claim that the item has no source."
            ),
            int(item_id),
            item_name,
        )

    source_ids = tuple(int(row["npc_id"]) for row in sources)
    source_names = tuple(str(row["npc_name"]) for row in sources)
    allowed_ids = set(source_ids)

    base = knowledge_map_choices(db, int(item_id), current_zone)
    current = tuple(
        choice
        for choice in base.choices
        if choice.origin == "related_entity"
        and choice.relation == "drops_from"
        and int(choice.location_entity_id) in allowed_ids
    )
    remote = tuple(
        choice
        for choice in base.other_zone_choices
        if choice.origin == "related_entity"
        and choice.relation == "drops_from"
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
        return LootSourceNavigation(
            "map_ready",
            f"Reviewed source NPC {names} has a safe location in the current zone.",
            int(item_id),
            item_name,
            source_ids,
            source_names,
            map_choices=current,
            route_choices=routes,
        )

    if routes:
        zones = ", ".join(dict.fromkeys(choice.zone_name for choice in routes))
        return LootSourceNavigation(
            "route_ready",
            f"Reviewed source NPC locations for {item_name} are in: {zones}.",
            int(item_id),
            item_name,
            source_ids,
            source_names,
            route_choices=routes,
        )

    if base.status in {
        "no_current_zone",
        "current_zone_ambiguous",
        "current_zone_unresolved",
    }:
        return LootSourceNavigation(
            base.status,
            base.reason,
            int(item_id),
            item_name,
            source_ids,
            source_names,
        )

    names = ", ".join(source_names)
    return LootSourceNavigation(
        "source_location_unavailable",
        (
            f"Reviewed drop source NPC evidence is known for {item_name} ({names}), but "
            "none of those exact NPCs currently has a safe canonical Map/Travel location."
        ),
        int(item_id),
        item_name,
        source_ids,
        source_names,
    )
