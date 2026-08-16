from __future__ import annotations

from dataclasses import dataclass

from .profile_availability import entity_profile_decision
from .world_profiles import active_world_profile_id


_DIRECT_RELATIONS = {
    "started_by": (0, "Starts quest"),
    "objective_speak": (1, "Conversation target"),
    "objective_turn_in_to": (2, "Turn-in NPC"),
    "objective_kill": (3, "Kill objective"),
    "objective_source_creature": (4, "Objective source creature"),
    "related_creature": (8, "Related creature"),
}
_ITEM_RELATIONS = {
    "objective_loot": (5, "Drops loot objective"),
    "objective_turn_in_item": (6, "Drops turn-in item"),
    "quest_item": (7, "Drops quest item"),
}


@dataclass(frozen=True, slots=True)
class TargetQuestReason:
    path_kind: str
    relation: str
    label: str
    priority: int
    via_item_id: int | None = None
    via_item_name: str = ""
    evidence: str = ""

    @property
    def display_label(self) -> str:
        if self.via_item_name:
            return f"{self.label}: {self.via_item_name}"
        return self.label


@dataclass(frozen=True, slots=True)
class TargetQuestRelevance:
    quest_id: int
    quest_name: str
    tracked: bool
    profile_status: str
    profile_reason: str
    reasons: tuple[TargetQuestReason, ...]

    @property
    def primary_reason(self) -> str:
        return self.reasons[0].display_label if self.reasons else "Source-backed quest relationship"


def _bounded(*parts: str, limit: int = 700) -> str:
    text = " | ".join(
        " ".join(str(part or "").split())
        for part in parts
        if str(part or "").strip()
    )
    return text[: max(0, int(limit))]


