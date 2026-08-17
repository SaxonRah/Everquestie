from __future__ import annotations

from dataclasses import dataclass

from .quest_progress_identity import exact_entity_name_candidates


_TASK_ASSIGNMENT_TRACKING_MARKER = "_everquestie_task_assignment_tracking_ui"


@dataclass(frozen=True, slots=True)
class TaskAssignmentTrackingResult:
    status: str
    quest_id: int | None = None
    quest_name: str = ""
    was_tracked: bool = False
    reason: str = ""

    @property
    def changed_player_state(self) -> bool:
        return self.status in {"tracked", "restarted"}


def handle_live_task_assignment(app, event) -> TaskAssignmentTrackingResult:
    """Apply one explicit EQ task-assignment line without reading ahead in the log.

    ``You have been assigned the task '…'.`` is direct ownership evidence, but its text
    still has to identify exactly one local quest. The assignment event itself is the
    progress boundary. Reading the whole log from inside the live tailer would look into
    lines that have not been drained yet, causing later objective events to be counted by
    reconciliation and then counted again when they arrive through the live stream.

    A genuine assignment is also *not* evidence of the player's current zone, so this
    path never calls the generic track-and-reconcile helper that may infer quest geography.
    """
    if str(getattr(event, "kind", "") or "").casefold() != "task_assigned":
        return TaskAssignmentTrackingResult(status="ignored")

    text = " ".join(str(getattr(event, "text", "") or "").split()).strip()
    if not text:
        return TaskAssignmentTrackingResult(status="ignored")

    candidates = exact_entity_name_candidates(app.db, "quest", text)
    quest_id = candidates.unique_entity_id
    if quest_id is None:
        if len(candidates.entity_ids) > 1:
            reason = (
                f"assignment name is ambiguous across {len(candidates.entity_ids)} local quests"
            )
            app._append_event(
                f"QUEST | assigned task not auto-tracked; {reason}: {text}"
            )
            return TaskAssignmentTrackingResult(status="ambiguous", reason=reason)

        reason = "assigned task is not uniquely present in local quest knowledge"
        app._append_event(f"QUEST | assigned task not auto-tracked; {reason}: {text}")
        return TaskAssignmentTrackingResult(status="unknown", reason=reason)

    quest_id = int(quest_id)
    was_tracked = any(
        int(row["id"]) == quest_id
        for row in app.db.tracked_quests()
    )

    # The explicit assignment line starts a fresh task instance. Track first so both the
    # builder DB and packaged RuntimeDatabase have writable quest state, then reset only
    # that quest at this exact stream boundary. Do not scan ahead or infer geography.
    app.db.track_quest(quest_id)
    app.db.reset_quest_progress(quest_id)

    row = app.db.entity(quest_id)
    quest_name = str(row["name"]) if row is not None else text
    status = "restarted" if was_tracked else "tracked"
    verb = "restarted assigned task" if was_tracked else "auto-tracked assigned task"
    app._append_event(
        f"QUEST | {verb}: {quest_name} | explicit live assignment boundary; no log lookahead"
    )

    # Tracking immediately changes every untracked-quest recommendation surface. The
    # composed Live refresh is optional here for lightweight/non-UI callers, but when
    # present it removes the newly owned quest before the next periodic tick.
    refresh_live = getattr(app, "_refresh_activity_pathways", None)
    if callable(refresh_live):
        try:
            refresh_live(force=True)
        except Exception:
            pass

    return TaskAssignmentTrackingResult(
        status=status,
        quest_id=quest_id,
        quest_name=quest_name,
        was_tracked=was_tracked,
        reason="explicit EQ task assignment",
    )


def install_task_assignment_tracking_ui() -> None:
    """Replace the legacy permissive/read-ahead task-assignment handler."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _TASK_ASSIGNMENT_TRACKING_MARKER, False):
        return

    def _handle_task_assigned(self, event):
        return handle_live_task_assignment(self, event)

    current_app._handle_task_assigned = _handle_task_assigned
    setattr(current_app, _TASK_ASSIGNMENT_TRACKING_MARKER, True)
