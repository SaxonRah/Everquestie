from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .activity_pathways import ActivityPathwayEngine, PathwaySuggestion, pathway_detail_text


_ACTIVITY_PATHWAYS_MARKER = "_everquestie_activity_pathways_ui"


def install_activity_pathways_ui() -> None:
    """Add evidence-backed live activity opportunities without changing quest state."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _ACTIVITY_PATHWAYS_MARKER, False):
        return

    current_build_live = current_app._build_live
    current_start = current_app._start
    current_stop = current_app._stop

    def _build_live(self) -> None:
        current_build_live(self)

        self.activity_pathway_engine = ActivityPathwayEngine(self.db)
        self.activity_pathway_engine.reset_session(
            self.activity_pathway_engine.latest_observed_event_id()
        )
        self._activity_pathway_by_item: dict[str, PathwaySuggestion] = {}
        self._activity_pathway_signature = None

        self.live_tab.rowconfigure(1, weight=0)
        panel = ttk.LabelFrame(self.live_tab, text="Potential Pathways", padding=6)
        panel.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        panel.columnconfigure(0, weight=1)

        self.activity_pathway_status = tk.StringVar(
            value=(
                "Start monitoring to discover source-backed quest opportunities from "
                "exact kill and loot activity. Nothing is auto-tracked."
            )
        )
        ttk.Label(
            panel,
            textvariable=self.activity_pathway_status,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        columns = ("why", "score")
        self.activity_pathway_tree = ttk.Treeview(
            panel,
            columns=columns,
            show="tree headings",
            selectmode="browse",
            height=4,
        )
        self.activity_pathway_tree.heading("#0", text="Quest")
        self.activity_pathway_tree.heading("why", text="Why it appeared")
        self.activity_pathway_tree.heading("score", text="Signal")
        self.activity_pathway_tree.column("#0", width=290, minwidth=180, stretch=True)
        self.activity_pathway_tree.column("why", width=430, minwidth=220, stretch=True)
        self.activity_pathway_tree.column(
            "score", width=70, minwidth=60, stretch=False, anchor="center"
        )
        self.activity_pathway_tree.grid(row=1, column=0, sticky="ew")
        scroll = ttk.Scrollbar(
            panel, orient="vertical", command=self.activity_pathway_tree.yview
        )
        scroll.grid(row=1, column=1, sticky="ns")
        self.activity_pathway_tree.configure(yscrollcommand=scroll.set)
        self.activity_pathway_tree.bind(
            "<Double-1>", lambda _event: self._activity_pathway_view_selected()
        )

        buttons = ttk.Frame(panel)
        buttons.grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Button(
            buttons,
            text="View quest",
            command=self._activity_pathway_view_selected,
        ).pack(side="left")
        ttk.Button(
            buttons,
            text="Track quest",
            command=self._activity_pathway_track_selected,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Why this?",
            command=self._activity_pathway_explain_selected,
        ).pack(side="left", padx=(6, 0))

        self.after(1000, self._activity_pathway_tick)

    def _selected_pathway(self) -> PathwaySuggestion | None:
        tree = getattr(self, "activity_pathway_tree", None)
        if tree is None:
            return None
        selected = tree.selection()
        if not selected:
            return None
        return getattr(self, "_activity_pathway_by_item", {}).get(selected[0])

    def _activity_pathway_view_selected(self) -> None:
        suggestion = _selected_pathway(self)
        if suggestion is None:
            return
        # This existing exact-ID handoff opens Knowledge without resolving by name,
        # so duplicate quest names remain distinct.
        self._map_entity_selected(int(suggestion.quest_id))

    def _activity_pathway_track_selected(self) -> None:
        suggestion = _selected_pathway(self)
        if suggestion is None:
            return
        self._track_and_reconcile(
            int(suggestion.quest_id),
            announce="PATHWAY | tracking suggested quest",
        )
        self._refresh_guidance()
        self._refresh_activity_pathways(force=True)

    def _activity_pathway_explain_selected(self) -> None:
        suggestion = _selected_pathway(self)
        if suggestion is None:
            return
        messagebox.showinfo("Potential Pathway", pathway_detail_text(suggestion))

    def _refresh_activity_pathways(self, *, force: bool = False) -> None:
        engine = getattr(self, "activity_pathway_engine", None)
        tree = getattr(self, "activity_pathway_tree", None)
        if engine is None or tree is None:
            return

        monitoring = getattr(self, "tailer", None) is not None
        if monitoring:
            engine.refresh_observations()

        suggestions = engine.suggestions(
            getattr(self.state_model, "current_zone", None),
            limit=10,
        )
        signature = tuple(
            (
                suggestion.quest_id,
                suggestion.score,
                tuple(
                    (e.event_kind, e.subject, e.observed_count, e.step_order)
                    for e in suggestion.evidence
                ),
            )
            for suggestion in suggestions
        )
        if force or signature != getattr(self, "_activity_pathway_signature", None):
            previous = tree.selection()
            previous_quest = None
            if previous:
                old = getattr(self, "_activity_pathway_by_item", {}).get(previous[0])
                previous_quest = old.quest_id if old is not None else None

            tree.delete(*tree.get_children(""))
            self._activity_pathway_by_item = {}
            for suggestion in suggestions:
                iid = f"pathway:{suggestion.quest_id}"
                strength = (
                    "high"
                    if suggestion.score >= 90
                    else "medium"
                    if suggestion.score >= 55
                    else "new"
                )
                tree.insert(
                    "",
                    "end",
                    iid=iid,
                    text=suggestion.quest_name,
                    values=(suggestion.primary_reason, strength),
                )
                self._activity_pathway_by_item[iid] = suggestion
                if previous_quest == suggestion.quest_id:
                    tree.selection_set(iid)
                    tree.focus(iid)
            self._activity_pathway_signature = signature

        if suggestions:
            prefix = "Watching live activity" if monitoring else "Last monitoring session"
            self.activity_pathway_status.set(
                f"{prefix}: {len(suggestions)} potential quest pathway(s). "
                "Exact structured objectives only; nothing is auto-tracked."
            )
        elif monitoring:
            self.activity_pathway_status.set(
                "Watching live activity. Potential pathways appear when exact kill/loot "
                "observations match structured quest objectives."
            )
        else:
            self.activity_pathway_status.set(
                "Start monitoring to discover source-backed quest opportunities from "
                "exact kill and loot activity. Nothing is auto-tracked."
            )

    def _activity_pathway_tick(self) -> None:
        self._refresh_activity_pathways()
        self.after(1000, self._activity_pathway_tick)

    def _start(self) -> None:
        current_start(self)
        engine = getattr(self, "activity_pathway_engine", None)
        if engine is not None and getattr(self, "tailer", None) is not None:
            engine.reset_session(engine.latest_observed_event_id())
            self._activity_pathway_signature = None
            self._refresh_activity_pathways(force=True)

    def _stop(self) -> None:
        current_stop(self)
        if hasattr(self, "activity_pathway_status"):
            self._refresh_activity_pathways(force=True)

    current_app._build_live = _build_live
    current_app._selected_activity_pathway = _selected_pathway
    current_app._activity_pathway_view_selected = _activity_pathway_view_selected
    current_app._activity_pathway_track_selected = _activity_pathway_track_selected
    current_app._activity_pathway_explain_selected = _activity_pathway_explain_selected
    current_app._refresh_activity_pathways = _refresh_activity_pathways
    current_app._activity_pathway_tick = _activity_pathway_tick
    current_app._start = _start
    current_app._stop = _stop
    setattr(current_app, _ACTIVITY_PATHWAYS_MARKER, True)
