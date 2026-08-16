from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .db import normalize_name
from .profile_availability import entity_profile_decision


_REVIEWED_QUEST_NPC_RELATIONS = {
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
class NPCQuestConnection:
    quest_id: int
    quest_name: str
    relation: str
    relation_label: str
    evidence: str
    tracked: bool
    profile_status: str


@dataclass(frozen=True, slots=True)
class NPCRelevance:
    npc_id: int
    npc_name: str
    targeted_count: int
    considered_count: int
    last_event_id: int
    connections: tuple[NPCQuestConnection, ...]

    @property
    def observation_count(self) -> int:
        return int(self.targeted_count) + int(self.considered_count)

    @property
    def primary_reason(self) -> str:
        if not self.connections:
            return "No reviewed quest connection is currently known"
        first = self.connections[0]
        extra = len(self.connections) - 1
        suffix = f" + {extra} more" if extra else ""
        return f"{first.relation_label}: {first.quest_name}{suffix}"

    @property
    def observation_text(self) -> str:
        bits: list[str] = []
        if self.targeted_count:
            bits.append(f"targeted x{self.targeted_count}")
        if self.considered_count:
            bits.append(f"considered x{self.considered_count}")
        return ", ".join(bits)


def _bounded(text: str, limit: int = 500) -> str:
    return " ".join(str(text or "").split())[:limit]


def _unique_npc_name_index(db) -> dict[str, int]:
    """Map exact normalized NPC names/aliases that identify exactly one NPC."""
    rows = db.conn.execute(
        """
        SELECT e.id AS entity_id, e.normalized_name AS value
        FROM entities e
        WHERE e.kind='npc'
        UNION ALL
        SELECT e.id AS entity_id, a.normalized_alias AS value
        FROM entity_aliases a
        JOIN entities e ON e.id=a.entity_id
        WHERE e.kind='npc'
        """
    ).fetchall()
    owners: dict[str, set[int]] = {}
    for row in rows:
        key = str(row["value"] or "")
        if key:
            owners.setdefault(key, set()).add(int(row["entity_id"]))
    return {
        key: next(iter(entity_ids))
        for key, entity_ids in owners.items()
        if len(entity_ids) == 1
    }


def _quest_connections_for_npcs(
    db,
    npc_ids: Iterable[int],
) -> dict[int, tuple[NPCQuestConnection, ...]]:
    ids = sorted({int(value) for value in npc_ids})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = db.conn.execute(
        f"""
        SELECT r.target_entity_id AS npc_id,
               r.source_entity_id AS quest_id,
               q.name AS quest_name,
               r.relation,
               r.evidence
        FROM entity_relationships r
        JOIN entities q ON q.id=r.source_entity_id AND q.kind='quest'
        WHERE r.target_entity_id IN ({placeholders})
          AND r.relation IN ('started_by','objective_turn_in_to','objective_speak','objective_kill')
          AND r.source_page_id IS NOT NULL
        ORDER BY r.target_entity_id, r.source_entity_id, r.relation, r.id
        """,
        tuple(ids),
    ).fetchall()

    grouped: dict[int, dict[tuple[int, str], NPCQuestConnection]] = {}
    for row in rows:
        npc_id = int(row["npc_id"])
        quest_id = int(row["quest_id"])
        decision = entity_profile_decision(db, quest_id)
        if decision.compatibility is False:
            continue
        relation = str(row["relation"])
        connection = NPCQuestConnection(
            quest_id=quest_id,
            quest_name=str(row["quest_name"]),
            relation=relation,
            relation_label=_REVIEWED_QUEST_NPC_RELATIONS[relation],
            evidence=_bounded(str(row["evidence"] or "")),
            tracked=bool(db.is_quest_tracked(quest_id)),
            profile_status=str(decision.status or ""),
        )
        grouped.setdefault(npc_id, {}).setdefault((quest_id, relation), connection)

    out: dict[int, tuple[NPCQuestConnection, ...]] = {}
    for npc_id, values in grouped.items():
        out[npc_id] = tuple(
            sorted(
                values.values(),
                key=lambda connection: (
                    0 if connection.tracked else 1,
                    _RELATION_PRIORITY.get(connection.relation, 99),
                    connection.quest_name.casefold(),
                    connection.quest_id,
                ),
            )
        )
    return out


def recent_npc_relevance(
    db,
    after_event_id: int,
    *,
    limit_npcs: int = 10,
) -> tuple[NPCRelevance, ...]:
    """Return source-backed quest relevance for NPCs intentionally observed this session.

    Only direct `target_npc` and `consider` signals participate. Nearby `npc_say`, generic
    combat/death text and fuzzy names never create this projection. The logged name/alias
    must identify exactly one canonical NPC and the quest connection must retain source
    provenance.
    """
    rows = db.conn.execute(
        """
        SELECT id,kind,target
        FROM observed_events
        WHERE id>? AND kind IN ('target_npc','consider') AND COALESCE(target,'')<>''
        ORDER BY id
        """,
        (int(after_event_id),),
    ).fetchall()
    if not rows:
        return ()

    unique_npcs = _unique_npc_name_index(db)
    targeted: dict[int, int] = {}
    considered: dict[int, int] = {}
    last_ids: dict[int, int] = {}
    for row in rows:
        key = normalize_name(str(row["target"] or ""))
        npc_id = unique_npcs.get(key)
        if npc_id is None:
            continue
        if str(row["kind"]) == "target_npc":
            targeted[npc_id] = targeted.get(npc_id, 0) + 1
        else:
            considered[npc_id] = considered.get(npc_id, 0) + 1
        last_ids[npc_id] = max(last_ids.get(npc_id, 0), int(row["id"]))

    observed_ids = set(targeted) | set(considered)
    connections_by_npc = _quest_connections_for_npcs(db, observed_ids)
    relevance: list[NPCRelevance] = []
    for npc_id in observed_ids:
        connections = connections_by_npc.get(npc_id, ())
        if not connections:
            continue
        npc = db.entity(npc_id)
        if npc is None:
            continue
        relevance.append(
            NPCRelevance(
                npc_id=npc_id,
                npc_name=str(npc["name"]),
                targeted_count=int(targeted.get(npc_id, 0)),
                considered_count=int(considered.get(npc_id, 0)),
                last_event_id=int(last_ids[npc_id]),
                connections=connections,
            )
        )

    relevance.sort(
        key=lambda row: (
            -row.last_event_id,
            0 if row.connections[0].tracked else 1,
            _RELATION_PRIORITY.get(row.connections[0].relation, 99),
            row.npc_name.casefold(),
            row.npc_id,
        )
    )
    return tuple(relevance[: max(0, int(limit_npcs))])


def npc_relevance_text(npc: NPCRelevance) -> str:
    lines = [
        npc.npc_name,
        "",
        f"Observed this monitoring session: {npc.observation_text}",
        "",
        "Known source-backed quest connections:",
    ]
    for connection in npc.connections:
        state = "tracked" if connection.tracked else "untracked"
        profile = (
            f"; profile {connection.profile_status}"
            if connection.profile_status not in {"", "available"}
            else ""
        )
        lines.append(
            f"• {connection.quest_name} — {connection.relation_label} ({state}{profile})"
        )
        if connection.evidence:
            lines.append(f"  Evidence: {connection.evidence}")
    lines.extend(
        [
            "",
            "This projection uses intentional target/consider observations plus compiled quest relationships. "
            "It does not mean the quest is owned or that the NPC should be killed.",
        ]
    )
    return "\n".join(lines)
