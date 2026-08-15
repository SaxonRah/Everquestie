from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .db import Database
from .knowledge_map_choices import KnowledgeMapChoice, KnowledgeMapChoiceSet, knowledge_map_choices
from .world_entity_context import build_world_entity_context


@dataclass(frozen=True, slots=True)
class LiveQuestObjective:
    quest_entity_id: int
    quest_name: str
    step_order: int
    step_description: str
    step_selection: str
    progress_count: int
    complete: bool
    target_entity_id: int
    target_kind: str
    target_name: str
    target_resolution: str
    choices: tuple[KnowledgeMapChoice, ...]


@dataclass(frozen=True, slots=True)
class LiveQuestMapResult:
    status: str
    reason: str
    objective: LiveQuestObjective | None = None
    choice_set: KnowledgeMapChoiceSet | None = None

    @property
    def ready(self) -> bool:
        return (
            self.status == "ready"
            and self.objective is not None
            and self.choice_set is not None
            and self.choice_set.ready
        )


def _row_value(row: Any, key: str, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _tracked_quest(db: Database, quest_id: int):
    for row in db.tracked_quests():
        if int(_row_value(row, "id", -1)) == int(quest_id):
            return row
    return None


def _parse_match(step: Any) -> dict[str, Any]:
    try:
        value = json.loads(_row_value(step, "match_json", "{}") or "{}")
    except (TypeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _entity_by_match_id(db: Database, value: Any, expected_kind: str | None):
    if value is None or isinstance(value, bool):
        return None
    try:
        entity_id = int(value)
    except (TypeError, ValueError):
        return None
    entity = db.entity(entity_id)
    if entity is None:
        return None
    if expected_kind and str(entity["kind"] or "") != expected_kind:
        return None
    return entity


def _resolve_exact_name(db: Database, value: Any, kind: str | None):
    name = " ".join(str(value or "").split()).strip()
    if not name:
        return None, "missing"
    context, status = build_world_entity_context(db, name, kind)
    if context is None:
        return None, status
    return db.entity(context.entity_id), status


def _resolve_step_target(db: Database, step: Any):
    """Resolve explicit normalized step identity without parsing prose.

    Stable entity IDs, when present, win over display-name fields. Name fallback is
    exact canonical/alias resolution only. The step description itself is never
    heuristically parsed into a target.
    """
    rule = _parse_match(step)
    id_fields = (
        ("npc_entity_id", "npc"),
        ("item_entity_id", "item"),
        ("target_entity_id", None),
    )
    for key, kind in id_fields:
        entity = _entity_by_match_id(db, rule.get(key), kind)
        if entity is not None:
            return entity, f"{key}"

    named_fields: list[tuple[str, str | None]] = []
    if rule.get("item"):
        named_fields.append(("item", "item"))
    if rule.get("npc"):
        named_fields.append(("npc", "npc"))
    event = str(rule.get("event") or "").casefold()
    if rule.get("target") and event in {"kill", "consider", "target_npc"}:
        named_fields.append(("target", "npc"))

    for key, kind in named_fields:
        entity, status = _resolve_exact_name(db, rule.get(key), kind)
        if entity is not None:
            return entity, f"{key}:{status}"
        if status == "ambiguous":
            return None, f"{key}:ambiguous"
    return None, "missing"


def live_quest_map_choices(
    db: Database,
    quest_id: int,
    current_zone: str | None,
    *,
    selected_step_order: int | None = None,
) -> LiveQuestMapResult:
    """Resolve one tracked quest step into the shared safe world-location choices.

    User state decides *which step* is active. Immutable knowledge decides target
    identity and location. No user progress is written and no coordinate is inferred
    from quest prose or relationship text.
    """
    quest = db.entity(int(quest_id))
    if quest is None or str(quest["kind"] or "") != "quest":
        return LiveQuestMapResult("missing_quest", "Selected tracked quest no longer exists in knowledge.")

    tracked = _tracked_quest(db, int(quest_id))
    if tracked is None:
        return LiveQuestMapResult(
            "not_tracked",
            f"{quest['name']} is not currently tracked in Live state.",
        )

    steps = list(db.quest_steps(int(quest_id)))
    if not steps:
        return LiveQuestMapResult(
            "no_steps",
            f"No structured quest steps are known for {quest['name']}.",
        )

    if selected_step_order is not None:
        order = int(selected_step_order)
        selection = "selected_step"
    else:
        order = int(_row_value(tracked, "active_step", 1) or 1)
        selection = "active_step"

    step = next(
        (row for row in steps if int(_row_value(row, "step_order", -1)) == order),
        None,
    )
    if step is None:
        all_complete = all(bool(int(_row_value(row, "complete", 0) or 0)) for row in steps)
        if selected_step_order is None and all_complete:
            return LiveQuestMapResult(
                "quest_complete",
                f"All structured steps are complete for {quest['name']}.",
            )
        return LiveQuestMapResult(
            "step_missing",
            f"Step {order} is not present in structured knowledge for {quest['name']}.",
        )

    target, target_resolution = _resolve_step_target(db, step)
    if target is None:
        if target_resolution.endswith(":ambiguous"):
            return LiveQuestMapResult(
                "target_ambiguous",
                f"Step {order} has an ambiguous explicit target identity; EverQuestie will not guess.",
            )
        return LiveQuestMapResult(
            "no_target_identity",
            f"Step {order} has no explicit normalized item/NPC target identity to map.",
        )

    target_id = int(target["id"])
    choices = knowledge_map_choices(db, target_id, current_zone)
    objective = LiveQuestObjective(
        quest_entity_id=int(quest_id),
        quest_name=str(quest["name"] or ""),
        step_order=order,
        step_description=str(_row_value(step, "description", "") or ""),
        step_selection=selection,
        progress_count=int(_row_value(step, "progress_count", 0) or 0),
        complete=bool(int(_row_value(step, "complete", 0) or 0)),
        target_entity_id=target_id,
        target_kind=str(target["kind"] or ""),
        target_name=str(target["name"] or ""),
        target_resolution=target_resolution,
        choices=choices.choices,
    )
    if not choices.ready:
        return LiveQuestMapResult(
            f"target_{choices.status}",
            f"Step {order} target {objective.target_name}: {choices.reason}",
            objective=objective,
            choice_set=choices,
        )
    return LiveQuestMapResult(
        "ready",
        f"Step {order} has {len(choices.choices)} safe current-zone map choice(s).",
        objective=objective,
        choice_set=choices,
    )
