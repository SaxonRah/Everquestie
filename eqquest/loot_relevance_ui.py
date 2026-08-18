from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .knowledge_location_ui import ask_knowledge_map_choice, ask_knowledge_route_choice
from .live_composition import chain_activity_pathways_refresh
from .live_navigation import handoff_to_travel
from .loot_relevance import LootQuestUse, LootRelevance, loot_relevance_text, recent_loot_relevance
from .loot_source_navigation import loot_source_navigation
from .loot_turn_in_navigation import loot_turn_in_navigation


_LOOT_RELEVANCE_MARKER = "_everquestie_loot_relevance_ui"


def install_loot_relevance_ui() -> None:
    """Add source-backed quest relevance for recently looted items to Live."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _LOOT_RELEVANCE_MARKER, False):
        return

    current_build_live = current_app._build_live

    def _build_live(self) -> None:
        current_build_live(self)

        panel = ttk.LabelFrame(self.live_tab, text="Recent Loot Relevance", padding=6)
        panel.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        panel.columnconfigure(0, weight=1)

        self.loot_relevance_status = tk.StringVar(
            value=(
                "Start monitoring to see source-backed quest uses for items you loot. "
                "No displayed use never means an item is automatically vendor trash."
            )
        )
        ttk.Label(
            panel,
            textvariable=self.loot_relevance_status,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        self.loot_relevance_tree = ttk.Treeview(
            panel,
            columns=("quest", "use", "observed"),
            show="tree headings",
            selectmode="browse",
            height=4,
        )
        self.loot_relevance_tree.heading("#0", text="Looted item")
        self.loot_relevance_tree.heading("quest", text="Known quest use")
        self.loot_relevance_tree.heading("use", text="Relationship")
        self.loot_relevance_tree.heading("observed", text="Session")
        self.loot_relevance_tree.column("#0", width=260, minwidth=160, stretch=True)
        self.loot_relevance_tree.column("quest", width=300, minwidth=180, stretch=True)
        self.loot_relevance_tree.column("use", width=150, minwidth=120, stretch=False)
        self.loot_relevance_tree.column(
            "observed", width=75, minwidth=65, stretch=False, anchor="center"
        )
        self.loot_relevance_tree.grid(row=1, column=0, sticky="ew")
        scroll = ttk.Scrollbar(
            panel,
            orient="vertical",
            command=self.loot_relevance_tree.yview,
        )
        scroll.grid(row=1, column=1, sticky="ns")
        self.loot_relevance_tree.configure(yscrollcommand=scroll.set)
        self.loot_relevance_tree.bind(
            "<Double-1>", lambda _event: self._loot_relevance_view_item()
        )

        buttons = ttk.Frame(panel)
        buttons.grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Button(
            buttons,
            text="View item",
            command=self._loot_relevance_view_item,
        ).pack(side="left")
        ttk.Button(
            buttons,
            text="View quest",
            command=self._loot_relevance_view_quest,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Track quest",
            command=self._loot_relevance_track_quest,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Find source",
            command=self._loot_relevance_find_source,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Navigate turn-in",
            command=self._loot_relevance_navigate_turn_in,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Why relevant?",
            command=self._loot_relevance_explain,
        ).pack(side="left", padx=(6, 0))

        self._loot_relevance_by_item: dict[str, tuple[LootRelevance, LootQuestUse]] = {}
        self._loot_relevance_signature = None

    def _selected_loot_relevance(self) -> tuple[LootRelevance, LootQuestUse] | None:
        tree = getattr(self, "loot_relevance_tree", None)
        if tree is None:
            return None
        selected = tree.selection()
        if not selected:
            return None
        return getattr(self, "_loot_relevance_by_item", {}).get(selected[0])

    def _open_exact(self, entity_id: int) -> None:
        opener = getattr(self, "_open_knowledge_entity_exact", None)
        if callable(opener):
            opener(int(entity_id))
        else:
            self._map_entity_selected(int(entity_id))

    def _loot_relevance_view_item(self) -> None:
        selected = _selected_loot_relevance(self)
        if selected is None:
            return
        item, _use = selected
        _open_exact(self, int(item.item_id))

    def _loot_relevance_view_quest(self) -> None:
        selected = _selected_loot_relevance(self)
        if selected is None:
            return
        _item, use = selected
        _open_exact(self, int(use.quest_id))

    def _loot_relevance_track_quest(self) -> None:
        selected = _selected_loot_relevance(self)
        if selected is None:
            return
        _item, use = selected
        if use.tracked:
            self.status.set(f"{use.quest_name} is already tracked.")
            return
        self._track_and_reconcile(
            int(use.quest_id),
            announce="LOOT RELEVANCE | tracking selected quest",
        )
        self._refresh_guidance()
        self._refresh_activity_pathways(force=True)

    def _loot_relevance_find_source(self) -> None:
        selected = _selected_loot_relevance(self)
        if selected is None:
            self.status.set("Select a Recent Loot Relevance row first.")
            return
        item, _use = selected
        result = loot_source_navigation(
            self.db,
            int(item.item_id),
            self.state_model.current_zone,
        )

        if result.map_ready:
            choice = ask_knowledge_map_choice(
                self,
                result.item_name,
                self.state_model.current_zone or "current zone",
                result.map_choices,
            )
            if choice is None:
                self.status.set("Loot source selection cancelled.")
                return
            self._focus_navigation_map_target(
                choice.zone_name,
                choice.x,
                choice.y,
                choice.z,
                choice.map_label,
            )
            self.status.set(
                f"Mapped reviewed source {choice.location_entity_name} for {result.item_name}."
            )
            return

        if result.route_ready:
            choice = ask_knowledge_route_choice(
                self,
                result.item_name,
                self.state_model.current_zone or "current zone",
                result.route_choices,
            )
            if choice is None:
                self.status.set("Loot source route selection cancelled.")
                return
            routed = handoff_to_travel(self, choice.zone_name)
            if routed is None:
                self.status.set("Travel routing is not connected in this application surface.")
                return
            if routed:
                self.status.set(
                    f"Travel route opened to {choice.zone_name} for {choice.route_label}."
                )
            else:
                self.status.set(
                    f"No confirmed route to {choice.zone_name} is currently available; see Travel for details."
                )
            return

        self.status.set(result.reason)

    def _loot_relevance_navigate_turn_in(self) -> None:
        selected = _selected_loot_relevance(self)
        if selected is None:
            self.status.set("Select a Recent Loot Relevance row first.")
            return
        _item, use = selected
        if use.relation != "objective_turn_in_item":
            self.status.set(
                f"{use.quest_name}: the selected relationship is {use.relation_label}, not an explicit turn-in item."
            )
            return

        result = loot_turn_in_navigation(
            self.db,
            int(use.quest_id),
            self.state_model.current_zone,
        )
        if result.map_ready:
            choice = ask_knowledge_map_choice(
                self,
                result.quest_name,
                self.state_model.current_zone or "current zone",
                result.map_choices,
            )
            if choice is None:
                self.status.set("Turn-in location selection cancelled.")
                return
            self._focus_navigation_map_target(
                choice.zone_name,
                choice.x,
                choice.y,
                choice.z,
                choice.map_label,
            )
            self.status.set(
                f"Mapped explicit turn-in contact {choice.location_entity_name} for {result.quest_name}."
            )
            return

        if result.route_ready:
            choice = ask_knowledge_route_choice(
                self,
                result.quest_name,
                self.state_model.current_zone or "current zone",
                result.route_choices,
            )
            if choice is None:
                self.status.set("Turn-in route selection cancelled.")
                return
            routed = handoff_to_travel(self, choice.zone_name)
            if routed is None:
                self.status.set("Travel routing is not connected in this application surface.")
                return
            if routed:
                self.status.set(
                    f"Travel route opened to {choice.zone_name} for {choice.route_label}."
                )
            else:
                self.status.set(
                    f"No confirmed route to {choice.zone_name} is currently available; see Travel for details."
                )
            return

        self.status.set(result.reason)

    def _loot_relevance_explain(self) -> None:
        selected = _selected_loot_relevance(self)
        if selected is None:
            return
        item, _use = selected
        messagebox.showinfo("Recent Loot Relevance", loot_relevance_text(item))

    def _refresh_loot_relevance(self, *, force: bool = False) -> None:
        tree = getattr(self, "loot_relevance_tree", None)
        status = getattr(self, "loot_relevance_status", None)
        if tree is None or status is None:
            return

        boundary = int(getattr(self, "_activity_session_start_event_id", 0) or 0)
        rows = recent_loot_relevance(self.db, boundary, limit_items=10)
        signature = tuple(
            (
                item.item_id,
                item.observed_count,
                item.last_event_id,
                tuple(
                    (
                        use.quest_id,
                        use.relation,
                        use.quantity,
                        use.tracked,
                        use.profile_status,
                    )
                    for use in item.uses
                ),
            )
            for item in rows
        )
        if force or signature != getattr(self, "_loot_relevance_signature", None):
            previous = tree.selection()
            previous_key = previous[0] if previous else None
            tree.delete(*tree.get_children(""))
            self._loot_relevance_by_item = {}

            for item in rows:
                for use in item.uses:
                    iid = f"loot-relevance:{item.item_id}:{use.quest_id}:{use.relation}"
                    relationship = use.relation_label
                    if use.quantity:
                        relationship += f" x{use.quantity}"
                    if use.tracked:
                        relationship += "; tracked"
                    if use.profile_status not in {"", "available"}:
                        relationship += f"; {use.profile_status}"
                    tree.insert(
                        "",
                        "end",
                        iid=iid,
                        text=item.item_name,
                        values=(
                            use.quest_name,
                            relationship,
                            f"x{item.observed_count}",
                        ),
                    )
                    self._loot_relevance_by_item[iid] = (item, use)
                    if iid == previous_key:
                        tree.selection_set(iid)
                        tree.focus(iid)
            self._loot_relevance_signature = signature

        monitoring = getattr(self, "tailer", None) is not None
        if rows:
            quest_ids = {
                int(use.quest_id)
                for item in rows
                for use in item.uses
            }
            prefix = "Watching live loot" if monitoring else "Last monitoring session"
            status.set(
                f"{prefix}: {len(rows)} looted item(s) have {len(quest_ids)} known "
                "profile-compatible quest connection(s). Exact source-backed relationships only."
            )
        elif monitoring:
            status.set(
                "Watching live loot. Relevant items appear only when an exact canonical item "
                "has a reviewed source-backed quest relationship. No match does not mean vendor trash."
            )
        else:
            status.set(
                "Start monitoring to see source-backed quest uses for items you loot. "
                "No displayed use never means an item is automatically vendor trash."
            )

    current_app._build_live = _build_live
    current_app._selected_loot_relevance = _selected_loot_relevance
    current_app._loot_relevance_view_item = _loot_relevance_view_item
    current_app._loot_relevance_view_quest = _loot_relevance_view_quest
    current_app._loot_relevance_track_quest = _loot_relevance_track_quest
    current_app._loot_relevance_find_source = _loot_relevance_find_source
    current_app._loot_relevance_navigate_turn_in = _loot_relevance_navigate_turn_in
    current_app._loot_relevance_explain = _loot_relevance_explain
    current_app._refresh_loot_relevance = _refresh_loot_relevance
    chain_activity_pathways_refresh(current_app, _refresh_loot_relevance)
    setattr(current_app, _LOOT_RELEVANCE_MARKER, True)