def target_quest_relevance(
    db,
    npc_entity_id: int,
    *,
    profile_id: str | None = None,
    limit: int = 12,
) -> tuple[TargetQuestRelevance, ...]:
    """Return exact source-backed quest uses for one already-resolved NPC target.

    Two evidence paths are accepted:

    * direct quest -> NPC semantics such as starter, kill, speak, source-creature or
      turn-in contact;
    * quest -> item plus item -> NPC ``drops_from`` chains where *both* relationship
      rows retain source provenance.

    The function never resolves an NPC from display text and never treats generic prose
    as a quest relationship. Profile-incompatible quests are omitted; unknown lifecycle
    evidence remains visible and labeled by the caller.
    """
    npc = db.entity(int(npc_entity_id))
    if npc is None or str(npc["kind"] or "") != "npc":
        return ()

    selected_profile = profile_id or active_world_profile_id(db)
    grouped: dict[int, dict] = {}

    direct_rows = db.conn.execute(
        """
        SELECT r.id AS relationship_id,
               r.source_entity_id AS quest_id,
               q.name AS quest_name,
               r.relation,
               r.evidence
        FROM entity_relationships r
        JOIN entities q ON q.id=r.source_entity_id AND q.kind='quest'
        WHERE r.target_entity_id=?
          AND r.relation IN (
              'started_by','objective_speak','objective_turn_in_to',
              'objective_kill','objective_source_creature','related_creature'
          )
          AND r.source_page_id IS NOT NULL
        ORDER BY r.source_entity_id, r.id
        """,
        (int(npc_entity_id),),
    ).fetchall()

    for row in direct_rows:
        quest_id = int(row["quest_id"])
        decision = entity_profile_decision(db, quest_id, selected_profile)
        if decision.compatibility is False:
            continue
        relation = str(row["relation"])
        priority, label = _DIRECT_RELATIONS[relation]
        bucket = grouped.setdefault(
            quest_id,
            {
                "name": str(row["quest_name"]),
                "decision": decision,
                "reasons": {},
            },
        )
        key = ("direct", relation, None)
        bucket["reasons"].setdefault(
            key,
            TargetQuestReason(
                path_kind="direct",
                relation=relation,
                label=label,
                priority=priority,
                evidence=_bounded(str(row["evidence"] or "")),
            ),
        )

    chain_rows = db.conn.execute(
        """
        SELECT qi.id AS quest_relationship_id,
               q.id AS quest_id,
               q.name AS quest_name,
               qi.relation AS quest_relation,
               qi.evidence AS quest_evidence,
               i.id AS item_id,
               i.name AS item_name,
               d.id AS drop_relationship_id,
               d.evidence AS drop_evidence
        FROM entity_relationships d
        JOIN entities i ON i.id=d.source_entity_id AND i.kind='item'
        JOIN entity_relationships qi ON qi.target_entity_id=i.id
        JOIN entities q ON q.id=qi.source_entity_id AND q.kind='quest'
        WHERE d.target_entity_id=?
          AND d.relation='drops_from'
          AND d.source_page_id IS NOT NULL
          AND qi.relation IN ('objective_loot','objective_turn_in_item','quest_item')
          AND qi.source_page_id IS NOT NULL
        ORDER BY q.id, i.name COLLATE NOCASE, i.id, qi.id, d.id
        """,
        (int(npc_entity_id),),
    ).fetchall()

    for row in chain_rows:
        quest_id = int(row["quest_id"])
        decision = entity_profile_decision(db, quest_id, selected_profile)
        if decision.compatibility is False:
            continue
        relation = str(row["quest_relation"])
        priority, label = _ITEM_RELATIONS[relation]
        item_id = int(row["item_id"])
        item_name = str(row["item_name"])
        bucket = grouped.setdefault(
            quest_id,
            {
                "name": str(row["quest_name"]),
                "decision": decision,
                "reasons": {},
            },
        )
        key = ("drop_chain", relation, item_id)
        bucket["reasons"].setdefault(
            key,
            TargetQuestReason(
                path_kind="drop_chain",
                relation=relation,
                label=label,
                priority=priority,
                via_item_id=item_id,
                via_item_name=item_name,
                evidence=_bounded(
                    f"drop: {row['drop_evidence'] or ''}",
                    f"quest use: {row['quest_evidence'] or ''}",
                ),
            ),
        )

    results: list[TargetQuestRelevance] = []
    for quest_id, bucket in grouped.items():
        reasons = tuple(
            sorted(
                bucket["reasons"].values(),
                key=lambda reason: (
                    reason.priority,
                    reason.via_item_name.casefold(),
                    reason.via_item_id or 0,
                    reason.relation,
                ),
            )
        )
        decision = bucket["decision"]
        results.append(
            TargetQuestRelevance(
                quest_id=quest_id,
                quest_name=str(bucket["name"]),
                tracked=bool(db.is_quest_tracked(quest_id)),
                profile_status=str(decision.status or ""),
                profile_reason=str(decision.reason or ""),
                reasons=reasons,
            )
        )

    results.sort(
        key=lambda result: (
            0 if result.tracked else 1,
            result.reasons[0].priority if result.reasons else 99,
            result.quest_name.casefold(),
            result.quest_id,
        )
    )
    return tuple(results[: max(0, int(limit))])


def target_quest_relevance_text(value: TargetQuestRelevance) -> str:
    state = "tracked" if value.tracked else "not tracked"
    lines = [
        value.quest_name,
        f"State: {state}",
        f"Gameplay profile: {value.profile_status} — {value.profile_reason}",
        "",
        "Why this exact target is relevant:",
    ]
    for reason in value.reasons:
        lines.append(f"  • {reason.display_label}")
        if reason.evidence:
            lines.append(f"    Evidence: {reason.evidence}")
    lines.extend(
        [
            "",
            "Every listed path uses normalized source-backed relationships. A drop chain "
            "requires both the NPC drop relationship and the quest-item relationship; "
            "EverQuestie does not infer quest relevance from names or prose.",
        ]
    )
    return "\n".join(lines)
