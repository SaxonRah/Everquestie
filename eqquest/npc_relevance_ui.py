from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .knowledge_map_choices import knowledge_map_choices, knowledge_route_choices
from .npc_relevance import NPCQuestConnection, NPCRelevance, npc_relevance_text, recent_npc_relevance


_NPC_RELEVANCE_MARKER = "_everquestie_npc_relevance_ui"


def install_npc_relevance_ui() -> None:
    """Add exact target/consider quest relevance to the Live activity surface."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _NPC_RELEVANCE_MARKER, False):
        return

    current_build_live = current_app._build_live
    current_refresh_pathways = current_app._refresh_activity_pathways

    def _build_live(self) -> None:
        current_build_live(self)

        panel = ttk.LabelFrame(self.live_tab, text="Recent NPC Relevance", padding=6)
        panel.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        panel.columnconfigure(0, weight=1)

        self.npc_relevance_status = tk.StringVar(
            value=(
                "Start monitoring to see source-backed quest connections for NPCs you target or consider."
            )
        )
        ttk.Label(
            panel,
            textvariable=self.npc_relevance_status,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        self.npc_relevance_tree = ttk.Treeview(
            panel,
            columns=("quest", "connection", "observed"),
            show="tree headings",
            selectmode="browse",
            height=4,
        )
        self.npc_relevance_tree.heading("#0", text="Observed NPC")
        self.npc_relevance_tree.heading("quest", text="Known quest")
        self.npc_relevance_tree.heading("connection", text="Connection")
        self.npc_relevance_tree.heading("observed", text="Session signal")
        self.npc_relevance_tree.column("#0", width=250, minwidth=150, stretch=True)
        self.npc_relevance_tree.column("quest", width=300, minwidth=180, stretch=True)
        self.npc_relevance_tree.column("connection", width=145, minwidth=115, stretch=False)
        self.npc_relevance_tree.column("observed", width=150, minwidth=110, stretch=False)
        self.npc_relevance_tree.grid(row=1, column=0, sticky="ew")
        scroll = ttk.Scrollbar(panel, orient="vertical", command=self.npc_relevance_tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.npc_relevance_tree.configure(yscrollcommand=scroll.set)
        self.npc_relevance_tree.bind(
            "<Double-1>", lambda _event: self._npc_relevance_view_npc()
        )

        buttons = ttk.Frame(panel)
        buttons.grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Button(buttons, text="View NPC", command=self._npc_relevance_view_npc).pack(side="left")
        ttk.Button(buttons, text="View quest", command=self._npc_relevance_view_quest).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(buttons, text="Track quest", command=self._npc_relevance_track_quest).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(buttons, text="Navigate NPC", command=self._npc_relevance_navigate_npc).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(buttons, text="Why relevant?", command=self._npc_relevance_explain).pack(
            side="left", padx=(6, 0)
        )

        self._npc_relevance_by_item: dict[str, tuple[NPCRelevance, NPCQuestConnection]] = {}
        self._npc_relevance_signature = None

    def _selected_npc_relevance(self) -> tuple[NPCRelevance, NPCQuestConnection] | None:
        tree = getattr(self, "npc_relevance_tree", None)
        if tree is None:
            return None
        selected = tree.selection()
        if not selected:
            return None
        return getattr(self, "_npc_relevance_by_item", {}).get(selected[0])

    def _open_exact(self, entity_id: int) -> None:
        opener = getattr(self, "_open_knowledge_entity_exact", None)
        if callable(opener):
            opener(int(entity_id))
        else:
            self._map_entity_selected(int(entity_id))

    def _npc_relevance_view_npc(self) -> None:
        selected = _selected_npc_relevance(self)
        if selected is None:
            return
        npc, _connection = selected
        _open_exact(self, npc.npc_id)

    def _npc_relevance_view_quest(self) -> None:
        selected = _selected_npc_relevance(self)
        if selected is None:
            return
        _npc, connection = selected
        _open_exact(self, connection.quest_id)

    def _npc_relevance_track_quest(self) -> None:
        selected = _selected_npc_relevance(self)
        if selected is None:
            return
        _npc, connection = selected
        if connection.tracked:
            self.status.set(f"{connection.quest_name} is already tracked.")
            return
        self._track_and_reconcile(
            int(connection.quest_id),
            announce="NPC RELEVANCE | tracking selected quest",
        )
        self._refresh_guidance()
        self._refresh_activity_pathways(force=True)

    def _npc_relevance_navigate_npc(self) -> None:
        selected = _selected_npc_relevance(self)
        if selected is None:
            self.status.set("Select a Recent NPC Relevance row first.")
            return
        npc, _connection = selected
        result = knowledge_map_choices(
            self.db,
            int(npc.npc_id),
            getattr(self.state_model, "current_zone", None),
        )
        if result.ready:
            if len(result.choices) == 1:
                choice = result.choices[0]
            else:
                from .knowledge_location_ui import ask_knowledge_map_choice

                choice = ask_knowledge_map_choice(
                    self,
                    npc.npc_name,
                    result.current_zone_name,
                    result.choices,
                )
                if choice is None:
                    self.status.set("NPC map location selection cancelled.")
                    return
            self._focus_navigation_map_target(
                choice.zone_name,
                choice.x,
                choice.y,
                choice.z,
                choice.map_label,
            )
            self.status.set(f"Mapped {npc.npc_name} from safe canonical location evidence.")
            return

        routes = knowledge_route_choices(result)
        if routes:
            if len(routes) == 1:
                choice = routes[0]
            else:
                from .knowledge_location_ui import ask_knowledge_route_choice

                choice = ask_knowledge_route_choice(
                    self,
                    npc.npc_name,
                    result.current_zone_name,
                    routes,
                )
                if choice is None:
                    self.status.set("NPC route selection cancelled.")
                    return
            travel = getattr(self, "travel_tab", None)
            if travel is None or not hasattr(travel, "route_to_zone"):
                self.status.set("Travel routing is not connected in this application surface.")
                return
            self.notebook.select(self.travel_tab)
            routed = bool(self.travel_tab.route_to_zone(choice.zone_name))
            if routed:
                self.status.set(f"Travel route opened to {choice.zone_name} for {npc.npc_name}.")
            else:
                self.status.set(
                    f"No confirmed route to {choice.zone_name} is currently available; see Travel for details."
                )
            return

        self.status.set(result.reason)

    def _npc_relevance_explain(self) -> None:
        selected = _selected_npc_relevance(self)
        if selected is None:
            return
        npc, _connection = selected
        messagebox.showinfo("Recent NPC Relevance", npc_relevance_text(npc))

    def _refresh_npc_relevance(self, *, force: bool = False) -> None:
        tree = getattr(self, "npc_relevance_tree", None)
        status = getattr(self, "npc_relevance_status", None)
        if tree is None or status is None:
            return

        boundary = int(getattr(self, "_activity_session_start_event_id", 0) or 0)
        rows = recent_npc_relevance(self.db, boundary, limit_npcs=10)
        signature = tuple(
            (
                npc.npc_id,
                npc.targeted_count,
                npc.considered_count,
                npc.last_event_id,
                tuple(
                    (
                        connection.quest_id,
                        connection.relation,
                        connection.tracked,
                        connection.profile_status,
                    )
                    for connection in npc.connections
                ),
            )
            for npc in rows
        )
        if force or signature != getattr(self, "_npc_relevance_signature", None):
            previous = tree.selection()
            previous_key = previous[0] if previous else None
            tree.delete(*tree.get_children(""))
            self._npc_relevance_by_item = {}
            for npc in rows:
                for connection in npc.connections:
                    iid = f"npc-relevance:{npc.npc_id}:{connection.quest_id}:{connection.relation}"
                    relation = connection.relation_label
                    if connection.tracked:
                        relation += "; tracked"
                    if connection.profile_status not in {"", "available"}:
                        relation += f"; {connection.profile_status}"
                    tree.insert(
                        "",
                        "end",
                        iid=iid,
                        text=npc.npc_name,
                        values=(connection.quest_name, relation, npc.observation_text),
                    )
                    self._npc_relevance_by_item[iid] = (npc, connection)
                    if iid == previous_key:
                        tree.selection_set(iid)
                        tree.focus(iid)
            self._npc_relevance_signature = signature

        monitoring = getattr(self, "tailer", None) is not None
        if rows:
            quest_ids = {
                connection.quest_id
                for npc in rows
                for connection in npc.connections
            }
            prefix = "Watching NPC interactions" if monitoring else "Last monitoring session"
            status.set(
                f"{prefix}: {len(rows)} observed NPC(s) have {len(quest_ids)} known "
                "profile-compatible quest connection(s). Exact target/consider signals only."
            )
        elif monitoring:
            status.set(
                "Watching target/consider events. NPC relevance appears only for exact canonical NPCs "
                "with reviewed source-backed quest relationships."
            )
        else:
            status.set(
                "Start monitoring to see source-backed quest connections for NPCs you target or consider."
            )

    def _refresh_activity_pathways(self, *, force: bool = False) -> None:
        current_refresh_pathways(self, force=force)
        _refresh_npc_relevance(self, force=force)

    current_app._build_live = _build_live
    current_app._selected_npc_relevance = _selected_npc_relevance
    current_app._npc_relevance_view_npc = _npc_relevance_view_npc
    current_app._npc_relevance_view_quest = _npc_relevance_view_quest
    current_app._npc_relevance_track_quest = _npc_relevance_track_quest
    current_app._npc_relevance_navigate_npc = _npc_relevance_navigate_npc
    current_app._npc_relevance_explain = _npc_relevance_explain
    current_app._refresh_npc_relevance = _refresh_npc_relevance
    current_app._refresh_activity_pathways = _refresh_activity_pathways
    setattr(current_app, _NPC_RELEVANCE_MARKER, True)
