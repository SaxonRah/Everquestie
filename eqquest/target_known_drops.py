from __future__ import annotations

from dataclasses import dataclass

from .profile_availability import entity_profile_decision
from .world_profiles import active_world_profile_id


_QUEST_ITEM_LABELS = {
    "objective_loot": "loot objective",
    "objective_turn_in_item": "turn-in item",
    "quest_item": "quest item",
}
_QUEST_ITEM_PRIORITY = {
    "objective_turn_in_item": 0,
    "objective_loot": 1,
    "quest_item": 2,
}


@dataclass(frozen=True, slots=True)
class TargetDropQuestUse:
    quest_id: int
    quest_name: str
    relation: str
    relation_label: str
    tracked: bool
    profile_status: str


@dataclass(frozen=True, slots=True)
class TargetKnownDrop:
    item_id: int
    item_name: str
    profile_status: str
    profile_reason: str
    evidence_count: int
    source_labels: tuple[str, ...]
    evidence: tuple[str, ...]
    quest_uses: tuple[TargetDropQuestUse, ...]

    @property
    def quest_use_label(self) -> str:
        if not self.quest_uses:
            return "no reviewed quest use"
        first = self.quest_uses[0]
        suffix = f" + {len(self.quest_uses) - 1} more" if len(self.quest_uses) > 1 else ""
        tracked = " [tracked]" if first.tracked else ""
        return f"{first.relation_label}: {first.quest_name}{tracked}{suffix}"

    @property
    def source_label(self) -> str:
        if not self.source_labels:
            return f"{self.evidence_count} evidence row(s)"
        sources = ", ".join(self.source_labels)
        return f"{sources}; {self.evidence_count} evidence row(s)"


def _bounded(text: str, limit: int = 500) -> str:
    return " ".join(str(text or "").split())[: max(0, int(limit))]


def _quest_uses_for_items(
    db,
    item_ids: tuple[int, ...],
    *,
    profile_id: str,
) -> dict[int, tuple[TargetDropQuestUse, ...]]:
    if not item_ids:
        return {}
    placeholders = ",".join("?" for _ in item_ids)
    rows = db.conn.execute(
        f"""
        SELECT r.target_entity_id AS item_id,
               r.source_entity_id AS quest_id,
               q.name AS quest_name,
               r.relation
        FROM entity_relationships r
        JOIN entities q ON q.id=r.source_entity_id AND q.kind='quest'
        WHERE r.target_entity_id IN ({placeholders})
          AND r.relation IN ('objective_loot','objective_turn_in_item','quest_item')
          AND r.source_page_id IS NOT NULL
        ORDER BY r.target_entity_id, r.source_entity_id, r.relation, r.id
        """,
        item_ids,
    ).fetchall()

    grouped: dict[int, dict[tuple[int, str], TargetDropQuestUse]] = {}
    for row in rows:
        item_id = int(row["item_id"])
        quest_id = int(row["quest_id"])
        decision = entity_profile_decision(db, quest_id, profile_id)
        if decision.compatibility is False:
            continue
        relation = str(row["relation"])
        grouped.setdefault(item_id, {}).setdefault(
            (quest_id, relation),
            TargetDropQuestUse(
                quest_id=quest_id,
                quest_name=str(row["quest_name"]),
                relation=relation,
                relation_label=_QUEST_ITEM_LABELS[relation],
                tracked=bool(db.is_quest_tracked(quest_id)),
                profile_status=str(decision.status or ""),
            ),
        )

    out: dict[int, tuple[TargetDropQuestUse, ...]] = {}
    for item_id, uses in grouped.items():
        out[item_id] = tuple(
            sorted(
                uses.values(),
                key=lambda use: (
                    0 if use.tracked else 1,
                    _QUEST_ITEM_PRIORITY.get(use.relation, 99),
                    use.quest_name.casefold(),
                    use.quest_id,
                ),
            )
        )
    return out


