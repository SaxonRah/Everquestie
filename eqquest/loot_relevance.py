from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .db import normalize_name
from .profile_availability import entity_profile_decision


_REVIEWED_QUEST_ITEM_RELATIONS = {
    "objective_turn_in_item": "turn-in item",
    "objective_loot": "loot objective",
    "quest_item": "source-listed quest item",
}
_RELATION_PRIORITY = {
    "objective_turn_in_item": 0,
    "objective_loot": 1,
    "quest_item": 2,
}


@dataclass(frozen=True, slots=True)
class LootQuestUse:
    quest_id: int
    quest_name: str
    relation: str
    relation_label: str
    quantity: int | None
    evidence: str
    tracked: bool
    profile_status: str


@dataclass(frozen=True, slots=True)
class LootRelevance:
    item_id: int
    item_name: str
    observed_count: int
    last_event_id: int
    uses: tuple[LootQuestUse, ...]

    @property
    def primary_reason(self) -> str:
        if not self.uses:
            return "No reviewed quest use is currently known"
        first = self.uses[0]
        extra = len(self.uses) - 1
        suffix = f" + {extra} more" if extra else ""
        return f"{first.relation_label}: {first.quest_name}{suffix}"


def _bounded(text: str, limit: int = 500) -> str:
    return " ".join(str(text or "").split())[:limit]


def _unique_item_name_index(db) -> dict[str, int]:
    """Map exact item text to one canonical item using exact-first identity semantics.

    A canonical exact name is stronger evidence than an alias on another item.  Aliases
    are consulted only when no canonical item carries that normalized name at all.  True
    duplicate canonical names and duplicate aliases remain ambiguous and are omitted.
    This mirrors the fail-closed identity policy used by tracked quest progress without
    introducing fuzzy or substring matching into Recent Loot.
    """
    exact_rows = db.conn.execute(
        """
        SELECT e.id AS entity_id, e.normalized_name AS value
        FROM entities e
        WHERE e.kind='item'
        """
    ).fetchall()
    exact_owners: dict[str, set[int]] = {}
    for row in exact_rows:
        key = str(row["value"] or "")
        if key:
            exact_owners.setdefault(key, set()).add(int(row["entity_id"]))

    aliases = db.conn.execute(
        """
        SELECT e.id AS entity_id, a.normalized_alias AS value
        FROM entity_aliases a
        JOIN entities e ON e.id=a.entity_id
        WHERE e.kind='item'
        """
    ).fetchall()
    alias_owners: dict[str, set[int]] = {}
    for row in aliases:
        key = str(row["value"] or "")
        if key:
            alias_owners.setdefault(key, set()).add(int(row["entity_id"]))

    resolved: dict[str, int] = {
        key: next(iter(entity_ids))
        for key, entity_ids in exact_owners.items()
        if len(entity_ids) == 1
    }
    for key, entity_ids in alias_owners.items():
        if key in exact_owners:
            continue
        if len(entity_ids) == 1:
            resolved[key] = next(iter(entity_ids))
    return resolved


