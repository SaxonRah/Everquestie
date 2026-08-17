from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ManualStepCompletionResult:
    status: str
    quest_id: int
    step_order: int
    description: str = ""
    progress_count: int = 0
    active_step: int | None = None
    reason: str = ""

    @property
    def completed(self) -> bool:
        return self.status == "completed"


def _required_count(match_json: str | None) -> int:
    try:
        rule = json.loads(match_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return 1
    try:
        return max(1, int(rule.get("count", 1)))
    except (TypeError, ValueError):
        return 1


def complete_active_tracked_step(
    db,
    quest_id: int,
    step_order: int,
) -> ManualStepCompletionResult:
    """Explicitly complete exactly one still-active tracked quest step.

    This is a player-state mutation boundary, not an inference engine. The caller must
    supply an exact selected step. Writable tracking state is re-read immediately here;
    stale UI snapshots cannot complete a quest that was untracked or a step that is no
    longer active.

    Requiring the selected step to remain active is important for the combined builder
    DB, whose legacy ``set_step_progress`` advances relative to the completed step. It
    also gives RuntimeDatabase one consistent contract even though that implementation
    globally recomputes the first pending step.
    """
    quest_id = int(quest_id)
    step_order = int(step_order)

    tracked = next(
        (row for row in db.tracked_quests() if int(row["id"]) == quest_id),
        None,
    )
    if tracked is None:
        return ManualStepCompletionResult(
            status="not_tracked",
            quest_id=quest_id,
            step_order=step_order,
            reason="The quest is no longer tracked.",
        )

    active_step = int(tracked["active_step"])
    if step_order != active_step:
        return ManualStepCompletionResult(
            status="not_active",
            quest_id=quest_id,
            step_order=step_order,
            active_step=active_step,
            reason=(
                f"Selected step {step_order} is no longer the active step "
                f"(current active step: {active_step})."
            ),
        )

    step = next(
        (
            row
            for row in db.quest_steps(quest_id)
            if int(row["step_order"]) == step_order
        ),
        None,
    )
    if step is None:
        return ManualStepCompletionResult(
            status="missing_step",
            quest_id=quest_id,
            step_order=step_order,
            active_step=active_step,
            reason="The selected objective no longer exists in current quest knowledge.",
        )

    description = " ".join(str(step["description"] or "").split()).strip()
    current = max(0, int(step["progress_count"] or 0))
    if int(step["complete"]):
        return ManualStepCompletionResult(
            status="already_complete",
            quest_id=quest_id,
            step_order=step_order,
            description=description,
            progress_count=current,
            active_step=active_step,
            reason="The selected objective is already complete.",
        )

    required = _required_count(step["match_json"])
    completed_count = max(current, required)
    db.set_step_progress(quest_id, step_order, completed_count, True)

    tracked_after = next(
        (row for row in db.tracked_quests() if int(row["id"]) == quest_id),
        None,
    )
    active_after = int(tracked_after["active_step"]) if tracked_after is not None else None
    return ManualStepCompletionResult(
        status="completed",
        quest_id=quest_id,
        step_order=step_order,
        description=description,
        progress_count=completed_count,
        active_step=active_after,
        reason="Marked complete by explicit player action.",
    )
