from __future__ import annotations

from dataclasses import dataclass
import json

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
_PARALLEL_COUNT_EVENTS = frozenset({"kill", "loot", "receive_item"})


@dataclass(frozen=True, slots=True)
class TargetQuestReason:
    path_kind: str
    relation: str
    label: str
    priority: int
    via_item_id: int | None = None
    via_item_name: str = ""
    evidence: str = ""
    step_order: int | None = None
    progress_count: int | None = None
    required_count: int | None = None
    active_step: bool = False

    @property
    def display_label(self) -> str:
        text = f"{self.label}: {self.via_item_name}" if self.via_item_name else self.label
        if self.progress_count is not None and self.required_count is not None:
            text += f" [{self.progress_count}/{self.required_count}]"
        return text

    @property
    def progress_label(self) -> str:
        if self.step_order is None:
            return ""
        position = "active" if self.active_step else "parallel"
        if self.progress_count is not None and self.required_count is not None:
            return f"{position} {self.progress_count}/{self.required_count}"
        return position


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

    @property
    def tracked_progress_label(self) -> str:
        for reason in self.reasons:
            if reason.path_kind == "tracked_step" and reason.progress_label:
                return reason.progress_label
        return ""


def _bounded(*parts: str, limit: int = 700) -> str:
    text = " | ".join(
        " ".join(str(part or "").split())
        for part in parts
        if str(part or "").strip()
    )
    return text[: max(0, int(limit))]