def target_known_drops(
    db,
    npc_entity_id: int,
    *,
    profile_id: str | None = None,
    limit: int = 40,
) -> tuple[TargetKnownDrop, ...]:
    """Return exact source-backed item drops for one already-resolved canonical NPC.

    ``drops_from`` is stored as item -> NPC. Only rows retaining ``source_page_id`` are
    eligible for the player-facing drop browser. Duplicate provenance rows are grouped
    by exact canonical item ID rather than inflating the drop list.

    This projection intentionally does not invent drop rates, rarity, commonality or
    completeness. Missing items mean only that no reviewed normalized drop relationship
    is present in the current knowledge snapshot.
    """
    npc = db.entity(int(npc_entity_id))
    if npc is None or str(npc["kind"] or "") != "npc":
        return ()

    selected_profile = profile_id or active_world_profile_id(db)
    rows = db.conn.execute(
        """
        SELECT r.source_entity_id AS item_id,
               i.name AS item_name,
               r.evidence,
               r.source_page_id,
               sp.source_name,
               sp.title
        FROM entity_relationships r
        JOIN entities i ON i.id=r.source_entity_id AND i.kind='item'
        LEFT JOIN source_pages sp ON sp.id=r.source_page_id
        WHERE r.target_entity_id=?
          AND r.relation='drops_from'
          AND r.source_page_id IS NOT NULL
        ORDER BY i.name COLLATE NOCASE, i.id, r.id
        """,
        (int(npc_entity_id),),
    ).fetchall()
    if not rows:
        return ()

    grouped: dict[int, dict] = {}
    for row in rows:
        item_id = int(row["item_id"])
        bucket = grouped.setdefault(
            item_id,
            {
                "name": str(row["item_name"]),
                "source_page_ids": set(),
                "source_labels": [],
                "evidence": [],
            },
        )
        page_id = int(row["source_page_id"])
        bucket["source_page_ids"].add(page_id)
        source = " ".join(str(row["source_name"] or "").split()).strip()
        title = " ".join(str(row["title"] or "").split()).strip()
        label = source or title
        if label and label not in bucket["source_labels"]:
            bucket["source_labels"].append(label)
        evidence = _bounded(str(row["evidence"] or ""))
        if evidence and evidence not in bucket["evidence"]:
            bucket["evidence"].append(evidence)

    item_ids = tuple(sorted(grouped))
    quest_uses = _quest_uses_for_items(db, item_ids, profile_id=selected_profile)
    drops: list[TargetKnownDrop] = []
    for item_id in item_ids:
        bucket = grouped[item_id]
        decision = entity_profile_decision(db, item_id, selected_profile)
        if decision.compatibility is False:
            continue
        drops.append(
            TargetKnownDrop(
                item_id=item_id,
                item_name=str(bucket["name"]),
                profile_status=str(decision.status or ""),
                profile_reason=str(decision.reason or ""),
                evidence_count=len(bucket["source_page_ids"]),
                source_labels=tuple(bucket["source_labels"][:4]),
                evidence=tuple(bucket["evidence"][:4]),
                quest_uses=quest_uses.get(item_id, ()),
            )
        )

    drops.sort(
        key=lambda drop: (
            0 if any(use.tracked for use in drop.quest_uses) else 1,
            0 if drop.quest_uses else 1,
            drop.item_name.casefold(),
            drop.item_id,
        )
    )
    return tuple(drops[: max(0, int(limit))])


def target_known_drop_text(target_name: str, drop: TargetKnownDrop) -> str:
    lines = [
        drop.item_name,
        f"Known source-backed drop from exact target: {target_name}",
        f"Gameplay profile: {drop.profile_status} — {drop.profile_reason}",
        f"Drop evidence: {drop.evidence_count} reviewed source page(s)",
    ]
    if drop.source_labels:
        lines.append("Sources: " + ", ".join(drop.source_labels))
    if drop.quest_uses:
        lines += ["", "Reviewed quest uses:"]
        for use in drop.quest_uses:
            state = "tracked" if use.tracked else "untracked"
            profile = (
                f"; profile {use.profile_status}"
                if use.profile_status not in {"", "available"}
                else ""
            )
            lines.append(
                f"  • {use.quest_name} — {use.relation_label} ({state}{profile})"
            )
    if drop.evidence:
        lines += ["", "Drop evidence:"]
        lines.extend(f"  • {text}" for text in drop.evidence)
    lines += [
        "",
        "This means the current normalized knowledge contains reviewed item -> NPC "
        "drop evidence. It does not imply a drop rate, rarity tier, guaranteed drop, or "
        "complete loot table.",
    ]
    return "\n".join(lines)
