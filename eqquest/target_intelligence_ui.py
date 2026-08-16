from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .knowledge_map_choices import knowledge_map_choices, knowledge_route_choices
from .target_intelligence import (
    TargetIntelligence,
    current_target_intelligence,
    target_intelligence_compact_text,
    target_intelligence_detail_text,
)
from .target_quest_connections import (
    TargetQuestConnection,
    target_quest_connection_text,
    target_quest_connections,
)


_TARGET_INTELLIGENCE_MARKER = "_everquestie_target_intelligence_ui"


def install_target_intelligence_ui() -> None:
    """Add exact current-target context and safe navigation to the Live tab."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _TARGET_INTELLIGENCE_MARKER, False):
        return

    current_build_live = current_app._build_live
    current_refresh_pathways = current_app._refresh_activity_pathways

    def _build_live(self) -> None:
        current_build_live(self)

        panel = ttk.LabelFrame(self.live_tab, text="Target Intelligence", padding=6)
        panel.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        panel.columnconfigure(0, weight=1)

        self.target_intelligence_status = tk.StringVar(
            value=(
                "Target or consider an NPC while monitoring to see exact source-backed "
                "context. EverQuestie will not fuzzy-match a target name."
            )
        )
        ttk.Label(
            panel,
            textvariable=self.target_intelligence_status,
            justify="left",
            wraplength=1060,
        ).grid(row=0, column=0, sticky="ew")

        buttons = ttk.Frame(panel)
        buttons.grid(row=0, column=1, sticky="e", padx=(10, 0))
        ttk.Button(
            buttons,
            text="View target",
            command=self._target_intelligence_view,
        ).pack(side="left")
        ttk.Button(
            buttons,
            text="Navigate",
            command=self._target_intelligence_navigate,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Details",
            command=self._target_intelligence_details,
        ).pack(side="left", padx=(6, 0))

        ttk.Label(
            panel,
            text="Exact source-backed quest connections",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 2))

        self.target_quest_tree = ttk.Treeview(
            panel,
            columns=("connection", "status"),
            show="tree headings",
            selectmode="browse",
            height=3,
        )
        self.target_quest_tree.heading("#0", text="Quest")
        self.target_quest_tree.heading("connection", text="Target connection")
        self.target_quest_tree.heading("status", text="Quest status")
        self.target_quest_tree.column("#0", width=360, minwidth=180, stretch=True)
        self.target_quest_tree.column("connection", width=160, minwidth=120, stretch=False)
        self.target_quest_tree.column("status", width=150, minwidth=110, stretch=False)
        self.target_quest_tree.grid(row=2, column=0, sticky="ew")
        quest_scroll = ttk.Scrollbar(
            panel,
            orient="vertical",
            command=self.target_quest_tree.yview,
        )
        quest_scroll.grid(row=2, column=1, sticky="ns")
        self.target_quest_tree.configure(yscrollcommand=quest_scroll.set)
        self.target_quest_tree.bind(
            "<Double-1>", lambda _event: self._target_intelligence_view_quest()
        )

        quest_buttons = ttk.Frame(panel)
        quest_buttons.grid(row=3, column=0, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Button(
            quest_buttons,
            text="View quest",
            command=self._target_intelligence_view_quest,
        ).pack(side="left")
        ttk.Button(
            quest_buttons,
            text="Track quest",
            command=self._target_intelligence_track_quest,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            quest_buttons,
            text="Why linked?",
            command=self._target_intelligence_why_quest,
        ).pack(side="left", padx=(6, 0))

        self._target_intelligence_value: TargetIntelligence | None = None
        self._target_intelligence_signature = None
        self._target_quest_connections_by_item: dict[str, TargetQuestConnection] = {}
        self._refresh_target_intelligence(force=True)

    def _target_intelligence_view(self) -> None:
        value = getattr(self, "_target_intelligence_value", None)
        if value is None or not value.resolved or value.entity_id is None:
            self.status.set("No exact current NPC target is available to open in Knowledge.")
            return

        opener = getattr(self, "_open_knowledge_entity_exact", None)
        if callable(opener):
            opener(int(value.entity_id))
        else:
            self._map_entity_selected(int(value.entity_id))

    def _target_intelligence_navigate(self) -> None:
        value = getattr(self, "_target_intelligence_value", None)
        if value is None or not value.resolved or value.entity_id is None:
            self.status.set("No exact current NPC target is available for navigation.")
            return

        choices = knowledge_map_choices(
            self.db,
            int(value.entity_id),
            getattr(self.state_model, "current_zone", None),
        )
        if choices.ready:
            if len(choices.choices) == 1:
                choice = choices.choices[0]
            else:
                from .knowledge_location_ui import ask_knowledge_map_choice

                choice = ask_knowledge_map_choice(
                    self,
                    value.canonical_name,
                    choices.current_zone_name,
                    choices.choices,
                )
                if choice is None:
                    self.status.set("Target location selection cancelled.")
                    return
            self._focus_navigation_map_target(
                choice.zone_name,
                choice.x,
                choice.y,
                choice.z,
                choice.map_label,
            )
            self.status.set(
                f"Mapped exact target {value.canonical_name} at {choice.loc_text}."
            )
            return

        routes = knowledge_route_choices(choices)
        if routes:
            if len(routes) == 1:
                route = routes[0]
            else:
                from .knowledge_location_ui import ask_knowledge_route_choice

                route = ask_knowledge_route_choice(
                    self,
                    value.canonical_name,
                    choices.current_zone_name,
                    routes,
                )
                if route is None:
                    self.status.set("Target route selection cancelled.")
                    return

            travel = getattr(self, "travel_tab", None)
            if travel is None or not hasattr(travel, "route_to_zone"):
                self.status.set("Travel routing is not connected in this application surface.")
                return
            self.notebook.select(self.travel_tab)
            routed = bool(self.travel_tab.route_to_zone(route.zone_name))
            if routed:
                self.status.set(
                    f"Travel route opened to {route.zone_name} for target {value.canonical_name}."
                )
            else:
                self.status.set(
                    f"No confirmed route to {route.zone_name} is currently available; "
                    "see Travel for details."
                )
            return

        self.status.set(choices.reason)

    def _target_intelligence_details(self) -> None:
        value = getattr(self, "_target_intelligence_value", None)
        if value is None:
            value = current_target_intelligence(
                self.db,
                after_event_id=int(
                    getattr(self, "_activity_session_start_event_id", 0) or 0
                ),
            )
        messagebox.showinfo(
            "Target Intelligence",
            target_intelligence_detail_text(value),
        )

    def _selected_target_quest_connection(self) -> TargetQuestConnection | None:
        tree = getattr(self, "target_quest_tree", None)
        if tree is None:
            return None
        selected = tree.selection()
        if not selected:
            return None
        return getattr(self, "_target_quest_connections_by_item", {}).get(selected[0])

    def _target_intelligence_view_quest(self) -> None:
        connection = _selected_target_quest_connection(self)
        if connection is None:
            self.status.set("Select an exact Target Intelligence quest connection first.")
            return
        opener = getattr(self, "_open_knowledge_entity_exact", None)
        if callable(opener):
            opener(int(connection.quest_id))
        else:
            self._map_entity_selected(int(connection.quest_id))

    def _target_intelligence_track_quest(self) -> None:
        connection = _selected_target_quest_connection(self)
        if connection is None:
            self.status.set("Select an exact Target Intelligence quest connection first.")
            return
        if connection.tracked:
            self.status.set(f"{connection.quest_name} is already tracked.")
            return
        self._track_and_reconcile(
            int(connection.quest_id),
            announce="TARGET INTELLIGENCE | tracking selected quest",
        )
        self._refresh_guidance()
        self._refresh_activity_pathways(force=True)

    def _target_intelligence_why_quest(self) -> None:
        connection = _selected_target_quest_connection(self)
        if connection is None:
            self.status.set("Select an exact Target Intelligence quest connection first.")
            return
        messagebox.showinfo(
            "Target Intelligence — Quest Connection",
            target_quest_connection_text(connection),
        )

    def _refresh_target_intelligence(self, *, force: bool = False) -> None:
        status = getattr(self, "target_intelligence_status", None)
        if status is None:
            return

        value = current_target_intelligence(
            self.db,
            after_event_id=int(
                getattr(self, "_activity_session_start_event_id", 0) or 0
            ),
        )
        quest_connections = (
            target_quest_connections(self.db, int(value.entity_id))
            if value.resolved and value.entity_id is not None
            else ()
        )
        signature = (
            value.status,
            value.observed_name,
            value.observed_event_kind,
            value.event_id,
            value.entity_id,
            value.canonical_name,
            value.resolution_kind,
            value.level_min,
            value.level_max,
            value.profile_status,
            value.profile_reason,
            tuple(
                (row.label, row.other_kind, row.count, row.examples)
                for row in value.relationships
            ),
            value.known_zones,
            value.personal_observed_slain,
            value.personal_targeted,
            tuple(
                (
                    connection.quest_id,
                    connection.relation,
                    connection.tracked,
                    connection.profile_status,
                    connection.profile_reason,
                    connection.evidence,
                )
                for connection in quest_connections
            ),
        )
        if force or signature != getattr(self, "_target_intelligence_signature", None):
            status.set(target_intelligence_compact_text(value))

            tree = getattr(self, "target_quest_tree", None)
            if tree is not None:
                previous = tree.selection()
                previous_key = previous[0] if previous else None
                tree.delete(*tree.get_children(""))
                self._target_quest_connections_by_item = {}
                for connection in quest_connections:
                    iid = f"target-quest:{connection.quest_id}:{connection.relation}"
                    state = "tracked" if connection.tracked else connection.profile_status
                    if not state:
                        state = "unknown"
                    tree.insert(
                        "",
                        "end",
                        iid=iid,
                        text=connection.quest_name,
                        values=(connection.relation_label, state),
                    )
                    self._target_quest_connections_by_item[iid] = connection
                    if iid == previous_key:
                        tree.selection_set(iid)
                        tree.focus(iid)

            self._target_intelligence_signature = signature
        self._target_intelligence_value = value

    def _refresh_activity_pathways(self, *, force: bool = False) -> None:
        # Activity Pathways already owns the monitoring-session boundary and refresh
        # cadence. Reuse that one activity pass rather than running a second permanent
        # SQLite polling loop just for the current target.
        current_refresh_pathways(self, force=force)
        _refresh_target_intelligence(self, force=force)

    current_app._build_live = _build_live
    current_app._target_intelligence_view = _target_intelligence_view
    current_app._target_intelligence_navigate = _target_intelligence_navigate
    current_app._target_intelligence_details = _target_intelligence_details
    current_app._selected_target_quest_connection = _selected_target_quest_connection
    current_app._target_intelligence_view_quest = _target_intelligence_view_quest
    current_app._target_intelligence_track_quest = _target_intelligence_track_quest
    current_app._target_intelligence_why_quest = _target_intelligence_why_quest
    current_app._refresh_target_intelligence = _refresh_target_intelligence
    current_app._refresh_activity_pathways = _refresh_activity_pathways
    setattr(current_app, _TARGET_INTELLIGENCE_MARKER, True)
