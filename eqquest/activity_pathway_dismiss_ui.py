from __future__ import annotations

from tkinter import ttk


_ACTIVITY_PATHWAY_DISMISS_MARKER = "_everquestie_activity_pathway_dismiss_ui"


def install_activity_pathway_dismiss_ui() -> None:
    """Add non-persistent dismissal to the existing Potential Pathways surface.

    Dismissal is intentionally UI/session state. The pathway engine continues to report
    every evidence-backed opportunity, and neither the knowledge DB nor writable user DB
    is modified. Starting a new monitoring session clears the dismissed set.
    """
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _ACTIVITY_PATHWAY_DISMISS_MARKER, False):
        return

    current_build_live = current_app._build_live
    current_refresh = current_app._refresh_activity_pathways
    current_start = current_app._start

    def _build_live(self) -> None:
        current_build_live(self)
        self._activity_pathway_dismissed_quests: set[int] = set()

        tree = getattr(self, "activity_pathway_tree", None)
        if tree is None:
            return
        panel = tree.master
        ttk.Button(
            panel,
            text="Dismiss selected for session",
            command=self._activity_pathway_dismiss_selected,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(5, 0))

    def _apply_activity_pathway_dismissals(self) -> int:
        tree = getattr(self, "activity_pathway_tree", None)
        if tree is None:
            return 0
        dismissed = {
            int(value)
            for value in getattr(self, "_activity_pathway_dismissed_quests", set())
        }
        mapping = getattr(self, "_activity_pathway_by_item", {})
        removed = 0
        for iid, suggestion in list(mapping.items()):
            if int(suggestion.quest_id) not in dismissed:
                continue
            try:
                tree.delete(iid)
            except Exception:
                pass
            mapping.pop(iid, None)
            removed += 1
        return removed

    def _refresh_activity_pathways(self, *, force: bool = False) -> None:
        current_refresh(self, force=force)
        _apply_activity_pathway_dismissals(self)

        dismissed_count = len(getattr(self, "_activity_pathway_dismissed_quests", set()))
        if dismissed_count <= 0:
            return
        status = getattr(self, "activity_pathway_status", None)
        if status is None:
            return
        visible = len(getattr(self, "_activity_pathway_by_item", {}))
        monitoring = getattr(self, "tailer", None) is not None
        prefix = "Watching live activity" if monitoring else "Last monitoring session"
        status.set(
            f"{prefix}: {visible} visible potential pathway(s); "
            f"{dismissed_count} dismissed for this session. "
            "Dismissal changes display only; nothing is auto-tracked."
        )

    def _activity_pathway_dismiss_selected(self) -> None:
        selected = getattr(self, "_selected_activity_pathway", lambda: None)()
        if selected is None:
            status = getattr(self, "status", None)
            if status is not None:
                status.set("Select a Potential Pathway to dismiss.")
            return

        dismissed = getattr(self, "_activity_pathway_dismissed_quests", None)
        if dismissed is None:
            dismissed = set()
            self._activity_pathway_dismissed_quests = dismissed
        dismissed.add(int(selected.quest_id))
        self._refresh_activity_pathways(force=True)

        status = getattr(self, "status", None)
        if status is not None:
            status.set(
                f"Dismissed pathway for this monitoring session: {selected.quest_name}."
            )

    def _start(self) -> None:
        # A new monitoring session is a new opportunity context. Clear before the
        # wrapped pathway start performs its forced refresh.
        self._activity_pathway_dismissed_quests = set()
        current_start(self)

    current_app._build_live = _build_live
    current_app._apply_activity_pathway_dismissals = _apply_activity_pathway_dismissals
    current_app._activity_pathway_dismiss_selected = _activity_pathway_dismiss_selected
    current_app._refresh_activity_pathways = _refresh_activity_pathways
    current_app._start = _start
    setattr(current_app, _ACTIVITY_PATHWAY_DISMISS_MARKER, True)
