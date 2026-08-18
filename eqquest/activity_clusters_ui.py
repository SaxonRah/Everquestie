from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .activity_clusters import (
    activity_cluster_summary,
    activity_cluster_text,
    related_pathway_names,
)
from .live_composition import chain_activity_pathways_refresh, chain_live_build


_ACTIVITY_CLUSTERS_MARKER = "_everquestie_activity_clusters_ui"


def install_activity_clusters_ui() -> None:
    """Add a compact current-zone activity pattern beneath Potential Pathways."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _ACTIVITY_CLUSTERS_MARKER, False):
        return

    def _build_activity_clusters(self) -> None:
        panel = ttk.LabelFrame(self.live_tab, text="Current Activity", padding=6)
        panel.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        panel.columnconfigure(0, weight=1)
        self.activity_cluster_status = tk.StringVar(
            value=(
                "Repeated kill/loot activity in your current zone will appear here. "
                "This is a log pattern, not an inferred named camp."
            )
        )
        ttk.Label(
            panel,
            textvariable=self.activity_cluster_status,
            justify="left",
            wraplength=1050,
        ).grid(row=0, column=0, sticky="ew")

    def _refresh_activity_cluster(self) -> None:
        status = getattr(self, "activity_cluster_status", None)
        if status is None:
            return

        boundary = int(getattr(self, "_activity_session_start_event_id", 0) or 0)
        current_zone = getattr(self.state_model, "current_zone", None)
        summary = activity_cluster_summary(
            self.db,
            boundary,
            current_zone=current_zone,
        )
        dismissed = {
            int(value)
            for value in getattr(self, "_activity_pathway_dismissed_quests", set())
        }
        suggestions = tuple(
            suggestion
            for suggestion in getattr(self, "_activity_pathway_by_item", {}).values()
            if int(suggestion.quest_id) not in dismissed
        )
        related = related_pathway_names(summary, suggestions)
        text = activity_cluster_text(summary, pathway_names=related)
        monitoring = getattr(self, "tailer", None) is not None

        if text:
            status.set(text)
        elif monitoring:
            status.set(
                "Watching current-zone activity. A cluster appears after repeated kill/loot "
                "signals; one-off events stay quiet."
            )
        else:
            status.set(
                "Start monitoring to summarize repeated current-zone kill/loot activity. "
                "Nothing here changes canonical knowledge or quest progress."
            )

    chain_live_build(current_app, _build_activity_clusters)
    current_app._refresh_activity_cluster = _refresh_activity_cluster
    chain_activity_pathways_refresh(
        current_app,
        _refresh_activity_cluster,
        pass_force=False,
    )
    setattr(current_app, _ACTIVITY_CLUSTERS_MARKER, True)