def _rule(step) -> dict:
    try:
        value = json.loads(step["match_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _source_backed_drops_for_target(db, npc_entity_id: int) -> dict[int, tuple[str, str]]:
    """Return exact item identities with reviewed item -> NPC drop evidence."""
    rows = db.conn.execute(
        """
        SELECT i.id AS item_id, i.name AS item_name, d.evidence
        FROM entity_relationships d
        JOIN entities i ON i.id=d.source_entity_id AND i.kind='item'
        WHERE d.target_entity_id=?
          AND d.relation='drops_from'
          AND d.source_page_id IS NOT NULL
        ORDER BY i.name COLLATE NOCASE, i.id, d.id
        """,
        (int(npc_entity_id),),
    ).fetchall()
    out: dict[int, tuple[str, str]] = {}
    for row in rows:
        item_id = int(row["item_id"])
        if item_id in out:
            continue
        out[item_id] = (
            str(row["item_name"]),
            _bounded(str(row["evidence"] or "")),
        )
    return out


def _tracked_step_label(event_kind: str, *, active: bool, via_item: bool) -> str:
    prefix = "Active tracked" if active else "Parallel tracked"
    if event_kind == "kill":
        return f"{prefix} kill objective"
    if event_kind == "loot":
        return f"{prefix} loot objective" if via_item else f"{prefix} NPC loot objective"
    if event_kind == "receive_item":
        return f"{prefix} item objective"
    if event_kind in {"say", "npc_say"}:
        return f"{prefix} conversation objective"
    if event_kind == "consider":
        return f"{prefix} target objective"
    return f"{prefix} objective"


def _add_tracked_step_reasons(
    db,
    npc_entity_id: int,
    selected_profile: str,
    grouped: dict[int, dict],
    drops: dict[int, tuple[str, str]],
) -> None:
    """Overlay exact tracked objective/progress evidence onto target relevance.

    This mirrors QuestEngine's ownership rules instead of inventing a separate progress
    model: sequential non-count steps matter only when active, while kill/loot/item
    count objectives may accumulate before they become the active sequential step.
    """
    for tracked in db.tracked_quests():
        quest_id = int(tracked["id"])
        active_order = int(tracked["active_step"])
        decision = entity_profile_decision(db, quest_id, selected_profile)
        if decision.compatibility is False:
            continue

        for step in db.quest_steps(quest_id):
            if bool(int(step["complete"] or 0)):
                continue
            if step["source_page_id"] is None:
                # A player-facing claim that this exact target advances a structured
                # objective must retain a reviewed source boundary.
                continue

            order = int(step["step_order"])
            rule = _rule(step)
            if not rule:
                continue
            event_kind = str(rule.get("event") or "").strip().casefold()
            active = order == active_order
            if not active and event_kind not in _PARALLEL_COUNT_EVENTS:
                continue

            via_item_id: int | None = None
            via_item_name = ""
            drop_evidence = ""
            matched = False

            raw_npc_id = rule.get("npc_entity_id")
            if raw_npc_id is not None:
                try:
                    matched = int(raw_npc_id) == int(npc_entity_id)
                except (TypeError, ValueError):
                    matched = False

            raw_item_id = rule.get("item_entity_id")
            if not matched and raw_item_id is not None and event_kind in {"loot", "receive_item"}:
                try:
                    item_id = int(raw_item_id)
                except (TypeError, ValueError):
                    item_id = -1
                drop = drops.get(item_id)
                if drop is not None:
                    matched = True
                    via_item_id = item_id
                    via_item_name, drop_evidence = drop

            if not matched:
                # Legacy free-text ``npc`` / ``item`` fields are intentionally not
                # matched against the target name here. Exact compiled canonical IDs
                # are required for target-time progress claims.
                continue

            need = max(1, int(rule.get("count", 1) or 1))
            progress = min(max(0, int(step["progress_count"] or 0)), need)
            label = _tracked_step_label(
                event_kind,
                active=active,
                via_item=via_item_id is not None,
            )
            bucket = grouped.setdefault(
                quest_id,
                {
                    "name": str(tracked["name"]),
                    "decision": decision,
                    "reasons": {},
                },
            )
            key = ("tracked_step", order, via_item_id, event_kind)
            bucket["reasons"][key] = TargetQuestReason(
                path_kind="tracked_step",
                relation=f"tracked_{event_kind or 'objective'}",
                label=label,
                priority=-20 if active else -10,
                via_item_id=via_item_id,
                via_item_name=via_item_name,
                evidence=_bounded(
                    f"step {order}: {step['description'] or ''}",
                    f"drop: {drop_evidence}" if drop_evidence else "",
                ),
                step_order=order,
                progress_count=progress,
                required_count=need,
                active_step=active,
            )


def target_quest_relevance(
    db,
    npc_entity_id: int,
    *,
    profile_id: str | None = None,
    limit: int = 12,
) -> tuple[TargetQuestRelevance, ...]:
    """Return exact source-backed quest uses for one already-resolved NPC target.

    Three evidence paths are accepted:

    * exact canonical IDs in source-backed tracked quest steps, preserving current
      progress and QuestEngine's active/parallel-count semantics;
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
    drops = _source_backed_drops_for_target(db, int(npc_entity_id))

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

    _add_tracked_step_reasons(
        db,
        int(npc_entity_id),
        selected_profile,
        grouped,
        drops,
    )

    results: list[TargetQuestRelevance] = []
    for quest_id, bucket in grouped.items():
        reasons = tuple(
            sorted(
                bucket["reasons"].values(),
                key=lambda reason: (
                    reason.priority,
                    reason.step_order if reason.step_order is not None else 10**9,
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
            0 if result.tracked_progress_label.startswith("active") else 1,
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
        if reason.step_order is not None:
            lines.append(
                f"    Structured step {reason.step_order}; "
                f"{'active now' if reason.active_step else 'parallel count objective'}."
            )
        if reason.evidence:
            lines.append(f"    Evidence: {reason.evidence}")
    lines.extend(
        [
            "",
            "Tracked-step progress is read from player state but target identity still "
            "requires an exact canonical ID compiled into the source-backed step. A "
            "drop-backed tracked objective additionally requires reviewed item -> NPC "
            "drop evidence.",
            "",
            "Every listed graph path uses normalized source-backed relationships. "
            "EverQuestie does not infer quest relevance or objective progress from names "
            "or prose.",
        ]
    )
    return "\n".join(lines)