def _quest_uses_for_items(db, item_ids: Iterable[int]) -> dict[int, tuple[LootQuestUse, ...]]:
    ids = sorted({int(value) for value in item_ids})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = db.conn.execute(
        f"""
        SELECT r.target_entity_id AS item_id,
               r.source_entity_id AS quest_id,
               q.name AS quest_name,
               r.relation,
               r.quantity,
               r.evidence
        FROM entity_relationships r
        JOIN entities q ON q.id=r.source_entity_id AND q.kind='quest'
        WHERE r.target_entity_id IN ({placeholders})
          AND r.relation IN ('objective_turn_in_item','objective_loot','quest_item')
          AND r.source_page_id IS NOT NULL
        ORDER BY r.target_entity_id, r.source_entity_id, r.relation, r.id
        """,
        tuple(ids),
    ).fetchall()

    grouped: dict[int, dict[tuple[int, str], LootQuestUse]] = {}
    for row in rows:
        item_id = int(row["item_id"])
        quest_id = int(row["quest_id"])
        decision = entity_profile_decision(db, quest_id)
        if decision.compatibility is False:
            continue
        relation = str(row["relation"])
        key = (quest_id, relation)
        use = LootQuestUse(
            quest_id=quest_id,
            quest_name=str(row["quest_name"]),
            relation=relation,
            relation_label=_REVIEWED_QUEST_ITEM_RELATIONS[relation],
            quantity=int(row["quantity"]) if row["quantity"] is not None else None,
            evidence=_bounded(str(row["evidence"] or "")),
            tracked=bool(db.is_quest_tracked(quest_id)),
            profile_status=str(decision.status or ""),
        )
        grouped.setdefault(item_id, {}).setdefault(key, use)

    out: dict[int, tuple[LootQuestUse, ...]] = {}
    for item_id, values in grouped.items():
        out[item_id] = tuple(
            sorted(
                values.values(),
                key=lambda use: (
                    _RELATION_PRIORITY.get(use.relation, 99),
                    0 if use.tracked else 1,
                    use.quest_name.casefold(),
                    use.quest_id,
                ),
            )
        )
    return out


def recent_loot_relevance(
    db,
    after_event_id: int,
    *,
    limit_items: int = 10,
) -> tuple[LootRelevance, ...]:
    """Return source-backed quest relevance for exact loot observed this session.

    The observation side is player-owned state. The knowledge side accepts only exact,
    unambiguous canonical item identity and reviewed source-backed quest-item relations.
    Items with no reviewed quest use stay quiet rather than being guessed useful/useless.
    """
    rows = db.conn.execute(
        """
        SELECT id,item
        FROM observed_events
        WHERE id>? AND kind='loot' AND COALESCE(item,'')<>''
        ORDER BY id
        """,
        (int(after_event_id),),
    ).fetchall()
    if not rows:
        return ()

    unique_items = _unique_item_name_index(db)
    counts: dict[int, int] = {}
    last_ids: dict[int, int] = {}
    for row in rows:
        key = normalize_name(str(row["item"] or ""))
        item_id = unique_items.get(key)
        if item_id is None:
            continue
        counts[item_id] = counts.get(item_id, 0) + 1
        last_ids[item_id] = max(last_ids.get(item_id, 0), int(row["id"]))

    uses_by_item = _quest_uses_for_items(db, counts)
    relevance: list[LootRelevance] = []
    for item_id, observed_count in counts.items():
        uses = uses_by_item.get(item_id, ())
        if not uses:
            continue
        item = db.entity(item_id)
        if item is None:
            continue
        relevance.append(
            LootRelevance(
                item_id=item_id,
                item_name=str(item["name"]),
                observed_count=int(observed_count),
                last_event_id=int(last_ids[item_id]),
                uses=uses,
            )
        )

    relevance.sort(
        key=lambda row: (
            -row.last_event_id,
            _RELATION_PRIORITY.get(row.uses[0].relation, 99),
            row.item_name.casefold(),
            row.item_id,
        )
    )
    return tuple(relevance[: max(0, int(limit_items))])


def loot_relevance_text(item: LootRelevance) -> str:
    lines = [
        item.item_name,
        "",
        f"Looted this monitoring session: {item.observed_count}",
        "",
        "Known source-backed quest relevance:",
    ]
    for use in item.uses:
        quantity = f" x{use.quantity}" if use.quantity else ""
        state = "tracked" if use.tracked else "untracked"
        profile = f"; profile {use.profile_status}" if use.profile_status not in {"", "available"} else ""
        lines.append(
            f"• {use.quest_name} — {use.relation_label}{quantity} ({state}{profile})"
        )
        if use.evidence:
            lines.append(f"  Evidence: {use.evidence}")
    lines.extend(
        [
            "",
            "This is a relevance projection from compiled quest relationships. "
            "It does not mean the quest is owned, and an item with no displayed use is not automatically vendor trash.",
        ]
    )
    return "\n".join(lines)
