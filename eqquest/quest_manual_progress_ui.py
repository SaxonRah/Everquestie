from __future__ import annotations

from tkinter import ttk

from .quest_manual_progress import complete_active_tracked_step


_QUEST_MANUAL_PROGRESS_UI_MARKER = "_everquestie_quest_manual_progress_ui"


def _tracked_action_row(app):
    tree = getattr(app, "tracked_tree", None)
    if tree is None:
        return None
    parent = getattr(tree, "master", None)
    if parent is None:
        return None
    try:
        rows = parent.grid_slaves(row=5, column=0)
    except Exception:
        return None
    return rows[0] if rows else None


def install_quest_manual_progress_ui() -> None:
    """Add an explicit, stale-safe manual completion action to tracked objectives."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _QUEST_MANUAL_PROGRESS_UI_MARKER, False):
        return

    current_build_live = current_app._build_live

    def _mark_selected_step_complete(self):
        selected = self._tracked_selected_step()
        if selected is None:
            self.status.set("Manual completion: select an objective row first.")
            return None

        quest_id, step_order = selected
        result = complete_active_tracked_step(self.db, quest_id, step_order)
        if not result.completed:
            self.status.set(f"Manual completion blocked: {result.reason}")
            # Re-project immediately because the rejection may have been caused by
            # tracking/active-step state changing after the row was rendered.
            self._refresh_guidance()
            return result

        label = result.description or f"step {result.step_order}"
        self.status.set(f"Marked objective complete: {label}")
        self._refresh_guidance()

        # Potential Pathways / Zone Opportunities intentionally exclude tracked quests.
        # Re-project the composed Live stack after a player-owned progress mutation so
        # those surfaces cannot retain stale recommendation state.
        refresh_live = getattr(self, "_refresh_activity_pathways", None)
        if callable(refresh_live):
            try:
                refresh_live(force=True)
            except Exception:
                pass
        return result

    def _build_live(self):
        current_build_live(self)
        action_row = _tracked_action_row(self)
        if action_row is None:
            return
        button = ttk.Button(
            action_row,
            text="Mark selected complete",
            command=self._mark_selected_step_complete,
        )
        button.pack(side="left", padx=(6, 0))
        self.mark_selected_step_complete_button = button

    current_app._mark_selected_step_complete = _mark_selected_step_complete
    current_app._build_live = _build_live
    setattr(current_app, _QUEST_MANUAL_PROGRESS_UI_MARKER, True)
