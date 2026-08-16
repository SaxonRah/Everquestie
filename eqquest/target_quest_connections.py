from __future__ import annotations

from dataclasses import dataclass

from .profile_availability import entity_profile_decision


_RELATION_LABELS = {
    "started_by": "quest starter",
    "objective_turn_in_to": "turn-in NPC",
    "objective_speak": "speak objective",
    "objective_kill": "kill objective",
}
_RELATION_PRIORITY = {
    "started_by": 0,
    "objective_turn_in_to": 1,
    "objective_speak": 2,
    "objective_kill": 3,
}


@dataclass(frozen=True, slots=True)
class TargetQuestConnection:
    quest_id: int
    quest_name: str
    relation: str
    relation_label: str
    evidence: str
    source_url: str
    tracked: bool
    profile_status: str
    profile_reason: str


def _bounded(text: str, limit: int = 600) -> str:
    return " ".join(str(text or "").split())[:limit]


def target_quest_connections(
    db,
    npc_entity_id: int,
    *,
    profile_id: str | None = None,
) -> tuple[TargetQuestConnection, ...]:
    """Return exact, source-backed quest connections for one canonical NPC.

    This projection is intentionally narrower than generic target relationship summaries:
    it returns exact quest IDs so the player can explicitly View/Track the quest. Only
    reviewed quest→NPC relationship kinds participate, every relationship must retain a
    source page, and definitively profile-blocked quests are omitted.
    """
    npc = db.entity(int(npc_entity_id))
    if npc is None or str(npc["kind"] or "") != "npc":
        return ()

    rows = db.conn.execute(
        """
        SELECT r.source_entity_id AS quest_id,
               q.name AS quest_name,
               q.source_url AS quest_source_url,
               r.relation,
               r.evidence,
               r.id AS relationship_id
        FROM entity_relationships r
        JOIN entities q ON q.id=r.source_entity_id AND q.kind='quest'
        WHERE r.target_entity_id=?
          AND r.relation IN ('started_by','objective_turn_in_to','objective_speak','objective_kill')
          AND r.source_page_id IS NOT NULL
        ORDER BY r.source_entity_id, r.relation, r.id
        """,
        (int(npc_entity_id),),
    ).fetchall()

    found: dict[tuple[int, str], TargetQuestConnection] = {}
    for row in rows:
        quest_id = int(row["quest_id"])
        relation = str(row["relation"])
        decision = entity_profile_decision(db, quest_id, profile_id)
        if decision.compatibility is False:
            continue
        key = (quest_id, relation)
        connection = TargetQuestConnection(
            quest_id=quest_id,
            quest_name=str(row["quest_name"]),
            relation=relation,
            relation_label=_RELATION_LABELS[relation],
            evidence=_bounded(str(row["evidence"] or "")),
            source_url=str(row["quest_source_url"] or ""),
            tracked=bool(db.is_quest_tracked(quest_id)),
            profile_status=str(decision.status or ""),
            profile_reason=str(decision.reason or ""),
        )
        # Multiple retained source rows can corroborate the same semantic edge. The
        # player-facing action is the canonical quest+relation, not a provenance-row count.
        found.setdefault(key, connection)

    return tuple(
        sorted(
            found.values(),
            key=lambda connection: (
                0 if connection.tracked else 1,
                _RELATION_PRIORITY.get(connection.relation, 99),
                connection.quest_name.casefold(),
                connection.quest_id,
            ),
        )
    )


def target_quest_connection_text(connection: TargetQuestConnection) -> str:
    lines = [
        connection.quest_name,
        "",
        f"Target connection: {connection.relation_label}",
        f"Tracking: {'tracked' if connection.tracked else 'not tracked'}",
        f"Gameplay profile: {connection.profile_status or 'unknown'}",
    ]
    if connection.profile_reason:
        lines.append(f"Profile reason: {connection.profile_reason}")
    if connection.evidence:
        lines.extend(("", f"Source-backed relationship evidence: {connection.evidence}"))
    if connection.source_url:
        lines.append(f"Quest primary source: {connection.source_url}")
    lines.extend(
        (
            "",
            "This row comes from an exact canonical NPC plus a retained source-backed quest relationship. "
            "It does not mean the quest is owned; tracking changes only after the explicit Track quest action.",
        )
    )
    return "\n".join(lines)
